"""Offline checks for bounded, exact-workspace admission failure evidence."""

import importlib.util
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest


SERVICE_TESTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SERVICE_TESTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load("test_direct_setup_pipeline")
recovery = load("test_direct_recovery_pipeline")


def private_rows():
    workspace = {"id": "PRIVATE_WORKSPACE", "state": "active",
        "channel_discovery": "incomplete", "general_channel_id": "PRIVATE_GENERAL",
        "epoch": 2}
    delivery = {"id": "PRIVATE_DELIVERY", "workspace_id": "PRIVATE_WORKSPACE",
        "kind": "workspace_channel_record", "state": "waiting_for_keys",
        "attempt_count": 3, "next_attempt_at": 99, "native_message_id": "PRIVATE_NATIVE",
        "document": json.dumps({"workspace_id": "PRIVATE_WORKSPACE",
            "channel_id": "PRIVATE_GENERAL", "name": "general"}),
        "recipient_destination": "a" * 32}
    pending = {"id": "PRIVATE_PENDING", "workspace_id": "PRIVATE_WORKSPACE",
        "kind": "workspace_channel_record", "reason": "missing_manifest",
        "document": delivery["document"]}
    return workspace, delivery, pending


def test_exact_record_collector_reports_only_fixed_admission_labels():
    workspace, delivery, pending = private_rows()
    rows = {("workspace", "PRIVATE_WORKSPACE_RECORD"): workspace,
        ("workspace_delivery", "PRIVATE_DELIVERY"): delivery,
        ("workspace_pending_control", "PRIVATE_PENDING"): pending,
        ("workspace_channel", "PRIVATE_CHANNEL_RECORD"): {"id": "PRIVATE_GENERAL",
            "workspace_id": "PRIVATE_WORKSPACE", "name": "general"}}
    class Store:
        def __init__(self):
            self.calls = []
        def get(self, kind, key):
            self.calls.append((kind, key))
            return rows.get((kind, key))
        def items(self, *_args, **_kwargs):
            pytest.fail("Admission diagnostic scanned unrelated records")
    store = Store()
    value = setup._admission_channel_diagnostic(store, "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", "PRIVATE_CHANNEL_RECORD",
        ["PRIVATE_DELIVERY"], ["PRIVATE_PENDING"], now=100)
    assert value["available"] is True
    assert value["workspace_state"] == "active"
    assert value["channel_discovery"] == "incomplete"
    assert value["general_reference"] == "present"
    assert value["general_channel_record"] == "present"
    assert value["channel_control"] == {"selection": "selected", "state": "waiting_for_keys",
        "attempts": 3, "attempts_capped": False, "schedule": "due",
        "native_message_id_present": True, "failure": "none"}
    assert value["pending_control"] == {"selection": "present", "reason": "missing_manifest"}
    assert set(store.calls) == set(rows)
    assert "PRIVATE" not in json.dumps(value)


def test_foreign_or_malformed_exact_records_fail_closed_without_raw_values():
    workspace, delivery, pending = private_rows()
    delivery["workspace_id"] = "PRIVATE_FOREIGN"
    pending["reason"] = "PRIVATE_ERROR"
    class Store:
        def get(self, kind, key):
            return {"workspace": workspace, "workspace_delivery": delivery,
                "workspace_pending_control": pending}.get(kind)
        def items(self, *_args, **_kwargs):
            pytest.fail("Admission diagnostic scanned unrelated records")
    value = setup._admission_channel_diagnostic(Store(), "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", "PRIVATE_CHANNEL_RECORD",
        ["PRIVATE_DELIVERY"], ["PRIVATE_PENDING"], now=100)
    assert value["channel_control"]["selection"] == "unavailable"
    assert value["pending_control"]["reason"] == "unknown"
    assert "PRIVATE" not in json.dumps(value)


def test_receiver_can_report_missing_exact_channel_without_claiming_a_global_scan():
    workspace = {"id": "PRIVATE_WORKSPACE", "state": "active",
        "channel_discovery": "incomplete", "general_channel_id": None}
    class Store:
        def __init__(self):
            self.calls = []
        def get(self, kind, key):
            self.calls.append((kind, key))
            return workspace if kind == "workspace" else None
        def items(self, *_args, **_kwargs):
            pytest.fail("Admission diagnostic scanned unrelated records")
    store = Store()
    value = setup._admission_channel_diagnostic(store, "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", "PRIVATE_CHANNEL_RECORD", [], [], now=100,
        expected_channel_id="PRIVATE_GENERAL")
    assert value == {"available": True, "workspace_state": "active",
        "channel_discovery": "incomplete", "general_reference": "absent",
        "general_channel_record": "absent",
        "channel_control": {"selection": "not_observed"},
        "pending_control": {"selection": "not_observed"}}
    assert store.calls == [("workspace", "PRIVATE_WORKSPACE_RECORD"),
                           ("workspace_channel", "PRIVATE_CHANNEL_RECORD")]


def test_pending_id_matches_production_key_and_worker_uses_global_hashlib():
    document = json.dumps({"workspace_id": "PRIVATE_WORKSPACE", "name": "general"})
    wire = SimpleNamespace(workspace_id="PRIVATE_WORKSPACE", kind="workspace_channel_record",
        document=document)
    calls = []
    store = SimpleNamespace(opaque_id=lambda *args: calls.append(args) or "PRIVATE_PENDING")
    assert setup._admission_pending_id(store, wire) == "PRIVATE_PENDING"
    assert calls == [("workspace-pending-control", "PRIVATE_WORKSPACE",
                      "workspace_channel_record", hashlib.sha256(document.encode()).hexdigest())]
    assert "hashlib" not in setup._service_worker.__code__.co_cellvars


def test_worker_pending_hook_tracks_exact_id_before_any_recovery_diagnostic():
    nested = next(code for code in setup._service_worker.__code__.co_consts
                  if getattr(code, "co_name", None) == "traced_pending_control")
    retained = []
    channels = []
    values = {"admission_pending": {}, "admission_tracking_failed": False,
        "original_pending_control": lambda _wire, _reason: "stored",
        "retain_admission_channel": lambda workspace, document: channels.append((workspace, document)),
        "retain_admission_id": lambda table, workspace, identifier:
            retained.append((table, workspace, identifier)),
        "store": SimpleNamespace(opaque_id=lambda *_args: "PRIVATE_PENDING")}
    cell = lambda value: (lambda: value).__closure__[0]
    closure = tuple(cell(values[name]) for name in nested.co_freevars)
    hook = FunctionType(nested, setup.__dict__, closure=closure)
    document = json.dumps({"workspace_id": "PRIVATE_WORKSPACE", "name": "general",
        "channel_id": "PRIVATE_GENERAL"})
    wire = SimpleNamespace(workspace_id="PRIVATE_WORKSPACE", kind="workspace_channel_record",
        document=document)
    assert hook(wire, "missing_manifest") == "stored"
    assert retained == [(values["admission_pending"], "PRIVATE_WORKSPACE", "PRIVATE_PENDING")]
    assert channels == [("PRIVATE_WORKSPACE", document)]
    assert closure[nested.co_freevars.index("admission_tracking_failed")].cell_contents is False


def test_oversize_or_foreign_channel_document_cannot_be_selected():
    assert not setup._admission_control_document({"document": " " * 16385}, "PRIVATE_WORKSPACE")
    assert not setup._admission_control_document({"document": json.dumps({
        "workspace_id": "PRIVATE_FOREIGN", "name": "general"})}, "PRIVATE_WORKSPACE")


def test_observed_channel_record_must_match_exact_general_channel_id():
    workspace = {"id": "PRIVATE_WORKSPACE", "state": "active", "general_channel_id": None}
    class Store:
        def get(self, kind, _key):
            if kind == "workspace":
                return workspace
            return {"id": "PRIVATE_UNRELATED", "workspace_id": "PRIVATE_WORKSPACE",
                    "name": "general"}
    value = setup._admission_channel_diagnostic(Store(), "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", "PRIVATE_CHANNEL_RECORD", [], [], now=100,
        expected_channel_id="PRIVATE_GENERAL")
    assert value["general_channel_record"] == "unavailable"
    assert "PRIVATE" not in json.dumps(value)


def test_failure_projection_drops_private_fields_and_caps_numeric_evidence():
    value = {"available": True, "workspace_state": "PRIVATE_STATE",
        "channel_discovery": "incomplete", "general_reference": "absent",
        "general_channel_record": "absent", "private": "PRIVATE_SECRET",
        "channel_control": {"selection": "selected", "state": "queued", "attempts": 999,
            "attempts_capped": True, "schedule": "future",
            "native_message_id_present": False, "failure": "PRIVATE_FAILURE",
            "document": "PRIVATE_DOCUMENT"},
        "pending_control": {"selection": "present", "reason": "PRIVATE_REASON"}}
    projected = recovery._admission_failure_snapshot(value)
    assert projected["workspace_state"] == "unknown"
    assert projected["channel_control"]["attempts"] == 32
    assert projected["channel_control"]["failure"] == "unknown"
    assert projected["pending_control"]["reason"] == "unknown"
    assert "PRIVATE" not in json.dumps(projected)


@pytest.mark.parametrize("has_reference", [False, True])
@pytest.mark.parametrize("table", ["workspace_delivery", "workspace_pending_control"])
@pytest.mark.parametrize("document_channel", [None, "PRIVATE_UNRELATED"])
def test_control_requires_exact_general_channel_anchor(has_reference, table, document_channel):
    workspace, delivery, pending = private_rows()
    workspace["general_channel_id"] = "PRIVATE_GENERAL" if has_reference else None
    row = delivery if table == "workspace_delivery" else pending
    document = {"workspace_id": "PRIVATE_WORKSPACE", "name": "general"}
    if document_channel is not None:
        document["channel_id"] = document_channel
    row["document"] = json.dumps(document)
    store = SimpleNamespace(get=lambda kind, key: workspace if kind == "workspace" else row)
    value = setup._admission_channel_diagnostic(store, "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", None,
        ["PRIVATE_DELIVERY"] if table == "workspace_delivery" else [],
        ["PRIVATE_PENDING"] if table == "workspace_pending_control" else [], now=100,
        expected_channel_id="PRIVATE_GENERAL")
    field = "channel_control" if table == "workspace_delivery" else "pending_control"
    assert value[field] == {"selection": "unavailable"}
    assert "native_failure" not in value
    assert "PRIVATE" not in json.dumps(value)


@pytest.mark.parametrize("has_reference", [False, True])
def test_missing_or_conflicting_channel_anchor_cannot_select_control(has_reference):
    workspace, delivery, pending = private_rows()
    workspace["general_channel_id"] = "PRIVATE_GENERAL" if has_reference else None
    rows = {"workspace": workspace, "workspace_delivery": delivery,
            "workspace_pending_control": pending}
    store = SimpleNamespace(get=lambda kind, key: rows.get(kind))
    value = setup._admission_channel_diagnostic(store, "PRIVATE_WORKSPACE",
        "PRIVATE_WORKSPACE_RECORD", None, ["PRIVATE_DELIVERY"], ["PRIVATE_PENDING"], now=100,
        expected_channel_id="PRIVATE_CONFLICT" if has_reference else None)
    if value.get("available") is True:
        assert value["channel_control"] == {"selection": "unavailable"}
        assert value["pending_control"] == {"selection": "unavailable"}
    assert "native_failure" not in value
    assert "PRIVATE" not in json.dumps(value)


def test_channel_native_probe_selects_exact_control_and_reports_contention():
    class Busy:
        def acquire(self, _blocking):
            return False
    network = SimpleNamespace(_message_lock=Busy(), _callback_condition=Busy())
    row = {"workspace_id": "PRIVATE_WORKSPACE", "id": "PRIVATE_DELIVERY",
        "recipient_destination": "ab" * 16, "kind": "workspace_channel_record"}
    result = setup._native_failure_diagnostic([row], network, "PRIVATE_WORKSPACE",
        kind="workspace_channel_record")
    assert result == {"selection": "selected", "attempts": "contended",
                      "callbacks": "contended"}
    assert "PRIVATE" not in json.dumps(result)


def test_workspace_timeout_uses_two_bounded_exact_admission_probes_and_original_deadline(monkeypatch):
    peers = object.__new__(recovery.Peers)
    peers.workspace = {"id": "PRIVATE_WORKSPACE"}
    peers.command = lambda *_args, **_kwargs: {"workspace_channels": [],
        "workspaces": [{"channel_discovery": "incomplete"}]}
    calls = []
    def call(index, operation, *, _diagnostic_timeout=None, **payload):
        calls.append((index, operation, _diagnostic_timeout, payload))
        return {"available": False, "private": "PRIVATE_TEXT"}
    peers.call = call
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(recovery, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda seconds: setattr(clock, "now", clock.now + seconds)))
    with pytest.raises(AssertionError) as caught:
        peers.wait(1, "workspace_snapshot", lambda _: False)
    failure = caught.value.args[0]
    assert failure[:2] == (1, "workspace_snapshot")
    assert failure[2]["workspace_channels"] == []
    assert 45 <= clock.now < 45.21
    assert calls == [(0, "admission_diagnostic", 1, {"workspace_id": "PRIVATE_WORKSPACE"}),
                     (1, "admission_diagnostic", 1, {"workspace_id": "PRIVATE_WORKSPACE"})]
    assert failure[3]["peers"] == [{"available": False}, {"available": False}]
    assert "PRIVATE_TEXT" not in str(failure)
