import json
import time

import pytest

from mesh_chat.models import DeliveryState, MessageKind
from mesh_chat.webrtc_signaling import create_call_invite
from test_two_peer_service_flow import _approved_pair


def _invite(service, contact, *, expired=False):
    now = int(time.time()) - (1200 if expired else 0)
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    return create_call_invite(service._identity, call_id="call_0123456789abcdef",
        callee_destination=contact["destination_hash"], media="audio",
        sdp=f"v=0\r\na=fingerprint:{fingerprint}\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n",
        dtls_fingerprint=fingerprint, now=now)


def test_new_call_outbox_uses_signed_deadline(tmp_path):
    _, receiver, _, _, sender, _, contact = _approved_pair(tmp_path)
    try:
        document = _invite(sender, contact)
        message = sender._create_outbound(contact, MessageKind.CALL_SIGNAL, document)
        assert message["expires_at"] == json.loads(document)["expires_at"]
    finally:
        sender.close()
        receiver.close()


@pytest.mark.parametrize("recover", [False, True])
def test_legacy_expired_calls_do_not_replay_when_route_returns(tmp_path, recover):
    hub, receiver, _, _, sender, _, contact = _approved_pair(tmp_path)
    try:
        document = _invite(sender, contact, expired=True)
        message = sender._create_outbound(contact, MessageKind.CALL_SIGNAL, document)
        # Reproduce pre-fix durable records: chat retention outlives the SDP.
        message["expires_at"] = time.time() + 7 * 86400
        sender.store.put("message", message["id"], message)
        if recover:
            sender._recover_outbox()
        sender._attempt(message["id"])
        assert not hub.pending
        assert sender.store.get("message", message["id"])["state"] == "expired"
        assert message["id"] not in sender._direct_retry_snapshot()
        # A late failure callback cannot resurrect an expired signal.
        sender._on_native_status(message["id"], DeliveryState.QUEUED, "late-attempt")
        assert message["id"] not in sender._direct_retry_snapshot()
        chat = sender.send_message(contact["id"], "Messaging still works after stale calls")
        hub.drain()
        assert sender.store.get("message", chat["id"])["state"] == "delivered"
        assert receiver.calls.active() == []
    finally:
        sender.close()
        receiver.close()
