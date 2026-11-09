"""Durable intent plus actual local HTTP; no atomic remote-effect claim."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
import urllib.request
import os

import pytest

from mesh_chat import signal_mailbox
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from test_core_call_idempotency import control, open_client, FINGERPRINT
from test_core_messages import host

SDP = f"v=0\r\na=fingerprint:{FINGERPRINT}\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"


@pytest.fixture
def mailbox(monkeypatch):
    state = {"requests": [], "documents": {}, "lose_reply": False, "service": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = state["documents"].get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append(self.path)
            state["documents"][self.path] = body
            self.send_response(201)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(signal_mailbox._NoRedirect())

    def transport(request):
        service = state["service"]
        assert service.store._db.in_transaction is False
        if request.get_method() == "PUT":
            assert service.store.list("workspace_operation"), "HTTP cannot precede durable intent"
        url = f"http://127.0.0.1:{server.server_port}" + urlsplit(request.full_url).path
        response = opener.open(urllib.request.Request(url, data=request.data,
            headers=dict(request.header_items()), method=request.get_method()), timeout=3)
        if state["lose_reply"]:
            state["lose_reply"] = False
            response.close()
            raise OSError("reply lost after real HTTP store")
        return response

    monkeypatch.setattr(signal_mailbox, "_open", transport)
    yield state
    server.shutdown()
    server.server_close()
    thread.join(3)
    assert not thread.is_alive()


def prepare(service, mailbox):
    mailbox["service"] = service
    service.update_call_settings({**service._call_settings.to_dict(),
        "signal_mailbox_url": "https://signal.example.test", "store_call_signaling": False})
    return service.webrtc_onboarding_offer(SDP, FINGERPRINT)["document"]


def publish(client, document, key="signal-publish-key00"):
    return control(client, "signal_publish", key, document=document, role="offer")


def test_http_reply_loss_reuses_pairing_and_restart_fences_unknown_resource(host, mailbox):
    service = host()
    document = prepare(service, mailbox)
    client = open_client(service)
    mailbox["lose_reply"] = True
    first = publish(client, document)
    assert first["error"]["code"] == "unavailable", first
    assert len(mailbox["requests"]) == 1
    retried = publish(client, document)
    assert retried["ok"], retried
    assert len(mailbox["requests"]) == 2 and len(set(mailbox["requests"])) == 1
    assert publish(client, document) == retried
    assert len(mailbox["requests"]) == 2
    assert all(SDP.encode() not in body for body in mailbox["documents"].values())
    receipt = service.store.list("workspace_operation")
    assert "MESHPAIR2" not in str(receipt) and SDP not in str(receipt)
    changed = service.webrtc_onboarding_offer(SDP, FINGERPRINT)["document"]
    assert publish(client, changed)["error"]["code"] == "idempotency_conflict"
    service.close()
    reopened = host()
    mailbox["service"] = reopened
    assert publish(open_client(reopened), document)["error"]["code"] == "resync_required"
    assert len(mailbox["requests"]) == 2


def test_signal_intent_rollback_prevents_http_and_current_mailbox_policy_wins(host, mailbox, monkeypatch):
    service = host()
    document = prepare(service, mailbox)
    client = open_client(service)
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected signal intent transaction failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert publish(client, document)["error"]["code"] == "unavailable"
    assert mailbox["requests"] == [] and service.store.list("workspace_operation") == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert publish(client, document)["ok"]
    service.update_call_settings({**service._call_settings.to_dict(),
                                  "signal_mailbox_url": "https://other.example.test"})
    assert publish(client, document)["error"]["code"] == "resync_required"
    assert len(mailbox["requests"]) == 1


def test_signal_operation_slots_do_not_evict_uncertain_pairings(host, mailbox):
    service = host()
    document = prepare(service, mailbox)
    client = open_client(service)
    for index in range(32):
        assert publish(client, document, f"signal-operation-{index:03}")["ok"]
    exhausted = publish(client, document, "signal-operation-overflow")
    assert exhausted["error"]["code"] == "resource_exhausted", exhausted
    assert len(service._core_signal_attempts) == 32
    assert len(mailbox["requests"]) == 32
    assert publish(client, document, "signal-operation-000")["ok"]
    assert len(mailbox["requests"]) == 32


def test_keyed_answer_publishes_in_the_existing_verified_pairing(host, mailbox, tmp_path):
    service = host()
    document = prepare(service, mailbox)
    published = publish(open_client(service), document)
    assert published["ok"], published
    code = published["result"]["result"]["session_id"]
    store = VaultStore(tmp_path / "answerer", os.urandom(32), allow_unprotected_for_tests=True)
    answerer = MeshChatService(store, tmp_path / "answerer", lambda _: None)
    try:
        answerer.create_profile("Blair")
        answerer.update_call_settings({**answerer._call_settings.to_dict(),
            "signal_mailbox_url": "https://signal.example.test", "store_call_signaling": False})
        mailbox["service"] = answerer
        client = open_client(answerer)
        fetched = control(client, "signal_fetch", "fetch-signal-offer-key", session=code, role="offer")
        assert fetched["ok"], fetched
        answer = answerer.webrtc_onboarding_answer(document, SDP, FINGERPRINT)["document"]
        reply = control(client, "signal_publish", "publish-signal-answer", document=answer, role="answer")
        assert reply["ok"] and reply["result"]["result"]["session_id"] == code, reply
        assert control(client, "signal_publish", "publish-signal-answer", document=answer, role="answer") == reply
        assert len(mailbox["documents"]) == 2 and len(mailbox["requests"]) == 2
    finally:
        answerer.close()
