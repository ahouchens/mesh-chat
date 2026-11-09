"""Outside-checkout application staging is component evidence, not SC21 traffic."""

import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import stage_independent_core_consumers as staging
import check_independent_core_consumers as bootstrap


def test_application_owned_runtime_framing_and_retirement_use_real_subprocesses():
    node, _ = staging.tools()
    result = subprocess.run([node, "--test", "--test-reporter=tap",
                             str(staging.ROOT / "tests/core-ui-boundary/app_owned_runtime.test.mjs")],
                            cwd=staging.ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-1000:]
    assert "# tests 11" in result.stdout
    assert "# pass 11" in result.stdout and "# fail 0" in result.stdout and "# skipped 0" in result.stdout


def staged_input(tmp_path):
    directory = tmp_path / "sdk"
    (directory / "typescript").mkdir(parents=True)
    artifact = directory / "typescript" / staging.ARTIFACTS["typescript"]
    artifact.write_bytes(b"component fixture bytes; not a real SDK archive")
    value = {"v": 1, "passed": True, "evidence_level": "public_sdk_archive_and_isolated_import_staging",
             "source_commit": "a" * 40, "source_tree": "b" * 40,
             "artifacts": {"typescript": {"artifact": "typescript/" + artifact.name,
                "sha256": staging.digest(artifact), "size_bytes": artifact.stat().st_size}}}
    report = tmp_path / "sdk-staging.json"
    report.write_text(json.dumps(value))
    return directory, artifact, report, value


def bootstrap_record(source="a" * 40, tree="b" * 40):
    """Synthetic complete declaration for rejection checks; never execution proof."""
    return {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": bootstrap.LEVEL, "scope": bootstrap.SCOPE,
            "checks": dict(bootstrap.CHECKS), "run_id": "6" * 32, "duration_seconds": 1,
            "sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64,
            "sdk_sha256": "a" * 64, "runtime_installed_outside_checkout": True, "cleanup": "passed",
            "sdk_artifact": bootstrap.SDK_ARTIFACT,
            "application": {"installed_outside_checkout": True, "imports_public_package": True,
                "application_files": {name: "c" * 64 for name in staging.FILES}}}


@pytest.mark.parametrize("fault", ["source", "tree", "scope", "component_scope", "failed", "efs",
    "efs_integer", "sdk_hash", "runtime_hash", "inside_checkout", "runtime_inside", "file_missing",
    "file_hash", "cleanup", "single_exit", "run", "duration"])
def test_normal_bootstrap_evidence_cannot_substitute_components_or_unprotected_storage(fault):
    record = bootstrap_record()
    bootstrap.verify_report(record, "a" * 40, "b" * 40)
    if fault == "source": record["source_commit"] = "c" * 40
    elif fault == "tree": record["source_tree"] = "c" * 40
    elif fault == "scope": record["scope"] = "SC21 public peer receipt qualification"
    elif fault == "component_scope": record["evidence_level"] = "windows_named_pipe_and_inprocess_domain"
    elif fault == "failed": record["passed"] = False
    elif fault == "efs": record["checks"]["efs_vault_file"] = False
    elif fault == "efs_integer": record["checks"]["efs_profile_directory"] = 1
    elif fault == "sdk_hash": record["sdk_sha256"] = "missing"
    elif fault == "runtime_hash": record.pop("sidecar_sha256")
    elif fault == "inside_checkout": record["application"]["installed_outside_checkout"] = False
    elif fault == "runtime_inside": record["runtime_installed_outside_checkout"] = False
    elif fault == "file_missing": record["application"]["application_files"].pop("bootstrap-check.mjs")
    elif fault == "file_hash": record["application"]["application_files"]["runtime.mjs"] = "bad"
    elif fault == "cleanup": record["cleanup"] = "pending"
    elif fault == "single_exit": record["checks"]["clean_host_exits"] = 1
    elif fault == "run": record["run_id"] = ""
    else: record["duration_seconds"] = float("nan")
    with pytest.raises(ValueError): bootstrap.verify_report(record, "a" * 40, "b" * 40)


def test_installed_application_does_not_inherit_checkout_import_paths_or_artifact_bearers():
    assert bootstrap.application_environment({"Path": "tools", "SYSTEMROOT": "system",
        "PythonPath": "checkout", "PYTHONHOME": "checkout", "NODE_PATH": "checkout", "NODE_OPTIONS": "checkout-preload",
        "mesh_private_key": "secret", "GITHUB_TOKEN": "secret", "Actions_Runtime_Token": "secret",
        "INPUT_ROLE": "secret"}) == {"Path": "tools", "SYSTEMROOT": "system"}


def test_normal_profile_protection_requires_an_existing_protected_profile_and_vault(tmp_path):
    directory = tmp_path / "mesh-core-runtime/profile-v1"
    directory.mkdir(parents=True)
    # The parent may itself be encrypted on a developer machine; missing Vault
    # storage must fail in either case, without asserting local EFS support.
    with pytest.raises((ValueError, FileNotFoundError)):
        bootstrap.protected_profile(tmp_path)


@pytest.mark.parametrize("fault", ["source", "tree", "bytes", "size", "path", "failed", "component_scope"])
def test_independent_stage_refuses_sdk_source_hash_and_scope_substitution(tmp_path, fault):
    directory, artifact, report, value = staged_input(tmp_path)
    assert staging.sdk_input(directory, report, "a" * 40, "b" * 40) == artifact
    if fault == "source": value["source_commit"] = "c" * 40
    elif fault == "tree": value["source_tree"] = "c" * 40
    elif fault == "bytes": artifact.write_bytes(artifact.read_bytes() + b"changed")
    elif fault == "size": value["artifacts"]["typescript"]["size_bytes"] += 1
    elif fault == "path": value["artifacts"]["typescript"]["artifact"] = "../different.tgz"
    elif fault == "failed": value["passed"] = False
    else: value["evidence_level"] = "simulated_and_in_process"
    report.write_text(json.dumps(value))
    with pytest.raises(ValueError): staging.sdk_input(directory, report, "a" * 40, "b" * 40)


def test_independent_install_cannot_use_checkout_or_delete_unowned_directory(tmp_path):
    with pytest.raises(ValueError, match="outside the checkout"):
        staging.outside_directory(staging.ROOT)
    with pytest.raises(ValueError, match="checkout dependencies"):
        staging.install_typescript(staging.ROOT, Path("missing-sdk"), "missing-node", "missing-npm")
    with pytest.raises(ValueError, match="ownership changed"):
        staging.cleanup(tmp_path, tmp_path.parent)
    assert tmp_path.is_dir()


def test_actual_independent_app_installs_from_sdk_archive_outside_checkout(record_property):
    # Actual SDK bytes are a mandatory staging prerequisite. This exercises
    # installation/import only, with no substitute host or fabricated receipt.
    artifact = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", staging.ROOT / "dist/sdk")) / "typescript" / staging.ARTIFACTS["typescript"]
    assert artifact.is_file(), "Stage the actual public TypeScript SDK first"
    node, npm = staging.tools()
    parent = Path(os.environ.get("MESH_CORE_CONSUMER_TMP") or tempfile.gettempdir())
    directory = staging.outside_directory(parent)
    try:
        report = staging.install_typescript(directory, artifact, node, npm)
        record_property("sdk_sha256", staging.digest(artifact))
        assert report["imports_public_package"] and report["installed_outside_checkout"]
        assert report["installed_sdk_entry"].startswith("node_modules/@mesh-chat/core-client/")
        assert set(report["application_files"]) == set(staging.FILES)
        rejected = subprocess.run([node, "bootstrap-check.mjs"], cwd=directory,
                                  capture_output=True, text=True, timeout=15)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"passed": False, "phase": "arguments", "error_code": "unavailable"}
    finally:
        staging.cleanup(directory, parent)
    assert not directory.exists()
