"""Kernel command/counter component checks; never actual impairment evidence."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_faults as faults


def row(local="0F02000A:C350", remote="026433C6:0D96", inode="1234"):
    return f" 0: {local} {remote} 01 00000000:00000000 00:00000000 00000000 10053 0 {inode} 2 0\n"


def test_kernel_socket_correlates_exact_owned_inode_and_remote_turn_flow():
    value = faults.owned_socket("header\n" + row(), {"1234"}, {"198.51.100.2"}, 3478)
    assert value == {"local": "10.0.2.15", "local_port": 50000, "remote": "198.51.100.2", "remote_port": 3478, "inode": "1234"}


@pytest.mark.parametrize("fault", ["other_inode", "other_ip", "other_port", "ambiguous", "unconnected_without_flow"])
def test_advertised_turn_server_or_unowned_socket_cannot_identify_a_kernel_path(fault):
    text, inodes, addresses, port = "header\n" + row(), {"1234"}, {"198.51.100.2"}, 3478
    if fault == "other_inode": inodes = {"5678"}
    elif fault == "other_ip": addresses = {"192.0.2.2"}
    elif fault == "other_port": port = 443
    elif fault == "ambiguous": text += row(inode="5678"); inodes.add("5678")
    else: text = "header\n" + row(remote="00000000:0000")
    with pytest.raises(ValueError): faults.owned_socket(text, inodes, addresses, port)


def test_unconnected_udp_requires_actual_kernel_conntrack_and_own_bound_port():
    flow = "ipv4 2 udp 17 29 src=10.0.2.15 dst=198.51.100.2 sport=50000 dport=3478 src=198.51.100.2 dst=10.0.2.15 sport=3478 dport=50000"
    value = faults.owned_socket("header\n" + row(local="00000000:C350", remote="00000000:0000"), {"1234"}, {"198.51.100.2"}, 3478, flow)
    assert value["local"] == "10.0.2.15" and value["inode"] == "1234"
    with pytest.raises(ValueError):
        faults.owned_socket("header\n" + row(remote="00000000:0000"), {"1234"}, {"198.51.100.2"}, 3478,
                            flow.replace("sport=50000", "sport=50001"))


def test_ipv4_mapped_ipv6_kernel_tcp_tuple_is_decoded_without_candidate_inference():
    assert faults.ipv4_proc("0000000000000000FFFF0000026433C6:01BB") == ("198.51.100.2", 443)


@pytest.mark.parametrize("raw", ["garbage", "0000:FFFF", "GG000000:0001", "00000000:99999"])
def test_malformed_kernel_socket_data_is_not_a_path(raw):
    with pytest.raises(ValueError): faults.ipv4_proc(raw)


def kernel_fixture(protocol="udp"):
    value = object.__new__(faults.AndroidKernelPath)
    value.protocol = protocol
    value.ip_protocol = "17" if protocol == "udp" else "6"
    value.device, value.ifb, value.uid, value.rule = "wlan0", "mci12345678", "10053", "mesh-ci-test"
    value.socket = {"local": "10.0.2.15", "local_port": 50000, "remote": "198.51.100.2", "remote_port": 3478, "inode": "1234"}
    value._installed, value._blocked = [], False
    return value


def test_declared_netem_profile_matches_selected_tuple_both_directions_and_preserves_point_one_percent(monkeypatch):
    value = kernel_fixture()
    commands = []
    monkeypatch.setattr(value, "command", lambda *args: commands.append(args))
    monkeypatch.setattr(value, "counters", lambda: {})
    value.install()
    profiles = [args for args in commands if "netem" in args]
    assert len(profiles) == 2
    assert all(args[-7:] == ("delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%") for args in profiles)
    filters = [args for args in commands if args[:2] == ("tc", "filter")]
    assert len(filters) == 2 and all("198.51.100.2/32" in args and "10.0.2.15/32" in args and "50000" in args for args in filters)


@pytest.mark.parametrize("protocol", ["tcp", "tls"])
def test_selected_tcp_and_tls_negative_control_blocks_actual_tcp_tuple_not_udp(monkeypatch, protocol):
    value = kernel_fixture("tcp")
    commands = []
    monkeypatch.setattr(value, "require_current", lambda: None)
    monkeypatch.setattr(value, "command", lambda *args: commands.append(args))
    value.block()
    args = commands[0]
    assert args[:5] == ("iptables", "-I", "OUTPUT", "1", "-p")
    assert args[5] == "tcp" and "--uid-owner" in args and "10053" in args and "50000" in args
    assert "udp" not in args


def test_counter_parser_requires_actual_netem_handle_not_arbitrary_command_success():
    text = "qdisc netem 30: parent 1:3 limit 1000 delay 75ms 10ms loss 0.1%\n Sent 10000 bytes 100 pkt (dropped 2, overlimits 0 requeues 0)\n"
    assert faults.netem_counter(text, "30:") == {"bytes": 10000, "packets": 100, "dropped": 2}
    with pytest.raises(ValueError): faults.netem_counter(text, "40:")


def test_zero_observed_random_loss_is_reported_truthfully_after_actual_routed_kernel_packets(monkeypatch):
    value = kernel_fixture()
    value.before = {direction: {"bytes": 0, "packets": 0, "dropped": 0} for direction in ("egress", "ingress")}
    monkeypatch.setattr(value, "counters", lambda: {direction: {"bytes": 100, "packets": 2, "dropped": 0} for direction in ("egress", "ingress")})
    report = value.report()
    assert report["loss_percent_each_way"] == 0.1 and report["loss_observed"] is False
    assert report["added_nominal_rtt_ms"] == 150


def test_kernel_fault_cleanup_retains_failed_exact_rule_for_later_retry(monkeypatch):
    value = kernel_fixture()
    value._installed = ["ifb", "egress", "ingress"]
    calls = []
    def command(*args):
        calls.append(args)
        if args[-1] == "ingress": raise RuntimeError("simulated failed rule deletion")
    monkeypatch.setattr(value, "command", command)
    with pytest.raises(RuntimeError, match="cleanup is incomplete"): value.close()
    assert value._installed == ["ingress"]
    monkeypatch.setattr(value, "command", lambda *args: None)
    value.close()
    assert value._installed == []
