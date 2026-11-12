"""Kernel command/counter component checks; never actual impairment evidence."""

from pathlib import Path
import json
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


def udp_link_fixture(monkeypatch, *, second_link=False, sink=False, canonical=False,
                     nft_available=True, policy_conflict=False, initial_group=0,
                     replace_on_group=False, state_ref=None):
    """Exercise the real AndroidKernelPath composition against a fake kernel."""
    state = SimpleNamespace(commands=[], ifb=False, alias=False, root="default", ingress=False,
        filter=False, rules={}, egress_packets=0, ingress_packets=0, failure=None,
        pid="123", uid="10053", resource=True,
        route4="default via 10.0.2.2 dev wlan0 table main\n", group=initial_group,
        chains={}, hooks={}, guard_drops=0, ifb_name=None, second_link=second_link,
        canonical=canonical, nft_available=nft_available, wlan_index=2,
        extra_group=0, extra_root="default", extra_ingress=False, extra_filter=False,
        extra_ifb=None, extra_alias=False, extra_egress_packets=0, extra_ingress_packets=0,
        sink=sink, policy_conflict=policy_conflict, guard_drop_by_chain={},
        ifb_index=4 if second_link else 3, replace_on_group=replace_on_group)
    if state_ref is not None:
        state_ref.append(state)
    value = None

    def command(*args):
        state.commands.append(args)
        if args == ("id", "-u"): return "0"
        if args == ("getprop", "ro.kernel.qemu"): return "1"
        if args == ("pidof", "PRIVATE_APP"): return state.pid
        if args == ("cat", "/proc/123/status"):
            return f"Uid:\t{state.uid}\t{state.uid}\t{state.uid}\t{state.uid}\n"
        if args == ("pm", "list", "packages", "-U"): return "package:PRIVATE_APP uid:10053\n"
        if args == ("ps", "-A", "-o", "UID,PID"): return "UID PID\n10053 123\n"
        if args == ("ip", "-j", "-d", "link", "show"):
            links = [{"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK", "UP"],
                      "link_type": "loopback", "group": 0},
                     {"ifindex": state.wlan_index, "ifname": "wlan0", "flags": ["UP"],
                      "link_type": "ether", "group": state.group}]
            if state.second_link:
                links.append({"ifindex": 3, "ifname": "wlan1", "flags": ["UP"],
                    "link_type": "ether", "group": state.extra_group,
                    **({"linkinfo": {"info_kind": "dummy"}} if state.sink else {})})
            if state.ifb:
                links.append({"ifindex": state.ifb_index, "ifname": state.ifb_name, "flags": ["UP"],
                    "link_type": "ether", "linkinfo": {"info_kind": "ifb"}, "group": 0})
            if state.extra_ifb:
                links.append({"ifindex": 5, "ifname": state.extra_ifb, "flags": ["UP"],
                    "link_type": "ether", "linkinfo": {"info_kind": "ifb"}, "group": 0})
            return json.dumps(links)
        if args[0:1] == ("cat",) and args[1].startswith("/sys/class/net/"):
            name, field = args[1].split("/")[-2:]
            index = {"lo": 1, "wlan0": state.wlan_index, "wlan1": 3,
                     state.ifb_name: state.ifb_index, state.extra_ifb: 5}[name]
            return str({"type": 772 if name == "lo" else 1, "ifindex": index,
                "iflink": index, "netdev_group": state.group if name == "wlan0" else
                    state.extra_group if name == "wlan1" else 0}[field])
        if args[0:2] == ("sh", "-c"):
            if "command -v nft" in args[2]: return "present" if state.nft_available else "absent"
            if "/etc/iproute2/group" in args[2]: return "0 default"
            if "/sys/class/net/" in args[2]: return "0"
        if args == ("iptables-save",) or args == ("ip6tables-save",):
            return "*filter\n-A OUTPUT -m devgroup --dst-group 7 -j ACCEPT\nCOMMIT\n" if state.policy_conflict else "*filter\nCOMMIT\n"
        if args == ("nft", "list", "ruleset"): return ""
        if args == ("ip", "-4", "route", "show", "table", "all"):
            return state.route4 + ("10.3.0.0/16 dev wlan1 table main\n" if state.second_link else "")
        if args == ("ip", "-6", "route", "show", "table", "all"): return ""
        if args in (("ip", "-4", "rule", "show"), ("ip", "-6", "rule", "show")):
            return "0: from all lookup local\n100: from all lookup main\n"
        if args[:3] == ("ip", "link", "set") and "group" in args:
            if args[args.index("dev") + 1] == "wlan1": state.extra_group = int(args[-1])
            else:
                state.group = int(args[-1])
                if state.replace_on_group:
                    state.wlan_index, state.group, state.replace_on_group = 9, 0, False
            return ""
        if args[:2] == ("ip", "link"):
            if args[2] == "add":
                if not state.ifb: state.ifb = True; state.ifb_name = args[3]
                else: state.extra_ifb = args[3]
                if state.failure == "ifb_collision": raise RuntimeError("PRIVATE_IFB_COLLISION")
            elif args[2] == "del":
                if args[3] == state.ifb_name: state.ifb = False
                else: state.extra_ifb = None
            elif args[2] == "set" and "alias" in args:
                if state.failure == "alias": raise RuntimeError("PRIVATE_ALIAS_FAILURE")
                if args[args.index("dev") + 1] == state.ifb_name: state.alias = True
                else: state.extra_alias = True
            return ""
        if args[:5] == ("ip", "-d", "link", "show", "dev"):
            which = next(link for link in value.coverage.links if link["ifb"] == args[-1])
            alias = state.alias if args[-1] == state.ifb_name else state.extra_alias
            return f"3: {args[-1]}: <UP> ifb" + (f" alias {which['alias']}" if alias else "")
        if args[:3] == ("tc", "qdisc", "show"):
            device = args[-1]
            if device in {state.ifb_name, state.extra_ifb}:
                link = next(link for link in value.coverage.links if link["ifb"] == device)
                return (f"qdisc netem {link['ingress']} root delay 75ms 10ms loss 0.1%\n"
                        if device == state.ifb_name and state.ifb or device == state.extra_ifb and state.extra_ifb else "")
            link = next((link for link in value.coverage.links if link["identity"]["name"] == device), None) if value is not None else None
            handle = link["egress"] if link else "30:"
            root = state.root if device == "wlan0" else state.extra_root
            ingress = state.ingress if device == "wlan0" else state.extra_ingress
            return ((f"qdisc netem {handle} root delay 75ms 10ms loss 0.1%" if root == "netem"
                     else f"qdisc netem {handle} root delay 5ms loss 5%" if root == "bad_profile"
                     else "qdisc netem 77: root" if root == "foreign"
                     else "qdisc noqueue 0: root refcnt 2")
                    + ("\nqdisc ingress ffff: parent ffff:fff1" if ingress else "") + "\n")
        if args[:4] == ("tc", "-s", "qdisc", "show"):
            device = args[-1]
            link = next(link for link in value.coverage.links if device in
                        {link["identity"]["name"], link["ifb"]})
            packets = (state.egress_packets if device == "wlan0" else
                       state.extra_egress_packets if device == "wlan1" else
                       state.ingress_packets if device == state.ifb_name else state.extra_ingress_packets)
            handle = link["egress"] if device in {"wlan0", "wlan1"} else link["ingress"]
            return f"qdisc netem {handle} root delay 75ms 10ms loss 0.1%\n Sent {packets * 100} bytes {packets} pkt (dropped 0, overlimits 0 requeues 0)\n"
        if args[:2] == ("tc", "qdisc"):
            if args[2] == "replace" and args[args.index("dev") + 1] == "wlan0": state.root = "netem"
            elif args[2] == "replace" and args[args.index("dev") + 1] == "wlan1": state.extra_root = "netem"
            elif args[2] == "add":
                if args[args.index("dev") + 1] == "wlan0": state.ingress = True
                else: state.extra_ingress = True
                if state.failure == "ingress_collision": raise RuntimeError("PRIVATE_INGRESS_COLLISION")
            elif args[2] == "del" and args[-1] == "root":
                if args[args.index("dev") + 1] == "wlan0": state.root = "default"
                else: state.extra_root = "default"
            elif args[2] == "del" and args[-1] == "ingress":
                if args[args.index("dev") + 1] == "wlan0": state.ingress = state.filter = False
                else: state.extra_ingress = state.extra_filter = False
            return ""
        if args[:2] == ("tc", "filter"):
            if args[2] == "show":
                device = args[args.index("dev") + 1]
                link = next(link for link in value.coverage.links if link["identity"]["name"] == device)
                current_filter = state.filter if device == "wlan0" else state.extra_filter
                return (f"filter protocol all pref {link['prio']} matchall action mirred redirect dev {link['ifb']}\n"
                        if current_filter is True else "filter protocol all pref 1 u32 action drop\n"
                        if current_filter == "foreign" else
                        f"filter protocol all pref {link['prio']} matchall action mirred redirect dev {link['ifb']}\n"
                        "filter protocol all pref 7 u32 action drop\n" if current_filter == "mixed" else "")
            if state.failure == "filter" or (state.failure == "second_filter" and args[args.index("dev") + 1] == "wlan1"):
                raise RuntimeError("PRIVATE_FILTER_FAILURE")
            if args[args.index("dev") + 1] == "wlan0": state.filter = True
            else: state.extra_filter = True
            return ""
        if args[0] in {"iptables", "ip6tables"}:
            family = args[0]
            if args[1] == "-N":
                state.chains[family, args[2]] = []
                if state.failure == "guard_new": raise RuntimeError("PRIVATE_GUARD_NEW_REPLY")
                return ""
            if args[1] == "-X": state.chains.pop((family, args[2])); return ""
            if args[1] == "-A":
                if state.failure == "guard_omit": return ""
                state.chains[family, args[2]].append("-A " + args[2] + " " + " ".join(args[3:]))
                if state.failure == "guard_append": raise RuntimeError("PRIVATE_GUARD_APPEND_REPLY")
                return ""
            if args[1] == "-I":
                if args[2] in {"OUTPUT", "INPUT"} and args[-1] != "DROP" and "--comment" in args:
                    state.hooks.setdefault((family, args[2]), []).insert(0,
                        "-A " + args[2] + " " + " ".join(args[4:]))
                    return ""
                comment = args[args.index("--comment") + 1]
                state.rules[comment] = [family, 0]
                state.hooks.setdefault((family, args[2]), []).insert(0,
                    "-A " + args[2] + " " + " ".join(args[4:]))
                if state.failure == "insert_reply": raise RuntimeError("PRIVATE_INSERT_REPLY")
                return ""
            if args[1] == "-S":
                key = (family, args[2])
                lines = state.chains.get(key, state.hooks.get(key, []))
                if state.canonical:
                    lines = [line.replace("/0xffffffff", "").replace("--comment ", '--comment "').replace(" -j ", '" -j ')
                             for line in lines]
                return "\n".join(lines)
            if args[1] == "-C": return ""
            if args[1] == "-D":
                if args[2] in {"INPUT", "OUTPUT"} and "--comment" in args and args[args.index("--comment") + 1].endswith("-jump"):
                    state.hooks[family, args[2]].remove("-A " + args[2] + " " + " ".join(args[3:]))
                elif (family, args[2]) in state.chains:
                    state.chains[family, args[2]].remove("-A " + args[2] + " " + " ".join(args[3:]))
                else:
                    state.rules.pop(args[args.index("--comment") + 1], None)
                    state.hooks[family, args[2]].remove("-A " + args[2] + " " + " ".join(args[3:]))
                return ""
            if args[1] == "-nvx":
                if args[2] == "-L" and (family, args[3]) in state.chains:
                    lines = []
                    for rule in state.chains[family, args[3]]:
                        comment = rule.split("--comment ", 1)[1].split()[0]
                        count = (state.guard_drop_by_chain.get(args[3], state.guard_drops)
                                 if comment.endswith("-drop") else
                                 state.extra_egress_packets if "-out-wlan1" in comment else
                                 state.extra_ingress_packets if "-in-wlan1" in comment else
                                 state.egress_packets if "-out-" in comment else state.ingress_packets)
                        lines.append(f"{count} {count * 100} RETURN udp -- * * /* {comment} */")
                    return "\n".join(lines)
                return "\n".join(f"1 {count} {count * 100} DROP udp -- * * 0.0.0.0/0 0.0.0.0/0 /* {comment} */"
                    for comment, (used_family, count) in state.rules.items() if used_family == family)
            return ""
        raise AssertionError(args)

    class Peer:
        APP = "PRIVATE_APP"
        def _adb(self, *args):
            assert args[0] == "shell"
            return command(*args[1:])
    observation = {"pair": {"relay_protocol": "udp", "local": {"type": "relay"}}}
    value = faults.AndroidKernelPath(Peer(), observation,
        "turn:turn.example:3478?transport=udp", resource_check=lambda: state.resource)
    link = value.coverage.links[0]
    value.device, value.ifb, value.egress_handle, value.ingress_handle = (
        "wlan0", link["ifb"], link["egress"], link["ingress"])
    value.filter_prio, value._qdisc_before = link["prio"], link["before_qdisc"]
    value._installed = link["installed"]
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
    inserts = [item for item in state.commands if item[0] in {"iptables", "ip6tables"}
               and item[1] == "-I" and item[-1] == "DROP"]
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
    assert not any(item[0] in {"iptables", "ip6tables"} and item[1] == "-I"
                   and item[-1] == "DROP" for item in state.commands)
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
    with pytest.raises(ValueError, match="profile_ingress_mismatch"):
        value.report()
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert state.ingress and "ingress" in value._installed


def test_two_independent_links_use_distinct_kernel_profiles_and_complete_guard(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, second_link=True)
    value.install()
    assert len(value.coverage.links) == 2
    assert state.ifb and state.extra_ifb and state.root == state.extra_root == "netem"
    assert state.ingress and state.extra_ingress
    commands = state.commands
    guard_appends = [index for index, item in enumerate(commands)
                     if item[0] in {"iptables", "ip6tables"} and item[1] == "-A"]
    guard_hooks = [index for index, item in enumerate(commands)
                   if item[0] in {"iptables", "ip6tables"} and item[1] == "-I" and item[-1] != "DROP"]
    assert len(guard_hooks) == 4 and max(guard_appends) < min(guard_hooks)
    returns = [item for item in commands if item[0] in {"iptables", "ip6tables"}
               and item[1] == "-A" and item[-1] == "RETURN"]
    assert len(returns) == 8
    assert {item[item.index("-o") + 1] for item in returns if "-o" in item} == {"wlan0", "wlan1"}
    assert {item[item.index("-i") + 1] for item in returns if "-i" in item} == {"wlan0", "wlan1"}
    assert all("-m" in item and "devgroup" in item and "/0xffffffff" in " ".join(item) for item in returns)
    state.egress_packets = state.ingress_packets = 4
    state.extra_egress_packets = state.extra_ingress_packets = 3
    report = value.report()
    assert report["link_coverage"]["admitted_links"] == 2
    assert report["link_coverage"]["impaired_links"] == 2
    assert report["counters"]["egress"]["packets"] == 7
    assert report["counters"]["ingress"]["packets"] == 7
    value.close()
    assert not state.ifb and not state.extra_ifb
    assert state.root == state.extra_root == "default"
    assert state.group == state.extra_group == 0


def test_dummy_sink_is_denied_and_never_impairment_or_return_target(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, second_link=True, sink=True)
    value.install()
    state.egress_packets = state.ingress_packets = 2
    report = value.report()
    assert report["link_coverage"]["admitted_links"] == 1
    assert report["link_coverage"]["excluded_sink_links"] == 1
    assert not any("wlan1" in item for item in state.commands if item[0] in {"tc", "iptables", "ip6tables"})
    value.close()


def test_guard_accepts_only_equivalent_saved_rule_format(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, canonical=True)
    value.install()
    state.egress_packets = state.ingress_packets = 2
    assert value.report()["link_coverage"]["guard_current"] is True
    state.chains[next(iter(state.chains))][0] = state.chains[next(iter(state.chains))][0].replace(
        "/0xffffffff", "/0xfffffffe")
    with pytest.raises(ValueError, match="guard_current_mismatch"):
        value.report()
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()


def test_foreign_hook_prefix_cannot_bypass_owned_udp_guard(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.hooks[("iptables", "OUTPUT")].insert(0, "-A OUTPUT -j ACCEPT")
    with pytest.raises(ValueError, match="guard_current_mismatch"):
        value.report()
    value.close()
    assert state.hooks[("iptables", "OUTPUT")] == ["-A OUTPUT -j ACCEPT"]


def test_one_chain_drop_change_cannot_be_hidden_by_another_chain(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    state.guard_drops = 1
    value.install()
    first, second = value.coverage.guard[:2]
    state.guard_drop_by_chain[first["chain"]] = 0
    state.guard_drop_by_chain[second["chain"]] = 2
    state.egress_packets = state.ingress_packets = 2
    with pytest.raises(ValueError, match="guard_.*_drop"):
        value.report()
    value.close()


@pytest.mark.parametrize("missing", ["nft", "group_policy"])
def test_group_preflight_rejects_incomplete_active_policy_inventory(monkeypatch, missing):
    with pytest.raises(ValueError, match="group_inventory_unavailable|group_policy_conflict"):
        udp_link_fixture(monkeypatch, nft_available=missing != "nft",
                         policy_conflict=missing == "group_policy")


def test_same_name_replacement_is_not_mutated_during_cleanup(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.wlan_index = 9
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert not any(item[:3] == ("tc", "qdisc", "del") for item in state.commands)


def test_name_replacement_between_group_write_and_readback_is_not_restored(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, replace_on_group=True)
    with pytest.raises(ValueError, match="recheck_link_set_changed") as result:
        value.install()
    assert isinstance(result.value.__cause__, RuntimeError)
    assert state.wlan_index == 9 and state.group == 0
    assert len([item for item in state.commands if item[:3] == ("ip", "link", "set")
                and "group" in item]) == 1
    assert not any(item[0] == "tc" and item[1] in {"replace", "add"} for item in state.commands)


def test_same_name_ifb_replacement_is_not_deleted(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    value.install()
    state.ifb_index = 99
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        value.close()
    assert state.ifb
    assert not any(item[:3] == ("ip", "link", "del") for item in state.commands)


def test_original_nondefault_netdevice_group_is_restored_exactly(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, initial_group=7)
    value.install()
    assert state.group == value.coverage.group and state.group != 7
    value.close()
    assert state.group == 7


def test_high_bit_random_source_still_installs_positive_31_bit_group(monkeypatch):
    serial = iter(range(1, 100))
    def high_bit_uuid():
        number = next(serial)
        return SimpleNamespace(hex=f"{0x80000000 | number:08x}{number:08x}" + "0" * 16)
    monkeypatch.setattr(faults, "uuid4", high_bit_uuid)
    value, state = udp_link_fixture(monkeypatch)
    assert 0 < value.coverage.group <= 0x7fffffff
    value.install()
    assert state.group == value.coverage.group
    assert all(0 <= int(item[-1]) <= 0x7fffffff for item in state.commands
               if item[:3] == ("ip", "link", "set") and "group" in item)
    state.egress_packets = state.ingress_packets = 2
    assert value.report()["link_coverage"]["group_identity_guard"] is True
    value.close()
    assert state.group == 0


@pytest.mark.parametrize("group", [0x80000000, -0x80000000])
def test_preexisting_high_bit_group_fails_before_any_tag_mutation(monkeypatch, group):
    states = []
    with pytest.raises(ValueError, match="group_inventory_unavailable"):
        udp_link_fixture(monkeypatch, initial_group=group, state_ref=states)
    assert len(states) == 1
    assert not any(item[:3] == ("ip", "link", "set") and "group" in item
                   for item in states[0].commands)


@pytest.mark.parametrize("late", ["root", "ingress"])
def test_late_foreign_tc_state_is_not_replaced_or_removed(monkeypatch, late):
    value, state = udp_link_fixture(monkeypatch)
    if late == "root": state.root = "foreign"
    else: state.ingress = True
    with pytest.raises(ValueError, match="conflicting_qdisc|collision_ingress_filter"):
        value.install()
    assert state.root == ("foreign" if late == "root" else "default")
    assert state.ingress is (late == "ingress")
    if late == "root":
        assert not any(item[:3] == ("tc", "qdisc", "replace") and "wlan0" in item
                       for item in state.commands)
    assert not any(item[:3] == ("tc", "qdisc", "del") and item[-1] == "ingress"
                   for item in state.commands)


def test_second_link_partial_filter_reply_rolls_back_only_owned_links(monkeypatch):
    value, state = udp_link_fixture(monkeypatch, second_link=True)
    state.failure = "second_filter"
    with pytest.raises(RuntimeError, match="PRIVATE_FILTER_FAILURE"):
        value.install()
    assert not state.ifb and not state.extra_ifb
    assert state.root == state.extra_root == "default"
    assert not state.ingress and not state.extra_ingress
    assert state.group == state.extra_group == 0


@pytest.mark.parametrize("failure", ["guard_new", "guard_append"])
def test_guard_ambiguous_mutation_keeps_exact_cleanup_obligation(monkeypatch, failure):
    value, state = udp_link_fixture(monkeypatch)
    state.failure = failure
    with pytest.raises(RuntimeError, match="PRIVATE_GUARD") as result:
        value.install()
    if failure == "guard_new":
        assert isinstance(result.value.__cause__, RuntimeError)
        assert state.chains
    else:
        assert not state.chains


def test_incomplete_child_chain_is_rejected_before_any_guard_hook(monkeypatch):
    value, state = udp_link_fixture(monkeypatch)
    state.failure = "guard_omit"
    with pytest.raises(ValueError, match="guard_install_incomplete"):
        value.install()
    assert not any(item[0] in {"iptables", "ip6tables"} and item[1] == "-I"
                   for item in state.commands)
    assert not state.chains and not state.hooks


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
