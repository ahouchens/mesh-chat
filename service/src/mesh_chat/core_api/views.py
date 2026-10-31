"""Explicitly selected public observations; domain dictionaries never escape."""

import math
import re

from ..chat_text import validate_chat_text
from ..models import DeliveryState, TrustState
from .messages import IDEMPOTENCY_SECONDS
from ..message_journal import RETENTION_SECONDS


ENUMS = {
    "desired": {"enabled", "stopped"},
    "execution": {"available", "paused", "locked", "shutting_down"},
    "negotiation": {"idle", "discover", "request", "wait_request", "wait_offer", "gather_offer",
                    "gather_answer", "publish_offer", "publish_answer", "wait_answer", "apply_answer",
                    "checking", "attach", "path", "inspect"},
    "carrier": {"absent", "open", "suspect", "closing"},
    "bridge": {"detached", "attaching", "path_pending", "ready", "restoring"},
}
REASONS = ENUMS["negotiation"] | {
    "unknown", "ineligible", "ready", "pending", "health_unknown", "bridge_retry_wait", "blocked",
    "retry_wait", "network_unavailable", "signaling_unavailable", "carrier_lost", "phase_timeout",
    "transient", "rate_limited", "configuration", "invalid_document", "revoked", "unsupported", "internal",
    "invalid_adoption", "wrong_resource", "missing_observation", "invalid_pending", "unverified_resource",
    "missing_carrier", "context_changed", "observed", "poll_wait", "idle",
}


def connection_view(value):
    selected = {}
    for field, choices in ENUMS.items():
        if value.get(field) not in choices:
            raise ValueError("Invalid internal observation")
        selected[field] = value[field]
    epoch, sequence = value.get("runtime_epoch"), value.get("sequence")
    if (not isinstance(epoch, str) or not 1 <= len(epoch) <= 64
            or type(sequence) is not int or not 0 <= sequence <= 9007199254740991):
        raise ValueError("Invalid observation cursor")
    selected.update(runtime_epoch=epoch, sequence=sequence)
    for field in ("retry_in", "evidence_age"):
        number = value.get(field)
        if field == "evidence_age" and number is None:
            selected[field] = None
            continue
        if type(number) not in {int, float} or not math.isfinite(number) or number < 0:
            raise ValueError("Invalid observation time")
        selected[field] = number
    ready = value.get("messaging_ready")
    if type(ready) is not bool or (ready and not (
            selected["desired"] == "enabled" and selected["execution"] == "available"
            and selected["carrier"] == "open" and selected["bridge"] == "ready"
            and selected["evidence_age"] is not None)):
        raise ValueError("Invalid readiness observation")
    selected["messaging_ready"] = ready
    selected["reason"] = value["reason"] if value.get("reason") in REASONS else "unknown"
    return selected


def _timestamp(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 9007199254740991:
        raise ValueError("Invalid message timestamp")
    return value


def acceptance_view(profile, value):
    if not isinstance(value.message, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value.message) is None:
        raise ValueError("Invalid message handle")
    accepted = _timestamp(value.accepted_at)
    expires = _timestamp(value.idempotency_expires_at)
    if expires != accepted + IDEMPOTENCY_SECONDS:
        raise ValueError("Invalid idempotency retention")
    return {"profile": profile, "message": value.message, "accepted": True,
            "accepted_at": accepted, "idempotency_expires_at": expires}


def acknowledgment_view(profile, value):
    if not isinstance(value.checkpoint, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value.checkpoint) is None:
        raise ValueError("Invalid checkpoint handle")
    accepted = _timestamp(value.acknowledged_at)
    expires = _timestamp(value.expires_at)
    if expires != accepted + RETENTION_SECONDS:
        raise ValueError("Invalid checkpoint retention")
    return {"profile": profile, "checkpoint": value.checkpoint, "acknowledged": True,
            "acknowledged_at": accepted, "expires_at": expires}


def message_view(profile, handle, recipient, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (handle, recipient)):
        raise ValueError("Invalid message observation handle")
    validate_chat_text(value.text)
    return {"profile": profile, "message": handle, "recipient": recipient, "kind": "text",
            "text": value.text, "state": DeliveryState(value.state).value,
            "created_at": _timestamp(value.created_at)}


def received_view(profile, handle, peer, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (handle, peer)):
        raise ValueError("Invalid received message handle")
    validate_chat_text(value.text)
    return {"profile": profile, "message": handle, "peer": peer, "kind": "text",
            "text": value.text, "state": DeliveryState(value.state).value,
            "created_at": _timestamp(value.created_at)}


def intent_view(profile, peer, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, peer)):
        raise ValueError("Invalid connection intent handle")
    if value.desired not in {"enabled", "stopped"} or type(value.active) is not bool:
        raise ValueError("Invalid connection intent observation")
    if value.active != (value.desired == "enabled"):
        raise ValueError("Connection intent observation is inconsistent")
    return {"profile": profile, "peer": peer, "desired": value.desired, "active": value.active}


def relationship_view(profile, peer, operation, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, peer)):
        raise ValueError("Invalid relationship handle")
    allowed = {"approved", "verified"} if operation == "peer.approve" else {"blocked"}
    if value.trust not in allowed:
        raise ValueError("Relationship observation does not match the operation")
    return {"profile": profile, "peer": peer, "trust": value.trust}


def peer_view(profile, handle, value):
    if (not isinstance(value.display_name, str) or not 1 <= len(value.display_name) <= 80
            or not isinstance(value.destination, str) or re.fullmatch(r"[a-f0-9]{32}", value.destination) is None):
        raise ValueError("Invalid peer observation")
    return {"profile": profile, "peer": handle, "display_name": value.display_name,
            "destination": value.destination, "trust": TrustState(value.trust).value}


def event_view(value):
    if (value.type not in {"message.changed", "message.removed"}
            or any(not isinstance(handle, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                   for handle in (value.identifier, value.message))
            or value.direction not in {"inbound", "outbound"}
            or (value.type == "message.removed" and value.state is not None)):
        raise ValueError("Invalid message event")
    state = DeliveryState(value.state).value if value.type == "message.changed" else None
    return {"id": value.identifier, "message": value.message, "type": value.type,
            "state": state, "timestamp": _timestamp(value.timestamp), "direction": value.direction}
