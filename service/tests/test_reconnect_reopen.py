"""Restart the real encrypted services and renegotiate using their saved identities.

The mailbox and SDP are fixtures; these tests do not claim live ICE connectivity.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

import pytest

from mesh_chat.errors import ContactNotApproved, ReconnectReplayed, ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from test_reconnect_service import FINGERPRINT, SDP, FakeMailbox, _pair


def _reopen(root: Path, monkeypatch: pytest.MonkeyPatch) -> MeshChatService:
    # Keep identity/profile/settings intact, unlike creating a new fixture peer.
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *args: None)
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).digest()
    store = VaultStore(root, key, allow_unprotected_for_tests=True)
    service = MeshChatService(store, root, lambda _event: None)
    service._shutdown.set()
    return service


def _handshake(alex: MeshChatService, blair: MeshChatService) -> tuple[str, str]:
    a = alex.reconnect_profiles()["profiles"][0]
    b = blair.reconnect_profiles()["profiles"][0]
    assert a["effective"]["ready"] and b["effective"]["ready"]
    assert a["effective"]["session"] == b["effective"]["session"]
    request = alex.reconnect_request_create(a["contact_id"], uuid.uuid4().hex)
    alex.reconnect_publish(a["id"], request["document"], "request")
    received = blair.reconnect_fetch(b["id"], "request")["document"]
    blair.verify_reconnect_request(received, b["id"])
    offer = blair.reconnect_offer_create(b["contact_id"], received, SDP, FINGERPRINT)
    blair.reconnect_publish(b["id"], offer["document"], "offer")
    received = alex.reconnect_fetch(a["id"], "offer")["document"]
    assert alex.verify_reconnect_offer(received, a["id"])["sdp"] == SDP
    answer = alex.reconnect_answer_create(a["contact_id"], received, SDP, FINGERPRINT)
    alex.reconnect_publish(a["id"], answer["document"], "answer")
    received = blair.reconnect_fetch(b["id"], "answer")["document"]
    assert blair.verify_reconnect_answer(received, offer["document"], b["id"])["sdp"] == SDP
    return offer["document"], answer["document"]


@pytest.mark.parametrize("days_offline", [0, 45])
def test_default_reconnect_negotiates_after_both_services_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, days_offline: int,
) -> None:
    mailbox = FakeMailbox()
    monkeypatch.setattr("mesh_chat.reconnect_service.publish_signal", mailbox.publish)
    monkeypatch.setattr("mesh_chat.reconnect_service.fetch_signal", mailbox.fetch)
    alex, blair_id, blair, alex_id = _pair(tmp_path)
    services = [alex, blair]
    try:
        identities = [service._call_identity().get_public_key() for service in services]
        for service in services:
            # Existing relay consent is independent of the reconnect default.
            service._call_settings.turn_broker_consent = True
            service.store.put("call_settings", "default", service._call_settings.to_dict())
        alex_doc = alex._contact_capabilities(alex.store.get("contact", blair_id))
        blair_doc = blair._contact_capabilities(blair.store.get("contact", alex_id))
        blair.reconnect_capabilities_store(alex_doc)
        alex.reconnect_capabilities_store(blair_doc)
        for service in services:
            profile = service.reconnect_profiles()["profiles"][0]
            assert profile["auto_reconnect"] is True
            assert profile["allow_direct_ip_disclosure"] is False
            assert profile["capabilities_persistent"] is True
            assert profile["peer_capabilities_persistent"] is True
        old_offer, old_answer = _handshake(alex, blair)
        for service in services:
            service.close()
        services = []
        reopened_at = int(time.time()) + days_offline * 24 * 60 * 60
        monkeypatch.setattr("mesh_chat.reconnect_service._now", lambda: reopened_at)
        monkeypatch.setattr("mesh_chat.reconnect._now", lambda value=None: reopened_at if value is None else value)
        alex = _reopen(tmp_path / "alex", monkeypatch)
        services.append(alex)
        blair = _reopen(tmp_path / "blair", monkeypatch)
        services.append(blair)
        assert [service._call_identity().get_public_key() for service in services] == identities
        assert alex.reconnect_capabilities_get(blair_id)["local_capabilities"] == alex_doc
        assert blair.reconnect_capabilities_get(alex_id)["local_capabilities"] == blair_doc
        new_offer, new_answer = _handshake(alex, blair)
        assert new_offer != old_offer and new_answer != old_answer
        with pytest.raises(ValidationError if days_offline else ReconnectReplayed):
            blair.verify_reconnect_answer(old_answer, old_offer)

        # Deliberately disabling survives another app restart and prevents requests.
        alex.reconnect_consent_set(blair_id, False, False)
        alex.close()
        services.remove(alex)
        alex = _reopen(tmp_path / "alex", monkeypatch)
        services.append(alex)
        assert alex.reconnect_profiles()["profiles"][0]["auto_reconnect"] is False
        with pytest.raises(ContactNotApproved):
            alex.reconnect_request_create(blair_id, uuid.uuid4().hex)
    finally:
        for service in services:
            service.close()
