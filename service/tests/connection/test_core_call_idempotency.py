"""Real call-domain commits and replay through the serialized Core session."""

import pytest
import RNS

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.webrtc_signaling import create_call_invite
from test_core_messages import host


FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "\r\n".join(["v=0", "o=- 1 2 IN IP4 127.0.0.1", "s=-", "t=0 0",
                     "a=fingerprint:" + FINGERPRINT,
                     "m=audio 9 UDP/TLS/RTP/SAVPF 111", "a=mid:0"]) + "\r\n"


def open_client(service):
    session = bind_service_stream(service, lambda: Grant(
        "call-ui", frozenset({"observe", "send", "read"}), ("local",)))
    reply = decode_frame(session.exchange(encode_frame({"api_version": 1,
        "request_id": "call:1", "operation": "runtime.capabilities", "params": {}})))
    return session, reply["result"]["profiles"][0]


def control(client, action, key, **params):
    session, profile = client
    return decode_frame(session.exchange(encode_frame({"api_version": 1,
        "request_id": "call:1", "operation": "call.control", "idempotency_key": key,
        "params": {"profile": profile, "action": action, **params}})))


def start(client, key="start-call-operation", media="audio"):
    return control(client, "start", key, contact_id="internal-peer", media=media,
                   sdp=SDP, dtls_fingerprint=FINGERPRINT)


def test_call_start_candidate_and_end_replay_without_duplicate_signals(host):
    service = host()
    client = open_client(service)
    created = start(client)
    assert created["ok"], created
    identifier = created["result"]["result"]["id"]
    assert start(client) == start(open_client(service)) == created
    assert len(service.store.list("call")) == len(service.store.list("message")) == 1
    conflict = start(client, media="video")
    assert conflict["error"]["code"] == "idempotency_conflict", conflict
    candidate = {"call_id": identifier, "candidate": "candidate:1 1 UDP 2122252543 192.0.2.1 54400 typ host"}
    added = control(client, "candidate", "candidate-call-key00", **candidate)
    assert added["ok"], added
    assert control(client, "candidate", "candidate-call-key00", **candidate) == added
    assert len(service.store.get("call", identifier)["candidates"]) == 1
    ended = control(client, "end", "end-call-operation00", call_id=identifier, reason="completed")
    assert ended["ok"], ended
    assert control(client, "end", "end-call-operation00", call_id=identifier, reason="completed") == ended
    assert service.store.get("call", identifier)["state"] == "ended"
    assert len(service.store.list("message")) == 3
    superseded = start(client)
    assert superseded["result"]["result"]["state"] == "ended"
    assert superseded["result"]["result"]["candidate_count"] == 1
    assert len(service.store.list("message")) == 3
    contact = service.store.get("contact", "internal-peer")
    contact["trust"] = "blocked"
    service.store.put("contact", "internal-peer", contact)
    assert start(client)["error"]["code"] == "forbidden"


def test_call_replay_checks_ring_deadline_without_a_background_query(host, monkeypatch):
    service = host()
    client = open_client(service)
    created = start(client)
    call = created["result"]["result"]
    monkeypatch.setattr(service.calls, "now", lambda: call["ring_expires_at"] + 1)
    expired = start(client)
    assert expired["ok"], expired
    assert expired["result"]["result"]["state"] == "no_answer"
    assert service.store.get("call", call["id"])["state"] == "no_answer"
    assert len(service.store.list("message")) == 1


def test_call_write_failure_rolls_back_state_outbox_and_receipt(host, monkeypatch):
    service = host()
    client = open_client(service)
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    original = service.store._write_records_locked
    attempts = []
    monkeypatch.setattr(service, "_attempt", lambda *_: attempts.append(True))

    def fail(*args):
        original(*args)
        raise OSError("injected call commit failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert start(client)["error"]["code"] == "unavailable"
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    assert service.calls._memory == {} and attempts == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert start(client)["ok"]
    assert attempts == [True]


def test_post_commit_transport_failure_and_restart_never_reenqueue(host, monkeypatch):
    service = host()
    client = open_client(service)
    attempts = []

    def fail_transport(*_):
        attempts.append(True)
        raise OSError("injected after durable call commit")

    monkeypatch.setattr(service, "_attempt", fail_transport)
    assert start(client)["error"]["code"] == "unavailable"
    created = start(client)
    assert created["ok"] and attempts == [True]
    identifier = created["result"]["result"]["id"]
    assert len(service.store.list("message")) == 1
    service.close()
    reopened = host()
    assert start(open_client(reopened))["error"]["code"] == "resync_required"
    assert [item["id"] for item in reopened.store.list("call")] == [identifier]
    assert len(reopened.store.list("message")) == 1


def test_call_storage_preference_is_preserved_and_receipt_contains_no_sdp(host):
    service = host()
    service.update_call_settings({**service._call_settings.to_dict(), "store_call_signaling": False})
    client = open_client(service)
    created = start(client)
    assert created["ok"], created
    assert service.store.list("call") == []
    assert start(client) == created
    assert all(SDP not in str(item) and "call_invite" not in str(item)
               for item in service.store.list("workspace_operation"))
    service.close()
    reopened = host()
    assert reopened.calls.persist is False
    assert start(open_client(reopened))["error"]["code"] == "resync_required"
    assert reopened.store.list("call") == []


def test_prepared_answer_does_not_mutate_live_call_before_commit(host, monkeypatch):
    service = host()
    remote = RNS.Identity()
    contact = service.store.get("contact", "internal-peer")
    contact["destination_hash"] = RNS.Destination.hash(remote, "lxmf", "delivery").hex()
    service.store.put("contact", "internal-peer", contact)
    document = create_call_invite(remote, call_id="inbound-call-001", media="audio", sdp=SDP,
        dtls_fingerprint=FINGERPRINT, callee_destination=service._require_profile()["destination_hash"])
    service.calls.receive(service._identity, contact, document)
    client = open_client(service)
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected answer commit failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    params = {"call_id": "inbound-call-001", "sdp": SDP, "dtls_fingerprint": FINGERPRINT}
    assert control(client, "answer", "answer-call-operation", **params)["error"]["code"] == "unavailable"
    assert service.calls._memory["inbound-call-001"]["state"] == "ringing"
    assert service.store.get("call", "inbound-call-001")["state"] == "ringing"
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    answered = control(client, "answer", "answer-call-operation", **params)
    assert answered["ok"], answered
    assert control(client, "answer", "answer-call-operation", **params) == answered
    assert len(service.store.list("message")) == 1
