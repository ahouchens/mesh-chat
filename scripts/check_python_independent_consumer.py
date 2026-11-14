"""Qualify an installed Python SDK against the normal app-owned Windows host."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from check_independent_core_consumers import protected_profile
from stage_core_sdk import ARTIFACTS
from stage_independent_core_consumers import cleanup, outside_directory


ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "examples/python-independent-consumer"
FILES = ("consumer.py", "README.md")
WHEEL = ARTIFACTS["python"]
LEVEL = "windows_installed_python_public_sdk_normal_runtime_bootstrap"
SCOPE = ("Outside-checkout Python application, installed standalone wheel and frozen normal Windows host "
         "with actual DPAPI/EFS; public profile bootstrap and clean owner reopen only; "
         "no pairing, peer messages, receipts, Android, media or SC21 qualification")
CHECKS = {"fresh_without_profile": True, "public_only_capabilities": True,
          "explicit_profile_create_and_key_replay": True, "changed_key_payload_rejected": True,
          "reopen_same_public_identity": True, "clean_host_exits": 2,
          "efs_profile_directory": True, "efs_vault_file": True}
SDK_ARTIFACT = "windows-independent-python-sdk/" + WHEEL
SUCCESS_FIELDS = {"v", "passed", "source_commit", "source_tree", "evidence_level", "scope",
                  "sdk_artifact", "runtime_installed_outside_checkout", "cleanup", "checks",
                  "application_files", "duration_seconds", "run_id", "sidecar_sha256",
                  "build_input_sha256", "build_manifest_sha256", "sdk_sha256",
                  "sdk_staging_report_sha256"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def staged_wheel(directory, report, source, tree):
    if not report.is_file() or not 0 < report.stat().st_size <= 128 * 1024:
        raise ValueError("Exact-source SDK staging report is missing")
    value = json.loads(report.read_text(encoding="utf-8"))
    wheel = directory / "python" / WHEEL
    item = value.get("artifacts", {}).get("python", {})
    distribution = wheel.parent / "distribution-report.json"
    if (value.get("v") != 1 or value.get("passed") is not True
            or value.get("source_commit") != source or value.get("source_tree") != tree
            or value.get("evidence_level") != "public_sdk_archive_and_isolated_import_staging"
            or item.get("artifact") != "python/" + WHEEL
            or not wheel.is_file() or not 0 < wheel.stat().st_size <= 2 * 1024 * 1024
            or item.get("sha256") != digest(wheel) or item.get("size_bytes") != wheel.stat().st_size
            or not distribution.is_file() or not 0 < distribution.stat().st_size <= 128 * 1024
            or item.get("report_sha256") != digest(distribution)):
        raise ValueError("Installed Python wheel differs from exact-source staging")
    from check_python_distribution import verify
    verify(wheel)
    return wheel


def verify_report(record, source, tree):
    if (not isinstance(record, dict) or set(record) != SUCCESS_FIELDS
            or type(record.get("v")) is not int or record["v"] != 1
            or record.get("passed") is not True or record.get("source_commit") != source
            or record.get("source_tree") != tree or record.get("evidence_level") != LEVEL
            or record.get("scope") != SCOPE or record.get("sdk_artifact") != SDK_ARTIFACT
            or record.get("runtime_installed_outside_checkout") is not True
            or record.get("cleanup") != "passed" or record.get("checks") != CHECKS
            or not isinstance(record.get("application_files"), dict)
            or set(record["application_files"]) != set(FILES)
            or type(record.get("duration_seconds")) not in {int, float}
            or not math.isfinite(record["duration_seconds"])
            or not 0 <= record["duration_seconds"] < 600):
        raise ValueError("Installed Python consumer scope or execution is incomplete")
    for field, length in (("run_id", 32), ("sidecar_sha256", 64), ("build_input_sha256", 64),
                          ("build_manifest_sha256", 64), ("sdk_sha256", 64),
                          ("sdk_staging_report_sha256", 64)):
        if not isinstance(record.get(field), str) or re.fullmatch(r"[a-f0-9]{" + str(length) + r"}", record[field]) is None:
            raise ValueError("Installed Python consumer provenance is incomplete")
    if any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
           for value in record["application_files"].values()):
        raise ValueError("Installed Python application source hashes are invalid")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--sdk-directory", type=Path, default=ROOT / "dist/sdk")
    parser.add_argument("--sdk-report", type=Path, default=ROOT / "dist/reports/core-sdk-distribution-staging.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/windows-independent-python.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE}
    parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    directory = None
    phase = "source_artifact_binding"
    started = time.monotonic()
    try:
        from native_windows_evidence import artifact_binding, require_unchanged
        binary, binding = artifact_binding(args.expected_source)
        wheel = staged_wheel(args.sdk_directory, args.sdk_report,
                             binding["source_commit"], binding["source_tree"])
        wheel_hash, staging_hash = digest(wheel), digest(args.sdk_report)
        directory = outside_directory(parent)
        phase = "outside_checkout_installation"
        site = directory / "site"
        environment = {name: value for name, value in os.environ.items()
                       if not name.upper().startswith(("MESH_", "GITHUB_", "ACTIONS_", "INPUT_"))
                       and name.upper() not in {"PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"}}
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                           PIP_CACHE_DIR=str(directory / "pip-cache"), PIP_DISABLE_PIP_VERSION_CHECK="1")
        subprocess.run([sys.executable, "-m", "pip", "install", str(wheel.resolve()),
                        "--target", str(site), "--no-deps", "--no-index", "--no-compile"],
                       cwd=directory, env=environment, capture_output=True, check=True, timeout=90)
        files = {}
        for name in FILES:
            source = APPLICATION / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Independent Python application source is invalid")
            shutil.copyfile(source, directory / name)
            files[name] = digest(source)
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if digest(runtime) != binding["sidecar_sha256"]:
            raise ValueError("Installed normal host differs from source-bound binary")
        phase = "normal_python_application_bootstrap"
        completed = subprocess.run([sys.executable, "-I", "-S", "-B", "consumer.py",
                                    "--runtime", str(runtime), "--data-directory", str(directory / "app-data"),
                                    "--site", str(site)], cwd=directory, env=environment,
                                   capture_output=True, timeout=150)
        if len(completed.stdout) > 4096:
            raise ValueError("Installed Python application exceeded its report budget")
        observed = json.loads(completed.stdout)
        if completed.returncode != 0:
            if (isinstance(observed, dict) and observed.get("passed") is False
                    and observed.get("phase") in {"arguments", "runtime_start", "capabilities", "fresh_state",
                       "profile_create", "key_replay", "changed_payload", "observations", "retirement"}
                    and isinstance(observed.get("error_code"), str)
                    and re.fullmatch(r"[a-z_]{1,64}", observed["error_code"])):
                result.update(application_phase=observed["phase"], error_code=observed["error_code"])
            raise ValueError("Installed Python application bootstrap failed")
        checks = {**observed, **protected_profile(directory / "app-data")}
        if checks != CHECKS or any(type(checks[name]) is not type(expected) for name, expected in CHECKS.items()):
            raise ValueError("Python application omitted a required normal-host check")
        phase = "final_artifact_binding"
        require_unchanged(binary, binding)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(wheel) != wheel_hash
                or digest(args.sdk_report) != staging_hash
                or any(digest(directory / name) != expected for name, expected in files.items())):
            raise ValueError("Python application or platform inputs changed during execution")
        retained = args.output.parent / SDK_ARTIFACT
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wheel, retained)
        if digest(retained) != wheel_hash:
            raise ValueError("Retained Python wheel differs from the installed SDK")
        result.update(passed=True, **binding, run_id=uuid4().hex,
                      sdk_sha256=wheel_hash, sdk_staging_report_sha256=staging_hash,
                      sdk_artifact=SDK_ARTIFACT, application_files=files,
                      runtime_installed_outside_checkout=True, checks=checks)
    except Exception as error:
        result.update(passed=False, phase=phase, failure_type=type(error).__name__)
    finally:
        if directory is not None:
            try:
                cleanup(directory, parent)
            except (OSError, ValueError):
                result.update(passed=False, cleanup_failed=True)
        result["duration_seconds"] = time.monotonic() - started
    if result["passed"]:
        result["cleanup"] = "passed"
        try:
            verify_report(result, binding["source_commit"], binding["source_tree"])
        except ValueError:
            result.update(passed=False, phase="evidence_validation", failure_type="ValueError")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "evidence_level": LEVEL}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
