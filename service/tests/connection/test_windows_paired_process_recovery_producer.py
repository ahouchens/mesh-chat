"""Distinct installed paired-process recovery producer and evidence contract."""

import copy
import io
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


def failure_bytes(stage="enqueue_and_pending", cause="pending_record_changed", pairing=None):
    value = {"v": 1, "passed": False, "scope": producer.FIXTURE_SCOPE,
             "phase": "paired_process_recovery", "stage": stage, "cause": cause,
             "duration_ms": 71}
    if pairing is not None:
        value["pairing_failure"] = pairing
    return (json.dumps(value, separators=(",", ":")) + "\n").encode()


def test_fixture_frame_requires_exact_bounded_delivered_recovery():
    assert producer.fixture_result(fixture_bytes())["checks"] == producer.FIXTURE_CHECKS
    for raw in (fixture_bytes() + b"extra\n", fixture_bytes().rstrip(b"\n"),
                fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                fixture_bytes().replace(b'"passed":true', b'"passed":false'),
                fixture_bytes().replace(b'"positive_owner_exits":4', b'"positive_owner_exits":3'),
                fixture_bytes().replace(b'"single_inbound_record":true', b'"single_inbound_record":1'),
                fixture_bytes().replace(b'"terminal_snapshot_watermark":true', b'"terminal_snapshot_watermark":false'),
                fixture_bytes().replace(b'"same_caller_progress_resumed_after_restart":true',
                                        b'"same_caller_progress_resumed_after_restart":false'),
                fixture_bytes().replace(b'"duration_ms":71', b'"duration_ms":360000'),
                b"PRIVATE_MESSAGE\n", b"x" * (producer.MAX_STDOUT + 1)):
        with pytest.raises((ValueError, UnicodeError)):
            producer.fixture_result(raw)


def test_failed_fixture_frame_selects_only_fixed_stage_and_cause():
    assert producer.fixture_failure(failure_bytes()) == {
        "stage": "enqueue_and_pending", "cause": "pending_record_changed"}
    assert producer.fixture_failure(failure_bytes("event_delivery", "delivery_event_replay")) == {
        "stage": "event_delivery", "cause": "delivery_event_replay"}
    for raw in (failure_bytes() + b"extra\n", failure_bytes().rstrip(b"\n"),
                failure_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                failure_bytes().replace(b'"passed":false', b'"passed":true'),
                failure_bytes().replace(b'"stage":"enqueue_and_pending"', b'"stage":"PRIVATE_PATH"'),
                failure_bytes().replace(b'"cause":"pending_record_changed"', b'"cause":"PRIVATE_TEXT"'),
                failure_bytes().replace(b'"duration_ms":71', b'"duration_ms":360001'),
                failure_bytes().replace(b'"phase":"paired_process_recovery"', b'"phase":"arguments"'),
                failure_bytes().replace(b'"duration_ms":71', b'"duration_ms":71,"text":"PRIVATE"'),
                b"PRIVATE_MESSAGE\n", b"x" * (producer.MAX_STDOUT + 1)):
        assert producer.fixture_failure(raw) is None


def test_initial_pairing_summary_requires_exact_existing_phase_subphase_and_code():
    summary = {"phase": "public_pairing", "subphase": "offer_code_wait",
               "error_code": "unavailable"}
    assert producer.fixture_failure(failure_bytes("initial_pairing", "public_pairing_deadline", summary)) == {
        "stage": "initial_pairing", "cause": "public_pairing_deadline", "pairing_failure": summary}
    for bad in ({**summary, "subphase": "pending_request_wait"},
                {**summary, "phase": "shared_host_lifetime"},
                {**summary, "error_code": "PRIVATE_CODE"},
                {**summary, "text": "PRIVATE_TEXT"}):
        assert producer.fixture_failure(failure_bytes("initial_pairing", "unavailable", bad)) is None
    assert producer.fixture_failure(failure_bytes("delivery_receipt", "unavailable", summary)) is None


@pytest.mark.parametrize("stderr", [b"", b"PRIVATE_STDERR"])
def test_selected_runner_retains_only_valid_failure_labels_with_empty_stderr(tmp_path, monkeypatch, stderr):
    class Child:
        returncode = 1
        def __init__(self):
            self.stdout = io.BytesIO(failure_bytes())
            self.stderr = io.BytesIO(stderr)
        def poll(self): return self.returncode
        def wait(self, timeout): return self.returncode
    monkeypatch.setattr(child_runner.subprocess, "Popen", lambda *args, **kwargs: Child())
    with pytest.raises(child_runner.FixtureExecutionFailure) as caught:
        child_runner.run_fixture("node", tmp_path, tmp_path / "host.exe", tmp_path / "data",
                                 time.monotonic() + 10, fixture="paired_process_recovery",
                                 failure_parser=producer.fixture_failure)
    assert caught.value.failure_detail == (
        {"stage": "enqueue_and_pending", "cause": "pending_record_changed"} if not stderr else None)
    assert "PRIVATE" not in str(caught.value)


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
    def exercise(node, directory, runtime, data, deadline, *, fixture, failure_parser):
        assert fixture == "paired_process_recovery"
        assert failure_parser is producer.fixture_failure
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


def test_valid_fixed_failure_detail_survives_producer_without_content(tmp_path, monkeypatch):
    def failed(_runtime):
        raise child_runner.FixtureExecutionFailure(None, producer.fixture_failure(failure_bytes()))
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=failed)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == "paired_process_execution"
    assert result["failure_type"] == "FixtureExecutionFailure"
    assert result["fixture_stage"] == "enqueue_and_pending"
    assert result["fixture_cause"] == "pending_record_changed"
    assert result["workspace_retained"] is True and workspace.is_dir()
    assert "cleanup" not in events and "PRIVATE" not in json.dumps(result)


def test_valid_initial_pairing_summary_survives_producer_without_payload(tmp_path, monkeypatch):
    pairing = {"phase": "explicit_approval", "subphase": "pending_request_wait",
               "error_code": "rate_limited"}
    detail = producer.fixture_failure(failure_bytes("initial_pairing", "unavailable", pairing))
    def failed(_runtime):
        raise child_runner.FixtureExecutionFailure(None, detail)
    report, workspace, events = prepared_run(tmp_path, monkeypatch, execution=failed)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["pairing_failure"] == pairing
    assert result["fixture_stage"] == "initial_pairing" and result["fixture_cause"] == "unavailable"
    assert result["workspace_retained"] is True and workspace.is_dir() and "cleanup" not in events
    assert "PRIVATE" not in json.dumps(result)


def test_unvalidated_failure_detail_cannot_enter_producer_report(tmp_path, monkeypatch):
    def failed(_runtime):
        raise child_runner.FixtureExecutionFailure(None, {"stage": "PRIVATE_PATH",
                                                       "cause": "pending_record_changed"})
    report, workspace, _ = prepared_run(tmp_path, monkeypatch, execution=failed)
    result = producer.run("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    assert result["passed"] is False and result["workspace_retained"] is True and workspace.is_dir()
    assert "fixture_stage" not in result and "fixture_cause" not in result
    assert "PRIVATE" not in json.dumps(result)


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
