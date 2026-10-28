"""Opt-in protocol smoke test against Wrangler dev or an owned staging Worker.

MESH_CHAT_TEST_SIGNAL_URL=http://127.0.0.1:8789 python -m pytest ...
Only synthetic identities/documents are used. No real chat traffic is sent.
"""
from __future__ import annotations

import os
import urllib.request
import uuid
from urllib.parse import urlsplit

import pytest

from mesh_chat import signal_mailbox
from mesh_chat.call_settings import CallSettings
from mesh_chat.service import MeshChatService
from mesh_chat.webrtc_onboarding import create_onboarding_offer, create_onboarding_answer, verify_onboarding_offer, verify_onboarding_answer
from test_reconnect_scope import Peer, WORKSPACES, enable_pair, scope, SDP, FINGERPRINT

TARGET = os.environ.get("MESH_CHAT_TEST_SIGNAL_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not TARGET, reason="requires an explicitly configured test Worker")


@pytest.fixture
def worker(monkeypatch):
    parsed = urlsplit(TARGET)
    assert parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
    opener = urllib.request.build_opener(signal_mailbox._NoRedirect(),
                                        urllib.request.HTTPSHandler(context=signal_mailbox._context()))
    captured = []
    def transport(request):
        # Local HTTP is test-only; the production client always requires HTTPS.
        url = TARGET + urlsplit(request.full_url).path
        captured.append(request.data or b"")
        return opener.open(urllib.request.Request(url, data=request.data,
            headers=dict(request.header_items()), method=request.get_method()), timeout=10)
    monkeypatch.setattr(signal_mailbox, "_open", transport)
    return captured


@pytest.mark.parametrize("workspace_id", [None, WORKSPACES[0]])
def test_real_worker_encrypted_reconnect(worker, workspace_id):
    alex, blair = Peer("alex-" + uuid.uuid4().hex), Peer("blair-" + uuid.uuid4().hex)
    for local, other in ((alex, blair), (blair, alex)):
        local.add_contact(other)
        if workspace_id:
            local.add_workspace(other, workspace_id)
    left, right = enable_pair(alex, blair, workspace_id)
    left_id, right_id = left["profile"]["id"], right["profile"]["id"]
    request = alex.reconnect_request_create(scope(blair, workspace_id), uuid.uuid4().hex)
    alex.reconnect_publish(left_id, request["document"], "request")
    received = blair.reconnect_fetch(right_id, "request")["document"]
    assert received == request["document"]
    offer = blair.reconnect_offer_create(scope(alex, workspace_id), received, SDP, FINGERPRINT)
    blair.reconnect_publish(right_id, offer["document"], "offer")
    received = alex.reconnect_fetch(left_id, "offer")["document"]
    answer = alex.reconnect_answer_create(scope(blair, workspace_id), received, SDP, FINGERPRINT)
    alex.reconnect_publish(left_id, answer["document"], "answer")
    received = blair.reconnect_fetch(right_id, "answer")["document"]
    assert blair.verify_reconnect_answer(received, offer["document"], right_id)["attempt_id"] == request["attempt_id"]
    assert all(alex.destination.encode() not in body and b"fingerprint" not in body for body in worker)


def test_real_worker_encrypted_onboarding(worker):
    import RNS
    clients = []
    for _ in range(2):
        service = object.__new__(MeshChatService)
        identity = RNS.Identity()
        destination = RNS.Destination.hash(identity, "lxmf", "delivery").hex()
        service._require_profile = lambda dest=destination: {"destination_hash": dest}
        service._call_settings = CallSettings(signal_mailbox_url="https://signal.example.test")
        clients.append((service, identity))
    (owner, identity), (joiner, peer) = clients
    offer = create_onboarding_offer(identity, session_id=uuid.uuid4().hex, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    code = owner.signal_publish(offer, "offer")["session_id"]
    fetched = joiner.signal_fetch(code, "offer")["document"]
    answer = create_onboarding_answer(peer, verify_onboarding_offer(fetched), sdp=SDP, dtls_fingerprint=FINGERPRINT)
    assert joiner.signal_publish(answer, "answer")["session_id"] == code
    received = owner.signal_fetch(code, "answer")["document"]
    assert verify_onboarding_answer(received, verify_onboarding_offer(offer)).session_id == verify_onboarding_offer(offer).session_id
    assert all(b"fingerprint" not in body for body in worker)
