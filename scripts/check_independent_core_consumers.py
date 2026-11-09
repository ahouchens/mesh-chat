"""Normal installed Windows SDK/runtime bootstrap; no pairing or SC21 claim."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

from stage_independent_core_consumers import ROOT, FILES, cleanup, digest, install_typescript, outside_directory
from stage_core_sdk import ARTIFACTS, tools

LEVEL = "windows_installed_public_sdk_normal_runtime_bootstrap"
SCOPE = "Outside-checkout TypeScript application and frozen normal Windows host with actual DPAPI/EFS; no pairing, peer receipts, Android, media or SC21 qualification"
CHECKS = {"fresh_without_profile": True, "public_only_capabilities": True,
          "explicit_profile_create_and_key_replay": True, "changed_key_payload_rejected": True,
          "reopen_same_public_identity": True, "clean_host_exits": 2,
          "efs_profile_directory": True, "efs_vault_file": True}
SDK_ARTIFACT = "windows-independent-sdk/" + ARTIFACTS["typescript"]


def protected_profile(directory):
    profile = directory / "mesh-core-runtime/profile-v1"
    for path in (profile, profile / "mesh-chat.vault"):
        if path.is_symlink() or not getattr(path.stat(), "st_file_attributes", 0) & 0x4000:
            raise ValueError("Normal installed runtime did not establish EFS protection")
    return {"efs_profile_directory": True, "efs_vault_file": True}


def application_environment(environment):
    return {key: value for key, value in environment.items()
            if not key.upper().startswith(("MESH_", "GITHUB_", "ACTIONS_", "INPUT_"))
            and key.upper() not in {"PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"}}


def verify_binding(record, source, tree):
    if (type(record.get("v")) is not int or record["v"] != 1 or record.get("passed") is not True
            or record.get("source_commit") != source or record.get("source_tree") != tree
            or record.get("sdk_artifact") != SDK_ARTIFACT):
        raise ValueError("Installed Windows consumer evidence has the wrong source or outcome")
    import re
    for key in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "sdk_sha256"):
        if not isinstance(record.get(key), str) or re.fullmatch(r"[a-f0-9]{64}", record[key]) is None:
            raise ValueError("Installed consumer artifact binding is incomplete")
    app = record.get("application", {})
    if (app.get("installed_outside_checkout") is not True or app.get("imports_public_package") is not True
            or set(app.get("application_files", {})) != set(FILES)
            or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
                   for value in app["application_files"].values())
            or record.get("runtime_installed_outside_checkout") is not True
            or record.get("cleanup") != "passed"):
        raise ValueError("Independent application installation or cleanup is incomplete")
    if (not isinstance(record.get("run_id"), str) or re.fullmatch(r"[a-f0-9]{32}", record["run_id"]) is None
            or type(record.get("duration_seconds")) not in {int, float}
            or not 0 <= record["duration_seconds"] < 600):
        raise ValueError("Independent application run identity or duration is invalid")
    return record


def verify_report(record, source, tree):
    verify_binding(record, source, tree)
    if (record.get("evidence_level") != LEVEL or record.get("scope") != SCOPE
            or record.get("checks") != CHECKS or any(type(record["checks"].get(key)) is not type(value)
                                                   for key, value in CHECKS.items())):
        raise ValueError("Installed Windows consumer scope or execution is incomplete")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/windows-independent-bootstrap.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE}
    directory = None
    parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    phase = "source_artifact_binding"
    started = time.monotonic()
    try:
        from native_windows_evidence import artifact_binding, require_unchanged
        binary, binding = artifact_binding(args.expected_source)
        node, npm = tools()
        directory = outside_directory(parent)
        phase = "outside_checkout_installation"
        distribution = directory / "sdk"
        environment = {**os.environ, "MESH_NODE": node, "MESH_NPM_CLI": npm}
        for command in ([node, str(ROOT / "node_modules/typescript/bin/tsc"), "-p", str(ROOT / "sdk/typescript")],
                        [node, str(ROOT / "scripts/check_typescript_distribution.mjs"), "--output-dir", str(distribution)]):
            subprocess.run(command, cwd=ROOT, env=environment, check=True, capture_output=True, timeout=180)
        sdk = distribution / ARTIFACTS["typescript"]
        sdk_hash = digest(sdk)
        installed = install_typescript(directory, sdk, node, npm)
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if digest(runtime) != binding["sidecar_sha256"]:
            raise ValueError("Installed runtime differs from source-bound artifact")
        phase = "normal_application_bootstrap"
        data = directory / "app-data"
        completed = subprocess.run([node, "bootstrap-check.mjs", "--runtime", str(runtime),
                                    "--data-directory", str(data)], cwd=directory,
                                   env=application_environment(os.environ), capture_output=True, timeout=150)
        if len(completed.stdout) > 4096:
            raise ValueError("Normal independent application bootstrap failed")
        observed = json.loads(completed.stdout)
        if completed.returncode != 0:
            import re
            if (isinstance(observed, dict) and observed.get("passed") is False
                    and observed.get("phase") in {"arguments", "runtime_start", "capabilities", "fresh_state", "profile_create",
                        "key_replay", "changed_payload", "observations", "retirement"}
                    and isinstance(observed.get("error_code"), str)
                    and re.fullmatch(r"[a-z_]{1,64}", observed["error_code"])):
                result.update(application_phase=observed["phase"], error_code=observed["error_code"])
            raise ValueError("Normal independent application bootstrap failed")
        checks = {**observed, **protected_profile(data)}
        if checks != CHECKS or any(type(checks.get(key)) is not type(value) for key, value in CHECKS.items()):
            raise ValueError("Independent application omitted a required check")
        phase = "final_artifact_binding"
        require_unchanged(binary, binding)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or any(digest(directory / name) != value for name, value in installed["application_files"].items())):
            raise ValueError("Installed runtime changed during execution")
        retained_sdk = args.output.parent / SDK_ARTIFACT
        retained_sdk.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sdk, retained_sdk)
        if digest(retained_sdk) != sdk_hash:
            raise ValueError("Retained SDK differs from the installed artifact")
        result.update(passed=True, **binding, run_id=uuid4().hex, checks=checks,
                      application=installed, sdk_sha256=sdk_hash, sdk_artifact=SDK_ARTIFACT,
                      runtime_installed_outside_checkout=True)
    except Exception as error:
        result.update(passed=False, phase=phase, failure_type=type(error).__name__)
    finally:
        if directory is not None:
            try:
                cleanup(directory, parent)
            except (OSError, ValueError):
                result.update(passed=False, cleanup_failed=True)
        result.update(duration_seconds=time.monotonic() - started)
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
