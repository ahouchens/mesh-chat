"""The first-cold diagnostic pair is bounded, source-bound, and never full evidence."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_native_interop_b8_diagnostic as checker
import native_interop_evidence as evidence
from test_ui_core_boundary_interop_controller import interop_reports


SOURCE, TREE = "a" * 40, "b" * 40
LEVEL = "packaged_windows_android_emulator_b8_first_cold_diagnostic_only"


@pytest.fixture
def reports(tmp_path, monkeypatch):
    windows, android = interop_reports(workload="b8_first_cold")
    paths = {role: tmp_path / f"native-interop-b8-first-cold-{role}.json"
             for role in ("windows", "android")}
    for role, record in (("windows", windows), ("android", android)):
        paths[role].write_text(json.dumps(record), encoding="utf-8")
    output = tmp_path / "native-interop-b8-first-cold-pair.json"
    for key, value in {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_JOB": "b8_pair_check", "GITHUB_SHA": SOURCE,
        "GITHUB_REPOSITORY": "example/mesh", "GITHUB_REPOSITORY_ID": "1",
        "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(checker, "source_identity", lambda expected: (SOURCE, TREE))
    monkeypatch.setattr(sys, "argv", ["checker", "--expected-source", SOURCE,
        "--windows-report", str(paths["windows"]), "--android-report", str(paths["android"]),
        "--output", str(output)])
    return paths, output, windows, android


def test_diagnostic_plan_is_distinct_from_required_quick_and_full():
    from native_interop_workload import selected_workload

    plan = evidence.required_workload("b8_first_cold")
    assert plan["level"] == LEVEL and plan["scope"] == checker.SCOPE
    assert tuple(plan["paths"]) == evidence.PATH_CASES
    assert plan["iterations"] == 1 and plan["cold_start_every"] == 10
    assert evidence.required_workload("full")["iterations"] == 100
    assert evidence.required_workload("quick")["iterations"] == 5
    assert selected_workload("workflow_dispatch", None) == "full"
    assert selected_workload("pull_request", ["service/src/mesh_chat/service.py"]) == "quick"


def run(reports):
    paths, output, *_ = reports
    code = checker.main()
    summary = json.loads(output.read_text(encoding="utf-8"))
    return code, summary, paths


def test_success_requires_exact_two_role_pair_and_hashes_bounded_inputs(reports):
    code, summary, paths = run(reports)
    assert code == 0 and summary["passed"] is True
    assert summary["evidence_level"] == LEVEL
    assert summary["source_commit"] == SOURCE and summary["source_tree"] == TREE
    assert summary["context"]["run_id"] == 2 and summary["context"]["run_attempt"] == 1
    assert summary["path_cases"] == [[a, b] for a, b in evidence.PATH_CASES]
    assert summary["receipt_iterations_per_role"] == 1
    for role in ("windows", "android"):
        data = paths[role].read_bytes()
        assert summary["reports"][role] == {"sha256": hashlib.sha256(data).hexdigest(),
                                             "size_bytes": len(data)}
    assert "failure_kind" not in summary


@pytest.mark.parametrize("fault", ["missing", "invalid_json", "failed", "other_attempt", "zero_cycle", "other_receipt"])
def test_incomplete_pair_fails_closed_with_sanitized_summary_and_available_hashes(reports, fault):
    paths, _, _, _ = reports
    target = paths["android"]
    record = json.loads(target.read_text(encoding="utf-8"))
    if fault == "missing":
        target.unlink()
    elif fault == "invalid_json":
        target.write_text("{private malformed report", encoding="utf-8")
    else:
        if fault == "failed": record["passed"] = False
        elif fault == "other_attempt": record["context"]["run_attempt"] = 2
        elif fault == "zero_cycle": record["execution"]["receipt_iterations"] = []
        else: record["execution"]["receipt_iterations"][0]["message"]["inbound"] = "f" * 64
        target.write_text(json.dumps(record), encoding="utf-8")
    code, summary, _ = run(reports)
    assert code == 1 and summary["passed"] is False
    assert summary["failure_kind"] in {"report_invalid", "pair_invalid"}
    assert len(summary["reports"]["windows"]["sha256"]) == 64
    assert (summary["reports"]["android"] is None) is (fault == "missing")
    assert not any(key in summary for key in ("exception", "error", "raw_report", "message"))


@pytest.mark.parametrize("fault", ["not_actions", "not_manual", "wrong_job", "wrong_sha", "source_changed"])
def test_manual_exact_source_admission_fails_closed(reports, monkeypatch, fault):
    if fault == "not_actions": monkeypatch.setenv("GITHUB_ACTIONS", "false")
    elif fault == "not_manual": monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    elif fault == "wrong_job": monkeypatch.setenv("GITHUB_JOB", "gate")
    elif fault == "wrong_sha": monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    else: monkeypatch.setattr(checker, "source_identity", lambda expected: (_ for _ in ()).throw(ValueError()))
    code, summary, _ = run(reports)
    assert code == 1 and summary["passed"] is False
    assert summary["failure_kind"] in {"admission_invalid", "source_invalid"}
    assert len(summary["reports"]["windows"]["sha256"]) == 64


def test_oversized_report_is_rejected_without_hashing_it(reports):
    paths, _, _, _ = reports
    paths["android"].write_bytes(b"x" * (checker.MAX_REPORT_BYTES + 1))
    code, summary, _ = run(reports)
    assert code == 1 and summary["failure_kind"] == "report_invalid"
    assert summary["reports"]["android"] is None


def test_diagnostic_pair_cannot_satisfy_full_or_default_qualification(reports):
    _, _, windows, android = reports
    assert evidence.verify_pair(windows, android, SOURCE, TREE, workload="b8_first_cold")
    for record, role in ((windows, "windows"), (android, "android")):
        with pytest.raises(ValueError):
            evidence.verify_report(record, SOURCE, TREE, role, workload="full")
    with pytest.raises(ValueError):
        evidence.verify_pair(windows, android, SOURCE, TREE)
