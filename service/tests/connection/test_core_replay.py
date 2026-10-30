from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from test_core_messages import host, client, enqueue, request


def snapshot(session, profile, *, cursor=None, limit=128):
    return session.request(request("message.list", profile=profile, cursor=cursor, limit=limit))


def poll(session, profile, cursor, *, limit=128):
    return session.request(request("events.poll", profile=profile, cursor=cursor, limit=limit))


def test_snapshot_and_replay_have_no_query_subscribe_gap(host):
    service = host()
    session, _, profile, peer = client(service)
    accepted = enqueue(session, profile, peer)
    initial = snapshot(session, profile)
    assert initial["ok"], initial
    assert initial["result"]["messages"][0]["state"] == "queued"
    cursor = initial["result"]["events_cursor"]
    record = service.store.list("message")[0]
    for state in ("received_by_endpoint", "delivered"):
        service.store.put("message", record["id"], {**record, "state": state})
    replay = poll(session, profile, cursor)
    assert replay["ok"], replay
    changes = replay["result"]["events"]
    assert [item["state"] for item in changes] == ["received_by_endpoint", "delivered"]
    assert all(item["message"] == accepted["result"]["message"] for item in changes)
    assert poll(session, profile, cursor)["result"]["events"] == changes
    assert poll(session, profile, replay["result"]["next_cursor"])["result"]["events"] == []


def test_durable_cursor_survives_service_restart(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    record = service.store.list("message")[0]
    service.store.put("message", record["id"], {**record, "state": "delivered"})
    service.close()
    reopened = host()
    again, _, _, _ = client(reopened)
    assert [item["state"] for item in poll(again, profile, cursor)["result"]["events"]] == ["delivered"]


def test_snapshot_pagination_requires_one_consistent_revision(host):
    service = host()
    session, _, profile, peer = client(service)
    for index in range(3): enqueue(session, profile, peer, key=f"enqueue-key-{index:04}")
    first = snapshot(session, profile, limit=1)["result"]
    assert len(first["messages"]) == 1 and first["events_cursor"] is None
    next_page = snapshot(session, profile, cursor=first["next_cursor"], limit=1)["result"]
    assert first["messages"][0]["message"] != next_page["messages"][0]["message"]
    record = service.store.list("message")[0]
    service.store.put("message", record["id"], {**record, "state": "delivered"})
    assert snapshot(session, profile, cursor=next_page["next_cursor"])["error"]["code"] == "resync_required"


def test_pagination_ends_with_a_watermark_and_no_missing_or_duplicate_messages(host):
    service = host()
    session, _, profile, peer = client(service)
    expected = {enqueue(session, profile, peer, key=f"enqueue-key-{index:04}")["result"]["message"] for index in range(5)}
    seen, cursor = [], None
    for _ in range(5):
        page = snapshot(session, profile, cursor=cursor, limit=1)["result"]
        seen.extend(item["message"] for item in page["messages"])
        cursor = page["next_cursor"]
    assert cursor is None and page["events_cursor"] is not None
    assert len(seen) == len(set(seen)) and set(seen) == expected


def test_cursors_are_caller_scoped_and_snapshot_cursors_cannot_be_used_for_events(host):
    service = host()
    alex, _, profile, peer = client(service)
    for index in range(2): enqueue(alex, profile, peer, key=f"enqueue-key-{index:04}")
    page = snapshot(alex, profile, limit=1)["result"]
    assert poll(alex, profile, page["next_cursor"])["error"]["code"] == "invalid_request"
    cursor = snapshot(alex, profile)["result"]["events_cursor"]
    blair, _, other_profile, _ = client(service, "blair")
    assert poll(blair, other_profile, cursor)["error"]["code"] == "forbidden"
    assert snapshot(blair, other_profile, cursor=page["next_cursor"])["error"]["code"] == "forbidden"
    assert snapshot(blair, other_profile)["result"]["messages"] == []


@pytest.mark.parametrize("change", ["permission", "profile", "contact", "locked", "detach"])
def test_recovery_rechecks_current_authority(host, change):
    service = host()
    session, grants, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    if change == "permission": grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    if change == "profile": grants[0] = replace(grants[0], profiles=())
    if change == "locked": service._identity = None
    if change == "detach": session.detach()
    if change == "contact":
        contact = service.store.get("contact", "internal-peer")
        service.store.put("contact", "internal-peer", {**contact, "trust": "blocked"})
    reply = poll(session, profile, cursor)
    assert reply["error"]["code"] in {"forbidden", "resync_required", "locked", "unauthenticated"}


def test_deleted_message_produces_a_content_free_removal_event(host):
    service = host()
    session, _, profile, peer = client(service)
    handle = enqueue(session, profile, peer)["result"]["message"]
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    service.store.delete("message", service.store.list("message")[0]["id"])
    event = poll(session, profile, cursor)["result"]["events"][0]
    assert event["message"] == handle and event["type"] == "message.removed" and event["state"] is None
    assert "Hello" not in json.dumps(event)
    assert snapshot(session, profile)["result"]["messages"] == []


def test_slow_reader_gets_explicit_resynchronization_on_retention_overflow(host, monkeypatch):
    from mesh_chat import message_journal
    monkeypatch.setattr(message_journal, "MAX_EVENTS", 4)
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    for index in range(6): enqueue(session, profile, peer, key=f"enqueue-key-{index:04}")
    assert poll(session, profile, cursor)["error"]["code"] == "resync_required"
    assert snapshot(session, profile)["ok"]


def test_snapshot_response_obeys_encoded_byte_budget(host):
    service = host()
    session, _, profile, peer = client(service)
    for index in range(20):
        assert enqueue(session, profile, peer, key=f"enqueue-key-{index:04}", text="\x01" * 16384)["ok"]
    reply = snapshot(session, profile)
    assert reply["ok"] and reply["result"]["next_cursor"] is not None
    assert len(json.dumps(reply).encode("utf-8")) <= 1048576


def test_stream_contracts_and_cursors_hide_internal_ids(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    page = snapshot(session, profile)
    replay = poll(session, profile, page["result"]["events_cursor"])
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    schema = json.loads((root / "recovery-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    for reply in (page, replay): Draft202012Validator(schema).validate(reply)
    assert "internal-peer" not in json.dumps([page, replay])
    assert service.store.list("message")[0]["id"] not in json.dumps([page, replay])
    Draft202012Validator(json.loads((root / "request-v1.schema.json").read_text())).validate(
        request("events.poll", profile=profile, cursor=page["result"]["events_cursor"], limit=128))


@pytest.mark.parametrize("limit", [True, 0, 129, "1"])
def test_recovery_bounds_are_enforced_before_domain_access(host, limit):
    session, _, profile, _ = client(host())
    assert snapshot(session, profile, limit=limit)["error"]["code"] == "invalid_request"


def test_poll_without_a_snapshot_cannot_silently_skip_history(host):
    session, _, profile, _ = client(host())
    assert poll(session, profile, None)["error"]["code"] == "resync_required"


def test_expired_cursor_requires_a_new_snapshot(host, monkeypatch):
    from mesh_chat.core_api import service_recovery
    service = host()
    session, _, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    future = service_recovery.time.time() + 8 * 86400
    monkeypatch.setattr(service_recovery.time, "time", lambda: future)
    assert poll(session, profile, cursor)["error"]["code"] == "resync_required"
    assert snapshot(session, profile)["ok"]


def test_foreign_messages_and_events_are_filtered_without_unbounded_scans(host, monkeypatch):
    service = host()
    alex, _, profile, _ = client(service)
    cursor = snapshot(alex, profile)["result"]["events_cursor"]
    blair, _, other_profile, other_peer = client(service, "blair")
    for index in range(140):
        assert enqueue(blair, other_profile, other_peer, key=f"enqueue-key-{index:04}")["ok"]
    opened = set()
    original = service.store._open
    def track(kind, identifier, sealed):
        if kind == "api_message": opened.add(identifier)
        return original(kind, identifier, sealed)
    monkeypatch.setattr(service.store, "_open", track)
    first = snapshot(alex, profile)["result"]
    assert first["messages"] == [] and first["next_cursor"] is not None
    assert len(opened) == 129
    last = snapshot(alex, profile, cursor=first["next_cursor"])["result"]
    assert last["messages"] == [] and last["next_cursor"] is None
    first_poll = poll(alex, profile, cursor)["result"]
    assert first_poll["events"] == [] and first_poll["more"] is True
    last_poll = poll(alex, profile, first_poll["next_cursor"])["result"]
    assert last_poll["events"] == [] and last_poll["more"] is False


def test_detach_does_not_stop_journaling_or_the_durable_outbox(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    session.detach()
    record = service.store.list("message")[0]
    service.store.put("message", record["id"], {**record, "state": "received_by_endpoint"})
    again, _, _, _ = client(service)
    assert poll(again, profile, cursor)["result"]["events"][0]["state"] == "received_by_endpoint"


def test_signed_receipt_commits_a_replay_event_through_the_existing_delivery_path(tmp_path):
    from test_two_peer_service_flow import _approved_pair
    hub, receiver, _, _, sender, _, _ = _approved_pair(tmp_path)
    try:
        sender._retry_thread.join(timeout=1)
        assert not sender._retry_thread.is_alive()
        sender._shutdown.clear()
        session, _, profile, peer = client(sender)
        accepted = enqueue(session, profile, peer)
        cursor = snapshot(session, profile)["result"]["events_cursor"]
        sender._retry_once()
        hub.drain()
        changes = poll(session, profile, cursor)["result"]["events"]
        assert changes[-1]["state"] == "delivered"
        assert all(item["message"] == accepted["result"]["message"] for item in changes)
        assert "Hello" not in json.dumps(changes)
    finally:
        receiver.close()
        sender.close()
