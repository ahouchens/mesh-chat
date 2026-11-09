"""The fast boundary tests cannot hide affected native integration suites."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("boundary_ci", ROOT / "scripts/connection_ci.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def test_isolated_ui_boundary_and_parser_tests_run_their_actual_consumers():
    plan = ci.select(["tests/core-ui-boundary/app.test.tsx", "tests/core-ui-boundary/facade_host.py",
                      "tests/core-ui-boundary/request-vectors.json",
                      "service/tests/connection/test_ui_core_boundary_requests.py"])
    assert plan["required"] == ["policy", "verification"]
    assert plan["reason"] == "isolated_ui_core_boundary_tests"


@pytest.mark.parametrize("path", [
    "src/App.tsx", "src/api.ts", "src-tauri/src/lib.rs", "service/src/mesh_chat/core_api/requests.py",
    "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/TypedCoreBridgeBoundaryTest.kt",
    "tests/core-ui-boundary/../../src/api.ts", "tests\\core-ui-boundary\\app.test.tsx",
    "scripts/check_core_ui_boundary.py", ".github/workflows/ci.yml", "pnpm-lock.yaml",
])
def test_production_android_tooling_mixed_or_ambiguous_changes_keep_full_matrix(path):
    assert ci.select(["tests/core-ui-boundary/app.test.tsx", path])["required"] == list(ci.SUITES)


@pytest.mark.parametrize("event", ["workflow_dispatch", "merge_group", "schedule", "release", "unknown"])
def test_final_manual_and_release_gates_never_narrow_boundary_qualification(event):
    assert ci.select(["tests/core-ui-boundary/app.test.tsx"], event=event)["required"] == list(ci.SUITES)


def test_missing_boundary_runtime_or_skipped_required_verification_cannot_pass():
    plan = ci.select(["tests/core-ui-boundary/app.test.tsx"])
    jobs = {suite: {"result": "success" if suite == "policy" else "skipped"} for suite in ci.SUITES}
    with pytest.raises(ValueError, match="verification"):
        ci.validate(plan, jobs)


def test_android_typed_app_cases_are_required_by_the_artifact_bound_inventory():
    spec = importlib.util.spec_from_file_location("boundary_android", ROOT / "scripts/android_qualification.py")
    android = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(android)
    cases = android.cases("core_api")
    actual = {case["method"] for case in cases if case["class"] == "TypedCoreBridgeBoundaryTest"}
    assert actual == {
        "typedProfileWorkspaceAndSettingsReachProductionCore",
        "typedDraftAndLostReplyRetryKeepOneDurableMessage",
        "typedErrorsPreserveConflictAndCallerAuthority",
        "typedSettingsMutationsReadBackFromTheRealDomain",
        "typedCallControlSignsQueuesAndEndsAnApprovedCall",
    }
    assert len(cases) == len({case["id"] for case in cases}) == 9


@pytest.mark.parametrize("body", [
    "<testsuites/>",
    '<testsuite><testcase name="omitted"><skipped/></testcase></testsuite>',
    '<testsuite><testcase name="failed"><failure/></testcase></testsuite>',
    '<testsuite><testcase name="passed"/><error/></testsuite>',
])
def test_fast_gate_rejects_empty_skipped_failed_and_collection_error_results(tmp_path, body):
    spec = importlib.util.spec_from_file_location("boundary_gate", ROOT / "scripts/check_core_ui_boundary.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    junit = tmp_path / "result.xml"
    junit.write_text(body, encoding="utf-8")
    assert gate.junit_summary(junit)["passed"] is False


def test_windows_gate_rejects_missing_environment_and_removes_stale_success(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("boundary_windows_gate", ROOT / "scripts/check_core_windows_boundary.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr("sys.argv", ["check_core_windows_boundary.py", "--expected-source", "a" * 40])
    report = tmp_path / "dist/reports/core-windows-boundary.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"passed":true}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="environment is unavailable"):
        gate.main()
    assert not report.exists()
