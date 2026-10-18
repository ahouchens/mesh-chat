import json
import time
from types import SimpleNamespace

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
    for _ in range(220):
        diagnostics.record(service, "state", {"state":"connecting"})
    reopened = SimpleNamespace(store=service.store)
    value = diagnostics.report(reopened)
    assert len(value["events"]) == 200
    assert value["truncated"] is True
    assert value["last_failure"]["phase"] == "failed"
    assert len(json.dumps(value).encode()) < 65536


def test_expired_diagnostics_are_not_exported(monkeypatch):
    service = SimpleNamespace(store=Store())
    diagnostics.record(service, "action_failed", {"state":"failed"})
    future = time.time() + diagnostics.RETENTION + 1
    monkeypatch.setattr(diagnostics.time, "time", lambda:future)
    assert diagnostics.report(service)["events"] == []
    assert diagnostics.report(service)["last_failure"] is None


def test_capture_failure_does_not_change_operation_outcome():
    class BrokenStore(Store):
        def put(self, *args):
            raise OSError("private-path-and-secret")
    diagnostics.record(SimpleNamespace(store=BrokenStore()), "action_failed", {"state":"failed"})
