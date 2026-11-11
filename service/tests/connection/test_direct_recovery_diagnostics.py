"""Test-only, bounded address-loss failure evidence; no native acceptance claim."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SERVICE_TESTS = Path(__file__).resolve().parents[1]


def load(name):
    path = SERVICE_TESTS / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load("test_direct_setup_pipeline")
recovery = load("test_direct_recovery_pipeline")


def test_workspace_event_delivery_has_its_own_bounded_outbox_state_without_values():
    source = {table: [] for table in setup._WORKSPACE_DIAGNOSTIC_TABLES}
    source["workspace_delivery"] = [{"workspace_id": "PRIVATE_WORKSPACE", "id": "PRIVATE_DELIVERY",
        "kind": "workspace_event", "state": "waiting_for_keys", "attempt_count": 3,
        "next_attempt_at": 100, "native_message_id": "PRIVATE_NATIVE_ID",
        "document": "PRIVATE_DOCUMENT", "failure_code": "PRIVATE_EXCEPTION"}]
    selected = setup._project_workspace_bootstrap_diagnostic(source, now=101)
    assert selected["delivery_counts"]["kind"]["workspace_event"] == 1
    assert selected["workspace_event_states"]["waiting_for_keys"] == 1
    assert selected["deliveries"][0] == {"kind": "workspace_event", "state": "waiting_for_keys",
        "attempts": 3, "attempts_capped": False, "schedule": "due", "native_message_id_present": True,
        "failure": "unknown"}
    assert "PRIVATE" not in json.dumps(selected)


def test_both_peer_projection_keeps_only_fixed_readiness_and_event_branches():
    raw = {"identity": "PRIVATE_IDENTITY", "pending": 10**9,
        "peers": [{"state": "connected", "authenticated_peer_live": True, "rns_ready": True,
                   "relationship_id": "PRIVATE_RELATIONSHIP", "workspace_id": "PRIVATE_WORKSPACE"},
                  {"state": "PRIVATE_STATE", "rns_ready": "PRIVATE_NOT_BOOL"},
                  {"state": "connected", "rns_ready": False}],
        "workspace_bootstrap": {"workspaces": [{"channel_discovery": "incomplete",
            "id": "PRIVATE_WORKSPACE"}], "workspace_event_states": {"waiting_for_keys": 10**9,
            "sending": 1, "private_state": 999}, "deliveries": [{"text": "PRIVATE_TEXT"},
                {"kind": "workspace_event", "state": "queued", "attempts": 2,
                 "attempts_capped": False, "schedule": "future",
                 "native_message_id_present": False, "failure": "none",
                 "id": "PRIVATE_DELIVERY", "payload": "PRIVATE_TEXT"}]},
        "workspace_event_trace": [
            {"stage": "preflight", "outcome": "waiting", "bootstrap_ready": True,
             "bootstrap_handles": False, "main_identity": True, "main_ratchet": False,
             "main_path": False, "destination": "PRIVATE_ADDRESS", "key": "PRIVATE_KEY"},
            {"stage": "send", "outcome": "recipient_keys_unavailable", "main_ratchet": False,
             "error": "PRIVATE_EXCEPTION"},
            {"stage": "status", "outcome": "handled", "state": "received_by_endpoint",
             "native_id": "PRIVATE_NATIVE_ID"},
            {"stage": "ingress", "outcome": "observed", "payload": "PRIVATE_DOCUMENT"},
            {"stage": "acceptance", "outcome": "deferred_or_rejected", "wire": "PRIVATE_WIRE"}]}
    selected = recovery._recovery_failure_snapshot(raw)
    assert selected["available"] and selected["pending"] == 32 and selected["pending_capped"]
    assert selected["peer_states_truncated"]
    assert selected["peer_states"] == [
        {"state": "connected", "authenticated_peer_live": True, "rns_ready": True},
        {"state": "unknown", "authenticated_peer_live": None, "rns_ready": None}]
    assert selected["channel_discovery"] == "incomplete"
    assert selected["workspace_event_scan"] == "unknown"
    assert selected["workspace_event_states"]["waiting_for_keys"] == 64
    assert selected["workspace_event_deliveries"] == {"entries": [{"state": "queued", "attempts": 2,
        "attempts_capped": False, "schedule": "future", "native_message_id_present": False,
        "failure": "none"}], "truncated": False, "malformed": True}
    assert [row["stage"] for row in selected["workspace_event_trace"]["entries"]] == [
        "preflight", "send", "status", "ingress", "acceptance"]
    assert selected["workspace_event_trace"]["entries"][0]["main_ratchet"] is False
    assert selected["workspace_event_trace"]["entries"][2]["state"] == "received_by_endpoint"
    assert "PRIVATE" not in json.dumps(selected)


def test_event_delivery_snapshot_distinguishes_retry_schedule_and_endpoint_receipt():
    rows = [{"kind": "workspace_channel_record", "state": "queued", "attempts": 7,
             "schedule": "future", "id": "PRIVATE_CONTROL"}]
    rows += [{"kind": "workspace_event", "state": state, "attempts": attempts,
              "attempts_capped": capped, "schedule": schedule,
              "native_message_id_present": native, "failure": failure,
              "id": "PRIVATE_ID", "document": "PRIVATE_PAYLOAD"}
             for state, attempts, capped, schedule, native, failure in (
                 ("queued", 0, False, "due", False, "none"),
                 ("waiting_for_keys", 3, False, "future", False, "transport_unavailable"),
                 ("received_by_endpoint", 32, True, "terminal", True, "transport_error"))]
    selected = recovery._event_delivery_snapshot(rows)
    assert selected == {"entries": [
        {"state": "queued", "attempts": 0, "attempts_capped": False,
         "schedule": "due", "native_message_id_present": False, "failure": "none"},
        {"state": "waiting_for_keys", "attempts": 3, "attempts_capped": False,
         "schedule": "future", "native_message_id_present": False,
         "failure": "transport_unavailable"},
        {"state": "received_by_endpoint", "attempts": 32, "attempts_capped": True,
         "schedule": "terminal", "native_message_id_present": True,
         "failure": "transport_error"}], "truncated": False, "malformed": False}
    assert "PRIVATE" not in json.dumps(selected)


def test_event_delivery_snapshot_sanitizes_malformed_values_and_bounds_rows():
    selected = recovery._event_delivery_snapshot([None, {"kind": "workspace_event",
        "state": "PRIVATE_STATE", "attempts": 10**100, "attempts_capped": "PRIVATE_BOOL",
        "schedule": "PRIVATE_SCHEDULE", "native_message_id_present": "PRIVATE_ID",
        "failure": "PRIVATE_EXCEPTION", "document": "PRIVATE_PAYLOAD"}])
    assert selected == {"entries": [{"state": "unknown", "attempts": 32,
        "attempts_capped": None, "schedule": "unknown", "native_message_id_present": None,
        "failure": "unknown"}], "truncated": False, "malformed": True}
    assert "PRIVATE" not in json.dumps(selected)
    assert recovery._event_delivery_snapshot("PRIVATE_ROWS") == {
        "entries": [], "truncated": False, "malformed": True}
    row = {"kind": "workspace_event", "state": "queued", "attempts": 1,
        "attempts_capped": False, "schedule": "due", "native_message_id_present": False,
        "failure": "none", "id": "PRIVATE_ID"}
    many = recovery._event_delivery_snapshot([row] * 65)
    assert len(many["entries"]) == 8 and many["truncated"] and not many["malformed"]
    assert "PRIVATE" not in json.dumps(many)


@pytest.mark.parametrize("table,expected", [
    ({"unavailable": False, "truncated": False, "malformed_rows": 0}, "complete"),
    ({"unavailable": False, "truncated": True, "malformed_rows": 0}, "partial"),
    ({"unavailable": False, "truncated": False, "malformed_rows": 1}, "partial"),
    ({"unavailable": True, "truncated": False, "malformed_rows": 0}, "unavailable"),
])
def test_workspace_event_absence_requires_complete_bounded_delivery_scan(table, expected):
    value = {"workspace_bootstrap": {"workspace_event_states": {"queued": 0},
        "tables": {"workspace_delivery": table}}}
    selected = recovery._recovery_failure_snapshot(value)
    assert selected["workspace_event_states"]["queued"] == 0
    assert selected["workspace_event_scan"] == expected


def test_malformed_trace_is_unknown_and_bounded_without_raw_error_or_identifiers():
    trace = [{"stage": "send", "outcome": "accepted", "secret": "PRIVATE_KEY"}] * 17
    trace += [{"stage": "PRIVATE_STAGE", "outcome": "PRIVATE_EXCEPTION"}]
    selected = recovery._event_trace_snapshot(trace)
    assert len(selected["entries"]) == 15 and selected["malformed"]
    assert "PRIVATE" not in json.dumps(selected)
    assert recovery._event_trace_snapshot(None) == {"entries": [], "malformed": True}


@pytest.mark.parametrize("case,outcome", [("success", "accepted"), ("keys", "recipient_keys_unavailable"),
    ("foreign_mesh", "other_mesh_error"), ("unexpected", "other_error")])
def test_traced_workspace_send_calls_original_once_and_preserves_result_or_exception(case, outcome):
    class MeshError(Exception):
        def __init__(self, code):
            self.code = code
            super().__init__("PRIVATE_ERROR_AND_CREDENTIAL")
    values = {"fields": {1: "PRIVATE_PAYLOAD"}, "recipient_destination": b"PRIVATE_ADDRESS"}
    result = object()
    errors = {"keys": MeshError("recipient_keys_unavailable"),
        "foreign_mesh": MeshError("PRIVATE_CODE"), "unexpected": RuntimeError("PRIVATE_EXCEPTION")}
    calls, entry = [], {"stage": "send", "outcome": "unknown"}
    def original(**kwargs):
        calls.append(kwargs)
        if case in errors: raise errors[case]
        return result
    if case == "success":
        assert setup._call_traced_workspace_send(original, values, entry, MeshError) is result
    else:
        with pytest.raises(type(errors[case])) as caught:
            setup._call_traced_workspace_send(original, values, entry, MeshError)
        assert caught.value is errors[case]
    assert calls == [values] and entry == {"stage": "send", "outcome": outcome}
    assert "PRIVATE" not in json.dumps(entry)


def test_original_delivery_timeout_survives_failed_sender_diagnostic_and_collects_receiver(monkeypatch):
    peers = object.__new__(recovery.Peers)
    calls = []
    original_page = {"messages": [], "high_water": 0}
    def command(index, name, **payload):
        calls.append(("command", index, name, payload))
        return original_page
    def diagnostic(index, operation, *, _diagnostic_timeout=None, **payload):
        calls.append(("diagnostic", index, operation, _diagnostic_timeout))
        if index == 0: raise TimeoutError("PRIVATE_DIAGNOSTIC_ENDPOINT")
        return {"pending": 1, "peers": [{"state": "connected", "rns_ready": True}],
            "workspace_bootstrap": {"workspace_event_states": {"queued": 1}},
            "workspace_event_trace": [{"stage": "preflight", "outcome": "waiting",
                "main_ratchet": False, "recipient": "PRIVATE_ADDRESS"}]}
    peers.command, peers.call = command, diagnostic
    ticks = iter((0, 0, 45))
    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=lambda: next(ticks),
        sleep=lambda seconds: calls.append(("sleep", seconds))))
    with pytest.raises(AssertionError) as caught:
        peers.wait(1, "list_workspace_messages", lambda _: False, timeout=45, limit=50)
    index, name, last, diagnostic_result = caught.value.args[0]
    assert (index, name, last) == (1, "list_workspace_messages", original_page)
    assert calls == [("command", 1, "list_workspace_messages", {"limit": 50}), ("sleep", .2),
        ("diagnostic", 0, "recovery_diagnostic", 1),
        ("diagnostic", 1, "recovery_diagnostic", 1)]
    assert diagnostic_result["peers"][0] == {"available": False}
    assert diagnostic_result["peers"][1]["workspace_event_states"]["queued"] == 1
    assert "PRIVATE" not in repr(diagnostic_result)
