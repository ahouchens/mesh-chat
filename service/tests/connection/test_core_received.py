"""Bounded received-message pages over the real service, vault and projection."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from test_core_messages import client, host, request


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
CONTACT = "internal-peer"


def inbound(service, identifier, text, *, created_at=1_800_000_000.0, contact=CONTACT):
    service.store.put("message", identifier, {
        "id": identifier, "conversation_id": "direct:" + contact, "contact_id": contact,
        "direction": "inbound", "kind": "chat", "text": text, "state": "delivered",
        "created_at": created_at, "expires_at": created_at + 604800,
        "native_message_id": "ab" * 16, "receipt_for": None, "failure_code": None,
    })


def received(session, profile, *, cursor=None, limit=128):
    return session.request(request("message.received", profile=profile, cursor=cursor, limit=limit))


def page(session, profile, **kwargs):
    reply = received(session, profile, **kwargs)
    assert reply["ok"], reply
    return reply["result"]


def test_received_page_selects_only_public_fields_and_matches_its_contract(host):
    service = host()
    session, _, profile, peer = client(service)
    inbound(service, "message-0001", "Hello from Blair")
    result = page(session, profile)
    assert [(item["peer"], item["text"], item["state"]) for item in result["messages"]] == [
        (peer, "Hello from Blair", "delivered")]
    assert result["more"] is False and result["next_cursor"] is None
    encoded = json.dumps(result)
    assert "message-0001" not in encoded and CONTACT not in encoded
    schema = json.loads((CONTRACTS / "received-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(received(session, profile))


def test_index_commits_with_the_message_and_stores_no_text(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "Private body")
    indexed = service.store.list("received_message")
    assert len(indexed) == 1
    assert indexed[0]["message_id"] == "message-0001" and indexed[0]["contact_id"] == CONTACT
    assert "Private body" not in json.dumps(indexed)
    assert page(session, profile)["messages"][0]["text"] == "Private body"


def test_pagination_yields_each_message_once_in_chronological_order(host):
    service = host()
    session, _, profile, _ = client(service)
    for index in range(5):
        inbound(service, f"message-{index:04}", f"body {index}", created_at=1_800_000_000.0 + index)
    seen, cursor = [], None
    for _ in range(5):
        result = page(session, profile, cursor=cursor, limit=1)
        seen.extend(item["text"] for item in result["messages"])
        cursor = result["next_cursor"]
    assert cursor is None
    assert seen == [f"body {index}" for index in range(5)]


def test_only_inbound_chat_messages_are_listed(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "inbound-chat", "visible")
    service.store.put("message", "outbound-chat", {
        "id": "outbound-chat", "conversation_id": "direct:" + CONTACT, "contact_id": CONTACT,
        "direction": "outbound", "kind": "chat", "text": "hidden", "state": "queued",
        "created_at": 1_800_000_001.0, "expires_at": 1_800_000_001.0,
        "native_message_id": None, "receipt_for": None, "failure_code": None})
    service.store.put("message", "inbound-receipt", {
        "id": "inbound-receipt", "conversation_id": "direct:" + CONTACT, "contact_id": CONTACT,
        "direction": "inbound", "kind": "receipt", "text": "receipt", "state": "delivered",
        "created_at": 1_800_000_002.0, "expires_at": 1_800_000_002.0,
        "native_message_id": None, "receipt_for": "inbound-chat", "failure_code": None})
    assert [item["text"] for item in page(session, profile)["messages"]] == ["visible"]


def test_unapproved_contact_messages_are_hidden_and_invalidate_the_cursor(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "first")
    inbound(service, "message-0002", "second", created_at=1_800_000_100.0)
    first = page(session, profile, limit=1)
    assert first["more"] is True and first["next_cursor"] is not None
    record = service.store.get("contact", CONTACT)
    service.store.put("contact", CONTACT, {**record, "trust": "blocked"})
    assert page(session, profile)["messages"] == []
    blocked = received(session, profile, cursor=first["next_cursor"])
    assert blocked["error"]["code"] == "resync_required"


def test_unknown_contact_messages_are_not_readable(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "orphan", contact="removed-contact")
    assert page(session, profile)["messages"] == []


def test_handles_are_caller_scoped_and_cursors_cannot_cross_callers(host):
    service = host()
    alex, _, profile, alex_peer = client(service)
    inbound(service, "message-0001", "shared body")
    inbound(service, "message-0002", "second body", created_at=1_800_000_100.0)
    alex_page = page(alex, profile, limit=1)
    assert alex_page["more"] is True
    blair, _, other_profile, blair_peer = client(service, "blair")
    blair_page = page(blair, other_profile)
    assert alex_peer == alex_page["messages"][0]["peer"]
    assert blair_peer == blair_page["messages"][0]["peer"]
    assert alex_page["messages"][0]["message"] != blair_page["messages"][0]["message"]
    assert received(blair, other_profile, cursor=alex_page["next_cursor"])["error"]["code"] == "forbidden"


def test_cursor_purpose_cannot_be_confused_with_replay(host):
    service = host()
    session, _, profile, peer = client(service)
    from test_core_messages import enqueue
    enqueue(session, profile, peer)
    inbound(service, "message-0001", "body")
    snapshot_cursor = session.request(request("message.list", profile=profile, cursor=None, limit=128))
    assert snapshot_cursor["ok"], snapshot_cursor
    events_cursor = snapshot_cursor["result"]["events_cursor"]
    assert received(session, profile, cursor=events_cursor)["error"]["code"] == "invalid_request"


def test_state_and_contact_updates_do_not_move_or_duplicate_a_message(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "body")
    before = page(session, profile)["messages"]
    record = service.store.get("message", "message-0001")
    service.store.put("message", "message-0001", {**record, "state": "expired"})
    after = page(session, profile)["messages"]
    assert len(service.store.list("received_message")) == 1
    assert [item["message"] for item in after] == [item["message"] for item in before]
    assert after[0]["state"] == "expired"


def test_deleted_message_leaves_no_page_entry(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "body")
    service.store.delete("message", "message-0001")
    assert service.store.list("received_message") == []
    assert page(session, profile)["messages"] == []


def test_page_bounds_and_request_validation(host):
    service = host()
    session, _, profile, peer = client(service)
    inbound(service, "message-0001", "body")
    assert received(session, profile, limit=0)["error"]["code"] == "invalid_request"
    assert received(session, profile, limit=129)["error"]["code"] == "invalid_request"
    assert received(session, profile, cursor="not-a-cursor")["error"]["code"] == "invalid_request"
    from test_core_messages import enqueue
    enqueue(session, profile, peer)
    outbound_cursor = session.request(request("message.list", profile=profile, cursor=None, limit=128))
    assert outbound_cursor["ok"]
    assert received(session, profile, cursor="")["error"]["code"] == "invalid_request"


def test_cursor_survives_service_restart(host):
    service = host()
    session, _, profile, _ = client(service)
    inbound(service, "message-0001", "first")
    inbound(service, "message-0002", "second", created_at=1_800_000_100.0)
    first = page(session, profile, limit=1)
    service.close()
    reopened = host()
    again, _, same_profile, _ = client(reopened)
    assert page(again, same_profile, cursor=first["next_cursor"])["messages"][0]["text"] == "second"


def test_failed_projection_write_aborts_the_message_commit(host, monkeypatch):
    from mesh_chat.errors import StorageUnavailable
    service = host()
    session, _, profile, _ = client(service)
    original = service.store._seal

    def seal(kind, *args):
        if kind == "received_message":
            raise StorageUnavailable("received index unavailable")
        return original(kind, *args)

    monkeypatch.setattr(service.store, "_seal", seal)
    with pytest.raises(StorageUnavailable):
        inbound(service, "message-0001", "body")
    assert service.store.get("message", "message-0001") is None
    assert service.store.list("received_message") == []
    assert page(session, profile)["messages"] == []
