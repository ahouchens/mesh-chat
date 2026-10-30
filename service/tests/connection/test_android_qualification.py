import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "android_qualification.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("android_qualification", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def successful_output(run="current", method="case", test_class="NativeTest"):
    return f"""MESH_QUALIFICATION_RUN={run}
INSTRUMENTATION_STATUS: class=com.meshchat.runtime.{test_class}
INSTRUMENTATION_STATUS: test={method}
INSTRUMENTATION_STATUS: numtests=1
INSTRUMENTATION_STATUS_CODE: 1
INSTRUMENTATION_STATUS: class=com.meshchat.runtime.{test_class}
INSTRUMENTATION_STATUS: test={method}
INSTRUMENTATION_STATUS: numtests=1
INSTRUMENTATION_STATUS_CODE: 0
OK (1 test)
INSTRUMENTATION_CODE: -1
"""


def test_actual_single_instrumentation_success_is_required():
    gate.verify_case(successful_output(), "current", "NativeTest", "case")


@pytest.mark.parametrize("output", [
    "", "OK (1 test)", successful_output(run="old"),
    successful_output(method="other"), successful_output(test_class="OtherTest"),
    successful_output().replace("OK (1 test)", "OK (0 tests)"),
    successful_output().replace("numtests=1", "numtests=2"),
    successful_output().replace("STATUS_CODE: 0", "STATUS_CODE: -3"),
    successful_output().replace("STATUS_CODE: 0", "STATUS_CODE: -4"),
    successful_output() + successful_output(),
    successful_output() + "INSTRUMENTATION_FAILED: Process crashed\n",
])
def test_stale_wrong_skipped_crashed_or_duplicate_instrumentation_is_rejected(output):
    with pytest.raises(ValueError):
        gate.verify_case(output, "current", "NativeTest", "case")


def test_scenario_inventory_names_are_unique_and_both_offer_roles_are_mandatory():
    cases = list(gate.cases("webrtc")) + list(gate.cases("signaling"))
    assert len(cases) == len({case["id"] for case in cases}) == 24
    assert {case["method"] for case in cases} >= {
        "productionDesktopTransportOffersToNative", "productionDesktopTransportAnswersNative",
        "sharedRuntimeOwnsNativeRecoveryAcrossLifecycle",
    }


def inventory_fixture(directory):
    identity = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    artifacts = {"host.apk": "c" * 64, "tests.apk": "d" * 64}
    inventory = {"v": 1, **identity, "artifacts": artifacts, "run_id": "e" * 32,
                 "scenarios": gate.cases("webrtc"), "started_at": 1}
    (directory / "inventory.json").write_text(json.dumps(inventory))
    for case in gate.cases("webrtc"):
        (directory / case["report"]).write_text(successful_output("e" * 32, case["method"], case["class"]))
    return identity, artifacts, inventory


def test_evidence_counts_actual_execution_and_hashes_each_report(tmp_path):
    identity, artifacts, _ = inventory_fixture(tmp_path)
    result = gate.verify_suite(tmp_path, "webrtc", identity, artifacts)
    assert result["tests_collected"] == result["tests_executed"] == result["tests_passed"] == 16
    assert result["tests_skipped"] == result["tests_failed"] == 0
    assert all(len(case["report_sha256"]) == 64 for case in result["scenarios"])


@pytest.mark.parametrize("fault", ["source", "binary", "selection", "stale", "missing", "version"])
def test_wrong_source_artifact_selection_and_stale_or_missing_cases_fail(tmp_path, fault):
    identity, artifacts, inventory = inventory_fixture(tmp_path)
    if fault == "source":
        inventory["source_commit"] = "f" * 40
    elif fault == "binary":
        inventory["artifacts"] = {"other.apk": "f" * 64}
    elif fault == "selection":
        inventory["scenarios"].pop()
    elif fault == "stale":
        inventory["run_id"] = "f" * 32
    elif fault == "version":
        inventory["v"] = True
    else:
        (tmp_path / inventory["scenarios"][0]["report"]).unlink()
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    with pytest.raises((ValueError, FileNotFoundError)):
        gate.verify_suite(tmp_path, "webrtc", identity, artifacts)


@pytest.mark.parametrize("processes", ["USER PID NAME\nu0 12 com.meshchat.runtime.smoke:mesh_bootstrap", ""])
def test_live_test_process_or_uninspectable_cleanup_cannot_pass(monkeypatch, processes):
    def adb(*arguments):
        if arguments[-1] == "ro.kernel.qemu":
            return "1"
        return processes if "ps" in arguments else ""
    monkeypatch.setattr(gate, "adb", adb)
    with pytest.raises(ValueError):
        gate.emulator_and_cleanup()


def test_emulator_evidence_cannot_be_produced_from_a_physical_device(monkeypatch):
    monkeypatch.setattr(gate, "adb", lambda *args: "0")
    with pytest.raises(ValueError, match="emulator"):
        gate.emulator_and_cleanup()


def test_failed_runner_cannot_reuse_prior_success_or_leak_private_output(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "REPORTS", tmp_path)
    (tmp_path / "android-qualification.json").write_text('{"passed":true}')
    assert gate.report(1) == 1
    result = json.loads((tmp_path / "android-qualification.json").read_text())
    assert result["passed"] is False
    assert set(result) == {"v", "passed", "evidence_level", "failure_type", "phase"}
