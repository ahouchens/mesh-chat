from __future__ import annotations

import os
from pathlib import Path

from mesh_chat.models import Contact, DeliveryState, Message, MessageKind, TrustState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def _contact(contact_id: str, trust: TrustState) -> dict[str, object]:
    return Contact(
        id=contact_id,
        display_name="Alex",
        public_identity="public",
        identity_hash="identity",
        destination_hash="destination",
        fingerprint="fingerprint",
        trust=trust,
    ).to_dict()


def _request(
    message_id: str,
    contact_id: str,
    state: DeliveryState,
    created_at: float,
) -> dict[str, object]:
    return Message(
        id=message_id,
        conversation_id="conversation",
        contact_id=contact_id,
        direction="outbound",
        kind=MessageKind.CONTACT_REQUEST,
        text="",
        state=state,
        created_at=created_at,
        expires_at=created_at + 3600,
    ).to_dict()


def test_snapshot_derives_latest_request_state_without_persisting_it(tmp_path: Path) -> None:
    awaiting_id = "awaiting"
    approved_id = "approved"
    store = VaultStore(
        tmp_path, os.urandom(32), allow_unprotected_for_tests=True
    )
    store.put("contact", awaiting_id, _contact(awaiting_id, TrustState.AWAITING_CONSENT))
    store.put("contact", approved_id, _contact(approved_id, TrustState.APPROVED))
    store.put(
        "message",
        "older-request",
        _request("older-request", awaiting_id, DeliveryState.WAITING_FOR_KEYS, 10),
    )
    store.put(
        "message",
        "latest-request",
        _request("latest-request", awaiting_id, DeliveryState.RECEIVED_BY_ENDPOINT, 20),
    )
    store.put(
        "message",
        "approved-request",
        _request("approved-request", approved_id, DeliveryState.DELIVERED, 30),
    )

    service = MeshChatService(store, tmp_path, lambda _event: None)
    try:
        contacts = {contact["id"]: contact for contact in service.snapshot()["contacts"]}
        assert contacts[awaiting_id]["request_state"] == "received_by_endpoint"
        assert "request_state" not in contacts[approved_id]
        assert "request_state" not in store.get("contact", awaiting_id)
    finally:
        service.close()
