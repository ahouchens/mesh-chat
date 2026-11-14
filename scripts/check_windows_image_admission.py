"""Installed Windows public-SDK image-path admission diagnostic only."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from uuid import uuid4

import check_independent_core_consumers as bootstrap
from check_windows_separate_process_consumer import FixtureExecutionFailure, run_fixture
from native_windows_evidence import require_unchanged
from stage_core_sdk import tools
from stage_independent_core_consumers import ROOT, cleanup, digest, install_typescript, outside_directory
from windows_public_consumer_session import verified_inputs


REPORT = ROOT / "dist/reports/windows-independent-image-admission.json"
LEVEL = "windows_installed_public_sdk_distinct_image_path_admission"
SCOPE = ("Outside-checkout Windows TypeScript public SDK and one ordinary frozen owner; "
         "same-byte Node executable at a different absolute image path is denied before Core reply, "
         "original image remains admitted and owner survives; no same-image cross-application, "
         "pairing, media or full SC22/R7 acceptance")
FIXTURE_SCOPE = ("Installed public SDK Windows image-path admission on one ordinary frozen owner; "
                 "no same-image cross-application, pairing, media or full R7 acceptance")
FIXTURE_CHECKS = {"original_image_positive": True, "copied_image_preflight": True,
                  "copied_image_denied_before_reply": True, "original_owner_survived": True,
                  "fresh_allowed_helper": True, "exact_child_exits": True,
                  "frozen_host_retired": True, "inputs_unchanged": True}
CHECKS = {**FIXTURE_CHECKS, "efs_profile_directory": True, "efs_vault_file": True}
MAX_STDOUT = 4096
FIXTURE_SECONDS = 120
TOTAL_SECONDS = 600
FIXTURE_FAILURE_PHASES = frozenset({"arguments", "owner_start", "positive_control",
    "copy_preflight", "wrong_image", "owner_survives", "artifact_binding"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("fixture_duplicate_field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("fixture_nonfinite")


def fixture_result(raw):
    """Accept only D's exact fixed success frame, never child-supplied narrative."""
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
            or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
        raise ValueError("fixture_frame")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_constant=_reject_constant)
    if (type(value) is not dict or set(value) != {"v", "passed", "scope", "checks", "duration_ms"}
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["scope"] != FIXTURE_SCOPE or type(value["checks"]) is not dict
            or set(value["checks"]) != set(FIXTURE_CHECKS)
            or any(type(value["checks"][key]) is not bool or value["checks"][key] is not expected
                   for key, expected in FIXTURE_CHECKS.items())
            or type(value["duration_ms"]) is not int
            or not 0 <= value["duration_ms"] < FIXTURE_SECONDS * 1000):
        raise ValueError("fixture_result")
    return value


def fixture_failure(raw):
    """Project one fixed phase from an exact, bounded failed child frame."""
    try:
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
                or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
            return None
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if (type(value) is dict and set(value) == {"v", "passed", "scope", "phase", "duration_ms"}
                and type(value["v"]) is int and value["v"] == 1
                and value["passed"] is False and value["scope"] == FIXTURE_SCOPE
                and type(value["phase"]) is str and value["phase"] in FIXTURE_FAILURE_PHASES
                and type(value["duration_ms"]) is int
                and 0 <= value["duration_ms"] <= FIXTURE_SECONDS * 1000):
            return value["phase"]
    except (ValueError, UnicodeError, TypeError):
        pass
    return None


def verify_report(record, source, tree):
    fields = {"v", "passed", "evidence_level", "scope", "source_commit", "source_tree",
              "sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "sdk_sha256",
              "sdk_artifact", "bootstrap_report_sha256", "application", "runtime_installed_outside_checkout",
              "run_id", "checks", "fixture_duration_ms", "duration_seconds", "cleanup"}
    if type(record) is not dict or set(record) != fields:
        raise ValueError("image_admission_report_shape")
    try:
        bootstrap.verify_binding(record, source, tree)
    except (ValueError, AttributeError, TypeError, KeyError):
        raise ValueError("image_admission_report_binding") from None
    application = record["application"]
    entry = application.get("installed_sdk_entry") if type(application) is dict else None
    files = application.get("application_files") if type(application) is dict else None
    if (record["evidence_level"] != LEVEL or record["scope"] != SCOPE
            or type(record["checks"]) is not dict or set(record["checks"]) != set(CHECKS)
            or any(type(record["checks"][key]) is not bool or record["checks"][key] is not expected
                   for key, expected in CHECKS.items())
            or type(record["fixture_duration_ms"]) is not int
            or not 0 <= record["fixture_duration_ms"] < FIXTURE_SECONDS * 1000
            or type(record["duration_seconds"]) not in {int, float}
            or not math.isfinite(record["duration_seconds"])
            or not 0 <= record["duration_seconds"] < TOTAL_SECONDS
            or type(record["bootstrap_report_sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", record["bootstrap_report_sha256"]) is None
            or type(application) is not dict
            or set(application) != {"application_files", "installed_sdk_entry",
                                    "installed_outside_checkout", "imports_public_package"}
            or type(files) is not dict or "image-admission-check.mjs" not in files
            or type(files["image-admission-check.mjs"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", files["image-admission-check.mjs"]) is None
            or type(entry) is not str
            or not entry.startswith("node_modules/@mesh-chat/core-client/")
            or ".." in entry.split("/") or record["cleanup"] != "passed"):
        raise ValueError("image_admission_report_scope")
    return record


def run(expected_source, *, bootstrap_report=None, temporary_root=None):
    started = time.monotonic()
    deadline = started + TOTAL_SECONDS
    prior_report = Path(bootstrap_report or ROOT / "dist/reports/windows-independent-bootstrap.json")
    parent = Path(temporary_root or os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE}
    directory = None
    phase = "source_artifact_binding"
    try:
        binary, binding, sdk, report_hash = verified_inputs(expected_source, prior_report)
        sdk_hash = digest(sdk)
        node, npm = tools()
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        phase = "outside_checkout_installation"
        directory = outside_directory(parent)
        installed = install_typescript(directory, sdk, node, npm)
        files = installed.get("application_files") if type(installed) is dict else None
        if type(files) is not dict or "image-admission-check.mjs" not in files:
            raise ValueError("image_fixture_not_staged")
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or any(digest(directory / name) != value for name, value in files.items())):
            raise ValueError("installed_inputs_changed")
        require_unchanged(binary, binding)
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        phase = "image_admission_execution"
        data = directory / "app-data"
        observed = fixture_result(run_fixture(node, directory, runtime, data, deadline,
                                              fixture="image_admission", failure_parser=fixture_failure))
        phase = "protected_profile"
        protection = bootstrap.protected_profile(data)
        phase = "final_artifact_binding"
        require_unchanged(binary, binding)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or digest(prior_report) != report_hash
                or any(digest(directory / name) != value for name, value in files.items())):
            raise ValueError("installed_inputs_changed")
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        candidate = {"v": 1, "passed": True, "evidence_level": LEVEL, "scope": SCOPE,
                     **binding, "sdk_sha256": sdk_hash, "sdk_artifact": bootstrap.SDK_ARTIFACT,
                     "bootstrap_report_sha256": report_hash, "application": installed,
                     "runtime_installed_outside_checkout": True, "run_id": uuid4().hex,
                     "checks": {**observed["checks"], **protection},
                     "fixture_duration_ms": observed["duration_ms"],
                     "duration_seconds": time.monotonic() - started, "cleanup": "passed"}
        verify_report(candidate, binding["source_commit"], binding["source_tree"])
        phase = "owned_workspace_cleanup"
        if deadline - time.monotonic() < 30:
            raise TimeoutError("producer_cleanup_reserve")
        cleanup(directory, parent)
        candidate["duration_seconds"] = time.monotonic() - started
        if candidate["duration_seconds"] >= TOTAL_SECONDS:
            raise TimeoutError("producer_deadline")
        verify_report(candidate, binding["source_commit"], binding["source_tree"])
        result = candidate
    except Exception as failure:
        result.update(phase=phase, failure_type=type(failure).__name__,
                      workspace_retained=directory is not None and directory.is_dir(),
                      duration_seconds=min(max(0, time.monotonic() - started), TOTAL_SECONDS + 60))
        detail = failure.failure_detail if isinstance(failure, FixtureExecutionFailure) else None
        if type(detail) is str and detail in FIXTURE_FAILURE_PHASES:
            result["fixture_failure_phase"] = detail
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--bootstrap-report", type=Path)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    result = run(args.expected_source, bootstrap_report=args.bootstrap_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "phase": result.get("phase")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
