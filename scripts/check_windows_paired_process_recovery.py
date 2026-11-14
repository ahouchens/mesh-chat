"""Installed Windows paired consumer-process recovery diagnostic only."""

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
from check_independent_core_pairing import ERROR_CODES as PAIRING_ERROR_CODES, SUBPHASES as PAIRING_SUBPHASES
from check_windows_separate_process_consumer import FixtureExecutionFailure, run_fixture
from native_windows_evidence import require_unchanged
from stage_core_sdk import tools
from stage_independent_core_consumers import ROOT, cleanup, digest, install_typescript, outside_directory
from windows_public_consumer_session import verified_inputs


FIXTURE = "paired-process-recovery-check.mjs"
REPORT = ROOT / "dist/reports/windows-independent-paired-process-recovery.json"
LEVEL = "windows_installed_public_sdk_paired_consumer_process_recovery"
SCOPE = ("Outside-checkout Windows TypeScript public SDK and frozen normal hosts; two explicitly approved "
         "profiles, distinct same-image consumer processes, application-side discarded enqueue reply, pending "
         "replay across trusted owner reopen and one authenticated delivery after receiver reopen; no cross-app "
         "caller isolation, selected path, impairment or full SC22/SC23/SC24/R7 acceptance")
FIXTURE_SCOPE = ("Installed public SDK Windows paired process recovery after explicit approval on one same-image "
                 "caller; application-side discarded enqueue reply, pending replay and later single delivery; "
                 "no cross-app caller isolation or full SC22/SC23/SC24 acceptance")
FIXTURE_CHECKS = {"approved_profiles": 2, "authenticated_pre_recovery_receipts": 2,
                  "max_owner_sdk_sessions": 2, "distinct_helper_processes": 2,
                  "discarded_application_reply": True, "independent_pending_commit_observed": True,
                  "first_helper_positive_exit": True, "owner_reopened_same_data": True,
                  "current_authority_preserved": True, "same_key_original_handle": True,
                  "changed_payload_conflict": True, "single_outbound_record": True,
                  "receiver_reopened": True, "authenticated_delivery_receipt": True,
                  "single_inbound_record": True, "positive_owner_exits": 4,
                  "positive_helper_exits": 2}
CHECKS = {**FIXTURE_CHECKS, "efs_profile_directories": 2, "efs_vault_files": 2}
MAX_STDOUT = 4096
FIXTURE_SECONDS = 360
TOTAL_SECONDS = 600
FIXTURE_FAILURE_STAGES = frozenset({
    "arguments", "initial_pairing", "initial_authority", "receiver_stop", "first_helper",
    "enqueue_and_pending", "first_helper_stop", "sender_stop", "sender_reopen", "second_helper",
    "replay_and_conflict", "second_helper_stop", "receiver_reopen", "delivery_receipt",
    "final_stop", "success_contract",
})
FIXTURE_FAILURE_CAUSES = frozenset({
    "public_rows", "duplicate_public_record", "public_capabilities", "public_authority_changed",
    "message_page", "duplicate_outbound", "pending_record_changed", "owner_session_count",
    "helper_identity", "reply_not_discarded", "pending_not_reopened", "replay_handle_changed",
    "changed_payload_accepted", "duplicate_after_replay", "receipt_records_changed", "retirement_count",
    "paired_contract", "helper_deadline", "helper_closed", "helper_process_error", "helper_output",
    "helper_reply", "helper_output_closed", "helper_unavailable", "helper_frame_budget",
    "helper_write", "helper_request_pending", "helper_exit", "public_pairing_deadline",
    "pairing_retired", "retirement_incomplete", "client_detach_incomplete", "helper_core_error",
    "unavailable",
})
PAIRING_PREFIX_PHASES = frozenset({"fresh_profiles", "public_pairing", "explicit_approval",
                                   "transferred_cancellation", "authenticated_receipts"})


def _unique_object(pairs):
    selected = {}
    for key, value in pairs:
        if key in selected:
            raise ValueError("fixture_duplicate_field")
        selected[key] = value
    return selected


def _reject_constant(_value):
    raise ValueError("fixture_nonfinite")


def fixture_result(raw):
    """Accept one exact, bounded, content-free result from the installed app."""
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
            or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
        raise ValueError("fixture_frame")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_constant=_reject_constant)
    if (type(value) is not dict or set(value) != {"v", "passed", "scope", "checks", "duration_ms"}
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["scope"] != FIXTURE_SCOPE or type(value["checks"]) is not dict
            or set(value["checks"]) != set(FIXTURE_CHECKS)
            or any(type(value["checks"][key]) is not type(expected)
                   or value["checks"][key] != expected for key, expected in FIXTURE_CHECKS.items())
            or type(value["duration_ms"]) is not int
            or not 0 <= value["duration_ms"] < FIXTURE_SECONDS * 1000):
        raise ValueError("fixture_result")
    return value


def fixture_failure(raw):
    """Extract fixed failure labels only from one bounded, exact child frame."""
    try:
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
                or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
            return None
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        expected = {"v", "passed", "scope", "phase", "stage", "cause", "duration_ms"}
        if (type(value) is not dict or set(value) not in (expected, expected | {"pairing_failure"})
                or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not False
                or value["scope"] != FIXTURE_SCOPE
                or type(value["phase"]) is not str
                or value["phase"] not in {"arguments", "paired_process_recovery"}
                or type(value["stage"]) is not str or value["stage"] not in FIXTURE_FAILURE_STAGES
                or (value["phase"] == "arguments") != (value["stage"] == "arguments")
                or type(value["cause"]) is not str or value["cause"] not in FIXTURE_FAILURE_CAUSES
                or type(value["duration_ms"]) is not int
                or not 0 <= value["duration_ms"] <= FIXTURE_SECONDS * 1000):
            return None
        detail = {"stage": value["stage"], "cause": value["cause"]}
        if "pairing_failure" in value:
            summary = validated_pairing_summary(value["pairing_failure"])
            if value["stage"] != "initial_pairing" or summary is None:
                return None
            detail["pairing_failure"] = summary
        return detail
    except (ValueError, UnicodeError, TypeError):
        return None


def validated_pairing_summary(value):
    if (type(value) is not dict or set(value) != {"phase", "subphase", "error_code"}
            or type(value["phase"]) is not str or value["phase"] not in PAIRING_PREFIX_PHASES
            or type(value["subphase"]) is not str
            or value["subphase"] not in PAIRING_SUBPHASES[value["phase"]]
            or type(value["error_code"]) is not str or value["error_code"] not in PAIRING_ERROR_CODES):
        return None
    return {"phase": value["phase"], "subphase": value["subphase"],
            "error_code": value["error_code"]}


def verify_report(record, source, tree):
    fields = {"v", "passed", "evidence_level", "scope", "source_commit", "source_tree",
              "sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "sdk_sha256",
              "sdk_artifact", "bootstrap_report_sha256", "application", "runtime_installed_outside_checkout",
              "run_id", "checks", "fixture_duration_ms", "duration_seconds", "cleanup"}
    if type(record) is not dict or set(record) != fields:
        raise ValueError("paired_process_report_shape")
    try:
        bootstrap.verify_binding(record, source, tree)
    except (ValueError, AttributeError, TypeError, KeyError):
        raise ValueError("paired_process_report_binding") from None
    application = record["application"]
    entry = application.get("installed_sdk_entry") if type(application) is dict else None
    files = application.get("application_files") if type(application) is dict else None
    if (record["evidence_level"] != LEVEL or record["scope"] != SCOPE
            or type(record["checks"]) is not dict or set(record["checks"]) != set(CHECKS)
            or any(type(record["checks"][key]) is not type(expected)
                   or record["checks"][key] != expected for key, expected in CHECKS.items())
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
            or type(files) is not dict or FIXTURE not in files
            or type(files[FIXTURE]) is not str or re.fullmatch(r"[a-f0-9]{64}", files[FIXTURE]) is None
            or type(entry) is not str
            or not entry.startswith("node_modules/@mesh-chat/core-client/")
            or ".." in entry.split("/") or record["cleanup"] != "passed"):
        raise ValueError("paired_process_report_scope")
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
        if type(files) is not dict or FIXTURE not in files:
            raise ValueError("paired_fixture_not_staged")
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or any(digest(directory / name) != value for name, value in files.items())):
            raise ValueError("installed_inputs_changed")
        require_unchanged(binary, binding)
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        phase = "paired_process_execution"
        data = directory / "app-data"
        observed = fixture_result(run_fixture(node, directory, runtime, data, deadline,
                                              fixture="paired_process_recovery",
                                              failure_parser=fixture_failure))
        phase = "protected_profiles"
        for role in ("offerer", "answerer"):
            protection = bootstrap.protected_profile(data / role)
            if (type(protection) is not dict
                    or set(protection) != {"efs_profile_directory", "efs_vault_file"}
                    or any(type(value) is not bool or value is not True for value in protection.values())):
                raise ValueError("unprotected_profile")
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
                     "checks": {**observed["checks"], "efs_profile_directories": 2,
                                "efs_vault_files": 2}, "fixture_duration_ms": observed["duration_ms"],
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
        if (type(detail) is dict and set(detail) in (
                {"stage", "cause"}, {"stage", "cause", "pairing_failure"})
                and type(detail["stage"]) is str and detail["stage"] in FIXTURE_FAILURE_STAGES
                and type(detail["cause"]) is str and detail["cause"] in FIXTURE_FAILURE_CAUSES):
            result.update(fixture_stage=detail["stage"], fixture_cause=detail["cause"])
            if "pairing_failure" in detail and detail["stage"] == "initial_pairing":
                summary = validated_pairing_summary(detail["pairing_failure"])
                if summary is not None:
                    result["pairing_failure"] = summary
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
