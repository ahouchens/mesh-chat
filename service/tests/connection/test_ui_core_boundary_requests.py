"""Serialized UI contract vectors must reach production admission and authority.

These tests deliberately stop at a denied caller grant. Domain effects need real
handles, but syntax and mutation identity must be admitted before that denial.
"""

from dataclasses import fields
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, PROFILE_RUNTIME_OPERATIONS, CALL_RECOVERY_OPERATIONS, parse_request
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.runtime_host import CoreRuntimeHost, RegisteredProfile
from mesh_chat.core_api.session import CoreSession, Grant, Ports
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.core_api.call_operations import CallRetirementAcknowledgment, CallRetirementTicket
from test_core_messages import host
from test_core_call_idempotency import FINGERPRINT, SDP


ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "tests/core-ui-boundary/request-vectors.json").read_text(encoding="utf-8"))
COMPONENT_VECTORS = [value for value in VECTORS if value["operation"] in COMPONENT_OPERATIONS]
CONTRACT = Draft202012Validator(json.loads(
    (ROOT / "contracts/core-api/request-v1.schema.json").read_text(encoding="utf-8")))
PRIVATE_CONTRACT = Draft202012Validator(json.loads(
    (ROOT / "contracts/core-api/private-host-request-v1.schema.json").read_text(encoding="utf-8")))
BOOTSTRAP_CONTRACT = Draft202012Validator(json.loads(
    (ROOT / "contracts/core-api/private-bootstrap-request-v1.schema.json").read_text(encoding="utf-8")))


def contract_for(operation):
    return {"native.command": PRIVATE_CONTRACT, "bootstrap.preview": BOOTSTRAP_CONTRACT}.get(operation, CONTRACT)


def wire_round_trip(value):
    return json.loads(json.dumps(value, ensure_ascii=False).encode("utf-8").decode("utf-8"))


class ForbiddenEffects:
    def __getattr__(self, name):
        raise AssertionError(f"Denied caller reached an effect: {name}")


@pytest.fixture
def denied_runtime(tmp_path):
    """Real protected catalog/runtime framing; no profile opener may execute."""
    effects = []
    def open_profile():
        effects.append("open")
        raise AssertionError("Denied caller opened a profile")
    def publish(service):
        effects.append("publish")
        raise AssertionError("Denied caller published a service")
    with VaultStore(tmp_path / "host-catalog", os.urandom(32), allow_unprotected_for_tests=True) as catalog:
        host = CoreRuntimeHost(catalog, (RegisteredProfile("boundary-profile", "Boundary profile", os.urandom(32), open_profile),),
            selected="boundary-profile", publish=publish, credential_authorizer=lambda *_: True)
        grants = [Grant("denied-ui", frozenset({"observe"}), ("boundary-profile",))]
        stream = host.bind(lambda: grants[0])
        caps = decode_frame(stream.exchange(encode_frame({"api_version": 1, "request_id": "runtime:negotiate",
            "operation": "runtime.capabilities", "params": {}})))
        assert caps["ok"] and set(PROFILE_RUNTIME_OPERATIONS) <= set(caps["result"]["operations"])
        profile = caps["result"]["profiles"][0]
        credential = host.issue_unlock_credential("denied-ui", "boundary-profile")
        grants[0] = Grant("denied-ui", frozenset(), ("boundary-profile",))
        def records():
            return catalog._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
        before = records(), catalog._db.total_changes, dict(host._credentials), host.lifecycle.query()
        def exchange(vector):
            value = wire_round_trip(vector)
            if "profile" in value["params"]: value["params"]["profile"] = profile
            if value["operation"] == "profile.unlock": value["params"]["credential_handle"] = credential
            contract_for(value["operation"]).validate(value)
            result = decode_frame(stream.exchange(encode_frame(value)))
            assert (records(), catalog._db.total_changes, dict(host._credentials), host.lifecycle.query()) == before
            assert effects == [] and host.lifecycle.active is None
            return result
        try:
            yield exchange
        finally:
            stream.close()


def test_vectors_cover_every_advertised_component_operation():
    names = [value["operation"] for value in COMPONENT_VECTORS]
    assert len(names) == len(set(names))
    assert set(names) == set(COMPONENT_OPERATIONS)


@pytest.fixture
def denied_call_recovery(host):
    """Actual framed journal with a typed substitute host; no media proof."""
    service = host()
    retirements = []
    class Retirement:
        owner_incarnation = "boundary-component-media-owner-0001"
        def request_retirement(self, ticket):
            assert isinstance(ticket, CallRetirementTicket)
            retirements.append(ticket)
            return CallRetirementAcknowledgment(ticket, retired=True)
    grants = [Grant("denied-call-ui", frozenset({"observe", "read", "send"}), ("local",))]
    stream = bind_service_stream(service, lambda: grants[0], call_retirement=Retirement())
    def invoke(operation, params=None, key=None):
        value = {"api_version": 1, "request_id": "call-vector:fixture", "operation": operation, "params": params or {}}
        if key is not None: value["idempotency_key"] = key
        return decode_frame(stream.exchange(encode_frame(value)))
    caps = invoke("runtime.capabilities")
    assert caps["ok"] and set(CALL_RECOVERY_OPERATIONS) <= set(caps["result"]["operations"])
    profile = caps["result"]["profiles"][0]
    accepted = invoke("call.control", {"profile": profile, "action": "start", "contact_id": "internal-peer",
        "media": "audio", "sdp": SDP, "dtls_fingerprint": FINGERPRINT}, "boundary-call-vector-start-0001")
    assert accepted["ok"], accepted
    listed = invoke("call.operation_list", {"profile": profile})
    assert listed["ok"] and len(listed["result"]["operations"]) == 1
    operation = listed["result"]["operations"][0]["operation"]
    grants[0] = Grant("denied-call-ui", frozenset(), ("local",))
    def rows():
        return service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    before = rows(), service.store._db.total_changes
    def exchange(vector):
        value = wire_round_trip(vector)
        value["params"]["profile"] = profile
        if "operation" in value["params"]: value["params"]["operation"] = operation
        contract_for(value["operation"]).validate(value)
        result = decode_frame(stream.exchange(encode_frame(value)))
        assert (rows(), service.store._db.total_changes) == before and retirements == []
        return result
    try:
        yield exchange
    finally:
        stream.close()


@pytest.mark.parametrize("vector", COMPONENT_VECTORS, ids=lambda value: value["operation"])
def test_schema_valid_serialized_request_reaches_production_parser(vector):
    value = wire_round_trip(vector)
    contract_for(value["operation"]).validate(value)
    operation, params = parse_request(value, COMPONENT_OPERATIONS)
    assert (operation, params) == (value["operation"], value["params"])


@pytest.mark.parametrize("operation", ["native.command", "bootstrap.preview"])
def test_private_host_envelope_is_rejected_by_the_public_contract(operation):
    private = next(value for value in COMPONENT_VECTORS if value["operation"] == operation)
    assert not CONTRACT.is_valid(wire_round_trip(private))
    contract_for(operation).validate(wire_round_trip(private))


@pytest.mark.parametrize("vector", COMPONENT_VECTORS, ids=lambda value: value["operation"])
def test_serialized_request_reaches_session_authority_without_effects(vector, request):
    if vector["operation"] in PROFILE_RUNTIME_OPERATIONS:
        reply = request.getfixturevalue("denied_runtime")(vector)
        assert reply == {"api_version": 1, "request_id": vector["request_id"], "ok": False,
                         "error": {"code": "forbidden", "retry_after_ms": None}}
        return
    if vector["operation"] in CALL_RECOVERY_OPERATIONS:
        reply = request.getfixturevalue("denied_call_recovery")(vector)
        assert reply == {"api_version": 1, "request_id": vector["request_id"], "ok": False,
                         "error": {"code": "forbidden", "retry_after_ms": None}}
        return
    effects = ForbiddenEffects()
    ports = Ports(**{field.name: effects for field in fields(Ports)})
    session = CoreSession(lambda: Grant("denied-ui", frozenset(), ("local",)),
                          effects, handle_key=b"boundary-handle-key" * 2, ports=ports)
    reply = wire_round_trip(session.request(wire_round_trip(vector)))
    assert reply == {
        "api_version": 1, "request_id": vector["request_id"], "ok": False,
        "error": {"code": "forbidden", "retry_after_ms": None},
    }


@pytest.mark.parametrize("vector", [value for value in COMPONENT_VECTORS if value["operation"] in PROFILE_RUNTIME_OPERATIONS + CALL_RECOVERY_OPERATIONS], ids=lambda value: value["operation"])
def test_ordinary_service_binding_does_not_advertise_or_dispatch_host_only_authority(vector, tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    store = VaultStore(tmp_path / "ordinary", os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path / "ordinary", lambda *_: None)
    session = bind_service_stream(service, lambda: Grant("ordinary-owner", frozenset({"observe", "read", "send", "profile_owner"}), ("local",)))
    try:
        caps = decode_frame(session.exchange(encode_frame({"api_version": 1, "request_id": "ordinary:negotiate",
            "operation": "runtime.capabilities", "params": {}})))
        assert caps["ok"] and not set(PROFILE_RUNTIME_OPERATIONS + CALL_RECOVERY_OPERATIONS) & set(caps["result"]["operations"])
        before = store._db.total_changes
        reply = decode_frame(session.exchange(encode_frame(wire_round_trip(vector))))
        assert reply == {"api_version": 1, "request_id": vector["request_id"], "ok": False,
                         "error": {"code": "unsupported_operation", "retry_after_ms": None}}
        assert store._db.total_changes == before and store.get("profile", "local") is None
    finally:
        session.close()
        service.close()
