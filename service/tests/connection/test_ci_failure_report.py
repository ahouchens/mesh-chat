"""A rejected qualification must retain evidence without becoming successful."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import connection_ci as ci


@pytest.fixture
def gate(tmp_path):
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    plan = {**ci.select(None, event="workflow_dispatch"), "source_commit": source, "source_tree": tree}
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(plan), encoding="utf-8")
    output = tmp_path / "reports/qualification.json"
    needs = {name: {"result": "success"} for name in ("plan", *ci.SUITES)}

    def run(*, jobs=needs, selected=plan, expected_source=source):
        selection.write_text(json.dumps(selected), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/connection_ci.py"),
             "--check-plan", str(selection), "--evidence-dir", str(tmp_path / "missing-evidence"),
             "--output", str(output)], cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "GITHUB_SHA": expected_source, "GITHUB_EVENT_NAME": "workflow_dispatch",
                 "GITHUB_EVENT_PATH": str(tmp_path / "absent-event.json"),
                 "QUALIFICATION_NEEDS": json.dumps(jobs)}, timeout=30,
        )
        assert completed.returncode != 0
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["passed"] is False
        assert "suites" not in report and "components" not in report
        return report

    return run, needs, plan


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", None, "untrusted-detail"])
def test_failed_native_gate_retains_summary_and_nonzero_exit(gate, status):
    run, needs, plan = gate
    needs["native_interop"]["result"] = status
    report = run()
    assert report["failure_stage"] == "workflow_results"
    assert report["source_commit"] == plan["source_commit"]
    assert report["source_tree"] == plan["source_tree"]
    assert report["jobs"]["native_interop"] == (status if status in {"failure", "cancelled", "skipped"} else "unknown")
    assert "untrusted-detail" not in json.dumps(report)


def test_failure_summary_distinguishes_source_and_selection_rejection(gate):
    run, _, plan = gate
    report = run(expected_source="0" * 40)
    assert report["failure_stage"] == "source"
    assert report["source_commit"] is None and report["source_tree"] is None
    report = run(selected={**plan, "source_commit": "0" * 40})
    assert report["failure_stage"] == "selection"
    assert report["source_commit"] == plan["source_commit"]


def test_failure_summary_does_not_copy_malformed_needs(gate):
    run, _, _ = gate
    report = run(jobs=["untrusted-detail"])
    assert report["failure_stage"] == "workflow_results"
    assert set(report["jobs"].values()) == {"unknown"}
    assert "untrusted-detail" not in json.dumps(report)


def test_successful_workflows_still_require_component_evidence(gate):
    run, _, _ = gate
    report = run()
    assert report["failure_stage"] == "component_evidence"
    assert set(report["jobs"].values()) == {"success"}
