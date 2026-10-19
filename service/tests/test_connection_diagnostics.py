import json
import os
import time
from types import SimpleNamespace

import pytest

from mesh_chat import connection_diagnostics as diagnostics


class Store:
    def __init__(self):
        self.rows = {}
    def get(self, kind, key):
        return self.rows.get((kind, key))
    def put(self, kind, key, value):
        self.rows[kind, key] = value
    def delete(self, kind, key):
        self.rows.pop((kind, key), None)


def test_allowlist_excludes_seeded_secrets_and_unexpected_structures():
    service = SimpleNamespace(store=Store())
    secret = "MESHWORKSPACE-secret-key-192.0.2.1-person-name"
    diagnostics.record(service, "state", {"setup_id":secret, "state":"existing_routes_only", "kind":"ready",
        "candidate_count":2, "expires_at":int(time.time())+60, "text":secret, "private_key":secret})
    value = diagnostics.report(service)
    assert secret not in json.dumps(value)
    assert value["last_failure"]["phase"] == "existing_routes_only"
    assert len(value["last_failure"]["attempt"]) == 12
    assert diagnostics.sanitize({"event":[], "phase":{}, "kind":secret})["phase"] == "unavailable"


def test_history_bounded_and_latest_failure_survives_new_service_instance():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed"})
    for index in range(220):
        diagnostics.record(service, "state", {"state":"connecting", "setup_id":str(index)})
    reopened = SimpleNamespace(store=service.store)
    value = diagnostics.report(reopened)
    assert 0 < len(value["events"]) <= 200
    assert len(service.store.get("connection_diagnostics", "history")["events"]) == 200
    assert value["truncated"] is True
    assert value["last_failure"]["phase"] == "failed"
    assert len(json.dumps(value).encode()) < 65536


@pytest.mark.parametrize("phase", ["no_route", "network_changed", "test_failed", "both_no_address"])
def test_readiness_failure_survives_later_success_and_history_rollover(phase):
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "state", {"state": phase, "setup_id": "failed-attempt"})
    for index in range(diagnostics.LIMIT + 1):
        diagnostics.record(service, "state", {"state": "peer_verified", "setup_id": str(index)})
    reopened = SimpleNamespace(store=service.store)
    report = diagnostics.report(reopened)
    assert all(row["phase"] == "peer_verified" for row in report["events"])
    assert report["last_failure"]["phase"] == phase


def test_one_sided_preparation_is_not_saved_as_a_failure():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "state", {"state": "no_local_address"})
    assert diagnostics.report(service)["last_failure"] is None


def test_expired_diagnostics_are_not_exported(monkeypatch):
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed"})
    future = time.time() + diagnostics.RETENTION + 1
    monkeypatch.setattr(diagnostics.time, "time", lambda:future)
    assert diagnostics.report(service)["events"] == []
    assert diagnostics.report(service)["last_failure"] is None
    assert service.store.get("connection_diagnostics", "history")["events"] == []
    assert service.store.get("connection_diagnostics", "history")["last_failure"] is None


def test_capture_failure_does_not_change_operation_outcome():
    class BrokenStore(Store):
        def put(self, *args):
            raise OSError("private-path-and-secret")
    diagnostics.record(SimpleNamespace(store=BrokenStore()), "action_failed", {"state":"failed"})


def test_failure_context_is_allowlisted_and_missing_attempt_is_not_a_fake_identifier():
    service = SimpleNamespace(store=Store())
    secret = "private-key-192.0.2.1-invitation-document"
    diagnostics.record(service, "action_failed", {"state":"failed",
        "command":"prepare_direct_answer", "error_code":"workspace_already_known",
        "failure_stage":"join_authorization", "failure_reason":"invitation_mismatch",
        "workspace_state":"joining", "exception":secret, "document":secret})
    row = diagnostics.report(service)["last_failure"]
    assert row["command"] == "prepare_direct_answer"
    assert row["error_code"] == "workspace_already_known"
    assert row["failure_stage"] == "join_authorization"
    assert row["failure_reason"] == "invitation_mismatch"
    assert row["workspace_state"] == "joining"
    assert row["attempt"] == "unavailable"
    assert secret not in json.dumps(row)
    diagnostics.record(service, "action_failed", {"state":"failed",
        "command":secret, "error_code":secret, "failure_stage":secret,
        "failure_reason":secret, "workspace_state":secret})
    row = diagnostics.report(service)["last_failure"]
    assert all(row[key] == "unavailable" for key in ("command", "error_code", "failure_stage"))
    assert row["failure_reason"] == "unavailable"
    assert row["workspace_state"] == "unavailable"
    assert secret not in json.dumps(diagnostics.report(service))


def test_unknown_workspace_state_is_unavailable_not_silently_none():
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed", "command":"prepare_direct_answer"})
    row = diagnostics.report(service)["last_failure"]
    assert row["workspace_state"] == "unavailable"
    assert row["failure_reason"] == "unavailable"


def test_failure_survives_encrypted_vault_reopen_and_clear_preserves_workspace(tmp_path):
    from mesh_chat.vault import VaultStore
    key = os.urandom(32)
    store = VaultStore(tmp_path / "profile", key, allow_unprotected_for_tests=True)
    secret = "synthetic-secret-document-never-in-diagnostics"
    try:
        store.put("workspace", "saved", {"state":"joining", "request":"preserve-this-request"})
        diagnostics.record(SimpleNamespace(store=store), "state", {
            "setup_id":"attempt", "state":"existing_routes_only", "document":secret})
    finally:
        store.close()
    reopened = VaultStore(tmp_path / "profile", key, allow_unprotected_for_tests=True)
    try:
        report = diagnostics.report(SimpleNamespace(store=reopened))
        assert report["last_failure"]["phase"] == "existing_routes_only"
        assert secret not in json.dumps(report)
        before = reopened.get("workspace", "saved")
        reopened.delete("connection_diagnostics", "history")
        assert diagnostics.report(SimpleNamespace(store=reopened))["events"] == []
        assert reopened.get("workspace", "saved") == before
    finally:
        reopened.close()
    assert secret.encode() not in (tmp_path / "profile" / "mesh-chat.vault").read_bytes()
