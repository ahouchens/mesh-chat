from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import LXMF
import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import DeliveryState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_channel_manifest,
    create_workspace_channel_record,
    create_workspace_device_card,
    create_workspace_event,
    create_workspace_manifest,
    verify_workspace_genesis,
)
from mesh_chat.workspace_wire import WorkspaceWirePayload, parse_workspace_payload


class RecordingWorkspaceNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.remembered: list[bytes] = []

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

    def cancel_outbound(self, _logical_ids: set[str]) -> int:
        return 0

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


def _service(
    root: Path,
    identity: RNS.Identity,
    display_name: str,
    *,
    vault_key: bytes | None = None,
) -> tuple[MeshChatService, RecordingWorkspaceNetwork]:
    store = VaultStore(
        root, vault_key or os.urandom(32), allow_unprotected_for_tests=True
    )
    # Keep this unit harness on its recording network even when reopening a
    # persisted profile. The production constructor sees both records and
    # starts Reticulum, so temporarily remove only these two local-profile
    # records while constructing the service and restore them immediately.
    if store.get("identity", "local") is not None:
        store.delete("identity", "local")
    if store.get("profile", "local") is not None:
        store.delete("profile", "local")
    service = MeshChatService(store, root, lambda _event: None)
    store.put(
        "identity",
        "local",
        {
            "private_key": base64.urlsafe_b64encode(
                identity.get_private_key()
            ).decode("ascii")
        },
    )
    store.put("profile", "local", _profile(identity, display_name))
    service._shutdown.set()
    service._identity = identity
    network = RecordingWorkspaceNetwork()
    service.network = network  # type: ignore[assignment]
    return service, network


def _native(sent: dict[str, Any], *, source: bytes, destination: bytes) -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=sent["text"],
        fields=sent["fields"],
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=destination,
        source_hash=source,
    )


def _deliver(
    recipient: MeshChatService,
    sent: dict[str, Any],
    *,
    source_profile: dict[str, Any],
    recipient_profile: dict[str, Any],
) -> None:
    recipient._on_inbound_locked(
        _native(
            sent,
            source=bytes.fromhex(source_profile["destination_hash"]),
            destination=bytes.fromhex(recipient_profile["destination_hash"]),
        )
    )


def _flush(service: MeshChatService, network: RecordingWorkspaceNetwork) -> list[dict[str, Any]]:
    before = len(network.sent)
    service._retry_workspace_outbox()
    return network.sent[before:]


def _op(index: int) -> str:
    return str(uuid.UUID(int=index, version=4))


def _joined_pair(
    root: Path, *, base: int
) -> tuple[
    MeshChatService,
    RecordingWorkspaceNetwork,
    dict[str, Any],
    MeshChatService,
    RecordingWorkspaceNetwork,
    dict[str, Any],
    dict[str, Any],
    bytes,
    RNS.Identity,
]:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    member_key = os.urandom(32)
    owner, owner_network = _service(root / "owner", owner_identity, "Alex")
    member, member_network = _service(
        root / "member", member_identity, "Bailey", vault_key=member_key
    )
    owner_profile = owner._require_profile()
    member_profile = member._require_profile()
    workspace = owner.create_workspace(_op(base), "Channel lab", "Increment 3")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(base + 1)
    )
    member.submit_workspace_join(invitation["text"], _op(base + 2))
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    request = next(
        item
        for item in owner.workspace_snapshot()["workspace_join_requests"]
        if item["workspace_id"] == workspace["id"]
    )
    owner.approve_workspace_join(workspace["id"], request["id"], _op(base + 3))
    controls = _flush(owner, owner_network)
    controls.sort(
        key=lambda item: 0
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_manifest_root"
        else 1
    )
    for item in controls:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert member._require_workspace(workspace["id"])["state"] == "active"
    return (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    )


def _deliver_all(
    recipient: MeshChatService,
    packets: list[dict[str, Any]],
    *,
    source_profile: dict[str, Any],
    recipient_profile: dict[str, Any],
) -> None:
    for packet in packets:
        _deliver(
            recipient,
            packet,
            source_profile=source_profile,
            recipient_profile=recipient_profile,
        )


def test_two_member_workspace_create_join_chat_and_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, owner_network = _service(tmp_path / "owner", owner_identity, "Alex")
    joiner, joiner_network = _service(tmp_path / "joiner", joiner_identity, "Bailey")
    owner_profile = owner._require_profile()
    joiner_profile = joiner._require_profile()

    workspace = owner.create_workspace(_op(1), "Lakewatcher", "Field team")
    assert owner.create_workspace(_op(1), "Lakewatcher", "Field team")["id"] == workspace["id"]
    with pytest.raises(ValidationError, match="different input"):
        owner.create_workspace(_op(1), "Another name", "Field team")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(2)
    )
    joining = joiner.submit_workspace_join(invitation["text"], _op(3))
    assert joining["state"] == "joining"

    outgoing_join = _flush(joiner, joiner_network)
    assert len(outgoing_join) == 1
    assert parse_workspace_payload(
        _native(
            outgoing_join[0],
            source=bytes.fromhex(joiner_profile["destination_hash"]),
            destination=bytes.fromhex(owner_profile["destination_hash"]),
        )
    ).kind == "workspace_join"
    _deliver(
        owner,
        outgoing_join[0],
        source_profile=joiner_profile,
        recipient_profile=owner_profile,
    )
    request = owner.workspace_snapshot()["workspace_join_requests"][0]
    assert bytes.fromhex(request["destination_hash"]) in owner_network.remembered
    approved = owner.approve_workspace_join(
        workspace["id"], request["id"], _op(4)
    )
    assert approved["state"] == "approved"

    controls = _flush(owner, owner_network)
    assert {parse_workspace_payload(_native(item, source=b"\x00" * 16, destination=b"\x01" * 16)).kind for item in controls} == {
        "workspace_manifest_root",
        "workspace_channel_record",
    }
    controls_by_kind = {
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind: item
        for item in controls
    }
    joining_record = joiner._require_workspace(workspace["id"])
    offered_manifest_id = joiner._workspace_manifest_record_id(
        joining_record["manifest_hash"]
    )
    offered_manifest = joiner.store.get("workspace_manifest", offered_manifest_id)
    assert offered_manifest is not None
    joiner.store.delete("workspace_manifest", offered_manifest_id)
    _deliver(
        joiner,
        controls_by_kind["workspace_channel_record"],
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    assert joiner.workspace_snapshot()["workspaces"][0]["general_channel_id"] is None
    assert len(joiner.store.list("workspace_pending_control")) == 1
    assert joiner.workspace_snapshot()["workspaces"][0]["sync_issue"] == "missing_manifest"
    joiner.store.put("workspace_manifest", offered_manifest_id, offered_manifest)
    joiner._drain_workspace_pending_controls(workspace["id"])
    assert joiner.store.list("workspace_pending_control") == []
    assert "sync_issue" not in joiner.workspace_snapshot()["workspaces"][0]
    assert joiner.workspace_snapshot()["workspaces"][0]["general_channel_id"] == (
        workspace["general_channel_id"]
    )
    _deliver(
        joiner,
        controls_by_kind["workspace_manifest_root"],
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    joined = joiner.workspace_snapshot()["workspaces"][0]
    assert joined["state"] == "active"
    assert len(joined["members"]) == 2
    channel_id = joined["general_channel_id"]
    assert isinstance(channel_id, str)

    # A current member can sign its own channel record, but it cannot replace
    # the genesis-owner-managed #general control.
    joined_manifest = joiner._workspace_current_manifest(
        joiner._require_workspace(workspace["id"])
    )
    forged_channel = create_workspace_channel_record(
        joiner_identity,
        workspace_id=workspace["id"],
        channel_id=workspace["general_channel_id"],
        manifest_digest=joined_manifest.digest,
        name="general",
        topic="forged topic",
        manager_member_id=joined["local_member_id"],
        manager_device_id=joined["local_device_id"],
    )
    assert not owner._receive_workspace_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_record",
            logical_id=_op(400),
            workspace_id=workspace["id"],
            expires_at=int(time.time()) + 60,
            document=forged_channel,
        )
    )
    assert owner._require_workspace(workspace["id"])["state"] == "active"

    event = owner.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Water level is stable.",
        _op(5),
        _op(6),
    )
    assert event["delivery_summary"]["devices_total"] == 1
    sent_event = _flush(owner, owner_network)[0]
    _deliver(
        joiner,
        sent_event,
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    page = joiner.list_workspace_messages(joined["id"], channel_id, limit=50)
    assert [item["text"] for item in page["messages"]] == ["Water level is stable."]
    assert joiner.snapshot()["messages"] == []
    assert "workspace_messages" not in joiner.snapshot()

    delivery = next(
        item
        for item in owner.store.list("workspace_delivery")
        if item.get("event_id") == event["id"]
    )
    original_list = owner.store.list

    def bounded_list(kind: str) -> list[dict[str, Any]]:
        assert kind != "workspace_delivery", "receipt handling must not scan deliveries"
        return original_list(kind)

    monkeypatch.setattr(owner.store, "list", bounded_list)
    assert owner._on_workspace_native_status(
        delivery["id"], DeliveryState.RECEIVED_BY_ENDPOINT, delivery.get("native_message_id")
    )
    owner_page = owner.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )
    assert owner_page["messages"][0]["delivery_summary"] == {
        "people_total": 1,
        "people_reached": 1,
        "people_partial": 0,
        "people_pending": 0,
        "people_failed": 0,
        "devices_total": 1,
        "devices_reached": 1,
        "devices_pending": 0,
        "devices_failed": 0,
        "devices_expired": 0,
        "devices_cancelled": 0,
    }
    monkeypatch.setattr(owner.store, "list", original_list)

    owner.close()
    joiner.close()


def test_workspace_mutations_converge_and_survive_restart_under_posting_policy(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "mutations", base=1_800)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    owner.update_workspace_policies(
        workspace_id, "all_members", "owner_and_admins", _op(1_804)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    message = owner.send_workspace_message(
        workspace_id, channel_id, "Initial field note", _op(1_805), _op(1_806)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    with pytest.raises(ContactNotApproved, match="author"):
        member.edit_workspace_message(
            workspace_id, message["id"], "Unauthorized", _op(1_807), _op(1_808)
        )

    reacted = member.set_workspace_reaction(
        workspace_id, message["id"], "👍", True, _op(1_809), _op(1_810)
    )
    assert reacted["reactions"] == [
        {"emoji": "👍", "count": 1, "reacted_by_self": True}
    ]
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    member.set_workspace_reaction(
        workspace_id, message["id"], "❤️", True, _op(1_817), _op(1_818)
    )
    member.set_workspace_reaction(
        workspace_id, message["id"], "👍", False, _op(1_819), _op(1_820)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    owner_reacted = owner.list_workspace_messages(workspace_id, channel_id)[
        "messages"
    ][0]
    assert owner_reacted["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_self": False}
    ]

    edited = owner.edit_workspace_message(
        workspace_id,
        message["id"],
        "Corrected field note",
        _op(1_811),
        _op(1_812),
    )
    assert edited["text"] == "Corrected field note"
    assert edited["revision"] == 1
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    deleted = owner.delete_workspace_message(
        workspace_id, message["id"], _op(1_813), _op(1_814)
    )
    assert deleted["deleted"] is True
    assert deleted["text"] == ""
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    page = member.list_workspace_messages(workspace_id, channel_id)
    assert page["high_water"] == 1
    assert len(page["messages"]) == 1
    assert page["messages"][0]["deleted"] is True
    assert page["messages"][0]["revision"] == 2
    with pytest.raises(ContactNotApproved, match="deleted"):
        member.set_workspace_reaction(
            workspace_id, message["id"], "❤️", True, _op(1_815), _op(1_816)
        )

    member.close()
    member, _member_network = _service(
        tmp_path / "mutations" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.list_workspace_messages(workspace_id, channel_id)["messages"]
    assert len(restarted) == 1
    assert restarted[0]["deleted"] is True
    assert restarted[0]["revision"] == 2
    assert restarted[0]["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_self": True}
    ]
    owner.close()
    member.close()


def test_concurrent_workspace_edits_resolve_then_same_device_equivocation_freezes(
    tmp_path: Path,
) -> None:
    (
        owner,
        _owner_network,
        _owner_profile,
        member,
        _member_network,
        _member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "concurrent-mutations", base=1_900)
    workspace_id = workspace["id"]
    message = owner.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "Shared draft",
        _op(1_906),
        _op(1_907),
    )
    record_id = owner._workspace_message_record_id(message["id"])
    original = owner.store.get("workspace_message_state", record_id)
    assert original is not None

    def edit_candidate(
        event_id: str,
        digest: str,
        destination_byte: int,
        base_revision: int,
        revision: int,
        text: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            event_id=event_id,
            digest=digest,
            event_type="edit",
            base_revision=base_revision,
            revision=revision,
            author_destination=bytes([destination_byte]) * 16,
            created_at=1_800_000_000 + revision,
            text=text,
            reaction_active=None,
        )

    first = edit_candidate(_op(1_908), "aa" * 32, 1, 0, 1, "Device one")
    second = edit_candidate(_op(1_909), "bb" * 32, 2, 0, 1, "Device two")
    first_then_second = owner._apply_workspace_message_mutation(
        owner._apply_workspace_message_mutation(dict(original), first), second
    )
    second_then_first = owner._apply_workspace_message_mutation(
        owner._apply_workspace_message_mutation(dict(original), second), first
    )
    assert first_then_second["text"] == second_then_first["text"]
    assert first_then_second["revision"] == 1
    assert first_then_second["mutation_conflict"] is True

    resolution = edit_candidate(
        _op(1_910), "cc" * 32, 2, 1, 2, "Merged resolution"
    )
    resolved = owner._apply_workspace_message_mutation(
        first_then_second, resolution
    )
    assert resolved["text"] == "Merged resolution"
    assert resolved["mutation_conflict"] is False

    equivocation = edit_candidate(
        _op(1_911), "dd" * 32, 2, 1, 2, "Conflicting device-two value"
    )
    frozen = owner._apply_workspace_message_mutation(resolved, equivocation)
    assert frozen["mutation_frozen"] is True
    owner.store.put("workspace_message_state", record_id, frozen)
    with pytest.raises(ContactNotApproved, match="frozen"):
        owner.edit_workspace_message(
            workspace_id, message["id"], "Too late", _op(1_912), _op(1_913)
        )
    owner.close()
    member.close()


def test_out_of_order_workspace_mutations_wait_for_predecessor_and_converge(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        _member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "out-of-order-mutations", base=1_950)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    message = owner.send_workspace_message(
        workspace_id, channel_id, "Revision zero", _op(1_954), _op(1_955)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    owner.edit_workspace_message(
        workspace_id, message["id"], "Revision one", _op(1_956), _op(1_957)
    )
    owner.edit_workspace_message(
        workspace_id, message["id"], "Revision two", _op(1_958), _op(1_959)
    )
    mutation_packets = _flush(owner, owner_network)
    assert len(mutation_packets) == 2
    _deliver(
        member,
        mutation_packets[1],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    assert member.list_workspace_messages(workspace_id, channel_id)["messages"][0][
        "text"
    ] == "Revision zero"
    _deliver(
        member,
        mutation_packets[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.store.list("workspace_pending_event") == []
    converged = member.list_workspace_messages(workspace_id, channel_id)["messages"]
    assert len(converged) == 1
    assert converged[0]["text"] == "Revision two"
    assert converged[0]["revision"] == 2
    _deliver(
        member,
        mutation_packets[1],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, channel_id)["messages"] == converged
    owner.close()
    member.close()


def test_workspace_direct_chat_hide_reopen_restart_and_removal(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path, base=450)
    workspace_id = workspace["id"]
    owner_view = owner.workspace_snapshot()["workspaces"][0]
    member_id = next(
        item["id"]
        for item in owner_view["members"]
        if item["id"] != owner_view["local_member_id"]
    )
    assert owner.snapshot()["contacts"] == []
    assert member.snapshot()["contacts"] == []

    opened, _ = owner.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-open",
            "command": "open_workspace_direct",
            "payload": {
                "operation_id": _op(454),
                "workspace_id": workspace_id,
                "member_id": member_id,
            },
        }
    )
    direct = opened["result"]
    assert direct["peer_display_name"] == "Bailey"
    assert owner.workspace_snapshot()["workspace_directs"] == [direct]
    assert member.workspace_snapshot()["workspace_directs"] == []

    first = owner.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Private field note",
        _op(455),
        _op(456),
        [member_id],
    )
    assert first["delivery_summary"]["devices_total"] == 1
    outgoing = _flush(owner, owner_network)
    assert len(outgoing) == 1
    _deliver(
        member,
        outgoing[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_direct = member.workspace_snapshot()["workspace_directs"][0]
    assert member_direct["id"] == direct["id"]
    assert member_direct["unread_count"] == 1
    marked, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-read",
            "command": "mark_workspace_direct_read",
            "payload": {
                "operation_id": _op(469),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
                "high_water": 1,
            },
        }
    )
    assert marked["result"]["high_water"] == 1
    assert member.workspace_snapshot()["workspace_directs"][0]["unread_count"] == 0
    assert [
        item["text"]
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note"]

    owner.edit_workspace_message(
        workspace_id,
        first["id"],
        "Private field note revised",
        _op(471),
        _op(472),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, direct["id"])[
        "messages"
    ][0]["text"] == "Private field note revised"
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [first["id"]]
    member.set_workspace_reaction(
        workspace_id, first["id"], "✅", True, _op(473), _op(474)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner.list_workspace_messages(workspace_id, direct["id"])[
        "messages"
    ][0]["reactions"] == [
        {"emoji": "✅", "count": 1, "reacted_by_self": False}
    ]

    reply = member.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Acknowledged",
        _op(457),
        _op(458),
    )
    reply_packets = _flush(member, member_network)
    assert len(reply_packets) == 1
    _deliver(
        owner,
        reply_packets[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert [
        item["text"]
        for item in owner.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note revised", "Acknowledged"]

    hidden, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-hide",
            "command": "hide_workspace_direct",
            "payload": {
                "operation_id": _op(459),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
            },
        }
    )
    assert hidden["result"]["hidden"] is True
    assert member.workspace_snapshot()["workspace_directs"] == []
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []
    member_workspace = member.workspace_snapshot()["workspaces"][0]
    reopened = member.open_workspace_direct(
        workspace_id, member_workspace["owner_member_id"], _op(460)
    )
    assert reopened["id"] == direct["id"]
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [first["id"]]
    saved_draft, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-draft",
            "command": "save_workspace_direct_draft",
            "payload": {
                "operation_id": _op(461),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
                "text": "Restart-safe draft",
            },
        }
    )
    assert saved_draft["result"]["text"] == "Restart-safe draft"
    member.close()

    member, member_network = _service(
        tmp_path / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.workspace_snapshot()
    assert restarted["workspace_directs"][0]["id"] == direct["id"]
    assert restarted["workspace_drafts"] == [
        {
            "workspace_id": workspace_id,
            "conversation_id": direct["id"],
            "text": "Restart-safe draft",
        }
    ]
    assert [
        item["text"]
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note revised", "Acknowledged"]

    pending = member.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Queued before removal",
        _op(462),
        _op(463),
    )
    pending_packets = _flush(member, member_network)
    assert len(pending_packets) == 1
    owner.remove_workspace_member(workspace_id, member_id, _op(464))
    removal_packets = _flush(owner, owner_network)
    removal_manifest = next(
        item
        for item in removal_packets
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_manifest_root"
    )
    _deliver(
        member,
        removal_manifest,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    pending_delivery = next(
        item
        for item in member.store.list("workspace_delivery")
        if item.get("event_id") == pending["id"]
    )
    assert pending_delivery["state"] == DeliveryState.CANCELLED.value
    pending_message = next(
        item
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
        if item["id"] == pending["id"]
    )
    assert pending_message["deliveries"] == [
        {
            "device_id": owner._require_workspace(workspace_id)["local_device_id"],
            "device_short_id": owner._require_workspace(workspace_id)[
                "local_device_id"
            ].replace("-", "")[:6],
            "member_id": owner._require_workspace(workspace_id)["local_member_id"],
            "member_display_name": "Alex",
            "state": DeliveryState.CANCELLED.value,
        }
    ]
    assert member.workspace_snapshot()["workspace_directs"][0]["state"] == "read_only"
    assert owner.workspace_snapshot()["workspace_directs"][0]["state"] == "read_only"
    owner_message_count = len(
        owner.list_workspace_messages(workspace_id, direct["id"])["messages"]
    )
    _deliver(
        owner,
        pending_packets[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert len(
        owner.list_workspace_messages(workspace_id, direct["id"])["messages"]
    ) == owner_message_count
    with pytest.raises(ContactNotApproved):
        owner.send_workspace_direct_message(
            workspace_id,
            direct["id"],
            "Too late",
            _op(465),
            _op(466),
        )
    with pytest.raises(ContactNotApproved):
        member.send_workspace_direct_message(
            workspace_id,
            direct["id"],
            "Also too late",
            _op(467),
            _op(468),
        )
    assert owner.snapshot()["contacts"] == []
    assert member.snapshot()["contacts"] == []
    assert reply["conversation_id"] == direct["id"]
    removed = member.remove_workspace_data(workspace_id, workspace_id, _op(470))
    assert removed == {"workspace_id": workspace_id, "removed": True}
    assert member.store.list("workspace_direct") == []
    assert member.store.list("workspace_draft") == []
    owner.close()
    member.close()


def test_unauthorized_manifest_cannot_fork_and_nonmember_sources_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_identity = RNS.Identity()
    attacker = RNS.Identity()
    service, _network = _service(tmp_path / "manifest-guard", owner_identity, "Alex")
    workspace = service.create_workspace(_op(500), "Guarded", "")
    stored = service._require_workspace(workspace["id"])
    genesis = verify_workspace_genesis(stored["genesis"])
    attacker_member_id = _op(501)
    attacker_device_id = _op(502)
    attacker_card = create_workspace_device_card(
        attacker,
        workspace_id=workspace["id"],
        member_id=attacker_member_id,
        device_id=attacker_device_id,
        display_name="Mallory",
    )
    forged = create_workspace_manifest(
        attacker,
        workspace_id=workspace["id"],
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name="Guarded",
        description="",
        authority_device_id=attacker_device_id,
        members=[
            WorkspaceManifestMemberInput(
                attacker_member_id,
                "Mallory",
                "owner",
                [attacker_card],
            )
        ],
    )
    wire = WorkspaceWirePayload(
        kind="workspace_manifest_root",
        logical_id=_op(503),
        workspace_id=workspace["id"],
        expires_at=int(time.time()) + 60,
        document=forged,
    )
    assert not service._receive_workspace_manifest(wire)
    assert service._require_workspace(workspace["id"])["state"] == "active"

    received: list[WorkspaceWirePayload] = []
    monkeypatch.setattr(service, "_receive_workspace_manifest", received.append)
    service._receive_workspace_payload(
        SimpleNamespace(
            source_hash=RNS.Destination.hash(attacker, "lxmf", "delivery")
        ),
        wire,
    )
    assert received == []
    service.close()


def test_workspace_decline_is_scoped_and_terminal_close_invalidates_requests(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "scoped-admin", identity, "Alex")
    first = service.create_workspace(_op(600), "First", "")
    second = service.create_workspace(_op(601), "Second", "")
    request_id = service.store.opaque_id("workspace-join", "fixture")
    service.store.put(
        "workspace_join_request",
        request_id,
        {
            "id": request_id,
            "workspace_id": first["id"],
            "state": "pending",
        },
    )
    with pytest.raises(ValidationError, match="no longer pending"):
        service.decline_workspace_join(second["id"], request_id, _op(602))
    assert service.store.get("workspace_join_request", request_id)["state"] == "pending"

    invitation = service.create_workspace_invitation_command(first["id"], _op(603))
    second_invitation = service.create_workspace_invitation_command(
        first["id"], _op(605)
    )
    assert second_invitation["id"] != invitation["id"]
    assert len(service.workspace_snapshot()["workspace_invitations"]) == 2
    expiring = service.store.get("workspace_invitation", invitation["id"])
    expiring["expires_at"] = time.time() - 1
    service.store.put("workspace_invitation", invitation["id"], expiring)
    service._expire_workspace_invitations()
    assert service.store.get("workspace_invitation", invitation["id"])["state"] == "expired"
    assert [
        item["id"]
        for item in service.workspace_snapshot()["workspace_invitations"]
    ] == [second_invitation["id"]]
    service.revoke_workspace_invitation(
        first["id"], second_invitation["id"], _op(606)
    )
    third_invitation = service.create_workspace_invitation_command(
        first["id"], _op(607)
    )
    service.close_workspace(first["id"], _op(604))
    assert service.store.get("workspace_join_request", request_id)["state"] == "closed"
    assert service.store.get("workspace_invitation", invitation["id"])["state"] == "expired"
    assert service.store.get("workspace_invitation", second_invitation["id"])["state"] == "revoked"
    assert service.store.get("workspace_invitation", third_invitation["id"])["state"] == "closed"
    assert service.workspace_snapshot()["workspace_join_requests"] == []
    service.close()


def test_eight_person_workspace_catches_up_concurrent_invites_and_admin_changes(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    owner_root = tmp_path / "owner-eight"
    owner_vault_key = os.urandom(32)
    owner, owner_network = _service(
        owner_root, owner_identity, "Owner", vault_key=owner_vault_key
    )
    owner_profile = owner._require_profile()
    workspace = owner.create_workspace(_op(700), "Field team", "Initial")
    invitations = [
        owner.create_workspace_invitation_command(
            workspace["id"], _op(701 + index)
        )
        for index in range(7)
    ]
    assert len(owner.workspace_snapshot()["workspace_invitations"]) == 7

    peers: list[tuple[MeshChatService, RecordingWorkspaceNetwork, dict[str, Any]]] = []
    peer_identities: list[RNS.Identity] = []
    peer_vault_keys: list[bytes] = []
    by_destination: dict[str, tuple[MeshChatService, dict[str, Any]]] = {}
    for index, invitation in enumerate(invitations):
        identity = RNS.Identity()
        peer_vault_key = os.urandom(32)
        peer_identities.append(identity)
        peer_vault_keys.append(peer_vault_key)
        peer, peer_network = _service(
            tmp_path / f"peer-{index}",
            identity,
            f"Member {index + 1}",
            vault_key=peer_vault_key,
        )
        profile = peer._require_profile()
        peers.append((peer, peer_network, profile))
        by_destination[profile["destination_hash"]] = (peer, profile)
        peer.submit_workspace_join(invitation["text"], _op(720 + index * 3))
        join_payload = _flush(peer, peer_network)
        assert len(join_payload) == 1
        _deliver(
            owner,
            join_payload[0],
            source_profile=profile,
            recipient_profile=owner_profile,
        )
        pending = owner.workspace_snapshot()["workspace_join_requests"]
        request = next(
            item
            for item in pending
            if item["invitation_id"] == invitation["id"]
        )
        owner.approve_workspace_join(
            workspace["id"], request["id"], _op(721 + index * 3)
        )
        controls = _flush(owner, owner_network)
        assert len(controls) == 2 * (index + 1)
        for sent in controls:
            recipient, recipient_profile = by_destination[
                sent["recipient_destination"].hex()
            ]
            _deliver(
                recipient,
                sent,
                source_profile=owner_profile,
                recipient_profile=recipient_profile,
            )
        assert len(peer.workspace_snapshot()["workspaces"][0]["members"]) == (
            index + 2
        )

    assert len(owner.workspace_snapshot()["workspaces"][0]["members"]) == 8
    assert owner.workspace_snapshot()["workspace_invitations"] == []
    assert all(
        len(peer.workspace_snapshot()["workspaces"][0]["members"]) == 8
        for peer, _network, _profile in peers
    )

    owner.update_workspace_metadata(
        workspace["id"], "Field coordination", "Current conditions", _op(760)
    )
    metadata_controls = _flush(owner, owner_network)
    assert len(metadata_controls) == 7
    for sent in metadata_controls:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert all(
        peer.workspace_snapshot()["workspaces"][0]["name"]
        == "Field coordination"
        for peer, _network, _profile in peers
    )

    requester, requester_network, requester_profile = peers[0]
    requester.request_workspace_display_name(
        workspace["id"], "River lead", _op(761)
    )
    request_payload = _flush(requester, requester_network)
    assert len(request_payload) == 1
    _deliver(
        owner,
        request_payload[0],
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    name_request = owner.workspace_snapshot()[
        "workspace_display_name_requests"
    ][0]
    owner.decide_workspace_display_name(
        workspace["id"], name_request["id"], True, _op(762)
    )
    name_controls = _flush(owner, owner_network)
    assert len(name_controls) == 7
    for sent in name_controls:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert requester.workspace_snapshot()["workspace_display_name_requests"] == []
    assert any(
        member["display_name"] == "River lead"
        for member in owner.workspace_snapshot()["workspaces"][0]["members"]
    )

    requester.request_workspace_display_name(
        workspace["id"], "River watch", _op(768)
    )
    declined_request_payload = _flush(requester, requester_network)
    assert len(declined_request_payload) == 1
    _deliver(
        owner,
        declined_request_payload[0],
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    declined_request = owner.workspace_snapshot()[
        "workspace_display_name_requests"
    ][0]
    owner.decide_workspace_display_name(
        workspace["id"], declined_request["id"], False, _op(769)
    )
    decline_payload = _flush(owner, owner_network)
    assert len(decline_payload) == 1
    _deliver(
        requester,
        decline_payload[0],
        source_profile=owner_profile,
        recipient_profile=requester_profile,
    )
    assert requester.workspace_snapshot()["workspace_display_name_requests"] == []

    target = peers[-1][0].workspace_snapshot()["workspaces"][0]["local_member_id"]
    cancellable = owner.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Membership is changing.",
        _op(763),
        _op(764),
    )
    owner.remove_workspace_member(workspace["id"], target, _op(765))
    materialized = owner.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )["messages"][-1]
    assert materialized["id"] == cancellable["id"]
    assert materialized["delivery_summary"]["devices_cancelled"] == 1
    assert any(
        delivery["member_id"] == target
        and delivery["state"] == DeliveryState.CANCELLED.value
        for delivery in materialized["deliveries"]
    )

    removal_payloads = _flush(owner, owner_network)
    for sent in removal_payloads:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert peers[-1][0].workspace_snapshot()["workspaces"][0]["state"] == "removed"

    # The authority process is actually offline while the member commits this
    # event. Restart the sender before handing off any delivery legs to prove
    # that both the event and its frozen recipient set survive restart.
    owner.close()
    member_message = requester.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Owner can catch up later.",
        _op(766),
        _op(767),
    )
    requester.close()
    requester, requester_network = _service(
        tmp_path / "peer-0",
        peer_identities[0],
        "Member 1",
        vault_key=peer_vault_keys[0],
    )
    peers[0] = (requester, requester_network, requester_profile)
    assert any(
        message["id"] == member_message["id"]
        for message in requester.list_workspace_messages(
            workspace["id"], workspace["general_channel_id"]
        )["messages"]
    )
    member_payloads = _flush(requester, requester_network)
    delivered_without_owner = 0
    owner_payload: dict[str, Any] | None = None
    for sent in member_payloads:
        if sent["recipient_destination"].hex() == owner_profile["destination_hash"]:
            owner_payload = sent
            continue
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=requester_profile,
            recipient_profile=recipient_profile,
        )
        delivered_without_owner += 1
    assert delivered_without_owner == 5
    assert owner_payload is not None
    assert all(
        any(
            message["id"] == member_message["id"]
            for message in peer.list_workspace_messages(
                workspace["id"], workspace["general_channel_id"]
            )["messages"]
        )
        for peer, _network, _profile in peers[1:-1]
    )

    # Reconnect a restarted authority endpoint and deliver the exact canonical
    # event it missed during the partition. The owner catches up without being
    # required for the member-to-member exchange.
    owner, owner_network = _service(
        owner_root, owner_identity, "Owner", vault_key=owner_vault_key
    )
    _deliver(
        owner,
        owner_payload,
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    assert any(
        message["id"] == member_message["id"]
        for message in owner.list_workspace_messages(
            workspace["id"], workspace["general_channel_id"]
        )["messages"]
    )

    owner.close()
    for peer, _network, _profile in peers:
        peer.close()


def test_workspace_messages_are_paged_with_mac_bound_stale_cursors(tmp_path: Path) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "pager", identity, "Alex")
    workspace = service.create_workspace(_op(20), "Pager", "")
    for index in range(55):
        service.send_workspace_message(
            workspace["id"],
            workspace["general_channel_id"],
            f"Message {index}",
            _op(100 + index),
            _op(200 + index),
        )
    first = service.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"], limit=50
    )
    assert len(first["messages"]) == 50
    assert first["messages"][-1]["text"] == "Message 54"
    second = service.list_workspace_messages(
        workspace["id"],
        workspace["general_channel_id"],
        cursor=first["next_cursor"],
        limit=50,
    )
    assert [item["text"] for item in second["messages"]] == [
        f"Message {index}" for index in range(5)
    ]

    stored = service._require_workspace(workspace["id"])
    stored["authorization_generation"] += 1
    service.store.put("workspace", service._workspace_record_id(workspace["id"]), stored)
    with pytest.raises(ValidationError, match="stale"):
        service.list_workspace_messages(
            workspace["id"],
            workspace["general_channel_id"],
            cursor=first["next_cursor"],
        )
    service.close()


def test_local_workspace_removal_redacts_duplicate_operation_results(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "removal", identity, "Alex")
    workspace = service.create_workspace(_op(300), "Private cleanup", "Erase this")
    service.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Sensitive workspace text",
        _op(301),
        _op(302),
    )
    service.store.remember_command(
        "renderer-request", {"ok": True, "result": {"text": "Sensitive workspace text"}}
    )
    service.close_workspace(workspace["id"], _op(303))
    result = service.remove_workspace_data(
        workspace["id"], workspace["id"], _op(304)
    )
    assert result == {"workspace_id": workspace["id"], "removed": True}
    assert service.workspace_snapshot()["workspaces"] == []
    retained_operations = repr(service.store.items("workspace_operation"))
    assert "Sensitive workspace text" not in retained_operations
    assert "Private cleanup" not in retained_operations
    assert service.store.command_response("renderer-request")["error"]["code"] == (
        "command_result_deleted"
    )
    service.close()


def test_public_channel_control_before_data_unread_restart_and_full_lifecycle(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "lifecycle", base=1_000)
    workspace_id = workspace["id"]
    member_id = member._require_workspace(workspace_id)["local_member_id"]

    channel = owner.create_workspace_channel(
        workspace_id, "Field notes", "Daily observations", _op(1_010)
    )
    channel_controls = _flush(owner, owner_network)
    assert len(channel_controls) == 1
    first = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Control arrives second.",
        _op(1_011),
        _op(1_012),
    )
    first_events = _flush(owner, owner_network)
    assert len(first_events) == 1
    _deliver(
        member,
        first_events[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    _deliver(
        member,
        channel_controls[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.store.list("workspace_pending_event") == []
    assert [
        item["text"]
        for item in member.list_workspace_messages(workspace_id, channel["id"])[
            "messages"
        ]
    ] == [first["text"]]
    discovered = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert discovered["subscribed"] is False
    assert discovered["unread_count"] == 0

    member.set_workspace_channel_subscription(
        workspace_id, channel["id"], True, _op(1_013)
    )
    owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Now count this message.",
        _op(1_014),
        _op(1_015),
    )
    message_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in message_items
    ] == ["workspace_event"]
    for item in message_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    subscribed = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert subscribed["unread_count"] == 1
    member.close()
    member, member_network = _service(
        tmp_path / "lifecycle" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    persisted = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert persisted["subscribed"] is True
    assert persisted["unread_count"] == 1

    renamed = owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        "Field reports",
        "Validated daily observations",
        False,
        _op(1_016),
    )
    rename_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in rename_items
    ] == ["workspace_channel_record"]
    for item in rename_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert renamed["version"] == 2
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )["version"] == 2
    offer = owner.offer_workspace_channel_transfer(
        workspace_id, channel["id"], member_id, _op(1_017)
    )
    offer_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in offer_items
    ] == ["workspace_channel_transfer_offer"]
    for item in offer_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    transfer = next(
        item
        for item in member.workspace_snapshot()["workspace_channel_transfers"]
        if item["channel_id"] == channel["id"]
        and item["successor_member_id"] == member_id
    )
    accepted = member.accept_workspace_channel_transfer(
        workspace_id, transfer["id"], _op(1_018)
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert accepted["manager_member_id"] == member_id
    managed = member.update_workspace_channel(
        workspace_id,
        channel["id"],
        "Field reports",
        "Managed by Bailey",
        False,
        _op(1_019),
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert managed["topic"] == "Managed by Bailey"
    recovered = owner.recover_workspace_channel(
        workspace_id, channel["id"], _op(1_020)
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert recovered["manager_member_id"] == workspace["local_member_id"]
    archived = owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        recovered["name"],
        recovered["topic"],
        True,
        _op(1_021),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert archived["state"] == "archived"
    with pytest.raises(ContactNotApproved, match="not active"):
        owner.update_workspace_channel(
            workspace_id,
            channel["id"],
            "Cannot reopen",
            "Terminal",
            False,
            _op(1_022),
        )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )["state"] == "archived"
    owner.close()
    member.close()


def test_partitioned_channel_summary_fetch_converges_and_disambiguates_names(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "discovery", base=1_100)
    workspace_id = workspace["id"]
    first = owner.create_workspace_channel(
        workspace_id, "Ops", "North team", _op(1_110)
    )
    second = owner.create_workspace_channel(
        workspace_id, "ops", "South team", _op(1_111)
    )
    assert owner.sync_workspace_channels(workspace_id, _op(1_112))["state"] == (
        "incomplete"
    )
    partitioned = _flush(owner, owner_network)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in partitioned:
        kind = parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        by_kind.setdefault(kind, []).append(item)
    assert len(by_kind["workspace_channel_record"]) == 2
    assert len(by_kind["workspace_channel_summary"]) == 1

    # Simulate a partition dropping the direct controls while the later signed
    # summary reaches the member. The member must explicitly fetch the chain.
    _deliver(
        member,
        by_kind["workspace_channel_summary"][0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert {
        item["name"] for item in member.workspace_snapshot()["workspace_channels"]
    } == {"general"}
    member_sync = _flush(member, member_network)
    assert {
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in member_sync
    } == {"workspace_channel_fetch", "workspace_channel_summary"}
    for item in member_sync:
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )

    discovered = [
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] in {first["id"], second["id"]}
    ]
    assert len(discovered) == 2
    assert all(item["duplicate_name"] for item in discovered)
    assert len({item["display_name"] for item in discovered}) == 2
    assert all(item["short_id"] in item["display_name"] for item in discovered)
    assert all(item["subscribed"] is False for item in discovered)
    stable_labels = {item["id"]: item["display_name"] for item in discovered}
    assert member._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert owner._require_workspace(workspace_id)["channel_discovery"] == (
        "incomplete"
    )

    # A second summary after the fetch proves both reachable peers now expose
    # the same bounded directory.
    member.sync_workspace_channels(workspace_id, _op(1_113))
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert owner._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert member._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert {
        item["id"]: item["display_name"]
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] in stable_labels
    } == stable_labels

    member.set_workspace_channel_subscription(
        workspace_id, first["id"], True, _op(1_114)
    )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == first["id"]
    )["subscribed"] is True
    member.set_workspace_channel_subscription(
        workspace_id, first["id"], False, _op(1_115)
    )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == first["id"]
    )["subscribed"] is False
    owner.close()
    member.close()


def test_channel_policies_reject_members_and_valid_same_version_conflict_forks_only_channel(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "policies", base=1_200)
    workspace_id = workspace["id"]
    owner.update_workspace_policies(
        workspace_id,
        "owner_and_admins",
        "owner_and_admins",
        _op(1_210),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    with pytest.raises(ContactNotApproved, match="owner"):
        member.create_workspace_channel(
            workspace_id, "Denied", "Policy test", _op(1_211)
        )
    with pytest.raises(ContactNotApproved, match="owner"):
        member.send_workspace_message(
            workspace_id,
            workspace["general_channel_id"],
            "Disallowed post",
            _op(1_212),
            _op(1_213),
        )
    restricted_workspace = member._require_workspace(workspace_id)
    restricted_manifest = member._workspace_current_manifest(restricted_workspace)
    restricted_channel = member._workspace_channel_by_digest(
        member._require_workspace_channel(
            workspace_id, workspace["general_channel_id"]
        )["head_hash"]
    )
    assert member._identity is not None and restricted_channel is not None
    disallowed_event = create_workspace_event(
        member._identity,
        workspace_id=workspace_id,
        conversation_id=workspace["general_channel_id"],
        event_id=_op(1_222),
        author_member_id=restricted_workspace["local_member_id"],
        author_device_id=restricted_workspace["local_device_id"],
        sequence=1,
        previous_event_digest=None,
        manifest_digest=restricted_manifest.digest,
        channel_digest=restricted_channel.digest,
        text="Signed but forbidden by policy",
    )
    assert not owner._accept_workspace_event(
        WorkspaceWirePayload(
            kind="workspace_event",
            logical_id=_op(1_223),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=disallowed_event,
        )
    )
    assert owner.list_workspace_messages(
        workspace_id, workspace["general_channel_id"]
    )["messages"] == []

    owner.update_workspace_policies(
        workspace_id,
        "all_members",
        "all_members",
        _op(1_214),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    member_channel = member.create_workspace_channel(
        workspace_id, "Member channel", "Allowed by policy", _op(1_215)
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    member.send_workspace_message(
        workspace_id,
        member_channel["id"],
        "Member-created and member-posted.",
        _op(1_216),
        _op(1_217),
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert owner.list_workspace_messages(
        workspace_id, member_channel["id"]
    )["messages"][0]["text"] == "Member-created and member-posted."

    channel = owner.create_workspace_channel(
        workspace_id, "Fork test", "First head", _op(1_218)
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    initial = owner._workspace_channel_by_digest(channel["head_hash"])
    assert initial is not None
    owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        channel["name"],
        "Accepted second head",
        False,
        _op(1_219),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    manifest = owner._workspace_current_manifest(owner._require_workspace(workspace_id))
    assert owner._identity is not None
    conflicting = create_workspace_channel_record(
        owner._identity,
        workspace_id=workspace_id,
        channel_id=channel["id"],
        manifest_digest=manifest.digest,
        name=channel["name"],
        topic="Conflicting second head",
        manager_member_id=initial.manager_member_id,
        manager_device_id=initial.manager_device_id,
        version=2,
        previous_hash=initial.digest,
    )
    assert not member._receive_workspace_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_record",
            logical_id=_op(1_220),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=conflicting,
        )
    )
    assert member._require_workspace(workspace_id)["state"] == "active"
    assert member._require_workspace_channel(workspace_id, channel["id"])[
        "state"
    ] == "forked"
    with pytest.raises(ContactNotApproved, match="always subscribed"):
        member.set_workspace_channel_subscription(
            workspace_id, workspace["general_channel_id"], False, _op(1_221)
        )
    owner.close()
    member.close()


def test_archived_channels_release_active_capacity_and_directory_summary_pages(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "channel-capacity", identity, "Alex")
    workspace = service.create_workspace(_op(1_300), "Capacity", "")
    channels = [
        service.create_workspace_channel(
            workspace["id"], f"channel-{index:02d}", "", _op(1_301 + index)
        )
        for index in range(31)
    ]
    with pytest.raises(ValidationError, match="at most 32"):
        service.create_workspace_channel(
            workspace["id"], "one-too-many", "", _op(1_340)
        )
    first = channels[0]
    service.update_workspace_channel(
        workspace["id"],
        first["id"],
        first["name"],
        first["topic"],
        True,
        _op(1_341),
    )
    service.create_workspace_channel(
        workspace["id"], "replacement", "", _op(1_342)
    )
    stored_workspace = service._require_workspace(workspace["id"])
    manifest = service._workspace_current_manifest(stored_workspace)
    assert service._identity is not None
    pages = service._workspace_channel_summary_documents(
        stored_workspace, manifest, service._identity, _op(1_343)
    )
    assert len(pages) == 2
    snapshot_channels = service.workspace_snapshot()["workspace_channels"]
    assert len(snapshot_channels) == 33
    assert sum(item["state"] == "active" for item in snapshot_channels) == 32
    assert service.sync_workspace_channels(workspace["id"], _op(1_344))[
        "state"
    ] == "converged"
    service.close()


def test_private_channel_membership_audience_transfer_recovery_leave_and_privacy(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path, base=3000)
    workspace_id = workspace["id"]
    owner_workspace = owner._require_workspace(workspace_id)
    member_workspace = member._require_workspace(workspace_id)
    owner_id = owner_workspace["local_member_id"]
    member_id = member_workspace["local_member_id"]

    private = owner.create_workspace_channel(
        workspace_id,
        "incident-room",
        "Need-to-know coordination",
        _op(3010),
        "private",
        [owner_id],
    )
    private_id = private["id"]
    assert private["visibility"] == "private"
    assert private["member_ids"] == [owner_id]
    assert _flush(owner, owner_network) == []
    assert owner._identity is not None
    assert all(
        private_id not in document
        for document in owner._workspace_channel_summary_documents(
            owner_workspace,
            owner._workspace_current_manifest(owner_workspace),
            owner._identity,
            _op(3011),
        )
    )

    owner.send_workspace_message(
        workspace_id, private_id, "before admission", _op(3012), _op(3013)
    )
    assert _flush(owner, owner_network) == []

    owner.update_workspace_private_channel_members(
        workspace_id, private_id, [owner_id, member_id], _op(3014)
    )
    admission_controls = _flush(owner, owner_network)
    assert len(admission_controls) == 1
    assert {
        parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for packet in admission_controls
    } == {"workspace_channel_manifest"}
    after_admission_message = owner.send_workspace_message(
        workspace_id, private_id, "after admission", _op(3015), _op(3016)
    )
    post_admission = _flush(owner, owner_network)
    assert len(post_admission) == 1
    # Data can arrive before its private admission checkpoint. It remains
    # encrypted and inert across restart until the signed control validates.
    _deliver_all(
        member,
        post_admission,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    assert private_id not in str(member.workspace_snapshot())
    member.close()
    member, member_network = _service(
        tmp_path / "member", member_identity, "Bailey", vault_key=member_key
    )
    member_profile = member._require_profile()
    assert len(member.store.list("workspace_pending_event")) == 1
    _deliver_all(
        member,
        admission_controls,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_private = next(
        channel
        for channel in member.workspace_snapshot()["workspace_channels"]
        if channel["id"] == private_id
    )
    assert member_private["member_ids"] == sorted([owner_id, member_id])
    assert member_private["unread_count"] == 1
    assert member.store.list("workspace_pending_control") == []
    assert member.store.list("workspace_pending_event") == []
    _deliver_all(
        member,
        admission_controls,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission"]

    owner.edit_workspace_message(
        workspace_id,
        after_admission_message["id"],
        "after admission revised",
        _op(3033),
        _op(3034),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, private_id)["messages"][0][
        "text"
    ] == "after admission revised"

    owner.send_workspace_message(
        workspace_id, private_id, "delayed across metadata", _op(3026), _op(3027)
    )
    owner.update_workspace_channel(
        workspace_id,
        private_id,
        "incident-room",
        "Updated need-to-know coordination",
        False,
        _op(3028),
    )
    delayed_packets = _flush(owner, owner_network)
    delayed_controls = [
        packet
        for packet in delayed_packets
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_channel_manifest"
    ]
    delayed_events = [
        packet
        for packet in delayed_packets
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_event"
    ]
    assert len(delayed_controls) == len(delayed_events) == 1
    _deliver_all(
        member,
        [*delayed_controls, *delayed_events],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission revised", "delayed across metadata"]

    owner.offer_workspace_channel_transfer(
        workspace_id, private_id, member_id, _op(3017)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    transfer = next(
        item
        for item in member.workspace_snapshot()["workspace_channel_transfers"]
        if item["channel_id"] == private_id
    )
    member.accept_workspace_channel_transfer(
        workspace_id, transfer["id"], _op(3018)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner._require_workspace_channel(workspace_id, private_id)[
        "manager_member_id"
    ] == member_id

    # The channel manager is not a message relay. Existing members keep
    # chatting while that manager is offline, and a rostered owner can sign a
    # recovery that validates when the manager reconnects.
    member.close()
    owner.send_workspace_message(
        workspace_id, private_id, "manager offline", _op(3031), _op(3032)
    )
    manager_offline_event = _flush(owner, owner_network)
    assert len(manager_offline_event) == 1
    owner.recover_workspace_channel(workspace_id, private_id, _op(3019))
    recovery_controls = _flush(owner, owner_network)
    assert len(recovery_controls) == 1
    member, member_network = _service(
        tmp_path / "member", member_identity, "Bailey", vault_key=member_key
    )
    member_profile = member._require_profile()
    _deliver_all(
        member,
        [*recovery_controls, *manager_offline_event],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member._require_workspace_channel(workspace_id, private_id)[
        "manager_member_id"
    ] == owner_id
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission revised", "delayed across metadata", "manager offline"]

    owner.send_workspace_message(
        workspace_id, private_id, "cancelled on departure", _op(3029), _op(3030)
    )
    member.save_workspace_draft(
        workspace_id,
        private_id,
        "@Alex private draft",
        _op(3035),
        [owner_id],
    )
    assert member.workspace_snapshot()["workspace_drafts"]
    member.leave_workspace_private_channel(workspace_id, private_id, _op(3020))
    assert member.workspace_snapshot()["workspace_drafts"] == []
    leave_packets = _flush(member, member_network)
    assert len(leave_packets) == 1
    _deliver_all(
        owner,
        leave_packets,
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner._require_workspace_channel(workspace_id, private_id)[
        "member_ids"
    ] == [owner_id]
    assert member._require_workspace_channel(workspace_id, private_id)[
        "state"
    ] == "leaving"
    assert _flush(owner, owner_network) == []
    cancelled = next(
        message
        for message in owner.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
        if message["text"] == "cancelled on departure"
    )
    assert cancelled["delivery_summary"]["devices_cancelled"] == 1
    owner.send_workspace_message(
        workspace_id, private_id, "after departure", _op(3021), _op(3022)
    )
    assert _flush(owner, owner_network) == []
    owner.update_workspace_channel(
        workspace_id,
        private_id,
        "incident-room",
        "Need-to-know coordination",
        True,
        _op(3023),
    )
    assert owner._require_workspace_channel(workspace_id, private_id)["state"] == "archived"

    member_only = member.create_workspace_channel(
        workspace_id,
        "member-only",
        "Owner is not a member",
        _op(3024),
        "private",
        [member_id],
    )
    member_only_id = member_only["id"]
    assert _flush(member, member_network) == []
    assert owner.store.get(
        "workspace_channel", owner._workspace_channel_record_id(member_only_id)
    ) is None
    assert member_only_id not in str(owner.workspace_snapshot())
    with pytest.raises(ValidationError, match="does not exist"):
        owner.recover_workspace_channel(workspace_id, member_only_id, _op(3025))

    owner.close()
    member.close()


def test_private_channel_fork_is_scoped_and_does_not_freeze_workspace(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    owner, _network = _service(tmp_path / "owner", owner_identity, "Alex")
    workspace = owner.create_workspace(_op(3100), "Fork lab", "Private controls")
    workspace_id = workspace["id"]
    owner_record = owner._require_workspace(workspace_id)
    owner_id = owner_record["local_member_id"]
    original_record = owner.create_workspace_channel(
        workspace_id,
        "incident-room",
        "Original",
        _op(3101),
        "private",
        [owner_id],
    )
    original = owner._workspace_channel_by_digest(original_record["head_hash"])
    assert original is not None
    owner.update_workspace_channel(
        workspace_id,
        original.channel_id,
        "incident-room",
        "First branch",
        False,
        _op(3102),
    )
    conflicting = create_workspace_channel_manifest(
        owner_identity,
        workspace_id=workspace_id,
        channel_id=original.channel_id,
        manifest_digest=original.manifest_digest,
        name="incident-room",
        topic="Conflicting branch",
        manager_member_id=original.manager_member_id,
        manager_device_id=original.manager_device_id,
        member_ids=original.member_ids,
        version=original.version + 1,
        previous_hash=original.digest,
        now=time.time(),
    )
    assert not owner._receive_workspace_private_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_manifest",
            logical_id=_op(3103),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 3600,
            document=conflicting,
        )
    )
    assert owner._require_workspace_channel(workspace_id, original.channel_id)[
        "state"
    ] == "forked"
    assert owner._require_workspace(workspace_id)["state"] == "active"
    owner.close()


def test_structured_mentions_unsubscribed_mute_read_draft_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "mentions", base=4_000)
    workspace_id = workspace["id"]
    owner_workspace = owner.workspace_snapshot()["workspaces"][0]
    member_workspace = member.workspace_snapshot()["workspaces"][0]
    owner_id = owner_workspace["local_member_id"]
    member_id = member_workspace["local_member_id"]

    channel = owner.create_workspace_channel(
        workspace_id, "field-alerts", "Unsubscribed alerts", _op(4_010)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_channel = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert member_channel["subscribed"] is False
    assert member_channel["mentions_muted"] is False

    raw_text = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey raw text does not create a mention",
        _op(4_011),
        _op(4_012),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []

    first = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey inspect the north gauge",
        _op(4_013),
        _op(4_014),
        [member_id],
    )
    second = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey confirm the reading",
        _op(4_015),
        _op(4_016),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    snapshot = member.workspace_snapshot()
    assert snapshot["workspaces"][0]["mention_unread_count"] == 2
    assert member._require_workspace(workspace_id)["mention_unread_count"] == 2
    original_get = member.store.get
    with monkeypatch.context() as patch:
        def no_message_body_reads(kind: str, record_id: str) -> Any:
            if kind == "workspace_message_state":
                raise AssertionError("workspace startup decrypted a message body")
            return original_get(kind, record_id)

        patch.setattr(member.store, "get", no_message_body_reads)
        assert member.workspace_snapshot()["workspaces"][0][
            "mention_unread_count"
        ] == 2
    assert next(
        item for item in snapshot["workspace_channels"] if item["id"] == channel["id"]
    )["unread_count"] == 0
    first_page = member.list_workspace_mentions(workspace_id, limit=1)
    assert first_page["mentions"][0]["message"]["id"] == second["id"]
    assert first_page["mentions"][0]["read"] is False
    assert first_page["next_cursor"] is not None

    member.set_workspace_channel_mentions_muted(
        workspace_id, channel["id"], True, _op(4_017)
    )
    assert member.workspace_snapshot()["workspaces"][0]["mention_unread_count"] == 0
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []
    with pytest.raises(ValidationError, match="cursor is stale"):
        member.list_workspace_mentions(
            workspace_id, cursor=first_page["next_cursor"], limit=1
        )
    member.set_workspace_channel_mentions_muted(
        workspace_id, channel["id"], False, _op(4_018)
    )
    restored = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in restored["mentions"]] == [
        second["id"],
        first["id"],
    ]
    member.mark_workspace_mentions_read(
        workspace_id, restored["high_water"], _op(4_019)
    )
    assert member.workspace_snapshot()["workspaces"][0]["mention_unread_count"] == 0

    owner.edit_workspace_message(
        workspace_id,
        first["id"],
        "Mention removed by a signed edit",
        _op(4_030),
        _op(4_031),
        [],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [second["id"]]

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "@Bailey now added by the structured picker",
        _op(4_032),
        _op(4_033),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    added = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in added["mentions"]] == [
        raw_text["id"],
        second["id"],
    ]
    assert added["unread_count"] == 1

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "Structured mention removed again",
        _op(4_034),
        _op(4_035),
        [],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_mentions(workspace_id)["unread_count"] == 0

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "@Bailey re-added without reviving the stale inbox entry",
        _op(4_036),
        _op(4_037),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    readded = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in readded["mentions"]] == [
        raw_text["id"],
        second["id"],
    ]
    assert readded["unread_count"] == 1
    member.mark_workspace_mentions_read(
        workspace_id, readded["high_water"], _op(4_038)
    )

    draft = member.save_workspace_draft(
        workspace_id,
        channel["id"],
        "@Alex restart-safe structured draft",
        _op(4_020),
        [owner_id],
    )
    assert draft["mention_member_ids"] == [owner_id]
    member.close()
    member, member_network = _service(
        tmp_path / "mentions" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.workspace_snapshot()
    assert restarted["workspaces"][0]["mention_unread_count"] == 0
    assert restarted["workspace_drafts"] == [draft]
    assert all(
        item["read"] for item in member.list_workspace_mentions(workspace_id)["mentions"]
    )

    with pytest.raises(ContactNotApproved, match="cannot read"):
        member.save_workspace_draft(
            workspace_id,
            channel["id"],
            "Invalid structured target",
            _op(4_021),
            [_op(4_099)],
        )
    owner.close()
    member.close()
