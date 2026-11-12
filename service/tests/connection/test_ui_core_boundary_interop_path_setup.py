"""Fixed-site native path diagnostics; synthetic inputs are never native CI evidence."""

from pathlib import Path
import ipaddress
import json
import shlex
import sys
from types import SimpleNamespace

import pytest


def test_bounded_link_set_accepts_two_independent_devices_and_denied_dummy():
    from native_interop_link_scope import covered_links
    links = json.dumps([
        {"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK", "UP"], "link_type": "loopback", "group": 0},
        {"ifindex": 2, "ifname": "eth0", "flags": ["UP"], "link_type": "ether", "group": 0},
        {"ifindex": 3, "ifname": "wlan0", "flags": ["UP"], "link_type": "ether", "group": 0},
        {"ifindex": 4, "ifname": "dummy0", "flags": ["UP"], "link_type": "ether",
         "linkinfo": {"info_kind": "dummy"}, "group": 0},
    ])
    metadata = {name: (kind, index, index, False, 0) for name, kind, index in
                (("lo", 772, 1), ("eth0", 1, 2), ("wlan0", 1, 3), ("dummy0", 1, 4))}
    selected = covered_links(links, "default dev eth0 table main\n",
        "fe80::/64 dev dummy0 table main\n2001:db8::/64 dev wlan0 table main\n",
        "0: from all lookup local\n100: from all lookup main\n",
        "0: from all lookup local\n100: from all lookup main\n", metadata)
    assert tuple(link["name"] for link in selected["external"]) == ("eth0", "wlan0")
    assert tuple(link["name"] for link in selected["sinks"]) == ("dummy0",)


def test_down_tunnel_details_do_not_reject_live_independent_link():
    from native_interop_link_scope import covered_links, LinkScopeError
    links = json.dumps([
        {"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK", "UP"], "link_type": "loopback", "group": 0},
        {"ifindex": 2, "ifname": "eth0", "flags": ["UP"], "link_type": "ether", "group": 0},
        {"ifindex": 3, "ifname": "tun0", "flags": [], "link_type": "none", "group": 0,
         "linkinfo": {"info_kind": "tun", "info_data": {"mode": "tun"}}},
    ])
    metadata = {"lo": (772, 1, 1, False, 0), "eth0": (1, 2, 2, False, 0),
                "tun0": (65534, 3, 3, False, 0)}
    routes = "default dev eth0 table main\n"
    rules = "0: from all lookup local\n100: from all lookup main\n"
    assert len(covered_links(links, routes, "", rules, rules, metadata)["external"]) == 1
    up = links.replace('"flags": []', '"flags": ["UP"]')
    with pytest.raises(LinkScopeError, match="initial_kind_unproven"):
        covered_links(up, routes, "", rules, rules, metadata)


def test_sysfs_stack_probe_passes_one_quoted_remote_shell_program():
    from native_interop_link_scope import link_metadata
    links = json.dumps([{"ifindex": 2, "ifname": "eth0", "flags": ["UP"],
                         "link_type": "ether", "group": 0}])
    observed = []
    def command(*args):
        if args[:2] == ("sh", "-c"):
            observed.append(args[2])
            assert len(shlex.split(args[2])) == 1
            assert args[2].startswith("'") and args[2].endswith("'")
            return "0"
        return {"type": "1", "ifindex": "2", "iflink": "2", "netdev_group": "0"}[args[1].split("/")[-1]]
    assert link_metadata(command, links)["eth0"] == (1, 2, 2, False, 0)
    assert len(observed) == 1


def test_plain_inventory_handles_captured_erspan_detail_without_json_repair():
    from native_interop_link_scope import inventory, LinkScopeError
    basic = ("1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 group default\\    link/loopback 00\n"
             "2: wlan0: <BROADCAST,UP> mtu 1500 group default\\    link/ether 02\n"
             "3: erspan0@NONE: <BROADCAST> mtu 1450 group default\\    link/ether 00\n")
    details = {
        "lo": "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 group default\n    link/loopback 00\n",
        "wlan0": "2: wlan0: <BROADCAST,UP> mtu 1500 group default\n    link/ether 02\n",
        "erspan0": ("3: erspan0@NONE: <BROADCAST> mtu 1450 group default\n"
                    "    link/ether 00\n    erspan remote any local any okey 0.0.0.0 erspan_index 0\n"),
    }
    observed = []
    def command(*args):
        observed.append(args)
        if args == ("ip", "-o", "link", "show"): return basic
        if args[:5] == ("ip", "-d", "link", "show", "dev"):
            return details[args[5]]
        raise AssertionError(args)
    links = json.loads(inventory(command))
    assert [(item["ifname"], item.get("linkinfo", {}).get("info_kind")) for item in links] == [
        ("lo", None), ("wlan0", None), ("erspan0", "erspan")]
    assert ("ip", "-j", "-d", "link", "show") not in observed
    details["wlan0"] = details["wlan0"].replace("2: wlan0:", "9: wlan0:")
    with pytest.raises(LinkScopeError, match="initial_inventory_unavailable"):
        inventory(command)
    details["wlan0"] = details["wlan0"].replace("9: wlan0:", "2: wlan0:")
    details["wlan0"] += "    dummy peer 3\n"
    with pytest.raises(LinkScopeError, match="initial_kind_unproven"):
        inventory(command)


@pytest.mark.parametrize("change", ["new_up_link", "changed_flags", "unproven_kind"])
def test_plain_inventory_rejects_unstable_or_unproven_up_topology(change):
    from native_interop_link_scope import inventory, covered_links, link_metadata, LinkScopeError
    basic = ("1: lo: <LOOPBACK,UP> mtu 65536 group default\\    link/loopback 00\n"
             "2: wlan0: <BROADCAST,UP> mtu 1500 group default\\    link/ether 02\n")
    details = {"lo": "1: lo: <LOOPBACK,UP> mtu 65536 group default\n    link/loopback 00\n",
               "wlan0": "2: wlan0: <BROADCAST,UP> mtu 1500 group default\n    link/ether 02\n"}
    if change == "new_up_link":
        basic += "3: tun0: <UP> mtu 1500 group default\\    link/none 00\n"
        details["tun0"] = "3: tun0: <UP> mtu 1500 group default\n    link/none 00\n    tun addrgenmode eui64\n"
    elif change == "changed_flags":
        details["wlan0"] = details["wlan0"].replace("BROADCAST,UP", "BROADCAST")
    else:
        details["wlan0"] += "    veth addrgenmode eui64\n"
    def command(*args):
        if args == ("ip", "-o", "link", "show"): return basic
        if args[:5] == ("ip", "-d", "link", "show", "dev"): return details[args[5]]
        if args[0] == "cat":
            name, field = args[1].split("/")[-2:]
            return str({"type": 772 if name == "lo" else 1,
                        "ifindex": {"lo": 1, "wlan0": 2, "tun0": 3}[name],
                        "iflink": {"lo": 1, "wlan0": 2, "tun0": 3}[name],
                        "netdev_group": 0}[field])
        if args[:2] == ("sh", "-c"): return "0"
        raise AssertionError(args)
    if change == "changed_flags":
        with pytest.raises(LinkScopeError, match="initial_inventory_unavailable"):
            inventory(command)
    else:
        links = inventory(command)
        rules = "0: from all lookup local\n100: from all lookup main\n"
        with pytest.raises(LinkScopeError, match="initial_stack_unsupported"):
            covered_links(links, "default dev wlan0 table main\n", "", rules, rules,
                          link_metadata(command, links))


def test_plain_inventory_rejects_link_added_during_detail_reads():
    from native_interop_link_scope import inventory, LinkScopeError
    first = "1: lo: <LOOPBACK,UP> mtu 65536 group default\\    link/loopback 00\n"
    reads = 0
    def command(*args):
        nonlocal reads
        if args == ("ip", "-o", "link", "show"):
            reads += 1
            return first if reads == 1 else first + "2: tun0: <UP> mtu 1500 group default\\    link/none 00\n"
        if args == ("ip", "-d", "link", "show", "dev", "lo"):
            return "1: lo: <LOOPBACK,UP> mtu 65536 group default\n    link/loopback 00\n"
        raise AssertionError(args)
    with pytest.raises(LinkScopeError, match="initial_inventory_unavailable"):
        inventory(command)


def test_plain_inventory_matches_owned_ifb_alias_continuation():
    from native_interop_link_scope import inventory, LinkScopeError
    basic = ("1: lo: <LOOPBACK,UP> mtu 65536 group default\\    link/loopback 00\n"
             "2: mci123: <UP> mtu 1500 group default\\    link/ether 02\\    alias mesh-ci-test\n")
    details = {"lo": "1: lo: <LOOPBACK,UP> mtu 65536 group default\n    link/loopback 00\n",
               "mci123": ("2: mci123: <UP> mtu 1500 group default\n    link/ether 02\n"
                          "    ifb addrgenmode eui64\n    alias mesh-ci-test\n")}
    def command(*args):
        if args == ("ip", "-o", "link", "show"): return basic
        if args[:5] == ("ip", "-d", "link", "show", "dev"): return details[args[5]]
        raise AssertionError(args)
    assert json.loads(inventory(command))[1]["linkinfo"] == {"info_kind": "ifb"}
    details["mci123"] = details["mci123"].replace("alias mesh-ci-test", "alias foreign")
    with pytest.raises(LinkScopeError, match="initial_inventory_unavailable"):
        inventory(command)


def test_plain_inventory_rejects_master_disagreement_between_reads():
    from native_interop_link_scope import inventory, LinkScopeError
    basic = "2: wlan0: <BROADCAST,UP> mtu 1500 master bridge0 group default\\    link/ether 02\n"
    detail = "2: wlan0: <BROADCAST,UP> mtu 1500 group default\n    link/ether 02\n"
    def command(*args):
        if args == ("ip", "-o", "link", "show"): return basic
        if args == ("ip", "-d", "link", "show", "dev", "wlan0"): return detail
        raise AssertionError(args)
    with pytest.raises(LinkScopeError, match="initial_inventory_unavailable"):
        inventory(command)

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_faults as faults
from check_core_ui_boundary import PYTHON_SELECTION


ROW = " 0: 0F02000A:C350 026433C6:0D96 01 00000000:00000000 00:00000000 00000000 10053 0 1234 2 0\n"
OBSERVATION = {"pair": {"relay_protocol": "tcp", "local": {"type": "relay"}}}
TURN = "turn:turn.example:3478?transport=tcp"


@pytest.mark.parametrize("change", [None, "alternate_ipv4", "alternate_ipv6", "policy", "unknown_route", "vpn_link"])
def test_disposable_link_admission_requires_complete_route_coverage(change):
    from native_interop_link_scope import covered_link, LinkScopeError
    links = "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536\n2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n"
    route4 = "default via 10.0.2.2 dev eth0 table main\n10.0.2.0/24 dev eth0 table main\n"
    route6 = "2001:db8::/64 dev eth0 table main\n"
    rule4 = "0: from all lookup local\n100: from all fwmark 0x1/0x1 lookup main\n"
    rule6 = "0: from all lookup local\n100: from all lookup main\n"
    if change == "alternate_ipv4": route4 += "default dev wlan0 table 100\n"
    elif change == "alternate_ipv6": route6 += "default dev wlan0 table 100\n"
    elif change == "policy": rule4 += "200: from all goto 300\n"
    elif change == "unknown_route": route4 += "default PRIVATE_RAW_ROUTE\n"
    elif change == "vpn_link": links += "3: tun0: <POINTOPOINT,UP,LOWER_UP> mtu 1500\n"
    if change is None:
        assert covered_link(links, route4, route6, rule4, rule6) == "eth0"
    else:
        with pytest.raises(LinkScopeError): covered_link(links, route4, route6, rule4, rule6)


def test_native_path_diagnostic_cases_are_in_the_fast_boundary_gate():
    assert "service/tests/connection/test_ui_core_boundary_interop_path_setup.py" in PYTHON_SELECTION


def kernel_boundary(*, point=None, ambiguous=False, tcp_rows=None, fd_links=None, dns_addresses=None,
                    helper_state=None):
    events = []
    class Peer:
        APP = "PRIVATE_APP"
        def _adb(self, *args):
            events.append(args)
            if point == "kernel_emulator_identity" and args[-2:] == ("id", "-u"):
                return "2000"
            if point == "kernel_socket_inventory" and args[-2:] == ("cat", "/proc/123/net/tcp"):
                raise RuntimeError("PRIVATE_COMMAND_AND_ENDPOINT")
            if args[-2:] == ("id", "-u"): return "0"
            if args[-2:] == ("getprop", "ro.kernel.qemu"): return "1"
            if args[-2:] == ("pidof", self.APP): return "123 456" if point == "kernel_process_identity" else "123"
            if args[1:3] == ("sh", "-c"):
                if "command -v nft" in args[3]: return "present"
                if "/etc/iproute2/group" in args[3]: return "0 default"
                if "/sys/class/net/" in args[3]: return "0"
                if "/proc/456/fd/" in args[3]:
                    return "socket:[8888]" if helper_state["kind"] == "external" else ""
                return fd_links if fd_links is not None else "socket:[1234]" + (" socket:[5678]" if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp"):
                if point == "kernel_socket_correlation": return "header\n"
                if tcp_rows is not None: return "header\n" + tcp_rows
                row = ROW.replace("0F02000A:C350", "PRIVATE_INVALID_HEX:C350") if point == "kernel_socket_parse" else ROW
                return "header\n" + row + (ROW.replace("1234", "5678") if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp6"): return "header\n"
            if args[-2:] == ("cat", "/proc/123/status"):
                return "Name: app\n" if point == "kernel_process_uid" else "Uid:\t10053\t10053\t10053\t10053\n"
            if args[-2:] == ("cat", "/proc/456/cmdline"):
                if helper_state is None: return "PRIVATE_APP:other\0"
                if helper_state["kind"] == "exit_on_read":
                    helper_state["alive"] = False
                    raise RuntimeError("Bootstrap helper exited")
                return ("PRIVATE_APP:mesh_bootstrap" if helper_state["kind"] != "spoofed" else
                        "PRIVATE_APP:other") + "\0"
            if args[-2:] == ("cat", "/proc/456/net/tcp"):
                return "header\n" + (ROW.replace("1234", "8888") if helper_state["kind"] == "external" else "")
            if args[-2:] == ("cat", "/proc/456/net/tcp6"): return "header\n"
            if args[1:3] == ("ip", "-j"):
                if point == "link_capability": raise RuntimeError("PRIVATE_COMMAND_OUTPUT")
                links = [
                    {"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK", "UP"],
                     "link_type": "loopback", "group": 0},
                    {"ifindex": 2, "ifname": "eth0", "flags": ["UP"],
                     "link_type": "ether", "group": 0},
                ]
                if point == "link_alternate":
                    links.append({"ifindex": 3, "ifname": "tun0", "flags": ["UP"],
                                  "link_type": "none", "linkinfo": {"info_kind": "tun"}, "group": 0})
                return json.dumps(links)
            if args[-2] == "cat" and args[-1].startswith("/sys/class/net/"):
                name, field = args[-1].split("/")[-2:]
                index = {"lo": 1, "eth0": 2, "tun0": 3}[name]
                return str({"type": 772 if name == "lo" else 1,
                            "ifindex": index, "iflink": index, "netdev_group": 0}[field])
            if args[1:5] == ("pm", "list", "packages", "-U"):
                return "package:OTHER uid:10053\n" if point == "kernel_scope_exclusivity" else "package:PRIVATE_APP uid:10053\n"
            if args[1:5] == ("ps", "-A", "-o", "UID,PID"):
                return "UID PID\n10053 123\n" + ("10053 456\n" if point == "extra_uid_process"
                    or (helper_state is not None and helper_state["alive"]) else "")
            if args[1:4] == ("ip", "route", "get"):
                return "PRIVATE_ROUTE_WITHOUT_DEVICE" if point == "kernel_socket_route" else "198.51.100.2 dev wlan0 src 10.0.2.15"
            if args[1:5] == ("ip", "-o", "link", "show"):
                if point == "link_capability": raise RuntimeError("PRIVATE_COMMAND_OUTPUT")
                return ("1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 group default\\    link/loopback 00\n"
                        "2: eth0: <BROADCAST,UP,LOWER_UP> mtu 1500 group default\\    link/ether 02\n"
                        + ("3: tun0: <POINTOPOINT,UP> mtu 1500 group default\\    link/none 00\n"
                           if point == "link_alternate" else ""))
            if args[1:6] == ("ip", "-d", "link", "show", "dev"):
                name = args[6]
                return {"lo": "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 group default\n    link/loopback 00\n",
                        "eth0": "2: eth0: <BROADCAST,UP,LOWER_UP> mtu 1500 group default\n    link/ether 02\n",
                        "tun0": "3: tun0: <POINTOPOINT,UP> mtu 1500 group default\n    link/none 00\n    tun addrgenmode eui64\n"}[name]
            if args[1:2] in (("iptables-save",), ("ip6tables-save",)):
                return "*filter\nCOMMIT\n"
            if args[1:4] == ("nft", "list", "ruleset"):
                return ""
            if args[1:6] == ("ip", "-4", "route", "show", "table"):
                return "default via 10.0.2.2 dev eth0 table main\n"
            if args[1:6] == ("ip", "-6", "route", "show", "table"):
                return ""
            if args[1:5] == ("ip", "-4", "rule", "show") or args[1:5] == ("ip", "-6", "rule", "show"):
                return "0: from all lookup local\n100: from all lookup main\n" + (
                    "200: from all goto 300\n" if point == "link_policy" else "")
            if args[1:5] == ("tc", "qdisc", "show", "dev"):
                return ("qdisc netem 77: root delay 2ms\n" if point == "link_qdisc" else
                        "qdisc noqueue 0: root refcnt 2\n")
            raise AssertionError("Unexpected private command shape")
    def resolver(*args):
        events.append(("resolver", len(args)))
        if point == "kernel_turn_resolution": raise ValueError("PRIVATE_RESOLVER_OUTPUT")
        return [(None, None, None, None, (address, args[1]))
                for address in (dns_addresses or ("198.51.100.2",))]
    return Peer(), resolver, events


@pytest.mark.parametrize("point,observation,url,stage", [
    ("kernel_relay_evidence", {"pair": {"relay_protocol": "tcp", "local": {"type": "host"}}}, TURN, "kernel_relay_evidence"),
    ("kernel_emulator_identity", OBSERVATION, TURN, "kernel_emulator_identity"),
    ("kernel_turn_url", OBSERVATION, "PRIVATE_INVALID_URL", "kernel_turn_resolution"),
    ("kernel_turn_resolution", OBSERVATION, TURN, "kernel_turn_resolution"),
    ("kernel_process_identity", OBSERVATION, TURN, "kernel_process_identity"),
    ("kernel_socket_inventory", OBSERVATION, TURN, "kernel_socket_inventory"),
    ("kernel_socket_parse", OBSERVATION, TURN, "kernel_socket_parse"),
    ("kernel_socket_correlation", OBSERVATION, TURN, "kernel_socket_correlation"),
    ("kernel_process_uid", OBSERVATION, TURN, "kernel_process_uid"),
    ("kernel_scope_exclusivity", OBSERVATION, TURN, "kernel_scope_exclusivity"),
])
def test_actual_kernel_constructor_labels_exact_failing_check_without_values(point, observation, url, stage):
    peer, resolver, _ = kernel_boundary(point=point)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises((ValueError, RuntimeError)) as caught:
        faults.AndroidKernelPath(peer, observation, url, resolver=resolver, path_diagnostics=diagnostic,
                                resource_check=lambda: True)
    selected = diagnostic.failure_observation(caught.value)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if stage == "kernel_socket_correlation": expected["reason"] = "no_owned_match"
    assert selected == expected
    assert diagnostic.failure_observation(ValueError("PRIVATE_FOREIGN")) == {}
    assert "PRIVATE" not in repr(selected)


def test_multiple_owned_tcp_sockets_are_one_covered_turn_endpoint_scope():
    peer, resolver, _ = kernel_boundary(ambiguous=True)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert path.endpoint_mode and len(path.matches) == 2 and path.socket is None
    assert path.target_kind == "uid_tcp_turn_destination_set" and path.rule_count == 1


def test_impaired_udp_admits_covered_link_without_socket_or_dns_ownership(monkeypatch):
    peer, resolver, events = kernel_boundary()
    def no_socket(*_args, **_kwargs): pytest.fail("UDP must not demand an internal socket")
    monkeypatch.setattr(faults, "owned_socket", no_socket)
    path = faults.AndroidKernelPath(peer, {"pair": {"relay_protocol": "udp", "local": {"type": "relay"}}},
        "turn:turn.example:3478?transport=udp", resolver=resolver, resource_check=lambda: True)
    assert [link["identity"]["name"] for link in path.coverage.links] == ["eth0"]
    assert path.uid_udp_mode and path.target_kind == "uid_udp_all_destinations"
    assert path.rule_count == 2
    assert not any(item[0] == "resolver" or "/fd/" in repr(item) or "/net/udp" in repr(item) for item in events)


@pytest.mark.parametrize("point,reason", [("link_alternate", "initial_stack_unsupported"),
    ("link_policy", "unsupported_policy"), ("link_qdisc", "conflicting_qdisc"),
    ("link_capability", "initial_inventory_unavailable")])
def test_udp_link_admission_failures_publish_only_bounded_reason(point, reason):
    peer, resolver, _ = kernel_boundary(point=point)
    diagnostic = faults.NativePathDiagnostics("impaired")
    with pytest.raises(ValueError) as failure:
        faults.AndroidKernelPath(peer, {"pair": {"relay_protocol": "udp", "local": {"type": "relay"}}},
            "turn:turn.example:3478?transport=udp", resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
    selected = diagnostic.failure_observation(failure.value)
    assert selected == {"scenario": "impaired", "stage": "kernel_link_coverage", "reason": reason}
    assert "PRIVATE" not in repr(selected)


@pytest.mark.parametrize("states,inodes,summary,relation", [
    (("01", "08"), ("1234", "5678"), "one_established_plus_other", "distinct"),
    (("01", "01"), ("1234", "5678"), "multiple_established", "distinct"),
    (("08", "02"), ("1234", "5678"), "no_established", "distinct"),
    (("01", "PRIVATE"), ("1234", "5678"), "unclassifiable", "distinct"),
    (("01", "01"), ("1234", "1234"), "multiple_established", "same"),
])
def test_tcp_endpoint_aggregate_requires_at_least_one_established_owned_match(states, inodes, summary, relation):
    rows = "".join(ROW.replace(" 01 ", f" {state} ").replace("1234", inode)
                   for state, inode in zip(states, inodes))
    peer, resolver, _ = kernel_boundary(tcp_rows=rows, fd_links=" ".join(f"socket:[{inode}]" for inode in inodes))
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    if summary == "no_established":
        with pytest.raises(ValueError) as caught:
            faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                path_diagnostics=diagnostic, resource_check=lambda: True)
        assert diagnostic.failure_observation(caught.value) == {
            "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match"}
    else:
        path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
        assert path.matches and diagnostic.failure_observation(ValueError("PRIVATE_FOREIGN")) == {}


def test_actual_owned_socket_ambiguity_keeps_unrelated_scenario_report_unchanged():
    rows = "header\n" + ROW + ROW.replace("1234", "5678")
    diagnostic = faults.NativePathDiagnostics("turn_udp")
    with pytest.raises(ValueError) as caught:
        faults.owned_socket(rows, {"1234", "5678"}, {"198.51.100.2"}, 3478,
                            path_diagnostics=diagnostic)
    assert diagnostic.failure_observation(caught.value) == {
        "scenario": "turn_udp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches"}


def test_actual_owned_socket_observer_fault_does_not_change_ambiguous_rejection(monkeypatch):
    rows = "header\n" + ROW + ROW.replace("1234", "5678")
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    def broken_observer(*_args, **_kwargs): raise RuntimeError("PRIVATE_OBSERVER")
    monkeypatch.setattr(diagnostic, "observe", broken_observer)
    with pytest.raises(ValueError, match="Selected TURN path lacks one unambiguous own-process kernel socket"):
        faults.owned_socket(rows, {"1234", "5678"}, {"198.51.100.2"}, 3478,
                            path_diagnostics=diagnostic)


def test_tls_multiple_rows_admit_the_established_covered_endpoint():
    rows = ROW + ROW.replace(" 01 ", " 08 ").replace("1234", "5678")
    peer, resolver, _ = kernel_boundary(tcp_rows=rows, fd_links="socket:[1234] socket:[5678]")
    diagnostic = faults.NativePathDiagnostics("turn_tls")
    instance = controller.Controller("android", SimpleNamespace(), None, None, {})
    instance.phase = "turn_tls_authenticated_receipts"
    instance._path_diagnostics = diagnostic
    observation = {"pair": {"relay_protocol": "tls", "local": {"type": "relay"}}}
    path = faults.AndroidKernelPath(peer, observation, "turns:turn.example:3478", resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert len(path.matches) == 1 and instance.failure_native_path(ValueError("PRIVATE_FOREIGN")) == {}


@pytest.mark.parametrize("value", [
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "distinct"},
    {"scenario": "turn_udp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "tcp_state_summary": "multiple_established",
     "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "PRIVATE_STATE", "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "PRIVATE_INODE"},
])
def test_tcp_socket_ambiguity_summary_allowlist_rejects_unrelated_or_private_fields(value):
    assert faults.path_failure_observation(value) == {}


def test_one_established_turn_endpoint_retains_only_private_aggregate_and_no_failure_label():
    peer, resolver, events = kernel_boundary()
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert path.matches == frozenset({("1234", "10.0.2.15", 50000, "198.51.100.2", 3478)})
    assert path.protocol == "tcp" and path.uid == "10053" and path.socket is None
    assert diagnostic.failure_observation(ValueError("PRIVATE_UNRELATED")) == {}
    assert events.count(("resolver", 4)) == 1


def test_host_dns_candidate_set_must_cover_observed_guest_owned_turn_endpoint():
    peer, resolver, _ = kernel_boundary(dns_addresses=("203.0.113.7",))
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises(ValueError, match="outside the scoped TURN") as caught:
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
    assert diagnostic.failure_observation(caught.value) == {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "uncovered_endpoint"}


def test_external_owned_tcp_on_different_port_is_not_silently_ignored():
    row = ROW.replace("026433C6:0D96", "097100CB:01BB")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW + row)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises(ValueError, match="outside the scoped TURN") as caught:
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
    assert diagnostic.failure_observation(caught.value)["reason"] == "uncovered_endpoint"


def test_exact_known_mailbox_endpoint_and_guest_loopback_do_not_widen_turn_rule():
    mailbox = ROW.replace("026433C6:0D96", "026433C6:01BB").replace("1234", "5678")
    loopback = ROW.replace("026433C6:0D96", "0100007F:4E20").replace("1234", "9012")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW + mailbox + loopback,
        fd_links="socket:[1234] socket:[5678] socket:[9012]")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True, control_urls=("https://mail.example",))
    assert len(path.matches) == 1 and path.addresses == ("198.51.100.2",)
    assert path.control_endpoints == frozenset({("198.51.100.2", 443)})


@pytest.mark.parametrize("url,dns", [
    ("turn:turn.example:0?transport=tcp", ("198.51.100.2",)),
    ("turn:turn.example:3478?transport=udp", ("198.51.100.2",)),
    (TURN, ("fe80::1%eth0",)),
    (TURN, ("0.0.0.0",)),
])
def test_turn_endpoint_admission_rejects_invalid_port_protocol_or_address(url, dns):
    peer, resolver, _ = kernel_boundary(dns_addresses=dns)
    with pytest.raises(ValueError):
        faults.AndroidKernelPath(peer, OBSERVATION, url, resolver=resolver,
            resource_check=lambda: True)


def test_multiple_a_aaaa_answers_and_two_owned_sockets_are_one_endpoint_scope():
    address = ipaddress.ip_address("2001:db8::2")
    encoded = b"".join(address.packed[index:index + 4][::-1] for index in range(0, 16, 4)).hex().upper()
    row6 = ROW.replace("026433C6", encoded).replace("1234", "5678")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW, fd_links="socket:[1234] socket:[5678]",
        dns_addresses=("198.51.100.2", "2001:db8::2", "198.51.100.2"))
    original = peer._adb
    def adb(*args):
        if args[-2:] == ("cat", "/proc/123/net/tcp6"): return "header\n" + row6
        return original(*args)
    peer._adb = adb
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True)
    assert path.addresses == ("198.51.100.2", "2001:db8::2")
    assert len(path.matches) == 2 and path.rule_count == 2


def test_tls_mailbox_overlap_and_extra_same_uid_process_reject_scope():
    peer, resolver, _ = kernel_boundary()
    observation = {"pair": {"relay_protocol": "tls", "local": {"type": "relay"}}}
    with pytest.raises(ValueError, match="overlap"):
        faults.AndroidKernelPath(peer, observation, "turns:turn.example:443", resolver=resolver,
            resource_check=lambda: True, control_urls=("https://mail.example",))
    peer, resolver, _ = kernel_boundary(point="extra_uid_process")
    with pytest.raises(ValueError, match="unrecognized helper"):
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            resource_check=lambda: True)


def test_exact_bootstrap_helper_overlap_is_admitted_only_without_external_tcp():
    state = {"kind": "quiet", "alive": True}
    peer, resolver, events = kernel_boundary(helper_state=state)
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True)
    assert path.pid == "123" and path.matches
    assert ("shell", "cat", "/proc/456/cmdline") in events
    assert ("shell", "cat", "/proc/456/net/tcp") in events
    path.require_current()
    state["kind"] = "external"
    with pytest.raises(ValueError, match="external TCP"):
        path.require_current()
    state["alive"] = False
    path.require_current()


def test_bootstrap_helper_exit_during_inventory_needs_no_timeout():
    state = {"kind": "exit_on_read", "alive": True}
    peer, resolver, events = kernel_boundary(helper_state=state)
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True)
    assert path.pid == "123" and state["alive"] is False
    assert [event for event in events if event[1:5] == ("ps", "-A", "-o", "UID,PID")]


@pytest.mark.parametrize("kind,reason", [("external", "external TCP"),
                                          ("spoofed", "unrecognized helper")])
def test_bootstrap_helper_with_external_tcp_or_wrong_process_identity_rejects(kind, reason):
    state = {"kind": kind, "alive": True}
    peer, resolver, _ = kernel_boundary(helper_state=state)
    with pytest.raises(ValueError, match=reason):
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            resource_check=lambda: True)


@pytest.mark.parametrize("address", ["::ffff:0.0.0.0", "::ffff:224.0.0.1",
                                       "::ffff:169.254.1.1", "fe80::1%eth0"])
def test_mapped_unsafe_or_scoped_address_rejects_after_normalization(address):
    with pytest.raises(ValueError, match="cannot be scoped"):
        faults.scoped_address(address)


@pytest.mark.parametrize("value", [
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "PRIVATE_SOCKET"},
    {"scenario": "turn_tcp", "stage": "kernel_turn_url", "reason": "no_owned_match"},
    {"scenario": "turn_tcp", "stage": "PRIVATE_STAGE"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "address": "PRIVATE_ADDRESS"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "reason": None},
])
def test_native_path_diagnostic_allowlist_rejects_private_or_inapplicable_fields(value):
    assert faults.path_failure_observation(value) == {}


def test_controller_omits_forged_or_malformed_path_observer_projection(monkeypatch):
    instance = controller.Controller("android", SimpleNamespace(), None, None, {})
    instance.phase = "turn_tcp_authenticated_receipts"
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    error = ValueError("PRIVATE_ENDPOINT")
    diagnostic.observe(error, "kernel_socket_correlation", "no_owned_match")
    monkeypatch.setattr(diagnostic, "failure_observation", lambda _: {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches"})
    assert instance.failure_native_path(error) == {}
    monkeypatch.setattr(diagnostic, "failure_observation", lambda _: {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match",
        "endpoint": "PRIVATE_ENDPOINT"})
    assert instance.failure_native_path(error) == {}


def receipt_boundary(monkeypatch, point=None):
    instance = controller.Controller("android", SimpleNamespace(), None, None,
        {"run_id": 123, "run_attempt": 1})
    instance.partner = "windows"
    state = SimpleNamespace(events=[], error=ValueError("PRIVATE_MESSAGE_AND_CREDENTIAL"))
    instance.text = lambda scenario, index=0, *, sender=None, padded=False: "other" if sender else "own"
    def enqueue(text):
        state.events.append(("enqueue", text))
        if point == "receipt_enqueue": raise state.error
        return "PRIVATE_HANDLE"
    def delivered(handle):
        state.events.append(("delivered", handle))
        return True
    def records(text, direction):
        state.events.append(("records", direction))
        if point == "receipt_outbound_records" and direction == "outbound": raise state.error
        if point == "receipt_record_validation" and direction == "outbound": return []
        return [{"id": "PRIVATE_ID", "native_message_id": "PRIVATE_NATIVE_ID"}]
    def wait(action, *, timeout=90, interval=0.25):
        state.events.append(("wait", timeout))
        index = sum(event[0] == "wait" for event in state.events)
        if point == "receipt_delivery_wait" and index == 1: raise state.error
        if point == "receipt_inbound_wait" and index == 2: raise state.error
        return action()
    instance.enqueue, instance.delivered, instance.records, instance.wait = enqueue, delivered, records, wait
    return instance, state


@pytest.mark.parametrize("point", ["receipt_enqueue", "receipt_delivery_wait", "receipt_inbound_wait",
    "receipt_outbound_records", "receipt_record_validation"])
def test_actual_receipt_exchange_reports_only_escaping_fixed_stage(monkeypatch, point):
    instance, state = receipt_boundary(monkeypatch, point)
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    instance.phase = "turn_tcp_authenticated_receipts"
    with pytest.raises(ValueError) as caught:
        instance.exchange("turn_tcp:windows", path_diagnostics=diagnostic)
    if point != "receipt_record_validation": assert caught.value is state.error
    expected = {"native_path_failure": {"scenario": "turn_tcp", "stage": point}}
    assert instance.failure_native_path(caught.value) == expected
    assert instance.failure_native_path(ValueError("PRIVATE_REPLACEMENT")) == {}
    assert "PRIVATE" not in repr(expected)


def test_receipt_exchange_success_preserves_one_enqueue_two_90_second_waits_and_no_label(monkeypatch):
    instance, state = receipt_boundary(monkeypatch)
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    instance.phase = "turn_tcp_authenticated_receipts"
    result, handle = instance.exchange("turn_tcp:windows", path_diagnostics=diagnostic)
    assert result["authenticated_receipt"] is True and handle == "PRIVATE_HANDLE"
    assert state.events.count(("wait", 90)) == 2
    assert [event[0] for event in state.events].count("enqueue") == 1
    assert instance.failure_native_path(ValueError("PRIVATE_LATER")) == {}
    instance.phase = "turn_tcp_kernel_block_negative_control"
    error = ValueError("PRIVATE_LATER")
    diagnostic.observe(error, "receipt_enqueue")
    assert instance.failure_native_path(error) == {}


@pytest.mark.parametrize("matching", [True, False])
def test_actual_controller_main_projects_only_same_escaping_native_path_error(
        tmp_path, monkeypatch, capsys, matching):
    import connection_ci
    peer = SimpleNamespace(process=None)
    instance = controller.Controller("android", peer, None, None, {"source_commit": "a" * 40})
    instance.phase = "turn_tcp_authenticated_receipts"
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    observed = ValueError("PRIVATE_SOCKET_ENDPOINT")
    escaping = observed if matching else ValueError("PRIVATE_REPLACEMENT_EXCEPTION")
    diagnostic.observe(observed, "kernel_socket_correlation", "no_owned_match")
    def execute(): raise escaping
    instance.run = execute
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(
        start=lambda *args, **kwargs: None, close=lambda: None))
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "path_failure.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    record = json.loads(output.read_text())
    assert record["failure_type"] == "ValueError" and record["phase"] == "turn_tcp_authenticated_receipts"
    assert record.get("native_path_failure") == ({"scenario": "turn_tcp", "stage": "kernel_socket_correlation",
        "reason": "no_owned_match"} if matching else None)
    assert "PRIVATE" not in output.read_text() + capsys.readouterr().out
