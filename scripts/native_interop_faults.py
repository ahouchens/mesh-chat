"""CI-only exact Android Linux-kernel path faults, with actual packet counters.

Addresses/socket inodes stay transient. No application packet substitution,
sleep-based loss model, TURN advertisement inference, or unrelated-host rule.
"""

import ipaddress
import json
from contextlib import contextmanager, nullcontext
import re
import shlex
import socket
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from native_interop_diagnostics import negative_control_error, negative_control_stage
from native_interop_link_scope import (LinkScopeError, _numeric_group, covered_link, covered_links,
    link_metadata, link_names, snapshot as link_snapshot)


PATH_FAILURE_REASONS = {
    "kernel_relay_evidence": frozenset(), "kernel_emulator_identity": frozenset(),
    "kernel_turn_url": frozenset(), "kernel_turn_resolution": frozenset(),
    "kernel_process_identity": frozenset(), "kernel_socket_inventory": frozenset(),
    "kernel_socket_parse": frozenset(),
    "kernel_socket_correlation": frozenset({"no_owned_match", "ambiguous_owned_matches", "uncovered_endpoint"}),
    "kernel_process_uid": frozenset(), "kernel_scope_exclusivity": frozenset(),
    "kernel_socket_route": frozenset(),
    "kernel_link_coverage": LinkScopeError.REASONS,
    "receipt_enqueue": frozenset(), "receipt_delivery_wait": frozenset(),
    "receipt_inbound_wait": frozenset(), "receipt_outbound_records": frozenset(),
    "receipt_record_validation": frozenset(),
}
PATH_FAILURE_SCENARIOS = frozenset({"direct", "turn_udp", "turn_tcp", "turn_tls", "impaired"})
TCP_SOCKET_STATES = frozenset(f"{state:02X}" for state in range(1, 13))
TCP_AMBIGUITY_SUMMARIES = frozenset({"one_established_plus_other", "multiple_established",
                                     "no_established", "unclassifiable"})
MAX_TURN_ENDPOINTS = 16


def scoped_address(value):
    address = ipaddress.ip_address(value)
    if getattr(address, "scope_id", None):
        raise ValueError("Endpoint address cannot be scoped")
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError("Endpoint address cannot be scoped")
    return str(address)


def turn_endpoints(url, protocol, resolver):
    scheme, separator, rest = url.partition(":")
    parsed = urlsplit("//" + rest)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (not separator or scheme not in {"turn", "turns"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path or parsed.fragment
            or (scheme == "turns") != (protocol == "tls")
            or (protocol == "tcp" and query != {"transport": ["tcp"]})
            or (protocol == "tls" and query not in ({}, {"transport": ["tcp"]}))):
        raise ValueError("Selected TURN URL and relay protocol do not match")
    port = parsed.port if parsed.port is not None else (5349 if scheme == "turns" else 3478)
    if not 1 <= port <= 65535:
        raise ValueError("TURN destination port is invalid")
    addresses = set()
    for item in resolver(parsed.hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
        addresses.add(scoped_address(item[4][0]))
        if len(addresses) > MAX_TURN_ENDPOINTS:
            raise ValueError("TURN destination set exceeds its limit")
    if not addresses:
        raise ValueError("TURN destination set is empty")
    return tuple(sorted(addresses, key=lambda value: (ipaddress.ip_address(value).version, value))), port


def owned_turn_endpoints(table, inodes, addresses, port, *, controls=(), allow_empty=False,
                         path_diagnostics=None):
    matches = set()
    uncovered = False
    for line in table.splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[9] not in inodes:
            continue
        with path_stage(path_diagnostics, "kernel_socket_parse"):
            local, local_port = ipv4_proc(parts[1])
            remote, remote_port = ipv4_proc(parts[2])
        if parts[3] == "01" and local_port:
            if remote in addresses and remote_port == port:
                matches.add((parts[9], local, local_port, remote, remote_port))
            elif (remote, remote_port) not in controls and not ipaddress.ip_address(remote).is_loopback:
                uncovered = True
    if uncovered:
        error = ValueError("An own-process TCP endpoint is outside the scoped TURN or control set")
        if type(path_diagnostics) is NativePathDiagnostics:
            path_diagnostics.observe(error, "kernel_socket_correlation", "uncovered_endpoint")
        raise error
    if not matches and not allow_empty:
        error = ValueError("No established own-process TURN endpoint is covered")
        if type(path_diagnostics) is NativePathDiagnostics:
            path_diagnostics.observe(error, "kernel_socket_correlation", "no_owned_match")
        raise error
    return frozenset(matches)


def path_failure_observation(value):
    if (type(value) is not dict or not {"scenario", "stage"} <= set(value)
            or set(value) - {"scenario", "stage", "reason", "tcp_state_summary", "owned_inode_relation"}
            or type(value["scenario"]) is not str or value["scenario"] not in PATH_FAILURE_SCENARIOS
            or type(value["stage"]) is not str or value["stage"] not in PATH_FAILURE_REASONS):
        return {}
    if "reason" in value and (type(value["reason"]) is not str
            or value["reason"] not in PATH_FAILURE_REASONS[value["stage"]]):
        return {}
    if value.get("reason") == "uncovered_endpoint" and value["scenario"] not in {"turn_tcp", "turn_tls"}:
        return {}
    has_summary = "tcp_state_summary" in value or "owned_inode_relation" in value
    if has_summary and (set(value) != {"scenario", "stage", "reason", "tcp_state_summary", "owned_inode_relation"}
            or value["scenario"] not in {"turn_tcp", "turn_tls"}
            or value["stage"] != "kernel_socket_correlation"
            or value["reason"] != "ambiguous_owned_matches"
            or type(value["tcp_state_summary"]) is not str
            or value["tcp_state_summary"] not in TCP_AMBIGUITY_SUMMARIES
            or type(value["owned_inode_relation"]) is not str
            or value["owned_inode_relation"] not in {"same", "distinct"}):
        return {}
    return dict(value)


class NativePathDiagnostics:
    """One private escaping-error label; no kernel values or exception text."""
    def __init__(self, scenario):
        self.scenario = scenario if scenario in PATH_FAILURE_SCENARIOS else None
        self._failure = None

    def observe(self, error, stage, reason=None, *, tcp_state_summary=None, owned_inode_relation=None):
        if self._failure is not None and self._failure[0] is error:
            return  # A nested, more exact source check already selected this error.
        selected = path_failure_observation({"scenario": self.scenario, "stage": stage,
            **({"reason": reason} if reason is not None else {}),
            **({"tcp_state_summary": tcp_state_summary, "owned_inode_relation": owned_inode_relation}
               if tcp_state_summary is not None or owned_inode_relation is not None else {})})
        self._failure = (error, selected) if selected else None

    @contextmanager
    def scope(self, stage):
        if stage not in PATH_FAILURE_REASONS:
            raise ValueError("Unknown native path diagnostic stage")
        try:
            yield
        except Exception as error:
            try: self.observe(error, stage)
            except Exception: self._failure = None
            raise

    def failure_observation(self, error):
        observed = self._failure
        return path_failure_observation(observed[1]) if observed is not None and observed[0] is error else {}


def path_stage(observer, stage):
    return observer.scope(stage) if type(observer) is NativePathDiagnostics else nullcontext()


def ipv4_proc(value):
    address, port = value.split(":")
    if re.fullmatch(r"(?:[A-Fa-f0-9]{8}|[A-Fa-f0-9]{32})", address) is None or re.fullmatch(r"[A-Fa-f0-9]{4}", port) is None:
        raise ValueError("Invalid kernel IPv4 socket")
    data = bytes.fromhex(address)
    data = b"".join(data[index:index + 4][::-1] for index in range(0, len(data), 4))
    parsed = ipaddress.ip_address(data)
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is None:
            return str(parsed), int(port, 16)
        parsed = parsed.ipv4_mapped
    return str(parsed), int(port, 16)


def tcp_ambiguity_summary(states, inodes):
    if any(type(state) is not str or state.upper() not in TCP_SOCKET_STATES for state in states):
        state_summary = "unclassifiable"
    else:
        established = sum(state.upper() == "01" for state in states)
        state_summary = ("multiple_established" if established > 1 else
                         "one_established_plus_other" if established == 1 else "no_established")
    return {"tcp_state_summary": state_summary,
            "owned_inode_relation": "same" if len(set(inodes)) == 1 else "distinct"}


def owned_socket(table, inodes, allowed_addresses, port, conntrack="", *, path_diagnostics=None):
    matches = []
    match_states = []
    for line in table.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10 or parts[9] not in inodes:
            continue
        with path_stage(path_diagnostics, "kernel_socket_parse"):
            local, local_port = ipv4_proc(parts[1])
            remote, remote_port = ipv4_proc(parts[2])
        if remote in allowed_addresses and remote_port == port and local_port:
            matches.append({"local": local, "local_port": local_port, "remote": remote, "remote_port": remote_port, "inode": parts[9]})
            match_states.append(parts[3])
        elif remote_port == 0 and local_port:
            for flow in conntrack.splitlines():
                match = re.search(r"\bsrc=([0-9.]+) dst=([0-9.]+) sport=([0-9]+) dport=([0-9]+)\b", flow)
                if match and int(match[3]) == local_port and match[2] in allowed_addresses and int(match[4]) == port:
                    source = str(ipaddress.IPv4Address(match[1]))
                    if local not in {"0.0.0.0", source}: continue
                    matches.append({"local": source, "local_port": local_port, "remote": match[2], "remote_port": port, "inode": parts[9]})
                    match_states.append(parts[3])
    if len(matches) != 1:
        error = ValueError("Selected TURN path lacks one unambiguous own-process kernel socket")
        if type(path_diagnostics) is NativePathDiagnostics:
            try:
                summary = (tcp_ambiguity_summary(match_states, (match["inode"] for match in matches))
                           if len(matches) > 1 and path_diagnostics.scenario in {"turn_tcp", "turn_tls"} else {})
                path_diagnostics.observe(error, "kernel_socket_correlation",
                    "no_owned_match" if not matches else "ambiguous_owned_matches", **summary)
            except Exception: pass
        raise error
    return matches[0]


def netem_counter(text, handle):
    match = re.search(r"qdisc netem " + re.escape(handle) + r"[^\n]*\n\s*Sent ([0-9]+) bytes ([0-9]+) pkt \(dropped ([0-9]+),", text)
    if match is None:
        raise ValueError("Kernel netem packet counter is unavailable")
    return dict(zip(("bytes", "packets", "dropped"), map(int, match.groups())))


class _BoundedUdpLinks:
    """Exact owned multi-link tc and packet guard for the disposable emulator."""
    def __init__(self, owner):
        self.owner = owner
        self.command = owner.command
        self.plan = self._snapshot()
        self.links = []
        self.guard = []
        self.tagged = False
        for item in self.plan["external"]:
            self.links.append({"identity": item, "ifb": "mci" + uuid4().hex[:12],
                "alias": owner.rule + "-" + str(len(self.links)),
                "egress": format(0x100 + int(uuid4().hex[:4], 16) % 0x7000, "x") + ":",
                "ingress": format(0x8000 + int(uuid4().hex[:4], 16) % 0x7000, "x") + ":",
                "prio": 10000 + int(uuid4().hex[:4], 16) % 50000,
                "installed": [], "tag_possible": False, "before_qdisc": self._default_qdisc(item["name"])})
        self._policy_preflight()
        groups = {item["group"] for item in self.plan["all"].values()}
        for _ in range(8):
            candidate = int(uuid4().hex[:8], 16) & 0x7fffffff
            if candidate and candidate not in groups and candidate not in self._mapped_groups:
                self.group = candidate
                break
        else:
            raise LinkScopeError("group_collision")

    def _snapshot(self, *, owned_ifbs=()):
        try:
            output = link_snapshot(self.command)
        except Exception as error:
            raise LinkScopeError("initial_inventory_unavailable") from error
        return covered_links(*output, link_metadata(self.command, output[0]), owned_ifbs=owned_ifbs)

    def _default_qdisc(self, name):
        value = self.command("tc", "qdisc", "show", "dev", name).strip()
        if (len(value.splitlines()) != 1 or
                re.match(r"^qdisc (?:noqueue|pfifo_fast|fq_codel) 0: root(?:\s|$)", value) is None):
            raise LinkScopeError("conflicting_qdisc")
        return value

    def _policy_preflight(self):
        try:
            inventories = [self.command(family + "-save") for family in ("iptables", "ip6tables")]
            nft = self.command("sh", "-c", shlex.quote("command -v nft >/dev/null 2>&1 && echo present || echo absent"))
            if nft == "present":
                inventories.append(self.command("nft", "list", "ruleset"))
            else:
                # A missing userspace binary says nothing about kernel rules.
                raise ValueError("Active nft ruleset cannot be inventoried")
            mapping = self.command("sh", "-c", shlex.quote("if [ -f /etc/iproute2/group ]; then cat /etc/iproute2/group; fi"))
        except Exception as error:
            raise LinkScopeError("group_inventory_unavailable") from error
        if any(re.search(r"\b(?:devgroup|src-group|dst-group|iifgroup|oifgroup|suppress_ifgroup)\b", text)
               for text in inventories):
            raise LinkScopeError("group_policy_conflict")
        self._firewall_before = inventories[:2]
        self._mapped_groups = set()
        for line in mapping.splitlines():
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            if len(parts) != 2 or not parts[0].isdigit():
                raise LinkScopeError("group_inventory_unavailable")
            self._mapped_groups.add(int(parts[0]))

    def _current_plan(self, *, require_group=True):
        owned = tuple(link["ifb"] for link in self.links if "ifb" in link["installed"])
        for link in self.links:
            if link["ifb"] in owned:
                detail = self.command("ip", "-d", "link", "show", "dev", link["ifb"])
                if ("alias " + link["alias"]) not in detail or "ifb" not in detail:
                    raise LinkScopeError("collision_ifb")
        current = self._snapshot(owned_ifbs=owned)
        before = {(item["name"], item["ifindex"], item["kind"])
                  for item in self.plan["external"] + self.plan["sinks"]}
        after = {(item["name"], item["ifindex"], item["kind"])
                 for item in current["external"] + current["sinks"]}
        if before != after:
            raise LinkScopeError("recheck_link_set_changed")
        for link in self.links:
            if "ifb" in link["installed"] and link.get("ifb_index") is not None:
                item = current["all"].get(link["ifb"])
                if item is None or item["ifindex"] != link["ifb_index"] or item["kind"] != "ifb":
                    raise LinkScopeError("collision_ifb")
        if require_group:
            names = {link["identity"]["name"] for link in self.links}
            for name, item in current["all"].items():
                expected = self.group if self.tagged and name in names else self.plan["all"].get(name, item)["group"]
                if item["group"] != expected:
                    raise LinkScopeError("recheck_group_identity_changed")
        return current

    def _tag_links(self):
        for link in self.links:
            name = link["identity"]["name"]
            link["tag_possible"] = True
            self.command("ip", "link", "set", "dev", name, "group", str(self.group))
            current = self._current_plan(require_group=False)
            if current["all"][name]["ifindex"] != link["identity"]["ifindex"] or current["all"][name]["group"] != self.group:
                raise LinkScopeError("group_assignment_mismatch")
        self.tagged = True
        self._current_plan()

    def _install_link(self, link):
        name, ifb = link["identity"]["name"], link["ifb"]
        if ifb in self._current_plan()["all"]:
            raise LinkScopeError("collision_ifb")
        link["installed"].append("ifb")
        link["ifb_confirmed"] = False
        self.command("ip", "link", "add", ifb, "type", "ifb")
        link["ifb_confirmed"] = True
        created = self._cleanup_identity(ifb)
        if created is None or created["kind"] != "ifb":
            raise LinkScopeError("collision_ifb")
        link["ifb_index"] = created["ifindex"]
        self.command("ip", "link", "set", "dev", ifb, "alias", link["alias"])
        link["alias_confirmed"] = True
        self.command("ip", "link", "set", ifb, "up")
        self._current_plan()
        if self.command("tc", "qdisc", "show", "dev", name).strip() != link["before_qdisc"]:
            raise LinkScopeError("conflicting_qdisc")
        link["installed"].append("egress")
        self.command("tc", "qdisc", "replace", "dev", name, "root", "handle", link["egress"],
            "netem", "delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%")
        link["installed"].append("ingress")
        link["ingress_confirmed"] = False
        self._current_plan()
        if "qdisc ingress ffff:" in self.command("tc", "qdisc", "show", "dev", name):
            raise LinkScopeError("collision_ingress_filter")
        if self.command("tc", "filter", "show", "dev", name, "parent", "ffff:").strip():
            raise LinkScopeError("collision_ingress_filter")
        self.command("tc", "qdisc", "add", "dev", name, "handle", "ffff:", "ingress")
        link["ingress_confirmed"] = True
        self.command("tc", "filter", "add", "dev", name, "parent", "ffff:", "protocol", "all",
            "prio", str(link["prio"]), "matchall", "action", "mirred", "egress", "redirect", "dev", ifb)
        link["filter_confirmed"] = True
        self.command("tc", "qdisc", "replace", "dev", ifb, "root", "handle", link["ingress"],
            "netem", "delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%")

    @staticmethod
    def _rule_tokens(line):
        try:
            tokens = shlex.split(line)
        except ValueError as error:
            raise LinkScopeError("guard_current_mismatch") from error
        for marker in ("--dst-group", "--src-group"):
            if marker in tokens:
                index = tokens.index(marker) + 1
                if index >= len(tokens):
                    raise LinkScopeError("guard_current_mismatch")
                parts = tokens[index].split("/")
                if len(parts) > 2 or not all(re.fullmatch(r"(?:0x[0-9a-fA-F]+|[0-9]+)", part) for part in parts):
                    raise LinkScopeError("guard_current_mismatch")
                if len(parts) == 2 and int(parts[1], 0) != 0xffffffff:
                    raise LinkScopeError("guard_current_mismatch")
                tokens[index] = str(int(parts[0], 0))
        return tokens

    def _chain_rules(self, entry):
        listing = self.command(entry["family"], "-S", entry["chain"])
        lines = [line.strip() for line in listing.splitlines() if line.startswith("-A ")]
        return [self._rule_tokens(line) for line in lines]

    def _guard_shape(self, entry):
        expected = [self._rule_tokens(rule) for rule in entry["rules"]]
        if self._chain_rules(entry) != expected:
            raise LinkScopeError("guard_current_mismatch")
        hooks = self.command(entry["family"], "-S", entry["hook"])
        matches = [self._rule_tokens(line) for line in hooks.splitlines() if line.startswith("-A ")]
        jump = self._rule_tokens(entry["jump"])
        if matches.count(jump) != 1:
            raise LinkScopeError("guard_current_mismatch")
        if any(tokens[-2:] == ["-j", entry["chain"]] and
               tokens != jump for tokens in matches):
            raise LinkScopeError("guard_current_mismatch")
        allowed_prefix = []
        if entry["hook"] == "OUTPUT" and self.owner._blocked:
            for family, args, _ in self.owner._drop_rules:
                if family == entry["family"]:
                    allowed_prefix.append(self._rule_tokens("-A OUTPUT " + " ".join(args)))
        if matches[:len(allowed_prefix) + 1] != allowed_prefix + [jump]:
            raise LinkScopeError("guard_current_mismatch")

    def _install_guard(self):
        value = "0x" + format(self.group, "x") + "/0xffffffff"
        for family in ("iptables", "ip6tables"):
            for direction in ("OUTPUT", "INPUT"):
                chain = "MC" + uuid4().hex[:16].upper()
                if any(re.search(r"^:" + re.escape(chain) + r"\s", rules, re.M)
                       for rules in self._firewall_before):
                    raise LinkScopeError("guard_chain_collision")
                comment = self.owner.rule + ("-out" if direction == "OUTPUT" else "-in")
                entry = {"family": family, "hook": direction, "chain": chain,
                         "comment": comment, "rules": [], "created": False,
                         "created_possible": True, "jumped": False}
                self.guard.append(entry)
                self.command(family, "-N", chain)
                entry["created"] = True
                for link in self.links:
                    name = link["identity"]["name"]
                    flag = "-o" if direction == "OUTPUT" else "-i"
                    group_flag = "--dst-group" if direction == "OUTPUT" else "--src-group"
                    label = comment + "-" + name
                    args = [flag, name, "-m", "devgroup", group_flag, value,
                            "-m", "comment", "--comment", label, "-j", "RETURN"]
                    entry["rules"].append("-A " + chain + " " + " ".join(args))
                    self.command(family, "-A", chain, *args)
                args = ["-m", "comment", "--comment", comment + "-drop", "-j", "DROP"]
                entry["rules"].append("-A " + chain + " " + " ".join(args))
                self.command(family, "-A", chain, *args)
                jump_args = (["-p", "udp", "-m", "owner", "--uid-owner", self.owner.uid]
                             if direction == "OUTPUT" else ["-p", "udp"])
                jump_args += ["-m", "comment", "--comment", comment + "-jump", "-j", chain]
                entry["jump_args"] = jump_args
                entry["jump"] = "-A " + direction + " " + " ".join(jump_args)
        # Every child chain is complete before the first hook can expose it.
        for entry in self.guard:
            if self._chain_rules(entry) != [self._rule_tokens(rule) for rule in entry["rules"]]:
                raise LinkScopeError("guard_install_incomplete")
        for entry in self.guard:
            family, direction, jump_args = entry["family"], entry["hook"], entry["jump_args"]
            entry["jumped"] = True  # An error reply may follow a successful insert.
            self.command(family, "-I", direction, "1", *jump_args)
            self._guard_shape(entry)

    def _guard_count(self, entry, marker):
        listing = self.command(entry["family"], "-nvx", "-L", entry["chain"])
        lines = [line.split() for line in listing.splitlines() if marker in line.split()]
        if len(lines) != 1 or not lines[0][0].isdigit():
            raise LinkScopeError("guard_capability_unavailable")
        return int(lines[0][0])

    @staticmethod
    def _ingress_filter_owned(value, link):
        lines = value.splitlines()
        headers = [line for line in lines if line.lstrip().startswith("filter ")]
        actions = [line for line in lines if re.search(r"\baction\b", line)]
        marker = "pref " + str(link["prio"]) + " matchall"
        return (1 <= len(headers) <= 2
            and all("protocol all" in line and marker in line for line in headers)
            and len(actions) == 1 and "mirred" in actions[0]
            and "redirect" in actions[0].lower()
            and re.search(r"\b" + re.escape(link["ifb"]) + r"\b", actions[0]) is not None)

    def guard_counts(self):
        values = {"output": 0, "input": 0, "output_drop": 0, "input_drop": 0,
                  "chain": {}}
        for entry in self.guard:
            self._guard_shape(entry)
            name = "output" if entry["hook"] == "OUTPUT" else "input"
            allowed = 0
            for link in self.links:
                # The exact interface label is kept only in the private rule.
                allowed += self._guard_count(entry, entry["comment"] + "-" + link["identity"]["name"])
            dropped = self._guard_count(entry, entry["comment"] + "-drop")
            values[name] += allowed
            values[name + "_drop"] += dropped
            values["chain"][entry["chain"]] = {"allowed": allowed, "drop": dropped,
                                                "direction": name}
        return values

    def install(self):
        try:
            self._tag_links()
            for link in self.links:
                self._install_link(link)
            self._current_plan()
            self._install_guard()
            self.before_guard = self.guard_counts()
            self.before = self.counters()
        except Exception as error:
            try:
                self.close()
            except Exception as cleanup_error:
                self.owner._setup_cleanup_failure = cleanup_error
                raise error from cleanup_error
            raise

    def current(self):
        self._current_plan()
        for link in self.links:
            if "ingress" not in link["installed"]:
                raise LinkScopeError("guard_current_mismatch")
            name, ifb = link["identity"]["name"], link["ifb"]
            qdisc = self.command("tc", "qdisc", "show", "dev", name)
            iqdisc = self.command("tc", "qdisc", "show", "dev", ifb)
            filter_text = self.command("tc", "filter", "show", "dev", name, "parent", "ffff:")
            if ("qdisc netem " + link["egress"] + " root" not in qdisc
                    or "delay 75ms 10ms" not in qdisc or "loss 0.1%" not in qdisc):
                raise LinkScopeError("profile_egress_mismatch")
            if ("qdisc ingress ffff:" not in qdisc or
                    "qdisc netem " + link["ingress"] + " root" not in iqdisc
                    or "delay 75ms 10ms" not in iqdisc or "loss 0.1%" not in iqdisc
                    or not self._ingress_filter_owned(filter_text, link)):
                raise LinkScopeError("profile_ingress_mismatch")
        if len(self.guard) != 4:
            raise LinkScopeError("guard_current_mismatch")
        for entry in self.guard:
            self._guard_shape(entry)

    def counters(self):
        totals = {direction: dict.fromkeys(("bytes", "packets", "dropped"), 0)
                  for direction in ("egress", "ingress")}
        for link in self.links:
            name = link["identity"]["name"]
            samples = {"egress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", name), link["egress"]),
                       "ingress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", link["ifb"]), link["ingress"])}
            if "before" in link:
                for direction in samples:
                    for field, value in samples[direction].items():
                        if value < link["before"][direction][field]:
                            raise LinkScopeError("profile_counter_regression")
                        totals[direction][field] += value - link["before"][direction][field]
            else:
                link["before"] = samples
        return totals

    def report(self):
        self.current()
        counts = self.guard_counts()
        delta = {key: counts[key] - self.before_guard[key]
                 for key in ("output", "input", "output_drop", "input_drop")}
        for chain, after in counts["chain"].items():
            before = self.before_guard["chain"].get(chain)
            if before is None or after["direction"] != before["direction"]:
                raise LinkScopeError("guard_current_mismatch")
            if after["drop"] != before["drop"]:
                raise LinkScopeError("guard_output_drop" if after["direction"] == "output" else "guard_input_drop")
            if after["allowed"] < before["allowed"]:
                raise LinkScopeError("guard_current_mismatch")
        if delta["output_drop"] != 0 or delta["output"] < 0:
            raise LinkScopeError("guard_output_drop")
        if delta["input_drop"] != 0 or delta["input"] < 0:
            raise LinkScopeError("guard_input_drop")
        if delta["output"] <= 0 or delta["input"] <= 0:
            raise LinkScopeError("guard_input_path_unverified")
        counters = self.counters()
        if any(counters[direction][field] <= 0 for direction in counters for field in ("bytes", "packets")):
            raise ValueError("Kernel impairment lacks actual routed packets")
        return {"kind": "android_emulator_linux_kernel_tc_netem", "delay_ms_each_way": 75,
            "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1,
            "added_nominal_rtt_ms": 150, "link_scope": "isolated_emulator_route",
            "loss_observed": sum(item["dropped"] for item in counters.values()) > 0,
            "counters": counters, "link_coverage": {
                "admitted_links": len(self.links), "impaired_links": len(self.links),
                "excluded_sink_links": len(self.plan["sinks"]), "disjoint_paths": True,
                "current": True, "guard_current": True, "group_identity_guard": True,
                "allowed_output_packets": delta["output"], "allowed_input_packets": delta["input"],
                "uncovered_udp_drops": 0}}

    def close(self):
        failures = []
        for entry in reversed(self.guard):
            family, chain = entry["family"], entry["chain"]
            try:
                if entry.get("jumped"):
                    hooks = self.command(family, "-S", entry["hook"])
                    actual = [self._rule_tokens(line) for line in hooks.splitlines() if line.startswith("-A ")]
                    expected = self._rule_tokens(entry["jump"])
                    if actual.count(expected) > 1 or any(tokens[-2:] == ["-j", chain] and tokens != expected
                                                          for tokens in actual):
                        raise ValueError("Guard hook ownership changed")
                    if expected in actual:
                        self.command(family, "-D", entry["hook"], *entry["jump_args"])
                        if expected in [self._rule_tokens(line) for line in
                                self.command(family, "-S", entry["hook"]).splitlines() if line.startswith("-A ")]:
                            raise ValueError("Guard hook remains")
                    entry["jumped"] = False
                if entry.get("created"):
                    actual = self._chain_rules(entry)
                    expected = [self._rule_tokens(rule) for rule in entry["rules"]]
                    if actual != expected[:len(actual)]:
                        raise ValueError("Guard chain ownership changed")
                    for rule in reversed(entry["rules"][:len(actual)]):
                        self.command(family, "-D", chain, *shlex.split(rule)[2:])
                    self.command(family, "-X", chain)
                    entry["created"] = False
                    entry["created_possible"] = False
                elif entry.get("created_possible"):
                    raise ValueError("Guard chain creation reply was ambiguous")
            except Exception:
                failures.append("guard")
        self.guard = [entry for entry in self.guard if entry["created"] or entry["jumped"]
                      or entry.get("created_possible")]
        for link in reversed(self.links):
            name, ifb = link["identity"]["name"], link["ifb"]
            for resource in reversed(tuple(link["installed"])):
                try:
                    current = self._cleanup_identity(name)
                    if (current is None or current["ifindex"] != link["identity"]["ifindex"]
                            or current["kind"] != link["identity"]["kind"]):
                        raise ValueError("Original link identity changed")
                    if resource == "ingress":
                        qdisc = self.command("tc", "qdisc", "show", "dev", name)
                        if "qdisc ingress ffff:" in qdisc:
                            if not link.get("ingress_confirmed"):
                                raise ValueError("Ambiguous ingress ownership")
                            filters = self.command("tc", "filter", "show", "dev", name, "parent", "ffff:")
                            if (link.get("filter_confirmed") and
                                    not self._ingress_filter_owned(filters, link)) or (
                                    not link.get("filter_confirmed") and filters.strip()):
                                raise ValueError("Foreign ingress filter")
                            self.command("tc", "qdisc", "del", "dev", name, "ingress")
                    elif resource == "egress":
                        qdisc = self.command("tc", "qdisc", "show", "dev", name).strip()
                        if "qdisc netem " + link["egress"] + " root" in qdisc:
                            if "delay 75ms 10ms" not in qdisc or "loss 0.1%" not in qdisc:
                                raise ValueError("Foreign root profile")
                            self.command("tc", "qdisc", "del", "dev", name, "root")
                        elif qdisc != link["before_qdisc"]:
                            raise ValueError("Foreign root qdisc")
                        if self.command("tc", "qdisc", "show", "dev", name).strip() != link["before_qdisc"]:
                            raise ValueError("Original root qdisc was not restored")
                    else:
                        current_ifb = self._cleanup_identity(ifb)
                        detail = self.command("ip", "-d", "link", "show", "dev", ifb)
                        if (not link.get("ifb_confirmed") or "ifb" not in detail
                                or current_ifb is None or current_ifb["kind"] != "ifb"
                                or current_ifb["ifindex"] != link.get("ifb_index")
                                or (link.get("alias_confirmed") and "alias " + link["alias"] not in detail)
                                or (not link.get("alias_confirmed") and "alias" in detail)):
                            raise ValueError("Foreign IFB")
                        self.command("ip", "link", "del", ifb)
                    link["installed"].remove(resource)
                except Exception:
                    failures.append(resource)
            if link["tag_possible"]:
                try:
                    current = self._cleanup_identity(name)
                    if (current is None or current["ifindex"] != link["identity"]["ifindex"]
                            or current["kind"] != link["identity"]["kind"]):
                        raise ValueError("Original link identity changed")
                    if current["group"] == self.group:
                        self.command("ip", "link", "set", "dev", name, "group", str(link["identity"]["group"]))
                        if self._cleanup_identity(name)["group"] != link["identity"]["group"]:
                            raise ValueError("Original link group was not restored")
                    elif current["group"] != link["identity"]["group"]:
                        raise ValueError("Foreign link group")
                    link["tag_possible"] = False
                except Exception:
                    failures.append("group")
        if failures:
            raise RuntimeError("Exact kernel fault cleanup is incomplete")

    def _cleanup_identity(self, name):
        """Read identity without requiring routes that may have drifted."""
        raw = self.command("ip", "-j", "-d", "link", "show")
        links = json.loads(raw)
        matches = [item for item in links if item.get("ifname") == name]
        if len(matches) != 1:
            return None
        item = matches[0]
        values = link_metadata(self.command, raw)[name]
        try: group = _numeric_group(item.get("group"))
        except LinkScopeError: return None
        if (values[0] != 1 or values[1] != item.get("ifindex")
                or values[2] != values[1] or values[3]
                or group != values[4]
                or type(item.get("linkinfo", {})) is not dict):
            return None
        return {"ifindex": values[1], "kind": item.get("linkinfo", {}).get("info_kind"),
                "group": values[4]}


class AndroidKernelPath:
    """Only the explicitly booted rootable CI emulator may execute these rules."""
    def __init__(self, peer, observation, turn_url, *, resolver=socket.getaddrinfo, diagnostics=None,
                 path_diagnostics=None, resource_check=None, control_urls=()):
        self.peer, self._blocked = peer, False
        self._negative_diagnostics = diagnostics
        self._path_diagnostics = path_diagnostics
        self._installed = []
        self._drop_rules = []
        self.rule = "mesh-ci-" + uuid4().hex[:12]
        self.ifb = "mci" + uuid4().hex[:12]
        self.filter_prio = 10000 + int(uuid4().hex[:4], 16) % 50000
        self.egress_handle = format(0x100 + int(uuid4().hex[:4], 16) % 0x7000, "x") + ":"
        self.ingress_handle = format(0x8000 + int(uuid4().hex[:4], 16) % 0x7000, "x") + ":"
        with path_stage(path_diagnostics, "kernel_relay_evidence"):
            relay_protocol = observation["pair"]["relay_protocol"]
            if observation["pair"]["local"]["type"] != "relay" or relay_protocol not in {"udp", "tcp", "tls"}:
                raise ValueError("Kernel faults require actual selected relay protocol evidence")
            self.protocol = "udp" if relay_protocol == "udp" else "tcp"
            self.relay_protocol = relay_protocol
            self.ip_protocol = "17" if self.protocol == "udp" else "6"
            self.endpoint_mode = relay_protocol in {"tcp", "tls"}
            self.uid_udp_mode = relay_protocol == "udp"
        with path_stage(path_diagnostics, "kernel_emulator_identity"):
            if peer._adb("shell", "id", "-u") != "0" or peer._adb("shell", "getprop", "ro.kernel.qemu") != "1":
                raise ValueError("Kernel fault injection requires the explicit rootable CI emulator")
        with path_stage(path_diagnostics, "kernel_turn_url"):
            if self.uid_udp_mode and (not isinstance(turn_url, str) or not turn_url.startswith("turn:")):
                raise ValueError("Selected UDP relay configuration is unavailable")
        with path_stage(path_diagnostics, "kernel_turn_resolution"):
            if self.endpoint_mode:
                addresses, port = turn_endpoints(turn_url, relay_protocol, resolver)
                control_endpoints = set()
                for control_url in control_urls:
                    parsed_control = urlsplit(control_url)
                    if parsed_control.scheme not in {"http", "https"} or not parsed_control.hostname:
                        raise ValueError("Control endpoint cannot be scoped")
                    control_port = (parsed_control.port if parsed_control.port is not None
                                    else (443 if parsed_control.scheme == "https" else 80))
                    if not 1 <= control_port <= 65535:
                        raise ValueError("Control endpoint port is invalid")
                    control_addresses = {scoped_address(item[4][0]) for item in
                        resolver(parsed_control.hostname, control_port, socket.AF_UNSPEC, socket.SOCK_STREAM)}
                    if not control_addresses or len(control_addresses) > MAX_TURN_ENDPOINTS:
                        raise ValueError("Control endpoint set is unavailable")
                    if control_port == port and set(addresses) & control_addresses:
                        raise ValueError("TURN and control endpoints overlap")
                    control_endpoints.update((address, control_port) for address in control_addresses)
                self.control_endpoints = frozenset(control_endpoints)
        with path_stage(path_diagnostics, "kernel_process_identity"):
            pid = peer._adb("shell", "pidof", peer.APP)
            if re.fullmatch(r"[0-9]{1,8}", pid) is None:
                raise ValueError("Native application process is ambiguous")
        self.pid = pid
        if self.endpoint_mode:
            with path_stage(path_diagnostics, "kernel_socket_inventory"):
                links = peer._adb("shell", "sh", "-c", f"'for f in /proc/{pid}/fd/*; do readlink \"$f\" 2>/dev/null || true; done'")
                inodes = set(re.findall(r"socket:\[([0-9]+)\]", links))
                tables = [peer._adb("shell", "cat", f"/proc/{pid}/net/{self.protocol}"),
                          peer._adb("shell", "cat", f"/proc/{pid}/net/{self.protocol}6")]
                self.addresses, self.port = addresses, port
            with path_stage(path_diagnostics, "kernel_socket_correlation"):
                self.matches = owned_turn_endpoints("\n".join(tables), inodes, addresses, port,
                    controls=self.control_endpoints, path_diagnostics=path_diagnostics)
                self.socket = None
        with path_stage(path_diagnostics, "kernel_process_uid"):
            status = peer._adb("shell", "cat", f"/proc/{pid}/status")
            uid = re.search(r"^Uid:\s+([0-9]+)\s", status, re.M)
            if uid is None:
                raise ValueError("Native application UID is unavailable")
            self.uid = uid[1]
        if self.endpoint_mode:
            self._resource_check = resource_check
            with path_stage(path_diagnostics, "kernel_scope_exclusivity"):
                self._check_scope()
            self.target_kind = "uid_tcp_turn_destination_set"
            self.target_material = [self.uid, self.protocol, self.port, self.addresses]
            self.rule_count = len(self.addresses)
        else:
            self._resource_check = resource_check
            with path_stage(path_diagnostics, "kernel_scope_exclusivity"):
                self._check_scope()
            with path_stage(path_diagnostics, "kernel_link_coverage"):
                try:
                    self.coverage = _BoundedUdpLinks(self)
                except LinkScopeError as error:
                    try: path_diagnostics.observe(error, "kernel_link_coverage", error.reason)
                    except Exception: pass
                    raise
                except Exception as error:
                    failure = LinkScopeError("capability_unavailable")
                    try: path_diagnostics.observe(failure, "kernel_link_coverage", failure.reason)
                    except Exception: pass
                    raise failure from error
            self.target_kind = "uid_udp_all_destinations"
            self.target_material = [self.uid, "udp", "all_destinations"]
            self.rule_count = 2

    def command(self, *args):
        return self.peer._adb("shell", *map(str, args))

    def _default_qdisc(self):
        value = self.command("tc", "qdisc", "show", "dev", self.device).strip()
        if (len(value.splitlines()) != 1
                or re.match(r"^qdisc (?:noqueue|pfifo_fast|fq_codel) 0: root(?:\s|$)", value) is None):
            raise LinkScopeError("conflicting_qdisc")
        return value

    def _link_current(self):
        if self.uid_udp_mode:
            try:
                self.coverage.current()
            except LinkScopeError as error:
                self._observe_link_error(error)
                raise
            return
        try:
            owned_ifb = self.ifb if "ifb" in self._installed else None
            if owned_ifb is not None:
                detail = self.command("ip", "-d", "link", "show", "dev", owned_ifb)
                if not re.search(r"\balias\s+" + re.escape(self.rule) + r"\b", detail):
                    raise LinkScopeError("alternate_link")
            if covered_link(*link_snapshot(self.command), owned_ifb=owned_ifb) != self.device:
                raise LinkScopeError("alternate_link")
            if self._installed:
                qdisc = self.command("tc", "qdisc", "show", "dev", self.device)
                ifb_qdisc = self.command("tc", "qdisc", "show", "dev", self.ifb)
                if ("qdisc netem " + self.egress_handle + " root" not in qdisc
                        or "qdisc ingress ffff:" not in qdisc
                        or "qdisc netem " + self.ingress_handle + " root" not in ifb_qdisc
                        or any(not all(field in value for field in ("delay 75ms 10ms", "loss 0.1%"))
                               for value in (qdisc, ifb_qdisc))
                        or not self._owned_ingress_filter(self.command("tc", "filter", "show", "dev",
                            self.device, "parent", "ffff:"))):
                    raise LinkScopeError("conflicting_qdisc")
        except LinkScopeError as error:
            self._observe_link_error(error)
            raise
        except Exception as error:
            failure = LinkScopeError("capability_unavailable")
            self._observe_link_error(failure)
            raise failure from error

    def _observe_link_error(self, error):
        try:
            reason = error.reason if type(error) is LinkScopeError else "capability_unavailable"
            self._path_diagnostics.observe(error, "kernel_link_coverage", reason)
        except Exception:
            pass

    def _owned_ingress_filter(self, value):
        lines = value.splitlines()
        headers = [line for line in lines if line.lstrip().startswith("filter ")]
        actions = [line for line in lines if re.search(r"\baction\b", line)]
        marker = "pref " + str(self.filter_prio) + " matchall"
        return (bool(headers) and len(headers) <= 2
            and all("protocol all" in line and marker in line for line in headers)
            and len(actions) == 1 and "mirred" in actions[0]
            and "redirect" in actions[0].lower()
            and re.search(r"\b" + re.escape(self.ifb) + r"\b", actions[0]) is not None)

    def _check_scope(self):
        if not callable(self._resource_check) or self._resource_check() is not True:
            raise ValueError("Native endpoint block lacks one current resource")
        packages = self.command("pm", "list", "packages", "-U")
        package_lines = packages.splitlines()
        if not package_lines or any(re.fullmatch(r"package:([^\s]+)\s+uid:([0-9]+)", line) is None
                                    for line in package_lines):
            raise ValueError("Native package UID inventory is unavailable")
        owners = re.findall(r"^package:([^\s]+)\s+uid:([0-9]+)$", packages, re.M)
        if [name for name, uid in owners if uid == self.uid] != [self.peer.APP]:
            raise ValueError("Native endpoint block UID is not package-exclusive")
        owned = self._same_uid_processes()
        if owned == [self.pid]:
            return
        if len(owned) != 2 or self.pid not in owned:
            raise ValueError("Native endpoint block UID is not process-exclusive")
        helper = next(pid for pid in owned if pid != self.pid)
        try:
            cmdline = self.command("cat", f"/proc/{helper}/cmdline")
            if cmdline.split("\0", 1)[0] != self.peer.APP + ":mesh_bootstrap":
                raise ValueError("Native endpoint block UID has an unrecognized helper")
            if self.endpoint_mode:
                self._check_helper_tcp(helper)
        except Exception:
            # The bootstrap service may exit between ps and its proc reads.
            if self._same_uid_processes() == [self.pid]:
                return
            raise

    def _same_uid_processes(self):
        processes = self.command("ps", "-A", "-o", "UID,PID")
        process_lines = processes.splitlines()
        if (not process_lines or process_lines[0].split() != ["UID", "PID"]
                or any(re.fullmatch(r"\s*([0-9]+)\s+([0-9]+)\s*", line) is None
                       for line in process_lines[1:])):
            raise ValueError("Native process UID inventory is unavailable")
        owned = [pid for uid, pid in re.findall(r"^\s*([0-9]+)\s+([0-9]+)\s*$", processes, re.M)
                 if uid == self.uid]
        return owned

    def _check_helper_tcp(self, helper):
        links = self.command("sh", "-c", f"'for f in /proc/{helper}/fd/*; do readlink \"$f\" 2>/dev/null || true; done'")
        inodes = set(re.findall(r"socket:\[([0-9]+)\]", links))
        tables = [self.command("cat", f"/proc/{helper}/net/tcp"),
                  self.command("cat", f"/proc/{helper}/net/tcp6")]
        for table in tables:
            for line in table.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 10 or parts[9] not in inodes:
                    continue
                remote, port = ipv4_proc(parts[2])
                if port and not ipaddress.ip_address(remote).is_loopback:
                    raise ValueError("Native bootstrap helper owns an external TCP socket")

    def _owned_tcp_matches(self, *, allow_empty=False):
        links = self.command("sh", "-c", f"'for f in /proc/{self.pid}/fd/*; do readlink \"$f\" 2>/dev/null || true; done'")
        inodes = set(re.findall(r"socket:\[([0-9]+)\]", links))
        tables = [self.command("cat", f"/proc/{self.pid}/net/tcp"),
                  self.command("cat", f"/proc/{self.pid}/net/tcp6")]
        return owned_turn_endpoints("\n".join(tables), inodes, self.addresses, self.port,
                                    controls=self.control_endpoints, allow_empty=allow_empty)

    def _match(self, inbound=False):
        value = self.socket
        source, destination = (value["remote"], value["local"]) if inbound else (value["local"], value["remote"])
        sport, dport = (value["remote_port"], value["local_port"]) if inbound else (value["local_port"], value["remote_port"])
        return ["match", "ip", "protocol", self.ip_protocol, "0xff", "match", "ip", "src", source + "/32",
                "match", "ip", "dst", destination + "/32", "match", "ip", "sport", str(sport), "0xffff",
                "match", "ip", "dport", str(dport), "0xffff"]

    def install(self):
        if self.protocol != "udp":
            raise ValueError("The declared impairment profile requires the selected UDP path")
        if self.uid_udp_mode:
            try:
                self.coverage.install()
            except Exception as error:
                self._observe_link_error(error)
                raise
            return
        try:
            self.command("ip", "link", "add", self.ifb, "type", "ifb")
            self._installed.append("ifb")
            self.command("ip", "link", "set", self.ifb, "up")
            self.command("tc", "qdisc", "replace", "dev", self.device, "root", "handle", "1:", "prio", "bands", "3")
            self._installed.append("egress")
            self.command("tc", "qdisc", "add", "dev", self.device, "parent", "1:3", "handle", "30:",
                         "netem", "delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%")
            self.command("tc", "filter", "add", "dev", self.device, "protocol", "ip", "parent", "1:",
                         "prio", "1", "u32", *self._match(), "flowid", "1:3")
            self.command("tc", "qdisc", "add", "dev", self.device, "handle", "ffff:", "ingress")
            self._installed.append("ingress")
            self.command("tc", "filter", "add", "dev", self.device, "parent", "ffff:", "protocol", "ip",
                         "prio", "1", "u32", *self._match(True), "action", "mirred", "egress", "redirect", "dev", self.ifb)
            self.command("tc", "qdisc", "add", "dev", self.ifb, "root", "handle", "40:",
                         "netem", "delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%")
            self.before = self.counters()
        except Exception:
            self.close()
            raise

    def counters(self):
        if self.uid_udp_mode:
            return self.coverage.counters()
        return {"egress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", self.device), self.egress_handle),
                "ingress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", self.ifb), self.ingress_handle)}

    def block(self):
        self.require_current()
        if self.endpoint_mode or self.uid_udp_mode:
            observer = getattr(self, "_negative_diagnostics", None)
            try:
                with negative_control_stage(observer, "kernel_block_install"):
                    targets = (("iptables" if ipaddress.ip_address(address).version == 4 else "ip6tables", address)
                        for address in self.addresses) if self.endpoint_mode else (("iptables", None), ("ip6tables", None))
                    for index, (family, address) in enumerate(targets):
                        comment = self.rule + "-" + str(index)
                        args = (["-p", "tcp", "-d", address, "--dport", str(self.port)] if self.endpoint_mode
                                else ["-p", "udp"])
                        args += [
                                "-m", "owner", "--uid-owner", self.uid,
                                "-m", "comment", "--comment", comment, "-j", "DROP"]
                        if self.uid_udp_mode:
                            existing = self.command(family, "-nvx", "-L", "OUTPUT", "--line-numbers")
                            if any(comment in line.split() for line in existing.splitlines()):
                                raise ValueError("Kernel block comment is already owned")
                        # Retain possible exact ownership before the insert: an ADB
                        # error cannot prove that the kernel rejected the rule.
                        self._drop_rules.append((family, args, comment))
                        self._blocked = True
                        self.command(family, "-I", "OUTPUT", "1", *args)
                        self.command(family, "-C", "OUTPUT", *args)
                    self._counter_before = self._endpoint_counters()
                    self.require_current()
            except Exception:
                self._delete_endpoint_rules()
                raise
            return
        value = self.socket
        self.drop_args = ["-p", self.protocol, "-s", value["local"], "--sport", str(value["local_port"]),
            "-d", value["remote"], "--dport", str(value["remote_port"]), "-m", "owner", "--uid-owner", self.uid,
            "-m", "comment", "--comment", self.rule, "-j", "DROP"]
        with negative_control_stage(getattr(self, "_negative_diagnostics", None), "kernel_block_install"):
            self.command("iptables", "-I", "OUTPUT", "1", *self.drop_args)
        self._blocked = True

    def unblock(self):
        if not self._blocked:
            return 0
        observer = getattr(self, "_negative_diagnostics", None)
        if self.endpoint_mode or self.uid_udp_mode:
            current = True
            try:
                with negative_control_stage(observer, "kernel_counter_read"):
                    after = self._endpoint_counters()
                with negative_control_stage(observer, "kernel_counter_parse"):
                    deltas = [after[comment] - self._counter_before[comment]
                              for _, _, comment in self._drop_rules]
                    if any(value < 0 for value in deltas):
                        raise negative_control_error(observer, "kernel_counter_parse",
                            ValueError("Exact endpoint block counter changed unexpectedly"), "counter_unavailable")
                    packets = sum(deltas)
                try: self.require_current()
                except Exception: current = False
            finally:
                self._delete_endpoint_rules()
            if not current:
                raise negative_control_error(observer, "kernel_restore_current",
                    ValueError("The blocked native endpoint scope changed before restoration"), "current_check_failed")
            return packets
        current = True
        try:
            with negative_control_stage(observer, "kernel_counter_read"):
                text = self.command("iptables", "-nvx", "-L", "OUTPUT", "--line-numbers")
            with negative_control_stage(observer, "kernel_counter_parse"):
                lines = [line.split() for line in text.splitlines() if self.rule in line]
                if len(lines) != 1 or len(lines[0]) < 4 or lines[0][3] != "DROP":
                    raise negative_control_error(observer, "kernel_counter_parse",
                        ValueError("Exact kernel block rule counter is unavailable"), "counter_unavailable")
                packets = int(lines[0][1])
            try: self.require_current()
            except Exception: current = False
        finally:
            with negative_control_stage(observer, "kernel_restore_delete"):
                self.command("iptables", "-D", "OUTPUT", *self.drop_args)
            self._blocked = False
        if not current:
            raise negative_control_error(observer, "kernel_restore_current",
                ValueError("The blocked native kernel socket changed before restoration"), "current_check_failed")
        return packets

    def _endpoint_counters(self):
        counters = {}
        for family, args, comment in self._drop_rules:
            with negative_control_stage(self._negative_diagnostics, "kernel_counter_read"):
                if self.uid_udp_mode:
                    self.command(family, "-C", "OUTPUT", *args)
                text = self.command(family, "-nvx", "-L", "OUTPUT", "--line-numbers")
            with negative_control_stage(self._negative_diagnostics, "kernel_counter_parse"):
                lines = [line.split() for line in text.splitlines() if comment in line.split()]
                if len(lines) != 1 or len(lines[0]) < 4 or lines[0][3] != "DROP":
                    raise negative_control_error(self._negative_diagnostics, "kernel_counter_parse",
                        ValueError("Exact endpoint block counter is unavailable"), "counter_unavailable")
                counters[comment] = int(lines[0][1])
        return counters

    def _delete_endpoint_rules(self):
        observer = getattr(self, "_negative_diagnostics", None)
        first_error = None
        remaining = []
        for family, args, comment in reversed(self._drop_rules):
            delete_error = None
            try:
                with negative_control_stage(observer, "kernel_restore_delete"):
                    self.command(family, "-D", "OUTPUT", *args)
            except Exception as error:
                delete_error = error
            try:
                with negative_control_stage(observer, "kernel_restore_delete"):
                    listing = self.command(family, "-nvx", "-L", "OUTPUT", "--line-numbers")
                    if any(comment in line.split() for line in listing.splitlines()):
                        raise delete_error or ValueError("Exact endpoint block rule remains installed")
            except Exception as error:
                if first_error is None: first_error = error
                remaining.append((family, args, comment))
        self._drop_rules = list(reversed(remaining))
        self._blocked = bool(self._drop_rules)
        if first_error is not None:
            negative_control_error(observer, "kernel_restore_delete", first_error)
            raise first_error

    def require_current(self):
        observer = getattr(self, "_negative_diagnostics", None)
        with negative_control_stage(observer, "kernel_current_process"):
            if self.peer._adb("shell", "pidof", self.peer.APP) != self.pid:
                raise negative_control_error(observer, "kernel_current_process",
                    ValueError("The native process changed during kernel fault correlation"), "process_changed")
        if self.endpoint_mode or self.uid_udp_mode:
            with negative_control_stage(observer, "kernel_current_socket"):
                status = self.command("cat", f"/proc/{self.pid}/status")
                uid = re.search(r"^Uid:\s+([0-9]+)\s", status, re.M)
                if uid is None or uid[1] != self.uid:
                    raise negative_control_error(observer, "kernel_current_socket",
                        ValueError("The native endpoint UID changed"), "socket_changed")
                self._check_scope()
                if self.endpoint_mode:
                    self._owned_tcp_matches(allow_empty=self._blocked)
                else:
                    self._link_current()
            return
        with negative_control_stage(observer, "kernel_current_socket"):
            links = self.command("sh", "-c", f"'for f in /proc/{self.pid}/fd/*; do readlink \"$f\" 2>/dev/null || true; done'")
            inodes = set(re.findall(r"socket:\[([0-9]+)\]", links))
            tables = [self.command("cat", f"/proc/{self.pid}/net/{self.protocol}"),
                      self.command("cat", f"/proc/{self.pid}/net/{self.protocol}6")]
            try: conntrack = self.command("cat", "/proc/net/nf_conntrack") if self.protocol == "udp" else ""
            except Exception: conntrack = ""
            if owned_socket("\n".join(tables), inodes, self.addresses, self.port, conntrack) != self.socket:
                raise negative_control_error(observer, "kernel_current_socket",
                    ValueError("The native kernel socket changed during its selected-path test"), "socket_changed")

    def report(self):
        if self.uid_udp_mode:
            self.require_current()
            return self.coverage.report()
        after = self.counters()
        delta = {direction: {key: after[direction][key] - self.before[direction][key]
                            for key in ("bytes", "packets", "dropped")} for direction in ("egress", "ingress")}
        if (any(count < 0 for item in delta.values() for count in item.values())
                or any(item["bytes"] <= 0 or item["packets"] <= 0 for item in delta.values())):
            raise ValueError("Kernel impairment lacks actual routed packets and observed loss")
        return {"kind": "android_emulator_linux_kernel_tc_netem", "delay_ms_each_way": 75,
                "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                "link_scope": "isolated_emulator_route",
                "loss_observed": sum(item["dropped"] for item in delta.values()) > 0, "counters": delta}

    def _close_link(self):
        if self.uid_udp_mode:
            failures = []
            try:
                if self._blocked:
                    self._delete_endpoint_rules()
            except Exception:
                failures.append("block")
            try:
                self.coverage.close()
            except Exception:
                failures.append("coverage")
            if failures:
                raise negative_control_error(getattr(self, "_negative_diagnostics", None),
                    "fault_cleanup", RuntimeError("Exact kernel fault cleanup is incomplete"),
                    "cleanup_incomplete")
            return
        failures = []
        try:
            if self._blocked:
                self._delete_endpoint_rules()
        except Exception:
            failures.append("block")
        for item in reversed(self._installed):
            try:
                if item == "ingress":
                    current = self.command("tc", "qdisc", "show", "dev", self.device)
                    if "qdisc ingress ffff:" in current:
                        if not getattr(self, "_ingress_confirmed", False):
                            raise ValueError("Ingress creation reply was ambiguous")
                        filters = self.command("tc", "filter", "show", "dev", self.device, "parent", "ffff:")
                        if (filters.strip() and not self._owned_ingress_filter(filters)) or (
                                not filters.strip() and getattr(self, "_ingress_filter_complete", False)):
                            raise ValueError("Ingress filter ownership changed")
                        self.command("tc", "qdisc", "del", "dev", self.device, "ingress")
                    if "qdisc ingress ffff:" in self.command("tc", "qdisc", "show", "dev", self.device):
                        raise ValueError("Owned ingress qdisc remains")
                elif item == "egress":
                    current = self.command("tc", "qdisc", "show", "dev", self.device).strip()
                    if "qdisc netem " + self.egress_handle + " root" in current:
                        if not all(item in current for item in ("delay 75ms 10ms", "loss 0.1%")):
                            raise ValueError("Root netem ownership changed")
                        self.command("tc", "qdisc", "del", "dev", self.device, "root")
                    elif current != self._qdisc_before:
                        raise ValueError("Unrecognized root qdisc cannot be removed")
                    if self.command("tc", "qdisc", "show", "dev", self.device).strip() != self._qdisc_before:
                        raise ValueError("Original root qdisc was not restored")
                else:
                    if self.ifb in link_names(self.command("ip", "-o", "link", "show")):
                        if not getattr(self, "_ifb_add_confirmed", False):
                            raise ValueError("IFB creation reply was ambiguous")
                        detail = self.command("ip", "-d", "link", "show", "dev", self.ifb)
                        has_alias = re.search(r"\balias\s+" + re.escape(self.rule) + r"\b", detail)
                        if (not has_alias and (not getattr(self, "_ifb_add_confirmed", False)
                                or not getattr(self, "_ifb_prechecked_absent", False)
                                or re.search(r"\bifb\b", detail) is None or re.search(r"\balias\b", detail))):
                            raise ValueError("Owned IFB identity changed")
                        self.command("ip", "link", "del", self.ifb)
                    if self.ifb in link_names(self.command("ip", "-o", "link", "show")):
                        raise ValueError("Owned IFB remains")
            except Exception:
                failures.append(item)
        self._installed = [item for item in self._installed if item in failures]
        if failures:
            raise negative_control_error(getattr(self, "_negative_diagnostics", None), "fault_cleanup",
                RuntimeError("Exact kernel fault cleanup is incomplete"), "cleanup_incomplete")

    def close(self):
        if self.uid_udp_mode:
            self._close_link()
            return
        failures = []
        try:
            if self._blocked:
                if self.endpoint_mode: self._delete_endpoint_rules()
                else: self.unblock()
        except Exception: failures.append("block")
        for item in reversed(self._installed):
            try:
                if item == "ingress": self.command("tc", "qdisc", "del", "dev", self.device, "ingress")
                elif item == "egress": self.command("tc", "qdisc", "del", "dev", self.device, "root")
                else: self.command("ip", "link", "del", self.ifb)
            except Exception: failures.append(item)
        self._installed = [item for item in self._installed if item in failures]
        if failures:
            raise negative_control_error(getattr(self, "_negative_diagnostics", None), "fault_cleanup",
                RuntimeError("Exact kernel fault cleanup is incomplete"), "cleanup_incomplete")
