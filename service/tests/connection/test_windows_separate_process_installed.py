"""Narrow installed R7 producer admission, retirement and evidence tests."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_windows_separate_process_consumer as producer


def fixture_bytes():
    return (json.dumps({"v": 1, "passed": True, "scope": producer.FIXTURE_SCOPE,
                        "checks": producer.FIXTURE_CHECKS, "duration_ms": 23},
                       separators=(",", ":")) + "\n").encode()


def failed_fixture_bytes(phase="owner_stop"):
    return (json.dumps({"v": 1, "passed": False, "scope": producer.FIXTURE_SCOPE,
                        "phase": phase, "duration_ms": 23}, separators=(",", ":")) + "\n").encode()


def test_fixture_result_is_one_exact_content_free_line():
    assert producer.fixture_result(fixture_bytes())["checks"] == producer.FIXTURE_CHECKS
    for raw in (fixture_bytes() + b"extra\n", fixture_bytes().rstrip(b"\n"),
                fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                fixture_bytes().replace(b'"passed":true', b'"passed":false'),
                fixture_bytes().replace(b'"normal_owners":1', b'"normal_owners":true'),
                fixture_bytes().replace(b'"duration_ms":23', b'"duration_ms":240000'),
                b"PRIVATE_PIPE\n", b"x" * (producer.MAX_STDOUT + 1)):
        with pytest.raises((ValueError, UnicodeError)):
            producer.fixture_result(raw)


def test_optional_failure_phase_discards_malformed_or_private_output():
    assert producer.fixture_failure(failed_fixture_bytes()) == "owner_stop"
    for raw in (failed_fixture_bytes() + b"extra\n",
                failed_fixture_bytes().replace(b'"phase":"owner_stop"', b'"phase":"PRIVATE_PATH"'),
                failed_fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                failed_fixture_bytes().replace(b'"duration_ms":23', b'"duration_ms":240001'),
                failed_fixture_bytes().replace(b'"phase":"owner_stop"',
                                               b'"phase":"owner_stop","raw":"PRIVATE_PATH"')):
        assert producer.fixture_failure(raw) is None
        with pytest.raises(ValueError):
            producer.fixture_result(raw)


def test_one_child_capture_requires_exit_and_bounded_drained_output(tmp_path, monkeypatch):
    script = tmp_path / "separate-process-check.mjs"
    script.write_text("import os,sys,time\nmode=os.environ['FIXTURE_CAPTURE_MODE']\n"
        "if mode=='sleep': time.sleep(10)\n"
        "elif mode=='overflow': sys.stdout.write('x'*5000)\n"
        "elif mode=='stderr': sys.stderr.write('PRIVATE_SECRET')\n"
        "elif mode=='failed': sys.stdout.buffer.write(os.environ['FIXTURE_FAILURE_RESULT'].encode()); sys.exit(1)\n"
        "else: sys.stdout.buffer.write(os.environ['FIXTURE_RESULT'].encode())\n",
        encoding="utf-8")
    actual_popen = producer.subprocess.Popen
    children = []
    def launch(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(producer.subprocess, "Popen", launch)
    monkeypatch.setenv("FIXTURE_RESULT", fixture_bytes().decode())
    monkeypatch.setenv("FIXTURE_FAILURE_RESULT", failed_fixture_bytes().decode())
    monkeypatch.setenv("FIXTURE_CAPTURE_MODE", "success")
    raw = producer.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                               time.monotonic() + 5)
    assert producer.fixture_result(raw)["passed"] is True
    assert len(children) == 1 and children[-1].poll() == 0
    for mode in ("overflow", "stderr", "sleep"):
        monkeypatch.setenv("FIXTURE_CAPTURE_MODE", mode)
        with pytest.raises((ValueError, TimeoutError)):
            producer.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                 time.monotonic() + (0.2 if mode == "sleep" else 5))
        assert children[-1].poll() is not None
    monkeypatch.setenv("FIXTURE_CAPTURE_MODE", "failed")
    with pytest.raises(producer.FixtureExecutionFailure) as caught:
        producer.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                             time.monotonic() + 5)
    assert caught.value.failure_phase == "owner_stop" and children[-1].poll() == 1


def test_retirement_cleanup_uses_one_shared_child_deadline(monkeypatch, tmp_path):
    class Stream:
        def read(self, count):
            time.sleep(2)
            return b""
        def close(self): pass
    class Stalled:
        def __init__(self):
            self.stdout = Stream()
            self.stderr = Stream()
            self.killed = False
            self.wait_budgets = []
        def poll(self): return None
        def kill(self): self.killed = True
        def wait(self, timeout):
            self.wait_budgets.append(timeout)
            time.sleep(timeout)
            raise subprocess.TimeoutExpired("fixture", timeout)
    child = Stalled()
    monkeypatch.setattr(producer.subprocess, "Popen", lambda *args, **kwargs: child)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        producer.run_fixture("node", tmp_path, tmp_path / "host.exe", tmp_path / "data", started + 0.5)
    elapsed = time.monotonic() - started
    assert child.killed is True and len(child.wait_budgets) == 1
    assert child.wait_budgets[0] < 0.2 and elapsed < 1.0


def prepared_run(tmp_path, monkeypatch, *, execution=None):
    binary = tmp_path / "sidecar.exe"
    binary.write_bytes(b"host")
    sdk = tmp_path / "sdk.tgz"
    sdk.write_bytes(b"sdk")
    report = tmp_path / "bootstrap.json"
    report.write_text("{}", encoding="utf-8")
    binding = {"source_commit": "a" * 40, "source_tree": "b" * 40,
               "sidecar_sha256": producer.digest(binary), "build_input_sha256": "c" * 64,
               "build_manifest_sha256": "d" * 64}
    workspace = tmp_path / "owned"
    events = []
    monkeypatch.setattr(producer, "verified_inputs", lambda source, prior:
                        (binary, binding, sdk, producer.digest(report)))
    monkeypatch.setattr(producer, "tools", lambda: ("node", "npm"))
    def outside(_parent):
        workspace.mkdir()
        events.append("outside")
        return workspace
    monkeypatch.setattr(producer, "outside_directory", outside)
    def install(directory, artifact, node, npm):
        for name in producer.FILES:
            (directory / name).write_bytes(name.encode())
        events.append("installed")
        return {"application_files": {name: producer.digest(directory / name) for name in producer.FILES},
                "installed_sdk_entry": "node_modules/@mesh-chat/core-client/dist/index.js",
                "installed_outside_checkout": True, "imports_public_package": True}
    monkeypatch.setattr(producer, "install_typescript", install)
    monkeypatch.setattr(producer, "require_unchanged", lambda binary, binding: events.append("binding"))
    monkeypatch.setattr(producer.bootstrap, "protected_profile", lambda data:
                        events.append("efs") or {"efs_profile_directory": True, "efs_vault_file": True})
    def exercise(node, directory, runtime, data, deadline):
        events.append("child_retired")
        return execution(runtime) if execution else fixture_bytes()
    monkeypatch.setattr(producer, "run_fixture", exercise)
    monkeypatch.setattr(producer, "cleanup", lambda directory, parent: events.append("cleanup"))
    return report, workspace, events


def test_producer_requires_positive_child_efs_final_binding_before_cleanup(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is True
    assert result["checks"] == producer.CHECKS
    assert events == ["outside", "installed", "binding", "child_retired", "efs", "binding", "cleanup"]
    assert producer.verify_report(result, "a" * 40, "b" * 40) is result
    assert workspace.is_dir()  # The test's cleanup double records ordering only.


def test_failed_fixture_and_changed_final_host_retain_owned_workspace(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=lambda runtime:
        b'{"v":1,"passed":false,"scope":"PRIVATE_PIPE"}\n')
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "separate_process_execution"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "cleanup" not in events and "PRIVATE_PIPE" not in json.dumps(result)

    other = tmp_path / "other"
    other.mkdir()
    def changed_runtime(runtime):
        runtime.write_bytes(b"changed")
        return fixture_bytes()
    report2, workspace2, events2 = prepared_run(other, monkeypatch, execution=changed_runtime)
    result2 = producer.run("a" * 40, bootstrap_report=report2, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "final_artifact_binding"
    assert result2["workspace_retained"] is True and workspace2.is_dir()
    assert "cleanup" not in events2


def test_failed_child_phase_is_retained_only_as_fixed_label(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=lambda runtime:
        (_ for _ in ()).throw(producer.FixtureExecutionFailure("owner_stop")))
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "separate_process_execution"
    assert result["fixture_failure"] == "owner_stop" and result["workspace_retained"] is True
    assert workspace.is_dir() and "cleanup" not in events


def test_wrong_bootstrap_preflight_refuses_install_and_launch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(producer, "verified_inputs", lambda *_:
                        (_ for _ in ()).throw(ValueError("bootstrap_binding")))
    monkeypatch.setattr(producer, "outside_directory", lambda *_: calls.append("outside"))
    monkeypatch.setattr(producer, "run_fixture", lambda *_: calls.append("launched"))
    result = producer.run("a" * 40, bootstrap_report=tmp_path / "missing", temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "source_artifact_binding"
    assert calls == [] and result["workspace_retained"] is False


def test_changed_installed_application_refuses_child_launch_and_retains_workspace(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    installed = producer.install_typescript
    def changed_install(directory, artifact, node, npm):
        value = installed(directory, artifact, node, npm)
        (directory / "consumer.mjs").write_bytes(b"changed")
        return value
    monkeypatch.setattr(producer, "install_typescript", changed_install)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "outside_checkout_installation"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "child_retired" not in events and "cleanup" not in events


def test_cleanup_failure_cannot_promote_positive_execution(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    def failed_cleanup(directory, parent):
        events.append("cleanup_attempt")
        raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(producer, "cleanup", failed_cleanup)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "owned_workspace_cleanup"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert events[-2:] == ["binding", "cleanup_attempt"]
    assert "PRIVATE_PATH" not in json.dumps(result)


def test_cleanup_overrun_cannot_promote_positive_execution(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    actual = time.monotonic
    offset = [0]
    monkeypatch.setattr(producer, "time", SimpleNamespace(monotonic=lambda: actual() + offset[0],
                                                            sleep=time.sleep))
    def late_cleanup(directory, parent):
        events.append("cleanup")
        offset[0] = producer.TOTAL_SECONDS + 1
    monkeypatch.setattr(producer, "cleanup", late_cleanup)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "owned_workspace_cleanup"
    assert "cleanup" in events and result["workspace_retained"] is True and workspace.is_dir()


@pytest.mark.parametrize("field,value", [
    ("scope", "SC26 acceptance"), ("fixture_duration_ms", True),
    ("bootstrap_report_sha256", "PRIVATE_HASH"), ("checks", {**producer.CHECKS, "extra": True}),
])
def test_report_validator_refuses_overclaim_and_extra_data(tmp_path, monkeypatch, field, value):
    report, _, _ = prepared_run(tmp_path, monkeypatch)
    record = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    changed = copy.deepcopy(record)
    changed[field] = value
    with pytest.raises(ValueError):
        producer.verify_report(changed, "a" * 40, "b" * 40)
