"""GitHub Linux-only real NAT qualification of the shipping private dispatcher.

Requires root for isolated namespaces. No production code imports this file.
The fixture supplies simulator-known external tuples, not a discovery service.
All links are private veth pairs: no namespace has a route to the host Internet.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from mesh_chat.direct_native import NativeChannel
from mesh_chat.ipc import FrameWriter, read_frame


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10).stdout


class TrialFailure(AssertionError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(evidence["failure_reason"])


class Native:
    def __init__(self, namespace, binary):
        self.process = subprocess.Popen(["ip", "netns", "exec", namespace, binary],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.channel = NativeChannel(FrameWriter(self.process.stdin).write)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                self.channel.receive(read_frame(self.process.stdout, max_bytes=65536))
        except Exception:
            self.channel.close()

    def close(self):
        self.channel.close()
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdout.close()


class Topology:
    def __init__(self):
        self.prefix = "mnat" + uuid.uuid4().hex[:6]
        self.names = []

    def ns(self, suffix):
        return self.prefix + suffix

    def cmd(self, suffix, *args):
        return run("ip", "netns", "exec", self.ns(suffix), *args)

    def create(self):
        for suffix in ("a", "b", "ra", "rb"):
            run("ip", "netns", "add", self.ns(suffix))
            self.names.append(self.ns(suffix))
            self.cmd(suffix, "ip", "link", "set", "lo", "up")
        for index, (left, right, subnet) in enumerate((("a", "ra", "10.201.1"),
                ("b", "rb", "10.201.2"), ("ra", "rb", "198.18.0"))):
            v1, v2 = self.prefix + str(index) + "a", self.prefix + str(index) + "b"
            run("ip", "link", "add", v1, "type", "veth", "peer", "name", v2)
            run("ip", "link", "set", v1, "netns", self.ns(left))
            run("ip", "link", "set", v2, "netns", self.ns(right))
            for suffix, name, last in ((left, v1, 1), (right, v2, 2)):
                self.cmd(suffix, "ip", "addr", "add", f"{subnet}.{last}/24", "dev", name)
                self.cmd(suffix, "ip", "link", "set", name, "up")
        for side, subnet in (("a", "10.201.1"), ("b", "10.201.2")):
            self.cmd(side, "ip", "route", "add", "default", "via", subnet + ".2")
            router = "r" + side
            self.cmd(router, "sysctl", "-qw", "net.ipv4.ip_forward=1")
            # Drop unsolicited Internet packets BEFORE conntrack. Otherwise a
            # packet addressed to the router itself can create a competing local
            # conntrack entry before the other endpoint has emitted anything.
            # This kernel filter opens only when the LAN host sends to that peer.
            self.cmd(router, "iptables", "-t", "raw", "-A", "PREROUTING", "-s", subnet + ".0/24",
                     "-p", "udp", "-m", "recent", "--name", "mesh_nat", "--set", "--rdest")
            public_link = self.prefix + "2" + side
            self.cmd(router, "iptables", "-t", "raw", "-A", "PREROUTING", "-i", public_link,
                     "-p", "udp", "-m", "recent", "--name", "mesh_nat", "--rcheck", "--rsource", "--seconds", "30", "-j", "ACCEPT")
            self.cmd(router, "iptables", "-t", "raw", "-A", "PREROUTING", "-i", public_link,
                     "-p", "udp", "-j", "DROP")
            self.cmd(router, "iptables", "-P", "FORWARD", "DROP")
            self.cmd(router, "iptables", "-A", "FORWARD", "-s", subnet + ".0/24", "-j", "ACCEPT")
            self.cmd(router, "iptables", "-A", "FORWARD", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT")
            self.cmd(router, "iptables", "-A", "FORWARD", "-j", "DROP")

    def map(self, side, port, destination_dependent=False):
        subnet, public = ("10.201.1", "198.18.0.1") if side == "a" else ("10.201.2", "198.18.0.2")
        # SNAT only: this is not DNAT or an inbound port forward. An unsolicited
        # inbound datagram has no conntrack mapping and cannot reach either host.
        if destination_dependent:
            peer = "198.18.0.2" if side == "a" else "198.18.0.1"
            mapped_port = port + 1 if port < 65535 else port - 1
            self.cmd("r" + side, "iptables", "-t", "nat", "-A", "POSTROUTING", "-s", subnet + ".0/24",
                     "-d", peer, "-p", "udp", "-j", "SNAT", "--to-source", f"{public}:{mapped_port}")
        self.cmd("r" + side, "iptables", "-t", "nat", "-A", "POSTROUTING", "-s", subnet + ".0/24",
                 "-p", "udp", "-j", "SNAT", "--to-source", f"{public}:{port}")

    def counts(self, side):
        lines = self.cmd("r" + side, "iptables", "-L", "FORWARD", "-nvx").splitlines()[2:]
        return [int(line.split()[0]) for line in lines if line.strip()]

    def diagnostics(self):
        result = {}
        for side in ("ra", "rb"):
            result[side] = {}
            for name, command in (("rules", ("iptables-save", "-c")),
                                  ("udp_mappings", ("conntrack", "-L", "-p", "udp", "-o", "extended"))):
                try:
                    result[side][name] = self.cmd(side, *command)[-16384:]
                except subprocess.CalledProcessError as error:
                    result[side][name] = "unavailable: " + error.stderr[-512:]
                except subprocess.TimeoutExpired:
                    result[side][name] = "unavailable: diagnostic command timed out"
        return result

    def block_udp(self, side):
        self.cmd("r" + side, "iptables", "-t", "raw", "-I", "PREROUTING", "1",
                 "-i", self.prefix + "2" + side, "-p", "udp", "-j", "DROP")

    def close(self):
        for namespace in reversed(self.names):
            run("ip", "netns", "delete", namespace)


def trial(binary, coordinated, blocked="", destination_dependent=False):
    topology, hosts = Topology(), []
    started = time.monotonic()
    try:
        topology.create()
        for side in blocked:
            topology.block_udp(side)
        hosts = [Native(topology.ns(side), binary) for side in ("a", "b")]
        prepared = [host.channel.request("prepare", address=f"10.201.{i+1}.1:0", generation=1,
                    remaining_ms=60000) for i, host in enumerate(hosts)]
        for i, host in enumerate(hosts):
            p = prepared[i]
            topology.map("ab"[i], p["port"], destination_dependent)
            host.channel.request("arm", id=p["id"], session=p["session"], generation=1, digest="ab" * 32)
        for i, host in enumerate(hosts):
            other = prepared[1-i]
            candidates = [{"host":f"198.18.0.{2-i}", "port":other["port"], "remaining_ms":10000}]
            host.channel.request("activate", id=prepared[i]["id"], certificate=other["certificate"],
                local=("01" if i == 0 else "02") * 16, remote=("02" if i == 0 else "01") * 16,
                candidates=candidates if i == 0 or coordinated else [], client=i == 0, remaining_ms=10000)
        connected = False
        observations, states = [], []
        deadline = time.monotonic() + 11
        while time.monotonic() < deadline:
            observations = [host.channel.request("poll", id=p["id"]) for host, p in zip(hosts, prepared)]
            states = [observation["state"] for observation in observations]
            if states == [1, 1]:
                connected = True
                break
            if 2 in states:
                break
            time.sleep(.05)
        delivered = []
        if connected:
            for i, host in enumerate(hosts):
                payload = (b"nat-proof-a" if i == 0 else b"nat-proof-b").hex()
                host.channel.request("send", id=prepared[i]["id"], packets=[payload])
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    packets = hosts[1-i].channel.request("poll", id=prepared[1-i]["id"])["packets"]
                    if payload in packets:
                        delivered.append(True)
                        break
                    time.sleep(.02)
        counts = [topology.counts(side) for side in "ab"]
        expected = coordinated and not blocked and not destination_dependent
        result = {"profile":"destination-dependent mapping with stale destination-specific tuple" if destination_dependent else "endpoint-independent mapping, outbound-dependent UDP filtering",
                "coordinated_checks":coordinated, "connected":connected,
                "udp_blocked_sides":len(blocked), "expected_connection":bool(expected),
                "bidirectional_packets":len(delivered), "router_forward_counters":counts,
                "elapsed_seconds":round(time.monotonic()-started, 3),
                "candidate_source":"test-only tuple for a different destination" if destination_dependent else "test-only NAT ground truth", "retained_native_ports":True,
                "native_ports": [p["port"] for p in prepared], "native_states": states,
                "native_statistics": [value.get("statistics", {}) for value in observations]}
        reason = None
        if connected != expected:
            reason = "unexpected_topology_result"
        elif expected and len(delivered) != 2:
            reason = "missing_bidirectional_packets"
        elif expected and not all(row[0] > 0 and row[1] > 0 for row in counts):
            reason = "missing_router_forwarding"
        elif not coordinated and not (counts[0][0] > 0 and counts[1][0] == 0):
            reason = "invalid_uncoordinated_control"
        result["passed"] = reason is None
        if reason is not None:
            result.update(failure_reason=reason, router_diagnostics=topology.diagnostics())
            raise TrialFailure(result)
        return result
    finally:
        for host in hosts:
            host.close()
        topology.close()


def run_trials(binary, report, scenarios):
    results = []
    for enabled, blocked, destination_dependent in scenarios:
        try:
            results.append(trial(binary, enabled, blocked, destination_dependent))
        except TrialFailure as error:
            results.append(error.evidence)
            raise
        finally:
            # A failed trial and its router state are evidence too. Never lose
            # them while unwinding namespaces or hide failure behind a retry.
            report.write_text(json.dumps({"schema":1, "trials":results,
                "expected_trial_count":len(scenarios), "physical_evidence":False, "discovery_evidence":False,
                "tcp_fallback_evidence":False}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Run only in the isolated GitHub Linux qualification job")
    scenarios = [(False,"",False), (True,"",False), (True,"",False), (True,"",False),
                 (True,"a",False), (True,"ab",False), (True,"",True)]
    run_trials(str(Path(args.binary).resolve()), Path(args.report), scenarios)


if __name__ == "__main__":
    main()
