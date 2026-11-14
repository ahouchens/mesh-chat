"""Admission tests for the exact-artifact Windows candidate pair fixture."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).resolve().parents[3] / "tests/core-sdk-upgrade"
sys.path.insert(0, str(FIXTURE))
import windows_candidate_pair as candidate


def staged_manifest(tmp_path):
    source, tree = "a" * 40, "b" * 40
    files = {}
    for name, filename in candidate.ARTIFACT_NAMES.items():
        parent = "runtime" if name == "runtime_build" else name
        path = tmp_path / parent / filename
        path.parent.mkdir(exist_ok=True)
        if name not in {"sdk_staging", "old_staging"}:
            path.write_bytes((name + " exact fixture bytes").encode())
        files[name] = path
    def sha(name):
        return hashlib.sha256(files[name].read_bytes()).hexdigest()
    files["sdk_staging"].write_text(json.dumps({
        "passed": True, "source_commit": source, "source_tree": tree,
        "evidence_level": "public_sdk_archive_and_isolated_import_staging",
        "artifacts": {"python": {"sha256": sha("python")},
                      "typescript": {"sha256": sha("typescript")}},
    }))
    files["old_staging"].write_text(json.dumps({
        "baseline_source": candidate.BASELINE["baseline_source"],
        "baseline_tree": candidate.BASELINE["baseline_tree"],
        "provenance": candidate.BASELINE["provenance"],
        "artifacts": {"typescript": {"sha256": sha("old_typescript")},
                      "python_service_carrier": {"sha256": sha("old_service")}},
    }))
    manifest = {
        "v": 1, "source_commit": source, "source_tree": tree,
        "baseline_source": candidate.BASELINE["baseline_source"],
        "baseline_tree": candidate.BASELINE["baseline_tree"],
        "versions": dict(candidate.VERSION_FIELDS),
        "platform": {"os": "Windows", "architecture": "AMD64"},
        "permissions": {"app_owned_normal_host": True, "dpapi_key": True, "efs_profile": True},
        "baseline_native_binary": None,
        "artifacts": {name: {"path": path.relative_to(tmp_path).as_posix(),
                              "sha256": sha(name), "size_bytes": path.stat().st_size}
                      for name, path in files.items()},
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    return path, manifest, source, tree


def test_exact_candidate_and_baseline_artifact_manifest_is_admitted(tmp_path):
    path, value, source, tree = staged_manifest(tmp_path)
    accepted, files = candidate.validate_manifest(path, source, tree)
    assert accepted == value and set(files) == set(candidate.ARTIFACT_NAMES)
    assert all(file.is_file() for file in files.values())


@pytest.mark.parametrize("change", [
    lambda value: value.update(source_tree="wrong"),
    lambda value: value["versions"].update(public_api_minor=0),
    lambda value: value["versions"].update(public_api_major=True),
    lambda value: value["permissions"].update(efs_profile=False),
    lambda value: value["permissions"].update(dpapi_key=1),
    lambda value: value.update(baseline_native_binary="unverified-old.exe"),
    lambda value: value["artifacts"]["runtime"].update(sha256="0" * 64),
    lambda value: value["artifacts"]["old_typescript"].update(path="../old.tgz"),
])
def test_wrong_source_version_permission_native_upgrade_or_bytes_cannot_enter_pair(tmp_path, change):
    path, value, source, tree = staged_manifest(tmp_path)
    change(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        candidate.validate_manifest(path, source, tree)


def test_rebuilt_old_artifact_change_is_rejected_even_with_new_manifest_hash(tmp_path):
    path, value, source, tree = staged_manifest(tmp_path)
    old = tmp_path / value["artifacts"]["old_service"]["path"]
    old.write_bytes(b"changed baseline bytes")
    value["artifacts"]["old_service"].update(
        sha256=hashlib.sha256(old.read_bytes()).hexdigest(), size_bytes=old.stat().st_size)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Pinned component"):
        candidate.validate_manifest(path, source, tree)


def test_candidate_scripts_parse_as_node_modules_without_source_aliases():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to parse the embedded consumer scripts")
    for name, source in (("driver.mjs", candidate.DRIVER), ("old_client.mjs", candidate.OLD_TYPESCRIPT)):
        result = subprocess.run([node, "--input-type=module", "--check"], input=source,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, name + ": " + result.stderr
        assert "service/src" not in source and "sdk/typescript/src" not in source
