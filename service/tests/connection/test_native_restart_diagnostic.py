"""The focused reopen report retains failures without claiming qualification."""

import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_restart_diagnostic as diagnostic
from native_interop_evidence import verify_report as verify_native_report


class FakeEmulator:
    IMAGE = "system-images;android-35;google_apis;x86_64"

    def __init__(self, events):
        self.events = events
        self.process = SimpleNamespace(poll=lambda: None)
        self.observation = SimpleNamespace(snapshot=lambda: {})

    def start(self, apks):
        assert tuple(apks) == diagnostic.APKS
        self.events.append("emulator_start")

    def close(self):
        self.events.append("emulator_close")
        self.process = None


class FakePeer:
    def __init__(self, events, *, fail_reopen=False, fail_cleanup=False):
        self.events = events
        self.fail_reopen = fail_reopen
        self.fail_cleanup = fail_cleanup
        self.process = None
        self.starts = 0

    def start(self):
        self.starts += 1
        self.events.append("peer_start")
        self.process = object()
        if self.starts == 2 and self.fail_reopen:
            raise diagnostic.PeerFailure("android_host_start_failed")
        return {"service_incarnation": str(self.starts)}

    def core(self, operation):
        if operation == "runtime.capabilities":
            return {"profiles": ["PRIVATE_PROFILE_ID"]}
        assert operation == "application.snapshot"
        return {"profile": {"destination_hash": "PRIVATE_DESTINATION"}}

    def stop(self, *, crash=False, delete_profile=False, _origin=None):
        self.events.append("crash_stop" if crash else "clean_stop")
        if not crash and self.fail_cleanup:
            raise RuntimeError("PRIVATE_CLEANUP_DETAIL")
        self.process = None

    def failure_start_observation(self, error):
        if error.code != "android_host_start_failed":
            return None
        return {"v": 1, "stage": "initialize", "exception_kind": "peer_failure",
                "error_code": "peer_closed", "rollback_exception_kind": "called_process_error"}

    def failure_lifecycle_observation(self, _error):
        return None


def attempt(*, fail_reopen=False, fail_cleanup=False):
    events = []
    peer = FakePeer(events, fail_reopen=fail_reopen, fail_cleanup=fail_cleanup)
    result = diagnostic.run_attempt(1, emulator_factory=lambda: FakeEmulator(events),
                                    peer_factory=lambda _key: peer)
    return result, events


def test_reopen_uses_packaged_peer_lifecycle_and_retains_only_comparisons():
    result, events = attempt()
    assert result["passed"] is True
    assert result["reopen"] == {"service_replaced": True, "profile_handle_preserved": True,
                                "identity_preserved": True}
    assert events == ["emulator_start", "peer_start", "crash_stop", "peer_start",
                      "clean_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(result)


def test_reopen_failure_precedes_cleanup_failure_and_keeps_both():
    result, events = attempt(fail_reopen=True, fail_cleanup=True)
    assert result["passed"] is False and result["stage"] == "peer_reopen"
    assert result["primary_failure"]["error_code"] == "android_host_start_failed"
    assert result["primary_failure"]["android_start_failure"]["stage"] == "initialize"
    assert [item["stage"] for item in result["cleanup_failures"]] == ["peer_cleanup"]
    assert events[-2:] == ["clean_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(result)


def test_in_progress_observation_retains_primary_before_cleanup():
    events, observations = [], []
    peer = FakePeer(events, fail_reopen=True, fail_cleanup=True)
    result = diagnostic.run_attempt(1, emulator_factory=lambda: FakeEmulator(events),
        peer_factory=lambda _key: peer, observe=lambda value: observations.append(
            json.loads(json.dumps(value))))
    initial = next(item for item in observations if item["stage"] == "peer_reopen"
                   and "primary_failure" in item)
    assert initial["primary_failure"]["error_code"] == "android_host_start_failed"
    cleanup = next(item for item in observations if item["stage"] == "peer_cleanup"
                   and "cleanup_failures" in item)
    assert cleanup["primary_failure"] == initial["primary_failure"]
    assert cleanup["cleanup_failures"][0]["stage"] == "peer_cleanup"
    assert result["retirement_verified"] is False
    assert "PRIVATE" not in json.dumps(observations)


def test_emulator_retirement_failure_is_not_reusable():
    events = []
    class UnretiredEmulator(FakeEmulator):
        def close(self):
            self.events.append("emulator_close")
            raise RuntimeError("PRIVATE_EMULATOR_DETAIL")
    result = diagnostic.run_attempt(1, emulator_factory=lambda: UnretiredEmulator(events),
        peer_factory=lambda _key: FakePeer(events))
    assert result["retirement_verified"] is False and result["passed"] is False
    assert [item["stage"] for item in result["cleanup_failures"]] == ["emulator_cleanup"]
    assert "PRIVATE" not in json.dumps(result)


def test_atomic_report_replacement_keeps_prior_checkpoint_on_error(tmp_path, monkeypatch):
    path = tmp_path / "diagnostic.json"
    diagnostic.write_report(path, {"v": 1, "passed": False, "current_attempt": None})
    original = path.read_bytes()
    def fail_replace(*_):
        raise OSError("PRIVATE_REPLACE_DETAIL")
    with monkeypatch.context() as patch:
        patch.setattr(diagnostic.os, "replace", fail_replace)
        with pytest.raises(OSError):
            diagnostic.write_report(path, {"v": 1, "passed": False,
                "current_attempt": {"index": 2, "stage": "peer_reopen"}})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    with monkeypatch.context() as patch:
        patch.setattr(diagnostic, "MAX_REPORT_BYTES", 8)
        with pytest.raises(ValueError, match="budget"):
            diagnostic.write_report(path, {"v": 1, "passed": True})
    assert path.read_bytes() == original


def test_all_declared_attempts_remain_diagnostic_only(monkeypatch):
    source = "a" * 40
    bindings = {"source_commit": source, "source_tree": "b" * 40,
                "source_blobs": {"scripts/native_restart_diagnostic.py": "c" * 40}}
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: bindings)
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "d" * 64})
    monkeypatch.setattr(diagnostic, "run_attempt", lambda index, observe=None:
        {"index": index, "passed": index != 2, "retirement_verified": True})
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_JOB": "android_restart_diagnostic", "GITHUB_SHA": source,
                       "GITHUB_REPOSITORY": "ahouchens/mesh-chat", "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    report = diagnostic.run(source, 3)
    assert [item["index"] for item in report["attempts"]] == [1, 2, 3]
    assert report["passed"] is False and report["diagnostic_only"] is True
    assert report["artifact_origin"]["qualification_verified"] is False
    assert "native_interop" not in report["evidence_level"]


def test_checkpoints_preserve_completed_and_in_progress_attempts_then_block(tmp_path, monkeypatch):
    source, executed = "a" * 40, []
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: {"source_commit": source,
        "source_tree": "b" * 40, "source_blobs": {}})
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "c" * 64})
    def attempt(index, observe=None):
        executed.append(index)
        observe({"index": index, "stage": "peer_start"})
        observe({"index": index, "stage": "peer_reopen"})
        return {"index": index, "passed": index == 1, "retirement_verified": index == 1}
    monkeypatch.setattr(diagnostic, "run_attempt", attempt)
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_JOB": "android_restart_diagnostic", "GITHUB_SHA": source,
                       "GITHUB_REPOSITORY": "ahouchens/mesh-chat", "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    path, snapshots = tmp_path / "report.json", []
    def checkpoint(report):
        diagnostic.write_report(path, report)
        snapshots.append(json.loads(path.read_text()))
    report = diagnostic.run(source, 3, checkpoint=checkpoint)
    assert snapshots[0]["attempts"] == [] and snapshots[0]["current_attempt"] is None
    assert any(len(item["attempts"]) == 1 and item["current_attempt"] ==
               {"index": 2, "stage": "peer_reopen"} for item in snapshots)
    assert executed == [1, 2]
    assert [item["index"] for item in report["attempts"]] == [1, 2, 3]
    assert report["attempts"][2] == {"index": 3, "passed": False, "blocked": True,
                                      "reason": "prior_retirement_unresolved", "retirement_verified": False}
    assert json.loads(path.read_text()) == report
    assert report["passed"] is False and report["current_attempt"] is None


def test_checkpoint_failure_never_claims_success_or_starts_next_attempt(tmp_path, monkeypatch):
    source, executed = "a" * 40, []
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: {"source_commit": source,
        "source_tree": "b" * 40, "source_blobs": {}})
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "c" * 64})
    def attempt(index, observe=None):
        executed.append(index)
        observe({"index": index, "stage": "peer_reopen"})
        return {"index": index, "passed": True, "retirement_verified": True}
    monkeypatch.setattr(diagnostic, "run_attempt", attempt)
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_JOB": "android_restart_diagnostic", "GITHUB_SHA": source,
                       "GITHUB_REPOSITORY": "ahouchens/mesh-chat", "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    path, failed = tmp_path / "report.json", False
    def checkpoint(report):
        nonlocal failed
        current = report["current_attempt"]
        if not failed and current == {"index": 1, "stage": "peer_reopen"}:
            failed = True
            raise OSError("PRIVATE_WRITE_DETAIL")
        diagnostic.write_report(path, report)
    report = diagnostic.run(source, 2, checkpoint=checkpoint)
    assert executed == [1] and report["passed"] is False
    assert report["runner_failure"]["stage"] == "report_checkpoint"
    assert report["attempts"][1]["reason"] == "report_checkpoint_unavailable"
    assert json.loads(path.read_text()) == report
    assert "PRIVATE" not in path.read_text()


def test_successful_reopen_cannot_enter_full_native_acceptance():
    source, tree = "a" * 40, "b" * 40
    focused = {"v": 1, "passed": True, "diagnostic_only": True,
               "evidence_level": "android_packaged_reopen_diagnostic_only",
               "source_commit": source, "source_tree": tree,
               "attempts": [{"index": 1, "passed": True}]}
    with pytest.raises(ValueError, match="wrong source, scope, role or outcome"):
        verify_native_report(focused, source, tree, "android", workload="full")


def test_unexpected_attempt_error_blocks_later_repetitions(monkeypatch):
    source = "a" * 40
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: {"source_commit": source,
        "source_tree": "b" * 40, "source_blobs": {}})
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "c" * 64})
    executed = []
    def attempt(index, observe=None):
        executed.append(index)
        if index == 2:
            raise RuntimeError("PRIVATE_ATTEMPT_DETAIL")
        return {"index": index, "passed": True, "retirement_verified": True}
    monkeypatch.setattr(diagnostic, "run_attempt", attempt)
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_JOB": "android_restart_diagnostic", "GITHUB_SHA": source,
                       "GITHUB_REPOSITORY": "ahouchens/mesh-chat", "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    report = diagnostic.run(source, 3)
    assert [item["index"] for item in report["attempts"]] == [1, 2, 3]
    assert report["attempts"][1]["primary_failure"]["exception_kind"] == "RuntimeError"
    assert report["attempts"][2]["blocked"] is True and executed == [1, 2]
    assert report["passed"] is False and "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("repetitions", [0, 4, True])
def test_invalid_repetition_declaration_cannot_start(monkeypatch, repetitions):
    monkeypatch.setattr(diagnostic, "run_attempt", lambda _: pytest.fail("Attempt started"))
    report = diagnostic.run("a" * 40, repetitions)
    assert report["passed"] is False and report["attempts"] == []
    assert report["runner_failure"]["stage"] == "source_binding"


def test_fractional_dispatch_input_writes_a_failed_report(tmp_path, monkeypatch):
    output = tmp_path / "diagnostic.json"
    monkeypatch.setattr(sys, "argv", ["native_restart_diagnostic", "--expected-source", "a" * 40,
                                    "--repetitions", "1.5", "--output", str(output)])
    assert diagnostic.main() == 1
    report = json.loads(output.read_text())
    assert report["declared_repetitions"] == "1.5" and report["attempts"] == []
    assert report["runner_failure"]["stage"] == "source_binding"


def test_workflow_is_manual_and_keeps_diagnostic_artifact_separate():
    path = Path(__file__).resolve().parents[3] / ".github/workflows/native-restart-diagnostic.yml"
    workflow = path.read_text()
    parsed = yaml.safe_load(workflow)
    events = parsed.get("on", parsed.get(True))
    assert set(events) == {"workflow_call", "workflow_dispatch"}
    assert "pull_request:" not in workflow
    assert "native-restart-diagnostic-${{ github.sha }}" in workflow
    assert "native-interop-android-${{ github.sha }}" not in workflow
    assert "connection-qualification" not in workflow
    assert set(parsed["jobs"]) == {"android_restart_diagnostic"}
    assert events["workflow_call"]["inputs"]["probe"]["default"] == "reopen"
    assert events["workflow_call"]["inputs"]["repetitions"]["default"] == 1
    assert events["workflow_dispatch"]["inputs"]["probe"]["options"] == ["reopen", "boot_comparison"]


def expression_value(expression, event, **flags):
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("github.event_name", repr(event))
    expression = re.sub(r"\binputs\.([a-z_]+)\b", lambda match: repr(flags.get(match[1], False)), expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    return eval(expression, {"__builtins__": {}}, {})


def selected_jobs(workflow, event, **flags):
    jobs = set()
    for name, definition in workflow["jobs"].items():
        if expression_value(definition["if"], event, **flags):
            jobs.add(name)
    return jobs


@pytest.mark.parametrize("inventory,gateway,restart,expected", [
    (False, False, False, "android"),
    (True, False, False, "network_inventory"),
    (False, True, False, "gateway_probe"),
    (False, False, True, "restart_diagnostic"),
    (True, True, False, "diagnostic_conflict"),
    (True, False, True, "diagnostic_conflict"),
    (False, True, True, "diagnostic_conflict"),
    (True, True, True, "diagnostic_conflict"),
])
def test_android_workflow_routes_one_manual_mode(inventory, gateway, restart, expected):
    path = Path(__file__).resolve().parents[3] / ".github/workflows/android-webrtc.yml"
    workflow = yaml.safe_load(path.read_text())
    assert selected_jobs(workflow, "workflow_dispatch", network_inventory=inventory,
                         gateway_probe=gateway, restart_diagnostic=restart) == {expected}


def test_android_workflow_call_keeps_ordinary_job_and_restart_is_isolated():
    path = Path(__file__).resolve().parents[3] / ".github/workflows/android-webrtc.yml"
    workflow = yaml.safe_load(path.read_text())
    assert selected_jobs(workflow, "workflow_call") == {"android"}
    assert workflow["jobs"]["restart_diagnostic"]["uses"] == "./.github/workflows/native-restart-diagnostic.yml"
    assert workflow["jobs"]["restart_diagnostic"]["with"]["repetitions"] == "${{ inputs.restart_repetitions }}"
    assert workflow["jobs"]["restart_diagnostic"]["with"]["probe"] == "${{ inputs.restart_probe }}"
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["restart_diagnostic"]["default"] is False
    assert inputs["restart_repetitions"]["default"] == 1
    assert inputs["restart_probe"]["default"] == "reopen"
    assert inputs["restart_probe"]["options"] == ["reopen", "boot_comparison"]
    suffix = workflow["concurrency"]["group"].split("${{")[-1].removesuffix("}}")
    assert expression_value(suffix, "workflow_dispatch") == ""
    assert expression_value(suffix, "workflow_dispatch", restart_diagnostic=True) == "-restart"
    assert expression_value(suffix, "workflow_dispatch", gateway_probe=True) == "-gateway"
    assert expression_value(suffix, "workflow_dispatch", network_inventory=True) == "-inventory"
    for flags in (
        {"restart_diagnostic": True, "gateway_probe": True},
        {"restart_diagnostic": True, "network_inventory": True},
        {"gateway_probe": True, "network_inventory": True},
        {"restart_diagnostic": True, "gateway_probe": True, "network_inventory": True},
    ):
        assert expression_value(suffix, "workflow_dispatch", **flags) == "-conflict"


def test_diagnostic_uses_existing_android_package_recipe():
    root = Path(__file__).resolve().parents[3] / ".github/workflows"
    ordinary = yaml.safe_load((root / "android-webrtc.yml").read_text())["jobs"]["android"]["steps"]
    focused = yaml.safe_load((root / "native-restart-diagnostic.yml").read_text())["jobs"]["android_restart_diagnostic"]["steps"]
    by_name = lambda steps: {step["name"]: step for step in steps if "name" in step}
    ordinary, focused = by_name(ordinary), by_name(focused)
    for old, new in (
        ("Install Android SDK and NDK packages", "Install the qualification Android SDK and NDK"),
        ("Build Android debug APK", "Build the same-source Android app"),
        ("Build optimized WebRTC test host", "Build the existing optimized native host"),
        ("Verify optimized WebRTC JNI classes", "Verify optimized WebRTC JNI classes"),
        ("Build WebRTC instrumentation APK", "Build the existing instrumentation host"),
        ("Free disk for the emulator system image", "Free disk for the emulator system image"),
        ("Enable KVM for Android interoperability tests", "Enable KVM for the packaged peer"),
    ):
        assert focused[new]["run"] == ordinary[old]["run"]
        assert focused[new].get("working-directory") == ordinary[old].get("working-directory")


def test_boot_comparison_skips_package_build_and_reopen_uses_only_its_runner():
    path = Path(__file__).resolve().parents[3] / ".github/workflows/native-restart-diagnostic.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["android_restart_diagnostic"]["steps"]
    for step in steps:
        name = step.get("name")
        if name in {"Validate diagnostic mode", "Retain every diagnostic result"}:
            continue
        condition = step.get("if")
        if condition is None:
            assert step.get("uses") in {"actions/checkout@v7", "actions/setup-python@v7",
                                        "actions/setup-java@v5", "android-actions/setup-android@v4"} or name in {
                                            "Enable KVM for the packaged peer", "Install the native peer system image"}
        else:
            assert condition in {"${{ inputs.probe == 'reopen' }}", "${{ inputs.probe == 'boot_comparison' }}"}
    boot = next(step for step in steps if step.get("name") == "Compare emulator boot launchers")
    reopen = next(step for step in steps if step.get("name") == "Run bounded reopen observations")
    assert "scripts/native_emulator_boot_diagnostic.py" in boot["run"]
    assert "scripts/native_restart_diagnostic.py" in reopen["run"]
    assert "--output dist/reports/native-restart-diagnostic.json" in boot["run"]
    assert "--output dist/reports/native-restart-diagnostic.json" in reopen["run"]
    assert boot["if"] == "${{ inputs.probe == 'boot_comparison' }}"
    assert reopen["if"] == "${{ inputs.probe == 'reopen' }}"
    admission = next(step for step in steps if step.get("name") == "Validate diagnostic mode")
    assert '"$RESTART_PROBE" != "reopen"' in admission["run"]
    assert '"$RESTART_PROBE" == "boot_comparison" && "$RESTART_REPETITIONS" != "1"' in admission["run"]
