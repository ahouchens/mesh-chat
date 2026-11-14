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
    assert result["reopen"] == {"service_replaced": True, "profile_authority_preserved": True,
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


def test_all_declared_attempts_remain_diagnostic_only(monkeypatch):
    source = "a" * 40
    bindings = {"source_commit": source, "source_tree": "b" * 40,
                "source_blobs": {"scripts/native_restart_diagnostic.py": "c" * 40}}
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: bindings)
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "d" * 64})
    monkeypatch.setattr(diagnostic, "run_attempt", lambda index: {"index": index, "passed": index != 2})
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


def test_successful_reopen_cannot_enter_full_native_acceptance():
    source, tree = "a" * 40, "b" * 40
    focused = {"v": 1, "passed": True, "diagnostic_only": True,
               "evidence_level": "android_packaged_reopen_diagnostic_only",
               "source_commit": source, "source_tree": tree,
               "attempts": [{"index": 1, "passed": True}]}
    with pytest.raises(ValueError, match="wrong source, scope, role or outcome"):
        verify_native_report(focused, source, tree, "android", workload="full")


def test_unexpected_attempt_error_does_not_drop_declared_later_results(monkeypatch):
    source = "a" * 40
    monkeypatch.setattr(diagnostic, "source_binding", lambda _: {"source_commit": source,
        "source_tree": "b" * 40, "source_blobs": {}})
    monkeypatch.setattr(diagnostic, "artifact_binding", lambda: {"host.apk": "c" * 64})
    def attempt(index):
        if index == 2:
            raise RuntimeError("PRIVATE_ATTEMPT_DETAIL")
        return {"index": index, "passed": True}
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
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["restart_diagnostic"]["default"] is False
    assert inputs["restart_repetitions"]["default"] == 1
    suffix = workflow["concurrency"]["group"].split("${{")[-1].removesuffix("}}")
    assert expression_value(suffix, "workflow_dispatch") == ""
    assert expression_value(suffix, "workflow_dispatch", restart_diagnostic=True) == "-restart"
    assert expression_value(suffix, "workflow_dispatch", gateway_probe=True) == "-gateway"
    assert expression_value(suffix, "workflow_dispatch", network_inventory=True) == "-inventory"


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
