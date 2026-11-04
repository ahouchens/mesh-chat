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


def pairing_view(profile, peer, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, peer)):
        raise ValueError("Invalid pairing handle")
    if value.trust not in {"awaiting_consent", "pending_request", "approved", "verified"}:
        raise ValueError("Invalid pairing trust observation")
    return {"profile": profile, "peer": peer, "trust": value.trust}


def invitation_view(profile, value):
    if not isinstance(profile, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", profile) is None:
        raise ValueError("Invalid invitation profile handle")
    if (not isinstance(value.file, str) or not 1 <= len(value.file) <= 65536
            or not isinstance(value.link, str) or not 1 <= len(value.link) <= 65536
            or len(value.file) + len(value.link) > 200000
            or type(value.expires_at) not in {int, float} or not 0 < value.expires_at <= 9007199254740991):
        raise ValueError("Invalid invitation observation")
    return {"profile": profile, "file": value.file, "link": value.link,
            "expires_at": value.expires_at}


def workspace_preview_view(profile, value):
    if not isinstance(profile, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", profile) is None:
        raise ValueError("Invalid workspace preview handle")
    if (not isinstance(value.name, str) or not value.name
            or not isinstance(value.description, str)
            or type(value.member_count) is not int or value.member_count < 1
            or type(value.retention_days) is not int
            or type(value.expires_at) not in {int, float}
            or type(value.requires_i2p_consent) is not bool):
        raise ValueError("Invalid workspace preview")
    return {"profile": profile, "name": value.name, "description": value.description,
            "member_count": value.member_count, "retention_days": value.retention_days,
            "expires_at": value.expires_at, "requires_i2p_consent": value.requires_i2p_consent}


def workspace_join_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace join handle")
    if (not isinstance(value.name, str) or not value.name
            or value.state not in {"joining", "active", "pending", "left"}):
        raise ValueError("Invalid workspace join")
    return {"profile": profile, "workspace": workspace, "name": value.name,
            "state": value.state}


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


def stop_view(value):
    if value.stopping is not True or type(value.already_stopping) is not bool:
        raise ValueError("Invalid stop observation")
    return {"stopping": True, "already_stopping": value.already_stopping}


def pairing_request_view(profile, peer, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, peer)):
        raise ValueError("Invalid pairing request handle")
    if not isinstance(value.document, str) or not 1 <= len(value.document) <= 65536:
        raise ValueError("Invalid pairing request document")
    return {"profile": profile, "peer": peer, "state": "requested",
            "document": value.document}


WORKSPACE_ROLES = {"owner", "admin", "member"}
WORKSPACE_STATES = {"active", "joining", "linking", "left", "removed", "device_removed",
                    "revoked", "archived"}


def workspace_list_view(profile, items):
    if not isinstance(profile, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", profile) is None:
        raise ValueError("Invalid workspace profile handle")
    if len(items) > 16:
        raise ValueError("Workspace page is unbounded")
    workspaces = []
    for handle, value in items:
        if (re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                or not isinstance(value.name, str) or not value.name
                or value.role not in WORKSPACE_ROLES or value.state not in WORKSPACE_STATES):
            raise ValueError("Invalid workspace summary")
        workspaces.append({"workspace": handle, "name": value.name,
                           "role": value.role, "state": value.state})
    return {"profile": profile, "workspaces": workspaces}


def workspace_requests_view(profile, workspace, items):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace request handle")
    if len(items) > 32:
        raise ValueError("Join request page is unbounded")
    requests = []
    for handle, value in items:
        if (re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                or not isinstance(value.display_name, str) or not value.display_name
                or type(value.created_at) not in {int, float}):
            raise ValueError("Invalid join request summary")
        requests.append({"request": handle, "display_name": value.display_name,
                         "created_at": value.created_at})
    return {"profile": profile, "workspace": workspace, "requests": requests}


def workspace_approve_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace approval handle")
    if value.state not in WORKSPACE_STATES:
        raise ValueError("Invalid workspace approval state")
    return {"profile": profile, "workspace": workspace, "state": value.state}


def workspace_decline_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace decline handle")
    if value.state != "declined":
        raise ValueError("Invalid workspace decline state")
    return {"profile": profile, "workspace": workspace, "decision": "declined"}


def workspace_members_view(profile, workspace, items):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace member handle")
    if len(items) > 8:
        raise ValueError("Workspace member page is unbounded")
    members = []
    for handle, value in items:
        if (re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                or not isinstance(value.display_name, str) or not value.display_name
                or value.role not in WORKSPACE_ROLES
                or value.status not in {"active", "invited", "leaving", "left", "removed"}):
            raise ValueError("Invalid workspace member summary")
        members.append({"member": handle, "display_name": value.display_name,
                        "role": value.role, "status": value.status})
    return {"profile": profile, "workspace": workspace, "members": members}


def workspace_member_role_view(profile, workspace, member, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, member)):
        raise ValueError("Invalid workspace member role handle")
    if value.role not in {"admin", "member"}:
        raise ValueError("Invalid workspace member role")
    return {"profile": profile, "workspace": workspace, "member": member,
            "role": value.role}


def workspace_invitation_create_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace invitation handle")
    if (not isinstance(value.document, str) or not value.document
            or len(value.document.encode("utf-8")) > 1048576
            or not isinstance(value.link, str) or not value.link
            or len(value.link) > 1048576
            or value.connection_mode not in {None, "webrtc", "email", "i2p"}
            or (value.connection_mode == "i2p"
                and (not isinstance(value.i2p_access_point, str)
                     or not value.i2p_access_point))):
        raise ValueError("Invalid workspace invitation material")
    result = {"profile": profile, "workspace": workspace,
              "document": value.document, "link": value.link,
              "expires_at": _timestamp(value.expires_at)}
    if value.connection_mode is not None:
        result["connection_mode"] = value.connection_mode
    if value.i2p_access_point is not None:
        result["i2p_access_point"] = value.i2p_access_point
    return result


def workspace_channels_view(profile, workspace, items):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace channel handle")
    if len(items) > 32:
        raise ValueError("Workspace channel page is unbounded")
    channels = []
    for handle, value in items:
        if (re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                or not isinstance(value.name, str) or not value.name
                or value.visibility not in {"public", "private"}
                or value.state not in {"active", "archived", "left"}):
            raise ValueError("Invalid workspace channel summary")
        channels.append({"channel": handle, "name": value.name,
                         "visibility": value.visibility, "state": value.state})
    return {"profile": profile, "workspace": workspace, "channels": channels}


def workspace_channel_create_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace channel create handle")
    if (not isinstance(value.name, str) or not value.name
            or value.visibility not in {"public", "private"}
            or value.state not in {"active", "archived", "left"}):
        raise ValueError("Invalid created channel")
    return {"profile": profile, "workspace": workspace, "channel": value.channel,
            "name": value.name, "visibility": value.visibility}


def workspace_channel_members_view(profile, workspace, channel, members):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, channel)):
        raise ValueError("Invalid channel member handle")
    if not isinstance(members, list) or not 1 <= len(members) <= 8:
        raise ValueError("Invalid channel membership")
    if any(re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None for item in members):
        raise ValueError("Invalid channel member")
    return {"profile": profile, "workspace": workspace, "channel": channel,
            "members": members}


def workspace_channel_update_view(profile, workspace, channel, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, channel)):
        raise ValueError("Invalid channel update handle")
    if (not isinstance(value.name, str) or not value.name
            or not isinstance(value.topic, str)
            or value.visibility not in {"public", "private"}):
        raise ValueError("Invalid channel update")
    posting = getattr(value, "posting", None)
    if posting not in {None, "all_members", "owner_and_admins"}:
        raise ValueError("Invalid channel posting policy")
    return {"profile": profile, "workspace": workspace, "channel": channel,
            "name": value.name, "topic": value.topic, "visibility": value.visibility,
            "posting": posting}


def workspace_channel_archive_view(profile, workspace, channel, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, channel)):
        raise ValueError("Invalid channel archive handle")
    if value.state != "archived":
        raise ValueError("Invalid channel archive state")
    return {"profile": profile, "workspace": workspace, "channel": channel,
            "state": "archived"}


def device_link_create_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid device link handle")
    if (not isinstance(value.document, str) or not 1 <= len(value.document) <= 65536
            or not isinstance(value.link, str) or not 1 <= len(value.link) <= 65536
            or type(value.expires_at) not in {int, float}):
        raise ValueError("Invalid device link")
    return {"profile": profile, "workspace": workspace, "document": value.document,
            "link": value.link, "expires_at": value.expires_at}


def device_link_preview_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid device link preview handle")
    if (not isinstance(value.name, str) or not value.name
            or not isinstance(value.member_display_name, str) or not value.member_display_name
            or type(value.device_count) is not int or not 1 <= value.device_count <= 24
            or type(value.expires_at) not in {int, float}):
        raise ValueError("Invalid device link preview")
    return {"profile": profile, "workspace": workspace, "name": value.name,
            "member_display_name": value.member_display_name,
            "device_count": value.device_count, "expires_at": value.expires_at}


def device_link_submit_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid device link submission handle")
    if (not isinstance(value.name, str) or not value.name
            or value.state != "linking"):
        raise ValueError("Invalid device link submission")
    return {"profile": profile, "workspace": workspace, "name": value.name,
            "state": "linking"}


def device_links_view(profile, workspace, links):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid device link request handle")
    if len(links) > 24:
        raise ValueError("Device link request page is unbounded")
    for handle in links:
        if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None:
            raise ValueError("Invalid device link request")
    return {"profile": profile, "workspace": workspace,
            "links": [{"request": handle, "state": "pending"} for handle in links]}


def device_link_decision_view(profile, workspace, link, state):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, link)):
        raise ValueError("Invalid device link decision handle")
    if state not in {"approved", "declined"}:
        raise ValueError("Invalid device link decision")
    return {"profile": profile, "workspace": workspace, "link": link, "state": state}


def workspace_channel_transfer_offer_view(profile, workspace, channel, member):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, channel, member)):
        raise ValueError("Invalid channel transfer offer handle")
    return {"profile": profile, "workspace": workspace, "channel": channel,
            "member": member, "state": "offered"}


def workspace_channel_transfer_accept_view(profile, workspace, channel):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, channel)):
        raise ValueError("Invalid channel transfer accept handle")
    return {"profile": profile, "workspace": workspace, "channel": channel,
            "state": "accepted"}


def workspace_policies_view(profile, workspace, value):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace policy handle")
    if (value.channel_creation not in {"all_members", "owner_and_admins"}
            or value.posting not in {"all_members", "owner_and_admins"}
            or value.invitation_requests not in {"owner_only", "owner_and_admins",
                                                 "all_members_request"}):
        raise ValueError("Invalid workspace policy")
    return {"profile": profile, "workspace": workspace,
            "channel_creation": value.channel_creation, "posting": value.posting,
            "invitation_requests": value.invitation_requests}


def workspace_devices_view(profile, workspace, items):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace)):
        raise ValueError("Invalid workspace device handle")
    if len(items) > 48:
        raise ValueError("Workspace device page is unbounded")
    devices = []
    for handle, value in items:
        if (re.fullmatch(r"[A-Za-z0-9_-]{16,128}", handle) is None
                or not isinstance(value.current, bool)):
            raise ValueError("Invalid workspace device")
        devices.append({"device": handle, "member": value.member,
                        "current": value.current})
    return {"profile": profile, "workspace": workspace, "devices": devices}


def workspace_device_remove_view(profile, workspace, device, state):
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", item) is None
           for item in (profile, workspace, device)):
        raise ValueError("Invalid workspace device removal handle")
    if state != "removed":
        raise ValueError("Invalid workspace device removal state")
    return {"profile": profile, "workspace": workspace, "device": device,
            "state": "removed"}
