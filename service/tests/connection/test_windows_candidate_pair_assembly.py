"""The opt-in Windows route keeps exact staging and current runtime together."""

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import assemble_windows_candidate_pair as assembly


SOURCE = "a" * 40
TREE = "b" * 40


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def staged_inputs(tmp_path, monkeypatch):
    contract = assembly.fixture()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = {}
    for name, filename in assembly.SOURCE_NAMES.items():
        path = inputs / filename
        path.write_bytes((name + " exact bytes").encode())
        paths[name] = path
    old = {"baseline_source": contract.BASELINE["baseline_source"],
           "baseline_tree": contract.BASELINE["baseline_tree"],
           "provenance": contract.BASELINE["provenance"],
           "artifacts": {
               kind: {"filename": paths[name].name, "sha256": _digest(paths[name]),
                      "size_bytes": paths[name].stat().st_size}
               for name, kind in (("old_typescript", "typescript"),
                                  ("old_service", "python_service_carrier"))}}
    _json(paths["old_staging"], old)
    pinned = {"baseline_source": old["baseline_source"],
              "baseline_tree": old["baseline_tree"],
              "provenance": old["provenance"],
              "report_sha256": _digest(paths["old_staging"]),
              "artifacts": old["artifacts"]}
    staged = {"passed": True, "source_commit": SOURCE, "source_tree": TREE,
              "evidence_level": "public_sdk_archive_and_isolated_import_staging",
              "artifacts": {name: {"sha256": _digest(paths[name]),
                                   "size_bytes": paths[name].stat().st_size}
                            for name in ("python", "typescript")},
              "pinned_upgrade": pinned}
    _json(paths["sdk_staging"], staged)
    monkeypatch.setattr(assembly, "SOURCES", paths)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    return contract, paths, staged


def test_exact_manifest_and_provenance_are_assembled_outside_checkout(tmp_path, monkeypatch):
    contract, paths, _ = staged_inputs(tmp_path, monkeypatch)
    output = tmp_path / "candidate"
    report = assembly.assemble(output, SOURCE, TREE, "123", "2", "456", contract=contract)
    manifest, artifacts = contract.validate_manifest(output / "manifest.json", SOURCE, TREE)
    assert paths["sdk_staging"].name == "core-sdk-distribution-staging.json"
    assert artifacts["sdk_staging"].name == "core-sdk-staging.json"
    assert report["passed"] is True
    assert report["run_id"] == "123" and report["run_attempt"] == "2"
    assert report["verification_artifact"] == "core-sdk-verification-" + SOURCE
    assert report["verification_artifact_id"] == "456"
    assert report["pinned_upgrade_report_sha256"] == _digest(paths["old_staging"])
    assert set(artifacts) == set(contract.ARTIFACT_NAMES)
    assert manifest["baseline_native_binary"] is None
    assert artifacts["runtime"].parent == artifacts["runtime_build"].parent


def test_pinned_upgrade_report_hash_must_match_the_staged_crosslink(tmp_path, monkeypatch):
    contract, paths, staged = staged_inputs(tmp_path, monkeypatch)
    staged["pinned_upgrade"]["report_sha256"] = "0" * 64
    _json(paths["sdk_staging"], staged)
    with pytest.raises(ValueError, match="cross-linked"):
        assembly.assemble(tmp_path / "candidate", SOURCE, TREE, "123", "1", "456", contract=contract)
    assert not (tmp_path / "candidate").exists()


def test_changed_old_artifact_is_rejected_before_manifest_write(tmp_path, monkeypatch):
    contract, paths, _ = staged_inputs(tmp_path, monkeypatch)
    paths["old_typescript"].write_bytes(b"different old bytes")
    with pytest.raises(ValueError, match="Pinned upgrade artifact"):
        assembly.assemble(tmp_path / "candidate", SOURCE, TREE, "123", "1", "456", contract=contract)
    assert not (tmp_path / "candidate").exists()


def test_workflow_opt_in_depends_on_same_run_stage_and_retains_separate_report():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    dispatch = workflow.get("on", workflow.get(True))["workflow_dispatch"]
    assert dispatch["inputs"]["windows_candidate_pair"]["default"] is False
    assert workflow["jobs"]["verify"]["outputs"]["candidate_sdk_artifact_id"] == "${{ steps.candidate_sdk_upload.outputs.artifact-id }}"
    job = workflow["jobs"]["desktop-host"]
    assert job["needs"] == "verify"
    assert "!cancelled()" in job["if"]
    assert "always()" not in job["if"]
    assert "inputs.windows_candidate_pair != true" in job["if"]
    assert "needs.verify.result == 'success'" in job["if"]
    steps = job["steps"]
    build = next(i for i, step in enumerate(steps)
                 if step.get("run") == "python scripts/build_sidecar.py")
    download = next(i for i, step in enumerate(steps)
                    if step.get("uses") == "actions/download-artifact@v4")
    assemble = next(i for i, step in enumerate(steps)
                    if "scripts/assemble_windows_candidate_pair.py" in step.get("run", ""))
    execute = next(i for i, step in enumerate(steps)
                   if "tests/core-sdk-upgrade/windows_candidate_pair.py" in step.get("run", ""))
    assert build < download < assemble < execute
    assert steps[download]["with"]["name"] == "core-sdk-verification-${{ github.sha }}"
    assert steps[download]["with"]["path"] == "dist"
    assert "needs.verify.outputs.candidate_sdk_artifact_id" in steps[assemble]["run"]
    assert "steps.candidate_assembly.outcome == 'success'" in steps[execute]["if"]
    upload = next(step for step in steps
                  if step.get("with", {}).get("name", "").startswith("windows-candidate-pair-"))
    assert "always()" in upload["if"]
    assert "dist/reports/windows-candidate-pair-assembly.json" in upload["with"]["path"]
    assert "dist/reports/windows-candidate-pair.json" in upload["with"]["path"]
    assert "dist/reports/windows-candidate-pair-manifest.json" in upload["with"]["path"]


def test_python_owned_consumer_is_opt_in_and_uses_successful_same_run_staging():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["desktop-host"]["steps"]
    download = next(i for i, step in enumerate(steps) if step.get("id") == "candidate_sdk_download")
    execute = next(i for i, step in enumerate(steps)
                   if "scripts/check_python_independent_consumer.py" in step.get("run", ""))
    assert download < execute
    condition = steps[execute]["if"]
    assert "always()" in condition and "inputs.windows_candidate_pair == true" in condition
    assert "needs.verify.result == 'success'" in condition
    assert "steps.candidate_sdk_download.outcome == 'success'" in condition
    assert '--expected-source "${{ github.sha }}"' in steps[execute]["run"]
    upload = next(step for step in steps
                  if step.get("with", {}).get("name", "").startswith("windows-independent-python-"))
    assert "always()" in upload["if"] and "inputs.windows_candidate_pair == true" in upload["if"]
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in upload["with"]["name"]
    assert set(upload["with"]["path"].splitlines()) == {
        "dist/reports/windows-independent-python.json", "dist/reports/windows-independent-python-sdk/**"}


def test_post_assembly_source_failure_cannot_leave_a_passing_report(tmp_path, monkeypatch):
    calls = 0

    def source_identity(_):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Source changed after assembly")
        return SOURCE, TREE

    monkeypatch.setitem(sys.modules, "test_packaged_lifecycle",
                        SimpleNamespace(source_identity=source_identity))
    monkeypatch.setattr(assembly.sys, "platform", "win32")
    monkeypatch.setattr(assembly.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(assembly, "assemble", lambda *args: {
        "v": 1, "passed": True, "manifest_sha256": "c" * 64})
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_JOB": "desktop-host", "GITHUB_SHA": SOURCE,
                       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    report = tmp_path / "windows-candidate-pair-assembly.json"
    monkeypatch.setattr(sys, "argv", ["assemble_windows_candidate_pair.py",
                                  "--expected-source", SOURCE,
                                  "--verification-artifact-id", "456",
                                  "--output-dir", str(tmp_path / "inputs"),
                                  "--report", str(report),
                                  "--retained-manifest", str(tmp_path / "manifest.json")])
    assert assembly.main() == 1
    value = json.loads(report.read_text(encoding="utf-8"))
    assert value["passed"] is False and value["failure_type"] == "ValueError"
    pending = json.loads((tmp_path / "windows-candidate-pair.json").read_text(encoding="utf-8"))
    assert pending["passed"] is False and pending["status"] == "not_run"
