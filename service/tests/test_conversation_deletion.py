from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from mesh_chat.errors import ValidationError
from mesh_chat.models import Contact, DeliveryState, Message, MessageKind, TrustState
import mesh_chat.service as service_module
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class RecordingCancellationNetwork:
    interface_available = True

    def __init__(self, *, fail_cancel: bool = False) -> None:
        self.cancelled: list[set[str]] = []
        self.fail_cancel = fail_cancel

    def cancel_outbound(self, logical_ids: set[str]) -> int:
        self.cancelled.append(set(logical_ids))
        if self.fail_cancel:
            raise RuntimeError("adapter cancellation failed")
        return len(logical_ids)

    def snapshot(self) -> dict[str, object]:
        return {"interface_available": True, "interfaces": []}

    def shutdown(self) -> None:
        return None


def _message(
    message_id: str,
    contact_id: str,
    *,
    direction: str,
    kind: MessageKind = MessageKind.CHAT,
    text: str = "private text",
    receipt_for: str | None = None,
) -> dict[str, object]:
    now = time.time()
    return Message(
        id=message_id,
        conversation_id="conversation",
        contact_id=contact_id,
        direction=direction,
        kind=kind,
        text=text,
        state=DeliveryState.QUEUED,
        created_at=now,
        expires_at=now + 3600,
        receipt_for=receipt_for,
    ).to_dict()


def _direct_service(tmp_path: Path) -> tuple[MeshChatService, dict[str, object]]:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    contact = Contact(
        id="alex",
        display_name="Alex",
        public_identity="public",
        identity_hash="22" * 16,
        destination_hash="11" * 16,
        fingerprint="fingerprint",
        trust=TrustState.APPROVED,
    ).to_dict()
    store.put("contact", contact["id"], contact)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    return service, contact


def test_delete_direct_conversation_erases_chat_but_preserves_contact_and_control(
    tmp_path: Path,
) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        inbound = _message("inbound", contact["id"], direction="inbound")
        outbound = _message("outbound", contact["id"], direction="outbound")
        receipt = _message(
            "receipt",
            contact["id"],
            direction="outbound",
            kind=MessageKind.RECEIPT,
            text="",
            receipt_for="inbound",
        )
        control = _message(
            "accept",
            contact["id"],
            direction="outbound",
            kind=MessageKind.CONTACT_ACCEPT,
            text="",
        )
        service.store.put_many(
            [
                ("message", inbound["id"], inbound),
                ("message", outbound["id"], outbound),
                ("message", receipt["id"], receipt),
                ("message", control["id"], control),
                ("draft", contact["id"], {"contact_id": contact["id"], "text": "draft"}),
                # A colliding group logical ID must not be cancelled merely
                # because the remote sender selected the same direct ID.
                (
                    "group_delivery",
                    inbound["id"],
                    {
                        "id": inbound["id"],
                        "group_id": "farm",
                        "kind": MessageKind.GROUP_CHAT.value,
                    },
                ),
            ]
        )
        network = RecordingCancellationNetwork()
        service.network = network  # type: ignore[assignment]

        result = service.delete_conversation("direct", contact["id"])

        assert result == {"kind": "direct", "id": "alex", "deleted_messages": 2}
        assert service.store.get("contact", contact["id"]) == contact
        assert service.store.get("message", "accept") == control
        assert service.store.get("message", "inbound") is None
        assert service.store.get("message", "outbound") is None
        # Content-free receipts are protocol control jobs, not chat history;
        # keeping them prevents a delivered packet from being retried merely
        # because its local display copy was deleted.
        assert service.store.get("message", "receipt") == receipt
        assert service.store.get("draft", contact["id"]) is None
        assert service.store.get("group_delivery", "inbound") is not None
        assert network.cancelled == [{"outbound"}]
        snapshot = service.snapshot()
        assert snapshot["messages"] == []
        assert snapshot["hidden_conversations"] == [{"kind": "direct", "id": "alex"}]

        marker_ids = [
            row[0]
            for row in service.store._db.execute(
                "SELECT record_id FROM records "
                "WHERE kind IN ('conversation_hidden', 'discarded_message')"
            ).fetchall()
        ]
        assert len(marker_ids) == 2
        assert all(str(uuid.UUID(marker_id)) == marker_id for marker_id in marker_ids)
        assert all(
            value not in marker_id
            for marker_id in marker_ids
            for value in ("alex", "inbound", "direct")
        )
    finally:
        service.close()


def test_deleted_direct_replay_stays_hidden_but_fresh_inbound_reopens(
    tmp_path: Path,
) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        inbound = _message("old-message", contact["id"], direction="inbound")
        service.store.put("message", inbound["id"], inbound)
        service.delete_conversation("direct", contact["id"])
        native = SimpleNamespace(timestamp=time.time(), hash=b"native")
        replay = SimpleNamespace(
            logical_id="old-message",
            conversation_id="conversation",
            text="private text",
            expires_at=int(time.time()) + 3600,
        )

        service._receive_chat(contact, native, replay)

        assert service.snapshot()["messages"] == []
        assert service.snapshot()["hidden_conversations"] == [
            {"kind": "direct", "id": "alex"}
        ]
        assert any(
            item.get("kind") == MessageKind.RECEIPT.value
            and item.get("receipt_for") == "old-message"
            for item in service.store.list("message")
        )

        fresh = SimpleNamespace(
            logical_id="fresh-message",
            conversation_id="conversation",
            text="new private text",
            expires_at=int(time.time()) + 3600,
        )
        service._receive_chat(contact, native, fresh)

        snapshot = service.snapshot()
        assert [item["id"] for item in snapshot["messages"]] == ["fresh-message"]
        assert snapshot["hidden_conversations"] == []
    finally:
        service.close()


def test_restore_direct_conversation_keeps_history_deleted(tmp_path: Path) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        message = _message("old-message", contact["id"], direction="outbound")
        service.store.put("message", message["id"], message)
        service.delete_conversation("direct", contact["id"])

        restored = service.restore_conversation("direct", contact["id"])

        assert restored == {"kind": "direct", "id": "alex", "restored": True}
        snapshot = service.snapshot()
        assert snapshot["hidden_conversations"] == []
        assert snapshot["messages"] == []
        assert snapshot["contacts"][0]["trust"] == "approved"
    finally:
        service.close()


def test_delete_does_not_cancel_transport_when_vault_commit_fails(
    monkeypatch, tmp_path: Path
) -> None:
    service, contact = _direct_service(tmp_path)
    network = RecordingCancellationNetwork()
    service.network = network  # type: ignore[assignment]
    try:
        outbound = _message("outbound", contact["id"], direction="outbound")
        service.store.put("message", outbound["id"], outbound)

        def fail_commit(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("vault write failed")

        monkeypatch.setattr(service.store, "put_and_delete", fail_commit)
        with pytest.raises(RuntimeError, match="vault write failed"):
            service.delete_conversation("direct", contact["id"])

        assert network.cancelled == []
        assert service.store.get("message", outbound["id"]) == outbound
        assert service.store.list("conversation_hidden") == []
    finally:
        service.close()


def test_delete_remains_successful_when_native_cancellation_fails(tmp_path: Path) -> None:
    service, contact = _direct_service(tmp_path)
    network = RecordingCancellationNetwork(fail_cancel=True)
    service.network = network  # type: ignore[assignment]
    try:
        outbound = _message("outbound", contact["id"], direction="outbound")
        service.store.put("message", outbound["id"], outbound)

        result = service.delete_conversation("direct", contact["id"])

        assert result["deleted_messages"] == 1
        assert service.store.get("message", outbound["id"]) is None
        assert service.snapshot()["hidden_conversations"] == [
            {"kind": "direct", "id": "alex"}
        ]
        assert network.cancelled == [{"outbound"}]
    finally:
        service.close()


def test_direct_send_and_unhide_are_atomic_on_storage_failure(
    monkeypatch, tmp_path: Path
) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        service.store.put(
            "profile",
            "local",
            {
                "display_name": "Taylor",
                "destination_hash": "00" * 16,
            },
        )
        service.delete_conversation("direct", contact["id"])
        hidden_before = service.store.list("conversation_hidden")

        def fail_commit(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("vault write failed")

        monkeypatch.setattr(service.store, "put_and_delete", fail_commit)
        with pytest.raises(RuntimeError, match="vault write failed"):
            service.send_message(contact["id"], "do not persist partially")

        assert service.store.list("message") == []
        assert service.store.list("conversation_hidden") == hidden_before
    finally:
        service.close()


def test_successful_direct_send_persists_message_and_unhides_conversation(
    tmp_path: Path,
) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        service.store.put(
            "profile",
            "local",
            {
                "display_name": "Taylor",
                "destination_hash": "00" * 16,
            },
        )
        service.delete_conversation("direct", contact["id"])
        assert service.snapshot()["hidden_conversations"]

        sent = service.send_message(contact["id"], "start this conversation again")

        assert service.store.get("message", sent["id"]) == sent
        assert service.snapshot()["hidden_conversations"] == []
        assert [message["id"] for message in service.snapshot()["messages"]] == [
            sent["id"]
        ]
    finally:
        service.close()


@pytest.mark.parametrize("kind,target_id", [("direct", "alex"), ("group", "farm")])
def test_discard_marker_uses_the_protocol_integer_expiry_boundary(
    monkeypatch, tmp_path: Path, kind: str, target_id: str
) -> None:
    service, _contact = _direct_service(tmp_path)
    try:
        message = {
            "id": "old-message",
            "expires_at": 1_000.0,
            "direction": "inbound",
        }
        marker = service._discard_marker(kind, target_id, message, 1_000.0)
        assert marker is not None
        service.store.put(*marker)

        # parse_payload accepts the packet while int(now) is exactly one day
        # beyond expires_at, so the deletion marker must still win then.
        monkeypatch.setattr(service_module.time, "time", lambda: 87_400.999)
        assert service._message_was_discarded(kind, target_id, "old-message")

        # One integer second later parse_payload rejects the packet too; only
        # then may the marker be pruned.
        monkeypatch.setattr(service_module.time, "time", lambda: 87_401.0)
        assert not service._message_was_discarded(kind, target_id, "old-message")
    finally:
        service.close()


@pytest.mark.parametrize(
    "kind,target_id", [([], "alex"), ({"kind": "direct"}, "alex"), ("direct", [])]
)
def test_delete_conversation_rejects_malformed_targets_without_type_errors(
    tmp_path: Path, kind: object, target_id: object
) -> None:
    service, _contact = _direct_service(tmp_path)
    try:
        with pytest.raises(ValidationError, match="Conversation target is invalid"):
            service.dispatch(
                {
                    "v": 1,
                    "id": f"bad-{type(kind).__name__}-{type(target_id).__name__}",
                    "command": "delete_conversation",
                    "payload": {"kind": kind, "id": target_id},
                }
            )
    finally:
        service.close()


def test_inbound_direct_id_cannot_shadow_group_reaction_native_callback(
    tmp_path: Path,
) -> None:
    service, contact = _direct_service(tmp_path)
    try:
        collision_id = str(uuid.uuid4())
        inbound = _message(
            collision_id, contact["id"], direction="inbound"
        )
        group = {
            "id": "farm",
            "status": "active",
            "epoch": 2,
            "manifest_hash": "ab" * 32,
        }
        delivery = {
            "id": collision_id,
            "group_id": "farm",
            "kind": MessageKind.GROUP_REACTION.value,
            "state": DeliveryState.SENDING.value,
            "group_epoch": 2,
            "native_message_id": "native-group-leg",
        }
        service.store.put_many(
            [
                ("message", collision_id, inbound),
                ("group", "farm", group),
                ("group_delivery", collision_id, delivery),
            ]
        )

        service._on_native_status_locked(
            collision_id,
            DeliveryState.RECEIVED_BY_ENDPOINT,
            "native-group-leg",
        )

        assert service.store.get("message", collision_id) == inbound
        assert service.store.get("group_delivery", collision_id) is None
    finally:
        service.close()
