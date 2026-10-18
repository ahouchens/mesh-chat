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

LIMIT = 200
RETENTION = 7 * 24 * 3600
PHASES = frozenset({"waiting_for_reply", "waiting_for_ready", "ready_to_share", "ready_received",
    "connecting", "bootstrap_connected", "relationship_active", "admitted_path", "existing_routes_only",
    "refresh_required", "cancelled", "failed", "verified", "recovery", "unavailable"})
EVENTS = frozenset({"state", "import_verified", "import_rejected", "action_failed", "lifecycle_interrupted"})
KINDS = frozenset({"offer", "answer", "ready", "recovery", "unavailable"})
SOURCES = ("ipv4", "ipv6", "local_global", "pcp", "upnp", "upnp_ipv6", "nat_pmp")


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
        "phase":enum("phase", PHASES, "unavailable"),
        "kind":enum("kind", KINDS, "unavailable"),
        "candidate_count":integer("candidate_count", 8),
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
    row = sanitize({**{key:state.get(key) for key in ("state", "kind", "candidate_count", "candidate_sources", "expires_at", "checks_started", "checks_authenticated", "elapsed_ms")},
        "phase":state.get("state"), "event":event, "time":int(time.time()),
        "attempt":hashlib.sha256(str(state.get("setup_id", "unknown")).encode()).hexdigest()[:12]})
    value = history(service)
    if value["events"] and {k:v for k,v in value["events"][-1].items() if k != "time"} == {k:v for k,v in row.items() if k != "time"}:
        return
    value["truncated"] = value["truncated"] or len(value["events"]) >= LIMIT
    value["events"] = (value["events"] + [row])[-LIMIT:]
    if row["phase"] in {"failed", "existing_routes_only", "refresh_required"} or event in {"import_rejected", "action_failed"}:
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
        "receipt_status":"unavailable", "approval_status":"unavailable", **value}
    while len(json.dumps(result).encode()) >= 65536 and result["events"]:
        result["events"] = result["events"][1:]
        result["truncated"] = True
    return result
