import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import release_qualification as release
from connection_ci import SUITES


SOURCE, TREE, VERSION = "a" * 40, "b" * 40, "1.2.3"


def component(name, *, tests=None, checks=None):
    return {"suite": name, "evidence_level": "component", "source_commit": SOURCE,
            "source_tree": TREE, "tests": tests, "checks": checks,
            "artifacts": {} if not checks else {"native": "c" * 64},
            "cleanup": "not_applicable" if tests else "covered_by_checks",
            "report_sha256": "d" * 64}


def counts(executed=1):
    return {"collected": executed, "executed": executed, "passed": executed,
            "failed": 0, "skipped": 0}


def fixture(tmp_path, required=("policy", "verification")):
    repository = tmp_path / "repo"
    (repository / "contracts/core-api").mkdir(parents=True)
    (repository / "contracts/core-api/operations-v1.json").write_text(json.dumps(
        {"api_major": 1, "api_minor": 0, "status": "experimental_design"}))
    suites = [component("policy", tests=counts(5))]
    suites += [component(name, checks=3) for name in sorted(release.REQUIRED_COMPONENTS["verification"])]
    manifest = {"version": 1, "event": "pull_request", "paths": ["src/x"], "required": list(required),
                "reason": "conservative_full_matrix", "source_commit": SOURCE, "source_tree": TREE,
                "passed": True, "scope": "component qualification",
                "components": {"policy_tests_executed": 5},
                "jobs": {name: ("success" if name in required else "skipped") for name in SUITES},
                "suites": suites}
    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(manifest))
    artifacts = {}
    for kind in ("setup", "msi", "apk"):
        target = tmp_path / release.expected_name(kind, VERSION)
        target.write_bytes(b"release-binary-" + kind.encode())
        artifacts[kind] = target
    return path, artifacts, repository


def aggregate(tmp_path, **changes):
    path, artifacts, repository = fixture(tmp_path)
    arguments = {"qualification_path": path, "artifacts": artifacts, "source": SOURCE,
                 "tree": TREE, "version": VERSION, "repository": repository}
    arguments.update(changes)
    return release.aggregate(**arguments)


def test_exact_artifacts_bind_to_the_qualified_source(tmp_path):
    result = aggregate(tmp_path)
    assert result["passed"] is True and result["release_version"] == VERSION
    assert result["source_commit"] == SOURCE and result["source_tree"] == TREE
    assert set(result["artifacts"]) == {"setup", "msi", "apk"}
    assert all(value["bytes"] > 0 and len(value["sha256"]) == 64
               for value in result["artifacts"].values())
    assert result["api"] == {"major": 1, "minor": 0, "stability": "experimental"}
    assert result["internal_contract"] == 1
    assert result["qualification_sha256"] and len(result["qualification_sha256"]) == 64
    assert "physical acceptance remain unqualified" in result["scope"]


@pytest.mark.parametrize("fault", ["source", "tree", "unpassed", "job", "incomplete_tests", "missing_component"])
def test_qualification_must_cover_the_exact_source_and_required_work(tmp_path, fault):
    path, artifacts, repository = fixture(tmp_path)
    manifest = json.loads(path.read_text())
    if fault == "source":
        manifest["source_commit"] = "f" * 40
    elif fault == "tree":
        manifest["source_tree"] = "f" * 40
    elif fault == "unpassed":
        manifest["passed"] = False
    elif fault == "job":
        manifest["jobs"]["policy"] = "failure"
    elif fault == "incomplete_tests":
        manifest["suites"][0]["tests"]["skipped"] = 1
    else:
        manifest["suites"] = [record for record in manifest["suites"]
                              if record["suite"] != "windows_packaged_pairing"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        release.aggregate(qualification_path=path, artifacts=artifacts, source=SOURCE,
                          tree=TREE, version=VERSION, repository=repository)


@pytest.mark.parametrize("fault", ["missing", "wrong_version", "empty", "incomplete_inventory", "bad_version"])
def test_release_artifacts_must_be_complete_version_bound_files(tmp_path, fault):
    path, artifacts, repository = fixture(tmp_path)
    if fault == "missing":
        artifacts["apk"].unlink()
    elif fault == "wrong_version":
        wrong = artifacts["setup"].with_name(release.expected_name("setup", "9.9.9"))
        artifacts["setup"].rename(wrong)
        artifacts["setup"] = wrong
    elif fault == "empty":
        artifacts["msi"].write_bytes(b"")
    elif fault == "incomplete_inventory":
        del artifacts["msi"]
    with pytest.raises(ValueError):
        release.aggregate(qualification_path=path, artifacts=artifacts, source=SOURCE, tree=TREE,
                          version="1.2" if fault == "bad_version" else VERSION, repository=repository)


def test_unsupported_contract_version_is_rejected(tmp_path):
    path, artifacts, repository = fixture(tmp_path)
    (repository / "contracts/core-api/operations-v1.json").write_text(json.dumps(
        {"api_major": 2, "api_minor": 0, "status": "experimental_design"}))
    with pytest.raises(ValueError):
        release.aggregate(qualification_path=path, artifacts=artifacts, source=SOURCE, tree=TREE,
                          version=VERSION, repository=repository)
