"""Standalone client unit boundaries; production hosts are tested separately."""
from collections import deque
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_chat_core_client import CoreClient, CoreClientError


def response(identifier, result):
    return json.dumps({"api_version": 1, "request_id": identifier, "ok": True, "result": result}).encode() + b"\n"


CAP = {"api_major": 1, "api_minor": 0, "operations": ["runtime.capabilities"], "profiles": ["p" * 64], "limits": {}}


class Scripted:
    def __init__(self, *responses):
        self.responses, self.written, self.closed = deque(responses), [], False

    def write(self, value):
        self.written.append(value)

    def read(self, limit):
        return self.responses.popleft() if self.responses else b""

    def close(self):
        self.closed = True


def test_missing_feature_and_missing_caller_keys_never_write_a_mutation():
    stream = Scripted(response("client:1", CAP))
    client = CoreClient.open(stream.read, stream.write, stream.close)
    with pytest.raises(CoreClientError, match="unsupported_operation"):
        client.enqueue_draft("p" * 64, "q" * 64, "a" * 64)
    with pytest.raises(CoreClientError, match="unsupported_operation"):
        client.profile_catalog()
    with pytest.raises(CoreClientError, match="unsupported_operation"):
        client.lock_profile("p" * 64, "caller-profile-key-0001")
    with pytest.raises(CoreClientError, match="unsupported_operation"):
        client.create_group("p" * 64, "Title", "members", ["q" * 64], "caller-group-key-0001")
    with pytest.raises(CoreClientError, match="unsupported_operation"):
        client.send_group("p" * 64, "g" * 64, "Text", "caller-group-key-0001")
    for call in [lambda: client.create_profile("Example"),
                 lambda: client.workspace_join("p" * 64, "signed"),
                 lambda: client.workspace_admission_grant_list("p" * 64, "w" * 64)]:
        with pytest.raises(ValueError, match="caller-provided"):
            call()
    assert len(stream.written) == 1


def test_repaired_helpers_preserve_supplied_keys_without_inventing_any():
    stream = Scripted(response("client:1", CAP), *(response(f"client:{i}", {}) for i in range(2, 5)))
    client = CoreClient.open(stream.read, stream.write)
    key = "explicit-caller-key-0001"
    client.create_profile("Example", key)
    client.workspace_join("p" * 64, "signed", key)
    client.workspace_admission_grant_list("p" * 64, "w" * 64, key)
    assert all(json.loads(value)["idempotency_key"] == key for value in stream.written[1:])


@pytest.mark.parametrize("damage", ["old", "missing_operation", "missing_limit", "boolean_limit", "fractional_minor"])
def test_call_recovery_requires_complete_capabilities_before_any_frame(damage):
    limits = {name: 256 for name in ("call_operations_per_caller_profile", "call_operations_per_vault",
        "call_operation_retention_seconds", "call_operation_keys_per_caller_profile", "call_operation_keys_per_vault")}
    caps = {**CAP, "api_minor": 1, "operations": ["call.operation_list", "call.operation_query", "call.operation_abandon"], "limits": limits}
    if damage == "old": caps["api_minor"] = 0
    if damage == "fractional_minor": caps["api_minor"] = 1.5
    if damage == "missing_operation": caps["operations"] = caps["operations"][:-1]
    if damage == "missing_limit": del limits["call_operations_per_vault"]
    if damage == "boolean_limit": limits["call_operations_per_vault"] = True
    stream = Scripted(response("client:1", caps))
    if damage == "fractional_minor":
        with pytest.raises(CoreClientError, match="incompatible_version"):
            CoreClient.open(stream.read, stream.write)
        assert len(stream.written) == 1
        return
    client = CoreClient.open(stream.read, stream.write)
    for invoke in [lambda: client.call_operation_list("p" * 64),
                   lambda: client.call_operation_query("p" * 64, "o" * 64),
                   lambda: client.call_operation_abandon("p" * 64, "o" * 64, "explicit-abandon-key00")]:
        with pytest.raises(CoreClientError, match="unsupported_operation"): invoke()
    assert len(stream.written) == 1


def test_call_recovery_preserves_explicit_abandon_key_without_retry():
    caps = {**CAP, "api_minor": 1, "operations": ["call.operation_list", "call.operation_query", "call.operation_abandon"],
            "limits": {name: 256 for name in ("call_operations_per_caller_profile", "call_operations_per_vault",
                "call_operation_retention_seconds", "call_operation_keys_per_caller_profile", "call_operation_keys_per_vault")}}
    stream = Scripted(response("client:1", caps), response("client:2", {}))
    client = CoreClient.open(stream.read, stream.write)
    with pytest.raises(ValueError): client.call_operation_abandon("p" * 64, "o" * 64, "bad")
    assert len(stream.written) == 1
    client.call_operation_abandon("p" * 64, "o" * 64, "explicit-abandon-key00")
    frame = json.loads(stream.written[1])
    assert frame["idempotency_key"] == "explicit-abandon-key00" and frame["params"] == {"profile": "p" * 64, "operation": "o" * 64}


def pairing_capabilities():
    return {**CAP, "api_minor": 1, "operations": ["peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel"],
            "limits": {name: 2048 for name in ("pairing_intents_per_runtime", "pairing_active_intents", "pairing_intent_seconds",
                "pairing_code_utf8_bytes", "pairing_key_idempotency_seconds", "pairing_keys_per_caller_profile", "pairing_keys_per_vault")}}


@pytest.mark.parametrize("damage", ["old", "missing_operation", "missing_limit", "boolean_limit"])
def test_pairing_helpers_require_complete_advertised_feature_before_io(damage):
    caps = pairing_capabilities()
    if damage == "old": caps["api_minor"] = 0
    if damage == "missing_operation": caps["operations"] = caps["operations"][:-1]
    if damage == "missing_limit": del caps["limits"]["pairing_active_intents"]
    if damage == "boolean_limit": caps["limits"]["pairing_active_intents"] = True
    stream = Scripted(response("client:1", caps))
    client = CoreClient.open(stream.read, stream.write)
    for invoke in [lambda: client.pairing_begin("p" * 64, "offer", "caller-begin-key-0001"),
                   lambda: client.pairing_query("p" * 64, "q" * 64),
                   lambda: client.pairing_cancel("p" * 64, "q" * 64, "caller-cancel-key-001")]:
        with pytest.raises(CoreClientError, match="unsupported_operation"): invoke()
    assert len(stream.written) == 1


def test_pairing_helpers_preserve_keys_role_and_explicit_disclosure_consent():
    stream = Scripted(response("client:1", pairing_capabilities()), *(response(f"client:{i}", {}) for i in range(2, 6)))
    client = CoreClient.open(stream.read, stream.write)
    for invoke in [lambda: client.pairing_begin("p" * 64, "offer", "bad"),
                   lambda: client.pairing_begin("p" * 64, "answer", "caller-begin-key-0001"),
                   lambda: client.pairing_begin("p" * 64, "offer", "caller-begin-key-0001", pairing_code="forbidden"),
                   lambda: client.pairing_begin("p" * 64, "answer", "caller-begin-key-0001", pairing_code="é" * 1025),
                   lambda: client.pairing_begin("p" * 64, "offer", "caller-begin-key-0001", allow_direct_ip_disclosure=None),
                   lambda: client.pairing_cancel("p" * 64, "q" * 64, "bad")]:
        with pytest.raises(ValueError): invoke()
    assert len(stream.written) == 1
    client.pairing_begin("p" * 64, "offer", "caller-begin-key-0001")
    client.pairing_begin("p" * 64, "answer", "caller-answer-key001", pairing_code="synthetic-code", allow_direct_ip_disclosure=True)
    client.pairing_query("p" * 64, "q" * 64)
    client.pairing_cancel("p" * 64, "q" * 64, "caller-cancel-key-001")
    frames = [json.loads(frame) for frame in stream.written[1:]]
    assert frames[0]["params"] == {"profile": "p" * 64, "role": "offer", "allow_direct_ip_disclosure": False}
    assert frames[1]["params"]["pairing_code"] == "synthetic-code" and frames[1]["params"]["allow_direct_ip_disclosure"] is True
    assert "idempotency_key" not in frames[2]
    assert frames[3]["idempotency_key"] == "caller-cancel-key-001"


def test_optional_group_key_requires_complete_capability_and_valid_key():
    caps = {**CAP, "api_minor": 1, "operations": ["runtime.capabilities", "group.create"],
            "optional_keyed_operations": ["group.create"], "limits": {"optional_key_idempotency_seconds": 604800,
            "optional_keys_per_caller_profile": 4096, "optional_keys_per_vault": 65536}}
    stream = Scripted(response("client:1", caps), response("client:2", {}))
    client = CoreClient.open(stream.read, stream.write)
    with pytest.raises(ValueError, match="caller-provided"):
        client.create_group("p" * 64, "Title", "members", ["q" * 64], "bad")
    assert len(stream.written) == 1
    client.create_group("p" * 64, "Title", "members", ["q" * 64], "explicit-group-key-0001")
    assert json.loads(stream.written[1])["idempotency_key"] == "explicit-group-key-0001"


def test_short_writes_complete_the_same_frame_before_read():
    stream = Scripted(response("client:1", CAP))
    data = bytearray()

    def write(value):
        count = min(7, len(value))
        data.extend(value[:count])
        return count
    client = CoreClient.open(stream.read, write)
    assert client.capabilities == CAP
    assert json.loads(data)["operation"] == "runtime.capabilities"
    assert data.count(b"\n") == 1


def test_uncorrelated_admission_preserves_typed_failure_and_detaches():
    failure = {"api_version": 1, "request_id": None, "ok": False,
               "error": {"code": "unavailable", "retry_after_ms": 1000}}
    stream = Scripted(json.dumps(failure).encode() + b"\n")
    with pytest.raises(CoreClientError) as raised:
        CoreClient.open(stream.read, stream.write, stream.close)
    assert raised.value.code == "unavailable" and raised.value.retry_after_ms == 1000
    assert stream.closed and len(stream.written) == 1


def test_close_detaches_only_the_owned_stream():
    stream = Scripted(response("client:1", CAP))
    client = CoreClient.open(stream.read, stream.write, stream.close)
    client.close()
    with pytest.raises(CoreClientError, match="transport_closed"):
        client.profile()
    assert stream.closed
    assert len(stream.written) == 1
