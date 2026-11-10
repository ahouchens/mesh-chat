"""Offline privacy/read-only controls for test-only failure diagnostics."""
import ast
from copy import deepcopy
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "test_direct_setup_pipeline.py"
SPEC = importlib.util.spec_from_file_location("direct_setup_workspace_diagnostic_fixture", SOURCE)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def records():
    return {table: [] for table in setup._WORKSPACE_DIAGNOSTIC_TABLES}


def snapshot():
    result = records()
    result.update({
        "workspace": [{"id": "private-workspace", "state": "active", "channel_discovery": "incomplete",
                       "general_channel_id": "private-general", "manifest_hash": "private-current"}],
        "workspace_channel": [{"id": "private-general", "workspace_id": "private-workspace", "name": "general"}],
        "workspace_channel_control": [{"workspace_id": "private-workspace", "channel_id": "private-general", "digest": "private-head"}],
        "workspace_manifest": [{"workspace_id": "private-workspace", "digest": "private-first", "epoch": 1},
                               {"workspace_id": "private-workspace", "digest": "private-current", "epoch": 2}],
        "workspace_delivery": [{"id": "private-delivery", "workspace_id": "private-workspace",
                                "kind": "workspace_channel_record", "state": "waiting_for_keys",
                                "attempt_count": 2, "next_attempt_at": 1234567.5,
                                "native_message_id": "private-native"}],
        "workspace_pending_control": [{"workspace_id": "private-workspace", "kind": "workspace_channel_record",
                                       "reason": "missing_manifest"}],
    })
    return result


def test_projection_preserves_relevant_state_without_sensitive_fields_or_input_mutation():
    source = snapshot()
    for rows in source.values():
        for row in rows:
            row.update(document="private-document", serialized="private-serialized", text="private-text",
                       key="private-key", certificate="private-cert", error="private-error")
    before = deepcopy(source)
    result = setup._project_workspace_bootstrap_diagnostic(source, now=1234568.0)
    assert source == before
    assert result["workspaces"] == [{"state": "active", "channel_discovery": "incomplete",
        "general_reference_present": True, "general_channel": "present", "general_control": "present",
        "epoch1_manifest": "present", "current_manifest": "present"}]
    delivery = result["deliveries"][0]
    assert delivery == {"kind": "workspace_channel_record", "state": "waiting_for_keys", "attempts": 2,
                        "attempts_capped": False, "schedule": "due", "native_message_id_present": True, "failure": "none"}
    assert result["pending_controls"]["reason"]["missing_manifest"] == 1
    encoded = json.dumps(result)
    assert "private-" not in encoded and "1234567" not in encoded and "1234568" not in encoded


@pytest.mark.parametrize("state,schedule", [("queued", "future"), ("sending", "future"),
    ("received_by_endpoint", "terminal"), ("failed", "terminal"), ("cancelled", "terminal")])
def test_deliveries_distinguish_future_work_from_terminal_transport_results(state, schedule):
    source = snapshot()
    source["workspace_delivery"][0]["state"] = state
    result = setup._project_workspace_bootstrap_diagnostic(source, now=1)
    assert result["deliveries"][0]["schedule"] == schedule
    assert result["delivery_counts"]["state"][state] == 1


def test_unknown_values_never_become_dynamic_output_keys_or_error_text():
    source = snapshot()
    source["workspace"][0].update(state="private-state", channel_discovery={"private": "value"})
    source["workspace_delivery"][0].update(kind="private-kind", state="private-state", attempt_count=True,
                                         next_attempt_at=float("nan"), failure_code="private-exception")
    source["workspace_pending_control"][0].update(kind="private-kind", reason="private-reason")
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    assert result["workspaces"][0]["state"] == result["workspaces"][0]["channel_discovery"] == "unknown"
    assert result["delivery_counts"]["kind"]["unknown"] == result["delivery_counts"]["state"]["unknown"] == 1
    assert result["deliveries"][0]["attempts"] is None
    assert result["deliveries"][0]["failure"] == result["deliveries"][0]["schedule"] == "unknown"
    assert result["pending_controls"]["kind"]["unknown"] == result["pending_controls"]["reason"]["unknown"] == 1
    assert "private-" not in json.dumps(result)


@pytest.mark.parametrize("due", [True, "private-time", {}, -1, float("inf"), float("nan"), 10**400])
def test_malformed_due_values_are_unknown_without_throwing_or_exporting(due):
    source = snapshot()
    source["workspace_delivery"][0]["next_attempt_at"] = due
    assert setup._project_workspace_bootstrap_diagnostic(source, now=100)["deliveries"][0]["schedule"] == "unknown"


@pytest.mark.parametrize("attempts,expected,capped", [(-1, None, False), ("private-count", None, False),
    (32, 32, False), (33, 32, True), (10**400, 32, True)])
def test_attempts_are_strictly_numeric_and_capped(attempts, expected, capped):
    source = snapshot()
    source["workspace_delivery"][0]["attempt_count"] = attempts
    row = setup._project_workspace_bootstrap_diagnostic(source, now=100)["deliveries"][0]
    assert (row["attempts"], row["attempts_capped"]) == (expected, capped)


def test_bounded_iterators_and_counts_mark_truncation():
    source = snapshot()
    seen = []
    delivery = source["workspace_delivery"][0]
    def infinite():
        for index in itertools.count():
            seen.append(index)
            yield delivery
    source["workspace_delivery"] = infinite()
    source["workspace"] *= 9
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    assert len(seen) == 65 and len(result["deliveries"]) == 64
    assert result["delivery_counts"]["kind"]["workspace_channel_record"] == 64
    assert result["tables"]["workspace_delivery"]["truncated"]
    assert len(result["workspaces"]) == 8 and result["tables"]["workspace"]["truncated"]


@pytest.mark.parametrize("invalid", [None, "private-text", {}, [None, {"id": "private-malformed"}]])
def test_malformed_tables_cannot_claim_known_absence(invalid):
    source = snapshot()
    source["workspace_channel"] = invalid
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    assert result["workspaces"][0]["general_channel"] == "unknown"
    assert "private-" not in json.dumps(result)


def test_incomplete_scan_cannot_claim_absence_beyond_limit():
    source = snapshot()
    source["workspace_channel"] = [{"id": "private-other", "workspace_id": "private-other"}] * 64 + source["workspace_channel"]
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    assert result["workspaces"][0]["general_channel"] == "unknown"
    assert result["tables"]["workspace_channel"]["truncated"]


def test_general_and_manifest_presence_are_scoped_not_cross_workspace():
    source = snapshot()
    for table in ("workspace_channel", "workspace_channel_control", "workspace_manifest"):
        for row in source[table]:
            row["workspace_id"] = "private-other"
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    workspace = result["workspaces"][0]
    assert workspace["general_channel"] == workspace["general_control"] == "absent"
    assert workspace["epoch1_manifest"] == workspace["current_manifest"] == "absent"


def test_read_only_collector_uses_only_bounded_fixed_table_reads():
    source = snapshot()
    class Store:
        def __init__(self):
            self.calls = []
        def items(self, kind, *, limit):
            self.calls.append((kind, limit))
            return [("private-record-id", row) for row in source[kind]][:limit]
        def __getattr__(self, name):
            raise AssertionError("No mutation/domain/reconciliation call allowed")
    store = Store()
    result = setup._workspace_bootstrap_diagnostic(store, now=100)
    assert store.calls == [(table, 9 if table == "workspace" else 65) for table in setup._WORKSPACE_DIAGNOSTIC_TABLES]
    assert result == setup._project_workspace_bootstrap_diagnostic(source, now=100)


def test_read_error_is_unknown_not_empty_or_raw_exception():
    class Store:
        def items(self, *_args, **_kwargs):
            raise OSError("private-error-path-and-key")
    result = setup._workspace_bootstrap_diagnostic(Store(), now=100)
    assert all(table["unavailable"] for table in result["tables"].values())
    assert "private-" not in json.dumps(result)


def test_broken_iterator_and_malformed_manifest_do_not_claim_absence():
    source = snapshot()
    def broken():
        raise ValueError("private-iterator-error")
        yield
    source["workspace_channel"] = broken()
    source["workspace_manifest"][0]["epoch"] = True
    result = setup._project_workspace_bootstrap_diagnostic(source, now=100)
    assert result["workspaces"][0]["general_channel"] == "unknown"
    assert result["workspaces"][0]["epoch1_manifest"] == "unknown"
    assert result["tables"]["workspace_manifest"]["malformed_rows"] == 1
    assert "private-" not in json.dumps(result)


def test_existing_failure_snapshot_is_only_integration_site():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_service_worker")
    calls = [node for node in ast.walk(worker) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "_workspace_bootstrap_diagnostic"]
    assert len(calls) == 1
    branch = next(node for node in ast.walk(worker) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Compare) and any(isinstance(value, ast.Constant)
                  and value.value == "recovery_diagnostic" for value in node.test.comparators))
    assert calls[0] in list(ast.walk(ast.Module(body=branch.body, type_ignores=[])))
