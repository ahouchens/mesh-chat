"""Kernel command/counter component checks; never actual impairment evidence."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_faults as faults
from native_interop_diagnostics import (NEGATIVE_CONTROL_REASONS, NegativeControlDiagnostics,
    negative_control_error, negative_control_observation, negative_control_stage)


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
    value.endpoint_mode = False  # Exercise the retained exact-flow UDP branch.
    value.uid_udp_mode = False
    value.protocol = protocol
    value.ip_protocol = "17" if protocol == "udp" else "6"
    value.device, value.ifb, value.uid, value.rule = "wlan0", "mci12345678", "10053", "mesh-ci-test"
    value.egress_handle, value.ingress_handle = "30:", "40:"
    value.socket = {"local": "10.0.2.15", "local_port": 50000, "remote": "198.51.100.2", "remote_port": 3478, "inode": "1234"}
    value._installed, value._blocked = [], False
    return value


def udp_link_fixture(monkeypatch):
    value = kernel_fixture()
    value.uid_udp_mode, value.endpoint_mode = True, False
    value.pid, value._qdisc_before = "123", "qdisc noqueue 0: root refcnt 2"
    value.filter_prio = 12345
    value.target_kind, value.target_material, value.rule_count = "uid_udp_all_destinations", ["10053", "udp"], 2
    value._drop_rules = []
    value._negative_diagnostics = None
    state = SimpleNamespace(commands=[], ifb=False, alias=False, root="default", ingress=False, filter=False, rules={},
        egress_packets=0, ingress_packets=0, failure=None, pid="123", uid="10053", resource=True,
        route4="default via 10.0.2.2 dev wlan0 table main\n")
    value.peer = SimpleNamespace(APP="PRIVATE_APP", _adb=lambda *_: state.pid)
    def check_scope():
        if not state.resource: raise ValueError("PRIVATE_STALE_RESOURCE")
    monkeypatch.setattr(value, "_check_scope", check_scope)
    def command(*args):
        state.commands.append(args)
        if args == ("ip", "-o", "link", "show"):
            return ("1: lo: <LOOPBACK,UP> mtu 65536\n2: wlan0: <BROADCAST,UP> mtu 1500\n"
                    + (f"3: {value.ifb}: <BROADCAST,UP> mtu 1500\n" if state.ifb else ""))
        if args == ("ip", "-d", "link", "show", "dev", value.ifb):
            return f"3: {value.ifb}: <BROADCAST,UP>\n    ifb" + (f" alias {value.rule}" if state.alias else "") + "\n"
        if args == ("ip", "-4", "route", "show", "table", "all"):
            return state.route4
        if args == ("ip", "-6", "route", "show", "table", "all"): return ""
        if args in (("ip", "-4", "rule", "show"), ("ip", "-6", "rule", "show")):
            return "0: from all lookup local\n100: from all lookup main\n"
        if args == ("cat", "/proc/123/status"):
            return f"Uid:\t{state.uid}\t{state.uid}\t{state.uid}\t{state.uid}\n"
        if args[:2] == ("ip", "link"):
            if args[2] == "add":
                state.ifb = True
                if state.failure == "ifb_collision": raise RuntimeError("PRIVATE_IFB_COLLISION")
            elif args[2] == "del": state.ifb = False
            elif args[2] == "set" and "alias" in args:
                if state.failure == "alias": raise RuntimeError("PRIVATE_ALIAS_FAILURE")
                state.alias = True
            return ""
        if args[:3] == ("tc", "qdisc", "show"):
            device = args[-1]
            if device == value.ifb:
                return "qdisc netem 40: root delay 75ms 10ms loss 0.1%\n" if state.ifb else ""
            return (("qdisc netem 30: root delay 75ms 10ms loss 0.1%" if state.root == "netem"
                     else "qdisc netem 30: root delay 5ms loss 5%" if state.root == "bad_profile"
                     else "qdisc netem 77: root" if state.root == "foreign" else value._qdisc_before)
                    + ("\nqdisc ingress ffff: parent ffff:fff1" if state.ingress else "") + "\n")
        if args[:4] == ("tc", "-s", "qdisc", "show"):
            packets = state.egress_packets if args[-1] == value.device else state.ingress_packets
            handle = "30:" if args[-1] == value.device else "40:"
            return f"qdisc netem {handle} root delay 75ms 10ms loss 0.1%\n Sent {packets * 100} bytes {packets} pkt (dropped 0, overlimits 0 requeues 0)\n"
        if args[:2] == ("tc", "qdisc"):
            if args[2] == "replace" and args[args.index("dev") + 1] == value.device: state.root = "netem"
            elif args[2] == "add":
                state.ingress = True
                if state.failure == "ingress_collision": raise RuntimeError("PRIVATE_INGRESS_COLLISION")
            elif args[2] == "del" and args[-1] == "root": state.root = "default"
            elif args[2] == "del" and args[-1] == "ingress": state.ingress = state.filter = False
            return ""
        if args[:2] == ("tc", "filter"):
            if args[2] == "show":
                return (f"filter protocol all pref {value.filter_prio} matchall action mirred redirect dev {value.ifb}\n"
                        if state.filter is True else "filter protocol all pref 1 u32 action drop\n"
                        if state.filter == "foreign" else
                        f"filter protocol all pref {value.filter_prio} matchall action mirred redirect dev {value.ifb}\n"
                        "filter protocol all pref 7 u32 action drop\n" if state.filter == "mixed" else "")
            if state.failure == "filter": raise RuntimeError("PRIVATE_FILTER_FAILURE")
            assert "protocol" in args and args[args.index("protocol") + 1] == "all"
            assert "matchall" in args and value.ifb in args
            state.filter = True
            return ""
        if args[0] in {"iptables", "ip6tables"}:
            if args[1] == "-I":
                comment = args[args.index("--comment") + 1]
                state.rules[comment] = [args[0], 0]
                if state.failure == "insert_reply": raise RuntimeError("PRIVATE_INSERT_REPLY")
            elif args[1] == "-C":
                assert args[args.index("--comment") + 1] in state.rules
            elif args[1] == "-D": state.rules.pop(args[args.index("--comment") + 1], None)
            elif args[1] == "-nvx":
                return "\n".join(f"1 {count} {count * 100} DROP udp -- * * 0.0.0.0/0 0.0.0.0/0 /* {comment} */"
                    for comment, (family, count) in state.rules.items() if family == args[0])
            return ""
        raise AssertionError(args)
    monkeypatch.setattr(value, "command", command)
    return value, state


def test_whole_link_netem_tracks_created_ifb_and_both_independent_directions(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    assert state.ifb and state.root == "netem" and state.ingress
    profiles = [item for item in state.commands if item[:3] == ("tc", "qdisc", "replace")]
    assert len(profiles) == 2 and all(item[-7:] == ("delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%") for item in profiles)
    state.egress_packets, state.ingress_packets = 7, 9
    assert value.report()["link_scope"] == "isolated_emulator_route"
    assert value.report()["counters"]["egress"]["packets"] == 7
    value.close()
    assert not state.ifb and state.root == "default" and not state.ingress


def test_uid_udp_block_has_exact_ipv4_ipv6_owner_rules_and_counter_delta(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    value.block()
    inserts = [item for item in state.commands if item[0] in {"iptables", "ip6tables"} and item[1] == "-I"]
    assert len(inserts) == 2 and {item[0] for item in inserts} == {"iptables", "ip6tables"}
    assert all("udp" in item and "--uid-owner" in item and "10053" in item and "-d" not in item for item in inserts)
    for entry in state.rules.values(): entry[1] = 3
    assert value.unblock() == 6
    assert not state.rules
    value.close()


def test_uid_udp_partial_insert_reply_removes_exact_possible_rule(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.failure = "insert_reply"
    with pytest.raises(RuntimeError, match="PRIVATE_INSERT_REPLY"):
        value.block()
    assert state.rules == {} and value._drop_rules == [] and value._blocked is False
    value.close()


def test_removed_ingress_redirect_cannot_qualify_block_or_netem_report(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.filter = False
    with pytest.raises(ValueError): value.block()
    with pytest.raises(ValueError): value.report()
    assert state.rules == {}
    with pytest.raises(RuntimeError, match="cleanup is incomplete"): value.close()
    assert state.ingress and "ingress" in value._installed


@pytest.mark.parametrize("change", ["pid", "uid", "resource", "route"])
def test_uid_udp_block_rejects_stale_current_scope_before_drop_rule(monkeypatch, change):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    if change == "pid": state.pid = "456"
    elif change == "uid": state.uid = "10054"
    elif change == "resource": state.resource = False
    else: state.route4 += "default dev tun0 table 100\n"
    with pytest.raises(ValueError): value.block()
    assert not any(item[0] in {"iptables", "ip6tables"} and item[1] == "-I" for item in state.commands)
    value.close()


def test_partial_whole_link_install_rolls_back_only_owned_state(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value._path_diagnostics = faults.NativePathDiagnostics("impaired")
    state.failure = "filter"
    with pytest.raises(RuntimeError, match="PRIVATE_FILTER_FAILURE") as failure:
        value.install()
    assert not state.ifb and state.root == "default" and not state.ingress and value._installed == []
    assert value._path_diagnostics.failure_observation(failure.value) == {
        "scenario": "impaired", "stage": "kernel_link_coverage", "reason": "capability_unavailable"}
    assert value._path_diagnostics.failure_observation(RuntimeError("PRIVATE_FOREIGN")) == {}


def test_ifb_alias_failure_after_creation_uses_prechecked_exact_name_for_cleanup(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    state.failure = "alias"
    with pytest.raises(RuntimeError, match="PRIVATE_ALIAS_FAILURE"):
        value.install()
    assert not state.ifb and value._installed == []


def test_foreign_ifb_collision_after_absence_check_is_never_deleted(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    state.failure = "ifb_collision"
    with pytest.raises(RuntimeError, match="PRIVATE_IFB_COLLISION") as failure:
        value.install()
    assert state.ifb and "ifb" in value._installed
    assert isinstance(failure.value.__cause__, RuntimeError)
    assert getattr(value, "_setup_cleanup_failure", None) is failure.value.__cause__
    assert not any(item[:3] == ("ip", "link", "del") for item in state.commands)


def test_ambiguous_ingress_add_leaves_unknown_qdisc_untouched(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    state.failure = "ingress_collision"
    with pytest.raises(RuntimeError, match="PRIVATE_INGRESS_COLLISION") as failure:
        value.install()
    assert state.ingress and "ingress" in value._installed
    assert isinstance(failure.value.__cause__, RuntimeError)
    assert not any(item[:3] == ("tc", "qdisc", "del") and item[-1] == "ingress" for item in state.commands)


def test_foreign_root_replacement_is_not_deleted_during_cleanup(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.root = "foreign"
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert state.root == "foreign" and "egress" in value._installed


def test_changed_netem_profile_cannot_be_claimed_or_deleted(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.root = "bad_profile"
    with pytest.raises(ValueError): value.report()
    with pytest.raises(RuntimeError, match="cleanup is incomplete"): value.close()
    assert state.root == "bad_profile" and "egress" in value._installed


def test_foreign_ingress_filter_is_not_deleted_during_cleanup(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.filter = "foreign"
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert state.ingress and "ingress" in value._installed


def test_mixed_own_and_foreign_ingress_filters_are_not_deleted(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.filter = "mixed"
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert state.ingress and "ingress" in value._installed


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


def diagnostic_kernel(monkeypatch):
    from subprocess import CalledProcessError
    value = kernel_fixture("tcp")
    observer = value._negative_diagnostics = NegativeControlDiagnostics()
    observer.reset("turn_tcp")
    state = SimpleNamespace(value=value, observer=observer, commands=[], fault=None,
        error=CalledProcessError(17, ["PRIVATE_COMMAND"], output="PRIVATE_OUTPUT", stderr="PRIVATE_STDERR"))
    value.pid, value.addresses, value.port = "123", {"198.51.100.2"}, 3478
    def adb(*args):
        state.commands.append(("adb", *args))
        if state.fault == "process_error": raise state.error
        return "456" if state.fault == "process_changed" else "123"
    value.peer = SimpleNamespace(APP="PRIVATE_APP", _adb=adb)
    def command(*args):
        state.commands.append(args)
        if args[:2] == ("iptables", "-I"):
            if state.fault == "install_error": raise state.error
            return ""
        if args[:2] == ("iptables", "-nvx"):
            if state.fault == "counter_read_error": raise state.error
            if state.fault == "counter_missing": return "PRIVATE_NOT_A_COUNTER"
            text = "1 3 100 DROP tcp -- * * PRIVATE_ENDPOINT PRIVATE_ENDPOINT /* " + value.rule + " */"
            if state.fault == "counter_duplicate": text += "\n" + text
            elif state.fault == "counter_target": text = text.replace("DROP", "ACCEPT")
            elif state.fault == "counter_number": text = text.replace("1 3 100", "1 PRIVATE_NUMBER 100")
            return text
        if args[:2] == ("iptables", "-D"):
            if state.fault == "delete_error": raise state.error
            return ""
        if args[:2] == ("sh", "-c"):
            if state.fault == "socket_read_error": raise state.error
            return "socket:[1234]"
        assert args[0] == "cat"
        if args[1].endswith("tcp6"): return "header\n"
        if state.fault == "socket_missing": return "header\n"
        return "header\n" + row(local="0F02000A:C351" if state.fault == "socket_changed" else "0F02000A:C350")
    monkeypatch.setattr(value, "command", command)
    return state


@pytest.mark.parametrize("point,stage,reason", [
    ("process_error", "kernel_current_process", None),
    ("process_changed", "kernel_current_process", "process_changed"),
    ("socket_read_error", "kernel_current_socket", None),
    ("socket_missing", "kernel_current_socket", None),
    ("socket_changed", "kernel_current_socket", "socket_changed"),
    ("install_error", "kernel_block_install", None),
])
def test_actual_kernel_block_keeps_deepest_stage_and_only_observed_branch_reason(monkeypatch, point, stage, reason):
    state = diagnostic_kernel(monkeypatch)
    state.fault = point
    with pytest.raises(Exception) as failure:
        with negative_control_stage(state.observer, "kernel_block"): state.value.block()
    expected = {"scenario": "turn_tcp", "stage": stage}
    if reason is not None: expected["reason"] = reason
    assert state.observer.failure_observation(failure.value) == expected
    if point.endswith("error"): assert failure.value is state.error
    assert state.value._blocked is False
    assert "PRIVATE" not in repr(expected)


@pytest.mark.parametrize("point,stage,reason", [
    ("counter_read_error", "kernel_counter_read", None),
    ("counter_missing", "kernel_counter_parse", "counter_unavailable"),
    ("counter_duplicate", "kernel_counter_parse", "counter_unavailable"),
    ("counter_target", "kernel_counter_parse", "counter_unavailable"),
    ("counter_number", "kernel_counter_parse", None),
    ("delete_error", "kernel_restore_delete", None),
    ("process_changed", "kernel_restore_current", "current_check_failed"),
    ("socket_changed", "kernel_restore_current", "current_check_failed"),
])
def test_actual_kernel_unblock_preserves_current_check_delete_order_and_new_error_custody(monkeypatch, point, stage, reason):
    state = diagnostic_kernel(monkeypatch)
    state.value.block()
    state.commands.clear()
    state.fault = point
    with pytest.raises(Exception) as failure:
        with negative_control_stage(state.observer, "kernel_unblock"): state.value.unblock()
    expected = {"scenario": "turn_tcp", "stage": stage}
    if reason is not None: expected["reason"] = reason
    assert state.observer.failure_observation(failure.value) == expected
    if point.endswith("error"): assert failure.value is state.error
    if stage == "kernel_restore_current":
        assert str(failure.value) == "The blocked native kernel socket changed before restoration"
    assert state.value._blocked is (stage == "kernel_restore_delete")
    assert state.commands[0] == ("iptables", "-nvx", "-L", "OUTPUT", "--line-numbers")
    assert state.commands[-1] == ("iptables", "-D", "OUTPUT", *state.value.drop_args)
    assert "PRIVATE" not in repr(expected)


def test_unblock_counter_failure_deletes_exact_rule_once_and_close_does_not_repeat(monkeypatch):
    state = diagnostic_kernel(monkeypatch)
    state.value.block()
    state.commands.clear()
    state.fault = "counter_read_error"
    with pytest.raises(type(state.error)) as failure: state.value.unblock()
    assert failure.value is state.error
    assert state.observer.failure_observation(failure.value) == {
        "scenario": "turn_tcp", "stage": "kernel_counter_read"}
    assert state.commands == [
        ("iptables", "-nvx", "-L", "OUTPUT", "--line-numbers"),
        ("iptables", "-D", "OUTPUT", *state.value.drop_args)]
    assert state.value._blocked is False
    state.value.close()
    assert len(state.commands) == 2


def test_unblock_delete_failure_supersedes_counter_error_with_context_and_keeps_rule_owned(monkeypatch):
    state = diagnostic_kernel(monkeypatch)
    state.value.block()
    state.commands.clear()
    original = state.value.command
    def command(*args):
        if args[:2] == ("iptables", "-D"):
            state.commands.append(args)
            raise RuntimeError("PRIVATE_DELETE_ERROR")
        return original(*args)
    monkeypatch.setattr(state.value, "command", command)
    state.fault = "counter_read_error"
    with pytest.raises(RuntimeError, match="PRIVATE_DELETE_ERROR") as failure:
        state.value.unblock()
    assert failure.value.__context__ is state.error
    assert state.observer.failure_observation(failure.value) == {
        "scenario": "turn_tcp", "stage": "kernel_restore_delete"}
    assert state.value._blocked is True
    assert state.commands == [
        ("iptables", "-nvx", "-L", "OUTPUT", "--line-numbers"),
        ("iptables", "-D", "OUTPUT", *state.value.drop_args)]
    state.fault = None
    monkeypatch.setattr(state.value, "command", original)
    state.value.close()
    assert state.value._blocked is False
    assert state.commands[-1] == ("iptables", "-D", "OUTPUT", *state.value.drop_args)


def test_unblock_already_clear_issues_no_kernel_commands(monkeypatch):
    state = diagnostic_kernel(monkeypatch)
    assert state.value.unblock() == 0
    assert state.commands == []


def test_actual_kernel_cleanup_replacement_has_own_literal_reason_and_no_primary_attribution(monkeypatch):
    state = diagnostic_kernel(monkeypatch)
    state.value.block()
    state.fault = "delete_error"
    with pytest.raises(Exception) as primary: state.value.unblock()
    assert primary.value is state.error
    with pytest.raises(RuntimeError) as escaped:
        with negative_control_stage(state.observer, "fault_cleanup"): state.value.close()
    assert escaped.value is not primary.value
    assert str(escaped.value) == "Exact kernel fault cleanup is incomplete"
    assert state.observer.failure_observation(escaped.value) == {
        "scenario": "turn_tcp", "stage": "fault_cleanup", "reason": "cleanup_incomplete"}
    assert state.observer.failure_observation(primary.value) == {}
    assert state.value._blocked is True


def test_actual_kernel_success_retains_same_commands_and_no_failure_evidence(monkeypatch):
    state = diagnostic_kernel(monkeypatch)
    state.value.block()
    assert state.value.unblock() == 3
    state.value.close()
    assert state.value._blocked is False and state.observer._failure is None
    assert len(state.commands) == 11
    assert [args[:2] for args in state.commands if args[0] == "iptables"] == [
        ("iptables", "-I"), ("iptables", "-nvx"), ("iptables", "-D")]


def endpoint_rule_fixture(monkeypatch, *, addresses=("198.51.100.2", "2001:db8::2")):
    value = kernel_fixture("tcp")
    value.endpoint_mode = True
    value.addresses, value.port = addresses, 3478
    value._drop_rules = []
    value._negative_diagnostics = NegativeControlDiagnostics()
    value._negative_diagnostics.reset("turn_tcp")
    state = SimpleNamespace(commands=[], rules={}, failure=None)
    monkeypatch.setattr(value, "require_current", lambda: None)
    def command(*args):
        state.commands.append(args)
        if args[1] == "-I":
            comment = args[args.index("--comment") + 1]
            state.rules[comment] = [args[0], 0]
            if state.failure == "insert_reply": raise RuntimeError("PRIVATE_INSERT_REPLY")
        elif args[1] == "-C":
            comment = args[args.index("--comment") + 1]
            if comment not in state.rules or state.failure == "check": raise RuntimeError("PRIVATE_CHECK")
        elif args[1] == "-D":
            comment = args[args.index("--comment") + 1]
            if state.failure == "delete": raise RuntimeError("PRIVATE_DELETE")
            state.rules.pop(comment)
        elif args[1] == "-nvx":
            if state.failure == "read_once":
                state.failure = None
                raise RuntimeError("PRIVATE_READ")
            if state.failure == "read": raise RuntimeError("PRIVATE_READ")
            return "\n".join(f"1 {count} {count * 20} DROP tcp -- * * PRIVATE PRIVATE /* {comment} */"
                for comment, (family, count) in state.rules.items() if family == args[0])
        return ""
    monkeypatch.setattr(value, "command", command)
    return value, state


def test_endpoint_scope_blocks_every_ipv4_ipv6_turn_destination_and_sums_exact_counters(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch)
    value.block()
    assert len(value._drop_rules) == 2 and len(state.rules) == 2
    inserts = [args for args in state.commands if args[1] == "-I"]
    assert {args[0] for args in inserts} == {"iptables", "ip6tables"}
    for args in inserts:
        assert args[2:4] == ("OUTPUT", "1")
        assert args[args.index("--uid-owner") + 1] == "10053"
        assert args[args.index("--dport") + 1] == "3478"
        assert args[args.index("-d") + 1] in value.addresses
    for item in state.rules.values(): item[1] = 3
    assert value.unblock() == 6
    assert state.rules == {} and value._blocked is False
    assert len([args for args in state.commands if args[1] == "-D"]) == 2


def test_endpoint_insert_reply_failure_still_deletes_possible_exact_rule(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    state.failure = "insert_reply"
    with pytest.raises(RuntimeError, match="PRIVATE_INSERT_REPLY"): value.block()
    assert state.rules == {} and value._drop_rules == [] and value._blocked is False
    assert [args[1] for args in state.commands] == ["-I", "-D", "-nvx"]


def test_endpoint_rejected_insert_confirms_exact_rule_absence(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    original = value.command
    def command(*args):
        if args[1] == "-I":
            state.commands.append(args)
            raise RuntimeError("PRIVATE_INSERT_REJECTED")
        if args[1] == "-D":
            state.commands.append(args)
            raise RuntimeError("PRIVATE_RULE_ABSENT")
        return original(*args)
    monkeypatch.setattr(value, "command", command)
    with pytest.raises(RuntimeError, match="PRIVATE_INSERT_REJECTED"):
        value.block()
    assert state.rules == {} and value._drop_rules == [] and value._blocked is False
    assert [args[1] for args in state.commands] == ["-I", "-D", "-nvx"]


def test_endpoint_insert_check_failure_rolls_back_and_does_not_claim_rule_absence(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    state.failure = "check"
    with pytest.raises(RuntimeError, match="PRIVATE_CHECK"):
        value.block()
    assert [args[1] for args in state.commands] == ["-I", "-C", "-D", "-nvx"]
    assert state.rules == {} and value._blocked is False


def test_endpoint_ambiguous_insert_and_failed_delete_retains_exact_cleanup_ownership(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    original = value.command
    def command(*args):
        if args[1] == "-D":
            state.commands.append(args)
            raise RuntimeError("PRIVATE_DELETE")
        return original(*args)
    monkeypatch.setattr(value, "command", command)
    state.failure = "insert_reply"
    with pytest.raises(RuntimeError, match="PRIVATE_DELETE") as failure:
        value.block()
    assert "PRIVATE_INSERT_REPLY" in str(failure.value.__context__)
    assert value._blocked is True and len(value._drop_rules) == 1
    monkeypatch.setattr(value, "command", original)
    state.failure = None
    value.close()
    assert state.rules == {} and value._blocked is False


def test_endpoint_delete_failure_keeps_exact_rule_for_close_retry(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    value.block()
    state.failure = "read_once"
    original = value.command
    def command(*args):
        if args[1] == "-D":
            state.commands.append(args)
            raise RuntimeError("PRIVATE_DELETE")
        return original(*args)
    monkeypatch.setattr(value, "command", command)
    with pytest.raises(RuntimeError, match="PRIVATE_DELETE") as failure: value.unblock()
    assert "PRIVATE_READ" in str(failure.value.__context__)
    assert value._blocked is True and len(value._drop_rules) == 1
    monkeypatch.setattr(value, "command", original)
    state.failure = None
    value.close()
    assert value._blocked is False and state.rules == {}


def test_endpoint_delete_acknowledgement_without_absence_keeps_cleanup_ownership(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch, addresses=("198.51.100.2",))
    value.block()
    original = value.command
    def command(*args):
        if args[1] == "-D":
            state.commands.append(args)
            return ""
        return original(*args)
    monkeypatch.setattr(value, "command", command)
    with pytest.raises(ValueError, match="remains installed"):
        value.unblock()
    assert value._blocked is True and len(value._drop_rules) == 1
    monkeypatch.setattr(value, "command", original)
    value.close()
    assert state.rules == {} and value._blocked is False


def test_partial_dual_family_insert_reply_failure_rolls_back_both_exact_rules(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch)
    original = value.command
    def command(*args):
        if args[:2] == ("ip6tables", "-I"):
            state.commands.append(args)
            comment = args[args.index("--comment") + 1]
            state.rules[comment] = ["ip6tables", 0]
            raise RuntimeError("PRIVATE_INSERT_REPLY")
        return original(*args)
    monkeypatch.setattr(value, "command", command)
    with pytest.raises(RuntimeError, match="PRIVATE_INSERT_REPLY"):
        value.block()
    assert value._drop_rules == [] and value._blocked is False and state.rules == {}
    assert [args[0] for args in state.commands if args[1] == "-D"] == ["ip6tables", "iptables"]


def test_endpoint_counter_read_failure_preserves_stage_after_exact_dual_rule_deletion(monkeypatch):
    value, state = endpoint_rule_fixture(monkeypatch)
    value.block()
    state.failure = "read_once"
    with pytest.raises(RuntimeError, match="PRIVATE_READ") as failure:
        value.unblock()
    assert value._negative_diagnostics.failure_observation(failure.value) == {
        "scenario": "turn_tcp", "stage": "kernel_counter_read"}
    assert state.rules == {} and value._drop_rules == [] and value._blocked is False
    value.close()


@pytest.mark.parametrize("after", [False, True])
def test_throwing_kernel_observer_cannot_replace_error_or_leak_partial_observation(monkeypatch, after):
    state = diagnostic_kernel(monkeypatch)
    state.fault = "process_changed"
    observe = state.observer.observe
    def broken(*args):
        if after: observe(*args)
        raise ValueError("PRIVATE_OBSERVER")
    monkeypatch.setattr(state.observer, "observe", broken)
    with pytest.raises(ValueError, match="native process changed") as failure: state.value.block()
    assert state.observer.failure_observation(failure.value) == {}
    assert state.value._blocked is False


@pytest.mark.parametrize("value", [None, [], {}, {"scenario": "direct", "stage": "kernel_block"},
    {"scenario": "turn_tcp", "stage": "PRIVATE_UNKNOWN"}, {"scenario": "turn_tcp", "stage": True},
    {"scenario": "turn_tcp", "stage": "kernel_block", "reason": "process_changed"},
    {"scenario": "turn_tcp", "stage": "blocked_receipt", "reason": "PRIVATE_UNKNOWN"},
    {"scenario": "turn_tcp", "stage": "blocked_receipt", "reason": None},
    {"scenario": "turn_tcp", "stage": "blocked_receipt", "reason": 1},
    {"scenario": "turn_tcp", "stage": "kernel_block", "socket": "PRIVATE_SOCKET"}])
def test_negative_projection_rejects_unknown_extra_wrong_type_and_mismatched_reason(value):
    assert negative_control_observation(value) == {}


def test_negative_projection_has_exact_safe_catalog_and_never_parses_exception_text():
    assert set(NEGATIVE_CONTROL_REASONS) == {"kernel_block", "kernel_current_process", "kernel_current_socket",
        "kernel_block_install", "ready_publish", "ready_receive", "blocked_enqueue", "blocked_receipt",
        "checked_receive", "checked_publish", "kernel_unblock", "kernel_counter_read", "kernel_counter_parse",
        "kernel_restore_current", "kernel_restore_delete", "dropped_count", "restored_delivery",
        "recovered_inbound", "recovered_records", "final_observation", "final_evidence", "final_traffic", "fault_cleanup"}
    observer = NegativeControlDiagnostics()
    for scenario in ("turn_tcp", "turn_tls", "impaired"):
        for stage, reasons in NEGATIVE_CONTROL_REASONS.items():
            for reason in (None, *reasons):
                observer.reset(scenario)
                error = ValueError("Authenticated receipt arrived while the selected kernel path was blocked")
                error.reason, error.stage = "PRIVATE_REASON", "PRIVATE_STAGE"
                assert negative_control_error(observer, stage, error, reason) is error
                value = {"scenario": scenario, "stage": stage}
                if reason is not None: value["reason"] = reason
                assert observer.failure_observation(error) == value
                assert observer.failure_observation(ValueError(str(error))) == {}
                selected = negative_control_observation(value)
                assert selected == value and selected is not value
    observer.reset("direct")
    with pytest.raises(ValueError) as failure:
        with negative_control_stage(observer, "final_traffic"): raise ValueError("PRIVATE_TEXT")
    assert observer.failure_observation(failure.value) == {}
