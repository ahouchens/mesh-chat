from __future__ import annotations

import base64
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import build_fields, conversation_id, parse_payload
from mesh_chat.errors import ContactNotApproved, ValidationError
from mesh_chat.group_protocol import (
    GroupManifestMemberInput,
    create_group_manifest,
    create_member_card,
    verify_group_manifest,
)
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import (
    Contact,
    DeliveryState,
    GroupRole,
    MessageKind,
    TrustState,
)
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class RecordingGroupNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.remembered: list[bytes] = []
        self.cancelled: list[set[str]] = []

    def invitation_hints(self) -> list[dict[str, Any]]:
        return []

    def remember_contact(self, _public_key: bytes, destination: bytes) -> None:
        self.remembered.append(destination)

    def recipient_ready(self, _destination: bytes) -> bool:
        return True

    def path_known(self, _destination: bytes) -> bool:
        return True

    def request_path(self, _destination: bytes) -> None:
        pass

    def send_with_fields(self, **value: Any) -> str:
        self.sent.append(value)
        return f"native-{len(self.sent)}"

    def apply_connection_settings(self, _settings: Any) -> None:
        pass

    def cancel_outbound(self, logical_ids: set[str]) -> int:
        self.cancelled.append(set(logical_ids))
        return len(logical_ids)

    def snapshot(self) -> dict[str, Any]:
        return {"interface_available": True, "interfaces": []}

    def shutdown(self) -> None:
        pass


def _profile(identity: RNS.Identity, display_name: str) -> dict[str, Any]:
    public_key = identity.get_public_key()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    return {
        "display_name": display_name,
        "public_identity": base64.urlsafe_b64encode(public_key).decode("ascii"),
        "identity_hash": identity.hash.hex(),
        "destination_hash": destination.hex(),
        "fingerprint": readable_fingerprint(public_key),
        "created_at": time.time(),
    }


def _contact(identity: RNS.Identity, display_name: str, contact_id: str) -> dict[str, Any]:
    profile = _profile(identity, display_name)
    return Contact(
        id=contact_id,
        display_name=display_name,
        public_identity=profile["public_identity"],
        identity_hash=profile["identity_hash"],
        destination_hash=profile["destination_hash"],
        fingerprint=profile["fingerprint"],
        trust=TrustState.APPROVED,
    ).to_dict()


def _service(
    root: Path,
    identity: RNS.Identity,
    display_name: str,
    contact: dict[str, Any] | list[dict[str, Any]],
) -> tuple[MeshChatService, RecordingGroupNetwork]:
    store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, root, lambda _event: None)
    service._shutdown.set()
    service._identity = identity
    store.put("profile", "local", _profile(identity, display_name))
    contacts = contact if isinstance(contact, list) else [contact]
    for item in contacts:
        store.put("contact", item["id"], item)
    network = RecordingGroupNetwork()
    service.network = network  # type: ignore[assignment]
    return service, network


def _native(
    sent: dict[str, Any], *, source: bytes, destination: bytes
) -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=sent["text"],
        fields=sent["fields"],
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=destination,
        source_hash=source,
    )


def _sent_kind(network: RecordingGroupNetwork, kind: str) -> dict[str, Any]:
    return next(
        value for value in reversed(network.sent) if parse_payload(
            _native(value, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind.value == kind
    )


def _sent_values(
    network: RecordingGroupNetwork,
    kind: str,
    *,
    recipient: bytes | None = None,
    epoch: int | None = None,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for sent in network.sent:
        if recipient is not None and sent["recipient_destination"] != recipient:
            continue
        parsed = parse_payload(
            _native(sent, source=b"\x00" * 16, destination=b"\x01" * 16)
        )
        if parsed.kind.value != kind:
            continue
        if epoch is not None and parsed.group_epoch != epoch:
            continue
        values.append(sent)
    return values


def _deliver(
    recipient: MeshChatService,
    sent: dict[str, Any],
    *,
    source_profile: dict[str, Any],
    destination_profile: dict[str, Any],
) -> None:
    recipient._on_inbound(
        _native(
            sent,
            source=bytes.fromhex(source_profile["destination_hash"]),
            destination=bytes.fromhex(destination_profile["destination_hash"]),
        )
    )


def _group_reaction_native(
    *,
    group: dict[str, Any],
    source_profile: dict[str, Any],
    destination_profile: dict[str, Any],
    target_id: str,
    logical_id: str | None = None,
    event_id: str | None = None,
    emoji: str = "👍",
    active: bool = True,
    revision: int = 1,
) -> LXMF.LXMessage:
    source = bytes.fromhex(source_profile["destination_hash"])
    destination = bytes.fromhex(destination_profile["destination_hash"])
    return LXMF.LXMessage(
        None,
        None,
        content="",
        fields=build_fields(
            kind=MessageKind.GROUP_REACTION,
            logical_id=logical_id or str(uuid.uuid4()),
            conversation=conversation_id(source, destination),
            expires_at=int(time.time()) + 60,
            group_id=group["id"],
            group_epoch=int(group["epoch"]),
            group_manifest_hash=group["manifest_hash"],
            group_message_id=event_id or str(uuid.uuid4()),
            reaction_for=target_id,
            reaction_emoji=emoji,
            reaction_active=active,
            reaction_revision=revision,
        ),
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=destination,
        source_hash=source,
    )


@dataclass
class JoinedPair:
    owner: MeshChatService
    owner_network: RecordingGroupNetwork
    owner_identity: RNS.Identity
    owner_profile: dict[str, Any]
    member: MeshChatService
    member_network: RecordingGroupNetwork
    member_identity: RNS.Identity
    member_profile: dict[str, Any]
    group_id: str
    accept_wire: dict[str, Any]

    def close(self) -> None:
        self.owner.close()
        self.member.close()


def _joined_pair(root: Path, posting_policy: str = "members") -> JoinedPair:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    owner_profile = _profile(owner_identity, "Alex")
    member_profile = _profile(member_identity, "Bailey")
    owner, owner_network = _service(
        root / "owner",
        owner_identity,
        "Alex",
        _contact(member_identity, "Bailey", "bailey"),
    )
    member, member_network = _service(
        root / "member",
        member_identity,
        "Bailey",
        _contact(owner_identity, "Alex", "alex"),
    )
    created = owner.create_group("Farm operations", ["bailey"], posting_policy)
    invite = _sent_values(
        owner_network,
        "group_invite",
        recipient=bytes.fromhex(member_profile["destination_hash"]),
    )[-1]
    _deliver(
        member,
        invite,
        source_profile=owner_profile,
        destination_profile=member_profile,
    )
    invitation = member.snapshot()["group_invitations"][0]
    member.accept_group_invitation(invitation["id"])
    accept = _sent_values(
        member_network,
        "group_accept",
        recipient=bytes.fromhex(owner_profile["destination_hash"]),
    )[-1]
    _deliver(
        owner,
        accept,
        source_profile=member_profile,
        destination_profile=owner_profile,
    )
    manifest = _sent_values(
        owner_network,
        "group_manifest",
        recipient=bytes.fromhex(member_profile["destination_hash"]),
        epoch=2,
    )[-1]
    _deliver(
        member,
        manifest,
        source_profile=owner_profile,
        destination_profile=member_profile,
    )
    assert member.snapshot()["groups"][0]["status"] == "active"
    return JoinedPair(
        owner=owner,
        owner_network=owner_network,
        owner_identity=owner_identity,
        owner_profile=owner_profile,
        member=member,
        member_network=member_network,
        member_identity=member_identity,
        member_profile=member_profile,
        group_id=created["id"],
        accept_wire=accept,
    )


def test_group_invite_join_fanout_and_per_member_receipt(tmp_path: Path) -> None:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    owner_profile = _profile(owner_identity, "Alex")
    member_profile = _profile(member_identity, "Bailey")
    owner, owner_network = _service(
        tmp_path / "owner",
        owner_identity,
        "Alex",
        _contact(member_identity, "Bailey", "bailey"),
    )
    member, member_network = _service(
        tmp_path / "member",
        member_identity,
        "Bailey",
        _contact(owner_identity, "Alex", "alex"),
    )
    try:
        created = owner.create_group("Farm operations", ["bailey"], "members")
        assert created["epoch"] == 1
        assert [item["status"] for item in created["members"]] == ["active", "invited"]

        invite_wire = _sent_kind(owner_network, "group_invite")
        member._on_inbound(
            _native(
                invite_wire,
                source=bytes.fromhex(owner_profile["destination_hash"]),
                destination=bytes.fromhex(member_profile["destination_hash"]),
            )
        )
        invitation = member.snapshot()["group_invitations"][0]
        assert invitation["title"] == "Farm operations"
        assert invitation["owner_display_name"] == "Alex"

        joining = member.accept_group_invitation(invitation["id"])
        assert joining["status"] == "joining"
        accept_wire = _sent_kind(member_network, "group_accept")
        owner._on_inbound(
            _native(
                accept_wire,
                source=bytes.fromhex(member_profile["destination_hash"]),
                destination=bytes.fromhex(owner_profile["destination_hash"]),
            )
        )
        owner_group = owner.snapshot()["groups"][0]
        assert owner_group["epoch"] == 2
        assert len([m for m in owner_group["members"] if m["status"] == "active"]) == 2

        manifest_wire = _sent_kind(owner_network, "group_manifest")
        member._on_inbound(
            _native(
                manifest_wire,
                source=bytes.fromhex(owner_profile["destination_hash"]),
                destination=bytes.fromhex(member_profile["destination_hash"]),
            )
        )
        assert member.snapshot()["groups"][0]["status"] == "active"

        outbound = owner.send_group_message(created["id"], "Gate is secured")
        assert outbound["delivery_summary"] == {
            "total": 1,
            "delivered": 0,
            "pending": 1,
            "failed": 0,
            "expired": 0,
        }
        chat_wire = _sent_kind(owner_network, "group_chat")
        member._on_inbound(
            _native(
                chat_wire,
                source=bytes.fromhex(owner_profile["destination_hash"]),
                destination=bytes.fromhex(member_profile["destination_hash"]),
            )
        )
        received = member.snapshot()["group_messages"][0]
        assert received["text"] == "Gate is secured"
        assert received["sender_display_name"] == "Alex"

        receipt_wire = _sent_kind(member_network, "group_receipt")
        owner._on_inbound(
            _native(
                receipt_wire,
                source=bytes.fromhex(member_profile["destination_hash"]),
                destination=bytes.fromhex(owner_profile["destination_hash"]),
            )
        )
        delivered = owner.snapshot()["group_messages"][0]
        assert delivered["delivery_summary"]["delivered"] == 1
        assert delivered["delivery_summary"]["pending"] == 0
    finally:
        owner.close()
        member.close()


def test_delete_group_history_preserves_membership_and_reopens_for_fresh_inbound(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        first = pair.owner.send_group_message(pair.group_id, "Old gate report")
        first_wire = _sent_values(
            pair.owner_network,
            "group_chat",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.member,
            first_wire,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        pair.member.save_group_draft(pair.group_id, "unfinished note")
        before = pair.member.store.get("group", pair.group_id)

        result = pair.member.delete_conversation("group", pair.group_id)

        assert result == {
            "kind": "group",
            "id": pair.group_id,
            "deleted_messages": 1,
        }
        assert pair.member.store.get("group", pair.group_id) == before
        assert pair.member.store.get("group_message", first["id"]) is None
        assert pair.member.store.get("group_draft", pair.group_id) is None
        snapshot = pair.member.snapshot()
        assert snapshot["group_messages"] == []
        assert snapshot["hidden_conversations"] == [
            {"kind": "group", "id": pair.group_id}
        ]

        # Reticulum may redeliver a packet already handed off before local
        # deletion. The short-lived marker acknowledges it without resurrecting
        # text or making the hidden conversation reappear.
        _deliver(
            pair.member,
            first_wire,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        assert pair.member.snapshot()["group_messages"] == []
        assert pair.member.snapshot()["hidden_conversations"]

        second = pair.owner.send_group_message(pair.group_id, "Fresh gate report")
        second_wire = _sent_values(
            pair.owner_network,
            "group_chat",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.member,
            second_wire,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        reopened = pair.member.snapshot()
        assert [message["id"] for message in reopened["group_messages"]] == [second["id"]]
        assert reopened["hidden_conversations"] == []
        assert reopened["groups"][0]["id"] == pair.group_id
    finally:
        pair.close()


def test_delete_group_conversation_cancels_only_chat_outbox(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        request = {
            "v": 1,
            "id": "group-send-before-delete",
            "command": "send_group_message",
            "payload": {
                "group_id": pair.group_id,
                "text": "Queued private report",
            },
        }
        response, _ = pair.owner.dispatch(request)
        assert response["ok"] is True
        chat_before = [
            delivery["id"]
            for delivery in pair.owner.store.list("group_delivery")
            if delivery.get("group_id") == pair.group_id
            and delivery.get("kind") == MessageKind.GROUP_CHAT.value
        ]
        assert chat_before
        assert any(
            delivery.get("group_id") == pair.group_id
            and delivery.get("kind") == MessageKind.GROUP_CHAT.value
            for delivery in pair.owner.store.list("group_delivery")
        )
        control_before = [
            delivery["id"]
            for delivery in pair.owner.store.list("group_delivery")
            if delivery.get("group_id") == pair.group_id
            and delivery.get("kind") != MessageKind.GROUP_CHAT.value
        ]

        pair.owner.delete_conversation("group", pair.group_id)

        replay, _ = pair.owner.dispatch(request)
        assert replay["ok"] is False
        assert replay["error"]["code"] == "command_result_deleted"

        deliveries = pair.owner.store.list("group_delivery")
        assert not any(
            delivery.get("group_id") == pair.group_id
            and delivery.get("kind") == MessageKind.GROUP_CHAT.value
            for delivery in deliveries
        )
        assert all(
            pair.owner.store.get("group_delivery", delivery_id) is not None
            for delivery_id in control_before
        )
        assert pair.owner.store.list("group_message") == []
        assert pair.owner.store.get("group", pair.group_id) is not None
        assert pair.owner_network.cancelled[-1] == set(chat_before)
        assert not set(control_before) & pair.owner_network.cancelled[-1]

        pair.owner.restore_conversation("group", pair.group_id)
        sent = pair.owner.send_group_message(pair.group_id, "Replacement report")
        assert sent["sender_sequence"] == 2
        assert pair.owner.snapshot()["hidden_conversations"] == []
    finally:
        pair.close()


def test_group_invite_receipt_and_manual_retry_report_phone_state(tmp_path: Path) -> None:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    owner_profile = _profile(owner_identity, "Alex")
    member_profile = _profile(member_identity, "Bailey")
    owner, owner_network = _service(
        tmp_path / "owner",
        owner_identity,
        "Alex",
        _contact(member_identity, "Bailey", "bailey"),
    )
    member, member_network = _service(
        tmp_path / "member",
        member_identity,
        "Bailey",
        _contact(owner_identity, "Alex", "alex"),
    )
    try:
        created = owner.create_group("Farm operations", ["bailey"], "members")
        pending = next(item for item in created["members"] if item["status"] == "invited")
        assert pending["invite_delivery_state"] == "sending"
        assert pending["invite_attempt_count"] == 1

        owner.retry_group_invitation(created["id"], member_profile["destination_hash"])
        invites = _sent_values(
            owner_network,
            "group_invite",
            recipient=bytes.fromhex(member_profile["destination_hash"]),
        )
        assert len(invites) == 2
        retried = owner.snapshot()["groups"][0]
        retried_member = next(
            item for item in retried["members"] if item["status"] == "invited"
        )
        assert retried_member["invite_attempt_count"] == 2

        _deliver(
            member,
            invites[-1],
            source_profile=owner_profile,
            destination_profile=member_profile,
        )
        receipt = _sent_values(
            member_network,
            "group_receipt",
            recipient=bytes.fromhex(owner_profile["destination_hash"]),
        )[-1]
        _deliver(
            owner,
            receipt,
            source_profile=member_profile,
            destination_profile=owner_profile,
        )
        ready = owner.snapshot()["groups"][0]
        ready_member = next(
            item for item in ready["members"] if item["status"] == "invited"
        )
        assert ready_member["invite_delivery_state"] == "delivered"

        sent_before = len(owner_network.sent)
        owner.retry_group_invitation(created["id"], member_profile["destination_hash"])
        assert len(owner_network.sent) == sent_before
    finally:
        owner.close()
        member.close()


def test_announcement_channel_rejects_member_posting(tmp_path: Path) -> None:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "owner",
        owner_identity,
        "Alex",
        _contact(member_identity, "Bailey", "bailey"),
    )
    try:
        channel = owner.create_group(
            "Farm announcements", ["bailey"], "owner_admins"
        )
        assert channel["posting_policy"] == "owner_admins"
    finally:
        owner.close()


def test_two_invitees_catch_up_when_manifests_arrive_out_of_order(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    first_identity = RNS.Identity()
    second_identity = RNS.Identity()
    owner_profile = _profile(owner_identity, "Alex")
    first_profile = _profile(first_identity, "Bailey")
    second_profile = _profile(second_identity, "Casey")
    owner, owner_network = _service(
        tmp_path / "owner",
        owner_identity,
        "Alex",
        [
            _contact(first_identity, "Bailey", "bailey"),
            _contact(second_identity, "Casey", "casey"),
        ],
    )
    first, first_network = _service(
        tmp_path / "first",
        first_identity,
        "Bailey",
        _contact(owner_identity, "Alex", "alex"),
    )
    second, second_network = _service(
        tmp_path / "second",
        second_identity,
        "Casey",
        _contact(owner_identity, "Alex", "alex"),
    )
    try:
        created = owner.create_group(
            "Farm operations", ["bailey", "casey"], "members"
        )
        for service, profile in (
            (first, first_profile),
            (second, second_profile),
        ):
            invite = _sent_values(
                owner_network,
                "group_invite",
                recipient=bytes.fromhex(profile["destination_hash"]),
            )[-1]
            _deliver(
                service,
                invite,
                source_profile=owner_profile,
                destination_profile=profile,
            )
            invitation = service.snapshot()["group_invitations"][0]
            service.accept_group_invitation(invitation["id"])

        first_accept = _sent_values(
            first_network,
            "group_accept",
            recipient=bytes.fromhex(owner_profile["destination_hash"]),
        )[-1]
        _deliver(
            owner,
            first_accept,
            source_profile=first_profile,
            destination_profile=owner_profile,
        )
        assert owner.snapshot()["groups"][0]["epoch"] == 2

        second_accept = _sent_values(
            second_network,
            "group_accept",
            recipient=bytes.fromhex(owner_profile["destination_hash"]),
        )[-1]
        _deliver(
            owner,
            second_accept,
            source_profile=second_profile,
            destination_profile=owner_profile,
        )
        assert owner.snapshot()["groups"][0]["epoch"] == 3

        catch_up = _sent_values(
            owner_network,
            "group_manifest",
            recipient=bytes.fromhex(second_profile["destination_hash"]),
        )
        catch_up_by_epoch = {
            parse_payload(
                _native(
                    sent,
                    source=bytes.fromhex(owner_profile["destination_hash"]),
                    destination=bytes.fromhex(second_profile["destination_hash"]),
                )
            ).group_epoch: sent
            for sent in catch_up
        }
        assert sorted(catch_up_by_epoch) == [2, 3]

        _deliver(
            second,
            catch_up_by_epoch[3],
            source_profile=owner_profile,
            destination_profile=second_profile,
        )
        waiting = second.snapshot()["groups"][0]
        assert waiting["epoch"] == 1
        assert waiting["status"] == "joining"
        assert len(second.store.list("group_pending_manifest")) == 1

        _deliver(
            second,
            catch_up_by_epoch[2],
            source_profile=owner_profile,
            destination_profile=second_profile,
        )
        caught_up = second.snapshot()["groups"][0]
        assert caught_up["id"] == created["id"]
        assert caught_up["epoch"] == 3
        assert caught_up["status"] == "active"
        assert len(
            [member for member in caught_up["members"] if member["status"] == "active"]
        ) == 3
        assert second.store.list("group_pending_manifest") == []
    finally:
        owner.close()
        first.close()
        second.close()


def test_accepted_invite_replay_after_removal_cannot_readmit_member(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        pair.owner.remove_group_member(
            pair.group_id, pair.member_profile["destination_hash"]
        )
        removed = pair.owner.snapshot()["groups"][0]
        assert removed["epoch"] == 3
        assert not any(
            member["destination_hash"] == pair.member_profile["destination_hash"]
            and member["status"] == "active"
            for member in removed["members"]
        )

        _deliver(
            pair.owner,
            pair.accept_wire,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
        )
        after_replay = pair.owner.snapshot()["groups"][0]
        assert after_replay["epoch"] == 3
        assert after_replay["manifest_hash"] == removed["manifest_hash"]
        assert not any(
            member["destination_hash"] == pair.member_profile["destination_hash"]
            and member["status"] == "active"
            for member in after_replay["members"]
        )
    finally:
        pair.close()


def test_owner_removal_transitions_removed_member_locally(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        owner_group = pair.owner.remove_group_member(
            pair.group_id, pair.member_profile["destination_hash"]
        )
        assert owner_group["epoch"] == 3
        assert all(
            member["destination_hash"] != pair.member_profile["destination_hash"]
            for member in owner_group["members"]
        )
        removal = _sent_values(
            pair.owner_network,
            "group_manifest",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
            epoch=3,
        )[-1]
        _deliver(
            pair.member,
            removal,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        local = pair.member.snapshot()["groups"][0]
        assert local["epoch"] == 3
        assert local["status"] == "removed"
        assert local["local_role"] is None
    finally:
        pair.close()


def test_member_leave_request_removes_member_and_clears_pending_state(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        local = pair.member.leave_group(pair.group_id)
        assert local["status"] == "removed"
        assert local["leave_pending"] is True
        leave = _sent_values(
            pair.member_network,
            "group_leave_request",
            recipient=bytes.fromhex(pair.owner_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.owner,
            leave,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
        )
        owner_group = pair.owner.snapshot()["groups"][0]
        assert owner_group["epoch"] == 3
        assert all(
            member["destination_hash"] != pair.member_profile["destination_hash"]
            for member in owner_group["members"]
        )

        removal = _sent_values(
            pair.owner_network,
            "group_manifest",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
            epoch=3,
        )[-1]
        _deliver(
            pair.member,
            removal,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        completed = pair.member.snapshot()["groups"][0]
        assert completed["status"] == "removed"
        assert completed["leave_pending"] is False
        leave_delivery = next(
            delivery
            for delivery in pair.member.store.list("group_delivery")
            if delivery["kind"] == "group_leave_request"
        )
        assert leave_delivery["state"] == "delivered"
    finally:
        pair.close()


def test_owner_close_transitions_every_member_to_closed(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        owner_group = pair.owner.close_group(pair.group_id)
        assert owner_group["status"] == "closed"
        assert owner_group["epoch"] == 3
        closing = _sent_values(
            pair.owner_network,
            "group_manifest",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
            epoch=3,
        )[-1]
        _deliver(
            pair.member,
            closing,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        member_group = pair.member.snapshot()["groups"][0]
        assert member_group["status"] == "closed"
        assert member_group["epoch"] == 3
        assert member_group["local_role"] == "member"
    finally:
        pair.close()


def test_conflicting_older_epoch_manifest_freezes_group(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        owner_group = pair.owner.store.get("group", pair.group_id)
        assert owner_group is not None
        epoch_one_record = next(
            record
            for record in pair.owner.store.list("group_manifest")
            if record["group_id"] == pair.group_id and record["epoch"] == 1
        )
        epoch_one = verify_group_manifest(
            epoch_one_record["serialized"],
            expected_group_id=pair.group_id,
            expected_owner_destination=bytes.fromhex(
                pair.owner_profile["destination_hash"]
            ),
        )
        conflicting_raw = create_group_manifest(
            pair.owner_identity,
            group_id=pair.group_id,
            epoch=epoch_one.epoch,
            previous_manifest_hash=epoch_one.previous_manifest_hash,
            title="Conflicting farm operations",
            posting_policy=epoch_one.posting_policy,
            members=[
                GroupManifestMemberInput(member.card.serialized, member.role)
                for member in epoch_one.members
            ],
        )
        conflicting = verify_group_manifest(
            conflicting_raw,
            expected_group_id=pair.group_id,
            expected_owner_destination=bytes.fromhex(
                pair.owner_profile["destination_hash"]
            ),
        )
        assert conflicting.digest != epoch_one.digest
        recipient = pair.owner._group_member(
            owner_group, pair.member_profile["destination_hash"]
        )
        assert recipient is not None
        delivery = pair.owner._delivery_record(
            group=owner_group,
            recipient=recipient,
            kind=MessageKind.GROUP_MANIFEST,
            document=conflicting.serialized,
            group_message_id=str(uuid.uuid4()),
            epoch=conflicting.epoch,
            manifest_hash=conflicting.digest,
        )
        pair.owner.store.put("group_delivery", delivery["id"], delivery)
        pair.owner._attempt_group_delivery(delivery["id"])
        equivocation = _sent_values(
            pair.owner_network,
            "group_manifest",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
            epoch=1,
        )[-1]
        _deliver(
            pair.member,
            equivocation,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )

        frozen = pair.member.snapshot()["groups"][0]
        assert frozen["epoch"] == 2
        assert frozen["status"] == "forked"
        assert frozen["security_warning"] == "conflicting_membership_manifest"
        evidence = pair.member.store.list("group_fork_evidence")
        assert len(evidence) == 1
        assert evidence[0]["epoch"] == 1
        assert sorted(evidence[0]["known_digests"]) == sorted(
            [epoch_one.digest, conflicting.digest]
        )
    finally:
        pair.close()


def test_terminal_failed_group_delivery_survives_recovery(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "Check the north gate")
        delivery = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("group_message_id") == message["id"]
            and item["kind"] == "group_chat"
        )
        pair.owner._on_group_native_status(
            delivery["id"],
            DeliveryState.FAILED,
            delivery["native_message_id"],
        )
        failed = pair.owner.store.get("group_delivery", delivery["id"])
        assert failed is not None
        attempts = failed["attempt_count"]
        sent_count = sum(
            sent["logical_id"] == delivery["id"]
            for sent in pair.owner_network.sent
        )

        pair.owner._recover_group_outbox()
        pair.owner._retry_group_outbox()

        recovered = pair.owner.store.get("group_delivery", delivery["id"])
        assert recovered is not None
        assert recovered["state"] == "failed"
        assert recovered["attempt_count"] == attempts
        assert recovered["native_message_id"] == delivery["native_message_id"]
        assert sum(
            sent["logical_id"] == delivery["id"]
            for sent in pair.owner_network.sent
        ) == sent_count
    finally:
        pair.close()


def test_endpoint_received_group_chat_retries_until_app_receipt(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "Water trough is full")
        delivery = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("group_message_id") == message["id"]
            and item["kind"] == "group_chat"
        )
        pair.owner._on_group_native_status(
            delivery["id"],
            DeliveryState.RECEIVED_BY_ENDPOINT,
            delivery["native_message_id"],
        )
        endpoint_received = pair.owner.store.get("group_delivery", delivery["id"])
        assert endpoint_received is not None
        assert endpoint_received["state"] == "received_by_endpoint"
        assert message["delivery_summary"]["delivered"] == 0

        attempts = endpoint_received["attempt_count"]
        endpoint_received["next_attempt_at"] = 0
        pair.owner.store.put("group_delivery", delivery["id"], endpoint_received)
        before_retry = len(pair.owner_network.sent)
        pair.owner._retry_group_outbox()

        retried = pair.owner.store.get("group_delivery", delivery["id"])
        assert retried is not None
        assert retried["state"] == "sending"
        assert retried["attempt_count"] == attempts + 1
        assert len(pair.owner_network.sent) == before_retry + 1
        public = next(
            item
            for item in pair.owner.snapshot()["group_messages"]
            if item["id"] == message["id"]
        )
        assert public["delivery_summary"]["delivered"] == 0
        assert public["delivery_summary"]["pending"] == 1
    finally:
        pair.close()


def test_duplicate_group_message_with_metadata_mismatch_is_not_acknowledged(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "Original gate report")
        chat = _sent_values(
            pair.owner_network,
            "group_chat",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.member,
            chat,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        receipts_before = _sent_values(pair.member_network, "group_receipt")
        receipt_records_before = [
            item
            for item in pair.member.store.list("group_delivery")
            if item["kind"] == "group_receipt"
        ]
        assert len(receipts_before) == 3  # invite, manifest and chat receipts
        assert len(receipt_records_before) == 3

        mismatched = dict(chat)
        mismatched["text"] = "Rewritten gate report"
        _deliver(
            pair.member,
            mismatched,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )

        inbound = next(
            item
            for item in pair.member.snapshot()["group_messages"]
            if item["id"] == message["id"]
        )
        assert inbound["text"] == "Original gate report"
        assert len(_sent_values(pair.member_network, "group_receipt")) == len(
            receipts_before
        )
        receipt_records_after = [
            item
            for item in pair.member.store.list("group_delivery")
            if item["kind"] == "group_receipt"
        ]
        assert len(receipt_records_after) == len(receipt_records_before)
    finally:
        pair.close()


def test_group_reactions_cross_devices_replace_reverse_order_and_cleanup(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "South field complete")
        chat = _sent_values(
            pair.owner_network,
            "group_chat",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.member,
            chat,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        assert pair.member.snapshot()["group_messages"][0]["reactions"] == []

        pair.member.set_message_reaction("group", message["id"], "👍", True)
        first = _sent_values(
            pair.member_network,
            "group_reaction",
            recipient=bytes.fromhex(pair.owner_profile["destination_hash"]),
        )[-1]
        _deliver(
            pair.owner,
            first,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
        )
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == [
            {"emoji": "👍", "count": 1, "reacted_by_self": False}
        ]

        # The later revision arrives first. The stale first revision is still
        # receipted but cannot restore its older emoji.
        pair.member.set_message_reaction("group", message["id"], "😂", True)
        pair.member.set_message_reaction("group", message["id"], "❤️", True)
        updates = _sent_values(
            pair.member_network,
            "group_reaction",
            recipient=bytes.fromhex(pair.owner_profile["destination_hash"]),
        )[-2:]
        for wire in reversed(updates):
            _deliver(
                pair.owner,
                wire,
                source_profile=pair.member_profile,
                destination_profile=pair.owner_profile,
            )
        owner_reactions = pair.owner.snapshot()["group_messages"][0]["reactions"]
        assert owner_reactions == [
            {"emoji": "❤️", "count": 1, "reacted_by_self": False}
        ]

        # Deliver every generated app receipt. Superseded delivery IDs are
        # harmless; the current operation is securely removed on its receipt.
        for receipt in _sent_values(
            pair.owner_network,
            "group_receipt",
            recipient=bytes.fromhex(pair.member_profile["destination_hash"]),
        ):
            _deliver(
                pair.member,
                receipt,
                source_profile=pair.owner_profile,
                destination_profile=pair.member_profile,
            )
        remaining_reactions = [
            delivery
            for delivery in pair.member.store.list("group_delivery")
            if delivery.get("kind") == MessageKind.GROUP_REACTION.value
        ]
        assert not remaining_reactions, remaining_reactions
        local_states = [
            item
            for item in pair.member.store.list("reaction")
            if item.get("scope") == "group"
            and item.get("message_id") == message["id"]
        ]
        assert len(local_states) == 1
        assert local_states[0]["emoji"] == "❤️"
        assert local_states[0]["revision"] == 3

        pair.member.set_message_reaction("group", message["id"], "❤️", False)
        removal = _sent_values(pair.member_network, "group_reaction")[-1]
        _deliver(
            pair.owner,
            removal,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
        )
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == []
        before = len(_sent_values(pair.member_network, "group_reaction"))
        pair.member.set_message_reaction("group", message["id"], "❤️", False)
        assert len(_sent_values(pair.member_network, "group_reaction")) == before
    finally:
        pair.close()


def test_group_reaction_can_overtake_target_and_survives_as_pending(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "New irrigation plan")
        chat = _sent_values(pair.owner_network, "group_chat")[-1]
        pair.owner.set_message_reaction("group", message["id"], "🎉", True)
        reaction = _sent_values(pair.owner_network, "group_reaction")[-1]

        _deliver(
            pair.member,
            reaction,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        assert len(pair.member.store.list("pending_reaction")) == 1
        assert pair.member.snapshot()["group_messages"] == []

        _deliver(
            pair.member,
            chat,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        assert pair.member.store.list("pending_reaction") == []
        assert pair.member.snapshot()["group_messages"][0]["reactions"] == [
            {"emoji": "🎉", "count": 1, "reacted_by_self": False}
        ]
    finally:
        pair.close()


def test_announcement_member_may_react_but_cannot_post(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path, "owner_admins")
    try:
        message = pair.owner.send_group_message(pair.group_id, "Owner announcement")
        chat = _sent_values(pair.owner_network, "group_chat")[-1]
        _deliver(
            pair.member,
            chat,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        with pytest.raises(ContactNotApproved, match="owner or an admin"):
            pair.member.send_group_message(pair.group_id, "not allowed")

        result = pair.member.set_message_reaction(
            "group", message["id"], "🧑🏽\u200d🌾", True
        )
        assert result["active"] is True
        reaction = _sent_values(pair.member_network, "group_reaction")[-1]
        _deliver(
            pair.owner,
            reaction,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
        )
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == [
            {"emoji": "🧑🏽\u200d🌾", "count": 1, "reacted_by_self": False}
        ]
    finally:
        pair.close()


def test_removed_group_member_reaction_is_ignored(tmp_path: Path) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "Membership target")
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        member = next(
            item
            for item in group["members"]
            if item["destination_hash"] == pair.member_profile["destination_hash"]
        )
        member["status"] = "removed"
        pair.owner.store.put("group", pair.group_id, group)
        member_group = pair.member.store.get("group", pair.group_id)
        assert member_group is not None
        fields = pair.member._delivery_record(
            group=member_group,
            recipient=next(
                item
                for item in member_group["members"]
                if item["destination_hash"] == pair.owner_profile["destination_hash"]
            ),
            kind=MessageKind.GROUP_REACTION,
            group_message_id=str(uuid.uuid4()),
            reaction_for=message["id"],
            reaction_emoji="😮",
            reaction_active=True,
            reaction_revision=1,
        )
        # Build the authenticated app shape directly; the owner must derive the
        # actor only from the native source and reject its non-active roster row.
        native = LXMF.LXMessage(
            None,
            None,
            content="",
            fields=build_fields(
                kind=MessageKind.GROUP_REACTION,
                logical_id=fields["id"],
                conversation=fields["conversation_id"],
                expires_at=int(fields["expires_at"]),
                group_id=pair.group_id,
                group_epoch=int(fields["group_epoch"]),
                group_manifest_hash=fields["group_manifest_hash"],
                group_message_id=fields["group_message_id"],
                reaction_for=message["id"],
                reaction_emoji="😮",
                reaction_active=True,
                reaction_revision=1,
            ),
            desired_method=LXMF.LXMessage.DIRECT,
            destination_hash=bytes.fromhex(pair.owner_profile["destination_hash"]),
            source_hash=bytes.fromhex(pair.member_profile["destination_hash"]),
        )
        pair.owner._on_inbound(native)
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == []
        assert not any(
            item.get("reaction_receipt") is True
            and item.get("receipt_for") == fields["id"]
            for item in pair.owner.store.list("group_delivery")
        )
    finally:
        pair.close()


def test_group_reaction_endpoint_evidence_is_final_but_chat_still_retries(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        message = pair.owner.send_group_message(pair.group_id, "Compatibility target")
        reaction_result = pair.owner.set_message_reaction(
            "group", message["id"], "👍", True
        )
        assert reaction_result["active"] is True
        reaction_delivery = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("kind") == MessageKind.GROUP_REACTION.value
        )
        reaction_sent_count = len(_sent_values(pair.owner_network, "group_reaction"))
        pair.owner._on_native_status(
            reaction_delivery["id"],
            DeliveryState.RECEIVED_BY_ENDPOINT,
            reaction_delivery["native_message_id"],
        )
        assert pair.owner.store.get("group_delivery", reaction_delivery["id"]) is None
        pair.owner._retry_group_outbox()
        assert len(_sent_values(pair.owner_network, "group_reaction")) == reaction_sent_count

        chat_delivery = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("kind") == MessageKind.GROUP_CHAT.value
            and item.get("group_message_id") == message["id"]
        )
        pair.owner._on_native_status(
            chat_delivery["id"],
            DeliveryState.RECEIVED_BY_ENDPOINT,
            chat_delivery["native_message_id"],
        )
        retained = pair.owner.store.get("group_delivery", chat_delivery["id"])
        assert retained is not None
        retained["next_attempt_at"] = 0
        pair.owner.store.put("group_delivery", retained["id"], retained)
        before_chat_retry = len(_sent_values(pair.owner_network, "group_chat"))
        pair.owner._retry_group_outbox()
        assert len(_sent_values(pair.owner_network, "group_chat")) == before_chat_retry + 1
    finally:
        pair.close()


def test_new_member_cannot_react_to_historical_target_but_retained_member_can(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        target = pair.owner.send_group_message(pair.group_id, "Historical target")
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        current = verify_group_manifest(
            group["manifest"],
            expected_group_id=pair.group_id,
            expected_owner_destination=bytes.fromhex(
                pair.owner_profile["destination_hash"]
            ),
        )
        newcomer_identity = RNS.Identity()
        newcomer_profile = _profile(newcomer_identity, "Casey")
        newcomer_card = create_member_card(
            newcomer_identity,
            "Casey",
            group_id=pair.group_id,
        )
        raw = create_group_manifest(
            pair.owner_identity,
            group_id=pair.group_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            title=current.title,
            posting_policy=current.posting_policy,
            members=[
                *[
                    GroupManifestMemberInput(member.card.serialized, member.role)
                    for member in current.members
                ],
                GroupManifestMemberInput(newcomer_card, GroupRole.MEMBER),
            ],
        )
        updated = verify_group_manifest(
            raw,
            expected_group_id=pair.group_id,
            expected_owner_destination=bytes.fromhex(
                pair.owner_profile["destination_hash"]
            ),
            expected_previous_hash=current.digest,
            expected_epoch=current.epoch + 1,
        )
        group = pair.owner._apply_group_manifest(
            group, updated, keep_pending=False
        )
        pair.owner.store.put_many(
            [
                ("group", pair.group_id, group),
                (
                    "group_manifest",
                    updated.digest,
                    {
                        "group_id": pair.group_id,
                        "epoch": updated.epoch,
                        "digest": updated.digest,
                        "serialized": updated.serialized,
                    },
                ),
            ]
        )

        pair.owner._on_inbound(
            _group_reaction_native(
                group=group,
                source_profile=newcomer_profile,
                destination_profile=pair.owner_profile,
                target_id=target["id"],
            )
        )
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == []
        assert not any(
            item.get("reaction_actor") == newcomer_profile["destination_hash"]
            for item in pair.owner.store.list("group_delivery")
        )

        pair.owner._on_inbound(
            _group_reaction_native(
                group=group,
                source_profile=pair.member_profile,
                destination_profile=pair.owner_profile,
                target_id=target["id"],
            )
        )
        assert pair.owner.snapshot()["group_messages"][0]["reactions"] == [
            {"emoji": "👍", "count": 1, "reacted_by_self": False}
        ]

        # Renderer IPC uses the same historical entitlement rule. The owner
        # can still react, but fanout excludes the newly-added member.
        pair.owner.set_message_reaction("group", target["id"], "🎉", True)
        reaction_recipients = {
            item["recipient_destination"]
            for item in pair.owner.store.list("group_delivery")
            if item.get("kind") == MessageKind.GROUP_REACTION.value
        }
        assert reaction_recipients == {pair.member_profile["destination_hash"]}
    finally:
        pair.close()


def test_group_reaction_rebinds_to_new_epoch_for_still_entitled_member(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        target = pair.owner.send_group_message(pair.group_id, "Epoch target")
        pair.owner.set_message_reaction("group", target["id"], "😮", True)
        delivery = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("kind") == MessageKind.GROUP_REACTION.value
        )
        old_native = delivery["native_message_id"]
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        group["epoch"] = int(group["epoch"]) + 1
        group["manifest_hash"] = "ab" * 32
        recipient = next(
            item
            for item in group["members"]
            if item["destination_hash"] == pair.member_profile["destination_hash"]
        )
        recipient["display_name"] = "Bailey Updated"
        recipient["connection_hints"] = [
            {"type": "tcp", "host": "192.0.2.44", "port": 4242}
        ]
        pair.owner.store.put("group", pair.group_id, group)

        # Evidence from the pre-update native attempt cannot complete the job.
        pair.owner._on_native_status(
            delivery["id"], DeliveryState.RECEIVED_BY_ENDPOINT, old_native
        )
        assert pair.owner.store.get("group_delivery", delivery["id"]) is not None

        delivery = pair.owner.store.get("group_delivery", delivery["id"])
        assert delivery is not None
        delivery["next_attempt_at"] = 0
        pair.owner.store.put("group_delivery", delivery["id"], delivery)
        pair.owner._retry_group_delivery_if_due(delivery["id"])
        rebound = pair.owner.store.get("group_delivery", delivery["id"])
        assert rebound is not None
        assert rebound["group_epoch"] == group["epoch"]
        assert rebound["group_manifest_hash"] == group["manifest_hash"]
        assert rebound["recipient_display_name"] == "Bailey Updated"
        assert rebound["recipient_hints"] == recipient["connection_hints"]
        assert parse_payload(
            _native(
                pair.owner_network.sent[-1],
                source=b"\x00" * 16,
                destination=b"\x01" * 16,
            )
        ).group_epoch == group["epoch"]
    finally:
        pair.close()


def test_group_reaction_receipts_are_bounded_and_keep_newest_revision(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        target = pair.owner.send_group_message(pair.group_id, "Receipt cap target")
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        pair.owner._on_inbound(
            _group_reaction_native(
                group=group,
                source_profile=pair.member_profile,
                destination_profile=pair.owner_profile,
                target_id=target["id"],
                revision=10,
                emoji="🎉",
            )
        )
        for revision in range(1, 8):
            pair.owner._on_inbound(
                _group_reaction_native(
                    group=group,
                    source_profile=pair.member_profile,
                    destination_profile=pair.owner_profile,
                    target_id=target["id"],
                    revision=revision,
                )
            )
        receipts = [
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("reaction_receipt") is True
            and item.get("reaction_target_message_id") == target["id"]
        ]
        assert len(receipts) == 4
        assert max(item["reaction_ack_revision"] for item in receipts) == 10
        assert pair.owner_network.cancelled
        assert len(set().union(*pair.owner_network.cancelled)) >= 4
    finally:
        pair.close()


def test_hidden_group_ignores_random_reaction_targets_without_outbox_growth(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        pair.owner.delete_conversation("group", pair.group_id)
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        before = len(pair.owner.store.list("group_delivery"))
        for _ in range(300):
            pair.owner._on_inbound(
                _group_reaction_native(
                    group=group,
                    source_profile=pair.member_profile,
                    destination_profile=pair.owner_profile,
                    target_id=str(uuid.uuid4()),
                )
            )
        assert len(pair.owner.store.list("group_delivery")) == before
        assert pair.owner.store.list("pending_reaction") == []
    finally:
        pair.close()


def test_snapshot_reads_reaction_table_once_for_direct_and_group_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        direct = pair.owner.send_message("bailey", "Direct target")
        group = pair.owner.send_group_message(pair.group_id, "Group target")
        pair.owner.set_message_reaction("direct", direct["id"], "👍", True)
        pair.owner.set_message_reaction("group", group["id"], "🎉", True)
        original_list = pair.owner.store.list
        reaction_reads = 0

        def counting_list(kind: str) -> list[dict[str, Any]]:
            nonlocal reaction_reads
            if kind == "reaction":
                reaction_reads += 1
            return original_list(kind)

        monkeypatch.setattr(pair.owner.store, "list", counting_list)
        snapshot = pair.owner.snapshot()
        assert snapshot["messages"] and snapshot["group_messages"]
        assert reaction_reads == 1
    finally:
        pair.close()


def test_same_message_uuid_has_independent_direct_and_group_reaction_state(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        group_message = pair.owner.send_group_message(
            pair.group_id, "Shared identifier target"
        )
        now = time.time()
        direct_message = {
            "id": group_message["id"],
            "conversation_id": conversation_id(
                bytes.fromhex(pair.owner_profile["destination_hash"]),
                bytes.fromhex(pair.member_profile["destination_hash"]),
            ),
            "contact_id": "bailey",
            "direction": "outbound",
            "kind": MessageKind.CHAT.value,
            "text": "Direct target with same UUID",
            "state": DeliveryState.DELIVERED.value,
            "created_at": now,
            "expires_at": now + 3600,
            "receipt_for": None,
        }
        pair.owner.store.put("message", direct_message["id"], direct_message)

        pair.owner.set_message_reaction(
            "direct", direct_message["id"], "👍", True
        )
        pair.owner.set_message_reaction(
            "group", group_message["id"], "🎉", True
        )
        states = [
            item
            for item in pair.owner.store.list("reaction")
            if item.get("message_id") == group_message["id"]
        ]
        assert {item["scope"] for item in states} == {"direct", "group"}
        assert len({item["id"] for item in states}) == 2

        pair.owner.delete_conversation("direct", "bailey")
        remaining = pair.owner.store.list("reaction")
        assert len(remaining) == 1 and remaining[0]["scope"] == "group"
        assert pair.owner.store.get("group_message", group_message["id"]) is not None
    finally:
        pair.close()


def test_deleted_group_reaction_targets_do_not_resurrect_after_restore_or_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    restarted: MeshChatService | None = None
    owner_closed = False
    member_closed = False
    try:
        target = pair.owner.send_group_message(pair.group_id, "Delete target")
        chat = _sent_values(pair.owner_network, "group_chat")[-1]
        _deliver(
            pair.member,
            chat,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
        )
        owner_group = pair.owner.store.get("group", pair.group_id)
        member_group = pair.member.store.get("group", pair.group_id)
        assert owner_group is not None and member_group is not None
        to_owner = _group_reaction_native(
            group=owner_group,
            source_profile=pair.member_profile,
            destination_profile=pair.owner_profile,
            target_id=target["id"],
        )
        to_member = _group_reaction_native(
            group=member_group,
            source_profile=pair.owner_profile,
            destination_profile=pair.member_profile,
            target_id=target["id"],
        )
        key = bytes(pair.owner.store._key)
        pair.owner.store.put(
            "identity",
            "local",
            {
                "private_key": base64.urlsafe_b64encode(
                    pair.owner_identity.get_private_key()
                ).decode("ascii")
            },
        )

        pair.owner.delete_conversation("group", pair.group_id)
        pair.owner.restore_conversation("group", pair.group_id)
        pair.owner._on_inbound(to_owner)
        assert pair.owner.store.list("reaction") == []
        assert pair.owner.store.list("pending_reaction") == []

        pair.member.delete_conversation("group", pair.group_id)
        pair.member.restore_conversation("group", pair.group_id)
        pair.member._on_inbound(to_member)
        assert pair.member.store.list("reaction") == []
        assert pair.member.store.list("pending_reaction") == []

        pair.owner.close()
        owner_closed = True
        monkeypatch.setattr(
            MeshChatService, "_start_network", lambda _self, _name: None
        )
        store = VaultStore(
            tmp_path / "owner", key, allow_unprotected_for_tests=True
        )
        restarted = MeshChatService(
            store, tmp_path / "owner", lambda _event: None
        )
        restarted._shutdown.set()
        restarted._on_inbound(
            _group_reaction_native(
                group=restarted.store.get("group", pair.group_id),
                source_profile=pair.member_profile,
                destination_profile=pair.owner_profile,
                target_id=target["id"],
                revision=2,
            )
        )
        assert restarted.store.list("reaction") == []
        assert restarted.store.list("pending_reaction") == []
        assert restarted.snapshot()["group_messages"] == []
    finally:
        if restarted is not None:
            restarted.close()
        elif not owner_closed:
            pair.owner.close()
        if not member_closed:
            pair.member.close()


def test_group_reaction_receipt_lookup_is_bound_to_group_and_target(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        other_group = dict(group)
        other_group["id"] = str(uuid.uuid4())
        source = bytes.fromhex(pair.member_profile["destination_hash"])
        app = SimpleNamespace(
            logical_id=str(uuid.uuid4()),
            conversation_id=conversation_id(
                source,
                bytes.fromhex(pair.owner_profile["destination_hash"]),
            ),
            reaction_for=str(uuid.uuid4()),
            reaction_revision=1,
            group_message_id=str(uuid.uuid4()),
            group_epoch=int(group["epoch"]),
            group_manifest_hash=group["manifest_hash"],
        )
        wrong = pair.owner._group_reaction_receipt_record(
            other_group, source, app
        )
        pair.owner.store.put("group_delivery", wrong["id"], wrong)

        pair.owner._ensure_group_reaction_receipt(group, source, app)

        matches = [
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("reaction_receipt") is True
            and item.get("receipt_for") == app.logical_id
        ]
        assert {item["group_id"] for item in matches} == {
            other_group["id"],
            group["id"],
        }
    finally:
        pair.close()


def test_group_callback_then_raise_does_not_resurrect_reaction_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        target = pair.owner.send_group_message(pair.group_id, "Race target")

        def callback_then_raise(**values: Any) -> str:
            pair.owner._on_native_status(
                values["logical_id"],
                DeliveryState.RECEIVED_BY_ENDPOINT,
                "native-sync",
            )
            raise RuntimeError("adapter unwound after callback")

        monkeypatch.setattr(
            pair.owner_network, "send_with_fields", callback_then_raise
        )
        pair.owner.set_message_reaction(
            "group", target["id"], "👍", True
        )
        assert not any(
            item.get("kind") == MessageKind.GROUP_REACTION.value
            for item in pair.owner.store.list("group_delivery")
        )

        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        pair.owner._on_inbound(
            _group_reaction_native(
                group=group,
                source_profile=pair.member_profile,
                destination_profile=pair.owner_profile,
                target_id=target["id"],
                emoji="🎉",
            )
        )
        assert not any(
            item.get("reaction_receipt") is True
            for item in pair.owner.store.list("group_delivery")
        )
        assert pair.owner.store.list("reaction")
    finally:
        pair.close()


def test_group_reaction_only_terminal_rows_are_removed_on_recovery(
    tmp_path: Path,
) -> None:
    pair = _joined_pair(tmp_path)
    try:
        target = pair.owner.send_group_message(pair.group_id, "Terminal target")
        pair.owner.network = None
        pair.owner.set_message_reaction("group", target["id"], "😢", True)
        operation = next(
            item
            for item in pair.owner.store.list("group_delivery")
            if item.get("kind") == MessageKind.GROUP_REACTION.value
        )
        operation["state"] = DeliveryState.FAILED.value
        pair.owner.store.put("group_delivery", operation["id"], operation)

        group = pair.owner.store.get("group", pair.group_id)
        assert group is not None
        source = bytes.fromhex(pair.member_profile["destination_hash"])
        app = SimpleNamespace(
            logical_id=str(uuid.uuid4()),
            conversation_id=operation["conversation_id"],
            reaction_for=target["id"],
            reaction_revision=1,
            group_message_id=str(uuid.uuid4()),
            group_epoch=int(group["epoch"]),
            group_manifest_hash=group["manifest_hash"],
        )
        receipt = pair.owner._group_reaction_receipt_record(group, source, app)
        receipt["state"] = DeliveryState.EXPIRED.value
        receipt["expires_at"] = time.time() - 1
        pair.owner.store.put("group_delivery", receipt["id"], receipt)

        pair.owner._recover_group_outbox()
        assert pair.owner.store.get("group_delivery", operation["id"]) is None
        assert pair.owner.store.get("group_delivery", receipt["id"]) is None
        assert pair.owner.store.list("reaction")
    finally:
        pair.close()
