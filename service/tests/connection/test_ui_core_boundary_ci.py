"""The fast boundary tests cannot hide affected native integration suites."""

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
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


@pytest.mark.parametrize("service_root", [False, True])
def test_required_inventory_binds_test_paths_to_the_actual_pytest_root(tmp_path, service_root):
    from connection_test_inventory import TestInventory
    selection = ("service/tests/test_app_owned_windows.py",)
    root = ROOT / "service" if service_root else ROOT
    prefix = "tests/" if service_root else "service/tests/"
    item = SimpleNamespace(nodeid=prefix + "test_app_owned_windows.py::test_case", user_properties=[])
    session = SimpleNamespace(items=[item], testsfailed=0,
                              config=SimpleNamespace(option=SimpleNamespace(), rootpath=root))
    inventory = TestInventory(tmp_path / "inventory.json", "source", selection)
    inventory.pytest_collection_finish(session)
    assert item.user_properties
    item.nodeid = "other/" + item.nodeid
    with pytest.raises(ValueError, match="was not collected"):
        inventory.pytest_collection_finish(session)


def test_normal_installed_windows_runtime_is_a_required_distinct_artifact_bound_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["desktop-host"]["steps"]
    build = next(index for index, step in enumerate(steps) if step.get("run") == "python scripts/build_sidecar.py")
    qualification = next(index for index, step in enumerate(steps)
                         if "scripts/check_independent_core_consumers.py" in step.get("run", ""))
    assert qualification > build
    assert "continue-on-error" not in steps[qualification] and "if" not in steps[qualification]
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert any("dist/reports/windows-independent-bootstrap.json" in step["with"]["path"] for step in uploads)
    assert "windows_independent_bootstrap" in ci.COMPONENTS["verification"]


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
        "typedFreshProfileBootstrapDoesNotSeedIdentity",
    }
    registry = [case for case in cases if case["class"] == "NativeProfileResultRegistrationTest"]
    assert {case["method"] for case in registry} == {
        "overlappingNonAuthSuccessCannotVerifyTheCurrentConfirmation",
        "cancelledActivityResultCannotAuthorizeAReplacementChallenge",
        "cancelledCredentialUiCannotSupplyProof",
    }
    assert all(case["scope"] == android.PROFILE_RESULT_SCOPE for case in registry)
    source = ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/NativeProfileResultRegistrationTest.kt"
    declared = re.findall(r"@Test\s+fun\s+(\w+)\s*\(", source.read_text(encoding="utf-8"))
    assert len(declared) == len(set(declared)) == 3
    assert set(declared) == {case["method"] for case in registry}
    assert len(cases) == len({case["id"] for case in cases}) == 13


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
