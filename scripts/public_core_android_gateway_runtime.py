"""Own the public Android partition role inside one disposable Linux gateway.

This wrapper does not select or attest an ICE carrier. It bounds the installed
app's non-loopback IP traffic in both families, while preserving local ADB
control, and delegates product operations to the ordinary public SDK role.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from native_interop_gateway_probe import (Child, Commands, Gateway, Unavailable,
    namespace_inode, process_identity, require, same_process, stop_process)
from native_interop_gateway_runtime import GatewayClient, GatewayProfile, NativeChild, read_message
from native_interop_network_probe import Emulator, SERIAL


ROOT = Path(__file__).resolve().parents[1]
APP = "com.meshchat.core.independent"
APK_ROLE = "dist/android-independent-consumer/consumer.apk"
MAX_ROLE_REPORT = 256 * 1024
MAX_RUN_SECONDS = 35 * 60
IP_FAMILIES = (("iptables", "v4"), ("ip6tables", "v6"))


class PublicGatewayFailure(RuntimeError):
    pass


class PublicUidFault:
    """Counted app-UID egress and non-loopback guest ingress partition."""

    def __init__(self, emulator, profile_current, expected_source):
        self.emulator = emulator
        self.profile_current = profile_current
        self.expected_source = expected_source
        self.peer = None
        self.bound = None
        self.rules = []
        self.before = {}
        self.baseline_chains = {}
        self.blocked = False
        self.closed = False
        self.token = "meshpub" + uuid4().hex[:12]

    def _run(self, *arguments):
        process = subprocess.run([str(self.emulator.adb), "-s", SERIAL, "shell", *map(str, arguments)],
                                 env=self.emulator.env, capture_output=True, timeout=12)
        if len(process.stdout) > 8192 or len(process.stderr) > 512:
            raise PublicGatewayFailure("guest_command_unbounded")
        return process.returncode, process.stdout.decode("utf-8", "replace").strip()

    def _command(self, *arguments):
        code, value = self._run(*arguments)
        if code != 0:
            raise PublicGatewayFailure("guest_command_failed")
        return value

    def _process(self):
        pids = self._command("pidof", APP).split()
        if len(pids) != 1 or not pids[0].isdigit():
            raise PublicGatewayFailure("installed_app_process_unavailable")
        pid = pids[0]
        name = self._command("cat", f"/proc/{pid}/cmdline").split("\x00", 1)[0]
        status = self._command("cat", f"/proc/{pid}/status")
        uid = re.search(r"(?m)^Uid:\s+([0-9]+)\s", status)
        stats = self._command("cat", f"/proc/{pid}/stat").rsplit(")", 1)
        if (name != APP or uid is None or int(uid[1]) < 10000 or len(stats) != 2
                or len(stats[1].split()) <= 19 or not stats[1].split()[19].isdigit()):
            raise PublicGatewayFailure("installed_app_process_identity_invalid")
        return {"pid": int(pid), "uid": int(uid[1]), "start": stats[1].split()[19]}

    def _apk_sha(self):
        paths = self._command("pm", "path", APP).splitlines()
        if len(paths) != 1 or not paths[0].startswith("package:/data/app/"):
            raise PublicGatewayFailure("installed_apk_path_invalid")
        path = paths[0].removeprefix("package:")
        if not re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~-]+\.apk", path) or ".." in Path(path).parts:
            raise PublicGatewayFailure("installed_apk_path_invalid")
        result = self._command("sha256sum", path).split()
        if len(result) != 2 or result[1] != path or not re.fullmatch(r"[a-f0-9]{64}", result[0]):
            raise PublicGatewayFailure("installed_apk_hash_invalid")
        return result[0]

    def bind(self, peer):
        if self.peer is not None or not getattr(peer, "opened", False) or not getattr(peer, "admitted", False) \
                or not getattr(peer, "owned", False) or getattr(peer, "serial", None) != SERIAL:
            raise PublicGatewayFailure("public_fault_peer_unadmitted")
        identity, artifacts = getattr(peer, "identity", None), getattr(peer, "artifacts", None)
        if (not isinstance(identity, dict) or not isinstance(artifacts, dict)
                or identity.get("source_commit") != self.expected_source
                or not isinstance(artifacts.get(APK_ROLE), str)
                or not re.fullmatch(r"[a-f0-9]{64}", artifacts[APK_ROLE])
                or self._apk_sha() != artifacts[APK_ROLE]):
            raise PublicGatewayFailure("installed_apk_not_source_bound")
        self.bound = self._process()
        self.peer = peer

    def _current(self):
        if self.bound is None or self._process() != self.bound:
            raise PublicGatewayFailure("installed_app_process_changed")
        if self._apk_sha() != self.peer.artifacts[APK_ROLE]:
            raise PublicGatewayFailure("installed_apk_changed")

    def _control_live(self):
        state = subprocess.run([str(self.emulator.adb), "-s", SERIAL, "get-state"],
                               env=self.emulator.env, capture_output=True, timeout=8)
        if (state.returncode != 0 or state.stdout.strip() != b"device"
                or len(state.stderr) > 512
                or self._command("getprop", "ro.kernel.qemu") != "1"):
            raise PublicGatewayFailure("adb_control_liveness_lost")

    def _rules(self):
        uid = str(self.bound["uid"])
        for family, suffix in IP_FAMILIES:
            yield (family, "OUTPUT", ("!", "-o", "lo", "-m", "owner", "--uid-owner", uid,
                                      "-m", "comment", "--comment", self.token + "-out-" + suffix,
                                      "-j", "DROP"), self.token + "-out-" + suffix)
            yield (family, "INPUT", ("!", "-i", "lo", "-m", "comment", "--comment",
                                     self.token + "-in-" + suffix, "-j", "DROP"),
                   self.token + "-in-" + suffix)

    def _chains(self):
        return {(family, chain): self._command(family, "-S", chain)
                for family, _ in IP_FAMILIES for chain in ("OUTPUT", "INPUT")}

    def _check_predecessor(self):
        uid = str(self.bound["uid"])
        for (_family, chain), listing in self.baseline_chains.items():
            for line in listing.splitlines():
                if not line.startswith(f"-A {chain} "):
                    continue
                tokens = line.split()
                if "-j" not in tokens:
                    continue
                jump = tokens[tokens.index("-j") + 1:][:1]
                if jump not in (["DROP"], ["REJECT"]):
                    continue
                if chain == "INPUT" or "--uid-owner" not in tokens \
                        or tokens[tokens.index("--uid-owner") + 1:][:1] == [uid]:
                    raise PublicGatewayFailure("guest_rule_ambiguous_predecessor")

    def _present(self, rule):
        family, chain, args, _comment = rule
        code, _ = self._run(family, "-C", chain, *args)
        if code not in (0, 1):
            raise PublicGatewayFailure("guest_rule_query_failed")
        return code == 0

    def _packets(self, rule):
        family, chain, _args, comment = rule
        listing = self._command(family, "-nvx", "-L", chain, "--line-numbers")
        rows = [line.split() for line in listing.splitlines() if comment in line.split()]
        if len(rows) != 1 or len(rows[0]) < 4 or rows[0][3] != "DROP" or not rows[0][1].isdigit():
            raise PublicGatewayFailure("guest_rule_counter_invalid")
        return int(rows[0][1])

    def _remove(self):
        failures = []
        for rule in reversed(self.rules[:]):
            family, chain, args, _ = rule
            try:
                if self._present(rule):
                    self._command(family, "-D", chain, *args)
                if self._present(rule):
                    raise PublicGatewayFailure("guest_rule_remains")
                self.rules.remove(rule)
            except Exception:
                failures.append(rule)
        self.blocked = bool(self.rules)
        if failures:
            raise PublicGatewayFailure("guest_rule_cleanup_unproven")
        if self.baseline_chains and self._chains() != self.baseline_chains:
            raise PublicGatewayFailure("guest_rule_baseline_changed")

    def block(self):
        if self.closed or self.blocked or self.peer is None:
            raise PublicGatewayFailure("public_fault_not_ready")
        self._current()
        planned = list(self._rules())
        self.baseline_chains = self._chains()
        if any(self._present(rule) for rule in planned):
            raise PublicGatewayFailure("guest_rule_preexisting")
        self._check_predecessor()
        try:
            for rule in planned:
                self.rules.append(rule)  # Reserve cleanup before a possibly ambiguous insert.
                family, chain, args, _ = rule
                self._command(family, "-I", chain, "1", *args)
                if not self._present(rule):
                    raise PublicGatewayFailure("guest_rule_install_unconfirmed")
            self.before = {rule[3]: self._packets(rule) for rule in self.rules if rule[1] == "OUTPUT"}
            self.blocked = True
            self._current()
            self._control_live()
        except Exception:
            self._remove()
            raise

    def dropped(self):
        if not self.blocked or len(self.before) != 2:
            raise PublicGatewayFailure("public_fault_not_blocked")
        self._control_live()
        self._current()
        counts = []
        for rule in self.rules:
            if rule[1] == "OUTPUT":
                if not self._present(rule):
                    raise PublicGatewayFailure("guest_rule_changed")
                delta = self._packets(rule) - self.before[rule[3]]
                if delta < 0:
                    raise PublicGatewayFailure("guest_counter_regressed")
                counts.append(delta)
        if len(counts) != 2 or len(self.rules) != 4:
            raise PublicGatewayFailure("guest_rule_scope_changed")
        return sum(counts)

    def unblock(self):
        if not self.blocked:
            raise PublicGatewayFailure("public_fault_not_blocked")
        packets = self.dropped()
        self._remove()
        self._current()
        current = self.profile_current()
        if not isinstance(current, dict) or len(current) != 2 or not all(
                isinstance(row, dict) and row.get("packets", 0) >= 0 for row in current.values()):
            raise PublicGatewayFailure("owned_route_profile_not_current")
        return {"app_uid_bound": True, "process_bound": True,
                "owned_route": True, "profile_restored": True, "dropped_packets": packets}

    def close(self):
        if self.closed:
            return True
        try:
            if self.rules:
                self._remove()
            self.closed = True
            return True
        except Exception:
            return False


class PublicChild(NativeChild):
    """Reuse native gateway RPC and helper custody with a public role entry."""

    def __init__(self, gateway, arguments):
        Child.__init__(self, gateway, entry=[str(Path(__file__).resolve()), "--namespace-child", *arguments])
        self.gateway = gateway
        self.profile = GatewayProfile(gateway)
        self.ready = False
        self.operation_failed = False
        self.failed_operation = None
        self.requests = 0
        self.result = None
        self.ice_capture = None
        self.impairment = None
        self.emulator_identity = None
        self.adb_identity = None

    def dispatch(self, request):
        value = super().dispatch(request)
        if request.get("op") == "ready":
            self.emulator_identity = process_identity(request["emulator"])
            self.adb_identity = process_identity(request["adb"])
            require(self.emulator_identity is not None and self.adb_identity is not None
                    and self.emulator_identity["namespace"] == self.inode
                    and self.adb_identity["namespace"] == self.inode,
                    "public_gateway_process_identity_changed")
        if request.get("op") == "report":
            self.impairment = value
        return value


def _ready_adb(emulator):
    server = subprocess.Popen([str(emulator.adb), "server", "nodaemon"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 10
        while time.monotonic() < until:
            require(server.poll() is None, "public_adb_server_exited")
            try:
                with socket.create_connection(("127.0.0.1", 5037), timeout=0.2):
                    return server
            except OSError:
                time.sleep(0.1)
        raise PublicGatewayFailure("public_adb_server_unavailable")
    except Exception:
        stop_process(server)
        raise


def namespace_child(arguments):
    writer = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    reader = os.fdopen(os.dup(sys.stdin.fileno()), "r")
    writer.write(json.dumps({"status": "started", "pid": os.getpid(),
                             "namespace_inode": namespace_inode(os.getpid())}) + "\n")
    writer.flush()
    environment = read_message(reader, 256 * 1024)
    require(all(type(key) is str and type(value) is str for key, value in environment.items()),
            "public_gateway_environment_shape")
    os.environ.clear()
    os.environ.update(environment)
    environment.clear()
    with open(os.devnull, "r+") as discarded:
        os.dup2(discarded.fileno(), sys.stdin.fileno())
        os.dup2(discarded.fileno(), sys.stdout.fileno())
    emulator = server = fault = coverage = None
    code, cleanup = 1, True
    try:
        def terminate(_signal, _frame):
            raise Unavailable("public_gateway_termination")
        signal.signal(signal.SIGTERM, terminate)
        emulator = Emulator()
        server = _ready_adb(emulator)
        emulator.start()
        inode = namespace_inode(os.getpid())
        require(namespace_inode(server.pid) == inode
                and namespace_inode(emulator.process.pid) == inode,
                "public_emulator_namespace_mismatch")
        client = GatewayClient(reader, writer, server)
        client.ready(emulator)
        coverage = client.coverage(None)
        coverage.install()
        source = arguments[arguments.index("--expected-source") + 1]
        fault = PublicUidFault(emulator, coverage.current, source)
        # D owns the product flow. The gateway controls only OS resources.
        import public_core_partition_controller as controller
        sys.argv = [controller.__file__, *arguments]
        code = controller.main(fault=fault)
        if code == 0:
            coverage.report()
    except Exception:
        code = 1
    finally:
        if fault is not None:
            try: cleanup = fault.close() is True and cleanup
            except Exception: cleanup = False
        if coverage is not None:
            try: coverage.close()
            except Exception: cleanup = False
        if emulator is not None:
            try: emulator.close()
            except Exception: cleanup = False
        try: stop_process(server)
        except Exception: cleanup = False
        writer.write(json.dumps({"status": "closed", "cleanup": "passed" if cleanup else "failed",
                                 "code": code}) + "\n")
        writer.flush()
        writer.close()
        reader.close()
    return code


def _source(expected):
    if not re.fullmatch(r"[a-f0-9]{40}", expected):
        raise PublicGatewayFailure("expected_source_invalid")
    value = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                    text=True, timeout=10, stderr=subprocess.DEVNULL).strip()
    if value != expected:
        raise PublicGatewayFailure("source_commit_changed")


def _role_report(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ROLE_REPORT:
        raise PublicGatewayFailure("public_role_report_unavailable")
    value = json.loads(path.read_bytes())
    if type(value) is not dict or value.get("role") != "android":
        raise PublicGatewayFailure("public_role_report_invalid")
    return value


def run_parent(arguments, output):
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(_signal, _frame):
        raise Unavailable("public_gateway_termination")

    signal.signal(signal.SIGTERM, terminate)
    try:
        return _run_parent(arguments, output, lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN))
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _run_parent(arguments, output, quiesce_termination):
    gateway = child = temporary = None
    failure = False
    cleanup_failures = []
    source = arguments[arguments.index("--expected-source") + 1]
    report = None
    previous_report = output.stat() if output.exists() else None
    try:
        require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true",
                "public_linux_ci_required")
        _source(source)
        temporary = Path(tempfile.mkdtemp(prefix="mesh-public-gateway-", dir=os.environ["RUNNER_TEMP"]))
        gateway = Gateway(Commands({"commands": []}))
        gateway.create(temporary)
        child = PublicChild(gateway, arguments)
        child.begin()
        child.receive_until_closed(time.monotonic() + MAX_RUN_SECONDS)
        require(child.ready and child.result is not None and child.result["code"] == 0
                and not child.operation_failed and child.impairment is not None
                and child.emulator_identity is not None and child.adb_identity is not None,
                "public_gateway_controller_failed")
        report = _role_report(output)
        current_report = output.stat()
        require(previous_report is None or
                (current_report.st_dev, current_report.st_ino, current_report.st_mtime_ns) !=
                (previous_report.st_dev, previous_report.st_ino, previous_report.st_mtime_ns),
                "public_role_report_stale")
        require(report.get("passed") is True and report.get("gateway") is None,
                "public_role_failed_or_unbound")
    except Exception:
        failure = True
    finally:
        quiesce_termination()
        if child is not None:
            try: child.close()
            except Exception: cleanup_failures.append("child")
            if gateway is not None:
                gateway.commands = Commands({"commands": []})
                try: child.retire_helpers(gateway)
                except Exception: cleanup_failures.append("helpers")
                try: child.profile.close()
                except Exception: cleanup_failures.append("profile")
        if gateway is not None:
            try: gateway.close()
            except Exception: cleanup_failures.append("gateway")
        if temporary is not None:
            try:
                (temporary / "resolv.conf").unlink(missing_ok=True)
                temporary.rmdir()
            except OSError:
                cleanup_failures.append("temporary")
    if report is None:
        try: report = _role_report(output)
        except Exception:
            report = {"v": 1, "passed": False, "role": "android",
                      "failure_phase": "host_gateway", "failure_type": "GatewayUnavailable"}
    if not failure and not cleanup_failures and report.get("passed") is True:
        report["gateway"] = {"namespace": "owned_linux_network_namespace",
                             "emulator_pid_bound": True, "adb_pid_bound": True,
                             "cleanup": "passed", "impairment": child.impairment}
    else:
        report["passed"] = False
        report["host_gateway_failure"] = {"controller_failed": failure,
                                           "cleanup_failures": cleanup_failures,
                                           "operation_failure": getattr(child, "failed_operation", None)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


def main():
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "--namespace-child":
        return namespace_child(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("android",), required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--disposable-emulator-serial", choices=(SERIAL,), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    return run_parent(arguments, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
