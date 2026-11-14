"""Diagnostic admission cannot replace the required native workload."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_workload as workloads
from native_interop_rendezvous import Rendezvous, checked_payload
from test_ui_core_boundary_interop_artifacts import CONTEXT


DIAGNOSTIC = "b8_first_cold"


def test_diagnostic_has_exact_full_prefix_and_one_cold_cycle():
    plan = workloads.workload(DIAGNOSTIC)
    assert plan["paths"] == workloads.PATH_CASES
    assert (plan["iterations"], plan["cold_start_every"]) == (1, 10)
    assert plan["level"] == "packaged_windows_android_emulator_b8_first_cold_diagnostic_only"
    assert "diagnostic" in plan["scope"].lower() and "100" in plan["scope"]
    assert workloads.workload("full")["iterations"] == 100
    assert workloads.workload("quick")["iterations"] == 5
    for event in ("workflow_dispatch", "pull_request", "push"):
        assert workloads.selected_workload(event, ["scripts/native_interop_controller.py"]) in {"quick", "full"}


def test_required_matrix_rejects_diagnostic_workload_before_reading_reports(tmp_path):
    import connection_matrix
    with pytest.raises(ValueError, match="qualification workload"):
        connection_matrix.collect(tmp_path, "a" * 40, "b" * 40, ["native_interop"],
                                  native_workload=DIAGNOSTIC)


@pytest.mark.parametrize("event,actions,selected,job,allowed", [
    ("workflow_dispatch", "true", "full", "native_windows_peer", True),
    ("workflow_dispatch", "true", "full", "native_android_peer", False),
    ("workflow_dispatch", "true", "quick", "native_windows_peer", False),
    ("workflow_dispatch", "false", "full", "native_windows_peer", False),
    ("pull_request", "true", "full", "native_windows_peer", False),
    ("push", "true", "full", "native_windows_peer", False),
    ("workflow_call", "true", "full", "native_windows_peer", False),
])
def test_controller_admits_diagnostic_only_for_manual_ci_before_binding(
        tmp_path, monkeypatch, event, actions, selected, job, allowed):
    import connection_ci
    source, tree = "a" * 40, "b" * 40
    output = tmp_path / "diagnostic.json"
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    monkeypatch.setenv("GITHUB_JOB", job)
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "windows", "--expected-source", source,
                                    "--workload", DIAGNOSTIC, "--output", str(output)])
    monkeypatch.setattr(controller, "source_identity", lambda _: (source, tree))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": selected})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {**CONTEXT, "source_commit": source})
    calls = []
    def bind(*args):
        calls.append(args)
        raise RuntimeError("PRIVATE_STOP_BEFORE_NATIVE")
    monkeypatch.setattr(controller, "binding", bind)
    assert controller.main() == 1
    assert bool(calls) is allowed
    report = json.loads(output.read_text())
    assert report["passed"] is False and report["workload"] == DIAGNOSTIC
    assert report["evidence_level"].endswith("diagnostic_only")
    assert "PRIVATE" not in json.dumps(report)


def test_single_cycle_completion_is_sealed_reciprocal_and_replay_checked():
    windows, android = Rendezvous(CONTEXT, "windows"), Rendezvous(CONTEXT, "android")
    try:
        windows.bind_partner(android.public_manifest())
        android.bind_partner(windows.public_manifest())
        value = {"completed": True}
        assert checked_payload("cold_complete_1", value) == value
        envelope = windows.seal("cold_complete_1", value)
        with pytest.raises(ValueError): android.open("cold_complete_10", envelope)
        assert android.open("cold_complete_1", envelope) == value
        with pytest.raises(ValueError): android.open("cold_complete_1", envelope)
        with pytest.raises(ValueError): checked_payload("cold_complete_1", {"completed": 1})
    finally:
        windows.close()
        android.close()


def test_six_path_prefix_runs_before_actual_first_cold_stop(monkeypatch):
    from test_ui_core_boundary_interop_controller import cold_setup_controller
    state = cold_setup_controller(monkeypatch, role="android")
    instance = state.controller
    instance.workload = workloads.workload(DIAGNOSTIC)
    instance.transport = SimpleNamespace(publish=lambda *_: None, wait=lambda *_args, **_kw: {})
    instance.rendezvous = SimpleNamespace(public_manifest=lambda: {}, bind_partner=lambda _: None)
    monkeypatch.setattr(instance, "initialize", lambda: None)
    monkeypatch.setattr(instance, "path_case", lambda *pair: state.events.append(("path", pair)))
    with pytest.raises(RuntimeError) as caught:
        instance.run()
    assert caught.value is state.stop
    assert state.events[:6] == [("path", pair) for pair in workloads.PATH_CASES]
    assert state.events[-1] == ("stop", {"crash": True, "_origin": "old_stop"})
    assert instance.cycles == []


@pytest.mark.parametrize("workload,event,allowed,prefix", [
    (DIAGNOSTIC, "workflow_dispatch", True, "native-interop-b8-first-cold"),
    (DIAGNOSTIC, "push", False, None),
    (DIAGNOSTIC, "pull_request", False, None),
    ("full", "workflow_dispatch", True, "native-interop"),
    ("quick", "pull_request", True, "native-interop"),
])
def test_node_action_admission_and_report_namespace(workload, event, allowed, prefix):
    script = """
      const childProcess = await import('node:child_process');
      const { EventEmitter } = await import('node:events');
      childProcess.default.spawn = (command, args) => {
        process.stdout.write('SPAWN:' + JSON.stringify(args) + '\\n');
        const child = new EventEmitter();
        child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
        child.kill = () => {};
        setImmediate(() => child.emit('exit', 0));
        return child;
      };
      (await import('node:module')).syncBuiltinESMExports();
      await import('./scripts/native-interop-artifact/action.mjs');
    """
    environment = {**os.environ, "INPUT_ROLE": "android", "INPUT_WORKLOAD": workload,
                   "GITHUB_JOB": "native_android_peer", "GITHUB_SHA": "a" * 40,
                   "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": event,
                   "ACTIONS_RUNTIME_TOKEN": "synthetic", "GITHUB_TOKEN": "synthetic"}
    result = subprocess.run([os.environ.get("MESH_NODE") or "node", "--input-type=module", "-e", script],
                            cwd=Path(__file__).resolve().parents[3], env=environment,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == (0 if allowed else 1), result.stderr
    launches = [line.removeprefix("SPAWN:") for line in result.stdout.splitlines() if line.startswith("SPAWN:")]
    assert bool(launches) is allowed
    if allowed:
        arguments = json.loads(launches[0])
        assert Path(arguments[0]).name == "native_interop_gateway_runtime.py"
        assert arguments[arguments.index("--workload") + 1] == workload
        assert Path(arguments[-1]).name == prefix + "-android.json"


@pytest.mark.parametrize("event,job,allowed", [("workflow_dispatch", "native_android_peer", True),
    ("workflow_dispatch", "native_windows_peer", False), ("pull_request", "native_android_peer", False),
    ("push", "native_android_peer", False)])
def test_gateway_rejects_automatic_diagnostic_before_creating_network_objects(tmp_path, monkeypatch, event, job, allowed):
    import native_interop_gateway_runtime as gateway
    output = tmp_path / "report.json"
    monkeypatch.setattr(gateway.sys, "platform", "linux")
    monkeypatch.setattr(gateway.sys, "argv", ["gateway", "--role", "android", "--expected-source", "a" * 40,
                                             "--workload", DIAGNOSTIC, "--output", str(output)])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_JOB", job)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(gateway.signal, "signal", lambda *_: None)
    calls = []
    def create(_):
        calls.append("gateway")
        raise RuntimeError("PRIVATE_STOP_BEFORE_NETWORK")
    monkeypatch.setattr(gateway, "Gateway", create)
    assert gateway.main() == 1
    assert bool(calls) is allowed
    assert json.loads(output.read_text())["passed"] is False
    assert not list(tmp_path.glob("mesh-native-gateway-*"))
