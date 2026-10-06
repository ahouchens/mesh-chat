from __future__ import annotations

import time
import uuid
from typing import Any

import RNS

from .app_protocol import (
    ALLOWED_REACTION_EMOJIS,
    MAX_REACTION_REVISION,
    conversation_id,
)
from .emoji_validation import is_valid_reaction_emoji
from .errors import ContactNotApproved, ValidationError
from .group_protocol import verify_group_manifest
from .models import MessageKind, TrustState


REACTION_REPLAY_GRACE_SECONDS = 24 * 60 * 60
MAX_PENDING_REACTIONS = 256
MAX_PENDING_REACTIONS_PER_ACTOR = 32
MAX_REACTION_RECEIPTS_PER_TARGET = 4
REACTION_SCOPES = frozenset({"direct", "group"})
REACTION_TRUST = frozenset({TrustState.APPROVED.value, TrustState.VERIFIED.value})


def _opaque_reaction_id(domain: bytes, *values: str) -> str:
    material = b"\x00".join(value.encode("utf-8") for value in values)
    digest = RNS.Identity.full_hash(domain + material)
    return str(uuid.UUID(bytes=digest[:16]))


class ReactionServiceMixin:
    """Durable reaction state layered over authenticated direct/group payloads."""

    @staticmethod
    def _reaction_record_id(
        scope: str, target_id: str, message_id: str, actor_destination: str
    ) -> str:
        return _opaque_reaction_id(
            b"mesh-chat:reaction-state:v1:",
            scope,
            target_id,
            message_id,
            actor_destination,
        )

    @staticmethod
    def _pending_reaction_id(
        scope: str, target_id: str, message_id: str, actor_destination: str
    ) -> str:
        return _opaque_reaction_id(
            b"mesh-chat:pending-reaction:v1:",
            scope,
            target_id,
            message_id,
            actor_destination,
        )

    def _reaction_state(
        self, scope: str, target_id: str, message_id: str, actor_destination: str
    ) -> dict[str, Any] | None:
        return self.store.get(
            "reaction",
            self._reaction_record_id(
                scope, target_id, message_id, actor_destination
            ),
        )

    def _reaction_record(
        self,
        *,
        scope: str,
        target_id: str,
        message_id: str,
        actor_destination: str,
        emoji: str,
        active: bool,
        revision: int,
        updated_at: float | None = None,
    ) -> dict[str, Any]:
        record_id = self._reaction_record_id(
            scope, target_id, message_id, actor_destination
        )
        return {
            "id": record_id,
            "scope": scope,
            "target_id": target_id,
            "message_id": message_id,
            "actor_destination": actor_destination,
            "emoji": emoji,
            "active": active,
            "revision": revision,
            "updated_at": time.time() if updated_at is None else updated_at,
        }

    def _reaction_index(
        self,
    ) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
        profile = self.store.get("profile", "local")
        local_destination = None if profile is None else profile.get("destination_hash")
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for reaction in self.store.list("reaction"):
            key_values = (
                reaction.get("scope"),
                reaction.get("target_id"),
                reaction.get("message_id"),
            )
            if (
                reaction.get("active") is not True
                or not is_valid_reaction_emoji(reaction.get("emoji"))
                or not all(isinstance(value, str) for value in key_values)
            ):
                continue
            key = (key_values[0], key_values[1], key_values[2])
            grouped.setdefault(key, []).append(reaction)
        indexed: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        legacy_order = {
            emoji: index for index, emoji in enumerate(ALLOWED_REACTION_EMOJIS)
        }
        for key, active in grouped.items():
            counts: dict[str, int] = {}
            reacted_by_self: set[str] = set()
            for item in active:
                emoji = item["emoji"]
                counts[emoji] = counts.get(emoji, 0) + 1
                if item.get("actor_destination") == local_destination:
                    reacted_by_self.add(emoji)
            ordered = sorted(
                counts,
                key=lambda emoji: (
                    0 if emoji in legacy_order else 1,
                    legacy_order.get(emoji, 0),
                    emoji,
                ),
            )
            indexed[key] = [
                {
                    "emoji": emoji,
                    "count": counts[emoji],
                    "reacted_by_self": emoji in reacted_by_self,
                }
                for emoji in ordered
            ]
        return indexed

    @staticmethod
    def _public_reactions(
        reaction_index: dict[tuple[str, str, str], list[dict[str, Any]]],
        scope: str,
        target_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        return [
            dict(reaction)
            for reaction in reaction_index.get((scope, target_id, message_id), [])
        ]

    def _public_direct_message(
        self,
        message: dict[str, Any],
        reaction_index: dict[tuple[str, str, str], list[dict[str, Any]]],
    ) -> dict[str, Any]:
        public = dict(message)
        public["reactions"] = self._public_reactions(
            reaction_index, "direct", message["contact_id"], message["id"]
        )
        return public

    @staticmethod
    def _validate_reaction_command(
        kind: Any, message_id: Any, emoji: Any, active: Any
    ) -> tuple[str, str, str, bool]:
        if not isinstance(kind, str) or kind not in REACTION_SCOPES:
            raise ValidationError("Reaction conversation kind is invalid")
        try:
            checked_message_id = str(uuid.UUID(message_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Reaction message ID is invalid") from exc
        if not is_valid_reaction_emoji(emoji):
            raise ValidationError("Reaction emoji is invalid")
        if not isinstance(active, bool):
            raise ValidationError("Reaction active state is invalid")
        return kind, checked_message_id, emoji, active

    def _direct_reaction_target(
        self, message_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        message = self.store.get("message", message_id)
        if message is None or message.get("kind") != MessageKind.CHAT.value:
            raise ValidationError("Reaction target does not exist")
        contact = self._require_contact(message.get("contact_id"))
        if contact.get("trust") not in REACTION_TRUST:
            raise ContactNotApproved("Contact is not approved for reactions")
        profile = self._require_profile()
        expected = conversation_id(
            bytes.fromhex(profile["destination_hash"]),
            bytes.fromhex(contact["destination_hash"]),
        )
        if message.get("conversation_id") != expected:
            raise ValidationError("Reaction target conversation is invalid")
        return message, contact

    def _group_reaction_target(
        self, message_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        message = self.store.get("group_message", message_id)
        if (
            message is None
            or message.get("id") != message_id
            or not isinstance(message.get("text"), str)
            or not isinstance(message.get("sender_destination"), str)
            or not isinstance(message.get("group_epoch"), int)
            or not isinstance(message.get("group_manifest_hash"), str)
        ):
            raise ValidationError("Reaction target does not exist")
        group = self._require_group(message.get("group_id"))
        if group.get("status") != "active":
            raise ContactNotApproved("Group is not active")
        local = self._local_group_member(group)
        if local is None or local.get("status") != "active":
            raise ContactNotApproved("Local identity is not an active group member")
        if (
            self._require_profile()["destination_hash"]
            not in self._reaction_target_destinations(group, message)
        ):
            raise ContactNotApproved(
                "Local identity was not a member for this message"
            )
        return message, group

    @staticmethod
    def _reaction_change_required(
        current: dict[str, Any] | None, emoji: str, active: bool
    ) -> bool:
        if active:
            return not (
                current is not None
                and current.get("active") is True
                and current.get("emoji") == emoji
            )
        return bool(
            current is not None
            and current.get("active") is True
            and current.get("emoji") == emoji
        )

    def set_message_reaction(
        self, kind: Any, message_id: Any, emoji: Any, active: Any
    ) -> dict[str, Any]:
        scope, checked_message_id, checked_emoji, checked_active = (
            self._validate_reaction_command(kind, message_id, emoji, active)
        )
        profile = self._require_profile()
        actor = profile["destination_hash"]
        if scope == "direct":
            target, contact = self._direct_reaction_target(checked_message_id)
            target_id = contact["id"]
        else:
            target, group = self._group_reaction_target(checked_message_id)
            target_id = group["id"]
        current = self._reaction_state(
            scope, target_id, checked_message_id, actor
        )
        if not self._reaction_change_required(current, checked_emoji, checked_active):
            return {
                "kind": scope,
                "message_id": checked_message_id,
                "emoji": checked_emoji,
                "active": checked_active,
            }
        revision = int(current.get("revision", 0) if current else 0) + 1
        if revision > MAX_REACTION_REVISION:
            raise ValidationError("Reaction revision is exhausted")
        state = self._reaction_record(
            scope=scope,
            target_id=target_id,
            message_id=checked_message_id,
            actor_destination=actor,
            emoji=checked_emoji,
            active=checked_active,
            revision=revision,
        )
        if scope == "direct":
            operation = self._outbound_record(contact, MessageKind.REACTION, "")
            operation.update(
                {
                    "reaction_for": checked_message_id,
                    "reaction_emoji": checked_emoji,
                    "reaction_active": checked_active,
                    "reaction_revision": revision,
                }
            )
            superseded = [
                item
                for item in self.store.list("message")
                if item.get("kind") == MessageKind.REACTION.value
                and item.get("contact_id") == contact["id"]
                and item.get("reaction_for") == checked_message_id
            ]
            self.store.put_and_delete(
                [
                    ("reaction", state["id"], state),
                    ("message", operation["id"], operation),
                ],
                [("message", item["id"]) for item in superseded],
            )
            self._cancel_reaction_operations(
                {item["id"] for item in superseded}
            )
            self._attempt(operation["id"])
        else:
            operation_id = str(uuid.uuid4())
            recipients = self._reaction_group_recipients(group, target)
            deliveries = [
                self._delivery_record(
                    group=group,
                    recipient=recipient,
                    kind=MessageKind.GROUP_REACTION,
                    group_message_id=operation_id,
                    reaction_for=checked_message_id,
                    reaction_emoji=checked_emoji,
                    reaction_active=checked_active,
                    reaction_revision=revision,
                )
                for recipient in recipients
            ]
            superseded = [
                delivery
                for delivery in self.store.list("group_delivery")
                if delivery.get("kind") == MessageKind.GROUP_REACTION.value
                and delivery.get("group_id") == group["id"]
                and delivery.get("reaction_for") == checked_message_id
            ]
            self.store.put_and_delete(
                [
                    ("reaction", state["id"], state),
                    *[
                        ("group_delivery", delivery["id"], delivery)
                        for delivery in deliveries
                    ],
                ],
                [("group_delivery", item["id"]) for item in superseded],
            )
            self._cancel_reaction_operations(
                {item["id"] for item in superseded}
            )
            for delivery in deliveries:
                self._attempt_group_delivery(delivery["id"])
        self._changed()
        return {
            "kind": scope,
            "message_id": checked_message_id,
            "emoji": checked_emoji,
            "active": checked_active,
        }

    def _cancel_reaction_operations(self, logical_ids: set[str]) -> None:
        if not logical_ids or self.network is None:
            return
        cancel_outbound = getattr(self.network, "cancel_outbound", None)
        if not callable(cancel_outbound):
            return
        try:
            cancel_outbound(logical_ids)
        except Exception:
            # Durable compaction already committed. Native cancellation is
            # best effort, and stale revisions are harmless at the receiver.
            pass

    def _reaction_target_destinations(
        self, group: dict[str, Any], target: dict[str, Any]
    ) -> set[str]:
        """Return identities entitled to learn about the target message.

        A group's current roster is not sufficient here: a member added later
        must not be able to infer or mutate reaction state for older messages.
        The message's authenticated epoch/hash pair selects the exact signed
        historical manifest that was in force when it was sent.
        """
        if target.get("group_id") != group.get("id"):
            raise ValidationError("Reaction target group is invalid")
        target_epoch = int(target.get("group_epoch", -1))
        target_digest = target.get("group_manifest_hash")
        serialized = None
        if (
            target_epoch == int(group.get("epoch", -2))
            and target_digest == group.get("manifest_hash")
        ):
            serialized = group.get("manifest")
        else:
            record = next(
                (
                    item
                    for item in self._manifest_records(group["id"])
                    if int(item.get("epoch", -1)) == target_epoch
                    and item.get("digest") == target_digest
                ),
                None,
            )
            if record is not None:
                serialized = record.get("serialized")
        if not isinstance(serialized, str):
            raise ValidationError("Reaction target membership is unavailable")
        manifest = verify_group_manifest(
            serialized,
            expected_group_id=group["id"],
            expected_owner_destination=bytes.fromhex(group["owner_destination"]),
            expected_epoch=target_epoch,
            now=int(float(target.get("created_at", time.time()))),
        )
        if manifest.digest != target_digest:
            raise ValidationError("Reaction target membership is invalid")
        return {
            member.card.destination_hash.hex() for member in manifest.members
        }

    def _reaction_group_recipients(
        self, group: dict[str, Any], target: dict[str, Any]
    ) -> list[dict[str, Any]]:
        entitled = self._reaction_target_destinations(group, target)
        local_destination = self._require_profile()["destination_hash"]
        return [
            member
            for member in group.get("members", [])
            if member.get("status") == "active"
            and member.get("destination_hash") != local_destination
            and member.get("destination_hash") in entitled
        ]

    def _reaction_pending_record(
        self,
        *,
        scope: str,
        target_id: str,
        actor_destination: str,
        app: Any,
    ) -> dict[str, Any]:
        record_id = self._pending_reaction_id(
            scope, target_id, app.reaction_for, actor_destination
        )
        return {
            "id": record_id,
            "scope": scope,
            "target_id": target_id,
            "message_id": app.reaction_for,
            "actor_destination": actor_destination,
            "emoji": app.reaction_emoji,
            "active": app.reaction_active,
            "revision": app.reaction_revision,
            "conversation_id": app.conversation_id,
            "group_epoch": app.group_epoch,
            "group_manifest_hash": app.group_manifest_hash,
            "expires_at": app.expires_at,
            "updated_at": time.time(),
        }

    def _prune_pending_reactions(self) -> None:
        now = int(time.time())
        for pending in self.store.list("pending_reaction"):
            remove = int(pending.get("expires_at", 0)) + REACTION_REPLAY_GRACE_SECONDS < now
            if not remove and pending.get("scope") == "group":
                group = self.store.get("group", pending.get("target_id", ""))
                remove = bool(
                    group is None
                    or group.get("status") != "active"
                    or int(pending.get("group_epoch", -1)) != int(group.get("epoch", -2))
                    or pending.get("group_manifest_hash") != group.get("manifest_hash")
                    or self._group_member(
                        group, pending.get("actor_destination", "")
                    )
                    is None
                )
            if remove:
                self.store.delete("pending_reaction", pending["id"])

    def _can_store_pending_reaction(self, actor_destination: str) -> bool:
        self._prune_pending_reactions()
        pending = self.store.list("pending_reaction")
        if len(pending) >= MAX_PENDING_REACTIONS:
            return False
        return sum(
            item.get("actor_destination") == actor_destination for item in pending
        ) < MAX_PENDING_REACTIONS_PER_ACTOR

    def _reaction_target_is_hidden(self, scope: str, target_id: str) -> bool:
        marker_id = self._conversation_marker_id(scope, target_id)
        return self.store.get("conversation_hidden", marker_id) is not None

    def _direct_reaction_receipt_record(
        self, contact: dict[str, Any], app: Any
    ) -> dict[str, Any]:
        receipt = self._receipt_record(contact, app.logical_id, app.conversation_id)
        receipt.update(
            {
                "reaction_receipt": True,
                "reaction_scope": "direct",
                "reaction_target_id": contact["id"],
                "reaction_target_message_id": app.reaction_for,
                "reaction_actor": contact["destination_hash"],
                "reaction_ack_revision": app.reaction_revision,
            }
        )
        return receipt

    def _bounded_reaction_receipt_deletions(
        self,
        *,
        table: str,
        scope: str,
        target_id: str,
        target_message_id: str,
        actor: str,
        added: dict[str, Any],
    ) -> list[tuple[str, str]]:
        existing = [
            record
            for record in self.store.list(table)
            if record.get("reaction_receipt") is True
            and record.get("reaction_scope") == scope
            and record.get("reaction_target_id") == target_id
            and record.get("reaction_target_message_id") == target_message_id
            and record.get("reaction_actor") == actor
            and record.get("id") != added["id"]
        ]
        existing.sort(
            key=lambda record: (
                int(record.get("reaction_ack_revision", 0)),
                float(record.get("created_at", 0)),
                str(record.get("id", "")),
            ),
        )
        excess = max(
            0, len(existing) + 1 - MAX_REACTION_RECEIPTS_PER_TARGET
        )
        return [
            (table, record["id"])
            for record in existing[:excess]
        ]

    def _direct_reaction_receipt_deletions(
        self, contact: dict[str, Any], app: Any, receipt: dict[str, Any]
    ) -> list[tuple[str, str]]:
        return self._bounded_reaction_receipt_deletions(
            table="message",
            scope="direct",
            target_id=contact["id"],
            target_message_id=app.reaction_for,
            actor=contact["destination_hash"],
            added=receipt,
        )

    def _ensure_direct_reaction_receipt(
        self, contact: dict[str, Any], app: Any
    ) -> None:
        for message in self.store.list("message"):
            if (
                message.get("kind") == MessageKind.RECEIPT.value
                and message.get("receipt_for") == app.logical_id
                and message.get("contact_id") == contact["id"]
                and message.get("conversation_id") == app.conversation_id
                and message.get("reaction_receipt") is True
                and message.get("reaction_target_message_id")
                == app.reaction_for
                and message.get("reaction_actor")
                == contact["destination_hash"]
            ):
                self._attempt(message["id"])
                return
        receipt = self._direct_reaction_receipt_record(contact, app)
        deletions = self._direct_reaction_receipt_deletions(
            contact, app, receipt
        )
        self.store.put_and_delete(
            [("message", receipt["id"], receipt)],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt(receipt["id"])

    def _group_reaction_receipt_record(
        self, group: dict[str, Any], source_destination: bytes, app: Any
    ) -> dict[str, Any]:
        receipt = self._make_group_receipt(group, source_destination, app)
        receipt["next_attempt_at"] = 0
        receipt.update(
            {
                "reaction_receipt": True,
                "reaction_scope": "group",
                "reaction_target_id": group["id"],
                "reaction_target_message_id": app.reaction_for,
                "reaction_actor": source_destination.hex(),
                "reaction_ack_revision": app.reaction_revision,
            }
        )
        return receipt

    def _group_reaction_receipt_deletions(
        self,
        group: dict[str, Any],
        source_destination: bytes,
        app: Any,
        receipt: dict[str, Any],
    ) -> list[tuple[str, str]]:
        return self._bounded_reaction_receipt_deletions(
            table="group_delivery",
            scope="group",
            target_id=group["id"],
            target_message_id=app.reaction_for,
            actor=source_destination.hex(),
            added=receipt,
        )

    def _ensure_group_reaction_receipt(
        self, group: dict[str, Any], source_destination: bytes, app: Any
    ) -> None:
        existing = next(
            (
                delivery
                for delivery in self.store.list("group_delivery")
                if delivery.get("kind") == MessageKind.GROUP_RECEIPT.value
                and delivery.get("receipt_for") == app.logical_id
                and delivery.get("group_id") == group["id"]
                and delivery.get("recipient_destination")
                == source_destination.hex()
                and delivery.get("reaction_receipt") is True
                and delivery.get("reaction_target_message_id")
                == app.reaction_for
                and delivery.get("reaction_actor")
                == source_destination.hex()
            ),
            None,
        )
        if existing is not None:
            self._attempt_group_delivery(existing["id"])
            return
        receipt = self._group_reaction_receipt_record(
            group, source_destination, app
        )
        deletions = self._group_reaction_receipt_deletions(
            group, source_destination, app, receipt
        )
        self.store.put_and_delete(
            [("group_delivery", receipt["id"], receipt)],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt_group_delivery(receipt["id"])

    def _receive_direct_reaction(
        self, contact: dict[str, Any], native: Any, app: Any
    ) -> None:
        actor = native.source_hash.hex()
        if actor != contact.get("destination_hash"):
            return
        if self._message_was_discarded(
            "direct", contact["id"], app.reaction_for
        ):
            self._ensure_direct_reaction_receipt(contact, app)
            return
        target = self.store.get("message", app.reaction_for)
        if target is not None:
            if (
                target.get("kind") != MessageKind.CHAT.value
                or target.get("contact_id") != contact["id"]
                or target.get("conversation_id") != app.conversation_id
            ):
                return
            self._apply_received_direct_reaction(contact, actor, app)
            return
        if self._reaction_target_is_hidden("direct", contact["id"]):
            # Hidden history intentionally ignores unknown targets. Native
            # endpoint evidence already terminates reaction-only retries, and
            # not allocating a receipt prevents arbitrary target UUIDs from
            # growing an invisible outbox.
            return
        pending_id = self._pending_reaction_id(
            "direct", contact["id"], app.reaction_for, actor
        )
        existing = self.store.get("pending_reaction", pending_id)
        if existing is not None and int(existing.get("revision", 0)) >= app.reaction_revision:
            self._ensure_direct_reaction_receipt(contact, app)
            return
        if existing is None and not self._can_store_pending_reaction(actor):
            return
        pending = self._reaction_pending_record(
            scope="direct", target_id=contact["id"], actor_destination=actor, app=app
        )
        receipt = self._direct_reaction_receipt_record(contact, app)
        deletions = self._direct_reaction_receipt_deletions(
            contact, app, receipt
        )
        self.store.put_and_delete(
            [
                ("pending_reaction", pending["id"], pending),
                ("message", receipt["id"], receipt),
            ],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt(receipt["id"])

    def _apply_received_direct_reaction(
        self, contact: dict[str, Any], actor: str, app: Any
    ) -> None:
        current = self._reaction_state(
            "direct", contact["id"], app.reaction_for, actor
        )
        if current is not None and int(current.get("revision", 0)) >= app.reaction_revision:
            self._ensure_direct_reaction_receipt(contact, app)
            return
        state = self._reaction_record(
            scope="direct",
            target_id=contact["id"],
            message_id=app.reaction_for,
            actor_destination=actor,
            emoji=app.reaction_emoji,
            active=app.reaction_active,
            revision=app.reaction_revision,
        )
        receipt = self._direct_reaction_receipt_record(contact, app)
        deletions = self._direct_reaction_receipt_deletions(
            contact, app, receipt
        )
        self.store.put_and_delete(
            [
                ("reaction", state["id"], state),
                ("message", receipt["id"], receipt),
            ],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt(receipt["id"])
        self._changed()

    def _receive_group_reaction(
        self,
        native: Any,
        app: Any,
        group: dict[str, Any],
        member: dict[str, Any],
    ) -> None:
        if (
            group.get("status") != "active"
            or app.group_epoch != group.get("epoch")
            or app.group_manifest_hash != group.get("manifest_hash")
        ):
            return
        actor = native.source_hash.hex()
        if member.get("destination_hash") != actor or member.get("status") != "active":
            return
        if self._message_was_discarded("group", group["id"], app.reaction_for):
            # A durable deletion marker deliberately retains no historical
            # manifest. A current member added after the target was sent must
            # not receive an acknowledgement that reveals the deleted UUID
            # existed. Endpoint evidence already terminates honest senders'
            # reaction retries, so silently ignoring is both private and safe.
            return
        target = self.store.get("group_message", app.reaction_for)
        if target is not None:
            try:
                entitled = self._reaction_target_destinations(group, target)
            except ValidationError:
                return
            if actor not in entitled:
                return
            self._apply_received_group_reaction(native, app, group, actor)
            return
        if self._reaction_target_is_hidden("group", group["id"]):
            return
        pending_id = self._pending_reaction_id(
            "group", group["id"], app.reaction_for, actor
        )
        existing = self.store.get("pending_reaction", pending_id)
        if existing is not None and int(existing.get("revision", 0)) >= app.reaction_revision:
            self._ensure_group_reaction_receipt(group, native.source_hash, app)
            return
        if existing is None and not self._can_store_pending_reaction(actor):
            return
        pending = self._reaction_pending_record(
            scope="group", target_id=group["id"], actor_destination=actor, app=app
        )
        receipt = self._group_reaction_receipt_record(
            group, native.source_hash, app
        )
        deletions = self._group_reaction_receipt_deletions(
            group, native.source_hash, app, receipt
        )
        self.store.put_and_delete(
            [
                ("pending_reaction", pending["id"], pending),
                ("group_delivery", receipt["id"], receipt),
            ],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt_group_delivery(receipt["id"])

    def _apply_received_group_reaction(
        self, native: Any, app: Any, group: dict[str, Any], actor: str
    ) -> None:
        current = self._reaction_state(
            "group", group["id"], app.reaction_for, actor
        )
        if current is not None and int(current.get("revision", 0)) >= app.reaction_revision:
            self._ensure_group_reaction_receipt(group, native.source_hash, app)
            return
        state = self._reaction_record(
            scope="group",
            target_id=group["id"],
            message_id=app.reaction_for,
            actor_destination=actor,
            emoji=app.reaction_emoji,
            active=app.reaction_active,
            revision=app.reaction_revision,
        )
        receipt = self._group_reaction_receipt_record(
            group, native.source_hash, app
        )
        deletions = self._group_reaction_receipt_deletions(
            group, native.source_hash, app, receipt
        )
        self.store.put_and_delete(
            [
                ("reaction", state["id"], state),
                ("group_delivery", receipt["id"], receipt),
            ],
            deletions,
        )
        self._cancel_reaction_operations({record_id for _, record_id in deletions})
        self._attempt_group_delivery(receipt["id"])
        self._changed()

    def _pending_reaction_changes(
        self,
        scope: str,
        target_id: str,
        message: dict[str, Any],
        *,
        group: dict[str, Any] | None = None,
    ) -> tuple[
        list[tuple[str, str, dict[str, Any]]], list[tuple[str, str]]
    ]:
        writes: list[tuple[str, str, dict[str, Any]]] = []
        deletions: list[tuple[str, str]] = []
        now = int(time.time())
        for pending in self.store.list("pending_reaction"):
            if (
                pending.get("scope") != scope
                or pending.get("target_id") != target_id
                or pending.get("message_id") != message["id"]
            ):
                continue
            deletions.append(("pending_reaction", pending["id"]))
            valid = (
                int(pending.get("expires_at", 0)) + REACTION_REPLAY_GRACE_SECONDS
                >= now
            )
            if scope == "direct":
                contact = self.store.get("contact", target_id)
                valid = bool(
                    valid
                    and contact is not None
                    and contact.get("destination_hash")
                    == pending.get("actor_destination")
                    and pending.get("conversation_id")
                    == message.get("conversation_id")
                )
            else:
                pending_member = (
                    None
                    if group is None
                    else self._group_member(
                        group,
                        pending.get("actor_destination", ""),
                        active_only=False,
                    )
                )
                try:
                    entitled = (
                        set()
                        if group is None
                        else self._reaction_target_destinations(group, message)
                    )
                except ValidationError:
                    entitled = set()
                valid = bool(
                    valid
                    and group is not None
                    and int(pending.get("group_epoch", -1))
                    == int(group.get("epoch", -2))
                    and pending.get("group_manifest_hash")
                    == group.get("manifest_hash")
                    and pending_member is not None
                    and pending_member.get("status") == "active"
                    and pending.get("actor_destination") in entitled
                )
            if not valid:
                continue
            current = self._reaction_state(
                scope,
                target_id,
                message["id"],
                pending["actor_destination"],
            )
            if current is not None and int(current.get("revision", 0)) >= int(
                pending.get("revision", 0)
            ):
                continue
            state = self._reaction_record(
                scope=scope,
                target_id=target_id,
                message_id=message["id"],
                actor_destination=pending["actor_destination"],
                emoji=pending["emoji"],
                active=pending["active"],
                revision=int(pending["revision"]),
                updated_at=float(pending.get("updated_at", time.time())),
            )
            writes.append(("reaction", state["id"], state))
        return writes, deletions

    def _reaction_deletions(
        self, scope: str, target_id: str
    ) -> list[tuple[str, str]]:
        return [
            (kind, record["id"])
            for kind in ("reaction", "pending_reaction")
            for record in self.store.list(kind)
            if record.get("scope") == scope
            and record.get("target_id") == target_id
        ]
