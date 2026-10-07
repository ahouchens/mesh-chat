from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path
from typing import Any

import LXMF
import pytest
import RNS

from mesh_chat.errors import ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import DeliveryState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_wire import parse_workspace_payload


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
    root: Path, identity: RNS.Identity, display_name: str
) -> tuple[MeshChatService, RecordingWorkspaceNetwork]:
    store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, root, lambda _event: None)
    service._shutdown.set()
    service._identity = identity
    store.put("profile", "local", _profile(identity, display_name))
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
    joiner.store.put("workspace_manifest", offered_manifest_id, offered_manifest)
    joiner._drain_workspace_pending_controls(workspace["id"])
    assert joiner.store.list("workspace_pending_control") == []
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
        "devices_total": 1,
        "devices_reached": 1,
        "devices_pending": 0,
        "devices_failed": 0,
    }
    monkeypatch.setattr(owner.store, "list", original_list)

    owner.close()
    joiner.close()


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
