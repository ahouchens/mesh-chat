"""Assemble a same-run, exact-source Windows candidate fixture outside checkout."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "dist/reports/core-sdk-distribution-staging.json"
SOURCES = {
    "runtime": ROOT / "src-tauri/binaries/mesh-chat-service-x86_64-pc-windows-msvc.exe",
    "runtime_build": ROOT / "src-tauri/binaries/.mesh-chat-service-x86_64-pc-windows-msvc.build.json",
    "python": ROOT / "dist/sdk/python/mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl",
    "typescript": ROOT / "dist/sdk/typescript/mesh-chat-core-client-0.3.0-experimental.tgz",
    "old_typescript": ROOT / "dist/sdk-upgrade/mesh-chat-core-client-0.2.0-experimental.tgz",
    "old_service": ROOT / "dist/sdk-upgrade/mesh_chat_service-0.9.66-py3-none-any.whl",
    "sdk_staging": STAGING,
    "old_staging": ROOT / "dist/sdk-upgrade/upgrade-artifacts.json",
}
LEVEL = "windows_candidate_pair_input_assembly_only"


def fixture():
    spec = importlib.util.spec_from_file_location(
        "windows_candidate_pair", ROOT / "tests/core-sdk-upgrade/windows_candidate_pair.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_report(path, limit=128 * 1024):
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= limit:
        raise ValueError("Required staged report is missing or exceeds its bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("Staged report shape is invalid")
    return value


def checked_artifact(path, name, contract):
    if (path.name != contract.ARTIFACT_NAMES[name] or not path.is_file() or path.is_symlink()
            or not 0 < path.stat().st_size <= contract.MAX_BYTES[name]):
        raise ValueError("Required candidate artifact is missing or exceeds its bound")
    return {"sha256": digest(path), "size_bytes": path.stat().st_size}


def verify_staging(source, tree, records, contract):
    staged = read_report(SOURCES["sdk_staging"])
    older = read_report(SOURCES["old_staging"])
    pinned = staged.get("pinned_upgrade")
    if (staged.get("passed") is not True or staged.get("source_commit") != source
            or staged.get("source_tree") != tree
            or staged.get("evidence_level") != "public_sdk_archive_and_isolated_import_staging"
            or type(staged.get("artifacts")) is not dict or type(pinned) is not dict):
        raise ValueError("Candidate SDK staging is not bound to current source")
    for name in ("python", "typescript"):
        item = staged["artifacts"].get(name)
        if (type(item) is not dict or item.get("sha256") != records[name]["sha256"]
                or item.get("size_bytes") != records[name]["size_bytes"]):
            raise ValueError("Current SDK differs from staged artifact")
    if (pinned.get("baseline_source") != contract.BASELINE["baseline_source"]
            or pinned.get("baseline_tree") != contract.BASELINE["baseline_tree"]
            or pinned.get("provenance") != contract.BASELINE["provenance"]
            or pinned.get("report_sha256") != records["old_staging"]["sha256"]
            or older.get("baseline_source") != pinned["baseline_source"]
            or older.get("baseline_tree") != pinned["baseline_tree"]
            or older.get("provenance") != pinned["provenance"]
            or type(pinned.get("artifacts")) is not dict
            or type(older.get("artifacts")) is not dict):
        raise ValueError("Pinned upgrade report is not cross-linked to staging")
    for name, kind in (("old_typescript", "typescript"), ("old_service", "python_service_carrier")):
        item, old_item = pinned["artifacts"].get(kind), older["artifacts"].get(kind)
        if (type(item) is not dict or type(old_item) is not dict
                or item.get("filename") != contract.ARTIFACT_NAMES[name]
                or old_item.get("filename") != item["filename"]
                or any(value.get(field) != records[name][field]
                       for value in (item, old_item) for field in ("sha256", "size_bytes"))):
            raise ValueError("Pinned upgrade artifact differs from exact report")
    return records["sdk_staging"]["sha256"]


def assemble(output, source, tree, run_id, run_attempt, artifact_id, *, contract=None):
    contract = contract or fixture()
    if (not re.fullmatch(r"[a-f0-9]{40}", source)
            or not re.fullmatch(r"[a-f0-9]{40}", tree)
            or not re.fullmatch(r"[1-9][0-9]*", run_id)
            or not re.fullmatch(r"[1-9][0-9]*", run_attempt)
            or not re.fullmatch(r"[1-9][0-9]*", artifact_id)):
        raise ValueError("Candidate source or run identity is invalid")
    output = Path(output).resolve()
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if output.parent != runner_temp or output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Candidate input directory must be fresh under runner temp")
    records = {name: checked_artifact(path, name, contract) for name, path in SOURCES.items()}
    staging_sha = verify_staging(source, tree, records, contract)
    output.mkdir()
    artifacts = output / "artifacts"
    artifacts.mkdir()
    manifest_artifacts = {}
    for name, path in SOURCES.items():
        target = artifacts / contract.ARTIFACT_NAMES[name]
        shutil.copyfile(path, target)
        if checked_artifact(target, name, contract) != records[name]:
            raise ValueError("Candidate artifact changed during assembly")
        manifest_artifacts[name] = {"path": "artifacts/" + target.name, **records[name]}
    manifest = {"v": 1, "source_commit": source, "source_tree": tree,
                "baseline_source": contract.BASELINE["baseline_source"],
                "baseline_tree": contract.BASELINE["baseline_tree"],
                "versions": contract.VERSION_FIELDS,
                "platform": {"os": "Windows", "architecture": "AMD64"},
                "permissions": {"app_owned_normal_host": True, "dpapi_key": True, "efs_profile": True},
                "artifacts": manifest_artifacts, "baseline_native_binary": None}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    contract.validate_manifest(path, source, tree)
    return {"v": 1, "passed": True, "evidence_level": LEVEL,
            "source_commit": source, "source_tree": tree,
            "run_id": run_id, "run_attempt": run_attempt,
            "verification_artifact": "core-sdk-verification-" + source,
            "verification_artifact_id": artifact_id,
            "manifest_sha256": digest(path), "sdk_staging_sha256": staging_sha,
            "pinned_upgrade_report_sha256": records["old_staging"]["sha256"],
            "artifacts": records, "scope": "Input assembly only; installed candidate execution is separate"}


def write_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise ValueError("Candidate assembly report exceeds its bound")
    path.write_text(encoded, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--verification-artifact-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--retained-manifest", type=Path, required=True)
    args = parser.parse_args()
    candidate_report = args.report.with_name("windows-candidate-pair.json")
    write_report(candidate_report, {"v": 1, "passed": False, "status": "not_run",
                                    "reason": "candidate_assembly_incomplete"})
    report = {"v": 1, "passed": False, "evidence_level": LEVEL}
    try:
        if (sys.platform != "win32" or platform.machine() != "AMD64"
                or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("GITHUB_JOB") != "desktop-host"
                or os.environ.get("GITHUB_SHA") != args.expected_source):
            raise RuntimeError("Manual same-run Windows desktop host is required")
        sys.path.insert(0, str(ROOT / "scripts"))
        from test_packaged_lifecycle import source_identity
        source, tree = source_identity(args.expected_source)
        report = assemble(args.output_dir, source, tree, os.environ["GITHUB_RUN_ID"],
                          os.environ["GITHUB_RUN_ATTEMPT"], args.verification_artifact_id)
        if source_identity(source) != (source, tree):
            raise ValueError("Candidate source changed during assembly")
        args.retained_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output_dir / "manifest.json", args.retained_manifest)
        if digest(args.retained_manifest) != report["manifest_sha256"]:
            raise ValueError("Retained candidate manifest differs from execution manifest")
        write_report(candidate_report, {"v": 1, "passed": False, "status": "not_run",
                                        "reason": "candidate_execution_pending",
                                        "manifest_sha256": report["manifest_sha256"]})
    except Exception as error:
        report.update(passed=False, failure_type=type(error).__name__)
    write_report(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != "artifacts"}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
