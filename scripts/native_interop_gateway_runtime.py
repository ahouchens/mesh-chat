"""Owned host gateway for the actual Android native qualification process.

The privileged parent controls only its disposable network objects. The native
controller and emulator remain unprivileged; the existing guest app-UID rules
provide the counted UDP block independently of the host impairment profile.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

from native_interop_gateway_probe import (Child, Commands, Gateway, Unavailable,
    counter_delta, namespace_inode, process_identity, require, same_process, stop_process)
from native_interop_ice_capture import IceCapture
from native_interop_ice_packets import correlation, unavailable, validated_snapshot

MAX_MESSAGE = 16384


def read_message(stream, limit=MAX_MESSAGE):
    line = stream.readline(limit + 1)
    require(bool(line) and len(line.encode()) <= limit and line.endswith("\n"), "gateway_message_limit")
    result = json.loads(line)
    require(type(result) is dict, "gateway_message_shape")
    return result


class GatewayClient:
    """Fixed operations over anonymous pipes inherited from the owning parent."""
    def __init__(self, reader, writer, server):
        self.reader, self.writer, self.server = reader, writer, server

    def call(self, operation, **fields):
        self.writer.write(json.dumps({"op": operation, **fields}) + "\n")
        self.writer.flush()
        response = read_message(self.reader)
        require(set(response) == {"ok", "value"} and response["ok"] is True, "gateway_operation_failed")
        return response["value"]

    def ready(self, emulator):
        inode = namespace_inode(os.getpid())
        require(namespace_inode(emulator.process.pid) == inode
                and namespace_inode(self.server.pid) == inode, "native_emulator_namespace_mismatch")
        self.call("ready", emulator=emulator.process.pid, adb=self.server.pid)

    def before_cleanup(self, *, ice_correlation=None):
        if ice_correlation is None:
            return self.call("inventory")
        return self.call("inventory", ice_correlation=ice_correlation)
    def coverage(self, _fault): return GatewayCoverage(self)


class GatewayCoverage:
    def __init__(self, client): self.client = client
    def install(self): return self.client.call("install")
    def current(self): return self.client.call("current")
    def counters(self): return self.client.call("counters")
    def report(self): return self.client.call("report")
    def close(self): return self.client.call("close_profile")


class GatewayProfile:
    def __init__(self, gateway):
        self.gateway = gateway
        self.installed = False
        self.before = self.previous = None

    def install(self):
        require(not self.installed, "gateway_profile_already_installed")
        self.installed = True
        self.gateway.impair()
        self.before = self.previous = self.gateway.counters()

    def current(self):
        require(self.installed and self.previous is not None, "gateway_profile_not_installed")
        current = self.gateway.counters()
        require(current.keys() == self.previous.keys(), "gateway_direction_changed")
        for name in current:
            counter_delta(self.previous[name], current[name])
        self.previous = current
        return current

    def counters(self):
        current = self.current()
        return {direction: counter_delta(self.before[name], current[name]) for direction, name in
                (("egress", self.gateway.guest), ("ingress", self.gateway.host))}

    def report(self):
        deltas = self.counters()
        require(all(values[key] > 0 for values in deltas.values()
                    for key in ("bytes", "packets", "veth_tx_packets")), "gateway_native_traffic_missing")
        counters = {direction: {key: values[key] for key in ("bytes", "packets", "dropped")}
                    for direction, values in deltas.items()}
        return {"kind": "android_emulator_host_gateway_tc_netem", "delay_ms_each_way": 75,
                "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                "link_scope": "owned_host_namespace_veth", "counters": counters,
                "loss_observed": sum(values["dropped"] for values in counters.values()) > 0,
                "gateway_coverage": {"external_links": 1, "namespace_bound": True,
                    "ipv6_disabled": True, "veth_identity_current": True,
                    "directional_veth_packets": {direction: values["veth_tx_packets"]
                                                  for direction, values in deltas.items()}}}

    def close(self):
        if self.installed:
            self.gateway.clear_impairment()
            self.installed = False
            self.before = self.previous = None


class NativeChild(Child):
    def __init__(self, gateway, arguments):
        super().__init__(gateway, entry=[str(Path(__file__).resolve()), "--namespace-child", *arguments])
        self.gateway = gateway
        self.profile = GatewayProfile(gateway)
        self.ready = False
        self.operation_failed = False
        self.failed_operation = None
        self.requests = 0
        self.result = None
        self.ice_capture = None

    def begin(self):
        started = self.read(15)
        require(set(started) == {"status", "pid", "namespace_inode"}
                and started["status"] == "started" and type(started["pid"]) is int,
                "native_gateway_child_start")
        identity = process_identity(started["pid"])
        require(identity is not None and identity["namespace"] == self.gateway.netns_inode
                and started["namespace_inode"] == identity["namespace"] and identity["uid"] == os.getuid(),
                "native_gateway_child_identity")
        self.pid, self.inode, self.start_time = identity["pid"], identity["namespace"], identity["start"]
        self.identity = identity
        # The existing workflow environment travels only through the owned pipe.
        # Tokens never appear in argv, a temporary file, or a command report.
        environment = dict(os.environ)
        require(len(json.dumps(environment).encode()) < 256 * 1024, "native_environment_limit")
        self.send(environment)

    def dispatch(self, request):
        self.requests += 1
        require(self.requests <= 128, "native_gateway_request_limit")
        operation = request.get("op")
        require(type(operation) is str, "native_gateway_operation_type")
        shape = {"op", "emulator", "adb"} if operation == "ready" else {"op"}
        if operation == "inventory" and "ice_correlation" in request:
            shape = {"op", "ice_correlation"}
        require(set(request) == shape,
                "native_gateway_request_shape")
        self.gateway.commands = Commands({"commands": []})
        self.gateway.commands.deadline = time.monotonic() + 30
        if operation == "ready":
            require(not self.ready, "native_gateway_already_ready")
            for name in ("emulator", "adb"):
                require(type(request[name]) is int, "native_gateway_process_type")
                identity = self.inspect_process(request[name])
                require(identity is not None and identity["namespace"] == self.inode
                        and identity["uid"] == os.getuid(), "native_gateway_process_identity")
            self.capture_helpers(self.gateway)
            self.gateway.check_links()
            try: self.ice_capture = IceCapture.start(self.gateway)
            except Exception: self.ice_capture = None
            self.ready = True
            return None
        if operation == "inventory":
            self.capture_helpers(self.gateway)
            if "ice_correlation" in request:
                try:
                    if correlation(request["ice_correlation"]) is None: return unavailable()
                    return validated_snapshot(self.ice_capture.snapshot(request["ice_correlation"])) or unavailable()
                except Exception:
                    return unavailable()
            return None
        require(self.ready, "native_gateway_not_ready")
        operations = {"install": self.profile.install, "current": self.profile.current,
                      "counters": self.profile.counters, "report": self.profile.report,
                      "close_profile": self.profile.close}
        require(operation in operations, "native_gateway_unknown_operation")
        return operations[operation]()

    def receive_until_closed(self, deadline):
        while not self.closed and time.monotonic() < deadline:
            try:
                if self.ice_capture is not None: self.ice_capture.drain()
            except Exception:
                # Optional capture cannot replace or reclassify a controller failure.
                try: self.ice_capture.disable("unavailable")
                except Exception: pass
            try:
                request = self.read(min(1, deadline - time.monotonic()))
            except Unavailable as error:
                if str(error) == "child_reply_timeout":
                    continue
                raise
            if request.get("status") == "closed":
                require(set(request) == {"status", "cleanup", "code"}
                        and type(request["code"]) is int and request["code"] in (0, 1),
                        "native_gateway_close_shape")
                self.result = request
                self.closed = True
                break
            try:
                value = self.dispatch(request)
                self.send({"ok": True, "value": value})
            except Exception as error:
                self.operation_failed = True
                operation = request.get("op")
                self.failed_operation = {"operation": operation if type(operation) is str and operation in
                    {"ready", "inventory", "install", "current", "counters", "report", "close_profile"} else "invalid",
                    "error": type(error).__name__}
                self.send({"ok": False, "value": None})
        require(self.closed, "native_gateway_child_deadline")

    def close(self):
        try:
            if self.pid is None:
                stop_process(self.process)
            if not self.closed and self.pid is not None:
                descriptor = os.pidfd_open(self.pid)
                try:
                    current = process_identity(self.pid)
                    if current is not None:
                        require(same_process(current, self.identity), "native_gateway_child_changed")
                        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                finally:
                    os.close(descriptor)
                self.receive_until_closed(time.monotonic() + 60)
            self.process.wait(timeout=10)
            require(self.result is not None and self.result["cleanup"] == "passed",
                    "native_gateway_child_cleanup")
            require(self.process.returncode == self.result["code"], "native_gateway_child_exit")
        finally:
            try:
                capture = getattr(self, "ice_capture", None)
                if capture is not None:
                    capture.close()
                    require(not capture.cleanup_failed, "packet_broker_cleanup_unproven")
            finally:
                self.selector.close()
                self.process.stdin.close()
                self.process.stdout.close()


def namespace_child(arguments):
    writer = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    reader = os.fdopen(os.dup(sys.stdin.fileno()), "r")
    writer.write(json.dumps({"status": "started", "pid": os.getpid(),
                             "namespace_inode": namespace_inode(os.getpid())}) + "\n")
    writer.flush()
    environment = read_message(reader, 256 * 1024)
    require(all(type(key) is str and type(value) is str for key, value in environment.items()),
            "native_environment_shape")
    os.environ.clear()
    os.environ.update(environment)
    environment.clear()
    # Inherited standard streams must not expose either private RPC direction.
    # In particular, adb shell reads stdin while instrumentation remains alive.
    with open(os.devnull, "r+") as discarded:
        os.dup2(discarded.fileno(), sys.stdin.fileno())
        os.dup2(discarded.fileno(), sys.stdout.fileno())
    server = None
    code, cleanup = 1, "passed"
    try:
        def terminate(_signal, _frame): raise Unavailable("native_gateway_termination")
        signal.signal(signal.SIGTERM, terminate)
        sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
        server = subprocess.Popen([str(sdk / "platform-tools/adb"), "server", "nodaemon"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            require(server.poll() is None, "native_adb_server_exited")
            try:
                with socket.create_connection(("127.0.0.1", 5037), timeout=0.2): break
            except OSError: time.sleep(0.1)
        else: raise Unavailable("native_adb_server_unavailable")
        import native_interop_controller
        sys.argv = [native_interop_controller.__file__, *arguments]
        code = native_interop_controller.main(gateway=GatewayClient(reader, writer, server))
    except Exception:
        code = 1
    finally:
        try: stop_process(server)
        except Exception: cleanup = "failed"
        writer.write(json.dumps({"status": "closed", "cleanup": cleanup, "code": code}) + "\n")
        writer.flush()
        writer.close()
        reader.close()
    return code


def main():
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "--namespace-child":
        return namespace_child(arguments[1:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("android",), required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--workload", choices=("quick", "full"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    gateway = child = temporary = None
    failed = False
    cleanup_failures = []
    result_before = args.output.stat() if args.output.exists() else None
    try:
        require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true", "linux_ci_required")
        def terminate(_signal, _frame): raise Unavailable("native_gateway_termination")
        signal.signal(signal.SIGTERM, terminate)
        temporary = Path(tempfile.mkdtemp(prefix="mesh-native-gateway-", dir=os.environ["RUNNER_TEMP"]))
        gateway = Gateway(Commands({"commands": []}))
        gateway.create(temporary)
        child = NativeChild(gateway, arguments)
        child.begin()
        child.receive_until_closed(time.monotonic() + 52 * 60)
        require(child.result["code"] == 0 and not child.operation_failed, "native_controller_failed")
    except Exception:
        failed = True
    finally:
        if child is not None:
            try: child.close()
            except Exception: cleanup_failures.append("controller")
            if gateway is not None:
                gateway.commands = Commands({"commands": []})
                try: child.retire_helpers(gateway)
                except Exception: cleanup_failures.append("helpers")
        if gateway is not None:
            try: gateway.close()
            except Exception: cleanup_failures.append("gateway")
        if temporary is not None:
            try:
                (temporary / "resolv.conf").unlink(missing_ok=True)
                temporary.rmdir()
            except OSError: cleanup_failures.append("temporary")
    try:
        result_after = args.output.stat()
        require(result_before is None or (result_before.st_mtime_ns, result_before.st_size)
                != (result_after.st_mtime_ns, result_after.st_size), "stale_native_report")
        require(result_after.st_size <= 8 * 1024 * 1024, "native_report_limit")
        report = json.loads(args.output.read_text())
        require(type(report) is dict and report.get("role") == "android", "native_report_role")
        if report.get("passed") is True:
            require(report.get("source_commit") == args.expected_source
                    and type(report.get("execution")) is dict, "native_report_source")
    except Exception:
        report = {"v": 1, "passed": False, "role": "android", "phase": "host_gateway",
                  "failure_type": "GatewayUnavailable"}
        failed = True
    if not failed and not cleanup_failures and report.get("passed") is True:
        report["execution"]["host_gateway"] = {"kind": "owned_linux_network_namespace",
                                                "cleanup": "passed", "helpers_retired": True}
    else:
        report["passed"] = False
        report["host_gateway_failure"] = {"controller_failed": failed, "cleanup_failures": cleanup_failures,
            "operation_failure": getattr(child, "failed_operation", None)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
