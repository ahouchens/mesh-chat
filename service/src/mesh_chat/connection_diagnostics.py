"""Allowlisted connection history in the existing protected vault.

One record, latest 200 events, seven-day retention, export below 64 KiB.
Never accept exception text, documents, network addresses or user labels.
"""
from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
import re
import time

from .errors import WORKSPACE_ALREADY_KNOWN_REASONS

LIMIT = 200
RETENTION = 7 * 24 * 3600
PHASES = frozenset({"waiting_for_reply", "waiting_for_ready", "ready_to_share", "ready_received",
    "connecting", "bootstrap_connected", "relationship_active", "admitted_path", "existing_routes_only",
    "refresh_required", "cancelled", "failed", "verified", "recovery", "unavailable",
    "connected", "reconnecting", "connection_update_needed", "dormant",
    "checking", "no_route", "network_changed", "test_failed", "both_no_address",
    "address_prepared", "no_local_address", "testing", "peer_verified", "complete"})
EVENTS = frozenset({"state", "import_verified", "import_rejected", "action_failed", "lifecycle_interrupted"})
KINDS = frozenset({"offer", "answer", "ready", "recovery", "unavailable"})
SOURCES = ("ipv4", "ipv6", "local_global", "pcp", "upnp", "upnp_ipv6", "nat_pmp")
FAILURE_PHASES = frozenset({"failed", "existing_routes_only", "refresh_required",
    "connection_update_needed", "no_route", "network_changed", "test_failed", "both_no_address"})
COMMANDS = frozenset({"preview_direct_connection", "prepare_direct_offer", "prepare_direct_answer",
    "prepare_direct_ready", "accept_direct_ready", "connect_direct_setup", "direct_setup_status",
    "check_direct_setup", "retry_direct_setup", "cancel_direct_setup", "resume_direct_setup"})
ERROR_CODES = frozenset({"internal_error", "invalid_request", "identity_mismatch", "invitation_invalid",
    "invitation_expired", "workspace_already_known", "workspace_limit_reached", "protected_storage_unavailable",
    "profile_in_use", "network_unavailable", "direct_connection_unavailable", "native_unavailable", "contact_not_approved",
    "contact_in_use", "recipient_keys_unavailable", "stale_cursor", "history_pruned"})
FAILURE_STAGES = frozenset({"runtime_check", "document_verification", "save_join_request", "join_authorization",
    "prepare_candidates", "sign_reply", "save_reply", "arm_socket", "verify_socket", "export_reply", "save_setup"})
FAILURE_REASONS = WORKSPACE_ALREADY_KNOWN_REASONS
WORKSPACE_STATES = frozenset({"unavailable", "none", "joining", "active", "linking", "leaving", "left", "removed",
    "closed", "forked", "incomplete_sync"})


def sanitize(value):
    """Revalidate stored data on export as well as at capture."""
    def integer(key, maximum, default=0):
        item = value.get(key)
        return item if type(item) is int and 0 <= item <= maximum else default
    reference = value.get("attempt")
    sources = value.get("candidate_sources")
    sources = sources if isinstance(sources, dict) else {}
    def enum(key, allowed, default):
        item = value.get(key)
        return item if isinstance(item, str) and item in allowed else default
    return {"time":integer("time", 2**53),
        "attempt":reference if isinstance(reference, str) and re.fullmatch(r"[0-9a-f]{12}", reference) else "unavailable",
        "event":enum("event", EVENTS, "action_failed"),
        "command":enum("command", COMMANDS, "unavailable"),
        "error_code":enum("error_code", ERROR_CODES, "unavailable"),
        "failure_stage":enum("failure_stage", FAILURE_STAGES, "unavailable"),
        "failure_reason":enum("failure_reason", FAILURE_REASONS, "unavailable"),
        "workspace_state":enum("workspace_state", WORKSPACE_STATES, "unavailable"),
        "phase":enum("phase", PHASES, "unavailable"),
        "kind":enum("kind", KINDS, "unavailable"),
        "candidate_count":integer("candidate_count", 8),
        "route":enum("route", {"available", "unavailable"}, "unavailable"),
        "socket":enum("socket", {"retained", "unavailable"}, "unavailable"),
        "mapping":enum("mapping", {"prepared_unverified", "unavailable", "not_needed"}, "unavailable"),
        "firewall":enum("firewall", {"udp_permission_unverified", "windows_profile_known_udp_unverified", "windows_profile_unavailable_udp_unverified"}, "unavailable"),
        "receipt_status":enum("receipt_status", {"confirmed", "not_confirmed"}, "unavailable"),
        "approval_status":enum("approval_status", {"approved", "pending"}, "unavailable"),
        "candidate_sources":{key:sources[key] if type(sources.get(key)) is int and 0 <= sources[key] <= 8 else None for key in SOURCES},
        "checks_started":integer("checks_started", 64, None),
        "checks_authenticated":integer("checks_authenticated", 128, None),
        "elapsed_ms":integer("elapsed_ms", 3600_000, None),
        "expires_at":integer("expires_at", 2**53)}


def history(service):
    record = service.store.get("connection_diagnostics", "history") or {}
    cutoff = int(time.time()) - RETENTION
    events = [sanitize(row) for row in record.get("events", [])[-LIMIT:] if isinstance(row, dict)]
    events = [row for row in events if row["time"] >= cutoff]
    failure = record.get("last_failure")
    failure = sanitize(failure) if isinstance(failure, dict) else None
    if failure and failure["time"] < cutoff:
        failure = None
    value = {"events":events, "last_failure":failure, "truncated":record.get("truncated") is True}
    # Retention applies to protected storage too, not only the exported view.
    if record and value != record:
        service.store.put("connection_diagnostics", "history", value)
    return value


def record(service, event, state=None):
    # Diagnostics must not change the outcome of an already committed join or
    # replace a validation error when protected storage is unavailable.
    try:
        _record(service, event, state)
    except Exception:
        pass


def _record(service, event, state=None):
    state = state or {}
    setup_id = state.get("setup_id")
    row = sanitize({**{key:state.get(key) for key in ("state", "kind", "command", "error_code", "failure_stage", "failure_reason", "workspace_state", "route", "socket", "mapping", "firewall", "candidate_count", "candidate_sources", "receipt_status", "approval_status", "expires_at", "checks_started", "checks_authenticated", "elapsed_ms")},
        "phase":state.get("state"), "event":event, "time":int(time.time()),
        "attempt":hashlib.sha256(setup_id.encode()).hexdigest()[:12] if isinstance(setup_id, str) and setup_id else "unavailable"})
    value = history(service)
    if value["events"] and {k:v for k,v in value["events"][-1].items() if k != "time"} == {k:v for k,v in row.items() if k != "time"}:
        return
    value["truncated"] = value["truncated"] or len(value["events"]) >= LIMIT
    value["events"] = (value["events"] + [row])[-LIMIT:]
    if row["phase"] in FAILURE_PHASES or event in {"import_rejected", "action_failed"}:
        value["last_failure"] = row
    service.store.put("connection_diagnostics", "history", value)


def report(service):
    value = history(service)
    try:
        installed = version("mesh-chat-service")
    except PackageNotFoundError:
        installed = "unavailable"
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+.][A-Za-z0-9.]+)?", installed):
        installed = "unavailable"
    result = {"format_version":1, "service_version":installed, "captured_at":int(time.time()),
        "retention_days":7, "event_limit":LIMIT, "native_check_counts":"unavailable",
        "receipt_status":"see_event_timestamp", "approval_status":"see_event_timestamp", **value}
    while len(json.dumps(result).encode()) >= 65536 and result["events"]:
        result["events"] = result["events"][1:]
        result["truncated"] = True
    return result
