from __future__ import annotations

import base64
import hashlib
import time
import uuid
from types import SimpleNamespace
from typing import Any

from .app_protocol import (
    DELIVERY_WINDOW_SECONDS,
    GROUP_KINDS,
    MAX_TEXT_BYTES,
    build_fields,
    conversation_id,
)
from .errors import ContactNotApproved, MeshChatError, ValidationError
from .group_protocol import (
    MAX_GROUP_MEMBERS,
    GroupManifestMemberInput,
    create_group_genesis,
    create_group_invitation,
    create_group_join_statement,
    create_group_leave_request,
    create_group_manifest,
    verify_group_invitation,
    verify_group_join_statement,
    verify_group_leave_request,
    verify_group_manifest,
)
from .models import (
    DeliveryState,
    GroupPostingPolicy,
    GroupRole,
    GroupStatus,
    MessageKind,
    TrustState,
)


ACTIVE_TRUST = {TrustState.APPROVED.value, TrustState.VERIFIED.value}
FINAL_DELIVERY_STATES = {
    DeliveryState.DELIVERED.value,
    DeliveryState.EXPIRED.value,
    DeliveryState.FAILED.value,
}
GROUP_RETRY_BASE_SECONDS = 3
GROUP_RETRY_MAX_SECONDS = 60
MAX_PENDING_GROUP_INVITATIONS = 32
MAX_PENDING_GROUP_INVITATIONS_PER_OWNER = 8
MAX_PENDING_GROUP_MANIFESTS = 32


def _new_id() -> str:
    return str(uuid.uuid4())


def _stable_id(prefix: bytes, value: str) -> str:
    return str(uuid.UUID(bytes=hashlib.sha256(prefix + value.encode("utf-8")).digest()[:16]))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value)
    except Exception as exc:
        raise ValidationError("Stored group identity encoding is invalid") from exc


def _member_record(member: Any, *, epoch: int) -> dict[str, Any]:
    card = member.card
    return {
        "display_name": card.display_name,
        "public_identity": _b64(card.public_identity),
        "identity_hash": card.identity_hash.hex(),
        "destination_hash": card.destination_hash.hex(),
        "fingerprint": card.fingerprint,
        "connection_hints": [dict(hint) for hint in card.hints],
        "member_card": card.serialized,
        "role": member.role.value,
        "status": "active",
        "joined_epoch": epoch,
    }


def _pending_member(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "contact_id": contact["id"],
        "display_name": contact["display_name"],
        "public_identity": contact["public_identity"],
        "identity_hash": contact["identity_hash"],
        "destination_hash": contact["destination_hash"],
        "fingerprint": contact["fingerprint"],
        "connection_hints": [dict(hint) for hint in contact.get("connection_hints", [])[:2]],
        "role": GroupRole.MEMBER.value,
        "status": "invited",
    }


class GroupServiceMixin:
    """Additive small-group coordination over individual LXMF destinations.

    This mixin deliberately owns no transport or cryptography.  It persists a
    logical group message and one recipient leg per member, while the existing
    network adapter continues to enforce native LXMF signatures, identity
    binding and recipient ratchets for every leg.
    """

    def _group_hints(self) -> list[dict[str, Any]]:
        network = getattr(self, "network", None)
        if network is None:
            return []
        return [dict(hint) for hint in network.invitation_hints()[:2]]

    def _require_group(self, group_id: str) -> dict[str, Any]:
        if not isinstance(group_id, str):
            raise ValidationError("Group ID is invalid")
        group = self.store.get("group", group_id)
        if group is None:
            raise ValidationError("Group does not exist")
        return group

    def _group_member(
        self, group: dict[str, Any], destination: str, *, active_only: bool = True
    ) -> dict[str, Any] | None:
        for member in group.get("members", []):
            if member.get("destination_hash") != destination:
                continue
            if active_only and member.get("status") != "active":
                return None
            return member
        return None

    def _local_group_member(self, group: dict[str, Any]) -> dict[str, Any] | None:
        profile = self._require_profile()
        return self._group_member(group, profile["destination_hash"], active_only=False)

    def _remember_group_members(self, group: dict[str, Any]) -> None:
        network = getattr(self, "network", None)
        if network is None:
            return
        local_destination = self._require_profile()["destination_hash"]
        for member in group.get("members", []):
            if (
                member.get("status") != "active"
                or member.get("destination_hash") == local_destination
                or not member.get("public_identity")
            ):
                continue
            try:
                network.remember_contact(
                    _unb64(member["public_identity"]),
                    bytes.fromhex(member["destination_hash"]),
                )
            except Exception:
                # The signed manifest remains authoritative.  A malformed or
                # unavailable route is retried later and never weakens trust.
                continue

    def _manifest_records(self, group_id: str) -> list[dict[str, Any]]:
        records = [
            record
            for record in self.store.list("group_manifest")
            if record.get("group_id") == group_id
        ]
        records.sort(key=lambda record: int(record["epoch"]))
        return records

    def _manifest_chain_deliveries(
        self,
        group: dict[str, Any],
        recipient: dict[str, Any],
        *,
        after_epoch: int,
        extra_manifest: Any | None = None,
    ) -> list[dict[str, Any]]:
        records = self._manifest_records(group["id"])
        if extra_manifest is not None and not any(
            record.get("digest") == extra_manifest.digest for record in records
        ):
            records.append(
                {
                    "group_id": group["id"],
                    "epoch": extra_manifest.epoch,
                    "digest": extra_manifest.digest,
                    "serialized": extra_manifest.serialized,
                }
            )
        records.sort(key=lambda record: int(record["epoch"]))
        return [
            self._delivery_record(
                group=group,
                recipient=recipient,
                kind=MessageKind.GROUP_MANIFEST,
                document=record["serialized"],
                group_message_id=_new_id(),
                epoch=int(record["epoch"]),
                manifest_hash=record["digest"],
            )
            for record in records
            if int(record["epoch"]) > after_epoch
        ]

    def _cancel_obsolete_group_chat_records(
        self, group_id: str, new_epoch: int
    ) -> list[tuple[str, str, dict[str, Any]]]:
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        for delivery in self.store.list("group_delivery"):
            if (
                delivery.get("group_id") != group_id
                or delivery.get("kind")
                not in {
                    MessageKind.GROUP_CHAT.value,
                    MessageKind.GROUP_REACTION.value,
                }
                or delivery.get("state") in FINAL_DELIVERY_STATES
                or int(delivery.get("group_epoch", -1)) >= new_epoch
            ):
                continue
            if delivery.get("kind") == MessageKind.GROUP_REACTION.value:
                # A reaction is still meaningful after a roster update for
                # recipients who remain active and were entitled to the target
                # message.  It is rebound lazily to the new epoch before its
                # next retry; new members never receive historical reactions.
                continue
            delivery["state"] = DeliveryState.FAILED.value
            delivery["failure_code"] = "membership_changed"
            delivery["failed_at"] = now
            records.append(("group_delivery", delivery["id"], delivery))
        return records

    def _complete_group_control_records(
        self,
        group_id: str,
        kinds: set[MessageKind],
        *,
        recipient_destination: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        for delivery in self.store.list("group_delivery"):
            if (
                delivery.get("group_id") != group_id
                or delivery.get("kind") not in {kind.value for kind in kinds}
                or delivery.get("state") in FINAL_DELIVERY_STATES
                or (
                    recipient_destination is not None
                    and delivery.get("recipient_destination") != recipient_destination
                )
            ):
                continue
            delivery["state"] = DeliveryState.DELIVERED.value
            delivery["delivered_at"] = now
            delivery.pop("failure_code", None)
            records.append(("group_delivery", delivery["id"], delivery))
        return records

    def _fail_group_delivery(
        self, delivery: dict[str, Any], code: str
    ) -> None:
        if self._is_reaction_only_delivery(delivery):
            self.store.delete("group_delivery", delivery["id"])
            return
        delivery["state"] = DeliveryState.FAILED.value
        delivery["failure_code"] = code
        delivery["failed_at"] = time.time()
        self.store.put("group_delivery", delivery["id"], delivery)

    @staticmethod
    def _is_reaction_only_delivery(delivery: dict[str, Any]) -> bool:
        return bool(
            delivery.get("kind") == MessageKind.GROUP_REACTION.value
            or (
                delivery.get("kind") == MessageKind.GROUP_RECEIPT.value
                and delivery.get("reaction_receipt") is True
            )
        )

    def _group_chat_invalid_reason(self, delivery: dict[str, Any]) -> str | None:
        if delivery.get("kind") not in {
            MessageKind.GROUP_CHAT.value,
            MessageKind.GROUP_REACTION.value,
        }:
            return None
        group = self.store.get("group", delivery["group_id"])
        if group is None or group.get("status") != "active":
            return "membership_changed"
        recipient = self._group_member(
            group, delivery.get("recipient_destination", "")
        )
        if recipient is None:
            return "membership_changed"
        if delivery.get("kind") == MessageKind.GROUP_REACTION.value:
            target = self.store.get(
                "group_message", delivery.get("reaction_for", "")
            )
            if target is None:
                return "reaction_target_unavailable"
            try:
                entitled = self._reaction_target_destinations(group, target)
            except ValidationError:
                return "reaction_target_invalid"
            if recipient.get("destination_hash") not in entitled:
                return "membership_changed"
            if int(delivery.get("group_epoch", -1)) != int(group.get("epoch", -2)):
                delivery["group_epoch"] = int(group["epoch"])
                delivery["group_manifest_hash"] = group["manifest_hash"]
                delivery["recipient_display_name"] = recipient.get(
                    "display_name", "Member"
                )
                delivery["recipient_public_identity"] = recipient[
                    "public_identity"
                ]
                delivery["recipient_hints"] = [
                    dict(hint)
                    for hint in recipient.get("connection_hints", [])[:2]
                ]
                delivery["state"] = DeliveryState.QUEUED.value
                # The caller already decided this record is due. Keep it due
                # after rebinding instead of comparing a newly-sampled clock
                # against the earlier timestamp captured by the send frame.
                delivery["next_attempt_at"] = 0
                delivery.pop("native_message_id", None)
                delivery.pop("failure_code", None)
                self.store.put("group_delivery", delivery["id"], delivery)
            return None
        if int(delivery.get("group_epoch", -1)) != int(group.get("epoch", -2)):
            return "membership_changed"
        return None

    def _apply_group_manifest(
        self,
        group: dict[str, Any],
        manifest: Any,
        *,
        keep_pending: bool,
    ) -> dict[str, Any]:
        pending = []
        if keep_pending:
            active_destinations = {
                member.card.destination_hash.hex() for member in manifest.members
            }
            pending = [
                dict(member)
                for member in group.get("members", [])
                if member.get("status") == "invited"
                and member.get("destination_hash") not in active_destinations
            ]
        group["title"] = manifest.title
        group["posting_policy"] = manifest.posting_policy.value
        group["epoch"] = manifest.epoch
        group["manifest_hash"] = manifest.digest
        group["manifest"] = manifest.serialized
        group["members"] = [
            _member_record(member, epoch=manifest.epoch) for member in manifest.members
        ] + pending
        group["updated_at"] = time.time()
        local = self._local_group_member(group)
        if manifest.status == GroupStatus.CLOSED:
            group["status"] = "closed"
            group["local_role"] = None if local is None else local["role"]
            group["leave_pending"] = False
        elif local is None or local.get("status") != "active":
            group["status"] = "removed"
            group["local_role"] = None
            group["leave_pending"] = False
        else:
            group["status"] = "active"
            group["local_role"] = local["role"]
        return group

    def _delivery_record(
        self,
        *,
        group: dict[str, Any],
        recipient: dict[str, Any],
        kind: MessageKind,
        text: str = "",
        document: str | None = None,
        group_message_id: str | None = None,
        sender_sequence: int | None = None,
        receipt_for: str | None = None,
        epoch: int | None = None,
        manifest_hash: str | None = None,
        reaction_for: str | None = None,
        reaction_emoji: str | None = None,
        reaction_active: bool | None = None,
        reaction_revision: int | None = None,
    ) -> dict[str, Any]:
        profile = self._require_profile()
        now = time.time()
        return {
            "id": _new_id(),
            "group_id": group["id"],
            "recipient_destination": recipient["destination_hash"],
            "recipient_display_name": recipient.get("display_name", "Member"),
            "recipient_public_identity": recipient["public_identity"],
            "recipient_hints": [
                dict(hint) for hint in recipient.get("connection_hints", [])[:2]
            ],
            "conversation_id": conversation_id(
                bytes.fromhex(profile["destination_hash"]),
                bytes.fromhex(recipient["destination_hash"]),
            ),
            "kind": kind.value,
            "text": text,
            "group_epoch": int(group["epoch"] if epoch is None else epoch),
            "group_manifest_hash": (
                group["manifest_hash"] if manifest_hash is None else manifest_hash
            ),
            "group_document": document,
            "group_message_id": group_message_id,
            "sender_sequence": sender_sequence,
            "receipt_for": receipt_for,
            "reaction_for": reaction_for,
            "reaction_emoji": reaction_emoji,
            "reaction_active": reaction_active,
            "reaction_revision": reaction_revision,
            "state": DeliveryState.QUEUED.value,
            "attempt_count": 0,
            "next_attempt_at": now,
            "created_at": now,
            "expires_at": now + DELIVERY_WINDOW_SECONDS,
        }

    def _attempt_group_delivery(self, delivery_id: str) -> None:
        delivery = self.store.get("group_delivery", delivery_id)
        if delivery is None or delivery["state"] in FINAL_DELIVERY_STATES:
            return
        now = time.time()
        if float(delivery["expires_at"]) <= now:
            if self._is_reaction_only_delivery(delivery):
                self.store.delete("group_delivery", delivery_id)
                return
            delivery["state"] = DeliveryState.EXPIRED.value
            delivery["expired_at"] = now
            self.store.put("group_delivery", delivery_id, delivery)
            return
        invalid_reason = self._group_chat_invalid_reason(delivery)
        if invalid_reason is not None:
            self._fail_group_delivery(delivery, invalid_reason)
            return
        if float(delivery.get("next_attempt_at", 0)) > now:
            return
        network = getattr(self, "network", None)
        if network is None:
            return
        hints = delivery.get("recipient_hints", [])
        if hints and any(hint not in self.settings.tcp_clients for hint in hints):
            self._apply_contact_hints({"connection_hints": hints})
        destination = bytes.fromhex(delivery["recipient_destination"])
        try:
            network.remember_contact(
                _unb64(delivery["recipient_public_identity"]), destination
            )
        except Exception:
            self._fail_group_delivery(delivery, "identity_binding_invalid")
            return
        if not network.recipient_ready(destination):
            delivery["state"] = DeliveryState.WAITING_FOR_KEYS.value
            delivery["next_attempt_at"] = now + GROUP_RETRY_BASE_SECONDS
            self.store.put("group_delivery", delivery_id, delivery)
            network.request_path(destination)
            return
        propagated = bool(self.settings.approved_propagation_nodes) and not network.path_known(
            destination
        )
        kind = MessageKind(delivery["kind"])
        fields = build_fields(
            kind=kind,
            logical_id=delivery["id"],
            conversation=delivery["conversation_id"],
            expires_at=int(delivery["expires_at"]),
            receipt_for=delivery.get("receipt_for"),
            group_id=delivery["group_id"],
            group_epoch=int(delivery["group_epoch"]),
            group_manifest_hash=delivery["group_manifest_hash"],
            sender_sequence=delivery.get("sender_sequence"),
            group_document=delivery.get("group_document"),
            group_message_id=delivery.get("group_message_id"),
            reaction_for=delivery.get("reaction_for"),
            reaction_emoji=delivery.get("reaction_emoji"),
            reaction_active=delivery.get("reaction_active"),
            reaction_revision=delivery.get("reaction_revision"),
        )
        attempts = int(delivery.get("attempt_count", 0)) + 1
        delay = min(
            GROUP_RETRY_MAX_SECONDS,
            GROUP_RETRY_BASE_SECONDS * (2 ** min(attempts - 1, 5)),
        )
        delivery["attempt_count"] = attempts
        delivery["last_attempt_at"] = now
        delivery["next_attempt_at"] = now + delay
        delivery["state"] = DeliveryState.SENDING.value
        self.store.put("group_delivery", delivery_id, delivery)
        try:
            native_id = network.send_with_fields(
                logical_id=delivery["id"],
                recipient_public_key=_unb64(delivery["recipient_public_identity"]),
                recipient_destination=destination,
                text=delivery["text"],
                fields=fields,
                propagated=propagated,
            )
            current = self.store.get("group_delivery", delivery_id)
            if current is not None and current["state"] not in FINAL_DELIVERY_STATES:
                current["native_message_id"] = native_id
                self.store.put("group_delivery", delivery_id, current)
        except MeshChatError as exc:
            current = self.store.get("group_delivery", delivery_id)
            if current is None:
                return
            if current["state"] in FINAL_DELIVERY_STATES:
                return
            current["state"] = (
                DeliveryState.WAITING_FOR_KEYS.value
                if exc.code == "recipient_keys_unavailable"
                else DeliveryState.QUEUED.value
            )
            current["failure_code"] = "transport_unavailable"
            self.store.put("group_delivery", delivery_id, current)
        except Exception:
            current = self.store.get("group_delivery", delivery_id)
            if current is None:
                return
            if current["state"] in FINAL_DELIVERY_STATES:
                return
            current["state"] = DeliveryState.QUEUED.value
            current["failure_code"] = "transport_error"
            self.store.put("group_delivery", delivery_id, current)

    def _on_group_native_status(
        self, logical_id: str, state: DeliveryState, native_id: str | None
    ) -> bool:
        delivery = self.store.get("group_delivery", logical_id)
        if delivery is None:
            return False
        if delivery["state"] in FINAL_DELIVERY_STATES:
            if self._is_reaction_only_delivery(delivery):
                self.store.delete("group_delivery", logical_id)
            return True
        if delivery.get("kind") == MessageKind.GROUP_REACTION.value:
            group = self.store.get("group", delivery.get("group_id", ""))
            if (
                group is None
                or int(delivery.get("group_epoch", -1))
                != int(group.get("epoch", -2))
            ):
                # Evidence for an old-epoch attempt cannot complete the
                # reaction.  The retry path will rebind it to the current
                # signed manifest for still-entitled recipients.
                return True
        if (
            state in {DeliveryState.FAILED, DeliveryState.EXPIRED}
            and self._is_reaction_only_delivery(delivery)
        ):
            self.store.delete("group_delivery", logical_id)
            self._changed()
            return True
        if (
            native_id
            and delivery.get("native_message_id")
            and delivery["native_message_id"] != native_id
        ):
            # Retries reuse the durable application ID but have distinct LXMF
            # hashes. A late callback from an older attempt cannot overwrite
            # evidence for the current attempt.
            return True
        if (
            state
            in {
                DeliveryState.RECEIVED_BY_ENDPOINT,
                DeliveryState.DELIVERED,
            }
            and (
                delivery.get("kind") == MessageKind.GROUP_REACTION.value
                or (
                    delivery.get("kind") == MessageKind.GROUP_RECEIPT.value
                    and delivery.get("reaction_receipt") is True
                )
            )
        ):
            self.store.delete("group_delivery", logical_id)
            self._changed()
            return True
        if (
            delivery.get("kind")
            in {
                MessageKind.GROUP_RECEIPT.value,
                MessageKind.GROUP_REACTION.value,
            }
            and state
            in {
                DeliveryState.RECEIVED_BY_ENDPOINT,
                DeliveryState.DELIVERED,
            }
        ):
            delivery["state"] = DeliveryState.DELIVERED.value
            delivery["delivered_at"] = time.time()
        else:
            delivery["state"] = state.value
        if native_id:
            delivery["native_message_id"] = native_id
        self.store.put("group_delivery", logical_id, delivery)
        self._changed()
        return True

    def create_group(
        self, title: str, member_ids: list[str], posting_policy: str
    ) -> dict[str, Any]:
        profile = self._require_profile()
        identity = getattr(self, "_identity", None)
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        try:
            policy = GroupPostingPolicy(posting_policy)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Group posting policy is invalid") from exc
        if not isinstance(member_ids, list) or not member_ids:
            raise ValidationError("Choose at least one group member")
        if any(not isinstance(value, str) for value in member_ids) or len(set(member_ids)) != len(
            member_ids
        ):
            raise ValidationError("Group members are invalid")
        if len(member_ids) + 1 > MAX_GROUP_MEMBERS:
            raise ValidationError(f"Groups support at most {MAX_GROUP_MEMBERS} members")
        contacts = [self._require_contact(contact_id) for contact_id in member_ids]
        if any(contact["trust"] not in ACTIVE_TRUST for contact in contacts):
            raise ContactNotApproved("Every group invitee must be an approved contact")

        genesis_created = create_group_genesis(
            identity,
            title,
            profile["display_name"],
            posting_policy=policy,
            owner_hints=self._group_hints(),
        )
        from .group_protocol import verify_group_genesis

        genesis = verify_group_genesis(genesis_created.serialized)
        manifest_raw = create_group_manifest(
            identity,
            group_id=genesis.group_id,
            epoch=1,
            previous_manifest_hash=genesis.digest,
            title=genesis.title,
            posting_policy=genesis.posting_policy,
            members=[
                GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER)
            ],
        )
        manifest = verify_group_manifest(
            manifest_raw,
            expected_group_id=genesis.group_id,
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
            expected_previous_hash=genesis.digest,
            expected_epoch=1,
        )
        now = time.time()
        group = {
            "id": genesis.group_id,
            "title": manifest.title,
            "owner_destination": profile["destination_hash"],
            "posting_policy": manifest.posting_policy.value,
            "epoch": manifest.epoch,
            "manifest_hash": manifest.digest,
            "genesis": genesis.serialized,
            "manifest": manifest.serialized,
            "status": "active",
            "local_role": GroupRole.OWNER.value,
            "next_sender_sequence": 0,
            "members": [
                _member_record(member, epoch=manifest.epoch) for member in manifest.members
            ]
            + [_pending_member(contact) for contact in contacts],
            "created_at": now,
            "updated_at": now,
        }
        records: list[tuple[str, str, dict[str, Any]]] = [
            ("group", group["id"], group),
            (
                "group_manifest",
                manifest.digest,
                {
                    "group_id": group["id"],
                    "epoch": manifest.epoch,
                    "digest": manifest.digest,
                    "serialized": manifest.serialized,
                },
            ),
        ]
        deliveries: list[dict[str, Any]] = []
        for contact in contacts:
            raw_invite = create_group_invitation(
                identity,
                genesis=genesis.serialized,
                manifest=manifest.serialized,
                invitee_destination=bytes.fromhex(contact["destination_hash"]),
            )
            checked_invite = verify_group_invitation(raw_invite)
            pending_member = self._group_member(
                group, contact["destination_hash"], active_only=False
            )
            if pending_member is not None:
                pending_member["invite_expires_at"] = checked_invite.expires_at
            invite_id = _stable_id(b"mesh-chat:group-invite:", raw_invite)
            invite_record = {
                "id": invite_id,
                "group_id": group["id"],
                "contact_id": contact["id"],
                "invitee_destination": contact["destination_hash"],
                "document": checked_invite.serialized,
                "state": "sent",
                "created_at": checked_invite.created_at,
                "expires_at": checked_invite.expires_at,
            }
            delivery = self._delivery_record(
                group=group,
                recipient=_pending_member(contact),
                kind=MessageKind.GROUP_INVITE,
                document=checked_invite.serialized,
                epoch=checked_invite.group_epoch,
                manifest_hash=checked_invite.manifest_hash,
            )
            records.extend(
                [
                    ("group_sent_invite", invite_id, invite_record),
                    ("group_delivery", delivery["id"], delivery),
                ]
            )
            deliveries.append(delivery)
        self.store.put_many(records)
        for delivery in deliveries:
            self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(self._require_group(group["id"]))

    def accept_group_invitation(self, invitation_id: str) -> dict[str, Any]:
        invitation_record = self.store.get("group_invitation", invitation_id)
        if invitation_record is None or invitation_record.get("state") != "pending":
            raise ValidationError("Group invitation is no longer pending")
        identity = getattr(self, "_identity", None)
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        profile = self._require_profile()
        invite = verify_group_invitation(
            invitation_record["document"],
            expected_invitee_destination=bytes.fromhex(profile["destination_hash"]),
        )
        if self.store.get("group", invite.group_id) is not None:
            raise ValidationError("This group is already known on this device")
        join_raw = create_group_join_statement(
            identity,
            invite,
            profile["display_name"],
            member_hints=self._group_hints(),
        )
        members = [
            _member_record(member, epoch=invite.manifest.epoch)
            for member in invite.manifest.members
        ]
        members.append(
            {
                "display_name": profile["display_name"],
                "public_identity": profile["public_identity"],
                "identity_hash": profile["identity_hash"],
                "destination_hash": profile["destination_hash"],
                "fingerprint": profile["fingerprint"],
                "connection_hints": self._group_hints(),
                "role": GroupRole.MEMBER.value,
                "status": "joining",
            }
        )
        now = time.time()
        group = {
            "id": invite.group_id,
            "title": invite.manifest.title,
            "owner_destination": invite.owner_destination.hex(),
            "posting_policy": invite.manifest.posting_policy.value,
            "epoch": invite.group_epoch,
            "manifest_hash": invite.manifest_hash,
            "genesis": invite.genesis.serialized,
            "manifest": invite.manifest.serialized,
            "status": "joining",
            "local_role": GroupRole.MEMBER.value,
            "next_sender_sequence": 0,
            "members": members,
            "created_at": now,
            "updated_at": now,
        }
        owner = next(
            member
            for member in members
            if member["destination_hash"] == invite.owner_destination.hex()
        )
        delivery = self._delivery_record(
            group=group,
            recipient=owner,
            kind=MessageKind.GROUP_ACCEPT,
            document=join_raw,
            epoch=invite.group_epoch,
            manifest_hash=invite.manifest_hash,
        )
        invitation_record["state"] = "accepted"
        invitation_record["updated_at"] = now
        self.store.put_many(
            [
                ("group", group["id"], group),
                (
                    "group_manifest",
                    invite.manifest.digest,
                    {
                        "group_id": group["id"],
                        "epoch": invite.manifest.epoch,
                        "digest": invite.manifest.digest,
                        "serialized": invite.manifest.serialized,
                    },
                ),
                ("group_invitation", invitation_id, invitation_record),
                ("group_delivery", delivery["id"], delivery),
            ]
        )
        self._remember_group_members(group)
        self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(group)

    def decline_group_invitation(self, invitation_id: str) -> dict[str, Any]:
        invitation = self.store.get("group_invitation", invitation_id)
        if invitation is None or invitation.get("state") != "pending":
            raise ValidationError("Group invitation is no longer pending")
        invitation["state"] = "declined"
        invitation["updated_at"] = time.time()
        self.store.put("group_invitation", invitation_id, invitation)
        self._changed()
        return self._public_invitation(invitation)

    def retry_group_invitation(
        self, group_id: str, destination_hash: str
    ) -> dict[str, Any]:
        """Retry one still-pending invitation immediately using current contact hints."""

        group = self._require_group(group_id)
        profile = self._require_profile()
        if group.get("status") != "active":
            raise ValidationError("Group membership is no longer active")
        if group.get("owner_destination") != profile["destination_hash"]:
            raise ContactNotApproved("Only the group owner can retry invitations")
        member = self._group_member(group, destination_hash, active_only=False)
        if member is None or member.get("status") != "invited":
            raise ValidationError("Group invitation is no longer pending")
        invitation = next(
            (
                item
                for item in self.store.list("group_sent_invite")
                if item.get("group_id") == group_id
                and item.get("invitee_destination") == destination_hash
                and item.get("state") == "sent"
            ),
            None,
        )
        if invitation is None or float(invitation.get("expires_at", 0)) <= time.time():
            raise ValidationError("Group invitation has expired")
        delivery = next(
            (
                item
                for item in reversed(self.store.list("group_delivery"))
                if item.get("group_id") == group_id
                and item.get("kind") == MessageKind.GROUP_INVITE.value
                and item.get("recipient_destination") == destination_hash
            ),
            None,
        )
        if delivery is None:
            raise ValidationError("Group invitation delivery is unavailable")
        if delivery.get("state") == DeliveryState.DELIVERED.value:
            return self._public_group(group)
        contact_id = member.get("contact_id")
        if isinstance(contact_id, str):
            contact = self._require_contact(contact_id)
            if contact.get("destination_hash") != destination_hash:
                raise ValidationError("Group invitation contact binding changed")
            delivery["recipient_public_identity"] = contact["public_identity"]
            delivery["recipient_hints"] = [
                dict(hint) for hint in contact.get("connection_hints", [])[:2]
            ]
        delivery["state"] = DeliveryState.QUEUED.value
        delivery["next_attempt_at"] = time.time()
        delivery.pop("failure_code", None)
        delivery.pop("failed_at", None)
        self.store.put("group_delivery", delivery["id"], delivery)
        self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(group)

    def send_group_message(self, group_id: str, text: str) -> dict[str, Any]:
        group = self._require_group(group_id)
        if group.get("status") != "active":
            raise ContactNotApproved("Group is not active")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Message is empty")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValidationError("Message exceeds the 16 KiB limit")
        local = self._local_group_member(group)
        if local is None or local.get("status") != "active":
            raise ContactNotApproved("Local identity is not an active group member")
        if (
            group["posting_policy"] == GroupPostingPolicy.OWNER_ADMINS.value
            and local.get("role") not in {GroupRole.OWNER.value, GroupRole.ADMIN.value}
        ):
            raise ContactNotApproved("Only the group owner or an admin can post here")
        profile = self._require_profile()
        recipients = [
            member
            for member in group.get("members", [])
            if member.get("status") == "active"
            and member.get("destination_hash") != profile["destination_hash"]
        ]
        if not recipients:
            raise ValidationError("No other active group members can receive this message")
        sequence = int(group.get("next_sender_sequence", 0)) + 1
        group["next_sender_sequence"] = sequence
        group["updated_at"] = time.time()
        message_id = _new_id()
        now = time.time()
        message = {
            "id": message_id,
            "group_id": group["id"],
            "direction": "outbound",
            "sender_destination": profile["destination_hash"],
            "sender_display_name": profile["display_name"],
            "text": text,
            "group_epoch": group["epoch"],
            "group_manifest_hash": group["manifest_hash"],
            "sender_sequence": sequence,
            "created_at": now,
            "expires_at": now + DELIVERY_WINDOW_SECONDS,
        }
        deliveries = [
            self._delivery_record(
                group=group,
                recipient=recipient,
                kind=MessageKind.GROUP_CHAT,
                text=text,
                group_message_id=message_id,
                sender_sequence=sequence,
            )
            for recipient in recipients
        ]
        self.store.put_and_delete(
            [
                ("group", group["id"], group),
                ("group_message", message_id, message),
                *[
                    ("group_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
            ],
            [
                (
                    "conversation_hidden",
                    self._conversation_marker_id("group", group["id"]),
                )
            ],
        )
        for delivery in deliveries:
            self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group_message(message)

    def remove_group_member(self, group_id: str, destination_hash: str) -> dict[str, Any]:
        group = self._require_group(group_id)
        profile = self._require_profile()
        if group.get("status") != "active":
            raise ValidationError("Group membership is no longer active")
        if group.get("owner_destination") != profile["destination_hash"]:
            raise ContactNotApproved("Only the group owner can remove members")
        target = self._group_member(group, destination_hash)
        if target is None or target.get("role") == GroupRole.OWNER.value:
            raise ValidationError("Group member cannot be removed")
        identity = getattr(self, "_identity", None)
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        current = verify_group_manifest(
            group["manifest"],
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
        )
        inputs = [
            GroupManifestMemberInput(member.card.serialized, member.role)
            for member in current.members
            if member.card.destination_hash.hex() != destination_hash
        ]
        raw = create_group_manifest(
            identity,
            group_id=group["id"],
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            title=current.title,
            posting_policy=current.posting_policy,
            members=inputs,
        )
        updated = verify_group_manifest(
            raw,
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
            expected_previous_hash=current.digest,
            expected_epoch=current.epoch + 1,
        )
        group = self._apply_group_manifest(group, updated, keep_pending=True)
        common_id = _new_id()
        recipients = [
            member
            for member in group["members"]
            if member.get("status") == "active"
            and member["destination_hash"] != profile["destination_hash"]
        ] + [target]
        deliveries = [
            self._delivery_record(
                group=group,
                recipient=recipient,
                kind=MessageKind.GROUP_MANIFEST,
                document=updated.serialized,
                group_message_id=common_id,
            )
            for recipient in recipients
        ]
        self.store.put_many(
            [
                ("group", group["id"], group),
                (
                    "group_manifest",
                    updated.digest,
                    {
                        "group_id": group["id"],
                        "epoch": updated.epoch,
                        "digest": updated.digest,
                        "serialized": updated.serialized,
                    },
                ),
                *self._cancel_obsolete_group_chat_records(
                    group["id"], updated.epoch
                ),
                *[
                    ("group_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
            ]
        )
        for delivery in deliveries:
            self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(group)

    def leave_group(self, group_id: str) -> dict[str, Any]:
        group = self._require_group(group_id)
        if group.get("status") != "active":
            raise ValidationError("Group is no longer active")
        profile = self._require_profile()
        if group.get("owner_destination") == profile["destination_hash"]:
            raise ValidationError("The owner must close the group instead")
        identity = getattr(self, "_identity", None)
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = verify_group_manifest(
            group["manifest"],
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(group["owner_destination"]),
        )
        raw = create_group_leave_request(identity, manifest)
        owner = self._group_member(group, group["owner_destination"])
        if owner is None:
            raise ValidationError("Group owner is unavailable")
        delivery = self._delivery_record(
            group=group,
            recipient=owner,
            kind=MessageKind.GROUP_LEAVE_REQUEST,
            document=raw,
        )
        for member in group.get("members", []):
            if member.get("destination_hash") == profile["destination_hash"]:
                member["status"] = "left"
                member["removed_epoch"] = int(group["epoch"]) + 1
        group["status"] = "removed"
        group["local_role"] = None
        group["leave_pending"] = True
        group["updated_at"] = time.time()
        self.store.put_many(
            [
                ("group", group["id"], group),
                ("group_delivery", delivery["id"], delivery),
                *self._cancel_obsolete_group_chat_records(
                    group["id"], int(group["epoch"]) + 1
                ),
            ]
        )
        self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(group)

    def close_group(self, group_id: str) -> dict[str, Any]:
        group = self._require_group(group_id)
        profile = self._require_profile()
        if group.get("owner_destination") != profile["destination_hash"]:
            raise ContactNotApproved("Only the group owner can close the group")
        if group.get("status") != "active":
            raise ValidationError("Group is no longer active")
        identity = getattr(self, "_identity", None)
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        current = verify_group_manifest(
            group["manifest"],
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
        )
        raw = create_group_manifest(
            identity,
            group_id=group["id"],
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            title=current.title,
            posting_policy=current.posting_policy,
            status=GroupStatus.CLOSED,
            members=[
                GroupManifestMemberInput(member.card.serialized, member.role)
                for member in current.members
            ],
        )
        closed = verify_group_manifest(
            raw,
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
            expected_previous_hash=current.digest,
            expected_epoch=current.epoch + 1,
        )
        group = self._apply_group_manifest(group, closed, keep_pending=False)
        common_id = _new_id()
        recipients = [
            member
            for member in group["members"]
            if member.get("status") == "active"
            and member["destination_hash"] != profile["destination_hash"]
        ]
        deliveries = [
            self._delivery_record(
                group=group,
                recipient=recipient,
                kind=MessageKind.GROUP_MANIFEST,
                document=closed.serialized,
                group_message_id=common_id,
            )
            for recipient in recipients
        ]
        closed_invite_records: list[tuple[str, str, dict[str, Any]]] = []
        for invitation in self.store.list("group_sent_invite"):
            if invitation.get("group_id") != group["id"]:
                continue
            if invitation.get("state") == "sent":
                invitation["state"] = "closed"
                invitation["updated_at"] = time.time()
                closed_invite_records.append(
                    ("group_sent_invite", invitation["id"], invitation)
                )
        self.store.put_many(
            [
                ("group", group["id"], group),
                (
                    "group_manifest",
                    closed.digest,
                    {
                        "group_id": group["id"],
                        "epoch": closed.epoch,
                        "digest": closed.digest,
                        "serialized": closed.serialized,
                    },
                ),
                *closed_invite_records,
                *self._cancel_obsolete_group_chat_records(
                    group["id"], closed.epoch
                ),
                *self._complete_group_control_records(
                    group["id"], {MessageKind.GROUP_INVITE}
                ),
                *[
                    ("group_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
            ]
        )
        for delivery in deliveries:
            self._attempt_group_delivery(delivery["id"])
        self._changed()
        return self._public_group(group)

    def save_group_draft(self, group_id: str, text: str) -> dict[str, Any]:
        self._require_group(group_id)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValidationError("Draft is invalid")
        draft = {"group_id": group_id, "text": text}
        self.store.put("group_draft", group_id, draft)
        return draft

    def _receive_group_payload(
        self, native: Any, app: Any, contact: dict[str, Any] | None
    ) -> None:
        if app.kind not in GROUP_KINDS:
            return
        profile = self._require_profile()
        source = native.source_hash.hex()
        expected_conversation = conversation_id(
            bytes.fromhex(profile["destination_hash"]), native.source_hash
        )
        if app.conversation_id != expected_conversation:
            return
        if app.kind == MessageKind.GROUP_INVITE:
            self._receive_group_invite(native, app, contact)
            return
        if app.kind == MessageKind.GROUP_ACCEPT:
            self._receive_group_accept(native, app, contact)
            return
        group = self.store.get("group", app.group_id)
        if group is None:
            return
        if app.kind == MessageKind.GROUP_MANIFEST:
            self._receive_group_manifest(native, app, group)
            return
        if app.kind == MessageKind.GROUP_LEAVE_REQUEST:
            self._receive_group_leave_request(native, app, group)
            return
        if app.kind == MessageKind.GROUP_RECEIPT:
            self._receive_group_receipt(native, app, group)
            return
        member = self._group_member(group, source)
        if member is None:
            return
        if app.kind == MessageKind.GROUP_CHAT:
            self._receive_group_chat(native, app, group, member)
        elif app.kind == MessageKind.GROUP_REACTION:
            self._receive_group_reaction(native, app, group, member)

    def _receive_group_invite(
        self, native: Any, app: Any, contact: dict[str, Any] | None
    ) -> None:
        if contact is None or contact.get("trust") not in ACTIVE_TRUST:
            return
        profile = self._require_profile()
        invite = verify_group_invitation(
            app.group_document,
            expected_group_id=app.group_id,
            expected_owner_destination=native.source_hash,
            expected_invitee_destination=bytes.fromhex(profile["destination_hash"]),
        )
        if app.group_epoch != invite.group_epoch or app.group_manifest_hash != invite.manifest_hash:
            return
        if self.store.get("group", invite.group_id) is not None:
            # A new invitation must never replace or roll back a live, closed,
            # removed, or fork-frozen local group record.
            return
        invitation_id = _stable_id(b"mesh-chat:group-invite:", invite.serialized)
        existing = self.store.get("group_invitation", invitation_id)
        if existing is not None:
            receipt_group = self._invitation_receipt_group(invite)
            self._queue_group_receipt(receipt_group, native.source_hash, app)
            return
        now = time.time()
        pending = [
            invitation
            for invitation in self.store.list("group_invitation")
            if invitation.get("state") == "pending"
            and float(invitation.get("expires_at", 0)) > now
        ]
        if len(pending) >= MAX_PENDING_GROUP_INVITATIONS:
            return
        if sum(
            invitation.get("owner_destination") == native.source_hash.hex()
            for invitation in pending
        ) >= MAX_PENDING_GROUP_INVITATIONS_PER_OWNER:
            return
        members = [
            _member_record(member, epoch=invite.manifest.epoch)
            for member in invite.manifest.members
        ]
        record = {
            "id": invitation_id,
            "group_id": invite.group_id,
            "title": invite.manifest.title,
            "posting_policy": invite.manifest.posting_policy.value,
            "owner_display_name": invite.genesis.owner.display_name,
            "owner_destination": invite.owner_destination.hex(),
            "owner_fingerprint": invite.owner_fingerprint,
            "members": members,
            "member_count": len(members),
            "document": invite.serialized,
            "state": "pending",
            "created_at": invite.created_at,
            "expires_at": invite.expires_at,
        }
        receipt_group = self._invitation_receipt_group(invite)
        receipt = self._make_group_receipt(receipt_group, native.source_hash, app)
        # Storing the invitation and its application receipt job together means
        # the owner only sees "ready for review" after the phone can recover the
        # invitation even if the process stops immediately after this commit.
        self.store.put_many(
            [
                ("group_invitation", invitation_id, record),
                ("group_delivery", receipt["id"], receipt),
            ]
        )
        self._attempt_group_delivery(receipt["id"])
        self._changed()

    @staticmethod
    def _invitation_receipt_group(invite: Any) -> dict[str, Any]:
        """Build the minimal verified group view needed to receipt an invitation."""

        return {
            "id": invite.group_id,
            "epoch": invite.group_epoch,
            "manifest_hash": invite.manifest_hash,
            "members": [
                _member_record(member, epoch=invite.manifest.epoch)
                for member in invite.manifest.members
            ],
        }

    def _receive_group_accept(
        self, native: Any, app: Any, contact: dict[str, Any] | None
    ) -> None:
        if contact is None or contact.get("trust") not in ACTIVE_TRUST:
            return
        group = self.store.get("group", app.group_id)
        profile = self._require_profile()
        identity = getattr(self, "_identity", None)
        if (
            group is None
            or identity is None
            or group.get("owner_destination") != profile["destination_hash"]
            or group.get("status") not in {"active", "closed"}
        ):
            return
        sent_invite = next(
            (
                invitation
                for invitation in self.store.list("group_sent_invite")
                if invitation["group_id"] == group["id"]
                and invitation["invitee_destination"] == native.source_hash.hex()
                and invitation.get("state") in {"sent", "accepted", "closed"}
            ),
            None,
        )
        if sent_invite is None:
            return
        join = verify_group_join_statement(
            app.group_document, invitation=sent_invite["document"]
        )
        if join.member.destination_hash != native.source_hash:
            return
        if app.group_epoch != join.group_epoch or app.group_manifest_hash != join.manifest_hash:
            return
        current = verify_group_manifest(
            group["manifest"],
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
        )
        already_member = any(
            member.card.destination_hash == join.member.destination_hash
            for member in current.members
        )
        # Invitations are single-use capabilities.  Once accepted, a replay can
        # request a catch-up response but can never re-admit a member that a
        # later signed manifest removed.  Closed groups similarly return their
        # terminal chain instead of leaving the invitee stuck in "joining".
        if (
            sent_invite.get("state") != "sent"
            or already_member
            or group.get("status") == "closed"
        ):
            sent_invite["state"] = (
                "closed" if group.get("status") == "closed" else "accepted"
            )
            sent_invite["updated_at"] = time.time()
            recipient = self._group_member(
                group, native.source_hash.hex(), active_only=False
            ) or _member_record(join.member, epoch=join.group_epoch)
            deliveries = self._manifest_chain_deliveries(
                group,
                recipient,
                after_epoch=join.group_epoch,
            )
            if not deliveries and already_member:
                deliveries = [
                    self._delivery_record(
                        group=group,
                        recipient=recipient,
                        kind=MessageKind.GROUP_MANIFEST,
                        document=current.serialized,
                        group_message_id=_new_id(),
                    )
                ]
            records: list[tuple[str, str, dict[str, Any]]] = [
                ("group_sent_invite", sent_invite["id"], sent_invite),
                *self._complete_group_control_records(
                    group["id"],
                    {MessageKind.GROUP_INVITE},
                    recipient_destination=native.source_hash.hex(),
                ),
                *[
                    ("group_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
            ]
            self.store.put_many(records)
            for delivery in deliveries:
                self._attempt_group_delivery(delivery["id"])
            self._changed()
            return
        if len(current.members) >= MAX_GROUP_MEMBERS:
            return
        raw = create_group_manifest(
            identity,
            group_id=group["id"],
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            title=current.title,
            posting_policy=current.posting_policy,
            members=[
                *[
                    GroupManifestMemberInput(member.card.serialized, member.role)
                    for member in current.members
                ],
                GroupManifestMemberInput(join.member.serialized, GroupRole.MEMBER),
            ],
        )
        updated = verify_group_manifest(
            raw,
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
            expected_previous_hash=current.digest,
            expected_epoch=current.epoch + 1,
        )
        group = self._apply_group_manifest(group, updated, keep_pending=True)
        sent_invite["state"] = "accepted"
        sent_invite["updated_at"] = time.time()
        common_id = _new_id()
        recipients = [
            member
            for member in group["members"]
            if member.get("status") == "active"
            and member["destination_hash"] != profile["destination_hash"]
        ]
        deliveries: list[dict[str, Any]] = []
        for recipient in recipients:
            if recipient["destination_hash"] == native.source_hash.hex():
                deliveries.extend(
                    self._manifest_chain_deliveries(
                        group,
                        recipient,
                        after_epoch=join.group_epoch,
                        extra_manifest=updated,
                    )
                )
            else:
                deliveries.append(
                    self._delivery_record(
                        group=group,
                        recipient=recipient,
                        kind=MessageKind.GROUP_MANIFEST,
                        document=updated.serialized,
                        group_message_id=common_id,
                    )
                )
        self.store.put_many(
            [
                ("group", group["id"], group),
                ("group_sent_invite", sent_invite["id"], sent_invite),
                (
                    "group_manifest",
                    updated.digest,
                    {
                        "group_id": group["id"],
                        "epoch": updated.epoch,
                        "digest": updated.digest,
                        "serialized": updated.serialized,
                    },
                ),
                *self._cancel_obsolete_group_chat_records(
                    group["id"], updated.epoch
                ),
                *self._complete_group_control_records(
                    group["id"],
                    {MessageKind.GROUP_INVITE},
                    recipient_destination=native.source_hash.hex(),
                ),
                *[
                    ("group_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
            ]
        )
        self._remember_group_members(group)
        for delivery in deliveries:
            self._attempt_group_delivery(delivery["id"])
        self._changed()

    def _receive_group_leave_request(
        self, native: Any, app: Any, group: dict[str, Any]
    ) -> None:
        profile = self._require_profile()
        if (
            group.get("owner_destination") != profile["destination_hash"]
            or group.get("status") != "active"
        ):
            return
        manifest = verify_group_manifest(
            group["manifest"],
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(profile["destination_hash"]),
        )
        leave = verify_group_leave_request(app.group_document, manifest=manifest)
        if (
            leave.leaver_destination != native.source_hash
            or app.group_epoch != leave.group_epoch
            or app.group_manifest_hash != leave.manifest_hash
        ):
            return
        self.remove_group_member(group["id"], native.source_hash.hex())

    def _record_group_fork(
        self,
        group: dict[str, Any],
        manifest: Any,
        known_digests: list[str],
    ) -> None:
        group["status"] = "forked"
        group["security_warning"] = "conflicting_membership_manifest"
        group["updated_at"] = time.time()
        all_digests = sorted({*known_digests, manifest.digest})
        evidence_id = _stable_id(
            b"mesh-chat:group-fork:",
            f"{group['id']}:{manifest.epoch}:{':'.join(all_digests)}",
        )
        evidence = {
            "id": evidence_id,
            "group_id": group["id"],
            "epoch": manifest.epoch,
            "known_digests": all_digests,
            "incoming_digest": manifest.digest,
            "incoming_manifest": manifest.serialized,
            "recorded_at": time.time(),
        }
        self.store.put_many(
            [
                ("group", group["id"], group),
                ("group_fork_evidence", evidence_id, evidence),
                *self._cancel_obsolete_group_chat_records(
                    group["id"], int(group["epoch"]) + 1
                ),
            ]
        )
        self._changed()

    def _pending_manifest_app(self, record: dict[str, Any]) -> Any:
        return SimpleNamespace(
            logical_id=record["logical_id"],
            group_message_id=record.get("group_message_id"),
            group_epoch=int(record["epoch"]),
            group_manifest_hash=record["digest"],
        )

    def _apply_received_group_manifest(
        self,
        group: dict[str, Any],
        manifest: Any,
        source_destination: bytes,
        app: Any,
    ) -> dict[str, Any]:
        group = self._apply_group_manifest(group, manifest, keep_pending=False)
        receipt = self._make_group_receipt(group, source_destination, app)
        completed_controls = {MessageKind.GROUP_ACCEPT}
        if not group.get("leave_pending"):
            completed_controls.add(MessageKind.GROUP_LEAVE_REQUEST)
        records: list[tuple[str, str, dict[str, Any]]] = [
            ("group", group["id"], group),
            (
                "group_manifest",
                manifest.digest,
                {
                    "group_id": group["id"],
                    "epoch": manifest.epoch,
                    "digest": manifest.digest,
                    "serialized": manifest.serialized,
                },
            ),
            ("group_delivery", receipt["id"], receipt),
            *self._cancel_obsolete_group_chat_records(
                group["id"], manifest.epoch
            ),
            *self._complete_group_control_records(
                group["id"],
                completed_controls,
            ),
        ]
        self.store.put_many(records)
        self._remember_group_members(group)
        self._attempt_group_delivery(receipt["id"])
        return group

    def _drain_pending_group_manifests(
        self, group: dict[str, Any], source_destination: bytes
    ) -> dict[str, Any]:
        for record in self.store.list("group_pending_manifest"):
            if (
                record.get("group_id") == group["id"]
                and int(record.get("epoch", -1)) <= int(group["epoch"])
            ):
                self.store.delete("group_pending_manifest", record["id"])
        while group.get("status") not in {"closed", "forked"}:
            next_epoch = int(group["epoch"]) + 1
            candidates = [
                record
                for record in self.store.list("group_pending_manifest")
                if record.get("group_id") == group["id"]
                and int(record.get("epoch", -1)) == next_epoch
            ]
            if not candidates:
                break
            digests = sorted({record["digest"] for record in candidates})
            chosen = candidates[0]
            manifest = verify_group_manifest(
                chosen["serialized"],
                expected_group_id=group["id"],
                expected_owner_destination=source_destination,
            )
            if len(digests) != 1 or manifest.previous_manifest_hash != group["manifest_hash"]:
                self._record_group_fork(group, manifest, digests)
                return self._require_group(group["id"])
            group = self._apply_received_group_manifest(
                group,
                manifest,
                source_destination,
                self._pending_manifest_app(chosen),
            )
            for candidate in candidates:
                self.store.delete("group_pending_manifest", candidate["id"])
        return group

    def _receive_group_manifest(self, native: Any, app: Any, group: dict[str, Any]) -> None:
        if native.source_hash.hex() != group.get("owner_destination"):
            return
        manifest = verify_group_manifest(
            app.group_document,
            expected_group_id=group["id"],
            expected_owner_destination=native.source_hash,
        )
        if app.group_epoch != manifest.epoch or app.group_manifest_hash != manifest.digest:
            return
        persisted_same_epoch = [
            record
            for record in self._manifest_records(group["id"])
            if int(record["epoch"]) == manifest.epoch
        ]
        pending_same_epoch = [
            record
            for record in self.store.list("group_pending_manifest")
            if record.get("group_id") == group["id"]
            and int(record.get("epoch", -1)) == manifest.epoch
        ]
        known_digests = [
            record["digest"] for record in [*persisted_same_epoch, *pending_same_epoch]
        ]
        if any(digest != manifest.digest for digest in known_digests):
            self._record_group_fork(group, manifest, known_digests)
            return
        if group.get("status") == "forked":
            return
        current_epoch = int(group["epoch"])
        current_hash = group["manifest_hash"]
        if manifest.epoch == current_epoch and manifest.digest == current_hash:
            self._queue_group_receipt(group, native.source_hash, app)
            return
        if manifest.epoch <= current_epoch:
            if manifest.digest in known_digests:
                self._queue_group_receipt(group, native.source_hash, app)
            else:
                self._record_group_fork(group, manifest, [current_hash])
            return
        if group.get("status") == "closed":
            return
        if manifest.epoch > current_epoch + 1:
            pending_for_group = [
                record
                for record in self.store.list("group_pending_manifest")
                if record.get("group_id") == group["id"]
            ]
            if (
                len(pending_for_group) >= MAX_PENDING_GROUP_MANIFESTS
                or manifest.epoch > current_epoch + MAX_PENDING_GROUP_MANIFESTS
            ):
                return
            pending_id = _stable_id(
                b"mesh-chat:pending-manifest:",
                f"{group['id']}:{manifest.epoch}:{manifest.digest}",
            )
            self.store.put(
                "group_pending_manifest",
                pending_id,
                {
                    "id": pending_id,
                    "group_id": group["id"],
                    "epoch": manifest.epoch,
                    "digest": manifest.digest,
                    "serialized": manifest.serialized,
                    "logical_id": app.logical_id,
                    "group_message_id": app.group_message_id,
                    "source_destination": native.source_hash.hex(),
                    "received_at": time.time(),
                },
            )
            return
        if manifest.previous_manifest_hash != current_hash:
            self._record_group_fork(group, manifest, [current_hash])
            return
        group = self._apply_received_group_manifest(
            group, manifest, native.source_hash, app
        )
        self._drain_pending_group_manifests(group, native.source_hash)
        self._changed()

    def _receive_group_chat(
        self, native: Any, app: Any, group: dict[str, Any], member: dict[str, Any]
    ) -> None:
        if group.get("status") != "active":
            return
        if app.group_epoch != group["epoch"] or app.group_manifest_hash != group["manifest_hash"]:
            return
        if (
            group["posting_policy"] == GroupPostingPolicy.OWNER_ADMINS.value
            and member.get("role") not in {GroupRole.OWNER.value, GroupRole.ADMIN.value}
        ):
            return
        if self._message_was_discarded("group", group["id"], app.group_message_id):
            self._queue_group_receipt(group, native.source_hash, app)
            return
        sequence_id = _stable_id(
            b"mesh-chat:group-sequence:",
            f"{group['id']}:{native.source_hash.hex()}:{app.sender_sequence}",
        )
        sequence = self.store.get("group_sequence", sequence_id)
        if sequence is not None and sequence.get("message_id") != app.group_message_id:
            # A sender sequence may arrive out of order, but it may never name
            # two different logical messages.  Treat that as an authenticated
            # conflict and fail closed without acknowledging either rewrite.
            return
        existing = self.store.get("group_message", app.group_message_id)
        if existing is not None:
            if (
                existing.get("group_id") == group["id"]
                and
                existing.get("sender_destination") == native.source_hash.hex()
                and existing.get("text") == app.text
                and int(existing.get("group_epoch", -1)) == app.group_epoch
                and existing.get("group_manifest_hash")
                == app.group_manifest_hash
                and int(existing.get("sender_sequence", -1))
                == app.sender_sequence
            ):
                self._queue_group_receipt(group, native.source_hash, app)
            return
        message = {
            "id": app.group_message_id,
            "group_id": group["id"],
            "direction": "inbound",
            "sender_destination": native.source_hash.hex(),
            "sender_display_name": member["display_name"],
            "text": app.text,
            "group_epoch": app.group_epoch,
            "group_manifest_hash": app.group_manifest_hash,
            "sender_sequence": app.sender_sequence,
            "state": DeliveryState.DELIVERED.value,
            "created_at": float(native.timestamp or time.time()),
            "expires_at": float(app.expires_at),
            "native_message_id": native.hash.hex() if native.hash else None,
        }
        receipt = self._make_group_receipt(group, native.source_hash, app)
        reaction_writes, reaction_deletions = self._pending_reaction_changes(
            "group", group["id"], message, group=group
        )
        self.store.put_and_delete(
            [
                ("group_message", message["id"], message),
                (
                    "group_sequence",
                    sequence_id,
                    {
                        "group_id": group["id"],
                        "sender_destination": native.source_hash.hex(),
                        "sender_sequence": app.sender_sequence,
                        "message_id": app.group_message_id,
                    },
                ),
                ("group_delivery", receipt["id"], receipt),
                *reaction_writes,
            ],
            [
                (
                    "conversation_hidden",
                    self._conversation_marker_id("group", group["id"]),
                ),
                *reaction_deletions,
            ],
        )
        self._attempt_group_delivery(receipt["id"])
        self._changed()

    def _make_group_receipt(
        self, group: dict[str, Any], recipient_destination: bytes, app: Any
    ) -> dict[str, Any]:
        recipient = self._group_member(
            group, recipient_destination.hex(), active_only=False
        )
        if recipient is None:
            # A removed member can still acknowledge the manifest that removed
            # it; the owner remains available in the new roster for that case.
            raise ValidationError("Receipt recipient is not known to this group")
        return self._delivery_record(
            group=group,
            recipient=recipient,
            kind=MessageKind.GROUP_RECEIPT,
            group_message_id=app.group_message_id or app.logical_id,
            receipt_for=app.logical_id,
            epoch=app.group_epoch,
            manifest_hash=app.group_manifest_hash,
        )

    def _queue_group_receipt(
        self, group: dict[str, Any], recipient_destination: bytes, app: Any
    ) -> None:
        existing = next(
            (
                delivery
                for delivery in self.store.list("group_delivery")
                if delivery.get("kind") == MessageKind.GROUP_RECEIPT.value
                and delivery.get("receipt_for") == app.logical_id
                and delivery.get("recipient_destination") == recipient_destination.hex()
            ),
            None,
        )
        if existing is not None:
            if existing["state"] in {
                DeliveryState.QUEUED.value,
                DeliveryState.WAITING_FOR_KEYS.value,
            }:
                self._attempt_group_delivery(existing["id"])
            return
        receipt = self._make_group_receipt(group, recipient_destination, app)
        self.store.put("group_delivery", receipt["id"], receipt)
        self._attempt_group_delivery(receipt["id"])

    def _receive_group_receipt(
        self, native: Any, app: Any, group: dict[str, Any]
    ) -> None:
        delivery = self.store.get("group_delivery", app.receipt_for)
        if (
            delivery is None
            or delivery.get("kind") == MessageKind.GROUP_RECEIPT.value
            or delivery.get("group_id") != group["id"]
            or delivery.get("recipient_destination") != native.source_hash.hex()
            or (delivery.get("group_message_id") or delivery["id"])
            != app.group_message_id
            or int(delivery.get("group_epoch", -1)) != app.group_epoch
            or delivery.get("group_manifest_hash") != app.group_manifest_hash
        ):
            return
        if delivery.get("kind") == MessageKind.GROUP_REACTION.value:
            self.store.delete("group_delivery", delivery["id"])
        else:
            delivery["state"] = DeliveryState.DELIVERED.value
            delivery["delivered_at"] = time.time()
            self.store.put("group_delivery", delivery["id"], delivery)
        self._changed()

    def _recover_group_outbox(self) -> None:
        now = time.time()
        self._expire_group_invitation_state(now)
        for delivery in self.store.list("group_delivery"):
            if delivery["state"] in FINAL_DELIVERY_STATES:
                if self._is_reaction_only_delivery(delivery):
                    self.store.delete("group_delivery", delivery["id"])
                continue
            invalid_reason = self._group_chat_invalid_reason(delivery)
            if invalid_reason is not None:
                self._fail_group_delivery(delivery, invalid_reason)
                continue
            elif self._group_control_business_complete(delivery):
                if self._is_reaction_only_delivery(delivery):
                    self.store.delete("group_delivery", delivery["id"])
                    continue
                delivery["state"] = DeliveryState.DELIVERED.value
                delivery["delivered_at"] = now
            elif float(delivery["expires_at"]) <= now:
                if self._is_reaction_only_delivery(delivery):
                    self.store.delete("group_delivery", delivery["id"])
                    continue
                delivery["state"] = DeliveryState.EXPIRED.value
                delivery["expired_at"] = now
            else:
                delivery["state"] = DeliveryState.QUEUED.value
                delivery["next_attempt_at"] = now
            self.store.put("group_delivery", delivery["id"], delivery)
        for group in self.store.list("group"):
            if group.get("status") in {"closed", "forked"}:
                continue
            try:
                self._drain_pending_group_manifests(
                    group, bytes.fromhex(group["owner_destination"])
                )
            except Exception:
                # Invalid pending state stays inert and must never prevent the
                # rest of the encrypted outbox from recovering.
                continue

    def _retry_group_outbox(self) -> None:
        now = time.time()
        self._expire_group_invitation_state(now)
        for delivery in self.store.list("group_delivery"):
            self._retry_group_delivery_if_due(delivery["id"], now)

    def _retry_group_delivery_if_due(
        self, delivery_id: str, now: float | None = None
    ) -> None:
        """Advance one durable group leg without requiring a backlog-wide lock."""

        current_time = time.time() if now is None else now
        delivery = self.store.get("group_delivery", delivery_id)
        if delivery is None or delivery["state"] in FINAL_DELIVERY_STATES:
            return
        if self._group_control_business_complete(delivery):
            if self._is_reaction_only_delivery(delivery):
                self.store.delete("group_delivery", delivery["id"])
                return
            delivery["state"] = DeliveryState.DELIVERED.value
            delivery["delivered_at"] = current_time
            self.store.put("group_delivery", delivery["id"], delivery)
            return
        if float(delivery["expires_at"]) <= current_time:
            if self._is_reaction_only_delivery(delivery):
                self.store.delete("group_delivery", delivery["id"])
                return
            delivery["state"] = DeliveryState.EXPIRED.value
            delivery["expired_at"] = current_time
            self.store.put("group_delivery", delivery["id"], delivery)
            return
        if float(delivery.get("next_attempt_at", 0)) <= current_time:
            self._attempt_group_delivery(delivery["id"])

    def _group_control_business_complete(self, delivery: dict[str, Any]) -> bool:
        kind = delivery.get("kind")
        if kind == MessageKind.GROUP_RECEIPT.value:
            return delivery.get("state") in {
                DeliveryState.RECEIVED_BY_ENDPOINT.value,
                DeliveryState.DELIVERED.value,
            }
        group = self.store.get("group", delivery.get("group_id", ""))
        if group is None:
            return False
        if kind == MessageKind.GROUP_ACCEPT.value:
            return group.get("status") != "joining"
        if kind == MessageKind.GROUP_LEAVE_REQUEST.value:
            return not bool(group.get("leave_pending"))
        if kind == MessageKind.GROUP_INVITE.value:
            return any(
                invitation.get("group_id") == group["id"]
                and invitation.get("invitee_destination")
                == delivery.get("recipient_destination")
                and invitation.get("state") in {"accepted", "closed", "expired"}
                for invitation in self.store.list("group_sent_invite")
            )
        return False

    def _expire_group_invitation_state(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        records: list[tuple[str, str, dict[str, Any]]] = []
        for invitation in self.store.list("group_invitation"):
            if float(invitation.get("expires_at", 0)) <= current:
                # Once its signed expiry passes, retaining a declined or
                # unhandled inbound capability serves no replay-defense purpose:
                # verification rejects it before deduplication.
                self.store.delete("group_invitation", invitation["id"])
        expired_by_group: dict[str, set[str]] = {}
        for invitation in self.store.list("group_sent_invite"):
            if float(invitation.get("expires_at", 0)) > current:
                continue
            if invitation.get("state") == "sent":
                expired_by_group.setdefault(invitation["group_id"], set()).add(
                    invitation["invitee_destination"]
                )
            self.store.delete("group_sent_invite", invitation["id"])
        for group_id, destinations in expired_by_group.items():
            group = self.store.get("group", group_id)
            if group is None:
                continue
            changed = False
            for member in group.get("members", []):
                if (
                    member.get("status") == "invited"
                    and member.get("destination_hash") in destinations
                ):
                    member["status"] = "invite_expired"
                    changed = True
            if changed:
                group["updated_at"] = current
                records.append(("group", group_id, group))
        if records:
            self.store.put_many(records)

    def _delivery_summary(self, message_id: str) -> dict[str, int]:
        deliveries = [
            delivery
            for delivery in self.store.list("group_delivery")
            if delivery.get("kind") == MessageKind.GROUP_CHAT.value
            and delivery.get("group_message_id") == message_id
        ]
        total = len(deliveries)
        delivered = sum(
            delivery["state"] == DeliveryState.DELIVERED.value
            for delivery in deliveries
        )
        failed = sum(
            delivery["state"] == DeliveryState.FAILED.value for delivery in deliveries
        )
        expired = sum(
            delivery["state"] == DeliveryState.EXPIRED.value for delivery in deliveries
        )
        return {
            "total": total,
            "delivered": delivered,
            "pending": max(0, total - delivered - failed - expired),
            "failed": failed,
            "expired": expired,
        }

    def _public_group(self, group: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in group.items()
            if key not in {"genesis", "manifest", "next_sender_sequence", "members"}
        }
        public_members = [
            {key: value for key, value in member.items() if key != "member_card"}
            for member in group.get("members", [])
        ]
        invite_deliveries = {
            delivery.get("recipient_destination"): delivery
            for delivery in self.store.list("group_delivery")
            if delivery.get("group_id") == group["id"]
            and delivery.get("kind") == MessageKind.GROUP_INVITE.value
        }
        for member in public_members:
            delivery = invite_deliveries.get(member.get("destination_hash"))
            if delivery is None:
                continue
            member["invite_delivery_state"] = delivery.get("state")
            member["invite_attempt_count"] = int(delivery.get("attempt_count", 0))
            if delivery.get("last_attempt_at") is not None:
                member["invite_last_attempt_at"] = delivery["last_attempt_at"]
            if delivery.get("failure_code") is not None:
                member["invite_failure_code"] = delivery["failure_code"]
        public["members"] = public_members
        active_destinations = {
            member["destination_hash"]
            for member in group.get("members", [])
            if member.get("status") == "active"
        }
        pending_manifest = any(
            delivery.get("group_id") == group["id"]
            and delivery.get("kind") == MessageKind.GROUP_MANIFEST.value
            and int(delivery.get("group_epoch", -1)) == int(group["epoch"])
            and delivery.get("recipient_destination") in active_destinations
            and delivery.get("state") != DeliveryState.DELIVERED.value
            for delivery in self.store.list("group_delivery")
        )
        public["membership_update_pending"] = pending_manifest
        return public

    def _public_group_message(
        self,
        message: dict[str, Any],
        reaction_index: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        reactions = self._reaction_index() if reaction_index is None else reaction_index
        public = dict(message)
        public["reactions"] = self._public_reactions(
            reactions, "group", message["group_id"], message["id"]
        )
        if message.get("direction") == "outbound":
            public["delivery_summary"] = self._delivery_summary(message["id"])
            public["deliveries"] = [
                {
                    "recipient_destination": delivery["recipient_destination"],
                    "recipient_display_name": delivery["recipient_display_name"],
                    "state": delivery["state"],
                }
                for delivery in self.store.list("group_delivery")
                if delivery.get("kind") == MessageKind.GROUP_CHAT.value
                and delivery.get("group_message_id") == message["id"]
            ]
        return public

    @staticmethod
    def _public_invitation(invitation: dict[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in invitation.items() if key != "document"}
        public["members"] = [
            {key: value for key, value in member.items() if key != "member_card"}
            for member in invitation.get("members", [])
        ]
        return public

    def group_snapshot(
        self,
        reaction_index: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        self._expire_group_invitation_state()
        reactions = self._reaction_index() if reaction_index is None else reaction_index
        groups = [self._public_group(group) for group in self.store.list("group")]
        messages = [
            self._public_group_message(message, reactions)
            for message in self.store.list("group_message")
        ]
        messages.sort(key=lambda item: item["created_at"])
        invitations = [
            self._public_invitation(invitation)
            for invitation in self.store.list("group_invitation")
            if invitation.get("state") == "pending"
            and float(invitation.get("expires_at", 0)) > time.time()
        ]
        return {
            "groups": groups,
            "group_messages": messages,
            "group_drafts": self.store.list("group_draft"),
            "group_invitations": invitations,
        }
