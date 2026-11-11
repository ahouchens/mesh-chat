"""CI-only exact Android Linux-kernel path faults, with actual packet counters.

Addresses/socket inodes stay transient. No application packet substitution,
sleep-based loss model, TURN advertisement inference, or unrelated-host rule.
"""

import ipaddress
from contextlib import contextmanager, nullcontext
import re
import socket
from urllib.parse import urlsplit
from uuid import uuid4

from native_interop_diagnostics import negative_control_error, negative_control_stage


PATH_FAILURE_REASONS = {
    "kernel_relay_evidence": frozenset(), "kernel_emulator_identity": frozenset(),
    "kernel_turn_url": frozenset(), "kernel_turn_resolution": frozenset(),
    "kernel_process_identity": frozenset(), "kernel_socket_inventory": frozenset(),
    "kernel_socket_parse": frozenset(),
    "kernel_socket_correlation": frozenset({"no_owned_match", "ambiguous_owned_matches"}),
    "kernel_process_uid": frozenset(), "kernel_socket_route": frozenset(),
    "receipt_enqueue": frozenset(), "receipt_delivery_wait": frozenset(),
    "receipt_inbound_wait": frozenset(), "receipt_outbound_records": frozenset(),
    "receipt_record_validation": frozenset(),
}
PATH_FAILURE_SCENARIOS = frozenset({"direct", "turn_udp", "turn_tcp", "turn_tls", "impaired"})


def path_failure_observation(value):
    if (type(value) is not dict or not {"scenario", "stage"} <= set(value)
            or set(value) - {"scenario", "stage", "reason"}
            or type(value["scenario"]) is not str or value["scenario"] not in PATH_FAILURE_SCENARIOS
            or type(value["stage"]) is not str or value["stage"] not in PATH_FAILURE_REASONS):
        return {}
    if "reason" in value and (type(value["reason"]) is not str
            or value["reason"] not in PATH_FAILURE_REASONS[value["stage"]]):
        return {}
    return dict(value)


class NativePathDiagnostics:
    """One private escaping-error label; no kernel values or exception text."""
    def __init__(self, scenario):
        self.scenario = scenario if scenario in PATH_FAILURE_SCENARIOS else None
        self._failure = None

    def observe(self, error, stage, reason=None):
        if self._failure is not None and self._failure[0] is error:
            return  # A nested, more exact source check already selected this error.
        selected = path_failure_observation({"scenario": self.scenario, "stage": stage,
            **({"reason": reason} if reason is not None else {})})
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


def owned_socket(table, inodes, allowed_addresses, port, conntrack="", *, path_diagnostics=None):
    matches = []
    for line in table.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10 or parts[9] not in inodes:
            continue
        with path_stage(path_diagnostics, "kernel_socket_parse"):
            local, local_port = ipv4_proc(parts[1])
            remote, remote_port = ipv4_proc(parts[2])
        if remote in allowed_addresses and remote_port == port and local_port:
            matches.append({"local": local, "local_port": local_port, "remote": remote, "remote_port": remote_port, "inode": parts[9]})
        elif remote_port == 0 and local_port:
            for flow in conntrack.splitlines():
                match = re.search(r"\bsrc=([0-9.]+) dst=([0-9.]+) sport=([0-9]+) dport=([0-9]+)\b", flow)
                if match and int(match[3]) == local_port and match[2] in allowed_addresses and int(match[4]) == port:
                    source = str(ipaddress.IPv4Address(match[1]))
                    if local not in {"0.0.0.0", source}: continue
                    matches.append({"local": source, "local_port": local_port, "remote": match[2], "remote_port": port, "inode": parts[9]})
    if len(matches) != 1:
        error = ValueError("Selected TURN path lacks one unambiguous own-process kernel socket")
        if type(path_diagnostics) is NativePathDiagnostics:
            try: path_diagnostics.observe(error, "kernel_socket_correlation",
                "no_owned_match" if not matches else "ambiguous_owned_matches")
            except Exception: pass
        raise error
    return matches[0]


def netem_counter(text, handle):
    match = re.search(r"qdisc netem " + re.escape(handle) + r"[^\n]*\n\s*Sent ([0-9]+) bytes ([0-9]+) pkt \(dropped ([0-9]+),", text)
    if match is None:
        raise ValueError("Kernel netem packet counter is unavailable")
    return dict(zip(("bytes", "packets", "dropped"), map(int, match.groups())))


class AndroidKernelPath:
    """Only the explicitly booted rootable CI emulator may execute these rules."""
    def __init__(self, peer, observation, turn_url, *, resolver=socket.getaddrinfo, diagnostics=None,
                 path_diagnostics=None):
        self.peer, self._blocked = peer, False
        self._negative_diagnostics = diagnostics
        self._installed = []
        self.rule = "mesh-ci-" + uuid4().hex[:12]
        self.ifb = "mci" + uuid4().hex[:8]
        with path_stage(path_diagnostics, "kernel_relay_evidence"):
            relay_protocol = observation["pair"]["relay_protocol"]
            if observation["pair"]["local"]["type"] != "relay" or relay_protocol not in {"udp", "tcp", "tls"}:
                raise ValueError("Kernel faults require actual selected relay protocol evidence")
            self.protocol = "udp" if relay_protocol == "udp" else "tcp"
            self.ip_protocol = "17" if self.protocol == "udp" else "6"
        with path_stage(path_diagnostics, "kernel_emulator_identity"):
            if peer._adb("shell", "id", "-u") != "0" or peer._adb("shell", "getprop", "ro.kernel.qemu") != "1":
                raise ValueError("Kernel fault injection requires the explicit rootable CI emulator")
        with path_stage(path_diagnostics, "kernel_turn_url"):
            parsed = urlsplit("//" + turn_url.split(":", 1)[-1])
            if not turn_url.startswith(("turn:", "turns:")) or not parsed.hostname:
                raise ValueError("Required selected TURN URL is unavailable")
            port = parsed.port or (5349 if turn_url.startswith("turns:") else 3478)
        with path_stage(path_diagnostics, "kernel_turn_resolution"):
            addresses = {item[4][0] for item in resolver(parsed.hostname, port, socket.AF_INET,
                         socket.SOCK_DGRAM if self.protocol == "udp" else socket.SOCK_STREAM)}
        with path_stage(path_diagnostics, "kernel_process_identity"):
            pid = peer._adb("shell", "pidof", peer.APP)
            if re.fullmatch(r"[0-9]{1,8}", pid) is None:
                raise ValueError("Native application process is ambiguous")
        # Only descriptors actually owned by this native app PID may correlate
        # a selected protocol with the kernel path. Reject ambiguous sockets.
        with path_stage(path_diagnostics, "kernel_socket_inventory"):
            links = peer._adb("shell", "sh", "-c", f"'for f in /proc/{pid}/fd/*; do readlink \"$f\" 2>/dev/null || true; done'")
            inodes = set(re.findall(r"socket:\[([0-9]+)\]", links))
            tables = [peer._adb("shell", "cat", f"/proc/{pid}/net/{self.protocol}"),
                      peer._adb("shell", "cat", f"/proc/{pid}/net/{self.protocol}6")]
            self.pid, self.addresses, self.port = pid, addresses, port
            try: conntrack = peer._adb("shell", "cat", "/proc/net/nf_conntrack") if self.protocol == "udp" else ""
            except Exception: conntrack = ""
        with path_stage(path_diagnostics, "kernel_socket_correlation"):
            self.socket = owned_socket("\n".join(tables), inodes, addresses, port, conntrack,
                                       path_diagnostics=path_diagnostics)
        with path_stage(path_diagnostics, "kernel_process_uid"):
            status = peer._adb("shell", "cat", f"/proc/{pid}/status")
            uid = re.search(r"^Uid:\s+([0-9]+)\s", status, re.M)
            if uid is None:
                raise ValueError("Native application UID is unavailable")
            self.uid = uid[1]
        with path_stage(path_diagnostics, "kernel_socket_route"):
            route = peer._adb("shell", "ip", "route", "get", self.socket["remote"])
            device = re.search(r"\bdev ([A-Za-z0-9_.-]{1,15})\b", route)
            if device is None:
                raise ValueError("Selected socket's kernel route is unavailable")
            self.device = device[1]

    def command(self, *args):
        return self.peer._adb("shell", *map(str, args))

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
        return {"egress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", self.device), "30:"),
                "ingress": netem_counter(self.command("tc", "-s", "qdisc", "show", "dev", self.ifb), "40:")}

    def block(self):
        self.require_current()
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
        with negative_control_stage(observer, "kernel_counter_read"):
            text = self.command("iptables", "-nvx", "-L", "OUTPUT", "--line-numbers")
        with negative_control_stage(observer, "kernel_counter_parse"):
            lines = [line.split() for line in text.splitlines() if self.rule in line]
            if len(lines) != 1 or len(lines[0]) < 4 or lines[0][3] != "DROP":
                raise negative_control_error(observer, "kernel_counter_parse",
                    ValueError("Exact kernel block rule counter is unavailable"), "counter_unavailable")
            packets = int(lines[0][1])
        current = True
        try: self.require_current()
        except Exception: current = False
        with negative_control_stage(observer, "kernel_restore_delete"):
            self.command("iptables", "-D", "OUTPUT", *self.drop_args)
        self._blocked = False
        if not current:
            raise negative_control_error(observer, "kernel_restore_current",
                ValueError("The blocked native kernel socket changed before restoration"), "current_check_failed")
        return packets

    def require_current(self):
        observer = getattr(self, "_negative_diagnostics", None)
        with negative_control_stage(observer, "kernel_current_process"):
            if self.peer._adb("shell", "pidof", self.peer.APP) != self.pid:
                raise negative_control_error(observer, "kernel_current_process",
                    ValueError("The native process changed during kernel fault correlation"), "process_changed")
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
        after = self.counters()
        delta = {direction: {key: after[direction][key] - self.before[direction][key]
                            for key in ("bytes", "packets", "dropped")} for direction in ("egress", "ingress")}
        if (any(count < 0 for item in delta.values() for count in item.values())
                or any(item["bytes"] <= 0 or item["packets"] <= 0 for item in delta.values())):
            raise ValueError("Kernel impairment lacks actual routed packets and observed loss")
        return {"kind": "android_emulator_linux_kernel_tc_netem", "delay_ms_each_way": 75,
                "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                "socket_correlation": "unique_own_pid_socket_and_kernel_flow",
                "loss_observed": sum(item["dropped"] for item in delta.values()) > 0, "counters": delta}

    def close(self):
        failures = []
        try:
            if self._blocked: self.unblock()
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
