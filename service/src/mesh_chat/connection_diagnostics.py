"""Allowlisted connection history in the existing protected vault.

One record, latest 200 events, seven-day retention, export below 64 KiB.
Never accept exception text, documents, network addresses or user labels.
"""
from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
import math
import re
import time

from .connectivity import DIAGNOSTIC_REASONS as NETWORK_FAILURE_REASONS
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
    "prepare_direct_ready", "accept_direct_ready", "connect_direct_setup", "configure_direct_firewall",
    "direct_setup_status", "check_direct_setup", "retry_direct_setup", "cancel_direct_setup", "resume_direct_setup"})
ERROR_CODES = frozenset({"internal_error", "invalid_request", "identity_mismatch", "invitation_invalid",
    "invitation_expired", "workspace_already_known", "workspace_limit_reached", "protected_storage_unavailable",
    "profile_in_use", "network_unavailable", "direct_connection_unavailable", "native_unavailable", "contact_not_approved",
    "contact_in_use", "recipient_keys_unavailable", "stale_cursor", "history_pruned"})
FAILURE_STAGES = frozenset({"runtime_check", "document_verification", "save_join_request", "join_authorization",
    "prepare_candidates", "sign_reply", "save_reply", "arm_socket", "verify_socket", "export_reply", "save_setup"})
FAILURE_REASONS = WORKSPACE_ALREADY_KNOWN_REASONS | NETWORK_FAILURE_REASONS | frozenset({
    "no_public_candidate", "no_eligible_route", "no_global_ipv6_route",
    "no_global_ipv6_address", "no_public_ipv4", "ipv6_pinhole_unavailable",
    "manual_forward_configured", "manual_forward_available", "mapping_not_attempted",
    "firewall_not_checked", "no_prepared_candidate",
})
WORKSPACE_STATES = frozenset({"unavailable", "none", "joining", "active", "linking", "leaving", "left", "removed",
    "closed", "forked", "incomplete_sync"})
PENDING_MESSAGE_STATES = ("waiting_for_keys", "queued", "sending", "stored_for_delivery", "received_by_endpoint")
RECONNECT_REASONS = ("local_capabilities_missing", "peer_capabilities_missing", "peer_capabilities_expired",
    "local_capabilities_expired", "consent_missing", "peer_consent_missing", "relay_required",
    "mailbox_not_configured", "workspace_peer_inactive")
RECONNECT_STATES = ("idle", "waiting_for_peer", "probing", "offer_pending", "answer_pending",
    "connecting", "connected", "retry_wait", "peer_offline", "manual_required", "stopped")


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


def current_state(service):
    """Read present transport/outbox evidence without exporting peer identifiers.

    Historical setup events describe earlier attempts and cannot establish the
    state of today's DataChannel or message. Do not call snapshot(), which also
    gathers plaintext, user labels, and unrelated workspace data.
    """
    network = getattr(service, "network", None)
    bridges = list(getattr(service, "_webrtc_bridges", {}).values())
    interface_available = False if network is None else None
    if network is not None:
        try:
            available = network.interface_available
            interface_available = available if type(available) is bool else None
        except Exception:
            pass
    def counter(value):
        return value if type(value) is int and 0 <= value <= 2**53 - 1 else 0
    result = {
        "captured_at": int(time.time()),
        "network_running": network is not None,
        "interface_available": interface_available,
        "webrtc_bridges": len(bridges),
        "webrtc_online_bridges": sum(getattr(bridge, "online", False) is True for bridge in bridges),
        "webrtc_received_bytes": sum(counter(getattr(bridge, "rxb", None)) for bridge in bridges),
        "webrtc_sent_bytes": sum(counter(getattr(bridge, "txb", None)) for bridge in bridges),
        "direct_outbox_status": "unavailable",
    }
    try:
        pending = [row for row in service.store.list("message")
            if row.get("direction") == "outbound" and row.get("kind") == "chat"
            and row.get("state") in PENDING_MESSAGE_STATES]
        contact_ids = {row.get("contact_id") for row in pending if isinstance(row.get("contact_id"), str)}
        route_count = key_count = unknown_count = 0
        for contact_id in contact_ids:
            contact = service.store.get("contact", contact_id)
            try:
                destination = bytes.fromhex(contact["destination_hash"])
                route_count += bool(network is not None and network.path_known(destination))
                key_count += bool(network is not None and network.recipient_ready(destination))
            except Exception:
                unknown_count += 1
        now = time.time()
        ages = [int(now - row["created_at"]) for row in pending
            if type(row.get("created_at")) in {int, float} and math.isfinite(row["created_at"])
            and 0 <= row["created_at"] <= now]
        result.update({
            "direct_outbox_status": "available",
            "pending_direct_messages": {state: sum(row["state"] == state for row in pending) for state in PENDING_MESSAGE_STATES},
            "oldest_pending_direct_message_age_seconds": max(ages) if ages else None,
            "pending_direct_contacts": len(contact_ids),
            "pending_contacts_with_route": route_count,
            "pending_contacts_with_keys": key_count,
            "pending_contacts_unchecked": unknown_count,
        })
    except Exception:
        # Copying earlier diagnostics must remain possible if the outbox or a
        # transport cannot be inspected. Never include exception text.
        pass
    return result


def native_webrtc_state(service):
    """Inspect service-owned transports, including after a WebView reload.

    Only aggregate allowlisted states/counters: never export native session
    identifiers, SDP, candidates, peer identities, or control-message contents.
    """
    live = getattr(service, "_native_webrtc_live", None)
    if live is None:
        return {"status": "unavailable"}
    sessions = list(live)
    channels = dict.fromkeys(("connecting", "open", "closing", "closed", "unavailable"), 0)
    ice = dict.fromkeys(("new", "checking", "connected", "completed", "disconnected", "failed", "closed", "unavailable"), 0)
    result = {"status": "available", "sessions": len(sessions), "attached": 0,
              "stats_unavailable": 0, "received_packets": 0, "received_controls": 0,
              "channels": channels, "ice": ice}
    for session_id in sessions:
        try:
            stats = service.native_webrtc_stats(session_id)
            if not isinstance(stats, dict):
                raise ValueError("Native statistics unavailable")
        except Exception:
            stats = {}
            result["stats_unavailable"] += 1
        result["attached"] += stats.get("attached") is True
        for counts, key in ((channels, "data_channel_state"), (ice, "ice_connection_state")):
            state = stats.get(key)
            counts[state if isinstance(state, str) and state in counts else "unavailable"] += 1
        for key in ("received_packets", "received_controls"):
            value = stats.get(key)
            if type(value) is int and 0 <= value <= 2**53 - 1:
                result[key] = min(2**53 - 1, result[key] + value)
    return result


def background_state(service):
    """Export service health, never arbitrary native status or exception text."""
    try:
        value = service.background_availability_status()
        native = value.get("native") or {}
        def choice(raw, allowed):
            return raw if isinstance(raw, str) and raw in allowed else "unavailable"
        def boolean(raw):
            return raw if type(raw) is bool else None
        restorations = native.get("restorations")
        return {
            "status": "available", "enabled": boolean(value.get("enabled")),
            "health": choice(value.get("health"), {"off", "starting", "available", "degraded", "failed", "stopped", "unknown"}),
            "lifecycle_state": choice(value.get("lifecycle_state"), {"foreground", "background", "background_available", "suspended", "reconciling", "caught_up"}),
            **{key: boolean(native.get(key)) for key in ("service_running", "runtime_initialized", "native_webrtc_ready", "start_requested", "notification_visible", "ui_foreground")},
            "native_enabled": boolean(native.get("enabled")),
            "notification_state": choice(native.get("notification_state"), {"allowed", "denied", "not_requested", "settings_required", "unknown"}),
            "failure": None if native.get("failure") is None else choice(native.get("failure"), {
                "foreground_start_denied", "foreground_restart_denied", "runtime_initialization_failed", "notification_permission_required"}),
            "restorations": restorations if type(restorations) is int and 0 <= restorations <= 2**53 - 1 else None,
        }
    except Exception:
        return {"status": "unavailable"}


def reconnect_state(service):
    # reconnect_profiles() promotes pending capabilities and creates device
    # state. Diagnostic inspection must only read the persisted profiles.
    try:
        profiles = [service._reconnect_profile_public(row) for row in service.store.list("reconnect_profile")]
        return {
            "status": "available",
            "mailbox_configured": bool(getattr(getattr(service, "_call_settings", None), "signal_mailbox_url", None)),
            "profiles": len(profiles),
            "profiles_ready": sum(row["effective"]["ready"] is True for row in profiles),
            "profiles_with_mailbox": sum(row["effective"]["configured"] is True for row in profiles),
            "local_consent": sum(row["auto_reconnect"] is True for row in profiles),
            "peer_consent": sum(row["peer_auto_reconnect"] is True for row in profiles),
            "states": {state: sum((row.get("state") if row.get("state") in RECONNECT_STATES else "unavailable") == state
                for row in profiles) for state in (*RECONNECT_STATES, "unavailable")},
            "reasons": {reason: sum(reason in row["effective"]["reasons"] for row in profiles) for reason in RECONNECT_REASONS},
        }
    except Exception:
        return {"status": "unavailable"}


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
        "receipt_status":"see_event_timestamp", "approval_status":"see_event_timestamp",
        "current_state":current_state(service), "current_native_webrtc":native_webrtc_state(service),
        "current_reconnect":reconnect_state(service), "current_background":background_state(service), **value}
    while len(json.dumps(result).encode()) >= 65536 and result["events"]:
        result["events"] = result["events"][1:]
        result["truncated"] = True
    return result
