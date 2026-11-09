import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    assert len(cases) == len({case["id"] for case in cases}) == 31
    assert {case["method"] for case in cases} >= {
        "productionDesktopTransportOffersToNative", "productionDesktopTransportAnswersNative",
        "sharedRuntimeOwnsNativeRecoveryAcrossLifecycle",
        "contactBootstrapUsesIsolatedProcessAndRejectsOrdinaryChat",
        "contactBootstrapUsesNativeDataChannelsAndIsolatedProcess",
    }


def inventory_fixture(directory, suite="webrtc"):
    identity = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    artifacts = {"host.apk": "c" * 64, "tests.apk": "d" * 64}
    inventory = {"v": 1, **identity, "artifacts": artifacts, "run_id": "e" * 32,
                 "scenarios": gate.cases(suite), "started_at": 1}
    (directory / "inventory.json").write_text(json.dumps(inventory))
    for case in gate.cases(suite):
        (directory / case["report"]).write_text(successful_output("e" * 32, case["method"], case["class"]))
    return identity, artifacts, inventory


def test_evidence_counts_actual_execution_and_hashes_each_report(tmp_path):
    identity, artifacts, _ = inventory_fixture(tmp_path)
    result = gate.verify_suite(tmp_path, "webrtc", identity, artifacts)
    assert result["tests_collected"] == result["tests_executed"] == result["tests_passed"] == 21
    assert result["tests_skipped"] == result["tests_failed"] == 0
    assert all(len(case["report_sha256"]) == 64 for case in result["scenarios"])


@pytest.mark.parametrize("fault", ["missing", "skipped", "wrong_process_case", "scope"])
def test_ordinary_android_host_requires_fresh_and_separate_cold_process_cases(tmp_path, fault):
    identity, artifacts, inventory = inventory_fixture(tmp_path, "core_independent")
    result = gate.verify_suite(tmp_path, "core_independent", identity, artifacts)
    assert result["tests_executed"] == 2
    assert all(case["scope"] == gate.INDEPENDENT_SCOPE for case in result["scenarios"])
    case = gate.cases("core_independent")[1]
    report = tmp_path / case["report"]
    if fault == "missing": report.unlink()
    elif fault == "skipped": report.write_text(report.read_text().replace("STATUS_CODE: 0", "STATUS_CODE: -3"))
    elif fault == "wrong_process_case": report.write_text(successful_output("e" * 32, gate.CORE_INDEPENDENT[0], case["class"]))
    else:
        inventory["scenarios"][1]["scope"] = "Successful OS unlock and native peer receipts"
        (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    with pytest.raises((ValueError, FileNotFoundError)):
        gate.verify_suite(tmp_path, "core_independent", identity, artifacts)


@pytest.mark.parametrize("method", gate.PROFILE_RESULT_REGISTRATION)
@pytest.mark.parametrize("fault", ["missing", "not_run", "skipped"])
def test_each_native_result_registration_case_must_execute(tmp_path, method, fault):
    identity, artifacts, _ = inventory_fixture(tmp_path, "core_api")
    result = gate.verify_suite(tmp_path, "core_api", identity, artifacts)
    assert result["tests_executed"] == 13
    registry = [case for case in result["scenarios"] if "NativeProfileResultRegistrationTest" in case["scenario_id"]]
    assert len(registry) == 3 and all(case["scope"] == gate.PROFILE_RESULT_SCOPE for case in registry)
    case = next(case for case in gate.cases("core_api") if case["method"] == method)
    report = tmp_path / case["report"]
    if fault == "missing":
        report.unlink()
    elif fault == "not_run":
        report.write_text("OK (0 tests)\nINSTRUMENTATION_CODE: -1\n")
    else:
        report.write_text(report.read_text().replace("STATUS_CODE: 0", "STATUS_CODE: -3"))
    with pytest.raises((ValueError, FileNotFoundError)):
        gate.verify_suite(tmp_path, "core_api", identity, artifacts)


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


@pytest.mark.parametrize("processes", ["USER PID NAME\nu0 12 com.meshchat.runtime.smoke:mesh_bootstrap",
    "USER PID NAME\nu0 12 com.meshchat.core.hostfixture", "USER PID NAME\nu0 12 com.meshchat.core.consumer.test", ""])
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
    assert set(result) == {"v", "passed", "evidence_level", "failure_type", "phase", "failed_run_reports"}
    assert len(result["failed_run_reports"]["suites"]) == 5


def test_failed_runner_preserves_all_case_failures_and_later_missing_suites(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "REPORTS", tmp_path)
    directory = tmp_path / "android-webrtc"
    directory.mkdir()
    identity, _, inventory = inventory_fixture(directory)
    monkeypatch.setattr(gate, "source", lambda: identity)
    first, second = gate.cases("webrtc")[:2]
    (directory / first["report"]).write_text("RAW private SDP signed document\nFAILURES!!!")
    (directory / second["report"]).unlink()
    assert gate.report(1) == 1
    result = json.loads((tmp_path / "android-qualification.json").read_text())
    assert result["passed"] is False and "RAW" not in json.dumps(result)
    webrtc, *later = result["failed_run_reports"]["suites"]
    assert webrtc["inventory"] == "valid" and webrtc["passed_case_reports"] == 19
    assert webrtc["failed_case_reports"] == webrtc["missing_case_reports"] == 1
    assert {issue["scenario_id"] for issue in webrtc["issues"]} == {first["id"], second["id"]}
    assert all(item["inventory"] == "missing" and item["unvalidated_case_reports"] == item["required_case_reports"] for item in later)
    # Stale inventory never promotes old successful text into passing reports.
    inventory["source_commit"] = "f" * 40
    (directory / "inventory.json").write_text(json.dumps(inventory))
    stale = gate.failed_run_reports(identity)["suites"][0]
    assert stale["inventory"] == "invalid" and stale["passed_case_reports"] == 0


def test_adb_cannot_consume_the_remaining_scenario_inventory(tmp_path):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file(), "The required runner integration test needs Bash"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("test_android_webrtc.sh", "android_qualification.py", "verify_android_independent_consumer.py"):
        (scripts / name).write_text((SCRIPT.parent / name).read_text(), encoding="utf-8", newline="\n")
    for binary in gate.APKS:
        target = tmp_path / binary.relative_to(gate.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"isolated test fixture, not an APK")
    for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                      ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                      ("commit", "-qm", "fixture")):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)
    commands = tmp_path / "commands"
    commands.mkdir()
    # ADB reads stdin even for shell invocations. This fake reproduces that
    # behavior without launching an emulator or touching an installed app.
    adb = commands / "adb"
    adb.write_text('''#!/usr/bin/env bash
cat >/dev/null
for argument in "$@"; do
  if [[ "$argument" == com.meshchat.runtime.*#* ]]; then
    class="${argument%#*}"
    method="${argument#*#}"
    for code in 1 0; do
      printf 'INSTRUMENTATION_STATUS: class=%s\\n' "$class"
      printf 'INSTRUMENTATION_STATUS: test=%s\\n' "$method"
      printf 'INSTRUMENTATION_STATUS: numtests=1\\nINSTRUMENTATION_STATUS_CODE: %s\\n' "$code"
    done
    printf 'OK (1 test)\\nINSTRUMENTATION_CODE: -1\\n'
  fi
done
''', encoding="utf-8", newline="\n")
    timeout = commands / "timeout"
    timeout.write_text('#!/usr/bin/env bash\nwhile [[ "$1" == --* ]]; do shift; done\nshift\nexec "$@"\n',
                       encoding="utf-8", newline="\n")
    adb.chmod(0o755)
    timeout.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if key != "GITHUB_SHA"}
    # Export inside Bash so Git Bash also honors the fixture ahead of Windows tools.
    environment["FIXTURE_COMMANDS"] = commands.as_posix()
    environment["FIXTURE_PYTHON"] = Path(sys.executable).parent.as_posix()
    setup = '''if command -v cygpath >/dev/null; then
FIXTURE_COMMANDS=$(cygpath -u "$FIXTURE_COMMANDS")
FIXTURE_PYTHON=$(cygpath -u "$FIXTURE_PYTHON")
fi
export PATH="$FIXTURE_COMMANDS:$FIXTURE_PYTHON:$PATH"
bash scripts/test_android_webrtc.sh'''
    result = subprocess.run([bash, "-c", setup],
        cwd=tmp_path, env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
    reports = tmp_path / "dist/reports/android-webrtc"
    inventory = json.loads((reports / "inventory.json").read_text())
    evidence = gate.verify_suite(reports, "webrtc", {key: inventory[key] for key in ("source_commit", "source_tree")},
                                 inventory["artifacts"])
    assert evidence["tests_executed"] == 21
