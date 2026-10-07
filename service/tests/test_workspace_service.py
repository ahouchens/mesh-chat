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

from mesh_chat.errors import ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import DeliveryState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_channel_record,
    create_workspace_device_card,
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
