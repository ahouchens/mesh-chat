"""Offline host gateway lifecycle contracts; real native evidence comes from CI."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import native_interop_gateway_runtime as runtime
import native_interop_gateway_probe as probe
from native_interop_gateway_runtime import GatewayProfile


class FakeGateway:
    host, guest = "owned-host", "owned-guest"
    def __init__(self):
        self.events = []
        self.packet_count = 10
    def check_links(self): self.events.append("current")
    def impair(self): self.events.append("install")
    def clear_impairment(self): self.events.append("remove")
    def counters(self):
        return {name: {"bytes": self.packet_count * 100, "packets": self.packet_count,
                       "dropped": 0, "veth_tx_packets": self.packet_count,
                       "veth_rx_packets": self.packet_count} for name in (self.host, self.guest)}


def test_gateway_report_requires_traffic_and_both_owned_directions():
    gateway = FakeGateway()
    profile = GatewayProfile(gateway)
    profile.install()
    with pytest.raises(RuntimeError, match="traffic"):
        profile.report()
    gateway.packet_count += 3
    report = profile.report()
    assert report["kind"] == "android_emulator_host_gateway_tc_netem"
    assert report["counters"] == {direction: {"bytes": 300, "packets": 3, "dropped": 0}
                                  for direction in ("egress", "ingress")}
    assert report["gateway_coverage"]["external_links"] == 1
    profile.close()
    assert gateway.events[-1] == "remove"


def test_gateway_counter_reset_fails_before_reporting_or_next_snapshot():
    gateway = FakeGateway()
    profile = GatewayProfile(gateway)
    profile.install()
    gateway.packet_count += 5
    profile.current()
    gateway.packet_count -= 1
    with pytest.raises(RuntimeError, match="counter_regression"):
        profile.report()


def test_gateway_profile_rejects_double_install_and_closes_partial_install():
    gateway = FakeGateway()
    profile = GatewayProfile(gateway)
    profile.install()
    with pytest.raises(RuntimeError, match="already_installed"):
        profile.install()
    profile.close()
    profile.install()
    profile.close()
    assert gateway.events.count("install") == gateway.events.count("remove") == 2


def test_gateway_profile_preserves_cleanup_obligation_after_install_failure():
    gateway = FakeGateway()
    def fail(): raise RuntimeError("partial qdisc")
    gateway.impair = fail
    profile = GatewayProfile(gateway)
    with pytest.raises(RuntimeError, match="partial qdisc"):
        profile.install()
    profile.close()
    assert "remove" in gateway.events


@pytest.mark.parametrize("payload", ["", "{}", "[]\n", "null\n", "x" * 16385 + "\n"])
def test_private_control_rejects_incomplete_oversized_or_nonobject_messages(payload):
    import io
    with pytest.raises((RuntimeError, ValueError)):
        runtime.read_message(io.StringIO(payload))


@pytest.mark.parametrize("message", [{"op": "shell", "command": "PRIVATE"}, {"op": "shell"},
                                     {"op": "install", "command": "PRIVATE"}, {"op": []}])
def test_parent_control_does_not_accept_arbitrary_commands(message):
    child = object.__new__(runtime.NativeChild)
    child.requests, child.ready = 0, True
    child.gateway, child.profile = SimpleNamespace(), SimpleNamespace(
        **{name: lambda: pytest.fail("unknown operation executed") for name in
           ("install", "current", "counters", "report", "close")})
    with pytest.raises(RuntimeError): child.dispatch(message)


def test_parent_rejects_profile_install_before_validated_emulator_boot():
    child = object.__new__(runtime.NativeChild)
    child.requests, child.ready = 0, False
    child.gateway = SimpleNamespace()
    with pytest.raises(RuntimeError, match="not_ready"):
        child.dispatch({"op": "install"})


def test_parent_rejects_emulator_outside_owned_namespace(monkeypatch):
    child = object.__new__(runtime.NativeChild)
    child.requests, child.ready, child.inode = 0, False, 22
    child.gateway = SimpleNamespace()
    child.inspect_process = lambda pid: {"uid": 1000, "namespace": 23}
    monkeypatch.setattr(runtime.os, "getuid", lambda: 1000, raising=False)
    with pytest.raises(RuntimeError, match="process_identity"):
        child.dispatch({"op": "ready", "emulator": 15, "adb": 16})


@pytest.mark.parametrize("namespace", [22, 23])
def test_environment_pipe_is_sent_only_after_child_namespace_validation(monkeypatch, namespace):
    child = object.__new__(runtime.NativeChild)
    child.gateway = SimpleNamespace(netns_inode=22)
    child.read = lambda timeout: {"status": "started", "pid": 15, "namespace_inode": namespace}
    sent = []
    child.send = sent.append
    monkeypatch.setattr(runtime.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(runtime, "process_identity", lambda pid: {"pid": pid, "uid": 1000, "namespace": namespace, "start": "10"})
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-private-token")
    if namespace == 22:
        child.begin()
        assert sent[0]["GITHUB_TOKEN"] == "synthetic-private-token"
    else:
        with pytest.raises(RuntimeError, match="child_identity"): child.begin()
        assert sent == []


def test_gateway_close_rejects_foreign_qdisc_without_removing_it():
    gateway = runtime.Gateway(SimpleNamespace())
    gateway.impaired_links = [gateway.host]
    gateway.check_links = lambda: None
    calls = []
    def run(*args):
        calls.append(args)
        return "qdisc fq_codel 900: root refcnt 2\n"
    gateway.run = run
    with pytest.raises(RuntimeError, match="owned_netem_profile_unavailable"):
        gateway.clear_impairment()
    assert all("del" not in call for call in calls)
    assert gateway.impaired_links == [gateway.host]


def test_gateway_close_confirms_absence_after_ambiguous_install():
    gateway = runtime.Gateway(SimpleNamespace())
    gateway.impaired_links = [gateway.host]
    gateway.check_links = lambda: None
    calls = []
    def run(*args):
        calls.append(args)
        return "qdisc noqueue 0: root refcnt 2\n"
    gateway.run = run
    gateway.clear_impairment()
    assert not gateway.impaired_links and all("del" not in call for call in calls)


def directional_gateway(*, fail_add=False, foreign=False):
    gateway = probe.Gateway(SimpleNamespace())
    gateway.check_links = lambda: None
    state = {"host": "noqueue", "guest": "noqueue", "dropped": 0, "calls": []}
    noqueue = "qdisc noqueue 0: root refcnt 2\n"
    def command(*args):
        state["calls"].append(args)
        if args[:4] == ("tc", "qdisc", "show", "dev"):
            link = "host" if args[4] == gateway.host else "guest"
            return noqueue if state[link] == "noqueue" else (
                "qdisc fq_codel 900: root refcnt 2\n" if state[link] == "foreign" else
                "qdisc netem a101: root refcnt 2 limit 1000 loss 100%\n")
        if args[:5] == ("tc", "-s", "qdisc", "show", "dev"):
            assert args[5] == gateway.host
            if state["host"] == "foreign":
                return "qdisc fq_codel 900: root refcnt 2\n"
            return ("qdisc netem a101: root refcnt 2 limit 1000 loss 100%\n"
                    f" Sent 0 bytes 0 pkt (dropped {state['dropped']}, overlimits 0 requeues 0)\n")
        if args[:3] == ("tc", "qdisc", "add"):
            state["host"] = "loss"
            if fail_add:
                raise RuntimeError("ambiguous_add")
            return ""
        if args[:3] == ("tc", "qdisc", "del"):
            state["host"] = "noqueue"
            return ""
        pytest.fail(f"unexpected gateway command: {args}")
    gateway.run = command
    gateway.inside = command
    if foreign:
        state["host"] = "foreign"
        gateway.directional_loss = True
    return gateway, state


def test_directional_loss_uses_only_owned_host_qdisc_and_recovers_counted_echo():
    gateway, state = directional_gateway()
    gateway.install_directional_loss()
    assert state["host"] == "loss" and state["guest"] == "noqueue"
    before = gateway.directional_loss_counters()
    state["dropped"] = 2
    assert probe.counter_delta(before, gateway.directional_loss_counters())["dropped"] == 2
    gateway.clear_directional_loss()
    assert state["host"] == state["guest"] == "noqueue"
    assert not gateway.directional_loss
    assert [args for args in state["calls"] if args[:3] == ("tc", "qdisc", "add")] == [
        ("tc", "qdisc", "add", "dev", gateway.host, "root", "handle", gateway.handles[gateway.host],
         "netem", "loss", "100%")]
    assert len([args for args in state["calls"] if args[:3] == ("tc", "qdisc", "del")]) == 1


@pytest.mark.parametrize("fault", ["wrong_handle", "delay", "second_qdisc", "missing_counters"])
def test_directional_counter_parser_requires_one_exact_owned_loss_qdisc(fault):
    row = ("qdisc netem a101: root refcnt 2 limit 1000 loss 100%\n"
           " Sent 0 bytes 0 pkt (dropped 2, overlimits 0 requeues 0)\n")
    if fault == "wrong_handle": row = row.replace("a101:", "a103:")
    elif fault == "delay": row = row.replace("limit 1000 loss", "limit 1000 delay 75ms loss")
    elif fault == "second_qdisc": row += "qdisc fq_codel 900: parent a101:1\n"
    else: row = row.replace(" Sent 0 bytes 0 pkt", " stats unavailable")
    with pytest.raises(probe.Unavailable, match="owned_directional_loss_unavailable"):
        probe.parse_directional_loss(row, "a101:")


@pytest.mark.parametrize("fault", ["none", "bypass", "uncounted", "recovery"])
def test_directional_control_requires_absent_echo_counted_drop_and_recovery(fault):
    events = []
    class Gateway:
        installed = False
        def clear_impairment(self): events.append("symmetric_removed")
        def require_noqueue(self): events.append("noqueue")
        def install_directional_loss(self): self.installed = True; events.append("host_loss")
        def directional_loss_counters(self):
            return {"bytes": 0, "packets": 0, "dropped": 1 if self.installed and len(events) > 4
                    and fault != "uncounted" else 0}
        def clear_directional_loss(self): self.installed = False; events.append("loss_removed")
    class Child:
        def echo(self, gateway, port):
            events.append("echo")
            if gateway.installed:
                return fault == "bypass"
            return fault != "recovery" or "host_loss" not in events
    gateway = Gateway()
    if fault == "none":
        result = probe.exercise_directional_loss(gateway, Child(), 10001)
        assert result == {"kind": "owned_host_veth_egress_netem_100pct",
                          "host_qdisc_delta": {"bytes": 0, "packets": 0, "dropped": 1},
                          "guest_echo_received": False}
        assert events == ["symmetric_removed", "noqueue", "echo", "host_loss", "echo",
                          "loss_removed", "noqueue", "echo"]
    else:
        with pytest.raises(probe.Unavailable, match={
                "bypass": "directional_loss_echo_bypassed", "uncounted": "directional_loss_not_counted",
                "recovery": "directional_recovery_echo_failed"}[fault]):
            probe.exercise_directional_loss(gateway, Child(), 10001)


def test_directional_partial_add_is_retired_only_after_owned_profile_proof():
    gateway, state = directional_gateway(fail_add=True)
    with pytest.raises(RuntimeError, match="ambiguous_add"):
        gateway.install_directional_loss()
    assert gateway.directional_loss and state["host"] == "loss"
    gateway.close()
    assert state["host"] == "noqueue" and not gateway.directional_loss
    assert len([args for args in state["calls"] if args[:3] == ("tc", "qdisc", "del")]) == 1


def test_directional_failed_add_with_no_qdisc_confirms_absence_without_delete():
    gateway, state = directional_gateway()
    def fail_without_add(*args):
        if args[:3] == ("tc", "qdisc", "add"):
            state["calls"].append(args)
            raise RuntimeError("add_refused")
        return original(*args)
    original = gateway.run
    gateway.run = fail_without_add
    with pytest.raises(RuntimeError, match="add_refused"):
        gateway.install_directional_loss()
    assert gateway.directional_loss and state["host"] == "noqueue"
    gateway.close()
    assert not gateway.directional_loss
    assert not any(args[:3] == ("tc", "qdisc", "del") for args in state["calls"])


def test_directional_foreign_qdisc_refuses_delete_and_gateway_cleanup_fails_closed():
    gateway, state = directional_gateway(foreign=True)
    gateway.resources = ["veth"]
    with pytest.raises(probe.Unavailable, match="gateway_cleanup_incomplete"):
        gateway.close()
    assert state["host"] == "foreign" and gateway.directional_loss
    assert not any(args[:3] == ("tc", "qdisc", "del") or args[:3] == ("ip", "link", "del")
                   for args in state["calls"])


@pytest.mark.parametrize("fault", ["missing", "failed", "helpers", "guest_claim"])
def test_native_gateway_evidence_cannot_pass_without_full_cleanup(fault):
    from test_ui_core_boundary_interop_controller import interop_reports
    from native_interop_evidence import verify_pair
    windows, android = interop_reports()
    if fault == "missing": del android["execution"]["host_gateway"]
    elif fault == "failed": android["execution"]["host_gateway"]["cleanup"] = "failed"
    elif fault == "helpers": android["execution"]["host_gateway"]["helpers_retired"] = False
    else: android["execution"]["scenarios"][-1]["impairment"]["kind"] = "android_emulator_linux_kernel_tc_netem"
    with pytest.raises(ValueError): verify_pair(windows, android, "a" * 40, "b" * 40)


def test_host_coverage_keeps_uid_udp_block_without_touching_guest_qdiscs(monkeypatch):
    import native_interop_faults as faults
    from test_ui_core_boundary_interop_path_setup import kernel_boundary
    peer, resolver, events = kernel_boundary(point="link_qdisc")
    coverage = SimpleNamespace()
    def forbidden(*args): pytest.fail("host coverage must not inspect guest qdiscs")
    monkeypatch.setattr(faults, "_BoundedUdpLinks", forbidden)
    path = faults.AndroidKernelPath(peer, {"pair": {"relay_protocol": "udp", "local": {"type": "relay"}}},
        "turn:turn.example:3478?transport=udp", resolver=resolver, resource_check=lambda: True,
        coverage_factory=lambda fault: coverage)
    assert path.coverage is coverage
    assert path.target_kind == "uid_udp_all_destinations" and path.rule_count == 2
    assert path.uid_udp_mode and path.protocol == "udp"
    assert not any("qdisc" in repr(event) for event in events)


def test_child_exit_code_must_match_its_cleanup_reply():
    import io
    child = object.__new__(runtime.NativeChild)
    child.pid, child.closed = 15, True
    child.result = {"code": 0, "cleanup": "passed"}
    child.process = SimpleNamespace(returncode=1, wait=lambda timeout: None,
                                    stdin=io.BytesIO(), stdout=io.BytesIO())
    child.selector = SimpleNamespace(close=lambda: None)
    with pytest.raises(RuntimeError, match="child_exit"): child.close()
    assert child.process.stdin.closed and child.process.stdout.closed


@pytest.mark.parametrize("fault", ["none", "controller", "child_cleanup", "helpers", "gateway", "wrong_source"])
def test_outer_cleanup_failure_cannot_leave_a_passing_native_report(monkeypatch, tmp_path, fault):
    import json
    output = tmp_path / "result.json"
    events = []
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.sys, "argv", ["gateway", "--role", "android", "--expected-source", "a" * 40,
                                             "--workload", "full", "--output", str(output)])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(runtime.signal, "signal", lambda *args: None)
    class Gateway:
        def __init__(self, commands): pass
        def create(self, directory): (directory / "resolv.conf").write_text("fixture")
        def close(self):
            events.append("gateway")
            if fault == "gateway": raise RuntimeError("fixture cleanup")
    class Child:
        def __init__(self, gateway, arguments):
            self.result = {"code": 1 if fault == "controller" else 0}
            self.operation_failed = False
        def begin(self): pass
        def receive_until_closed(self, deadline):
            output.write_text(json.dumps({"passed": True, "role": "android", "execution": {},
                "source_commit": ("b" if fault == "wrong_source" else "a") * 40}))
        def close(self):
            events.append("child")
            if fault == "child_cleanup": raise RuntimeError("fixture cleanup")
        def retire_helpers(self, gateway):
            events.append("helpers")
            if fault == "helpers": raise RuntimeError("fixture cleanup")
    monkeypatch.setattr(runtime, "Gateway", Gateway)
    monkeypatch.setattr(runtime, "NativeChild", Child)
    assert runtime.main() == (0 if fault == "none" else 1)
    report = json.loads(output.read_text())
    assert report["passed"] is (fault == "none")
    assert events == ["child", "helpers", "gateway"]
    assert not list(tmp_path.glob("mesh-native-gateway-*"))


def test_privileged_commands_do_not_inherit_workflow_credentials(monkeypatch):
    import native_interop_gateway_probe as probe
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("ACTIONS_RUNTIME_TOKEN", "synthetic-runtime-token")
    seen = []
    def collect(argv, **options):
        seen.append(options.get("env"))
        return {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": "",
                "stdout_truncated": False, "stderr_truncated": False}
    monkeypatch.setattr(probe, "_collect_process", collect)
    assert probe.Commands({"commands": []}).run("ip", "link", "show", privileged=True) == "ok"
    assert seen[0] is not None
    assert "GITHUB_TOKEN" not in seen[0] and "ACTIONS_RUNTIME_TOKEN" not in seen[0]
    assert seen[0]["PATH"] == probe.os.environ["PATH"]


def test_namespace_launcher_environment_is_token_free_before_pipe_handoff(monkeypatch):
    import io
    import native_interop_gateway_probe as probe
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("ACTIONS_RUNTIME_TOKEN", "synthetic-runtime-token")
    monkeypatch.setattr(probe.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(probe.os, "getgid", lambda: 1000, raising=False)
    captured = []
    process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO())
    def launch(argv, **options):
        captured.append((argv, options.get("env")))
        return process
    monkeypatch.setattr(probe.subprocess, "Popen", launch)
    monkeypatch.setattr(probe, "stop_process", lambda process: None)
    def fail_selector(): raise OSError("fixture stops before native IO")
    monkeypatch.setattr(probe.selectors, "DefaultSelector", fail_selector)
    with pytest.raises(OSError): probe.Child(SimpleNamespace(ns="owned"))
    argv, environment = captured[0]
    assert environment is not None
    assert "GITHUB_TOKEN" not in environment and "ACTIONS_RUNTIME_TOKEN" not in environment
    assert "synthetic-github-token" not in repr(argv) and "synthetic-runtime-token" not in repr(argv)


def test_native_subprocess_cannot_consume_private_gateway_replies():
    import json
    import os
    from pathlib import Path
    import queue
    import subprocess
    import sys
    import textwrap
    import threading

    script = textwrap.dedent('''
        import contextlib, os, subprocess, sys
        from types import SimpleNamespace
        import native_interop_gateway_runtime as runtime
        real_run, real_popen = subprocess.run, subprocess.Popen
        server = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
        def launch(argv, **options):
            if argv[1:] == ["server", "nodaemon"]: return server
            return real_popen(argv, **options)
        runtime.subprocess.Popen = launch
        runtime.stop_process = lambda process: None
        runtime.namespace_inode = lambda pid: 22
        runtime.socket.create_connection = lambda *a, **kw: contextlib.nullcontext()
        def controller(*, gateway):
            # A real descendant inherits fd0 just like adb shell instrumentation.
            # It must see EOF rather than compete with the gateway reader.
            result = real_run([sys.executable, "-c",
                "import os; assert os.read(0, 1) == b''; print('not-rpc')"],
                timeout=3, check=True)
            assert gateway.reader.fileno() != 0
            assert not os.get_inheritable(gateway.reader.fileno())
            assert not os.get_inheritable(gateway.writer.fileno())
            assert gateway.call("install") == "private-reply"
            return 0
        sys.modules['native_interop_controller'] = SimpleNamespace(__file__='fixture', main=controller)
        raise SystemExit(runtime.namespace_child([]))
    ''')
    environment = {**os.environ, "PYTHONPATH": str(Path(runtime.__file__).parent)}
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
    messages = queue.Queue()
    def read_output():
        for line in process.stdout: messages.put(line)
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        assert json.loads(messages.get(timeout=10))["status"] == "started"
        bootstrap = {key: os.environ[key] for key in ("PATH", "SystemRoot", "TEMP", "TMP") if key in os.environ}
        process.stdin.write(json.dumps({**bootstrap, "ANDROID_HOME": "synthetic-sdk"}) + "\n")
        process.stdin.flush()
        assert json.loads(messages.get(timeout=10)) == {"op": "install"}
        process.stdin.write(json.dumps({"ok": True, "value": "private-reply"}) + "\n")
        process.stdin.flush()
        assert json.loads(messages.get(timeout=10)) == {"status": "closed", "cleanup": "passed", "code": 0}
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None: process.kill()
        process.wait(timeout=10)
        reader.join(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
