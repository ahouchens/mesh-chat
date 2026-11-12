"""Manual Linux/KVM gateway capability check; never native qualification.

The runner owns a disposable namespace and veth pair. Android's queue policy is
untouched. The unprivileged namespace child owns ADB and the emulator; its UDP
client is the real Android guest, not a host substitute.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import selectors
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from uuid import uuid4

from native_interop_network_probe import Emulator, SERIAL, _collect_process, _image_revision, _source_identity


class Unavailable(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Unavailable(reason)


def namespace_inode(pid):
    return os.stat(f"/proc/{pid}/ns/net").st_ino


def process_identity(pid):
    root = Path(f"/proc/{pid}")
    try:
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "start": fields[19], "uid": root.stat().st_uid,
                "namespace": namespace_inode(pid), "executable": str((root / "exe").resolve(strict=True))}
    except (FileNotFoundError, ProcessLookupError):
        return None


def process_parent(pid):
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except FileNotFoundError:
        return None


def same_process(left, right):
    return left is not None and all(left[key] == right[key] for key in ("pid", "start", "uid", "namespace"))


def retire_exact_process(identity, descriptor, *, reader=None, force=False):
    reader = reader or process_identity
    for kind in ((signal.SIGKILL,) if force else (signal.SIGTERM, signal.SIGKILL)):
        if select.select([descriptor], [], [], 0)[0]:
            return
        current = reader(identity["pid"])
        if current is None:
            return
        require(same_process(current, identity), "helper_process_identity_changed")
        try:
            signal.pidfd_send_signal(descriptor, kind)
        except ProcessLookupError:
            return
        if select.select([descriptor], [], [], 5)[0]:
            return
    raise Unavailable("helper_process_remains")


def wait_for_guest_echo(child, gateway, port, attempts):
    for attempt in range(attempts):
        if child.echo(gateway, port):
            return True
        if attempt + 1 < attempts:
            time.sleep(5)
    return False


def firewall_shape(text):
    return "\n".join(re.sub(r"^(\S+\s+\S+) \[[0-9]+:[0-9]+\]$", r"\1 [counters]", line)
                     if line.startswith(":") else line
                     for line in text.splitlines() if not line.startswith("#"))


def rule_tokens(tokens):
    result = list(tokens)
    if "--ctstate" in result:
        index = result.index("--ctstate") + 1
        result[index] = ",".join(sorted(result[index].split(",")))
    # iptables -S prints base selectors in canonical order, independently of
    # their input order. Preserve extension order and every option/value.
    if len(result) < 2 or result[0] != "-A":
        return tuple(result)
    base, extensions = [], []
    index = 2
    while index < len(result):
        if result[index] in {"-s", "-d", "-i", "-o", "-p"} and index + 1 < len(result):
            base.append((result[index], result[index + 1]))
            index += 2
        else:
            extensions.append(result[index])
            index += 1
    return tuple(result[:2]), tuple(sorted(base)), tuple(extensions)


def counter_delta(before, after):
    require(before.keys() == after.keys(), "counter_shape_changed")
    result = {}
    for name in before:
        require(type(before[name]) is int and type(after[name]) is int
                and 0 <= before[name] <= after[name], "counter_regression")
        result[name] = after[name] - before[name]
    return result


def parse_netem(text, handle):
    pattern = (r"(?m)^qdisc netem " + re.escape(handle)
               + r" root[^\n]*delay 75ms\s+10ms[^\n]*loss 0\.1%[^\n]*\n"
               + r"\s*Sent ([0-9]+) bytes ([0-9]+) pkt \(dropped ([0-9]+),")
    matches = re.findall(pattern, text)
    require(len(matches) == 1, "owned_netem_profile_unavailable")
    return dict(zip(("bytes", "packets", "dropped"), map(int, matches[0])))


class Commands:
    def __init__(self, report):
        self.report = report
        self.kept = 0
        self.deadline = None

    def run(self, *args, privileged=False, timeout=10):
        argv = (["sudo", "-n"] if privileged else []) + list(map(str, args))
        require(len(self.report["commands"]) < 400, "command_budget_exhausted")
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            require(timeout > 0, "probe_deadline_exceeded")
        value = _collect_process(argv, timeout=timeout, stdout_limit=16384, stderr_limit=2048)
        self.kept += len(value["stdout"].encode()) + len(value["stderr"].encode())
        require(self.kept <= 256 * 1024, "capture_budget_exhausted")
        self.report["commands"].append({"argv": argv, **value})
        require(value["exit_code"] == 0 and not value["timed_out"]
                and not value["stdout_truncated"] and not value["stderr_truncated"], "command_unavailable")
        return value["stdout"].strip()


class Gateway:
    def __init__(self, commands):
        self.commands = commands
        self.token = "mg" + uuid4().hex[:10]
        self.ns, self.host, self.guest = self.token, self.token + "h", self.token + "g"
        self.chain = self.token.upper()
        self.resources = []
        self.rules = []
        self.identities = {}
        self.netns_inode = None
        self.dns_path = Path("/etc/netns") / self.ns
        self.handles = {self.host: "a101:", self.guest: "a102:"}

    def run(self, *args):
        return self.commands.run(*args, privileged=True)

    def inside(self, *args):
        self.check_namespace()
        return self.run("ip", "netns", "exec", self.ns, *args)

    def check_namespace(self):
        if self.netns_inode is not None:
            require(Path("/run/netns", self.ns).stat().st_ino == self.netns_inode, "namespace_identity_changed")

    def link(self, name):
        command = self.inside if name == self.guest else self.run
        rows = json.loads(command("ip", "-j", "-d", "link", "show", "dev", name))
        require(len(rows) == 1 and rows[0]["ifname"] == name
                and rows[0].get("linkinfo", {}).get("info_kind") == "veth", "veth_identity_unavailable")
        peer = command("cat", "/sys/class/net/" + name + "/iflink")
        require(peer.isdigit() and int(peer) > 0, "veth_peer_identity_unavailable")
        if "link_index" in rows[0]:
            require(rows[0]["link_index"] == int(peer), "veth_peer_identity_changed")
        else:
            require(rows[0].get("link") == (self.guest if name == self.host else self.host),
                    "veth_peer_name_unavailable")
        rows[0]["link_index"] = int(peer)
        return rows[0]

    def check_links(self):
        self.check_namespace()
        for name, identity in self.identities.items():
            current = self.link(name)
            require(current["ifindex"] == identity["ifindex"]
                    and current.get("link_index") == identity.get("link_index")
                    and current.get("ifalias") == self.token, "veth_identity_changed")
        rows = json.loads(self.inside("ip", "-j", "link", "show"))
        require({row["ifname"] for row in rows} == {"lo", self.guest}, "alternate_namespace_link")
        require(self.inside("sysctl", "-n", "net.ipv6.conf.all.disable_ipv6") == "1", "ipv6_not_disabled")
        routes = json.loads(self.inside("ip", "-j", "-4", "route", "show", "table", "all"))
        require(all(row.get("dev", "lo") in {"lo", self.guest} for row in routes), "alternate_namespace_route")
        defaults = [row for row in routes if row.get("dst") == "default"]
        require(len(defaults) == 1 and defaults[0].get("gateway") == self.host_ip
                and defaults[0].get("dev") == self.guest, "namespace_default_changed")

    def add_rule(self, table, chain, *args):
        # Reserve the exact rollback obligation before attempting a mutation.
        rule = (table, chain, tuple(args))
        self.rules.append(rule)
        self.run("iptables", "-w", "5", "-t", table, "-I", chain, "1", *args)

    def prepare_dns_directory(self):
        parent = self.dns_path.parent
        require(not parent.is_symlink(), "dns_parent_identity_unavailable")
        if not parent.exists():
            self.resources.append("dns_parent")
            self.run("mkdir", parent)
            self.dns_parent_inode = parent.stat().st_ino
        require(parent.is_dir(), "dns_parent_unavailable")
        self.resources.append("dns")
        self.run("mkdir", self.dns_path)
        self.dns_inode = self.dns_path.stat().st_ino

    def delete_rule(self, rule):
        table, chain, args = rule
        listing = self.run("iptables", "-w", "5", "-t", table, "-S", chain)
        expected = rule_tokens(["-A", chain, *args])
        lines = [rule_tokens(shlex.split(line)) for line in listing.splitlines()]
        require(lines.count(expected) <= 1, "duplicate_owned_rule")
        if expected in lines:
            self.run("iptables", "-w", "5", "-t", table, "-D", chain, *args)
            after = self.run("iptables", "-w", "5", "-t", table, "-S", chain)
            require(expected not in [rule_tokens(shlex.split(line)) for line in after.splitlines()], "owned_rule_remains")
        self.rules.remove(rule)

    def create(self, temporary):
        require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true", "linux_ci_required")
        require(self.commands.run("sysctl", "-n", "net.ipv4.ip_forward") == "1", "host_forwarding_disabled")
        self.run("iptables", "-t", "nat", "-S")
        self.firewall_before = firewall_shape(self.run("iptables-save"))
        self.ipv6_before = firewall_shape(self.run("ip6tables-save"))
        route = json.loads(self.commands.run("ip", "-j", "-4", "route", "get", "1.1.1.1"))
        require(len(route) == 1 and re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", route[0].get("dev", "")), "host_egress_unavailable")
        self.external = route[0]["dev"]
        routes = json.loads(self.commands.run("ip", "-j", "-4", "route", "show", "table", "all"))
        used = [ipaddress.ip_network(row["dst"], strict=False) for row in routes if row.get("dst") not in (None, "default")]
        for _ in range(16):
            network = ipaddress.ip_network(f"198.18.{int(uuid4().hex[:2], 16)}.{4 * (int(uuid4().hex[:2], 16) % 64)}/30")
            if not any(network.overlaps(other) for other in used):
                break
        else:
            raise Unavailable("private_subnet_unavailable")
        self.subnet = str(network)
        self.host_ip, self.guest_ip = map(str, list(network.hosts()))
        resolver = None
        for path in (Path("/etc/resolv.conf"), Path("/run/systemd/resolve/resolv.conf")):
            if not path.is_file():
                continue
            for line in path.read_text().splitlines():
                if line.startswith("nameserver "):
                    address = ipaddress.ip_address(line.split()[1])
                    if address.version == 4 and not address.is_loopback and not address.is_unspecified:
                        resolver = str(address)
                        break
            if resolver:
                break
        require(resolver is not None, "routed_resolver_unavailable")
        self.resolver = resolver
        resolver_file = temporary / "resolv.conf"
        resolver_file.write_text(f"nameserver {resolver}\noptions timeout:2 attempts:2\n")
        require(not self.dns_path.exists() and not Path("/run/netns", self.ns).exists(), "namespace_name_collision")
        self.resources.append("namespace")
        self.run("ip", "netns", "add", self.ns)
        self.netns_inode = Path("/run/netns", self.ns).stat().st_ino
        self.prepare_dns_directory()
        self.run("install", "-m", "644", resolver_file, self.dns_path / "resolv.conf")
        self.resources.append("veth")
        self.run("ip", "link", "add", self.host, "type", "veth", "peer", "name", self.guest)
        # Record identity immediately; never remove a replacement by name.
        self.identities[self.host] = self.link(self.host)
        self.run("ip", "link", "set", self.host, "alias", self.token)
        self.run("ip", "link", "set", self.guest, "alias", self.token)
        self.run("ip", "link", "set", self.guest, "netns", self.ns)
        self.identities[self.guest] = self.link(self.guest)
        self.inside("sysctl", "-qw", "net.ipv6.conf.all.disable_ipv6=1")
        self.inside("sysctl", "-qw", "net.ipv6.conf.default.disable_ipv6=1")
        self.inside("ip", "link", "set", "lo", "up")
        self.run("ip", "addr", "add", self.host_ip + "/30", "dev", self.host)
        self.inside("ip", "addr", "add", self.guest_ip + "/30", "dev", self.guest)
        self.run("ip", "link", "set", self.host, "up")
        self.inside("ip", "link", "set", self.guest, "up")
        self.inside("ip", "route", "add", "default", "via", self.host_ip)
        comment = ("-m", "comment", "--comment", self.token)
        self.add_rule("nat", "POSTROUTING", "-s", self.subnet, "-o", self.external, *comment, "-j", "MASQUERADE")
        self.add_rule("filter", "FORWARD", "-i", self.host, "-o", self.external, "-s", self.subnet, *comment, "-j", "ACCEPT")
        self.add_rule("filter", "FORWARD", "-i", self.external, "-o", self.host, "-d", self.subnet,
                      "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", *comment, "-j", "ACCEPT")
        self.resources.append("chain")
        self.run("iptables", "-w", "5", "-N", self.chain)
        self.chain_confirmed = True
        self.add_rule("filter", "INPUT", "-i", self.host, "-d", self.host_ip + "/32", *comment, "-j", self.chain)
        self.check_links()

    def impair(self):
        self.check_links()
        for name in (self.host, self.guest):
            command = self.inside if name == self.guest else self.run
            baseline = command("tc", "qdisc", "show", "dev", name)
            require(re.fullmatch(r"qdisc noqueue 0: root(?: refcnt [0-9]+)?\s*", baseline) is not None, "unexpected_owned_veth_qdisc")
            command("tc", "qdisc", "add", "dev", name, "root", "handle", self.handles[name], "netem",
                    "delay", "75ms", "10ms", "distribution", "normal", "loss", "0.1%")

    def counters(self):
        self.check_links()
        result = {}
        for name in (self.host, self.guest):
            command = self.inside if name == self.guest else self.run
            counts = parse_netem(command("tc", "-s", "qdisc", "show", "dev", name), self.handles[name])
            rows = json.loads(command("ip", "-j", "-s", "link", "show", "dev", name))
            statistics = rows[0].get("stats64", rows[0].get("stats"))
            require(statistics is not None, "veth_counters_unavailable")
            counts.update(veth_tx_packets=statistics["tx"]["packets"], veth_rx_packets=statistics["rx"]["packets"])
            result[name] = counts
        return result

    def block(self, port):
        self.check_links()
        self.add_rule("filter", self.chain, "-p", "udp", "-m", "udp", "--dport", str(port),
                      "-m", "comment", "--comment", self.token, "-j", "DROP")
        self.block_rule = self.rules[-1]

    def blocked_packets(self):
        text = self.run("iptables", "-w", "5", "-L", self.chain, "-n", "-v", "-x")
        rows = [line.split() for line in text.splitlines() if "DROP" in line]
        require(len(rows) == 1 and rows[0][0].isdigit(), "drop_counter_unavailable")
        return int(rows[0][0])

    def close(self):
        errors = []
        # Cleanup has its own command/output allowance after a failed probe.
        self.cleanup_record = {"commands": []}
        self.commands = Commands(self.cleanup_record)
        for rule in reversed(self.rules[:]):
            try:
                self.delete_rule(rule)
            except Exception:
                errors.append("firewall_rule")
        if "chain" in self.resources:
            try:
                require(getattr(self, "chain_confirmed", False), "chain_creation_ambiguous")
                require(self.run("iptables", "-S", self.chain) == "-N " + self.chain, "foreign_chain_rule")
                self.run("iptables", "-X", self.chain)
                self.resources.remove("chain")
            except Exception:
                errors.append("chain")
        if "veth" in self.resources:
            try:
                current = self.link(self.host)
                require(current["ifindex"] == self.identities[self.host]["ifindex"]
                        and current.get("link_index") == self.identities[self.host].get("link_index"), "veth_identity_changed")
                self.run("ip", "link", "del", self.host)
                self.resources.remove("veth")
            except Exception:
                errors.append("veth")
        if "namespace" in self.resources:
            try:
                require(self.netns_inode is not None and "veth" not in self.resources, "namespace_cleanup_unproven")
                self.check_namespace()
                remaining = self.run("ip", "netns", "pids", self.ns).splitlines()
                if remaining:
                    require(len(remaining) <= 32 and all(pid.isdigit() for pid in remaining), "namespace_process_inventory_unavailable")
                    self.run("ps", "-p", ",".join(remaining), "-o", "pid,ppid,uid,comm")
                    raise Unavailable("namespace_processes_remain")
                self.run("ip", "netns", "del", self.ns)
                self.resources.remove("namespace")
            except Exception:
                errors.append("namespace")
        if "dns" in self.resources:
            try:
                require(not self.dns_path.is_symlink(), "dns_identity_changed")
                if self.dns_path.exists():
                    require(self.dns_path.stat().st_ino == getattr(self, "dns_inode", None), "dns_identity_changed")
                    resolver = self.dns_path / "resolv.conf"
                    require(not resolver.is_symlink() and (not resolver.exists() or
                            resolver.read_text() == f"nameserver {self.resolver}\noptions timeout:2 attempts:2\n"), "resolver_identity_changed")
                    self.run("rm", "-f", self.dns_path / "resolv.conf")
                    self.run("rmdir", self.dns_path)
                self.resources.remove("dns")
            except Exception:
                errors.append("dns")
        if "dns_parent" in self.resources:
            try:
                parent = self.dns_path.parent
                require(not parent.is_symlink(), "dns_parent_identity_changed")
                if parent.exists():
                    require(parent.stat().st_ino == getattr(self, "dns_parent_inode", None), "dns_parent_identity_changed")
                    self.run("rmdir", parent)
                self.resources.remove("dns_parent")
            except Exception:
                errors.append("dns_parent")
        if hasattr(self, "firewall_before"):
            try:
                require(firewall_shape(self.run("iptables-save")) == self.firewall_before
                        and firewall_shape(self.run("ip6tables-save")) == self.ipv6_before, "firewall_baseline_changed")
                require(self.commands.run("sysctl", "-n", "net.ipv4.ip_forward") == "1", "host_forwarding_changed")
            except Exception:
                errors.append("baseline")
        require(not errors and not self.resources and not self.rules, "gateway_cleanup_incomplete:" + ",".join(errors))


class Echo:
    def __init__(self, address):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((address, 0))
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                data, address = self.socket.recvfrom(1024)
                if re.fullmatch(rb"mesh-[0-9a-f]{32}\n", data):
                    self.socket.sendto(data, address)
            except socket.timeout:
                pass
            except OSError:
                break

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        self.socket.close()
        require(not self.thread.is_alive(), "echo_thread_remains")


def stop_process(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def forward_check(emulator):
    port = 20000 + int(uuid4().hex[:4], 16) % 30000
    nonce = "mesh-" + uuid4().hex
    responder = "IFS= read -r token && printf '%s\\n' \"$token\""
    command = f"toybox nc -4 -l -s 127.0.0.1 -p {port} -w 8 sh -c {shlex.quote(responder)}"
    listener = None
    forwarded = None
    try:
        listener = subprocess.Popen([str(emulator.adb), "-s", SERIAL, "shell", "sh", "-c", shlex.quote(command)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=emulator.env)
        value = emulator._short("-s", SERIAL, "forward", "tcp:0", "tcp:" + str(port))
        require(value.returncode == 0 and value.stdout.strip().isdigit(), "adb_forward_unavailable")
        forwarded = int(value.stdout.strip())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", forwarded), timeout=1) as connection:
                    connection.settimeout(2)
                    connection.sendall(nonce.encode() + b"\n")
                    data = bytearray()
                    while b"\n" not in data and len(data) <= 128:
                        chunk = connection.recv(128)
                        if not chunk:
                            break
                        data.extend(chunk)
                    if data.strip() == nonce.encode():
                        return
            except OSError:
                pass
            time.sleep(0.1)
        raise Unavailable("adb_forward_round_trip_failed")
    finally:
        stop_process(listener)
        if forwarded is not None:
            value = emulator._short("-s", SERIAL, "forward", "--remove", "tcp:" + str(forwarded))
            require(value.returncode == 0, "adb_forward_cleanup_failed")


def child_main():
    emulator, server = None, None
    try:
        def terminate(_signal, _frame):
            raise Unavailable("child_termination_requested")
        signal.signal(signal.SIGTERM, terminate)
        print(json.dumps({"status": "started", "pid": os.getpid(), "namespace_inode": namespace_inode(os.getpid())}), flush=True)
        emulator = Emulator()
        server = subprocess.Popen([str(emulator.adb), "server", "nodaemon"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            require(server.poll() is None, "owned_adb_server_exited")
            try:
                with socket.create_connection(("127.0.0.1", 5037), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise Unavailable("owned_adb_server_unavailable")
        emulator.start()
        inode = namespace_inode(os.getpid())
        require(namespace_inode(server.pid) == inode and namespace_inode(emulator.process.pid) == inode,
                "emulator_namespace_mismatch")
        help_text = emulator._short("-s", SERIAL, "shell", "toybox", "nc", "--help")
        help_output = help_text.stdout + help_text.stderr
        require(help_text.returncode == 0 and all(option in help_output for option in (b"-u", b"-W", b"-q")), "guest_udp_nc_unavailable")
        forward_check(emulator)
        resolved = socket.getaddrinfo("api.github.com", 443, socket.AF_INET, socket.SOCK_STREAM)
        require(bool(resolved), "namespace_dns_unavailable")
        with urllib.request.urlopen("https://api.github.com/zen", timeout=10) as response:
            require(response.status == 200 and len(response.read(4097)) <= 4096, "namespace_https_unavailable")
        print(json.dumps({"status": "ready", "namespace_inode": inode, "emulator_pid": emulator.process.pid,
                          "adb_pid": server.pid, "image_revision": _image_revision(emulator.sdk),
                          "dns_https": "passed", "adb_forward": "passed"}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            if request["op"] == "close":
                break
            require(request["op"] == "echo", "unknown_child_request")
            address = str(ipaddress.IPv4Address(request["address"]))
            port = int(request["port"])
            nonce = request["nonce"]
            require(1024 <= port <= 65535 and re.fullmatch(r"mesh-[0-9a-f]{32}", nonce), "invalid_echo_request")
            command = f"printf '%s\\n' {shlex.quote(nonce)} | toybox nc -4 -u -w 3 -W 3 -q 3 {address} {port}"
            value = _collect_process([str(emulator.adb), "-s", SERIAL, "shell", "sh", "-c", shlex.quote(command)],
                                     timeout=8, stdout_limit=4096, stderr_limit=2048, env=emulator.env)
            require(not value["timed_out"] and not value["stdout_truncated"] and not value["stderr_truncated"], "guest_echo_command_unavailable")
            reply = {"status": "echo", "received": value["stdout"].strip() == nonce,
                     "exit_code": value["exit_code"], "stderr": value["stderr"]}
            if not reply["received"]:
                reply["guest_context"] = []
                for argv in (("ip", "-4", "route", "show", "table", "all"),
                             ("ip", "-4", "rule", "show"), ("ip", "-o", "link", "show")):
                    context = _collect_process([str(emulator.adb), "-s", SERIAL, "shell", *argv],
                                               timeout=1, stdout_limit=2048, stderr_limit=256, env=emulator.env)
                    reply["guest_context"].append({"argv": argv, **context})
            print(json.dumps(reply), flush=True)
    except Exception as error:
        print(json.dumps({"status": "failed", "reason": str(error)[:256]}), flush=True)
    finally:
        errors = []
        if emulator is not None:
            try:
                emulator.close()
            except Exception:
                errors.append("emulator")
        try:
            stop_process(server)
        except Exception:
            errors.append("adb_server")
        print(json.dumps({"status": "closed", "cleanup": "failed" if errors else "passed", "failures": errors}), flush=True)


class Child:
    def __init__(self, gateway):
        environment = {name: os.environ[name] for name in
                       ("PATH", "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "RUNNER_TEMP", "GITHUB_ACTIONS", "HOME")
                       if name in os.environ}
        command = ["sudo", "-n", "ip", "netns", "exec", gateway.ns, "setpriv", "--reuid", str(os.getuid()),
                   "--regid", str(os.getgid()), "--clear-groups", "env", *(key + "=" + value for key, value in environment.items()),
                   sys.executable, "-B", str(Path(__file__).resolve()), "--child"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.selector = None
        try:
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            stop_process(self.process)
            if self.selector is not None:
                self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()
            raise
        self.buffer = bytearray()
        self.closed = False
        self.pid = None
        self.results = []
        self.deadline = None
        self.helpers = []
        self.helper_descriptors = {}
        self.helper_observations = []
        self.helper_process_summaries = []
        self.inspection_report = {"commands": []}
        self.inspection_commands = Commands(self.inspection_report)

    def read(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            require(time.monotonic() < deadline, "child_reply_timeout")
            events = self.selector.select(max(0, deadline - time.monotonic()))
            require(bool(events), "child_reply_timeout")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            require(bool(chunk), "child_exited_without_reply")
            self.buffer.extend(chunk)
            require(len(self.buffer) <= 16384, "child_reply_limit")
        line, _, remaining = self.buffer.partition(b"\n")
        self.buffer = bytearray(remaining)
        result = json.loads(line)
        return result

    def start(self, gateway):
        started = self.read(15)
        require(started.get("status") == "started" and type(started.get("pid")) is int
                and started["namespace_inode"] == gateway.netns_inode, "child_start_identity_unavailable")
        self.pid = started["pid"]
        self.inode = started["namespace_inode"]
        self.start_time = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        return self.read(750)

    def capture_helpers(self, gateway):
        require(self.pid is not None, "child_start_identity_unavailable")
        sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"]).resolve(strict=True)
        gateway.check_namespace()
        pids = gateway.run("ip", "netns", "pids", gateway.ns).splitlines()
        require(len(pids) <= 32 and all(pid.isdigit() for pid in pids), "namespace_process_inventory_unavailable")
        if pids:
            self.helper_process_summaries.append(gateway.run("ps", "-p", ",".join(pids), "-o", "pid,ppid,uid,comm"))
        known = {item["pid"]: item for item in self.helpers}
        observations = []
        for value in pids:
            pid = int(value)
            identity = self.inspect_process(pid)
            if identity is None:
                continue
            parent = process_parent(pid)
            if parent is None:
                continue
            observations.append({**identity, "parent": parent})
        self.helper_observations.append(observations)
        for identity in observations:
            if identity["pid"] == self.pid:
                require(identity["start"] == self.start_time and identity["namespace"] == self.inode
                        and identity["uid"] == os.getuid(), "child_process_identity_changed")
        owned = {self.pid, *known}
        pending = [item for item in observations if item["pid"] != self.pid]
        while pending:
            progress = False
            for observed in pending[:]:
                identity = {key: value for key, value in observed.items() if key != "parent"}
                pid = identity["pid"]
                require(identity["namespace"] == self.inode and identity["uid"] == os.getuid()
                        and int(identity["start"]) >= int(self.start_time), "unowned_namespace_process")
                if pid not in known and not Path(identity["executable"]).is_relative_to(sdk) and observed["parent"] not in owned:
                    continue
                require(pid not in known or same_process(known[pid], identity), "helper_process_identity_changed")
                if pid not in known:
                    descriptor = os.pidfd_open(pid)
                    current = self.inspect_process(pid)
                    if current is None:
                        os.close(descriptor)
                    else:
                        if not same_process(current, identity):
                            os.close(descriptor)
                            raise Unavailable("helper_process_identity_changed")
                        self.helpers.append(identity)
                        self.helper_descriptors[pid] = descriptor
                owned.add(pid)
                pending.remove(observed)
                progress = True
            require(progress, "unowned_namespace_process")

    def inspect_process(self, pid):
        try:
            return process_identity(pid)
        except PermissionError:
            value = json.loads(self.inspection_commands.run(sys.executable, "-B", str(Path(__file__).resolve()),
                               "--inspect-process", str(pid), privileged=True))
            require(value is None or value.get("pid") == pid, "process_inspection_mismatch")
            return value

    def retire_helpers(self, gateway):
        failures = []
        frozen = set()
        try:
            # The emulator has exited. Stop known producers before a final
            # descendant inventory, preventing a fork during retirement.
            for _ in range(3):
                for identity in self.helpers:
                    pid = identity["pid"]
                    descriptor = self.helper_descriptors[pid]
                    if pid in frozen or select.select([descriptor], [], [], 0)[0]:
                        continue
                    current = self.inspect_process(pid)
                    if current is None:
                        continue
                    require(same_process(current, identity), "helper_process_identity_changed")
                    try:
                        signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
                    except ProcessLookupError:
                        continue
                    frozen.add(pid)
                count = len(self.helpers)
                self.capture_helpers(gateway)
                if len(self.helpers) == count:
                    break
            else:
                raise Unavailable("helper_inventory_unstable")
        except Exception as error:
            failures.append(str(error))
        for identity in reversed(self.helpers):
            descriptor = self.helper_descriptors.pop(identity["pid"])
            try:
                retire_exact_process(identity, descriptor, reader=self.inspect_process, force=True)
            except Exception as error:
                failures.append(str(error))
            finally:
                os.close(descriptor)
        require(not failures, "helper_retirement_failed:" + ",".join(failures)[:160])

    def send(self, value):
        self.process.stdin.write(json.dumps(value).encode() + b"\n")
        self.process.stdin.flush()

    def echo(self, gateway, port):
        timeout = 12 if self.deadline is None else min(12, self.deadline - time.monotonic())
        require(timeout > 0, "probe_deadline_exceeded")
        self.send({"op": "echo", "address": gateway.host_ip, "port": port, "nonce": "mesh-" + uuid4().hex})
        value = self.read(timeout)
        self.results.append(value)
        require(value.get("status") == "echo" and type(value.get("received")) is bool, "echo_reply_unavailable")
        return value["received"] and not value.get("stderr") and value.get("exit_code") == 0

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    self.send({"op": "close"})
                except (OSError, BrokenPipeError):
                    pass
            deadline = time.monotonic() + 45
            closed = None
            while time.monotonic() < deadline:
                try:
                    value = self.read(max(0.1, deadline - time.monotonic()))
                    if value.get("status") == "closed":
                        closed = value
                        break
                except Unavailable:
                    break
            if closed is None and self.pid is not None and Path(f"/proc/{self.pid}").exists():
                require(namespace_inode(self.pid) == self.inode
                        and Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[19] == self.start_time,
                        "child_process_identity_changed")
                os.kill(self.pid, signal.SIGTERM)
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    value = self.read(max(0.1, deadline - time.monotonic()))
                    if value.get("status") == "closed":
                        closed = value
                        break
            require(closed is not None and closed.get("cleanup") == "passed", "child_cleanup_failed")
            self.process.wait(timeout=10)
            require(self.process.returncode == 0, "child_cleanup_exit_failed")
            self.closed = True
        finally:
            self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--inspect-process", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inspect_process is not None:
        require(sys.platform == "linux" and 0 < args.inspect_process < 2**31, "invalid_process_inspection")
        print(json.dumps(process_identity(args.inspect_process)))
        return 0
    if args.child:
        child_main()
        return 0
    require(args.output == Path("dist/reports/android-gateway-probe.json"), "invalid_output_path")
    report = {"kind": "android_host_gateway_capability_v1", "qualification": False,
              "network_mutations": "owned_namespace_veth_and_scoped_host_rules", "passed": False,
              "cleanup": "not_started", "commands": [], "phase": "preflight",
              "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    gateway = child = echo = temporary = None
    try:
        require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true", "linux_ci_required")
        def terminate(_signal, _frame):
            raise Unavailable("probe_termination_requested")
        signal.signal(signal.SIGTERM, terminate)
        report["source_commit"], report["source_tree"] = _source_identity()
        require(report["source_commit"] == os.environ.get("GITHUB_SHA"), "source_binding_mismatch")
        require(all(re.fullmatch(r"[1-9][0-9]*", report[k] or "") for k in ("github_run_id", "github_run_attempt")), "run_binding_unavailable")
        temporary = Path(tempfile.mkdtemp(prefix="mesh-gateway-", dir=os.environ["RUNNER_TEMP"]))
        gateway = Gateway(Commands(report))
        gateway.create(temporary)
        report["topology"] = {"namespace_inode": gateway.netns_inode, "host": gateway.host,
                              "guest": gateway.guest, "identities": gateway.identities,
                              "subnet": gateway.subnet, "resolver": gateway.resolver, "ipv6": "disabled"}
        report["phase"] = "emulator_boot"
        echo = Echo(gateway.host_ip)
        child = Child(gateway)
        ready = child.start(gateway)
        child.capture_helpers(gateway)
        report["child"] = ready
        require(ready.get("status") == "ready" and ready["namespace_inode"] == gateway.netns_inode,
                "child_namespace_unavailable:" + str(ready.get("reason", "unknown"))[:192])
        deadline = time.monotonic() + 120
        child.deadline = gateway.commands.deadline = deadline
        require(wait_for_guest_echo(child, gateway, echo.port, 6), "baseline_guest_echo_failed")
        report["phase"] = "impaired_echo"
        gateway.impair()
        before = gateway.counters()
        received = sum(child.echo(gateway, echo.port) for _ in range(3))
        require(received >= 2, "impaired_guest_echo_failed")
        report["impaired_echoes"] = received
        after = gateway.counters()
        delta = {name: counter_delta(before[name], after[name]) for name in before}
        require(all(counts["packets"] > 0 and counts["bytes"] > 0 and counts["veth_tx_packets"] > 0
                    for counts in delta.values()), "bidirectional_counters_missing")
        report["counter_delta"] = delta
        report["phase"] = "counted_block"
        gateway.block(echo.port)
        count = gateway.blocked_packets()
        require(not child.echo(gateway, echo.port), "blocked_echo_bypassed_gateway")
        dropped = gateway.blocked_packets() - count
        require(dropped > 0, "negative_control_not_counted")
        report["blocked_packets"] = dropped
        gateway.delete_rule(gateway.block_rule)
        report["phase"] = "recovery"
        require(wait_for_guest_echo(child, gateway, echo.port, 3), "recovery_echo_failed")
        final = gateway.counters()
        for name in after:
            counter_delta(after[name], final[name])
        require(time.monotonic() <= deadline, "probe_deadline_exceeded")
        report["passed"] = True
    except Exception as error:
        report["failure"] = str(error)[:256]
    finally:
        failures = []
        if child is not None and gateway is not None:
            try:
                child.capture_helpers(gateway)
            except Exception as error:
                failures.append("helper_inventory")
                report.setdefault("cleanup_reasons", {})["helper_inventory"] = str(error)[:256]
        for name, resource in (("child", child), ("echo", echo), ("gateway", gateway)):
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    failures.append(name)
                    report.setdefault("cleanup_reasons", {})[name] = str(error)[:256]
                if name == "child":
                    try:
                        child.retire_helpers(gateway)
                    except Exception as error:
                        failures.append("helpers")
                        report.setdefault("cleanup_reasons", {})["helpers"] = str(error)[:256]
        if gateway is not None:
            report["cleanup_commands"] = getattr(gateway, "cleanup_record", {}).get("commands", [])
        if child is not None:
            report["guest_attempts"] = child.results
            report["owned_helpers"] = child.helpers
            report["helper_observations"] = child.helper_observations
            report["helper_process_summaries"] = child.helper_process_summaries
            report["process_inspection_commands"] = getattr(child, "inspection_report", {}).get("commands", [])
        if temporary is not None:
            try:
                temporary.rmdir()
            except OSError:
                # Only the two known task-local files may be removed.
                try:
                    (temporary / "resolv.conf").unlink(missing_ok=True)
                    temporary.rmdir()
                except OSError:
                    failures.append("temporary")
        report["cleanup"] = "failed" if failures else "passed"
        report["cleanup_failures"] = failures
        report["passed"] = report["passed"] and not failures
        encoded = json.dumps(report, separators=(",", ":")).encode()
        require(len(encoded) <= 512 * 1024, "report_limit")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded + b"\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
