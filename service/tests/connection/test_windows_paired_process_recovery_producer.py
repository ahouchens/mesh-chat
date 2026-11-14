"""Distinct installed paired-process recovery producer and evidence contract."""

import copy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_windows_paired_process_recovery as producer
import check_windows_separate_process_consumer as child_runner


def fixture_bytes():
    return (json.dumps({"v": 1, "passed": True, "scope": producer.FIXTURE_SCOPE,
                        "checks": producer.FIXTURE_CHECKS, "duration_ms": 71},
                       separators=(",", ":")) + "\n").encode()


def test_fixture_frame_requires_exact_bounded_delivered_recovery():
    assert producer.fixture_result(fixture_bytes())["checks"] == producer.FIXTURE_CHECKS
    for raw in (fixture_bytes() + b"extra\n", fixture_bytes().rstrip(b"\n"),
                fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                fixture_bytes().replace(b'"passed":true', b'"passed":false'),
                fixture_bytes().replace(b'"positive_owner_exits":4', b'"positive_owner_exits":3'),
                fixture_bytes().replace(b'"single_inbound_record":true', b'"single_inbound_record":1'),
                fixture_bytes().replace(b'"duration_ms":71', b'"duration_ms":360000'),
                b"PRIVATE_MESSAGE\n", b"x" * (producer.MAX_STDOUT + 1)):
        with pytest.raises((ValueError, UnicodeError)):
            producer.fixture_result(raw)


def test_selected_outer_budget_preserves_full_inner_recovery_window(tmp_path, monkeypatch):
    clock = [0.0]
    launched = []
    class Stream:
        def read(self, count): return b""
        def close(self): pass
    class Child:
        stdout = Stream()
        stderr = Stream()
        killed = False
        @property
        def returncode(self): return 0 if clock[0] >= 359 else None
        def poll(self): return self.returncode
        def kill(self): self.killed = True
        def wait(self, timeout): return self.returncode
    child = Child()
    def launch(*args, **kwargs):
        launched.append(args[0])
        return child
    monkeypatch.setattr(child_runner.subprocess, "Popen", launch)
    monkeypatch.setattr(child_runner, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda duration: clock.__setitem__(0, clock[0] + duration)))
    assert child_runner.run_fixture("node", tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                    600, fixture="paired_process_recovery") == b""
    assert launched[0][1] == producer.FIXTURE and 359 <= clock[0] < 360 and not child.killed
    with pytest.raises(ValueError, match="fixture_selector"):
        child_runner.run_fixture("node", tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                 600, fixture="../../private.mjs")
    assert len(launched) == 1


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
            names.append(producer.FIXTURE)
        monkeypatch.setattr(producer.bootstrap, "FILES", tuple(names))
        for name in names:
            (directory / name).write_bytes(name.encode())
        events.append("installed")
        return {"application_files": {name: producer.digest(directory / name) for name in names},
                "installed_sdk_entry": "node_modules/@mesh-chat/core-client/dist/index.js",
                "installed_outside_checkout": True, "imports_public_package": True}
    monkeypatch.setattr(producer, "install_typescript", install)
    monkeypatch.setattr(producer, "require_unchanged", lambda binary, binding: events.append("binding"))
    def protected(data):
        events.append("efs:" + data.name)
        return {"efs_profile_directory": True, "efs_vault_file": True}
    monkeypatch.setattr(producer.bootstrap, "protected_profile", protected)
    def exercise(node, directory, runtime, data, deadline, *, fixture):
        assert fixture == "paired_process_recovery"
        assert runtime == directory / binary.name and data == directory / "app-data"
        events.append("child_retired")
        return execution(runtime) if execution else fixture_bytes()
    monkeypatch.setattr(producer, "run_fixture", exercise)
    monkeypatch.setattr(producer, "cleanup", lambda directory, parent: events.append("cleanup"))
    return report, workspace, events


def test_success_requires_fixture_both_efs_profiles_final_binding_and_cleanup(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is True and result["checks"] == producer.CHECKS
    assert events == ["outside", "installed", "binding", "child_retired", "efs:offerer",
                      "efs:answerer", "binding", "cleanup"]
    assert producer.verify_report(result, "a" * 40, "b" * 40) is result
    assert workspace.is_dir()  # Cleanup double records ordering.


def test_failure_or_uncertain_result_retains_workspace(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=lambda runtime:
        b'{"v":1,"passed":false,"scope":"PRIVATE_PATH"}\n')
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "paired_process_execution"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "cleanup" not in events and "PRIVATE_PATH" not in json.dumps(result)

    other = tmp_path / "other"
    other.mkdir()
    report2, workspace2, events2 = prepared_run(other, monkeypatch, execution=lambda runtime:
        (_ for _ in ()).throw(TimeoutError("PRIVATE_TIMEOUT")))
    result2 = producer.run("a" * 40, bootstrap_report=report2, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "paired_process_execution"
    assert result2["workspace_retained"] is True and workspace2.is_dir()
    assert "cleanup" not in events2 and "PRIVATE_TIMEOUT" not in json.dumps(result2)


def test_missing_staged_fixture_or_efs_proof_refuses_success(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch, staged=False)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "outside_checkout_installation"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "child_retired" not in events

    other = tmp_path / "other"
    other.mkdir()
    report2, workspace2, events2 = prepared_run(other, monkeypatch)
    def unprotected(data):
        events2.append("efs:" + data.name)
        return {"efs_profile_directory": 1, "efs_vault_file": True}
    monkeypatch.setattr(producer.bootstrap, "protected_profile", unprotected)
    result2 = producer.run("a" * 40, bootstrap_report=report2, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "protected_profiles"
    assert result2["workspace_retained"] is True and workspace2.is_dir() and "cleanup" not in events2


def test_wrong_bootstrap_and_changed_staged_bytes_refuse_child_launch(tmp_path, monkeypatch):
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
    installed = producer.install_typescript
    def changed_install(directory, artifact, node, npm):
        value = installed(directory, artifact, node, npm)
        (directory / producer.FIXTURE).write_bytes(b"changed")
        return value
    monkeypatch.setattr(producer, "install_typescript", changed_install)
    result2 = producer.run("a" * 40, bootstrap_report=report, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "outside_checkout_installation"
    assert result2["workspace_retained"] is True and workspace.is_dir()
    assert "child_retired" not in events and "cleanup" not in events


def test_final_input_change_and_cleanup_failure_cannot_promote(tmp_path, monkeypatch):
    def changed(runtime):
        runtime.write_bytes(b"changed")
        return fixture_bytes()
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=changed)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "final_artifact_binding"
    assert result["workspace_retained"] is True and workspace.is_dir() and "cleanup" not in events

    other = tmp_path / "other"
    other.mkdir()
    report2, workspace2, events2 = prepared_run(other, monkeypatch)
    def failed_cleanup(directory, parent):
        events2.append("cleanup_attempt")
        raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(producer, "cleanup", failed_cleanup)
    result2 = producer.run("a" * 40, bootstrap_report=report2, temporary_root=other)
    assert result2["passed"] is False and result2["phase"] == "owned_workspace_cleanup"
    assert result2["workspace_retained"] is True and workspace2.is_dir()
    assert "PRIVATE_PATH" not in json.dumps(result2)


def test_cleanup_overrun_cannot_promote_positive_execution(tmp_path, monkeypatch):
    report, workspace, events = prepared_run(tmp_path, monkeypatch)
    actual = time.monotonic
    offset = [0]
    monkeypatch.setattr(producer, "time", SimpleNamespace(monotonic=lambda: actual() + offset[0]))
    def late_cleanup(directory, parent):
        events.append("cleanup")
        offset[0] = producer.TOTAL_SECONDS + 1
    monkeypatch.setattr(producer, "cleanup", late_cleanup)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "owned_workspace_cleanup"
    assert result["workspace_retained"] is True and workspace.is_dir() and "cleanup" in events


@pytest.mark.parametrize("field,value", [
    ("scope", "full SC23 acceptance"), ("fixture_duration_ms", True),
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
