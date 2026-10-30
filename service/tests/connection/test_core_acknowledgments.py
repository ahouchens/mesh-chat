from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from test_core_messages import host, client, enqueue, request
from test_core_replay import snapshot, poll


def acknowledge(session, profile, cursor, key="acknowledge-00001"):
    value = request("events.ack", profile=profile, cursor=cursor)
    value["idempotency_key"] = key
    return session.request(value)


def advance(service, state):
    message = service.store.list("message")[0]
    service.store.put("message", message["id"], {**message, "state": state})


def test_confirmed_progress_survives_restart_without_acknowledging_peer_delivery(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    message = service.store.list("message")[0]
    head = service._message_journal.head()
    result = acknowledge(session, profile, cursor)
    assert result["ok"], result
    assert result["result"]["acknowledged"] is True
    assert service.store.get("message", message["id"]) == message
    assert service._message_journal.head() == head
    advance(service, "received_by_endpoint")
    service.close()
    reopened = host()
    again, _, _, _ = client(reopened)
    events = poll(again, profile, None)["result"]["events"]
    assert events[0]["state"] == "received_by_endpoint"
    assert acknowledge(again, profile, cursor) == result


def test_acknowledgment_and_idempotency_receipt_commit_together(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    database = service.store._db
    class FailCommit:
        def execute(self, statement, *args):
            if statement == "COMMIT": raise OSError("private commit failure")
            return database.execute(statement, *args)
        def __getattr__(self, name): return getattr(database, name)
    service.store._db = FailCommit()
    try:
        assert acknowledge(session, profile, cursor)["error"]["code"] == "unavailable"
    finally:
        service.store._db = database
    assert not service.store.list("api_consumer_progress")
    assert not service.store.list("api_event_ack")
    assert not service.store.list("api_event_ack_quota")
    assert poll(session, profile, None)["error"]["code"] == "resync_required"
    assert acknowledge(session, profile, cursor)["ok"]


def test_late_ack_cannot_rewind_progress_but_lost_reply_replay_remains_stable(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    first_cursor = snapshot(session, profile)["result"]["events_cursor"]
    first = acknowledge(session, profile, first_cursor)
    advance(service, "received_by_endpoint")
    next_cursor = poll(session, profile, first_cursor)["result"]["next_cursor"]
    assert acknowledge(session, profile, next_cursor, "acknowledge-00002")["ok"]
    assert acknowledge(session, profile, first_cursor, "acknowledge-00003")["error"]["code"] == "conflict"
    assert acknowledge(session, profile, first_cursor) == first
    assert poll(session, profile, None)["result"]["events"] == []
    assert acknowledge(session, profile, next_cursor)["error"]["code"] == "idempotency_conflict"


def test_reissued_cursor_for_same_position_is_the_same_logical_ack(host):
    service = host()
    session, _, profile, _ = client(service)
    first_cursor = snapshot(session, profile)["result"]["events_cursor"]
    other_cursor = snapshot(session, profile)["result"]["events_cursor"]
    assert first_cursor != other_cursor
    first = acknowledge(session, profile, first_cursor)
    assert first["ok"] and acknowledge(session, profile, other_cursor) == first
    assert len(service.store.list("api_event_ack")) == 1


def test_concurrent_sessions_resolve_one_acknowledgment(host):
    service = host()
    entries = [client(service) for _ in range(8)]
    cursor = snapshot(entries[0][0], entries[0][2])["result"]["events_cursor"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda entry: acknowledge(entry[0], entry[2], cursor), entries))
    assert all(result["ok"] for result in results), results
    assert all(result == results[0] for result in results)
    assert len(service.store.list("api_event_ack")) == 1


@pytest.mark.parametrize("change", ["permission", "profile", "caller", "contact", "locked", "detach"])
def test_cached_acknowledgment_rechecks_current_authority(host, change):
    service = host()
    session, grants, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    assert acknowledge(session, profile, cursor)["ok"]
    if change == "permission": grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    if change == "profile": grants[0] = replace(grants[0], profiles=())
    if change == "caller": grants[0] = None
    if change == "locked": service._identity = None
    if change == "detach": session.detach()
    if change == "contact":
        contact = service.store.get("contact", "internal-peer")
        service.store.put("contact", "internal-peer", {**contact, "trust": "blocked"})
    assert acknowledge(session, profile, cursor)["error"]["code"] in {
        "forbidden", "unauthenticated", "resync_required", "locked"}


def test_other_caller_cannot_acknowledge_or_resume_a_foreign_stream(host):
    service = host()
    alex, _, profile, _ = client(service)
    cursor = snapshot(alex, profile)["result"]["events_cursor"]
    first = acknowledge(alex, profile, cursor)
    blair, _, other_profile, _ = client(service, "blair")
    assert acknowledge(blair, other_profile, cursor)["error"]["code"] == "forbidden"
    assert poll(blair, other_profile, None)["error"]["code"] == "resync_required"
    own = snapshot(blair, other_profile)["result"]["events_cursor"]
    second = acknowledge(blair, other_profile, own)
    assert second["ok"] and second["result"]["checkpoint"] != first["result"]["checkpoint"]


def test_new_ack_rejects_lost_history_and_null_resume_reports_the_gap(host, monkeypatch):
    from mesh_chat import message_journal
    monkeypatch.setattr(message_journal, "MAX_EVENTS", 4)
    service = host()
    session, _, profile, peer = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    first = acknowledge(session, profile, cursor)
    for index in range(6): enqueue(session, profile, peer, key=f"enqueue-key-{index:04}")
    assert acknowledge(session, profile, cursor, "acknowledge-00002")["error"]["code"] == "resync_required"
    assert poll(session, profile, None)["error"]["code"] == "resync_required"
    assert acknowledge(session, profile, cursor) == first
    fresh = snapshot(session, profile)["result"]["events_cursor"]
    assert acknowledge(session, profile, fresh, "acknowledge-00002")["ok"]
    assert poll(session, profile, None)["result"]["events"] == []


def test_checkpoint_and_idempotency_retention_do_not_silently_reset_progress(host, monkeypatch):
    from mesh_chat.core_api import service_cursors
    service = host()
    session, _, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    now = service_cursors.time.time()
    monkeypatch.setattr(service_cursors.time, "time", lambda: now + 6 * 86400)
    first = acknowledge(session, profile, cursor)
    assert first["ok"]
    monkeypatch.setattr(service_cursors.time, "time", lambda: now + 8 * 86400)
    assert acknowledge(session, profile, cursor) == first  # Resolve the old write, without moving progress.
    assert acknowledge(session, profile, cursor, "acknowledge-00002")["error"]["code"] == "resync_required"
    assert poll(session, profile, None)["ok"]
    monkeypatch.setattr(service_cursors.time, "time", lambda: now + 14 * 86400)
    assert acknowledge(session, profile, cursor)["error"]["code"] == "idempotency_expired"
    assert poll(session, profile, None)["error"]["code"] == "resync_required"


@pytest.mark.parametrize("bound", ["MAX_CALLER_ACKNOWLEDGMENTS", "MAX_VAULT_ACKNOWLEDGMENTS"])
def test_ack_capacity_keeps_existing_keys_replayable(host, monkeypatch, bound):
    from mesh_chat.core_api import service_consumer_progress
    monkeypatch.setattr(service_consumer_progress, bound, 1)
    service = host()
    session, _, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    first = acknowledge(session, profile, cursor)
    assert first["ok"]
    assert acknowledge(session, profile, cursor, "acknowledge-00002")["error"]["code"] == "resource_exhausted"
    assert acknowledge(session, profile, cursor) == first


def test_acknowledgment_result_and_request_follow_the_public_contract(host):
    service = host()
    session, _, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    result = acknowledge(session, profile, cursor)
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    schema = json.loads((root / "recovery-result-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    value = request("events.ack", profile=profile, cursor=cursor)
    value["idempotency_key"] = "acknowledge-00001"
    Draft202012Validator(json.loads((root / "request-v1.schema.json").read_text())).validate(value)


@pytest.mark.parametrize("value", [None, "short", "x" * 1025])
def test_invalid_ack_cursor_fails_without_writes(host, value):
    service = host()
    session, _, profile, _ = client(service)
    assert acknowledge(session, profile, value)["error"]["code"] == "invalid_request"
    assert not service.store.list("api_consumer_progress")


def test_poll_does_not_advance_or_renew_confirmed_progress(host):
    service = host()
    session, _, profile, peer = client(service)
    enqueue(session, profile, peer)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    assert acknowledge(session, profile, cursor)["ok"]
    before = service.store.list("api_consumer_progress")
    advance(service, "received_by_endpoint")
    first = poll(session, profile, None)["result"]
    assert first["events"]
    assert poll(session, profile, first["next_cursor"])["result"]["events"] == []
    assert poll(session, profile, None)["result"]["events"] == first["events"]
    assert service.store.list("api_consumer_progress") == before


def test_partial_snapshot_cursor_cannot_acknowledge_missing_pages(host):
    service = host()
    session, _, profile, peer = client(service)
    for index in range(2): enqueue(session, profile, peer, key=f"enqueue-key-{index:04}")
    page = snapshot(session, profile, limit=1)["result"]
    assert page["next_cursor"] and page["events_cursor"] is None
    assert acknowledge(session, profile, page["next_cursor"])["error"]["code"] == "invalid_request"
    assert not service.store.list("api_consumer_progress")


def test_acknowledgment_requires_negotiation_before_writing(host):
    from mesh_chat.core_api.composition import bind_service_session
    service = host()
    session, grants, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    fresh = bind_service_session(service, lambda: grants[0])
    assert acknowledge(fresh, profile, cursor)["error"]["code"] == "negotiation_required"
    assert not service.store.list("api_consumer_progress")


@pytest.mark.parametrize("key", [None, "short", "k" * 129, "k" * 15 + "\n", [], {}])
def test_acknowledgment_requires_a_bounded_idempotency_key(host, key):
    service = host()
    session, _, profile, _ = client(service)
    cursor = snapshot(session, profile)["result"]["events_cursor"]
    assert acknowledge(session, profile, cursor, key)["error"]["code"] == "invalid_request"
    assert not service.store.list("api_consumer_progress")
