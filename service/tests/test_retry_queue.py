from __future__ import annotations

import os
from pathlib import Path

import pytest

from mesh_chat.errors import NetworkUnavailable, RecipientKeysUnavailable
from mesh_chat.models import DeliveryState, Message, MessageKind
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def _service(tmp_path: Path) -> MeshChatService:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    # _retry_once only needs a truthy transport; the transport-specific
    # methods are replaced below.
    service.network = object()
    service._expire_group_invitation_state = lambda *_args, **_kwargs: None
    service._retry_workspace_outbox = lambda: None
    service.reconcile_remote_profiles = lambda *_args, **_kwargs: None
    service.reconcile_participant_access = lambda *_args, **_kwargs: None
    service._refresh_callback_routes = lambda *_args, **_kwargs: None
    return service


def test_retry_once_does_not_scan_encrypted_message_history(tmp_path: Path) -> None:
    service = _service(tmp_path)
    listed: list[str] = []
    original_list = service.store.list

    def list_records(kind: str):
        listed.append(kind)
        return original_list(kind)

    service.store.list = list_records  # type: ignore[method-assign]
    try:
        message = Message(
            id="queued-one",
            conversation_id="conversation",
            contact_id="missing-contact",
            direction="outbound",
            kind=MessageKind.CHAT,
            text="queued",
            state=DeliveryState.QUEUED,
            created_at=1,
            expires_at=9_999_999_999,
        ).to_dict()
        service.store.put("message", message["id"], message)
        service._queue_direct_retry(message["id"])
        service._retry_once()
        assert "message" not in listed
        assert "group_delivery" not in listed
        # The failed/unsendable record remains queued for a later real retry.
        assert message["id"] in service._direct_retry_snapshot()
    finally:
        service.network = None
        service.close()


def test_direct_queue_can_drop_terminal_records(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        service._queue_direct_retry("gone")
        assert service._direct_retry_snapshot() == ["gone"]
        service._drop_direct_retry("gone")
        assert service._direct_retry_snapshot() == []
    finally:
        service.network = None
        service.close()


def test_group_queue_does_not_scan_history_and_waits_for_a_missing_commit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    listed: list[str] = []
    original_list = service.store.list

    def list_records(kind: str):
        listed.append(kind)
        return original_list(kind)

    service.store.list = list_records  # type: ignore[method-assign]
    try:
        service._queue_group_retry("not-committed-yet")
        service._retry_once()
        assert "group_delivery" not in listed
        # The creator may still be committing the record; the worker gets one
        # grace cycle before dropping a permanently absent ID.
        assert "not-committed-yet" in service._group_retry_snapshot()
        service._retry_once()
        assert "not-committed-yet" not in service._group_retry_snapshot()
        assert "group_delivery" not in listed
    finally:
        service.network = None
        service.close()


@pytest.mark.parametrize("error, expected", [
    (OSError("native handoff failed"), "queued"),
    (NetworkUnavailable("native handoff failed"), "queued"),
    (RecipientKeysUnavailable("ratchet unavailable"), "waiting_for_keys"),
])
def test_failed_handoff_after_sending_rejoins_retry_queue(tmp_path, error, expected) -> None:
    from test_two_peer_service_flow import _approved_pair

    hub, receiver, _, _, sender, network, contact = _approved_pair(tmp_path)
    original_send = network.send

    def failed_handoff(**values):
        sender._on_native_status(values["logical_id"], DeliveryState.SENDING, "failed-native")
        raise error

    try:
        network.send = failed_handoff
        sent = sender.send_message(contact["id"], "Retry after a failed native handoff")
        assert sent["state"] == expected
        assert sent["id"] in sender._direct_retry_snapshot()
        network.send = original_send
        sender._retry_once()
        hub.drain()
        assert sender.store.get("message", sent["id"])["state"] == "delivered"
        assert sent["id"] not in sender._direct_retry_snapshot()
        assert receiver.snapshot()["messages"][0]["text"] == sent["text"]
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("state", [
    DeliveryState.RECEIVED_BY_ENDPOINT, DeliveryState.STORED_FOR_DELIVERY,
    DeliveryState.DELIVERED,
])
def test_failed_handoff_preserves_stronger_delivery_evidence(tmp_path, state) -> None:
    from test_two_peer_service_flow import _approved_pair

    _, receiver, _, _, sender, network, contact = _approved_pair(tmp_path)

    def callback_then_raise(**values):
        sender._on_native_status(values["logical_id"], state, "accepted-native")
        raise OSError("handoff unwound after delivery evidence")

    try:
        network.send = callback_then_raise
        sent = sender.send_message(contact["id"], "Already accepted")
        assert sent["state"] == state.value
        assert sent["id"] not in sender._direct_retry_snapshot()
    finally:
        receiver.close()
        sender.close()
