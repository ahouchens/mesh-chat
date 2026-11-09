"""Required installed-consumer collection cannot run against stale SDK archives."""

import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import stage_core_sdk as staging


@pytest.fixture
def candidates(tmp_path):
    for language, name in staging.ARTIFACTS.items():
        directory = tmp_path / language
        directory.mkdir()
        artifact = directory / name
        artifact.write_bytes(language.encode())
        consumer = {"installed_outside_checkout": True}
        if language == "python":
            consumer.update(version="0.3.0.dev0", private_runtime_imported=False)
        else:
            consumer["imports_public_package"] = True
        report = {"artifact": name, "artifact_path": str(artifact.resolve()), "sha256": staging.sha256(artifact),
                  "version": "0.3.0-experimental", "consumer": consumer}
        (directory / "distribution-report.json").write_text(json.dumps(report))
    return tmp_path


def test_both_candidate_hashes_and_reports_are_retained_for_real_host_consumers(candidates):
    value = staging.verify_artifacts(candidates, "a" * 40, "b" * 40, "v24.0.0")
    assert value["passed"] and value["source_commit"] == "a" * 40
    assert set(value["artifacts"]) == {"python", "typescript"}
    assert all(len(record["sha256"]) == len(record["report_sha256"]) == 64 for record in value["artifacts"].values())
    assert "real host execution" in value["scope"]


@pytest.mark.parametrize("language", ["python", "typescript"])
@pytest.mark.parametrize("fault", ["missing_artifact", "changed_bytes", "missing_report", "outside_path", "wrong_name", "inside_checkout", "wrong_import", "wrong_version"])
def test_incomplete_or_mismatched_staging_cannot_admit_installed_consumers(candidates, language, fault):
    artifact = candidates / language / staging.ARTIFACTS[language]
    path = candidates / language / "distribution-report.json"
    record = json.loads(path.read_text())
    if fault == "missing_artifact": artifact.unlink()
    elif fault == "changed_bytes": artifact.write_bytes(b"altered after smoke")
    elif fault == "missing_report": path.unlink()
    else:
        if fault == "outside_path": record["artifact_path"] = str(candidates / artifact.name)
        elif fault == "wrong_name": record["artifact"] = "other.tgz"
        elif fault == "inside_checkout": record["consumer"]["installed_outside_checkout"] = False
        elif fault == "wrong_import":
            record["consumer"]["private_runtime_imported" if language == "python" else "imports_public_package"] = language == "python"
        elif language == "python": record["consumer"]["version"] = "0.2.0"
        else: record["version"] = "0.2.0"
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        staging.verify_artifacts(candidates, "a" * 40, "b" * 40, "v24.0.0")


@pytest.mark.parametrize("workflow,job,collection", [("connection-runtime.yml", "policy", "Deterministic ownership and private adapter regressions"),
                                                    ("ci.yml", "verify", "Validate and test")])
def test_each_broad_collector_stages_once_with_pinned_node_and_retains_candidates(workflow, job, collection):
    value = yaml.safe_load((staging.ROOT / ".github/workflows" / workflow).read_text())
    steps = value["jobs"][job]["steps"]
    stages = [index for index, step in enumerate(steps) if "scripts/stage_core_sdk.py" in step.get("run", "")]
    assert len(stages) == 1
    assert stages[0] < next(index for index, step in enumerate(steps) if step.get("name") == collection)
    assert any(step.get("with", {}).get("runtime") == "node@24" for step in steps[:stages[0]])
    assert any(step.get("run") == "pnpm install --frozen-lockfile" for step in steps[:stages[0]])
    assert any("dist/sdk/**" in step.get("with", {}).get("path", "") and step.get("if") == "always()" for step in steps)


def test_staging_uses_selected_node_npm_and_explicit_matching_output_roots(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(staging.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    staging.stage(tmp_path, "selected-node", "selected-npm.js")
    assert len(calls) == 3
    assert calls[0][0][0][0] == calls[2][0][0][0] == "selected-node"
    assert calls[1][0][0][-1] == str(tmp_path / "python")
    assert calls[2][0][0][-1] == str(tmp_path / "typescript")
    assert all(kwargs["env"]["MESH_NPM_CLI"] == "selected-npm.js" and kwargs["check"] for _, kwargs in calls)


def test_failed_build_stops_before_stale_artifact_reports_can_be_used(tmp_path, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise staging.subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(staging.subprocess, "run", fail)
    with pytest.raises(staging.subprocess.CalledProcessError):
        staging.stage(tmp_path, "selected-node", "selected-npm.js")
    assert len(calls) == 1
