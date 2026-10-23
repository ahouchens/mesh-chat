from __future__ import annotations

import os
from pathlib import Path

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
