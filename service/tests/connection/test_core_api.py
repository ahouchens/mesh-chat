from dataclasses import replace
import json
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.session import CoreSession, Grant, ProfileObservation
from mesh_chat.connection.projection import snapshot
from tools.connection_harness.simulation import Simulation


class Observations:
    def __init__(self):
        self.calls = []
        sim = Simulation()
        self.value = ProfileObservation("Alex", "ab" * 16,
            {"internal-connection": snapshot(sim.owner.snapshot(sim.key), 0)})

    def profile(self, internal):
        self.calls.append(internal)
        return self.value


def request(operation, **params):
    return {"api_version": 1, "request_id": "request:1", "operation": operation, "params": params}


def session(caller="alex", profiles=("internal-profile",), permissions=frozenset({"observe"})):
    grants = [Grant(caller, permissions, profiles)]
    observations = Observations()
    client = CoreSession(lambda: grants[0], observations, handle_key=b"k" * 32)
    return client, grants, observations


def negotiate(client):
    reply = client.request(request("runtime.capabilities"))
    assert reply["ok"], reply
    return reply["result"]["profiles"][0]


def test_scoped_observations_follow_negotiation_without_exposing_internal_ids():
    client, _, observations = session()
    profile = negotiate(client)
    result = client.request(request("profile.query", profile=profile))
    connection = result["result"]["connections"][0]
    reply = client.request(request("connection.snapshot", profile=profile, connection=connection))
    assert reply["result"]["observation"]["messaging_ready"] is False
    encoded = json.dumps([result, reply])
    assert "internal-profile" not in encoded and "internal-connection" not in encoded
    assert '"profile_id"' not in encoded
    assert observations.calls == ["internal-profile", "internal-profile"]


def test_caller_cannot_use_another_callers_profile_handle():
    alex, _, _ = session()
    blair, _, observations = session("blair")
    foreign = negotiate(alex)
    negotiate(blair)
    result = blair.request(request("profile.query", profile=foreign))
    assert result["error"]["code"] == "forbidden"
    assert observations.calls == []


@pytest.mark.parametrize("revocation", ["session", "permission", "profile", "identity"])
def test_current_grants_are_rechecked_before_domain_access(revocation):
    client, grants, observations = session()
    profile = negotiate(client)
    if revocation == "session": grants[0] = None
    if revocation == "permission": grants[0] = replace(grants[0], permissions=frozenset())
    if revocation == "profile": grants[0] = replace(grants[0], profiles=())
    if revocation == "identity": grants[0] = replace(grants[0], caller="blair")
    result = client.request(request("profile.query", profile=profile))
    assert result["error"]["code"] in {"unauthenticated", "forbidden"}
    assert observations.calls == []


@pytest.mark.parametrize("field,value", [("caller", "owner"), ("permissions", ["observe"]),
    ("resource_id", "native-resource"), ("profile_dir", "private-path"),
    ("idempotency_key", "pretend-key")])
def test_untrusted_requests_cannot_supply_authority(field, value):
    client, _, observations = session()
    raw = request("runtime.capabilities")
    raw[field] = value
    assert client.request(raw)["error"]["code"] == "invalid_request"
    assert observations.calls == []


def test_negotiation_and_detach_are_session_local():
    first, _, observations = session()
    profile = negotiate(first)
    second, _, other = session()
    assert second.request(request("profile.query", profile=profile))["error"]["code"] == "negotiation_required"
    first.detach()
    assert first.request(request("profile.query", profile=profile))["error"]["code"] == "unauthenticated"
    assert not observations.calls and not other.calls
    assert negotiate(second) == profile


def test_domain_failures_are_stable_errors_without_exception_text():
    client, _, observations = session()
    profile = negotiate(client)
    def fail(_):
        raise RuntimeError("private SDP, vault key and file path")
    observations.profile = fail
    assert client.request(request("profile.query", profile=profile)) == {
        "api_version": 1, "request_id": "request:1", "ok": False,
        "error": {"code": "internal", "retry_after_ms": None}}


@pytest.mark.parametrize("change,code", [({"api_version": True}, "incompatible_version"),
    ({"api_version": 2}, "incompatible_version"), ({"request_id": "x" * 81}, "invalid_request"),
    ({"operation": "native_webrtc_close"}, "unsupported_operation"),
    ({"params": {"runtime_epoch": "spoofed"}}, "invalid_request")])
def test_versions_operations_and_field_bounds_fail_closed(change, code):
    client, _, _ = session()
    response = client.request({**request("runtime.capabilities"), **change})
    assert response["error"]["code"] == code


def test_no_permission_does_not_advertise_observation_operations_or_profiles():
    client, _, observations = session(permissions=frozenset())
    assert client.request(request("runtime.capabilities"))["error"]["code"] == "forbidden"
    assert observations.calls == []


def test_connection_handles_cannot_cross_profiles_even_for_the_same_caller():
    client, _, _ = session(profiles=("first-profile", "second-profile"))
    profiles = client.request(request("runtime.capabilities"))["result"]["profiles"]
    connection = client.request(request("profile.query", profile=profiles[0]))["result"]["connections"][0]
    result = client.request(request("connection.snapshot", profile=profiles[1], connection=connection))
    assert result["error"]["code"] == "forbidden"


def test_removed_grant_cannot_silently_reauthenticate_the_same_session():
    client, grants, _ = session()
    original = grants[0]
    negotiate(client)
    grants[0] = None
    assert client.request(request("runtime.capabilities"))["error"]["code"] == "unauthenticated"
    grants[0] = original
    assert client.request(request("runtime.capabilities"))["error"]["code"] == "unauthenticated"


def test_observation_capacity_is_a_failure_instead_of_silent_truncation():
    client, _, observations = session()
    profile = negotiate(client)
    observations.value.connections.update({f"internal-{index}": {} for index in range(256)})
    assert client.request(request("profile.query", profile=profile))["error"]["code"] == "resource_exhausted"


@pytest.mark.parametrize("field,value", [("sequence", True), ("sequence", 2**53),
    ("retry_in", float("nan")), ("evidence_age", -1), ("messaging_ready", True)])
def test_malformed_domain_observations_cannot_claim_readiness(field, value):
    client, _, observations = session()
    profile = negotiate(client)
    connection = client.request(request("profile.query", profile=profile))["result"]["connections"][0]
    observations.value.connections["internal-connection"][field] = value
    assert client.request(request("connection.snapshot", profile=profile, connection=connection))["error"]["code"] == "internal"


def test_every_returned_result_matches_its_contract_and_drops_private_fields():
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    results = Draft202012Validator(json.loads((root / "observation-result-v1.schema.json").read_text()))
    errors = Draft202012Validator(json.loads((root / "error-v1.schema.json").read_text()))
    Draft202012Validator.check_schema(results.schema)
    client, _, observations = session()
    cap = client.request(request("runtime.capabilities"))
    manifest = json.loads((root / "operations-v1.json").read_text())
    assert cap["result"]["operations"] == manifest["experimental_component_operations"][:3]
    profile = cap["result"]["profiles"][0]
    profile_reply = client.request(request("profile.query", profile=profile))
    connection = profile_reply["result"]["connections"][0]
    observations.value.connections["internal-connection"].update(
        sdp="private SDP", vault_key="secret", authenticated_receipt=True, reason="private_exception")
    status = client.request(request("connection.snapshot", profile=profile, connection=connection))
    for reply in (cap, profile_reply, status):
        results.validate(reply)
    assert status["result"]["observation"]["reason"] == "unknown"
    assert "private" not in json.dumps(status) and "secret" not in json.dumps(status)
    errors.validate(client.request(request("native_webrtc_event")))


def test_public_requests_cannot_select_the_trusted_host_bootstrap():
    from mesh_chat.service import MeshChatService
    client, _, observations = session()
    for operation in ("bind_service_session", "native_manual_carrier_authorized", "claim_native_reconnect_carrier",
                      "connection.platform_event", "connection.complete", "receipt.confirm"):
        assert operation not in MeshChatService.COMMANDS
        assert client.request(request(operation))["error"]["code"] == "unsupported_operation"
    assert not observations.calls


def test_service_binding_uses_current_policy_projection_and_serialized_authority():
    from mesh_chat.core_api.composition import bind_service_session
    sim = Simulation()
    sim.recover()
    service = SimpleNamespace(_shutdown=Event(), _dispatch_lock=RLock(), _identity=object(),
        store=SimpleNamespace(opaque_id=lambda *_: "ab" * 32, items=lambda *_, **__: [],
                              get=lambda *_: {"display_name": "Alex", "destination_hash": "cd" * 16}),
        _require_profile=lambda: {"display_name": "Alex", "destination_hash": "cd" * 16},
        _connection_runtime=SimpleNamespace(snapshots=lambda: {
            sim.key.profile_id: snapshot(sim.owner.snapshot(sim.key), sim.now)}))
    def authorize():
        assert service._dispatch_lock._is_owned()
        return Grant("host-authenticated-alex", frozenset({"observe"}), ("local",))
    client = bind_service_session(service, authorize)
    profile = negotiate(client)
    connection = client.request(request("profile.query", profile=profile))["result"]["connections"][0]
    assert client.request(request("connection.snapshot", profile=profile, connection=connection))["result"]["observation"]["messaging_ready"]
    sim.close()
    assert not client.request(request("connection.snapshot", profile=profile, connection=connection))["result"]["observation"]["messaging_ready"]
    service._identity = None
    assert client.request(request("profile.query", profile=profile))["error"]["code"] == "locked"
    service._shutdown.set()
    assert client.request(request("runtime.capabilities"))["error"]["code"] == "unauthenticated"
