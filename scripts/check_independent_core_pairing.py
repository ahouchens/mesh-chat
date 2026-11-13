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

LEVEL = "windows_installed_public_sdk_pairing_receipts_and_shared_host_sdk_session_lifetime"
SCOPE = "Installed Windows public-SDK pairing and two authenticated receipts, two SDK sessions in one Node application under the same authorized caller sharing one normal app-owned host, client.close detach/reattach and pending-message/key preservation across trusted owner reopen with actual DPAPI/EFS; positive host service-process exits, native-host shutdown acknowledgment and runtime lock reacquisition; no separate consumer-process exit, caller/cross-user/multi-app isolation, isolated-helper retirement, Android, cross-platform, credential-UI, selected-path, impairment, media, physical or SC21 qualification"
CHECKS = {"fresh_profiles": 2, "alternate_paths_disabled": True, "direct_disclosure_consented": False,
          "relay_only_requested": True, "broker_consent": True,
          "explicit_contact_decisions": 2, "supervisor_transfers": 2, "public_messaging_ready": 2,
          "transferred_cancel_preserves_delivery": True,
          "authenticated_receipts": 2, "original_message_key_replay": True,
          "single_inbound_and_outbound_records": True, "clean_host_exits": 3,
          "concurrent_owner_refusals": 1, "rejected_owner_exits": 1,
          "pending_message_before_owner_stop": True, "reopened_original_message_and_key": True,
          "reopened_same_public_identity": True, "runtime_lock_reacquired": True,
          "owner_native_host_shutdown_acknowledgments": 3, "shared_host_sdk_sessions": 2,
          "closed_sdk_session_survivor_usable": True, "reattached_sdk_session_same_authorized_state": True,
          "efs_profile_directories": 2, "efs_vault_files": 2}
PHASES = {"arguments", "fresh_profiles", "public_pairing", "explicit_approval", "transferred_cancellation",
          "authenticated_receipts", "shared_host_lifetime", "retirement"}
SUBPHASES = {
    "arguments": {"arguments"},
    "fresh_profiles": {"offerer_create", "answerer_create", "identity_distinct"},
    "public_pairing": {"offer_begin", "offer_code_wait", "answer_begin"},
    "explicit_approval": {"invitation_wait", "invitation_guard", "invitation_accept", "pending_request_wait",
        "request_approve", "offerer_relationship_wait", "answerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait"},
    "transferred_cancellation": {"transfer_wait", "transferred_cancel"},
    "authenticated_receipts": {"offerer_receipt", "answerer_receipt", "offerer_ready_recheck", "answerer_ready_recheck"},
    "shared_host_lifetime": {"second_client_attach", "client_detach_survivor", "client_reattach",
        "competing_owner_refusal", "offline_receiver_stop", "pending_enqueue", "pending_owner_stop",
        "pending_owner_reopen", "original_key_replay"},
    "retirement": {"retirement"},
}
PAIRING_STATES = {"reserved", "offer_ready", "awaiting_approval", "transferred", "retiring", "retired", "unknown"}
SNAPSHOT_COUNTS = {"contacts", "invitations", "pending_invitations", "pending_requests", "approved_contacts"}
SNAPSHOT_FLAGS = {"matching_pending_request", "matching_approved_contact", "counts_capped", "network_present"}
SERVICE_ERRORS = {None, "network_start_failed", "network_interface_unavailable", "unknown"}
CONNECTION_COUNTS = {"total", "checked", "ready"}
TIMING_FIELDS = ("invitation_accept_started", "invitation_accept_returned", "pending_request_wait_entered", "failure_observed")
FAILURE_ORIGINS = {"budget_deadline", "wait_deadline", "core_error", "cleanup_failure", "unknown"}
ACTOR_ENUMS = {
    "desired": {"enabled", "stopped"},
    "execution": {"available", "paused", "locked", "shutting_down"},
    "negotiation": {"idle", "discover", "request", "wait_request", "wait_offer", "gather_offer",
                    "gather_answer", "publish_offer", "publish_answer", "wait_answer", "apply_answer",
                    "checking", "attach", "path", "inspect"},
}
ACTOR_ENUMS["reason"] = ACTOR_ENUMS["negotiation"] | {
    "unknown", "ineligible", "ready", "pending", "health_unknown", "bridge_retry_wait", "blocked",
    "retry_wait", "network_unavailable", "signaling_unavailable", "carrier_lost", "phase_timeout",
    "transient", "rate_limited", "configuration", "invalid_document", "revoked", "unsupported", "internal",
    "invalid_adoption", "wrong_resource", "missing_observation", "invalid_pending", "unverified_resource",
    "missing_carrier", "context_changed", "observed", "poll_wait",
}
INVITATION_SAMPLE_OFFSETS_MS = [0, 1000, 5000, 20000, 90000]
# Five selected public checkpoints fit beside the existing bounded failure envelope.
MAX_FAILURE_STDOUT_BYTES = 8192
ERROR_CODES = {"invalid_request", "incompatible_version", "negotiation_required", "unsupported_operation",
    "unauthenticated", "forbidden", "not_found", "locked", "conflict", "idempotency_conflict",
    "idempotency_expired", "resync_required", "resource_exhausted", "rate_limited", "unavailable", "internal"}


def bounded_observation(value, counts, flags, extra=frozenset()):
    if (not isinstance(value, dict) or set(value) != counts | flags | extra
            or any(type(value[key]) is not int or not 0 <= value[key] <= 256 for key in counts)
            or any(type(value[key]) is not bool for key in flags)):
        raise ValueError("Pairing failure observations contain unsafe or unbounded fields")


def cleanup_details(rows):
    if not isinstance(rows, list) or len(rows) > 4:
        raise ValueError("Pairing cleanup slots are unbounded")
    slots = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) - {"role", "incarnation", "attempts", "detach", "stop", "retired", "budget_ms"}
                or not {"role", "incarnation", "attempts", "detach", "stop", "retired"} <= set(row)
                or type(row["role"]) is not str or row["role"] not in {"offerer", "answerer", "contender"}
                or type(row["incarnation"]) is not int or not 1 <= row["incarnation"] <= (2 if row["role"] == "offerer" else 1)
                or type(row["attempts"]) is not int or not 0 <= row["attempts"] <= 2
                or type(row["detach"]) is not str or row["detach"] not in {"not_attempted", "ok", "failed"}
                or type(row["stop"]) is not str or row["stop"] not in {"not_attempted", "completed", "failed"}
                or type(row["retired"]) is not bool
                or row["retired"] != (row["detach"] == "ok" and row["stop"] == "completed")):
            raise ValueError("Pairing cleanup facts are invalid")
        slot = row["role"], row["incarnation"]
        if slot in slots:
            raise ValueError("Pairing cleanup slot is duplicated")
        slots.add(slot)
        attempted = row["attempts"] > 0
        if (("budget_ms" in row) != attempted
                or (attempted and (type(row["budget_ms"]) is not int or not 0 <= row["budget_ms"] <= 30000))
                or (row["detach"] != "not_attempted") != attempted or (row["stop"] != "not_attempted") != attempted):
            raise ValueError("Pairing cleanup attempt provenance is invalid")


def public_diagnostic_details(probe):
    if not isinstance(probe, dict) or set(probe) - {"offerer", "answerer"}:
        raise ValueError("Public diagnostic roles are invalid")
    for value in probe.values():
        if not isinstance(value, dict):
            raise ValueError("Public diagnostic result is invalid")
        outcome = value.get("query_outcome")
        if outcome == "not_attempted":
            if value != {"query_outcome": "not_attempted", "reason": "deadline_exhausted"}:
                raise ValueError("Public diagnostic deadline outcome is invalid")
        elif type(outcome) is str and outcome in {"failed", "invalid_result"}:
            if set(value) != {"query_outcome"}:
                raise ValueError("Public diagnostic failure has extra fields")
        elif outcome == "ok":
            if (set(value) != {"query_outcome", "available", "runtime_failure", "total_connections", "truncated", "connections"}
                    or type(value["available"]) is not bool or type(value["truncated"]) is not bool
                    or type(value["total_connections"]) is not int or not 0 <= value["total_connections"] <= 256
                    or (value["runtime_failure"] is not None and (type(value["runtime_failure"]) is not str
                        or value["runtime_failure"] not in {"adapter_quarantined", "cleanup_failed", "unknown"}))
                    or not isinstance(value["connections"], list) or len(value["connections"]) != min(value["total_connections"], 4)
                    or value["truncated"] != (value["total_connections"] > len(value["connections"]))
                    or (not value["available"] and (value["total_connections"] != 0 or value["runtime_failure"] is not None))):
                raise ValueError("Public diagnostic projection is invalid")
            for row in value["connections"]:
                if (not isinstance(row, dict) or set(row) != set(ACTOR_ENUMS)
                        or any(type(row[key]) is not str or row[key] not in choices | {"unknown"}
                               for key, choices in ACTOR_ENUMS.items())):
                    raise ValueError("Public diagnostic actor projection is invalid")
        else:
            raise ValueError("Public diagnostic outcome is invalid")


def invitation_observation_details(value):
    if (not isinstance(value, dict) or set(value) != {"sample_budget", "sample_offsets_ms",
            "request_budget_ms", "work_reserve_ms", "actor_limit", "samples", "capped"}
            or type(value["sample_budget"]) is not int or value["sample_budget"] != len(INVITATION_SAMPLE_OFFSETS_MS)
            or not isinstance(value["sample_offsets_ms"], list)
            or any(type(offset) is not int for offset in value["sample_offsets_ms"])
            or value["sample_offsets_ms"] != INVITATION_SAMPLE_OFFSETS_MS
            or type(value["request_budget_ms"]) is not int or value["request_budget_ms"] != 2000
            or type(value["work_reserve_ms"]) is not int or value["work_reserve_ms"] != 100
            or type(value["actor_limit"]) is not int or value["actor_limit"] != 1
            or type(value["capped"]) is not bool or not isinstance(value["samples"], list)
            or len(value["samples"]) > value["sample_budget"]
            or (value["capped"] and len(value["samples"]) != value["sample_budget"])):
        raise ValueError("Invitation observation budget is invalid")
    previous = -1
    for index, sample in enumerate(value["samples"]):
        if (not isinstance(sample, dict) or type(sample.get("outcome")) is not str
                or sample["outcome"] not in {"complete", "incomplete"}
                or set(sample) != ({"offset_ms", "pending_invitations", "counts_capped", "outcome"}
                    | ({"offerer", "answerer"} if sample["outcome"] == "complete" else set()))
                or type(sample["offset_ms"]) is not int
                or not INVITATION_SAMPLE_OFFSETS_MS[index] <= sample["offset_ms"] <= 600000
                or sample["offset_ms"] < previous
                or type(sample["pending_invitations"]) is not int
                or not 0 <= sample["pending_invitations"] <= 256
                or type(sample["counts_capped"]) is not bool):
            raise ValueError("Invitation observation sample is invalid")
        previous = sample["offset_ms"]
        if sample["outcome"] == "incomplete":
            continue
        for role in ("offerer", "answerer"):
            peer = sample[role]
            if not isinstance(peer, dict) or set(peer) != {"pairing", "actor"}:
                raise ValueError("Invitation observation peer is invalid")
            pairing = peer["pairing"]
            if (not isinstance(pairing, dict) or type(pairing.get("query_outcome")) is not str
                    or pairing["query_outcome"] not in {
                    "ok", "failed", "invalid_result", "not_attempted"}):
                raise ValueError("Invitation pairing observation is invalid")
            if pairing["query_outcome"] == "ok":
                if (set(pairing) != {"query_outcome", "state", "expired"}
                        or type(pairing["state"]) is not str
                        or pairing["state"] not in PAIRING_STATES - {"unknown"}
                        or type(pairing["expired"]) is not bool):
                    raise ValueError("Invitation pairing state is invalid")
            elif set(pairing) != {"query_outcome"}:
                raise ValueError("Invitation pairing failure contains extra fields")
            actor = peer["actor"]
            if (not isinstance(actor, dict) or type(actor.get("query_outcome")) is not str
                    or actor["query_outcome"] not in {
                    "ok", "failed", "invalid_result", "not_attempted"}):
                raise ValueError("Invitation actor observation is invalid")
            if actor["query_outcome"] == "ok":
                if (set(actor) != {"query_outcome", "available", "runtime_failure", "total_connections",
                        "truncated", "actor"}
                        or type(actor["available"]) is not bool
                        or type(actor["total_connections"]) is not int
                        or not 0 <= actor["total_connections"] <= 256
                        or type(actor["truncated"]) is not bool
                        or actor["truncated"] != (actor["total_connections"] > 1)
                        or type(actor["runtime_failure"]) not in {type(None), str}
                        or actor["runtime_failure"] not in {None, "adapter_quarantined", "cleanup_failed", "unknown"}
                        or (not actor["available"] and (actor["total_connections"] != 0
                            or actor["runtime_failure"] is not None))):
                    raise ValueError("Invitation actor projection is invalid")
                selected = actor["actor"]
                if actor["total_connections"] == 1:
                    if (not isinstance(selected, dict) or set(selected) != set(ACTOR_ENUMS)
                            or any(type(selected[key]) is not str or selected[key] not in choices | {"unknown"}
                                   for key, choices in ACTOR_ENUMS.items())):
                        raise ValueError("Invitation actor state is invalid")
                elif selected is not None:
                    raise ValueError("Ambiguous invitation actor is selected")
            elif set(actor) != {"query_outcome"}:
                raise ValueError("Invitation actor failure contains extra fields")


def owner_retirement_details(value):
    if (type(value) is not dict or set(value) != {"scope", "budget_ms", "peers"}
            or value["scope"] != "trusted_owner_before_cleanup" or type(value["budget_ms"]) is not int
            or value["budget_ms"] != 2000 or type(value["peers"]) is not dict
            or set(value["peers"]) - {"offerer", "answerer"}):
        raise ValueError("Owner diagnostic envelope is invalid")
    phases = {"discover", "wait_offer", "gather_offer", "gather_answer", "publish_offer", "publish_answer",
              "wait_answer", "apply_answer", "checking", "unknown"}
    events = {"tick", "failed", "result", "adopted", "context_changed", "handoff_rejected", "unknown"}
    reasons = {"transient", "rate_limited", "configuration", "invalid_document", "revoked", "unsupported",
               "internal", "phase_timeout", "ineligible", "context_changed", "network_unavailable", "wrong_resource",
               "invalid_adoption", "invalid_handoff", "invalid_pending", "unverified_resource", "missing_handoff",
               "handoff_rejected", "unknown"}
    for role, result in value["peers"].items():
        if type(result) is not dict or type(result.get("outcome")) is not str:
            raise ValueError("Owner diagnostic outcome is invalid")
        if result["outcome"] in {"not_received", "invalid_result"}:
            if set(result) != {"outcome"}:
                raise ValueError("Owner diagnostic failure contains extra fields")
            continue
        if result["outcome"] != "received" or set(result) != {"outcome", "observation"}:
            raise ValueError("Owner diagnostic outcome is invalid")
        observed = result["observation"]
        if (type(observed) is not dict or set(observed) != {"status", "total_intents", "intents"}
                or type(observed["status"]) is not str or observed["status"] not in {"observed", "unavailable"}
                or type(observed["total_intents"]) is not int or not 0 <= observed["total_intents"] <= 32
                or type(observed["intents"]) is not list):
            raise ValueError("Owner diagnostic observation is invalid")
        if observed["status"] == "unavailable":
            if observed["intents"]:
                raise ValueError("Unavailable owner diagnostic contains an intent")
            continue
        if observed["total_intents"] != 1 or len(observed["intents"]) != 1:
            raise ValueError("Owner diagnostic intent attribution is ambiguous")
        intent = observed["intents"][0]
        if (type(intent) is not dict or set(intent) != {"role", "state", "retirement"}
                or intent["role"] != ("offer" if role == "offerer" else "answer")
                or type(intent["state"]) is not str or intent["state"] not in PAIRING_STATES - {"unknown"}):
            raise ValueError("Owner diagnostic intent is invalid")
        cause = intent["retirement"]
        if cause is not None and (intent["state"] not in {"retiring", "retired"} or type(cause) is not dict
                or set(cause) != {"phase", "event", "reason"}
                or any(type(cause[key]) is not str or cause[key] not in choices
                       for key, choices in (("phase", phases), ("event", events), ("reason", reasons)))):
            raise ValueError("Owner diagnostic retirement is invalid")


def failure_details(value):
    if (not isinstance(value, dict) or set(value) != {"passed", "phase", "error_code", "diagnostics"}
            or value["passed"] is not False or value["phase"] not in PHASES
            or value["error_code"] not in ERROR_CODES):
        raise ValueError("Pairing failure envelope is invalid")
    diagnostics = value["diagnostics"]
    if (not isinstance(diagnostics, dict) or set(diagnostics) - {
                "subphase", "deadline_exhausted", "peers", "failure_probe", "stage_timing", "post_accept_reads",
                "failure_origin", "cleanup", "public_diagnostics", "invitation_observation", "owner_retirement"}
            or not {"subphase", "deadline_exhausted", "peers", "failure_origin", "cleanup"} <= set(diagnostics)
            or diagnostics["subphase"] not in SUBPHASES[value["phase"]]
            or type(diagnostics["deadline_exhausted"]) is not bool
            or not isinstance(diagnostics["peers"], dict) or set(diagnostics["peers"]) - {"offerer", "answerer"}):
        raise ValueError("Pairing failure subphase or roles are invalid")
    if (type(diagnostics["failure_origin"]) is not str or diagnostics["failure_origin"] not in FAILURE_ORIGINS
            or (diagnostics["failure_origin"] == "cleanup_failure" and value["phase"] != "retirement")):
        raise ValueError("Pairing failure origin is invalid")
    cleanup_details(diagnostics["cleanup"])
    if "owner_retirement" in diagnostics:
        owner_retirement_details(diagnostics["owner_retirement"])
    if "public_diagnostics" in diagnostics:
        public_diagnostic_details(diagnostics["public_diagnostics"])
    if "invitation_observation" in diagnostics:
        if value["phase"] in {"arguments", "fresh_profiles", "public_pairing"}:
            raise ValueError("Invitation observation precedes invitation wait")
        invitation_observation_details(diagnostics["invitation_observation"])
    if ("stage_timing" in diagnostics) != (value["phase"] != "arguments"):
        raise ValueError("Pairing failure has no stage timing provenance")
    offsets = {}
    if "stage_timing" in diagnostics:
        timing = diagnostics["stage_timing"]
        if (not isinstance(timing, dict) or set(timing) != {"offsets_ms", "clipped"}
                or type(timing["clipped"]) is not bool or not isinstance(timing["offsets_ms"], dict)):
            raise ValueError("Pairing stage timing is invalid")
        offsets = timing["offsets_ms"]
        if (set(offsets) - set(TIMING_FIELDS) or "failure_observed" not in offsets
                or any(type(value) is not int or not 0 <= value <= 600000 for value in offsets.values())
                or ("invitation_accept_returned" in offsets and "invitation_accept_started" not in offsets)
                or ("pending_request_wait_entered" in offsets and "invitation_accept_returned" not in offsets)):
            raise ValueError("Pairing stage offsets are unbounded or incomplete")
        ordered = [offsets[key] for key in TIMING_FIELDS if key in offsets]
        if not timing["clipped"] and ordered != sorted(ordered):
            raise ValueError("Pairing stage offsets are inconsistent")
    if ("pending_request_wait_entered" in offsets) != ("post_accept_reads" in diagnostics):
        raise ValueError("Post-accept read observations have no stage provenance")
    if "post_accept_reads" in diagnostics:
        reads = diagnostics["post_accept_reads"]
        if (not isinstance(reads, dict) or set(reads) != {"attempts", "completed", "clipped", "deadline_exhausted_at_entry"}
                or any(type(reads[key]) is not int or not 0 <= reads[key] <= 4096 for key in ("attempts", "completed"))
                or any(type(reads[key]) is not bool for key in ("clipped", "deadline_exhausted_at_entry"))
                or reads["completed"] > reads["attempts"]):
            raise ValueError("Post-accept read counts are invalid")
    if "failure_probe" in diagnostics:
        probe = diagnostics["failure_probe"]
        if not isinstance(probe, dict) or set(probe) - {"offerer", "answerer"}:
            raise ValueError("Pairing failure probe roles are invalid")
        for observation in probe.values():
            if not isinstance(observation, dict):
                raise ValueError("Pairing failure probe outcome is invalid")
            if observation.get("query_outcome") == "ok":
                if (set(observation) != {"query_outcome", "state", "expired"} or observation["state"] not in PAIRING_STATES - {"unknown"}
                        or type(observation["expired"]) is not bool):
                    raise ValueError("Pairing failure probe contains unsafe state fields")
            elif set(observation) != {"query_outcome"} or observation["query_outcome"] not in {"failed", "invalid_result"}:
                raise ValueError("Pairing failure probe contains unsafe failure fields")
    for peer in diagnostics["peers"].values():
        if not isinstance(peer, dict) or not peer or set(peer) - {"last_snapshot", "last_pairing", "last_connections"}:
            raise ValueError("Pairing failure peer observations are invalid")
        if "last_snapshot" in peer:
            bounded_observation(peer["last_snapshot"], SNAPSHOT_COUNTS, SNAPSHOT_FLAGS, {"observed_subphase", "service_error"})
            if peer["last_snapshot"]["observed_subphase"] not in set().union(*SUBPHASES.values()):
                raise ValueError("Snapshot observation subphase is invalid")
            service_error = peer["last_snapshot"]["service_error"]
            if (service_error is not None and not isinstance(service_error, str)) or service_error not in SERVICE_ERRORS:
                raise ValueError("Snapshot service error is not selected")
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
        if len(completed.stdout) > MAX_FAILURE_STDOUT_BYTES:
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
