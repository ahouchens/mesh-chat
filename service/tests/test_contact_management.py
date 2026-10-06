from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from mesh_chat.errors import ContactInUse, ContactNotApproved
from mesh_chat.models import Contact, DeliveryState, Message, MessageKind, TrustState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def _service(tmp_path: Path, trust: TrustState = TrustState.APPROVED) -> MeshChatService:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    contact = Contact(
        id="taylor",
        display_name="Taylor",
        public_identity="public",
        identity_hash="22" * 16,
        destination_hash="11" * 16,
        fingerprint="1111 2222 3333 4444",
        trust=trust,
        connection_hints=[{"type": "tcp", "host": "192.0.2.10", "port": 4242}],
        created_at=1,
        updated_at=1,
    ).to_dict()
    contact["profile_name"] = "Taylor"
    store.put("contact", contact["id"], contact)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    return service


def test_contact_name_is_local_and_trust_controls_are_reversible(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        renamed = service.update_contact("taylor", "  T.   Morgan ")
        assert renamed["display_name"] == "T. Morgan"
        assert renamed["profile_name"] == "Taylor"

        verified = service.verify_contact("taylor")
        assert verified["trust"] == "verified"
        blocked = service.block_contact("taylor")
        assert blocked["trust"] == "blocked"
        assert blocked["trust_before_block"] == "verified"
        restored = service.unblock_contact("taylor")
        assert restored["trust"] == "verified"
        assert "trust_before_block" not in restored
        assert service.unverify_contact("taylor")["trust"] == "approved"
    finally:
        service.close()


def test_unapproved_contact_cannot_be_marked_verified(tmp_path: Path) -> None:
    service = _service(tmp_path, TrustState.AWAITING_CONSENT)
    try:
        with pytest.raises(ContactNotApproved):
            service.verify_contact("taylor")
        assert service.store.get("contact", "taylor")["trust"] == "awaiting_consent"
    finally:
        service.close()


def test_delete_contact_erases_direct_state_but_keeps_group_identity(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        now = time.time()
        chat = Message(
            id="chat",
            conversation_id="conversation",
            contact_id="taylor",
            direction="outbound",
            kind=MessageKind.CHAT,
            text="private text",
            state=DeliveryState.QUEUED,
            created_at=now,
            expires_at=now + 3600,
        ).to_dict()
        control = Message(
            id="receipt",
            conversation_id="conversation",
            contact_id="taylor",
            direction="outbound",
            kind=MessageKind.RECEIPT,
            text="",
            state=DeliveryState.QUEUED,
            created_at=now,
            expires_at=now + 3600,
            receipt_for="chat",
        ).to_dict()
        group = {
            "id": "group",
            "title": "Operations",
            "members": [
                {
                    "contact_id": "taylor",
                    "display_name": "Taylor",
                    "destination_hash": "11" * 16,
                    "status": "active",
                }
            ],
        }
        service.store.put_many(
            [
                ("message", chat["id"], chat),
                ("message", control["id"], control),
                ("draft", "taylor", {"contact_id": "taylor", "text": "draft"}),
                ("group", group["id"], group),
            ]
        )

        result = service.delete_contact("taylor")

        assert result == {"contact_id": "taylor", "deleted_messages": 1}
        assert service.store.get("contact", "taylor") is None
        assert service.store.list("message") == []
        assert service.store.get("draft", "taylor") is None
        assert service.store.list("conversation_hidden") == []
        saved_group = service.store.get("group", "group")
        assert saved_group["members"][0]["destination_hash"] == "11" * 16
        assert "contact_id" not in saved_group["members"][0]
        assert service.snapshot()["contacts"] == []
    finally:
        service.close()


def test_delete_contact_preserves_a_pending_group_invitation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        group = {
            "id": "group",
            "title": "Operations",
            "members": [
                {
                    "contact_id": "taylor",
                    "display_name": "Taylor",
                    "destination_hash": "11" * 16,
                    "status": "invited",
                }
            ],
        }
        service.store.put("group", group["id"], group)

        with pytest.raises(ContactInUse):
            service.delete_contact("taylor")

        assert service.store.get("contact", "taylor") is not None
        assert service.store.get("group", "group") == group
        assert service.store.list("conversation_hidden") == []
    finally:
        service.close()
