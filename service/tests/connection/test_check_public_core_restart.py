"""Aggregate restart evidence binds actual report bytes and all prerequisites."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_public_core_restart as checker
from test_public_core_pair_evidence import CONTEXT, TREE, prerequisites, valid_pair
from test_public_core_restart_evidence import evidence_pair, role_flow


def staged_reports(tmp_path, monkeypatch):
    windows, android, _ = prerequisites()
    paths = {name: tmp_path / (name + ".json") for name in
             ("windows_bootstrap", "android_distribution", "windows_report", "android_report")}
    identities = {}
    for name, value in (("windows_bootstrap", windows), ("android_distribution", android)):
        paths[name].write_text(json.dumps(value), encoding="utf-8")
        _, identities[name] = checker.baseline.read_report(paths[name])
    inputs = checker.baseline.prerequisite_inputs(windows, android, CONTEXT, TREE, identities)
    reports, _, _, _, needs = evidence_pair()
    for role, report in reports.items():
        report.update(context=CONTEXT, source_tree=TREE, inputs=inputs[role],
                      flow=role_flow(role, CONTEXT["pair_id"]))
        paths[role + "_report"].write_text(json.dumps(report), encoding="utf-8")
    environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_JOB": "public_pair_check", "GITHUB_SHA": CONTEXT["source_commit"],
        "GITHUB_REPOSITORY": CONTEXT["repository"], "GITHUB_REPOSITORY_ID": str(CONTEXT["repository_id"]),
        "GITHUB_RUN_ID": str(CONTEXT["run_id"]), "GITHUB_RUN_ATTEMPT": str(CONTEXT["run_attempt"]),
        "PUBLIC_PAIR_NEEDS": json.dumps(needs), "PUBLIC_PAIR_SCENARIO": "owner_restart"}
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(checker.baseline, "source_identity", lambda expected: (CONTEXT["source_commit"], TREE))
    output = tmp_path / "summary.json"
    arguments = ["checker", "--expected-source", CONTEXT["source_commit"]]
    for name, path in paths.items():
        arguments.extend(("--" + name.replace("_", "-"), str(path)))
    monkeypatch.setattr(sys, "argv", arguments + ["--output", str(output)])
    return reports, paths, needs, output


@pytest.mark.parametrize("fault", [None, "changed_bytes", "fresh_report", "missing_job",
    "failed_job", "failed_report", "late_report", "duplicate_needs", "wrong_scenario", "wrong_job"])
def test_cli_requires_restart_reports_with_exact_bytes_and_successful_jobs(tmp_path, monkeypatch, fault, capsys):
    reports, paths, needs, output = staged_reports(tmp_path, monkeypatch)
    report = reports["windows"]
    if fault == "changed_bytes":
        with paths["windows_bootstrap"].open("a", encoding="utf-8") as stream:
            stream.write("\n")
    if fault == "fresh_report":
        report = valid_pair()[0][0]
    if fault == "missing_job":
        del needs["verification"]
    if fault == "failed_job":
        needs["android_public"]["result"] = "failure"
    if fault == "failed_report":
        report.update(passed=False, failure_phase="retirement")
    if fault == "late_report":
        report["duration_seconds"] = 1201
    if fault == "wrong_scenario":
        monkeypatch.setenv("PUBLIC_PAIR_SCENARIO", "fresh")
    if fault == "wrong_job":
        monkeypatch.setenv("GITHUB_JOB", "native_peer_check")
    monkeypatch.setenv("PUBLIC_PAIR_NEEDS", json.dumps(needs) if fault != "duplicate_needs"
                       else '{"verification":{"result":"failure"},"verification":{"result":"success"}}')
    paths["windows_report"].write_text(json.dumps(report), encoding="utf-8")
    assert checker.main() == int(fault is not None)
    result = json.loads(output.read_text())
    assert result["passed"] is (fault is None)
    assert result["evidence_level"] == checker.evidence.LEVEL
    assert result["scope"] == checker.evidence.SCOPE
    if fault is not None:
        assert result["failure_phase"] == ("admission" if fault in {"wrong_scenario", "wrong_job"} else "restart_pair")
    assert str(tmp_path) not in capsys.readouterr().out
