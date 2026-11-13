"""Production setup/handoff with real isolated RNS and two controlled carriers.

Source pipes qualify orchestration; the CI-only shipping dispatcher adds real
QUIC. Neither qualifies physical router reachability or Android devices.
"""
import multiprocessing
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import threading
import time
import uuid
import math
from collections import deque
from itertools import islice

import pytest


_WORKSPACE_DIAGNOSTIC_TABLES = (
    "workspace", "workspace_channel", "workspace_channel_control", "workspace_manifest",
    "workspace_delivery", "workspace_pending_control",
)
_WORKSPACE_DIAGNOSTIC_ROWS = 64
_WORKSPACE_DIAGNOSTIC_ATTEMPTS = 32
_WORKSPACE_DIAGNOSTIC_KINDS = (
    "workspace_manifest_root", "workspace_manifest_delegated", "workspace_channel_record",
    "workspace_channel_manifest", "workspace_channel_summary", "workspace_channel_fetch",
    "workspace_channel_transfer", "workspace_channel_recovery", "unknown",
    "workspace_event",
)
_WORKSPACE_DIAGNOSTIC_STATES = (
    "queued", "waiting_for_keys", "sending", "stored_for_delivery", "received_by_endpoint",
    "delivered", "failed", "expired", "cancelled", "unknown",
)


def _workspace_diagnostic_enum(value, allowed):
    return value if type(value) is str and value in allowed else "unknown"


def _workspace_diagnostic_token(value):
    return value if type(value) is str and 0 < len(value) <= 256 else None


def _workspace_diagnostic_time(value):
    try:
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def _workspace_diagnostic_rows(source, table):
    limit = 8 if table == "workspace" else _WORKSPACE_DIAGNOSTIC_ROWS
    metadata = {"truncated": False, "malformed_rows": 0, "unavailable": False}
    if not isinstance(source, (list, tuple)) and not hasattr(source, "__next__"):
        metadata["unavailable"] = True
        return [], metadata
    try:
        sampled = list(islice(source, limit + 1))
    except Exception:
        metadata["unavailable"] = True
        return [], metadata
    metadata["truncated"] = len(sampled) > limit
    rows = []
    required = {
        "workspace": ("id",), "workspace_channel": ("workspace_id", "id"),
        "workspace_channel_control": ("workspace_id", "channel_id", "digest"),
        "workspace_manifest": ("workspace_id", "digest"),
        "workspace_delivery": ("workspace_id",), "workspace_pending_control": ("workspace_id",),
    }[table]
    for row in sampled[:limit]:
        if (type(row) is not dict or any(_workspace_diagnostic_token(row.get(key)) is None for key in required)
                or (table == "workspace_manifest" and (type(row.get("epoch")) is not int or row["epoch"] < 1))):
            metadata["malformed_rows"] += 1
        else:
            rows.append(row)
    return rows, metadata


def _project_workspace_bootstrap_diagnostic(records, *, now):
    """Pure bounded state projection: no identifiers, payloads or raw times."""
    records = records if type(records) is dict else {}
    tables, metadata = {}, {}
    for table in _WORKSPACE_DIAGNOSTIC_TABLES:
        tables[table], metadata[table] = _workspace_diagnostic_rows(records.get(table), table)

    def presence(found, table):
        if found:
            return "present"
        partial = metadata[table]
        return "unknown" if any(partial.values()) else "absent"

    workspaces = []
    for workspace in tables["workspace"]:
        identifier = workspace["id"]
        reference = _workspace_diagnostic_token(workspace.get("general_channel_id"))
        channels = [row for row in tables["workspace_channel"] if row["workspace_id"] == identifier
                    and (row["id"] == reference or _workspace_diagnostic_token(row.get("name")) == "general")]
        general_ids = {row["id"] for row in channels}
        if reference is not None:
            general_ids.add(reference)
        controls = [row for row in tables["workspace_channel_control"]
                    if row["workspace_id"] == identifier and row["channel_id"] in general_ids]
        manifests = [row for row in tables["workspace_manifest"] if row["workspace_id"] == identifier]
        current = _workspace_diagnostic_token(workspace.get("manifest_hash"))
        workspaces.append({
            "state": _workspace_diagnostic_enum(workspace.get("state"), (
                "joining", "active", "closed", "forked", "removed", "left", "device_removed", "incomplete_sync")),
            "channel_discovery": _workspace_diagnostic_enum(workspace.get("channel_discovery"), ("converged", "incomplete")),
            "general_reference_present": reference is not None,
            "general_channel": presence(bool(channels), "workspace_channel"),
            "general_control": presence(bool(controls), "workspace_channel_control") if general_ids else "unknown",
            "epoch1_manifest": presence(any(type(row.get("epoch")) is int and row["epoch"] == 1 for row in manifests), "workspace_manifest"),
            "current_manifest": presence(any(row["digest"] == current for row in manifests), "workspace_manifest") if current else "unknown",
        })
    by_kind = dict.fromkeys(_WORKSPACE_DIAGNOSTIC_KINDS, 0)
    by_state = dict.fromkeys(_WORKSPACE_DIAGNOSTIC_STATES, 0)
    event_states = dict.fromkeys(_WORKSPACE_DIAGNOSTIC_STATES, 0)
    deliveries = []
    valid_now = _workspace_diagnostic_time(now)
    for row in tables["workspace_delivery"]:
        kind = _workspace_diagnostic_enum(row.get("kind"), _WORKSPACE_DIAGNOSTIC_KINDS)
        state = _workspace_diagnostic_enum(row.get("state"), _WORKSPACE_DIAGNOSTIC_STATES)
        attempts, due = row.get("attempt_count"), row.get("next_attempt_at")
        valid_attempts = type(attempts) is int and attempts >= 0
        valid_due = _workspace_diagnostic_time(due)
        schedule = "unknown"
        if state in ("received_by_endpoint", "delivered", "failed", "expired", "cancelled"):
            schedule = "terminal"
        elif state != "unknown" and valid_now and valid_due:
            schedule = "due" if due <= now else "future"
        deliveries.append({"kind": kind, "state": state,
            "attempts": min(attempts, _WORKSPACE_DIAGNOSTIC_ATTEMPTS) if valid_attempts else None,
            "attempts_capped": valid_attempts and attempts > _WORKSPACE_DIAGNOSTIC_ATTEMPTS,
            "schedule": schedule,
            "native_message_id_present": type(row.get("native_message_id")) is str and bool(row["native_message_id"]),
            "failure": "none" if row.get("failure_code") is None else _workspace_diagnostic_enum(
                row.get("failure_code"), ("identity_binding_invalid", "transport_unavailable", "transport_error"))})
        by_kind[kind] += 1
        by_state[state] += 1
        if kind == "workspace_event": event_states[state] += 1
    pending_kinds = dict.fromkeys(_WORKSPACE_DIAGNOSTIC_KINDS, 0)
    pending_reasons = dict.fromkeys(("missing_manifest", "missing_channel_predecessor", "unknown"), 0)
    for row in tables["workspace_pending_control"]:
        pending_kinds[_workspace_diagnostic_enum(row.get("kind"), pending_kinds)] += 1
        pending_reasons[_workspace_diagnostic_enum(row.get("reason"), pending_reasons)] += 1
    return {"workspaces": workspaces, "deliveries": deliveries,
            "delivery_counts": {"kind": by_kind, "state": by_state},
            "workspace_event_states": event_states,
            "pending_controls": {"kind": pending_kinds, "reason": pending_reasons},
            "tables": metadata, "limits": {"workspaces": 8, "rows_per_kind": _WORKSPACE_DIAGNOSTIC_ROWS,
                                          "attempts": _WORKSPACE_DIAGNOSTIC_ATTEMPTS}}


def _admission_control_document(row, workspace_id, channel_id=None):
    try:
        document = row["document"]
        if type(document) is not str or len(document) > 16384:
            return False
        raw = json.loads(document)
        return (type(raw) is dict and raw.get("workspace_id") == workspace_id
                and raw.get("name") == "general"
                and (channel_id is None or raw.get("channel_id") == channel_id))
    except Exception:
        return False


def _admission_channel_diagnostic(store, workspace_id, workspace_record_id,
                                  channel_record_id, delivery_ids, pending_ids, *,
                                  now, native_network=None, expected_channel_id=None):
    """Read only exact IDs retained by this test worker; project no identifiers."""
    unavailable = {"available": False}
    if (type(workspace_id) is not str or not workspace_id
            or type(workspace_record_id) is not str or not workspace_record_id
            or type(delivery_ids) not in (list, tuple) or len(delivery_ids) > 2
            or type(pending_ids) not in (list, tuple) or len(pending_ids) > 2
            or any(type(key) is not str or not key for key in (*delivery_ids, *pending_ids))):
        return unavailable
    try:
        workspace = store.get("workspace", workspace_record_id)
    except Exception:
        return unavailable
    if type(workspace) is not dict or workspace.get("id") != workspace_id:
        return unavailable
    general = workspace.get("general_channel_id")
    reference = type(general) is str and bool(general)
    channel_record = None
    if type(channel_record_id) is str and channel_record_id:
        try: channel_record = store.get("workspace_channel", channel_record_id)
        except Exception: channel_record = False

    def exact(kind, identifiers):
        rows = []
        for identifier in identifiers:
            try: rows.append(store.get(kind, identifier))
            except Exception: rows.append(False)
        return rows

    deliveries = exact("workspace_delivery", delivery_ids)
    pending = exact("workspace_pending_control", pending_ids)
    result = {"available": True,
        "workspace_state": _workspace_diagnostic_enum(workspace.get("state"),
            ("joining", "active", "incomplete_sync", "forked", "closed", "removed", "left")),
        "channel_discovery": _workspace_diagnostic_enum(workspace.get("channel_discovery"),
            ("incomplete", "converged")),
        "general_reference": "present" if reference else "absent",
        "general_channel_record": (
            "unknown" if not channel_record_id else
            "unavailable" if channel_record is False else
            "present" if type(channel_record) is dict and channel_record.get("name") == "general" and (
                channel_record.get("id") == general if reference else
                type(expected_channel_id) is str and channel_record.get("id") == expected_channel_id
            ) and channel_record.get("workspace_id") == workspace_id else
            "absent" if channel_record is None else "unavailable")}
    selected = None
    if not delivery_ids:
        control = {"selection": "not_observed"}
    elif any(row is False or (row is not None and (
            type(row) is not dict or row.get("workspace_id") != workspace_id
            or row.get("kind") != "workspace_channel_record"
            or not _admission_control_document(row, workspace_id, general if reference else None)))
            for row in deliveries):
        control = {"selection": "unavailable"}
    else:
        selected_rows = [row for row in deliveries if row is not None]
        if len(selected_rows) != 1:
            control = {"selection": "absent" if not selected_rows else "ambiguous"}
        else:
            selected = selected_rows[0]
            state = _workspace_diagnostic_enum(selected.get("state"), _WORKSPACE_DIAGNOSTIC_STATES)
            attempts = selected.get("attempt_count")
            valid_attempts = type(attempts) is int and attempts >= 0
            due = selected.get("next_attempt_at")
            schedule = "unknown"
            if state in ("received_by_endpoint", "delivered", "failed", "expired", "cancelled"):
                schedule = "terminal"
            elif state != "unknown" and _workspace_diagnostic_time(now) and _workspace_diagnostic_time(due):
                schedule = "due" if due <= now else "future"
            control = {"selection": "selected", "state": state,
                "attempts": min(attempts, _WORKSPACE_DIAGNOSTIC_ATTEMPTS) if valid_attempts else None,
                "attempts_capped": valid_attempts and attempts > _WORKSPACE_DIAGNOSTIC_ATTEMPTS,
                "schedule": schedule,
                "native_message_id_present": type(selected.get("native_message_id")) is str
                                             and bool(selected["native_message_id"]),
                "failure": "none" if selected.get("failure_code") is None else
                    _workspace_diagnostic_enum(selected.get("failure_code"),
                        ("identity_binding_invalid", "transport_unavailable", "transport_error"))}
    result["channel_control"] = control
    if not pending_ids:
        result["pending_control"] = {"selection": "not_observed"}
    elif any(row is False or (row is not None and (
            type(row) is not dict or row.get("workspace_id") != workspace_id
            or row.get("kind") != "workspace_channel_record"
            or not _admission_control_document(row, workspace_id)))
            for row in pending):
        result["pending_control"] = {"selection": "unavailable"}
    else:
        present = [row for row in pending if row is not None]
        result["pending_control"] = (
            {"selection": "absent"} if not present else
            {"selection": "ambiguous"} if len(present) != 1 else
            {"selection": "present", "reason": _workspace_diagnostic_enum(
                present[0].get("reason"), ("missing_manifest", "missing_channel_predecessor"))})
    if native_network is not None and selected is not None:
        try:
            result["native_failure"] = _native_failure_diagnostic(
                [selected], native_network, workspace_id, kind="workspace_channel_record")
        except Exception:
            result["native_failure"] = {"selection": "unavailable", "attempts": "unavailable",
                                        "callbacks": "unavailable"}
    return result


def _admission_pending_id(store, wire):
    digest = hashlib.sha256(wire.document.encode("utf-8")).hexdigest()
    return store.opaque_id("workspace-pending-control", wire.workspace_id, wire.kind, digest)


def _workspace_bootstrap_diagnostic(store, *, now, native_network=None, workspace_id=None):
    records = {}
    for table in _WORKSPACE_DIAGNOSTIC_TABLES:
        limit = 9 if table == "workspace" else _WORKSPACE_DIAGNOSTIC_ROWS + 1
        try:
            records[table] = [row for _, row in store.items(table, limit=limit)]
        except Exception:
            records[table] = None  # Unknown, never a false empty/success or error text.
    result = _project_workspace_bootstrap_diagnostic(records, now=now)
    if native_network is not None:
        try:
            result["native_failure"] = _native_failure_diagnostic(
                records["workspace_delivery"], native_network, workspace_id)
        except Exception:
            result["native_failure"] = {"selection": "unavailable", "attempts": "unavailable",
                                        "callbacks": "unavailable"}
    return result


def _bounded_counter(value):
    return (min(value, 64), value > 64) if type(value) is int and value >= 0 else (None, None)


def _callback_failure_diagnostic(network):
    condition = getattr(network, "_callback_condition", None)
    if condition is None or not condition.acquire(False):
        return "contended" if condition is not None else "unavailable"
    try:
        items = getattr(network, "_callback_items", None)
        if items is None:
            return "unavailable"
        queue_depth, queue_capped = _bounded_counter(len(items))
        inbound, inbound_capped = _bounded_counter(getattr(network, "_callback_dropped_inbound", None))
        status, status_capped = _bounded_counter(getattr(network, "_callback_dropped_status", None))
        return {"queue_depth": queue_depth, "queue_capped": queue_capped,
            "dropped_inbound": inbound, "dropped_inbound_capped": inbound_capped,
            "dropped_status": status, "dropped_status_capped": status_capped}
    except Exception:
        return "unavailable"
    finally:
        condition.release()


def _native_state(message):
    state = getattr(message, "state", None)
    for name, label in (("OUTBOUND", "outbound"), ("SENDING", "sending"),
                        ("SENT", "sent"), ("DELIVERED", "delivered"),
                        ("FAILED", "failed"), ("REJECTED", "rejected"),
                        ("CANCELLED", "cancelled")):
        if type(state) is int and state == getattr(message, name, None):
            return label
    return "unknown"


def _native_link_state(links, destination):
    if type(links) is not dict:
        return "unknown"
    link = links.get(destination)
    if link is None:
        return "absent"
    for name, label in (("ACTIVE", "active"), ("PENDING", "pending"),
                        ("STALE", "stale"), ("CLOSED", "closed")):
        if type(getattr(link, "status", None)) is int and getattr(link, "status") == getattr(link, name, None):
            return label
    return "unknown"


def _native_failure_diagnostic(rows, network, workspace_id, *, kind="workspace_event"):
    """Failure-only exact event probe; never return its private correlation keys."""
    callbacks = _callback_failure_diagnostic(network)
    result = {"selection": "unavailable", "attempts": "unavailable", "callbacks": callbacks}
    if type(rows) is not list or type(workspace_id) is not str:
        return result
    if len(rows) > 64:
        result["selection"] = "partial"
        return result
    if any(type(row) is not dict or type(row.get("workspace_id")) is not str
           or type(row.get("kind")) is not str for row in rows):
        result["selection"] = "partial"
        return result
    matching = [row for row in rows if row.get("workspace_id") == workspace_id
                and row.get("kind") == kind]
    if not matching:
        result["selection"] = "absent"
        return result
    if len(matching) != 1:
        result["selection"] = "ambiguous"
        return result
    row = matching[0]
    key, address = row.get("id"), row.get("recipient_destination")
    if type(key) is not str or type(address) is not str or len(address) != 32:
        result["selection"] = "partial"
        return result
    try:
        destination = bytes.fromhex(address)
    except ValueError:
        result["selection"] = "partial"
        return result
    result["selection"] = "selected"
    lock = getattr(network, "_message_lock", None)
    if lock is None or not lock.acquire(False):
        result["attempts"] = "contended" if lock is not None else "unavailable"
        return result
    try:
        messages = getattr(network, "_messages", None)
        attempts = messages.get(key) if type(messages) is dict else None
        if attempts is None:
            attempts = [] if type(messages) is dict else None
        if type(attempts) is not list:
            return result
        count = len(attempts)
        selected = attempts[-4:]
    except Exception:
        return result
    finally:
        lock.release()
    router = getattr(network, "router", None)
    pending = getattr(router, "pending_outbound", None)
    try:
        before = len(pending) if type(pending) is list else None
        sampled = list(islice(pending, 64)) if before is not None else []
        stable = before == len(pending) if before is not None else False
    except Exception:
        sampled, stable = [], False
    deferred = getattr(router, "pending_deferred_stamps", None)
    direct = getattr(router, "direct_links", None)
    backchannel = getattr(router, "backchannel_links", None)
    entries = []
    for message in selected:
        if before is None:
            pending_state = "unknown"
        elif any(candidate is message for candidate in sampled):
            pending_state = "present"
        elif not stable or before > 64:
            pending_state = "partial"
        else:
            pending_state = "absent"
        native_key = getattr(message, "message_id", None)
        deferred_state = ("present" if deferred.get(native_key) is message else "absent") if (
            type(deferred) is dict and type(native_key) in (bytes, str)) else "unknown"
        delivery_attempts, _ = _bounded_counter(getattr(message, "delivery_attempts", None))
        entries.append({"state": _native_state(message), "delivery_attempts": delivery_attempts,
            "pending": pending_state, "deferred": deferred_state,
            "direct_link": _native_link_state(direct, destination),
            "backchannel_link": _native_link_state(backchannel, destination)})
    result["attempts"] = {"count": min(count, 4), "capped": count > 4, "entries": entries}
    return result


def _call_traced_workspace_send(original_send, values, entry, mesh_error_type):
    """Observe one test-harness send without changing its result or exception."""
    try:
        result = original_send(**values)
    except mesh_error_type as error:
        entry["outcome"] = error.code if error.code in (
            "recipient_keys_unavailable", "network_unavailable") else "other_mesh_error"
        raise
    except Exception:
        entry["outcome"] = "other_error"
        raise
    entry["outcome"] = "accepted"
    return result


class PipeNative:
    def __init__(self, incoming, outgoing, delay_admission=False):
        self.incoming, self.outgoing = incoming, outgoing
        self.lock = threading.RLock()
        self.owned, self.remote, self.next = {}, {}, 0
        self.delay_admission = delay_admission
        self.admission_visible_at = None

    def request(self, operation, **payload):
        with self.lock:
            while True:
                try:
                    event = self.incoming.get_nowait()
                except queue.Empty:
                    break
                if event[0] == "activate":
                    self.remote[event[1]] = event[2]
                elif event[0] == "close":
                    self.remote.pop(event[1],None)
                elif event[1] in self.owned:
                    packets = self.owned[event[1]]["packets"]
                    if len(packets) < 32:
                        packets.append(event[2])
            if operation == "prepare":
                self.next += 1
                host = payload["address"].rsplit(":",1)[0].strip("[]")
                value = {"id":self.next,"host":host,"port":45000+self.next,
                    "session":str(uuid.uuid4()),"generation":payload["generation"],
                    "certificate":str(self.next).encode().hex()}
                self.owned[self.next] = {"public":value,"peer":None,"packets":[],"online":False}
                return dict(value)
            if operation == "close":
                self.owned.pop(payload["id"],None)
                self.outgoing.put(("close",payload["id"]),timeout=1)
                return None
            record = self.owned[payload["id"]]
            if operation == "inspect":
                return {key:record["public"][key] for key in ("id","host","port","certificate")}
            if operation in {"arm","rearm"}:
                return None
            if operation == "activate":
                record["peer"] = int(bytes.fromhex(payload["certificate"]).decode())
                self.outgoing.put(("activate",payload["id"],record["peer"]),timeout=1)
                return None
            online = self.remote.get(record["peer"]) == payload["id"]
            if operation == "poll":
                # The peer observes QUIC authentication before this service
                # installs its admitted RNS adapter. Bootstrap must stay alive
                # during that gap, or channel bootstrap never completes.
                if online and self.delay_admission and payload["id"] == 2:
                    if self.admission_visible_at is None:
                        self.admission_visible_at = time.monotonic()+1.5
                    if time.monotonic() < self.admission_visible_at:
                        return {"state":0,"packets":[]}
                state = 1 if online else 2 if record["online"] else 0
                record["online"] = record["online"] or online
                packets, record["packets"] = record["packets"], []
                return {"state":state,"packets":packets}
            if operation == "send":
                assert online
                for packet in payload["packets"]:
                    self.outgoing.put(("packet",record["peer"],packet),timeout=1)
                return None
            raise ValueError("unknown fake native operation")

    def close(self):
        with self.lock:
            for identifier in list(self.owned):
                self.request("close", id=identifier)

    retire = close


def _service_worker(root, incoming, outgoing, commands, replies, native_binary=None, delay_admission=False, unhosted=False, vault_key=None):
    import RNS
    from mesh_chat import connectivity as c
    from mesh_chat.errors import MeshChatError
    from mesh_chat.reticulum_config import NetworkSettings
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore
    c.default_routes = lambda: [c.RouteInfo(socket.AF_INET,"controlled","192.168.1.1","93.184.216.34",1)]
    if unhosted:
        c.default_routes = lambda: []
    store = VaultStore(Path(root), vault_key or os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings","network",NetworkSettings(nearby_discovery=False,lan_fallback=False).to_dict())
    if native_binary:
        from direct_app_host_fixture import AppHostNative
        native = AppHostNative(native_binary)
    else:
        native = PipeNative(incoming,outgoing,delay_admission)
    service = MeshChatService(store,Path(root),lambda _:None,direct_native=native)
    # Test-only, bounded evidence for the channel bootstrap handoff. Never
    # retain destination hashes, payloads, native IDs, or exception strings.
    channel_trace = []
    workspace_event_trace = deque(maxlen=16)
    workspace_event_trace_truncated = False
    admission_deliveries = {}
    admission_pending = {}
    admission_channels = {}
    admission_tracking_failed = False
    def retain_admission_id(table, workspace_id, identifier):
        nonlocal admission_tracking_failed
        if type(workspace_id) is not str or type(identifier) is not str:
            return
        if workspace_id not in table and len(table) >= 8:
            admission_tracking_failed = True
            return
        tracked = table.setdefault(workspace_id, [])
        if identifier not in tracked and len(tracked) < 2:
            tracked.append(identifier)
        elif identifier not in tracked:
            admission_tracking_failed = True
    def retain_admission_channel(workspace_id, document):
        if type(document) is not str or len(document) > 16384:
            return
        raw = json.loads(document)
        if (type(raw) is dict and raw.get("workspace_id") == workspace_id
                and raw.get("name") == "general"):
            retain_admission_id(admission_channels, workspace_id, raw.get("channel_id"))
    def traced_delivery_record(**values):
        nonlocal admission_tracking_failed
        row = original_delivery_record(**values)
        try:
            if (values.get("kind") == "workspace_channel_record"
                    and _admission_control_document(row, values.get("workspace_id"))):
                retain_admission_id(admission_deliveries, values["workspace_id"], row["id"])
                retain_admission_channel(values["workspace_id"], values["document"])
        except Exception:
            admission_tracking_failed = True
        return row
    def traced_pending_control(wire, reason):
        nonlocal admission_tracking_failed
        result = original_pending_control(wire, reason)
        try:
            if (wire.kind == "workspace_channel_record"
                    and _admission_control_document({"document": wire.document}, wire.workspace_id)):
                identifier = _admission_pending_id(store, wire)
                retain_admission_id(admission_pending, wire.workspace_id, identifier)
                retain_admission_channel(wire.workspace_id, wire.document)
        except Exception:
            admission_tracking_failed = True
        return result
    def channel_entry(destination, fields, content):
        bootstrap = getattr(service.network, "_direct_bootstrap", None)
        return {"bootstrap_ready": bool(bootstrap is not None and bootstrap.ready and bootstrap.peer == destination),
                "bootstrap_handles": bool(bootstrap is not None and bootstrap.ready and bootstrap.handles(destination, fields, content)),
                "main_identity": RNS.Identity.recall(destination) is not None,
                "main_ratchet": RNS.Identity.get_ratchet(destination) is not None,
                "main_path": bool(RNS.Transport.has_path(destination))}
    def traced_kind(fields, content):
        from mesh_chat.workspace_wire import parse_workspace_payload
        from types import SimpleNamespace
        try:
            wire = parse_workspace_payload(SimpleNamespace(get_fields=lambda: fields, content=content))
        except Exception:
            return None
        return wire.kind if wire.kind in {"workspace_channel_record", "workspace_event"} else None
    def trace_entry(destination, fields, content):
        try: return channel_entry(destination, fields, content)
        except Exception: return {key: None for key in (
            "bootstrap_ready", "bootstrap_handles", "main_identity", "main_ratchet", "main_path")}
    def retain_trace(kind, entry):
        nonlocal workspace_event_trace_truncated
        try:
            if kind == "workspace_event":
                was_full = len(workspace_event_trace) == workspace_event_trace.maxlen
                workspace_event_trace.append(entry)
                if was_full: workspace_event_trace_truncated = True
            elif kind == "workspace_channel_record" and len(channel_trace) < 16: channel_trace.append(entry)
        except Exception:
            pass  # A test-only trace cannot replace the original send outcome.
    def traced_payload_ready(destination, fields, content=""):
        kind = traced_kind(fields, content)
        if kind is None:
            return original_payload_ready(destination, fields, content)
        entry = {"stage": "preflight", **trace_entry(destination, fields, content)}
        try:
            result = original_payload_ready(destination, fields, content)
        except MeshChatError as error:
            entry["outcome"] = error.code if error.code in (
                "recipient_keys_unavailable", "network_unavailable") else "other_mesh_error"
            raise
        except Exception:
            entry["outcome"] = "other_error"
            raise
        else:
            entry["outcome"] = "ready" if result else "waiting"
            return result
        finally:
            retain_trace(kind, entry)
    def traced_workspace_send(**values):
        destination = values["recipient_destination"]
        fields, content = values["fields"], values["text"]
        kind = traced_kind(fields, content)
        if kind is None:
            return original_workspace_send(**values)
        entry = {"stage": "send", **trace_entry(destination, fields, content), "outcome": "unknown"}
        retain_trace(kind, entry)
        return _call_traced_workspace_send(original_workspace_send, values, entry, MeshChatError)
    def traced_workspace_status(logical_id, state, native_id):
        try:
            row = store.get("workspace_delivery", logical_id)
            is_event = type(row) is dict and row.get("kind") == "workspace_event"
        except Exception:
            is_event = False
        result = original_workspace_status(logical_id, state, native_id)
        if is_event:
            try: state_value = getattr(state, "value", None)
            except Exception: state_value = None
            outcome = "returned_true" if result is True else "returned_false" if result is False else "unknown"
            retain_trace("workspace_event", {"stage": "status", "outcome": outcome,
                "state": _workspace_diagnostic_enum(state_value, _WORKSPACE_DIAGNOSTIC_STATES)})
        return result
    def traced_workspace_ingress(native, wire):
        try: is_event = getattr(wire, "kind", None) == "workspace_event"
        except Exception: is_event = False
        if is_event: retain_trace("workspace_event", {"stage": "ingress", "outcome": "observed"})
        return original_workspace_ingress(native, wire)
    def traced_workspace_accept(wire, *args, **kwargs):
        try: is_event = getattr(wire, "kind", None) == "workspace_event"
        except Exception: is_event = False
        if not is_event:
            return original_workspace_accept(wire, *args, **kwargs)
        entry = {"stage": "acceptance", "outcome": "unknown"}
        retain_trace("workspace_event", entry)
        try:
            result = original_workspace_accept(wire, *args, **kwargs)
        except Exception:
            entry["outcome"] = "error"
            raise
        entry["outcome"] = "returned_true" if result is True else "returned_false" if result is False else "unknown"
        return result
    controls={"sent":0,"send_failed":0,"received":0,"rejected":0}
    original_send=service._direct_recovery._send
    original_receive=service._direct_recovery.receive
    def tracked_send(*args,**kwargs):
        result=original_send(*args,**kwargs)
        controls["sent" if result else "send_failed"]+=1
        return result
    def tracked_receive(*args,**kwargs):
        try:
            result=original_receive(*args,**kwargs)
            controls["received"]+=1
            return result
        except Exception:
            controls["rejected"]+=1
            raise
    service._direct_recovery._send=tracked_send
    service._direct_recovery.receive=tracked_receive
    try:
        service.create_profile("Controlled peer")
        original_payload_ready = service.network.recipient_ready_for_fields
        service.network.recipient_ready_for_fields = traced_payload_ready
        original_workspace_send = service.network.send_with_fields
        service.network.send_with_fields = traced_workspace_send
        original_workspace_status = service._on_workspace_native_status
        service._on_workspace_native_status = traced_workspace_status
        original_workspace_ingress = service._receive_workspace_payload
        service._receive_workspace_payload = traced_workspace_ingress
        original_workspace_accept = service._accept_workspace_event
        service._accept_workspace_event = traced_workspace_accept
        original_delivery_record = service._workspace_delivery_record
        service._workspace_delivery_record = traced_delivery_record
        original_pending_control = service._store_pending_workspace_control
        service._store_pending_workspace_control = traced_pending_control
        replies.put({"ok":True})
        while True:
            operation, payload = commands.get()
            if operation == "close":
                break
            if operation == "crash":
                os._exit(91)
            try:
                with service._dispatch_lock:
                    if operation == "command":
                        result, _ = service.dispatch({"v":1,"id":str(uuid.uuid4()),**payload})
                        result = result["result"]
                    elif operation == "diagnostic":
                        import RNS
                        result = {"native_count":len(service._direct_native.owned),
                                  "interfaces":len(RNS.Transport.interfaces)}
                    elif operation == "admission_diagnostic":
                        workspace_id = payload.get("workspace_id")
                        if admission_tracking_failed or type(workspace_id) is not str or not workspace_id:
                            result = {"available": False}
                        else:
                            record_id = service._workspace_record_id(workspace_id)
                            workspace = store.get("workspace", record_id)
                            general = workspace.get("general_channel_id") if type(workspace) is dict else None
                            observed = admission_channels.get(workspace_id, ())
                            channel = (general if type(general) is str and general else
                                       observed[0] if len(observed) == 1 else None)
                            channel_id = (service._workspace_channel_record_id(channel)
                                          if type(channel) is str and channel else None)
                            result = _admission_channel_diagnostic(store, workspace_id,
                                record_id, channel_id, admission_deliveries.get(workspace_id, ()),
                                admission_pending.get(workspace_id, ()), now=time.time(),
                                native_network=service.network, expected_channel_id=channel)
                    elif operation == "recovery_diagnostic":
                        from mesh_chat.invitations import canonical_bytes
                        result = {"peers":service._direct_recovery.status(),
                            "identity":service.network.destination_hash.hex(),"controls":dict(controls),
                            "migration_attempts":getattr(native,"migration_attempts",0),"migrations":getattr(native,"migrations",0),
                            "application_receipts":[hashlib.sha256(canonical_bytes(w["join_receipt"])).hexdigest()
                                for w in store.list("workspace") if w.get("join_receipt")],
                            "paths":[{"recovery":carrier.recovery,"certificate":hashlib.sha256(bytes.fromhex(carrier.prepared._owned["certificate"])).hexdigest()}
                                     for carrier in service._direct_recovery._active.values() if not carrier._stop.is_set()],
                            "pending":len(service._direct_recovery._pending),"native_count":len(native.owned),
                            # CI-controlled loopback ports only, never production diagnostics.
                            "test_owned_ports":[value[1]["port"] for value in native.owned.values()] if native_binary else [],
                            "test_native_trace":list(native.trace) if native_binary else [],
                            "test_local_ports":[(value.get("local") or {}).get("socket_hint",{}).get("port") for value in store.list("direct_recovery")],
                            "test_remote_ports":[[c["port"] for c in value.get("candidates",[])] for value in store.list("direct_relationship")],
                            "failures":[{key:value.get(key) for key in ("failure_stage","failure_type","attempts","state")}
                                        for value in store.list("direct_recovery")]}
                        result["workspace_bootstrap"] = _workspace_bootstrap_diagnostic(
                            store, now=time.time(),
                            native_network=service.network if payload.get("failure_native") is True else None,
                            workspace_id=payload.get("workspace_id"))
                        result["channel_send_trace"] = list(channel_trace)
                        result["workspace_event_trace"] = list(workspace_event_trace)
                        result["workspace_event_trace_truncated"] = workspace_event_trace_truncated
                    elif operation == "force_recovery":
                        if payload.get("retire"):
                            service._direct_recovery.retire()
                        if "blocked" in payload:
                            native.blocked = payload["blocked"]
                        for identifier, record in store.items("direct_relationship"):
                            if payload.get("lose_addresses"):
                                saved=service._direct_recovery._state(identifier).get("local")
                                assert saved
                                saved["socket_hint"]={**saved["socket_hint"],"port":0}
                                service._direct_recovery._write(identifier,local=saved)
                            service._direct_recovery._write(identifier,next_at=time.time(),
                                attempts=6 if payload.get("blocked") or payload.get("lose_addresses") else 0,state="reconnecting")
                        service._direct_recovery._wake.set()
                        result = None
                    elif operation == "route_change":
                        c.default_routes = lambda: [c.RouteInfo(socket.AF_INET,"changed","192.168.2.1","93.184.216.34",1)]
                        service._direct_recovery._route_check_at=0
                        result = None
                    elif operation == "relationship_evidence":
                        records = store.list("direct_relationship")
                        result = [{"scope": item["scope"], "accepted": item["accepted"],
                                   "last_success": item["last_success"]} for item in records]
                    else:
                        names = {"offer":"prepare_direct_offer", "answer":"prepare_direct_answer",
                            "ready":"prepare_direct_ready", "accept_ready":"accept_direct_ready",
                            "connect":"connect_direct_setup", "status":"direct_setup_status"}
                        result, _ = service.dispatch({"v":1,"id":str(uuid.uuid4()),
                            "command":names[operation],"payload":payload})
                        result = result["result"]
                replies.put({"ok":True,"result":result})
            except Exception as exc:
                replies.put({"ok":False,"error":type(exc).__name__+":"+str(exc)})
    finally:
        service.close()
        native.close()


@pytest.mark.integration
@pytest.mark.parametrize("retirement", ["cancel", "suspend", "revocation"])
@pytest.mark.parametrize("carrier_mode", ["source", "native"])
@pytest.mark.parametrize("unhosted_joiner", [False, True], ids=["both_hosted", "unhosted_joiner"])
def test_production_setup_bootstrap_admission_and_fresh_workspace_path(tmp_path, retirement, carrier_mode, unhosted_joiner, request):
    native_binary = os.environ.get("MESH_DIRECT_APP_HOST_BINARY") if carrier_mode == "native" else None
    if carrier_mode == "native" and not native_binary:
        pytest.skip("Requires the GitHub-built shipping native dispatcher harness")
    context = multiprocessing.get_context("spawn")
    pipes = [context.Queue(maxsize=128),context.Queue(maxsize=128)]
    commands, replies, processes = [], [], []
    def call(index, operation, **payload):
        commands[index].put((operation,payload),timeout=2)
        response = replies[index].get(timeout=15)
        assert response["ok"], response
        return response.get("result")
    def command(index, command_name, **payload):
        return call(index,"command",command=command_name,payload=payload)
    def wait(index, name, predicate, **payload):
        deadline = time.monotonic()+25
        last = None
        while time.monotonic() < deadline:
            last = command(index,name,**payload)
            result = predicate(last)
            if result:
                return result
            time.sleep(.1)
        # Preserve the original assertion and deadline, but retain both sides
        # of intermittent admission failures instead of only one snapshot.
        diagnostics = []
        for peer in range(2):
            try:
                diagnostics.append(call(peer, "recovery_diagnostic"))
            except Exception as error:
                diagnostics.append({"unavailable": type(error).__name__})
        raise AssertionError((name, last, {"peers": diagnostics}))
    op = lambda: str(uuid.uuid4())
    try:
        for index in range(2):
            commands.append(context.Queue(maxsize=2))
            replies.append(context.Queue(maxsize=2))
            process = context.Process(target=_service_worker,args=(str(tmp_path/str(index)),pipes[index],
                pipes[1-index],commands[index],replies[index],native_binary,index == 1,unhosted_joiner and index == 1))
            process.start()
            processes.append(process)
            assert replies[index].get(timeout=15)["ok"]
        workspace = command(0,"create_workspace",operation_id=op(),name="Production setup",description="")
        invite = command(0,"create_workspace_invitation",operation_id=op(),workspace_id=workspace["id"])
        offer = call(0,"offer",invitation_id=invite["id"])
        answer = call(1,"answer",document=offer["text"],operation_id=op())
        assert answer["candidate_count"] == (0 if unhosted_joiner else 1)
        ready = call(0,"ready",document=answer["text"])
        call(1,"accept_ready",document=ready["text"])
        for index, setup in enumerate((ready,answer)):
            assert call(index,"connect",setup_id=setup["setup_id"],document=ready["text"])["state"] == "connecting"
        join_request = wait(0,"workspace_snapshot",lambda snap:next((item for item in snap["workspace_join_requests"]
            if item["state"] == "pending"),None))
        wait(1,"workspace_snapshot",lambda snap:any(item.get("join_acknowledged") for item in snap["workspaces"]))
        command(0,"approve_workspace_join",operation_id=op(),workspace_id=workspace["id"],request_id=join_request["id"])
        wait(1,"workspace_snapshot",lambda snap:any(item["state"] == "active" for item in snap["workspaces"]))
        wait(1,"workspace_snapshot",lambda snap:any(item["id"] == workspace["general_channel_id"] for item in snap["workspace_channels"]))
        if carrier_mode == "source":
            request.node.user_properties.append(("channel_send_trace", call(0, "recovery_diagnostic")["channel_send_trace"]))
        for index, setup in enumerate((ready,answer)):
            assert call(index,"status",setup_id=setup["setup_id"])["state"] in {"admitted_path","relationship_active"}
        for sender, recipient in ((0,1),(1,0)):
            sent = command(sender,"send_workspace_message",operation_id=op(),event_id=op(),workspace_id=workspace["id"],
                channel_id=workspace["general_channel_id"],text="Fresh admitted path")
            wait(recipient,"list_workspace_messages",lambda page:any(item["id"] == sent["id"] for item in page["messages"]),
                workspace_id=workspace["id"],channel_id=workspace["general_channel_id"],limit=50)
            wait(sender,"list_workspace_messages",lambda page:any(item["id"] == sent["id"] and
                item.get("delivery_summary",{}).get("devices_reached") == 1 for item in page["messages"]),
                workspace_id=workspace["id"],channel_id=workspace["general_channel_id"],limit=50)
        if carrier_mode == "source":
            for index in range(2):
                diagnostic = call(index, "recovery_diagnostic")
                stages = {item["stage"] for item in diagnostic["workspace_event_trace"]}
                assert {"preflight", "send", "status", "ingress", "acceptance"} <= stages
                assert 0 < len(diagnostic["workspace_event_trace"]) <= 16
                assert type(diagnostic["workspace_event_trace_truncated"]) is bool
                assert all(item["outcome"] in {"returned_true", "returned_false", "unknown"}
                    for item in diagnostic["workspace_event_trace"] if item["stage"] == "status")
                assert all(item["outcome"] in {"returned_true", "returned_false", "unknown", "error"}
                    for item in diagnostic["workspace_event_trace"] if item["stage"] == "acceptance")
                assert diagnostic["workspace_bootstrap"]["delivery_counts"]["kind"]["workspace_event"] >= 1
        for index in range(2):
            evidence = call(index, "relationship_evidence")
            assert len(evidence) == 1
            assert evidence[0]["scope"]["workspace_id"] == workspace["id"]
            assert evidence[0]["last_success"] is not None
            # A newly accepted replacement can coexist with the authenticated old path.
            assert evidence[0]["last_success"]["generation"] <= evidence[0]["accepted"]["generation"]
            if evidence[0]["last_success"]["generation"] == evidence[0]["accepted"]["generation"]:
                assert evidence[0]["last_success"]["digest"] == evidence[0]["accepted"]["digest"]
        if retirement == "cancel":
            command(0,"cancel_direct_setup",setup_id=ready["setup_id"])
        elif retirement == "suspend":
            command(0,"mobile_lifecycle_transition",state="suspended",reason="controlled_test")
        else:
            member = next(item for item in command(1,"workspace_snapshot")["workspaces"] if item["id"] == workspace["id"])
            command(0,"remove_workspace_member",operation_id=op(),workspace_id=workspace["id"],member_id=member["local_member_id"])
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            diagnostic = call(0,"diagnostic")
            if diagnostic == {"native_count":0,"interfaces":0}:
                break
            time.sleep(.05)
        assert diagnostic == {"native_count":0,"interfaces":0}
    finally:
        for index, process in enumerate(processes):
            if process.is_alive():
                commands[index].put(("close",{}),timeout=2)
            process.join(8)
            if process.is_alive():
                process.terminate()
                process.join(3)
        for channel in pipes+commands+replies:
            channel.close()
            channel.cancel_join_thread()
    assert all(process.exitcode == 0 for process in processes)
