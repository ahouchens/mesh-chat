"""Public pairing request/authority gates; real actor cases require C's hooks."""
from dataclasses import replace

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.requests import COMPONENT_OPERATIONS, PAIRING_INTENT_OPERATIONS, parse_request
from mesh_chat.core_api.session import CoreSession, Grant, Ports
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_core_messages import host
from test_pairing_runtime import native_pairing
from test_core_sdk_distribution import installed_consumer, run_consumer


def value(operation, **params):
    request = {"api_version": 1, "request_id": "pairing:1", "operation": operation,
               "params": {"profile": "p" * 64, **params}}
    if operation != "peer.pairing_query":
        request["idempotency_key"] = "explicit-pairing-key-0001"
    return request


@pytest.mark.parametrize("params", [
    {"role": "offer", "pairing_code": "unrequested-code"}, {"role": "answer"},
    {"role": "answer", "pairing_code": ""}, {"role": "answer", "pairing_code": "é" * 1025},
    {"role": "answer", "pairing_code": "\ud800"}, {"role": []}, {"role": True},
    {"role": "offer", "allow_direct_ip_disclosure": 1}, {"role": "offer", "allow_direct_ip_disclosure": None},
    {"role": "offer", "caller": "forged-owner"}, {"role": "offer", "operation_id": "forged-operation"},
    {"role": "offer", "sdp": "unrequested-sdp"}, {"role": "offer", "vault_key": "unrequested-key"},
])
def test_pairing_begin_rejects_invalid_consent_code_and_invented_authority(params):
    with pytest.raises(ApiFailure, match="invalid_request"):
        parse_request(value("peer.pairing_begin", **params), COMPONENT_OPERATIONS)


@pytest.mark.parametrize("operation", ["peer.pairing_begin", "peer.pairing_cancel"])
def test_begin_and_cancel_require_caller_keys_at_the_parser(operation):
    request = value(operation, **({"role": "offer"} if operation.endswith("begin") else {"pairing": "q" * 64}))
    del request["idempotency_key"]
    with pytest.raises(ApiFailure, match="invalid_request"):
        parse_request(request, COMPONENT_OPERATIONS)


def test_ordinary_unbound_host_advertises_no_pairing_actor_and_performs_no_effect(host):
    service = host()
    stream = bind_service_stream(service, lambda: Grant("sdk-owner", frozenset({"observe", "approve"}), ("local",)))
    def invoke(request): return decode_frame(stream.exchange(encode_frame(request)))
    caps = invoke({"api_version": 1, "request_id": "pairing:1", "operation": "runtime.capabilities", "params": {}})
    assert not set(PAIRING_INTENT_OPERATIONS) & set(caps["result"]["operations"])
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    for operation in PAIRING_INTENT_OPERATIONS:
        params = {"role": "offer"} if operation.endswith("begin") else {"pairing": "q" * 64}
        assert invoke(value(operation, **params))["error"]["code"] == "unsupported_operation"
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before


def test_actual_actor_without_durable_cancellation_hook_is_not_public(native_pairing, monkeypatch):
    create, _ = native_pairing
    service, _, created, _, _, _ = create()
    monkeypatch.setattr(service, "native_pairing_public_intents", False, raising=False)
    stream = bind_service_stream(service, lambda: Grant("sdk-owner", frozenset({"observe", "approve"}), ("local",)))
    caps = decode_frame(stream.exchange(encode_frame({"api_version": 1, "request_id": "pairing:1", "operation": "runtime.capabilities", "params": {}})))
    assert not set(PAIRING_INTENT_OPERATIONS) & set(caps["result"]["operations"])
    assert not created and not service.store.list("api_pairing_intent")


@pytest.mark.parametrize("operation", PAIRING_INTENT_OPERATIONS)
def test_every_pairing_request_rechecks_approve_before_calling_a_bound_port(operation):
    class Effects:
        def begin(self, *_): pytest.fail("denied begin reached actor")
        def query(self, *_): pytest.fail("denied query disclosed admission code")
        def cancel(self, *_): pytest.fail("denied cancel reached actor")
    grants = [Grant("sdk-owner", frozenset({"observe", "approve"}), ("local",))]
    session = CoreSession(lambda: grants[0], object(), handle_key=b"k" * 32, ports=Ports(pairing_intents=Effects()))
    caps = session.request({"api_version": 1, "request_id": "pairing:1", "operation": "runtime.capabilities", "params": {}})
    profile = caps["result"]["profiles"][0]
    grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    request = value(operation, **({"role": "offer"} if operation.endswith("begin") else {"pairing": "q" * 64}))
    request["params"]["profile"] = profile
    assert session.request(request)["error"]["code"] == "forbidden"


def test_installed_sdk_on_unbound_real_host_never_writes_a_pairing_mutation(host, installed_consumer):
    service = host()
    stream = bind_service_stream(service, lambda: Grant("sdk-owner", frozenset({"observe", "approve"}), ("local",)))
    requests = []
    class Recorded:
        def exchange(self, frame):
            requests.append(decode_frame(frame)["operation"])
            return stream.exchange(frame)
        def close(self):
            stream.close()
    report = run_consumer(installed_consumer, service, "--pairing-unsupported", session=Recorded())
    assert report["sdk_only"] and report["pairing_refused"]
    assert requests == ["runtime.capabilities"]
    assert service.store.list("api_pairing_intent") == service.store.list("api_pairing_quota") == []
