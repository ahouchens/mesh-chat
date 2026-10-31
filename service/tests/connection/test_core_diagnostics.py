from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.connection.projection import snapshot
from tools.connection_harness.simulation import Simulation
from test_core_messages import host, client, request


@pytest.fixture
def diagnostic_host(host):
    service = host()
    sim = Simulation()
    observations = {"private-connection": snapshot(sim.owner.snapshot(sim.key), 0)}
    calls = []
    def inspect():
        calls.append("inspect")
        return dict(observations)
    service._connection_runtime = SimpleNamespace(snapshots=inspect, _failure=None)
    try:
        yield service, observations, calls
    finally:
        service._connection_runtime = None


def query(session, profile, limit=256):
    return session.request(request("diagnostics.query", profile=profile, limit=limit))


def diagnostic_client(service, caller="alex"):
    return client(service, caller, permissions=frozenset({"observe", "diagnose"}))


def test_diagnostics_select_only_scoped_current_policy_observations(diagnostic_host):
    service, observations, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    observations["private-connection"].update(sdp="secret-sdp", resource_id="private-resource",
        profile_id="private-profile", delivered=True, reason="exception: private-path")
    result = query(session, profile)
    assert result["ok"], result
    body = result["result"]
    assert body["available"] and body["runtime_failure"] is None
    assert body["total_connections"] == 1 and body["truncated"] is False
    item, = body["connections"]
    expected = session.request(request("profile.query", profile=profile))["result"]["connections"]
    assert [item["connection"]] == expected
    assert item["observation"]["reason"] == "unknown"
    assert item["observation"]["messaging_ready"] is False
    assert all(secret not in json.dumps(body) for secret in ("secret", "private", "delivered"))


def test_diagnose_is_separate_from_observe_and_read(diagnostic_host):
    service, _, calls = diagnostic_host
    session, _, profile, _ = client(service)
    calls.clear()
    assert query(session, profile)["error"]["code"] == "forbidden"
    assert calls == []


@pytest.mark.parametrize("change", ["permission", "profile", "caller", "detach", "locked", "shutdown"])
def test_diagnostics_recheck_authority_before_inspecting_the_runtime(diagnostic_host, change):
    service, _, calls = diagnostic_host
    session, grants, profile, _ = diagnostic_client(service)
    assert query(session, profile)["ok"]
    calls.clear()
    if change == "permission": grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    if change == "profile": grants[0] = replace(grants[0], profiles=())
    if change == "caller": grants[0] = replace(grants[0], caller="blair")
    if change == "detach": session.detach()
    if change == "locked": service._identity = None
    if change == "shutdown": service._shutdown.set()
    try:
        assert query(session, profile)["error"]["code"] in {"forbidden", "unauthenticated", "locked"}
        assert calls == []
    finally:
        service._shutdown.clear()


def test_foreign_profile_is_rejected_and_connection_handles_are_caller_scoped(diagnostic_host):
    service, _, calls = diagnostic_host
    alex, _, profile, _ = diagnostic_client(service)
    blair, _, other_profile, _ = diagnostic_client(service, "blair")
    calls.clear()
    assert query(blair, profile)["error"]["code"] == "forbidden"
    assert calls == []
    first = query(alex, profile)["result"]["connections"][0]["connection"]
    second = query(blair, other_profile)["result"]["connections"][0]["connection"]
    assert first != second


def test_diagnostics_reports_explicit_truncation_with_stable_selection(diagnostic_host):
    service, observations, _ = diagnostic_host
    value = observations.pop("private-connection")
    observations.update({f"internal-{index}": value for index in range(256)})
    session, _, profile, _ = diagnostic_client(service)
    result = query(session, profile, 2)["result"]
    assert result["total_connections"] == 256 and result["truncated"]
    assert len(result["connections"]) == 2
    assert query(session, profile, 2)["result"]["connections"] == result["connections"]
    assert len(query(session, profile)["result"]["connections"]) == 256
    assert len(json.dumps(query(session, profile), ensure_ascii=True)) < 262144
    observations["overflow"] = value
    assert query(session, profile, 1)["error"]["code"] == "resource_exhausted"


@pytest.mark.parametrize("limit", [0, 257, True, 1.5, None, "1"])
def test_invalid_diagnostic_limits_fail_before_runtime_access(diagnostic_host, limit):
    service, _, calls = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    calls.clear()
    assert query(session, profile, limit)["error"]["code"] == "invalid_request"
    assert calls == []


@pytest.mark.parametrize("failure,expected", [(None, None), ("adapter_quarantined", "adapter_quarantined"),
    ("cleanup_failed", "cleanup_failed"), ("private exception path", "unknown")])
def test_runtime_failure_is_allowlisted_even_when_no_actors_exist(diagnostic_host, failure, expected):
    service, observations, _ = diagnostic_host
    observations.clear()
    service._connection_runtime._failure = failure
    session, _, profile, _ = diagnostic_client(service)
    result = query(session, profile)["result"]
    assert result["runtime_failure"] == expected and result["available"]
    assert result["connections"] == [] and result["total_connections"] == 0
    assert not result["truncated"]


def test_legacy_runtime_reports_unavailable_without_exporting_global_history(host):
    service = host()
    session, _, profile, _ = diagnostic_client(service)
    service.store.put("connection_diagnostics", "history", {"events": ["private-other-caller"]})
    before = service.store.get("connection_diagnostics", "history")
    result = query(session, profile)
    assert result["ok"], result
    assert result["result"]["available"] is False
    assert result["result"]["connections"] == []
    assert "private" not in json.dumps(result)
    assert service.store.get("connection_diagnostics", "history") == before


def test_query_never_persists_history_or_runs_native_inspection(diagnostic_host, monkeypatch):
    service, _, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    def forbidden(*_, **__): pytest.fail("Diagnostics must be a bounded policy read")
    with monkeypatch.context() as guards:
        guards.setattr(service.store, "put_many", forbidden)
        guards.setattr(service.store, "list", forbidden)
        guards.setattr(service, "native_webrtc_stats", forbidden)
        assert query(session, profile)["ok"]


def test_diagnostics_and_capabilities_match_explicit_result_contracts(diagnostic_host):
    service, _, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    schema = json.loads((root / "diagnostics-result-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(query(session, profile))
    cap = session.request(request("runtime.capabilities"))
    Draft202012Validator(json.loads((root / "observation-result-v1.schema.json").read_text())).validate(cap)
    assert cap["result"]["limits"]["diagnostic_count"] == 256
    assert cap["result"]["limits"]["diagnostic_bytes"] == 262144
    Draft202012Validator(json.loads((root / "request-v1.schema.json").read_text())).validate(
        request("diagnostics.query", profile=profile, limit=256))


def test_diagnostics_require_negotiation_before_runtime_access(diagnostic_host):
    from mesh_chat.core_api.composition import bind_service_session
    service, _, calls = diagnostic_host
    _, grants, profile, _ = diagnostic_client(service)
    session = bind_service_session(service, lambda: grants[0])
    calls.clear()
    assert query(session, profile)["error"]["code"] == "negotiation_required"
    assert not calls


def test_unbound_diagnostic_port_is_not_advertised_or_callable():
    from test_core_api import session as unbound_session
    session, _, observations = unbound_session(permissions=frozenset({"observe", "diagnose"}))
    cap = session.request(request("runtime.capabilities"))["result"]
    assert "diagnostics.query" not in cap["operations"]
    assert "diagnostic_count" not in cap["limits"]
    assert query(session, cap["profiles"][0])["error"]["code"] == "unsupported_operation"
    assert not observations.calls


@pytest.mark.parametrize("field,value", [("captured_at", float("nan")), ("captured_at", -1),
    ("captured_at", True), ("available", "yes"), ("runtime_failure", {}),
    ("connections", []), ("connections", {"": {}}), ("connections", {1: {}}),
    ("connections", {"internal": {"messaging_ready": True}})])
def test_malformed_diagnostic_port_results_fail_closed(diagnostic_host, field, value):
    from mesh_chat.core_api.diagnostics import DiagnosticObservation
    service, _, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    observation = replace(DiagnosticObservation(1, True, None, {}), **{field: value})
    session._diagnostics = SimpleNamespace(query=lambda _: observation)
    assert query(session, profile)["error"]["code"] == "internal"


@pytest.mark.parametrize("field,value", [("resource_id", "private"), ("caller", "owner"),
    ("runtime_epoch", "epoch"), ("cursor", "x" * 64), ("permissions", ["diagnose"])])
def test_diagnostic_requests_cannot_supply_private_controls(diagnostic_host, field, value):
    service, _, calls = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    calls.clear()
    payload = request("diagnostics.query", profile=profile, limit=1)
    payload["params"][field] = value
    assert session.request(payload)["error"]["code"] == "invalid_request"
    assert not calls


def test_private_runtime_failures_do_not_escape_as_raw_exceptions(diagnostic_host):
    service, _, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    def fail(): raise RuntimeError("private SDP and secret vault path")
    service._connection_runtime.snapshots = fail
    result = query(session, profile)
    assert result["error"]["code"] == "internal"
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)


def test_diagnostic_schema_rejects_private_fields_and_false_availability(diagnostic_host):
    service, _, _ = diagnostic_host
    session, _, profile, _ = diagnostic_client(service)
    result = query(session, profile)
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    validator = Draft202012Validator(json.loads((root / "diagnostics-result-v1.schema.json").read_text()))
    result["result"]["connections"][0]["observation"]["sdp"] = "private"
    assert not validator.is_valid(result)
    del result["result"]["connections"][0]["observation"]["sdp"]
    result["result"]["available"] = False
    assert not validator.is_valid(result)
