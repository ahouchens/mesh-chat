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
    assert any("dist/sdk-upgrade/**" in step.get("with", {}).get("path", "") for step in steps)
    assert any(step.get("uses", "").startswith("actions/checkout@") and step.get("with", {}).get("fetch-depth") == 0 for step in steps[:stages[0]])


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


@pytest.fixture
def upgrades(tmp_path):
    artifacts = {}
    for kind, name in staging.UPGRADE_FILES.items():
        path = tmp_path / name
        path.write_bytes(kind.encode())
        artifacts[kind] = {"filename": name, "size_bytes": path.stat().st_size, "sha256": staging.sha256(path)}
    value = {"v": 1, "baseline_source": staging.BASELINE, "baseline_tree": staging.BASELINE_TREE,
             "provenance": "Component artifacts rebuilt from exact Git source; not retained platform binaries", "artifacts": artifacts}
    (tmp_path / "upgrade-artifacts.json").write_text(json.dumps(value))
    return tmp_path


def test_pinned_upgrade_binding_keeps_exact_source_and_actual_rebuilt_hashes(upgrades):
    value = staging.verify_upgrade(upgrades)
    assert value["baseline_source"] == "174728edad62aae6ef16e95b075183d06c5cdda3"
    assert value["baseline_tree"] == "239d041f87b26f50879008ac947481464dcf4551"
    assert "not retained platform binaries" in value["provenance"]
    assert set(value["artifacts"]) == {"python_service_carrier", "typescript"}


@pytest.mark.parametrize("fault", ["source", "tree", "native_claim", "inventory", "path", "size", "hash", "missing", "changed"])
def test_upgrade_staging_rejects_wrong_baseline_partial_archive_or_native_claim(upgrades, fault):
    path = upgrades / "upgrade-artifacts.json"
    value = json.loads(path.read_text())
    artifact = upgrades / staging.UPGRADE_FILES["typescript"]
    if fault == "source": value["baseline_source"] = "b" * 40
    elif fault == "tree": value["baseline_tree"] = "b" * 40
    elif fault == "native_claim": value["provenance"] = "retained packaged Windows qualification"
    elif fault == "inventory": value["artifacts"].pop("typescript")
    elif fault == "path": value["artifacts"]["typescript"]["filename"] = "../other.tgz"
    elif fault == "size": value["artifacts"]["typescript"]["size_bytes"] += 1
    elif fault == "hash": value["artifacts"]["typescript"]["sha256"] = "b" * 64
    elif fault == "missing": artifact.unlink()
    else: artifact.write_bytes(b"different rebuilt bytes")
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError): staging.verify_upgrade(upgrades)


def test_missing_exact_baseline_never_builds_current_source_as_a_substitute(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(staging.subprocess, "check_output", lambda *args, **kwargs: "b" * 40)
    monkeypatch.setattr(staging.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="baseline tree"):
        staging.stage_upgrade(tmp_path, "selected-node", "selected-npm.js")
    assert calls == []
