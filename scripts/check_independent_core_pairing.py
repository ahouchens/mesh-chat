"""Two installed Windows applications using only public pairing and messages."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

import check_independent_core_consumers as bootstrap
from stage_independent_core_consumers import ROOT, cleanup, digest, install_typescript, outside_directory
from stage_core_sdk import tools

LEVEL = "windows_installed_public_sdk_supervisor_pairing_and_receipts"
SCOPE = "Two normally installed Windows application hosts, relay-only public pairing requests and authenticated receipts with actual DPAPI/EFS; no Android, selected-path, impairment, media, physical or SC21 qualification"
CHECKS = {"fresh_profiles": 2, "alternate_paths_disabled": True, "direct_disclosure_consented": False,
          "relay_only_requested": True, "broker_consent": True,
          "explicit_contact_decisions": 2, "supervisor_transfers": 2, "public_messaging_ready": 2,
          "transferred_cancel_preserves_delivery": True,
          "authenticated_receipts": 2, "original_message_key_replay": True,
          "single_inbound_and_outbound_records": True, "clean_host_exits": 2,
          "efs_profile_directories": 2, "efs_vault_files": 2}
PHASES = {"arguments", "fresh_profiles", "public_pairing", "explicit_approval", "transferred_cancellation",
          "authenticated_receipts", "retirement"}
SUBPHASES = {
    "arguments": {"arguments"},
    "fresh_profiles": {"offerer_create", "answerer_create", "identity_distinct"},
    "public_pairing": {"offer_begin", "offer_code_wait", "answer_begin"},
    "explicit_approval": {"invitation_wait", "invitation_guard", "invitation_accept", "pending_request_wait",
        "request_approve", "offerer_relationship_wait", "answerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait"},
    "transferred_cancellation": {"transfer_wait", "transferred_cancel"},
    "authenticated_receipts": {"offerer_receipt", "answerer_receipt", "offerer_ready_recheck", "answerer_ready_recheck"},
    "retirement": {"retirement"},
}
PAIRING_STATES = {"reserved", "offer_ready", "awaiting_approval", "transferred", "retiring", "retired", "unknown"}
SNAPSHOT_COUNTS = {"contacts", "invitations", "pending_invitations", "pending_requests", "approved_contacts"}
SNAPSHOT_FLAGS = {"matching_pending_request", "matching_approved_contact", "counts_capped"}
CONNECTION_COUNTS = {"total", "checked", "ready"}
ERROR_CODES = {"invalid_request", "incompatible_version", "negotiation_required", "unsupported_operation",
    "unauthenticated", "forbidden", "not_found", "locked", "conflict", "idempotency_conflict",
    "idempotency_expired", "resync_required", "resource_exhausted", "rate_limited", "unavailable", "internal"}


def bounded_observation(value, counts, flags):
    if (not isinstance(value, dict) or set(value) != counts | flags
            or any(type(value[key]) is not int or not 0 <= value[key] <= 256 for key in counts)
            or any(type(value[key]) is not bool for key in flags)):
        raise ValueError("Pairing failure observations contain unsafe or unbounded fields")


def failure_details(value):
    if (not isinstance(value, dict) or set(value) != {"passed", "phase", "error_code", "diagnostics"}
            or value["passed"] is not False or value["phase"] not in PHASES
            or value["error_code"] not in ERROR_CODES):
        raise ValueError("Pairing failure envelope is invalid")
    diagnostics = value["diagnostics"]
    if (not isinstance(diagnostics, dict) or set(diagnostics) != {"subphase", "deadline_exhausted", "peers"}
            or diagnostics["subphase"] not in SUBPHASES[value["phase"]]
            or type(diagnostics["deadline_exhausted"]) is not bool
            or not isinstance(diagnostics["peers"], dict) or set(diagnostics["peers"]) - {"offerer", "answerer"}):
        raise ValueError("Pairing failure subphase or roles are invalid")
    for peer in diagnostics["peers"].values():
        if not isinstance(peer, dict) or not peer or set(peer) - {"last_snapshot", "last_pairing", "last_connections"}:
            raise ValueError("Pairing failure peer observations are invalid")
        if "last_snapshot" in peer:
            bounded_observation(peer["last_snapshot"], SNAPSHOT_COUNTS, SNAPSHOT_FLAGS)
        if "last_connections" in peer:
            bounded_observation(peer["last_connections"], CONNECTION_COUNTS, {"counts_capped"})
            connections = peer["last_connections"]
            if not connections["ready"] <= connections["checked"] <= connections["total"]:
                raise ValueError("Pairing connection observations are inconsistent")
        if "last_pairing" in peer:
            pairing = peer["last_pairing"]
            if (not isinstance(pairing, dict) or set(pairing) != {"state", "code_present"}
                    or pairing["state"] not in PAIRING_STATES or type(pairing["code_present"]) is not bool):
                raise ValueError("Pairing state observations are invalid")
    return {"application_phase": value["phase"], "error_code": value["error_code"], "diagnostics": diagnostics}


def verify_report(record, source, tree):
    bootstrap.verify_binding(record, source, tree)
    if (record.get("evidence_level") != LEVEL or record.get("scope") != SCOPE
            or record.get("checks") != CHECKS
            or any(type(record["checks"].get(key)) is not type(value) for key, value in CHECKS.items())
            or not isinstance(record.get("bootstrap_report_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", record["bootstrap_report_sha256"]) is None):
        raise ValueError("Installed Windows public pairing evidence is incomplete or overstated")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--bootstrap-report", type=Path, default=ROOT / "dist/reports/windows-independent-bootstrap.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/windows-independent-pairing.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE}
    parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    directory = None
    phase = "source_artifact_binding"
    started = time.monotonic()
    try:
        from native_windows_evidence import artifact_binding, require_unchanged
        binary, binding = artifact_binding(args.expected_source)
        if not 0 < args.bootstrap_report.stat().st_size <= 128 * 1024:
            raise ValueError("Installed bootstrap prerequisite is missing")
        prior_hash = digest(args.bootstrap_report)
        prior = bootstrap.verify_report(json.loads(args.bootstrap_report.read_text()),
                                        binding["source_commit"], binding["source_tree"])
        if any(prior[key] != binding[key] for key in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")):
            raise ValueError("Normal bootstrap did not test this exact runtime")
        sdk = args.bootstrap_report.parent / prior["sdk_artifact"]
        if not 0 < sdk.stat().st_size <= 2 * 1024 * 1024 or digest(sdk) != prior["sdk_sha256"]:
            raise ValueError("Retained installed SDK prerequisite changed")
        node, npm = tools()
        directory = outside_directory(parent)
        phase = "outside_checkout_installation"
        installed = install_typescript(directory, sdk, node, npm)
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if digest(runtime) != binding["sidecar_sha256"]:
            raise ValueError("Installed runtime differs from the source-bound binary")
        phase = "public_pairing_and_receipts"
        data = directory / "app-data"
        completed = subprocess.run([node, "pairing-check.mjs", "--runtime", str(runtime),
            "--data-directory", str(data)], cwd=directory, env=bootstrap.application_environment(os.environ),
            capture_output=True, timeout=330)
        if len(completed.stdout) > 4096:
            raise ValueError("Independent pairing result exceeds its budget")
        observed = json.loads(completed.stdout)
        if completed.returncode != 0:
            result.update(failure_details(observed))
            raise ValueError("Public application pairing or receipts failed")
        for role in ("offerer", "answerer"):
            bootstrap.protected_profile(data / role)
        checks = {**observed, "efs_profile_directories": 2, "efs_vault_files": 2}
        if checks != CHECKS or any(type(checks.get(key)) is not type(value) for key, value in CHECKS.items()):
            raise ValueError("Public pairing application omitted required execution")
        phase = "final_artifact_binding"
        require_unchanged(binary, binding)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != prior["sdk_sha256"]
                or digest(args.bootstrap_report) != prior_hash
                or any(digest(directory / name) != value for name, value in installed["application_files"].items())):
            raise ValueError("Application or prerequisite artifacts changed during pairing")
        result.update(passed=True, **binding, run_id=uuid4().hex, checks=checks, application=installed,
            sdk_sha256=prior["sdk_sha256"], sdk_artifact=bootstrap.SDK_ARTIFACT,
            bootstrap_report_sha256=prior_hash, runtime_installed_outside_checkout=True)
    except Exception as error:
        result.update(passed=False, phase=phase, failure_type=type(error).__name__)
    finally:
        if directory is not None:
            try: cleanup(directory, parent)
            except (OSError, ValueError): result.update(passed=False, cleanup_failed=True)
        result["duration_seconds"] = time.monotonic() - started
    if result["passed"]:
        result["cleanup"] = "passed"
        try: verify_report(result, binding["source_commit"], binding["source_tree"])
        except ValueError: result.update(passed=False, phase="evidence_validation", failure_type="ValueError")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "evidence_level": LEVEL}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
