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
    finally:
        staging.cleanup(directory, parent)
    assert not directory.exists()
