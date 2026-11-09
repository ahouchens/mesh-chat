"""Private evidence validation and current-incarnation/resource trust boundaries."""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, NativeUnavailable
from mesh_chat.native_path_evidence import candidate, observation, pair_token, validate_observation
from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
from test_native_profile_lifecycle import profile_runtime


def evidence(resource="resource", sequence=1):
    epoch = "a" * 32
    local, remote = candidate("127.0.0.1", 1234, "host", "udp"), candidate("127.0.0.1", 4321, "host", "udp")
    pair = {"token": pair_token(epoch, resource, local, remote), "local": local, "remote": remote,
            "nominated": True, "relay_protocol": "not_applicable", "relay_socket": None,
            "bytes_sent": None, "bytes_received": None, "rtt_ms": None}
    return observation(resource, epoch, sequence, int(time.monotonic() * 1000), status="selected",
                       ice_state="completed", dtls_state="connected", channel_state="open", pair=pair)


@pytest.mark.parametrize("change", ["foreign_resource", "secret", "candidate_secret", "candidate_protocol",
                                   "relay_inference", "boolean_counter", "nan_rtt", "false_availability",
                                   "availability_list", "socket_list"])
def test_backend_evidence_cannot_export_foreign_unbounded_or_inferred_information(change):
    value = evidence()
    if change == "foreign_resource": value["resource"] = "replacement"
    elif change == "secret": value["sdp"] = "credentials must never leave backend"
    elif change == "candidate_secret": value["pair"]["local"]["password"] = "private"
    elif change == "candidate_protocol": value["pair"]["local"]["protocol"] = "https"
    elif change == "relay_inference": value["pair"]["relay_protocol"] = "tls"
    elif change == "boolean_counter": value["application"]["enqueued_bytes"] = True
    elif change == "nan_rtt": value["pair"]["rtt_ms"] = float("nan")
    elif change == "availability_list": value["availability"] = []
    elif change == "socket_list": value["pair"]["relay_socket"] = ["local", "remote", "protocol"]
    else: value["availability"]["pair_bytes"] = True
    with pytest.raises(NativeUnavailable):
        validate_observation(value, "resource")


@pytest.fixture
def inspection(profile_runtime):
    create, native = profile_runtime
    service = create()
    service.create_profile("Synthetic inspector")
    physical = service._native_resources.reserve("current")
    service._native_webrtc_live.add("current")
    native.close = lambda _: None
    sequence = 0
    def inspect(_):
        nonlocal sequence
        sequence += 1
        return json.dumps({"ok": True, "result": evidence(physical, sequence)})
    native.pathEvidence = inspect
    return service, native, physical


def test_private_inventory_and_evidence_bind_resource_profile_and_owner_without_public_command(inspection):
    service, _, physical = inspection
    inventory = service.native_webrtc_inspection_resources()
    assert inventory["resources"] == [{"logical_session": "current", "physical_resource": physical, "adopted": False}]
    value = service.native_webrtc_path_evidence("current", physical)
    assert value["qualification_only"] and value["resource"] == physical
    assert value["service_incarnation"] == inventory["service_incarnation"]
    assert value["profile_incarnation"] == inventory["profile_incarnation"]
    assert not value["adopted"] and not value["attached"] and not value["messaging_ready"]
    assert value["valid_for_ms"] == 2000
    assert value["pair"]["bytes_sent"] is None and not value["availability"]["pair_bytes"]
    assert "native_webrtc_path_evidence" not in service.COMMANDS
    assert "native_webrtc_inspection_resources" not in service.COMMANDS
    assert not inventory["host_accounting"]["complete"]
    assert inventory["host_accounting"]["reserved_count"] is None


def accounting():
    counts = dict(capacity=16, reserved_count=2, creating_count=1, allocated_count=2, active_count=1, retiring_count=1)
    return {"v": 1, "complete": True, "semantics": "native_allocation_leases", **counts,
            "availability": dict.fromkeys(counts, True)}


def test_inventory_keeps_actual_native_disposal_reservation_counts_separate_from_live_service_rows(inspection):
    service, native, _ = inspection
    value = accounting()
    native.resourceAccounting = lambda: json.dumps({"ok": True, "result": value})
    result = service.native_webrtc_inspection_resources()
    assert len(result["resources"]) == 1
    assert result["host_accounting"] == value
    assert result["host_accounting"]["retiring_count"] == 1
    assert "resourceAccounting" not in service.COMMANDS


@pytest.mark.parametrize("change", ["unavailable_zero", "lying_complete", "secret", "inconsistent", "boolean_count", "over_budget"])
def test_accounting_cannot_claim_unknown_zeros_or_export_unbounded_host_fields(inspection, change):
    service, native, _ = inspection
    value = accounting()
    if change == "unavailable_zero": value["availability"]["reserved_count"] = False
    elif change == "lying_complete": value["complete"] = False
    elif change == "secret": value["sdp"] = "must-not-export"
    elif change == "inconsistent": value["allocated_count"] = 0
    elif change == "boolean_count": value["reserved_count"] = True
    else: value["capacity"] = 17
    native.resourceAccounting = lambda: json.dumps({"ok": True, "result": value})
    with pytest.raises(NativeUnavailable):
        service.native_webrtc_inspection_resources()


def test_windows_empty_lease_inventory_reports_complete_physical_accounting():
    host = WindowsNativeWebRTCHost(lambda *_: None)
    try:
        value = json.loads(host.resourceAccounting())["result"]
        assert value["complete"] and value["retiring_count"] == 0
        assert value["availability"]["retiring_count"]
        assert value["reserved_count"] == value["creating_count"] == value["allocated_count"] == 0
    finally:
        host.shutdown()


@pytest.mark.parametrize("change", ["physical", "incarnation", "identity", "host", "shutdown"])
def test_resource_or_incarnation_change_during_sample_denies_old_observation(inspection, change):
    service, native, physical = inspection
    original = native.pathEvidence
    def inspect(resource):
        result = original(resource)
        if change == "physical": service._native_resources.release("current", physical)
        elif change == "incarnation": service._runtime_incarnation = uuid4().hex
        elif change == "identity": service._identity = RNS.Identity()
        elif change == "host": service._native_host = SimpleNamespace(close=lambda _: None)
        else: service._shutdown.set()
        return result
    native.pathEvidence = inspect
    with pytest.raises(NativeUnavailable):
        service.native_webrtc_path_evidence("current", physical)


def test_adopted_resource_revocation_during_sample_denies_live_path_success(inspection):
    service, native, physical = inspection
    current = [True]
    service._native_webrtc_profile_sessions["profile"] = "current"
    service._native_carrier_authorized = lambda _: current[0]
    original = native.pathEvidence
    def inspect(resource):
        result = original(resource)
        current[0] = False
        return result
    native.pathEvidence = inspect
    with pytest.raises(ContactNotApproved):
        service.native_webrtc_path_evidence("current", physical)


def test_cached_or_replaced_adapter_sample_is_not_a_new_observation(inspection):
    service, native, physical = inspection
    result = native.pathEvidence(physical)
    native.pathEvidence = lambda _: result
    assert service.native_webrtc_path_evidence("current", physical)["sample_sequence"] == 1
    with pytest.raises(NativeUnavailable, match="stale"):
        service.native_webrtc_path_evidence("current", physical)


@pytest.mark.parametrize("protocol", ["udp", "tcp", "tls"])
def test_windows_turn_protocol_comes_from_actual_selected_transport_and_ssl_socket(protocol):
    from aioice.turn import TurnClientTcpProtocol, TurnClientUdpProtocol, TurnTransport
    kind = TurnClientUdpProtocol if protocol == "udp" else TurnClientTcpProtocol
    inner = object.__new__(kind)
    values = {"ssl_object": object() if protocol == "tls" else None,
              "sockname": ("192.0.2.1", 1234), "peername": ("192.0.2.2", 443)}
    inner.transport = SimpleNamespace(get_extra_info=lambda key: values.get(key))
    transport = object.__new__(TurnTransport)
    transport._TurnTransport__inner_protocol = inner
    actual, socket = WindowsNativeWebRTCHost._relay_socket(transport)
    assert actual == protocol
    assert socket == {"local": {"address": "192.0.2.1", "port": 1234},
                      "remote": {"address": "192.0.2.2", "port": 443}, "protocol": protocol}


def test_unobserved_relay_transport_is_unknown_even_when_tls_was_advertised():
    assert WindowsNativeWebRTCHost._relay_socket(SimpleNamespace(turn_url="turns:advertised")) == ("unknown", None)
