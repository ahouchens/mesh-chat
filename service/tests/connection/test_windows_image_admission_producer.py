"""Distinct installed image-path admission producer and report contracts."""

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
import check_windows_image_admission as producer
import check_windows_separate_process_consumer as child_runner


def fixture_bytes():
    return (json.dumps({"v": 1, "passed": True, "scope": producer.FIXTURE_SCOPE,
                        "checks": producer.FIXTURE_CHECKS, "duration_ms": 23},
                       separators=(",", ":")) + "\n").encode()


def test_fixture_frame_is_exact_and_does_not_accept_claims_or_private_data():
    assert producer.fixture_result(fixture_bytes())["checks"] == producer.FIXTURE_CHECKS
    for raw in (fixture_bytes() + b"extra\n", fixture_bytes().rstrip(b"\n"),
                fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                fixture_bytes().replace(b'"passed":true', b'"passed":false'),
                fixture_bytes().replace(b'"original_image_positive":true',
                                        b'"original_image_positive":1'),
                fixture_bytes().replace(b'"duration_ms":23', b'"duration_ms":120000'),
                b"PRIVATE_PIPE\n", b"x" * (producer.MAX_STDOUT + 1)):
        with pytest.raises((ValueError, UnicodeError)):
            producer.fixture_result(raw)


def test_shared_child_runner_selects_only_fixed_image_script(tmp_path, monkeypatch):
    script = tmp_path / "image-admission-check.mjs"
    script.write_text("import sys,time\nmode=sys.argv[-1]\n"
        "if mode=='sleep': time.sleep(10)\n"
        "else: sys.stdout.buffer.write(b'{}\\n')\n", encoding="utf-8")
    launched = []
    actual_popen = child_runner.subprocess.Popen
    def launch(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        launched.append((args[0], child))
        return child
    monkeypatch.setattr(child_runner.subprocess, "Popen", launch)
    raw = child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                   time.monotonic() + 5, fixture="image_admission")
    assert raw == b"{}\n"
    assert launched[-1][0][1] == "image-admission-check.mjs" and launched[-1][1].poll() == 0
    with pytest.raises(ValueError, match="fixture_selector"):
        child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                 time.monotonic() + 5, fixture="../../private.mjs")
    assert len(launched) == 1
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    with pytest.raises(TimeoutError):
        child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                 time.monotonic() + 0.2, fixture="image_admission")
    assert len(launched) == 2 and launched[-1][1].poll() is not None


def test_image_outer_budget_allows_full_inner_fixture_window(tmp_path, monkeypatch):
    clock = [0.0]
    class Stream:
        def read(self, count): return b""
        def close(self): pass
    class Child:
        stdout = Stream()
        stderr = Stream()
        killed = False
        @property
        def returncode(self): return 0 if clock[0] >= 119 else None
        def poll(self): return self.returncode
        def kill(self): self.killed = True
        def wait(self, timeout): return self.returncode
    child = Child()
    monkeypatch.setattr(child_runner.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(child_runner, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda duration: clock.__setitem__(0, clock[0] + duration)))
    assert child_runner.run_fixture("node", tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                    200, fixture="image_admission") == b""
    assert 119 <= clock[0] < 120 and child.killed is False


def prepared_run(tmp_path, monkeypatch, *, execution=None, staged=True):
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
        names = ["consumer.mjs", "runtime.mjs"]
        if staged:
            names.append("image-admission-check.mjs")
        monkeypatch.setattr(producer.bootstrap, "FILES", tuple(names))
        for name in names:
            (directory / name).write_bytes(name.encode())
        events.append("installed")
        return {"application_files": {name: producer.digest(directory / name) for name in names},
                "installed_sdk_entry": "node_modules/@mesh-chat/core-client/dist/index.js",
                "installed_outside_checkout": True, "imports_public_package": True}
    monkeypatch.setattr(producer, "install_typescript", install)
    monkeypatch.setattr(producer, "require_unchanged", lambda binary, binding: events.append("binding"))
    monkeypatch.setattr(producer.bootstrap, "protected_profile", lambda data:
                        events.append("efs") or {"efs_profile_directory": True, "efs_vault_file": True})
    def exercise(node, directory, runtime, data, deadline, *, fixture):
        assert fixture == "image_admission" and runtime == directory / binary.name
        events.append("child_retired")
        return execution(runtime) if execution else fixture_bytes()
    monkeypatch.setattr(producer, "run_fixture", exercise)
    monkeypatch.setattr(producer, "cleanup", lambda directory, parent: events.append("cleanup"))
    return report, workspace, events


def test_producer_requires_positive_child_efs_binding_and_cleanup(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is True and result["checks"] == producer.CHECKS
    assert events == ["outside", "installed", "binding", "child_retired", "efs", "binding", "cleanup"]
    assert producer.verify_report(result, "a" * 40, "b" * 40) is result
    assert workspace.is_dir()  # Cleanup double records ordering.


def test_invalid_fixture_or_changed_host_retains_workspace(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=lambda runtime:
        b'{"v":1,"passed":false,"scope":"PRIVATE_PIPE"}\n')
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "image_admission_execution"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "cleanup" not in events and "PRIVATE_PIPE" not in json.dumps(result)

    other = tmp_path / "other"
    other.mkdir()
    def changed(runtime):
        runtime.write_bytes(b"changed")
        return fixture_bytes()
    report2, workspace2, events2 = prepared_run(other, monkeypatch, execution=changed)
    result2 = producer.run("a" * 40, bootstrap_report=report2, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "final_artifact_binding"
    assert result2["workspace_retained"] is True and workspace2.is_dir() and "cleanup" not in events2


def test_missing_staged_fixture_refuses_launch(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, staged=False)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "outside_checkout_installation"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "child_retired" not in events and "cleanup" not in events


def test_unprotected_profile_cannot_promote_report(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    monkeypatch.setattr(producer.bootstrap, "protected_profile", lambda data:
                        (_ for _ in ()).throw(ValueError("PRIVATE_VAULT")))
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "protected_profile"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "cleanup" not in events and "PRIVATE_VAULT" not in json.dumps(result)


def test_bootstrap_or_cleanup_failure_cannot_promote_report(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(producer, "verified_inputs", lambda *_:
                        (_ for _ in ()).throw(ValueError("bootstrap_binding")))
    monkeypatch.setattr(producer, "outside_directory", lambda *_: calls.append("outside"))
    result = producer.run("a" * 40, bootstrap_report=tmp_path / "missing", temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "source_artifact_binding"
    assert result["workspace_retained"] is False and calls == []

    other = tmp_path / "other"
    other.mkdir()
    report, workspace, events = prepared_run(other, monkeypatch)
    def failed_cleanup(directory, parent):
        events.append("cleanup_attempt")
        raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(producer, "cleanup", failed_cleanup)
    result2 = producer.run("a" * 40, bootstrap_report=report, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "owned_workspace_cleanup"
    assert result2["workspace_retained"] is True and workspace.is_dir()
    assert "PRIVATE_PATH" not in json.dumps(result2)


@pytest.mark.parametrize("field,value", [
    ("scope", "SC22 acceptance"), ("fixture_duration_ms", True),
    ("bootstrap_report_sha256", "PRIVATE_HASH"), ("checks", {**producer.CHECKS, "extra": True}),
    ("application", {"application_files": {}, "installed_sdk_entry": "node_modules/@mesh-chat/core-client/x",
                     "installed_outside_checkout": True, "imports_public_package": True}),
])
def test_report_validator_refuses_overclaim_or_missing_fixture(tmp_path, monkeypatch, field, value):
    report, _, _ = prepared_run(tmp_path, monkeypatch)
    record = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    changed = copy.deepcopy(record)
    changed[field] = value
    with pytest.raises(ValueError):
        producer.verify_report(changed, "a" * 40, "b" * 40)
