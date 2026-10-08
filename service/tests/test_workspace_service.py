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
        _member_key,
        _member_identity,
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
