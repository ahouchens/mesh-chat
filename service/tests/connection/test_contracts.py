from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.connection.projection import snapshot
from tools.connection_harness.simulation import Simulation


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def validator(relative):
    schema = json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_executing_policy_observations_follow_the_versioned_contract():
    contract = validator("connection/snapshot-v1.schema.json")
    sim = Simulation()
    sim.advance(0)
    sim.complete(adopt=True)
    for _ in range(15):
        contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))
        sim.complete()
        sim.advance(1)
    sim.network(False)
    contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))
    sim.close()
    contract.validate(snapshot(sim.owner.snapshot(sim.key), sim.now))


@pytest.mark.parametrize("field,value", [("sdp", "secret"), ("resource_id", "native-private"),
    ("mailbox_secret", "secret"), ("delivered", True), ("runtime_epoch", "x" * 65),
    ("sequence", -1), ("retry_in", -1), ("messaging_ready", True)])
def test_observations_reject_private_leaks_and_false_readiness(field, value):
    sim = Simulation()
    observation = snapshot(sim.owner.snapshot(sim.key), sim.now)
    observation[field] = value
    assert not validator("connection/snapshot-v1.schema.json").is_valid(observation)


def enqueue_request():
    return {"api_version": 1, "request_id": "client:request-1", "operation": "message.enqueue",
            "idempotency_key": "mutation-key-0001",
            "params": {"profile": "authorizedProfile1", "recipient": "authorizedPeer0001",
                       "kind": "text", "text": "Hello"}}


def test_public_request_contract_has_explicit_mutation_identity():
    contract = validator("core-api/request-v1.schema.json")
    request = enqueue_request()
    contract.validate(request)
    del request["idempotency_key"]
    assert not contract.is_valid(request)
    request = {"api_version": 1, "request_id": "query:1", "operation": "runtime.capabilities", "params": {}}
    contract.validate(request)
    request["idempotency_key"] = "query-cache-key-1"
    assert not contract.is_valid(request)


def test_each_designed_operation_has_an_executable_request_vector_and_permission():
    contract = validator("core-api/request-v1.schema.json")
    handle = "callerScopedHandle1"
    examples = {
        "runtime.capabilities": {}, "runtime.stop": {},
        "profile.create": {"display_name": "Alex"}, "profile.select": {},
        "profile.unlock": {"credential_handle": handle}, "profile.lock": {}, "profile.query": {},
        "peer.pairing_create": {"lifetime_seconds": 300},
        "peer.pairing_accept": {"document": "signed-pairing-document"},
        "peer.query": {"peer": handle},
        "peer.approve": {"peer": handle},
        "peer.revoke": {"peer": handle},
        "connection.start": {"connection": handle}, "connection.stop": {"connection": handle},
        "connection.retry": {"connection": handle}, "connection.snapshot": {"connection": handle},
        "message.enqueue": {"recipient": handle, "kind": "text", "text": "Hello"},
        "message.query": {"message": handle}, "message.list": {"cursor": None, "limit": 128},
        "message.received": {"cursor": None, "limit": 128},
        "connection.start": {"peer": handle}, "connection.stop": {"peer": handle},
        "events.poll": {"cursor": None, "limit": 128}, "events.ack": {"cursor": handle},
        "diagnostics.query": {"limit": 256},
    }
    manifest = json.loads((CONTRACTS / "core-api/operations-v1.json").read_text())
    assert manifest["implemented_operations"] == []  # Schema availability is not API implementation.
    assert set(examples) == {operation["operation"] for operation in manifest["operations"]}
    for operation in manifest["operations"]:
        params = dict(examples[operation["operation"]])
        assert operation["scope"] in {"runtime", "profile"}
        assert operation["permission"] in {"observe", "runtime_owner", "profile_owner", "pair",
                                            "approve", "connect", "send", "read", "diagnose"}
        if operation["scope"] == "profile":
            params["profile"] = handle
        request = {"api_version": 1, "request_id": "vector:1", "operation": operation["operation"], "params": params}
        if operation["idempotency"] == "caller_profile_operation_key":
            request["idempotency_key"] = "operation-key-0001"
        contract.validate(request)


@pytest.mark.parametrize("field,value", [("caller_id", "owner"), ("permissions", ["approve"]),
    ("runtime_epoch", "spoofed"), ("resource_id", "native-private"), ("authenticated_receipt", True),
    ("vault_key", "secret"), ("profile_dir", "C:/private"), ("delivered", True)])
def test_public_requests_cannot_supply_private_authority(field, value):
    contract = validator("core-api/request-v1.schema.json")
    for where in ("envelope", "params"):
        request = enqueue_request()
        (request if where == "envelope" else request["params"])[field] = value
        assert not contract.is_valid(request)


@pytest.mark.parametrize("mutation", [
    {"api_version": 2}, {"operation": "native_webrtc_event"},
    {"operation": "receipt.confirm"}, {"request_id": "x" * 81},
    {"params": {"profile": "../../vault", "recipient": "authorizedPeer0001", "kind": "text", "text": "Hello"}},
])
def test_incompatible_versions_private_operations_and_unbounded_ids_are_rejected(mutation):
    request = {**enqueue_request(), **deepcopy(mutation)}
    assert not validator("core-api/request-v1.schema.json").is_valid(request)


def test_public_errors_have_no_exception_or_unbounded_diagnostic_channel():
    contract = validator("core-api/error-v1.schema.json")
    response = {"api_version": 1, "request_id": "request:1", "ok": False,
                "error": {"code": "forbidden", "retry_after_ms": None}}
    contract.validate(response)
    response["error"]["exception"] = "private SDP"
    assert not contract.is_valid(response)
