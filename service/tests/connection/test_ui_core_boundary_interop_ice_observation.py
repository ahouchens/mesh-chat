"""Synthetic packet evidence only; never native ICE acceptance."""

import hashlib
import json
import socket
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_ice_packets as packets


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


TARGET = {"local_ufrag_sha256": digest("local123"), "remote_ufrag_sha256": digest("remote456")}


def attribute(kind, value):
    return struct.pack("!HH", kind, len(value)) + value + b"\0" * (-len(value) % 4)


def datagram(kind=1, *, username="remote456:local123", transaction=b"a" * 12, reverse=False,
             port=50000, malformed=False):
    attributes = attribute(6, username.encode()) if kind == 1 and username else b""
    if kind == 0x111:
        attributes = attribute(9, b"\0\0\x04\x57")
    stun = struct.pack("!HHI", kind, len(attributes) + int(malformed), 0x2112A442) + transaction + attributes
    source, destination = bytes([198, 18, 1, 2]), bytes([203, 0, 113, 1])
    sport, dport = port, 51000
    if reverse:
        source, destination, sport, dport = destination, source, dport, sport
    udp = struct.pack("!HHHH", sport, dport, 8 + len(stun), 0) + stun
    return b"\x45\0" + struct.pack("!H", 20 + len(udp)) + b"\0\0\0\0\x40\x11\0\0" + source + destination + udp


def test_exact_generation_request_response_and_retransmission_counts_hide_private_data():
    capture = packets.IcePackets()
    capture.observe(datagram(), "egress")
    capture.observe(datagram(), "egress")
    capture.observe(datagram(0x101, reverse=True), "ingress")
    capture.observe(datagram(username="local123:remote456", reverse=True, transaction=b"b" * 12), "ingress")
    capture.observe(datagram(0x111, transaction=b"b" * 12), "egress")
    result = capture.snapshot(TARGET)
    assert result["availability"] == "selected"
    assert result["egress"] == {"requests": 2, "transactions": 1, "success_responses": 0, "error_responses": 1}
    assert result["ingress"] == {"requests": 1, "transactions": 1, "success_responses": 1, "error_responses": 0}
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in (*TARGET.values(), "local123", "remote456", "203.0.113", "50000"))


def test_foreign_generation_discovery_and_wrong_flow_response_are_not_correlated():
    capture = packets.IcePackets()
    capture.observe(datagram(username="foreign1:foreign2", transaction=b"f" * 12), "egress")
    capture.observe(datagram(username=None, transaction=b"c" * 12), "egress")
    capture.observe(datagram(), "egress")
    capture.observe(datagram(0x101, reverse=True, port=50001), "ingress")
    result = capture.snapshot(TARGET)
    assert result["egress"]["requests"] == 1
    assert result["ingress"]["success_responses"] == 0


def test_no_correlated_request_is_unavailable_not_zero_network_traffic():
    assert packets.IcePackets().snapshot(TARGET) == packets.unavailable("uncorrelated")


@pytest.mark.parametrize("fault", ["malformed", "fragment", "truncated", "direction", "overflow", "gap", "ambiguous"])
def test_incomplete_or_ambiguous_capture_never_reports_absent_replies(fault):
    capture = packets.IcePackets()
    capture.observe(datagram(), "egress")
    if fault == "malformed": capture.observe(datagram(malformed=True), "egress")
    elif fault == "fragment":
        value = bytearray(datagram()); value[6] = 0x20
        capture.observe(bytes(value), "egress")
    elif fault == "truncated": capture.observe(datagram()[:-1], "egress")
    elif fault == "direction": capture.observe(datagram(), "unknown")
    elif fault == "overflow":
        for index in range(packets.MAX_TRANSACTIONS + 1):
            capture.observe(datagram(transaction=index.to_bytes(12, "big")), "egress")
    elif fault == "gap": capture.invalidate("capture_gap")
    else: capture.observe(datagram(username="changed1:changed2"), "egress")
    assert capture.snapshot(TARGET)["availability"] == "unavailable"


@pytest.mark.parametrize("target", [None, {}, {**TARGET, "extra": 1}, {**TARGET, "local_ufrag_sha256": "RAW"}])
def test_private_correlation_is_strict(target):
    assert packets.IcePackets().snapshot(target)["availability"] == "unavailable"


def test_reply_validator_rejects_extra_fields_and_boolean_counters():
    capture = packets.IcePackets(); capture.observe(datagram(), "egress")
    value = capture.snapshot(TARGET)
    assert packets.validated_snapshot(value) == value
    assert packets.validated_snapshot({**value, "raw_packet": "PRIVATE"}) is None
    value["egress"]["requests"] = True
    assert packets.validated_snapshot(value) is None


class PacketSocket:
    def __init__(self, *, drops=0):
        self.pending = [(datagram(), [], 0, ("mg1234567890h", 0x800, 0)),
                        (datagram(0x101, reverse=True), [], 0, ("mg1234567890h", 0x800, 4))]
        self.drops, self.closed = drops, False
    def recvmsg(self, size):
        assert size == 2048
        if self.pending: return self.pending.pop(0)
        raise BlockingIOError()
    def getsockopt(self, level, option, size):
        assert (level, option, size) == (263, 6, 8)
        return struct.pack("II", 2, self.drops)
    def getsockname(self): return ("mg1234567890h", 3)
    def close(self): self.closed = True


def capture_fixture(monkeypatch, *, drops=0):
    import native_interop_ice_capture as capture
    value = capture.IceCapture()
    value.packet = PacketSocket(drops=drops)
    value.identity = ("mg1234567890h", 11, 12, "mg1234567890")
    monkeypatch.setattr(capture, "link_identity", lambda *args: None)
    return value, value.packet


def test_capture_maps_owned_host_veth_directions_and_closes_descriptor(monkeypatch):
    capture, descriptor = capture_fixture(monkeypatch)
    result = capture.snapshot(TARGET)
    assert result["egress"]["requests"] == result["ingress"]["success_responses"] == 1
    capture.close(); capture.close()
    assert descriptor.closed and capture.packet is None


@pytest.mark.parametrize("fault", ["drops", "identity", "expired", "bytes", "read_error", "truncated"])
def test_capture_gaps_and_limits_close_socket_and_invalidate_counts(monkeypatch, fault):
    capture, descriptor = capture_fixture(monkeypatch, drops=int(fault == "drops"))
    if fault == "identity": descriptor.getsockname = lambda: ("foreign", 3)
    elif fault == "expired": capture.deadline = 0
    elif fault == "bytes": capture.bytes = 32 * 1024 * 1024
    elif fault == "read_error": descriptor.recvmsg = lambda _: (_ for _ in ()).throw(OSError())
    elif fault == "truncated":
        data, control, _, address = descriptor.pending[0]
        descriptor.pending[0] = data, control, getattr(socket, "MSG_TRUNC", 0x20), address
    assert capture.snapshot(TARGET)["availability"] == "unavailable"
    assert descriptor.closed and capture.packet is None


def test_gateway_existing_cleanup_inventory_carries_only_private_correlation(monkeypatch):
    import native_interop_gateway_runtime as runtime
    client = object.__new__(runtime.GatewayClient)
    requests = []
    client.call = lambda *args, **kwargs: requests.append((args, kwargs)) or packets.unavailable()
    assert client.before_cleanup(ice_correlation=TARGET) == packets.unavailable()
    assert requests == [(("inventory",), {"ice_correlation": TARGET})]
    child = object.__new__(runtime.NativeChild)
    child.requests, child.gateway = 0, SimpleNamespace()
    inventories = []
    child.capture_helpers = lambda gateway: inventories.append(gateway)
    child.ice_capture = SimpleNamespace(snapshot=lambda _: (_ for _ in ()).throw(OSError("PRIVATE")))
    assert child.dispatch({"op": "inventory", "ice_correlation": TARGET}) == packets.unavailable()
    assert inventories == [child.gateway] and child.requests == 1
    assert child.dispatch({"op": "inventory", "ice_correlation": {"raw": "PRIVATE"}}) == packets.unavailable()


def test_broker_timeout_is_a_cleanup_obligation_not_clean_unavailable(monkeypatch):
    import native_interop_ice_capture as capture
    gateway = SimpleNamespace(host="mg1234567890h", token="mg1234567890",
        identities={"mg1234567890h": {"ifindex": 11, "link_index": 12}})
    monkeypatch.setattr(capture, "acquire_socket", lambda _: (_ for _ in ()).throw(capture.BrokerCleanupUnproven()))
    value = capture.IceCapture.start(gateway)
    assert value.cleanup_failed and value.snapshot(TARGET)["availability"] == "unavailable"


def test_optional_socket_close_failure_still_closes_existing_gateway_pipes():
    import native_interop_gateway_runtime as runtime
    child = object.__new__(runtime.NativeChild)
    child.pid, child.closed, child.result = 1, True, {"cleanup": "passed", "code": 0}
    closed = []
    child.ice_capture = SimpleNamespace(close=lambda: (_ for _ in ()).throw(OSError("socket")))
    child.selector = SimpleNamespace(close=lambda: closed.append("selector"))
    child.process = SimpleNamespace(wait=lambda **_: None, returncode=0,
        stdin=SimpleNamespace(close=lambda: closed.append("stdin")),
        stdout=SimpleNamespace(close=lambda: closed.append("stdout")))
    with pytest.raises(OSError): child.close()
    assert closed == ["selector", "stdin", "stdout"]


def test_packet_probe_uses_synthetic_binding_with_fixed_nonqualifying_scope():
    import native_interop_ice_probe as probe
    assert len(probe.TRANSACTION) == 12
    kind, transaction, pair = packets._binding(probe.request())
    assert kind == 1 and transaction == probe.TRANSACTION and len(pair) == 2


def selected_sdp_summary():
    counts = {"total": 1, "types": {"host": 1, "srflx": 0, "prflx": 0, "relay": 0, "unknown": 0},
              "protocols": {"udp": 1, "tcp": 0, "unknown": 0},
              "families": {"ipv4": 1, "ipv6": 0, "mdns": 0, "unknown": 0}}
    return {"availability": "selected", "local": counts, "remote": counts, "correlation": dict(TARGET)}


@pytest.mark.parametrize("fault", [None, "malformed", "foreign_retirement", "gateway_failure"])
def test_actual_failure_report_strips_digests_and_uses_one_existing_gateway_inventory(
        tmp_path, monkeypatch, capsys, fault):
    import native_interop_controller as controller
    from test_ui_core_boundary_interop_controller import run_negotiate_report
    calls, statuses = [], []
    capture = packets.IcePackets(); capture.observe(datagram(), "egress")
    def before_cleanup(**kwargs):
        calls.append(kwargs)
        if fault == "gateway_failure": raise RuntimeError("PRIVATE")
        return capture.snapshot(kwargs.get("ice_correlation"))
    gateway = SimpleNamespace(ready=lambda _: None, coverage=lambda _: None, before_cleanup=before_cleanup)
    original_main = controller.main
    monkeypatch.setattr(controller, "main", lambda: original_main(gateway=gateway))
    def status(operation):
        statuses.append(operation)
        value = selected_sdp_summary()
        if fault == "malformed": value["extra"] = "PRIVATE"
        return {"operation_id": operation, "state": "awaiting_approval" if len(statuses) == 1 else "retired",
                "retirement": {"phase": "gathering" if fault == "foreign_retirement" else "checking",
                    "event": "tick", "reason": "phase_timeout"}, "ice_diagnostic": value}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement", status_reply=status,
        stats_reply=lambda: {"data_channel_state": "connecting", "ice_connection_state": "failed",
            "ice_gathering_state": "complete"},
        inventory_reply=lambda: {"service_incarnation": "s", "profile_incarnation": "p",
            "resources": [{"logical_session": "PRIVATE_LOGICAL", "physical_resource": "PRIVATE_PHYSICAL"}]})
    assert run.exit_code == 1 and run.record["error_code"] == "supervisor_pairing_retired"
    assert run.events == ["settings", "receive", "begin_answer", "status", "inventory", "stats", "status"]
    if fault in ("malformed", "foreign_retirement"):
        assert "pairing_ice" not in run.record and "pairing_ice_packets" not in run.record
        assert calls == [{}]
    else:
        assert calls == [{"ice_correlation": TARGET}]
        assert run.record["pairing_ice"]["gathering"] == {"first": "complete", "last": "complete"}
        if fault == "gateway_failure": assert run.record["cleanup_failed"]
        else: assert run.record["pairing_ice_packets"] == capture.snapshot(TARGET)
    assert all(secret not in run.output for secret in (*TARGET.values(), "PRIVATE"))


def test_unrelated_error_or_changed_pairing_cannot_reuse_ice_diagnostic():
    import native_interop_controller as controller
    from native_interop_pairing_ice import PairingIceObservation, RETIREMENT
    instance = controller.Controller("android", None, None, None, {}, workload="full")
    instance.pairing, instance.phase = "operation", "direct_supervisor_owned_pairing_windows"
    observed = instance._pairing_ice = PairingIceObservation(instance.pairing, instance.phase)
    error = controller.PeerFailure("supervisor_pairing_retired")
    observed.bind_failure(error, {"ice_diagnostic": selected_sdp_summary()}, RETIREMENT)
    instance._operation_failure = error, "pairing_status"
    assert instance.failure_pairing_ice(error, private=True) == TARGET
    assert instance.failure_pairing_ice(RuntimeError()) == {}
    instance.pairing = "other"
    assert instance.failure_pairing_ice(error) == {}


def test_gathering_stats_of_replacement_resource_are_not_attributed_to_original():
    from native_interop_pairing_ice import PairingIceObservation, RETIREMENT
    observed = PairingIceObservation("operation", "phase")
    inventory = {"service_incarnation": "service", "profile_incarnation": "profile"}
    resource = {"logical_session": "logical", "physical_resource": "physical"}
    observed.observe_stats(inventory, resource, {"ice_gathering_state": "gathering"})
    observed.observe_stats(inventory, {**resource, "physical_resource": "replacement"}, {"ice_gathering_state": "complete"})
    observed.bind_failure(RuntimeError(), {"ice_diagnostic": selected_sdp_summary()}, RETIREMENT)
    assert observed.public()["pairing_ice"]["gathering"] is None
