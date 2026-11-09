"""Scoped application requests after trusted host authentication.

This module does not authenticate IPC peers. A host must bind the authorizer to
an authenticated connection; callers never choose that function or its grants.
"""

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import hashlib
import hmac
import json
import re
from threading import RLock
import uuid
from typing import Protocol

from .views import (call_ice_view, call_media_view, call_settings_view, device_removal_view, draft_view,
    workspace_admin_request_view, workspace_authority_loss_view, workspace_authority_offer_view,
    workspace_edge_view,
    workspace_authority_view, workspace_lifecycle_view,
    workspace_metadata_view, workspace_retention_view,
    group_invitation_decision_view,
    group_list_view, group_membership_view,
    group_message_sent_view, group_view, network_settings_view, reaction_view,
    peer_delete_view, peer_trust_view,
    acceptance_view, acknowledgment_view, connection_view, event_view, intent_view, message_view,
    invitation_view, pairing_request_view, pairing_view, peer_view, received_view,
    relationship_view, stop_view, workspace_approve_view, workspace_decline_view,
    device_link_create_view, device_link_decision_view, device_link_preview_view,
    device_link_submit_view, device_links_view,
    workspace_channel_archive_view,
    workspace_channel_create_view, workspace_channel_transfer_accept_view,
    workspace_device_remove_view, workspace_devices_view, workspace_policies_view,
    workspace_channel_transfer_offer_view,
    workspace_channel_members_view,
    workspace_channel_update_view, workspace_channels_view, workspace_join_view,
    workspace_list_view, workspace_member_role_view, workspace_members_view,
    workspace_invitation_create_view, workspace_preview_view, workspace_requests_view,
)
from .errors import ApiFailure
from .limits import MAX_FRAME_BYTES, MAX_REQUEST_JSON_DEPTH, MAX_REQUEST_JSON_TOKENS
from .diagnostics import Diagnostics, MAX_DIAGNOSTICS, MAX_DIAGNOSTIC_BYTES
from .diagnostic_views import diagnostics_view
from .requests import (
    CURSOR, DIAGNOSTIC_OPERATIONS, INTENT_OPERATIONS, MESSAGE_OPERATIONS, OPERATIONS,
    INVITATION_OPERATIONS, PAIRING_OPERATIONS, PAIRING_PREVIEW_OPERATIONS, CONTACT_INVITATION_OPERATIONS, RECEIVED_OPERATIONS, RECOVERY_OPERATIONS, RECOVERY_TRANSFER_OPERATIONS,
    APPLICATION_OPERATIONS, CALL_OPERATIONS, CALL_CONTROL_OPERATIONS, COMPONENT_OPERATIONS, DRAFT_OPERATIONS,
    GROUP_OPERATIONS, GROUP_DRAFT_OPERATIONS, REACTION_OPERATIONS, RELATIONSHIP_OPERATIONS, SETTINGS_OPERATIONS, REQUEST_OPERATIONS, STOP_OPERATIONS,
    WORKSPACE_APPROVE_OPERATIONS, WORKSPACE_DECLINE_OPERATIONS, WORKSPACE_JOIN_OPERATIONS, WORKSPACE_PROMPT_JOIN_OPERATIONS,
    WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS, WORKSPACE_CHANNEL_CREATE_OPERATIONS,
    WORKSPACE_CHANNEL_MEMBERS_OPERATIONS,
    WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS, WORKSPACE_CHANNEL_UPDATE_OPERATIONS,
    WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS, WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS,
    WORKSPACE_CHANNEL_RECOVER_OPERATIONS, WORKSPACE_CHANNEL_STATE_OPERATIONS, WORKSPACE_MEMBER_REMOVE_OPERATIONS, WORKSPACE_DRAFT_OPERATIONS, REMOTE_PROFILE_OPERATIONS, REMOTE_PROFILE_QUERY_OPERATIONS, WORKSPACE_DISPLAY_DECIDE_OPERATIONS, WORKSPACE_DIRECT_OPEN_OPERATIONS, ROUTE_UPDATE_OPERATIONS, CONVERSATION_OPERATIONS, LINK_PREVIEW_OPERATIONS, CONNECTION_SUPPORT_OPERATIONS, CONNECTION_DOCUMENT_OPERATIONS,
    WORKSPACE_POLICY_UPDATE_OPERATIONS, WORKSPACE_METADATA_OPERATIONS,
    WORKSPACE_RETENTION_OPERATIONS, WORKSPACE_ADMIN_REQUEST_OPERATIONS, WORKSPACE_LIFECYCLE_OPERATIONS, WORKSPACE_AUTHORITY_LOSS_OPERATIONS, WORKSPACE_AUTHORITY_OPERATIONS, WORKSPACE_AUTHORITY_OFFER_OPERATIONS, WORKSPACE_EDGE_OPERATIONS, WORKSPACE_ADMISSION_OPERATIONS, WORKSPACE_TIMELINE_OPERATIONS, WORKSPACE_SNAPSHOT_OPERATIONS, WORKSPACE_ACCESS_OPERATIONS, WORKSPACE_HISTORY_OPERATIONS, WORKSPACE_CONNECTION_OPERATIONS, RUNTIME_QUERY_OPERATIONS, RUNTIME_MUTATION_OPERATIONS, WORKSPACE_DEVICES_OPERATIONS,
    WORKSPACE_DEVICE_REMOVE_OPERATIONS,
    WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS,
    WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS, WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS, WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS,
    WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS, WORKSPACE_DEVICE_LINKS_OPERATIONS,
    WORKSPACE_OPERATIONS, WORKSPACE_QUERY_OPERATIONS,
    WORKSPACE_ACCESS_MUTATION_OPERATIONS,
    WORKSPACE_CHANNELS_OPERATIONS, WORKSPACE_LIST_OPERATIONS, WORKSPACE_MEMBERS_OPERATIONS,
    WORKSPACE_INVITATION_CREATE_OPERATIONS,
    WORKSPACE_PREVIEW_OPERATIONS,
    WORKSPACE_REQUESTS_OPERATIONS, WORKSPACE_ROLE_OPERATIONS, REQUEST_ID, parse_request,
)
from .messages import (
    IDEMPOTENCY_SECONDS, MAX_CALLER_ENQUEUES, MAX_PEERS, MAX_VAULT_ENQUEUES,
    MessageScope, Messages,
)
from .intent import ConnectionIntent
from .invitations import Invitations
from .lifecycle import Lifecycle
from .workspace_admin import ChannelSummary, DeviceSummary, WorkspaceAdmin
from .workspace_relationship import WorkspaceRelationships
from .pairing import Pairing
from .relationship import Relationship
from .recovery import (
    MAX_BATCH, MAX_BATCH_BYTES, MAX_CALLER_ACKNOWLEDGMENTS, MAX_CURSOR_BYTES,
    MAX_VAULT_ACKNOWLEDGMENTS, ReceivedLog, Recovery,
)
from ..message_journal import MAX_EVENTS, RETENTION_SECONDS


MAX_PROFILES = 256
MAX_CONNECTIONS = 256


PERMISSION_BY_OPERATION = {
    "connection.snapshot": "observe",
    "connection.start": "connect",
    "connection.stop": "connect",
    "diagnostics.query": "diagnose",
    "events.ack": "read",
    "events.poll": "read",
    "message.enqueue": "send",
    "message.list": "read",
    "recovery.transfer": "send",
    "message.query": "read",
    "message.received": "read",
    "peer.approve": "approve",
    "peer.pairing_accept": "pair",
    "peer.pairing_preview": "pair",
    "peer.pairing_create": "pair",
    "peer.pairing_request": "pair",
    "peer.query": "observe",
    "peer.revoke": "approve",
    "peer.unblock": "approve",
    "peer.delete": "approve",
    "peer.update": "send",
    "peer.decide": "approve",
    "contact.invitation": "send",
    "peer.draft_get": "read",
    "peer.draft_set": "send",
    "call.settings_query": "read",
    "call.settings_update": "send",
    "call.ice_servers": "read",
    "call.media_query": "read",
    "call.control": "send",
    "settings.query": "read",
    "settings.update": "send",
    "message.reaction_set": "send",
    "group.query": "read",
    "group.draft_set": "send",
    "group.create": "send",
    "group.message_enqueue": "send",
    "group.leave": "send",
    "group.close": "send",
    "group.member_remove": "send",
    "group.invitation_accept": "send",
    "group.invitation_decline": "send",
    "group.invitation_retry": "send",
    "profile.query": "observe",
    "application.snapshot": "approve",
    "application.command": "approve",
    "runtime.capabilities": "observe",
    "runtime.stop": "runtime_owner",
    "workspace.channel_archive": "approve",
    "workspace.channel_recover": "approve",
    "workspace.channel_state": "send",
    "workspace.member_remove": "approve",
    "workspace.draft_set": "send",
    "remote_profile.mutate": "send",
    "remote_profile.query": "read",
    "workspace.display_name_decide": "approve",
    "workspace.direct_open": "send",
    "route.update": "send",
    "conversation.mutate": "send",
    "link.preview": "send",
    "connection.support": "send",
    "connection.document": "send",
    "workspace.channel_create": "approve",
    "workspace.channel_members": "approve",
    "workspace.channel_members_update": "approve",
    "workspace.channel_transfer_accept": "approve",
    "workspace.channel_transfer_offer": "approve",
    "workspace.channel_update": "approve",
    "workspace.channels": "approve",
    "workspace.device_link_approve": "approve",
    "workspace.device_link_create": "pair",
    "workspace.device_link_decline": "approve",
    "workspace.device_link_preview": "pair",
    "workspace.device_link_submit": "pair",
    "workspace.device_links": "approve",
    "workspace.device_remove": "approve",
    "workspace.device_removal_request": "send",
    "workspace.device_removal_approve": "approve",
    "workspace.device_removal_decline": "approve",
    "workspace.devices": "approve",
    "workspace.invitation_preview": "read",
    "workspace.join": "pair",
    "workspace.join_prompt": "pair",
    "workspace.join_approve": "approve",
    "workspace.join_decline": "approve",
    "workspace.join_requests": "approve",
    "workspace.member_role": "approve",
    "workspace.invitation_create": "approve",
    "workspace.members": "approve",
    "workspace.policy_update": "approve",
    "workspace.metadata_update": "approve",
    "workspace.retention_update": "approve",
    "workspace.admin_request_approve": "approve",
    "workspace.admin_request_decline": "approve",
    "workspace.admin_request_cancel": "send",
    "workspace.admin_request_dismiss": "send",
    "workspace.close": "approve",
    "workspace.leave": "send",
    "workspace.remove_data": "approve",
    "workspace.authority_loss_report": "approve",
    "workspace.authority_accept": "approve",
    "workspace.authority_finalize": "approve",
    "workspace.authority_offer": "approve",
    "workspace.invitation_revoke": "approve",
    "workspace.admin_request_submit": "send",
    "workspace.display_name_request": "send",
    "workspace.read_hint_sync": "send",
    "workspace.admission_grant_list": "read",
    "workspace.admission_grant_create": "approve",
    "workspace.admission_grant_accept": "approve",
    "workspace.admission_grant_end": "approve",
    "runtime.query": "read",
    "runtime.mutate": "send",
    "workspace.snapshot": "read",
    "workspace.access_recommendation": "send",
    "workspace.history": "send",
    "workspace.connection": "send",
    "workspace.timeline_query": "read",
    "workspace.timeline_mutation": "send",
    "workspace.query": "read",
}


@dataclass(frozen=True)
class Grant:
    caller: str
    permissions: frozenset[str]
    profiles: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.caller, str) or not 1 <= len(self.caller) <= 256
                or type(self.permissions) is not frozenset or type(self.profiles) is not tuple
                or len(self.profiles) > MAX_PROFILES or len(set(self.profiles)) != len(self.profiles)
                or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in self.profiles)):
            raise ValueError("Invalid trusted caller grant")


@dataclass(frozen=True)
class ProfileObservation:
    display_name: str
    destination: str
    connections: dict[str, dict]


class Observations(Protocol):
    def profile(self, internal_profile: str) -> ProfileObservation: ...


@dataclass(frozen=True)
class Ports:
    """Optional capability ports bound by the trusted composition."""

    messages: Messages | None = None
    recovery: Recovery | None = None
    diagnostics: Diagnostics | None = None
    received: ReceivedLog | None = None
    intent: ConnectionIntent | None = None
    relationship: Relationship | None = None
    pairing: Pairing | None = None
    invitations: Invitations | None = None
    lifecycle: Lifecycle | None = None
    workspace: WorkspaceRelationships | None = None
    workspace_admin: WorkspaceAdmin | None = None
    workspace_timeline: object | None = None
    runtime: object | None = None
    application: object | None = None
    drafts: object | None = None
    calls: object | None = None
    settings: object | None = None
    reactions: object | None = None
    groups: object | None = None


class CoreSession:
    def __init__(self, authorize, observations: Observations, *, handle_key: bytes, transaction=None,
                 ports: Ports | None = None):
        if not isinstance(handle_key, bytes) or not 32 <= len(handle_key) <= 64:
            raise ValueError("A protected handle key is required")
        ports = ports or Ports()
        self._authorize = authorize
        self._observations = observations
        self._messages = ports.messages
        self._recovery = ports.recovery
        self._diagnostics = ports.diagnostics
        self._received = ports.received
        self._intent = ports.intent
        self._relationship = ports.relationship
        self._pairing = ports.pairing
        self._invitations = ports.invitations
        self._lifecycle = ports.lifecycle
        self._workspace = ports.workspace
        self._workspace_admin = ports.workspace_admin
        self._workspace_timeline = ports.workspace_timeline
        self._runtime = ports.runtime
        self._application = ports.application
        self._drafts = ports.drafts
        self._calls = ports.calls
        self._settings = ports.settings
        self._reactions = ports.reactions
        self._groups = ports.groups
        self._stopped = False
        bound = set(OPERATIONS)
        for operations, port in (
            (MESSAGE_OPERATIONS, self._messages),
            (RECOVERY_OPERATIONS, self._recovery),
            (RECOVERY_TRANSFER_OPERATIONS, self._recovery),
            (RECEIVED_OPERATIONS, self._received),
            (INTENT_OPERATIONS, self._intent),
            (RELATIONSHIP_OPERATIONS, self._relationship),
            (DRAFT_OPERATIONS, self._drafts),
            (CALL_OPERATIONS, self._calls),
            (CALL_CONTROL_OPERATIONS, self._calls),
            (SETTINGS_OPERATIONS, self._settings),
            (REACTION_OPERATIONS, self._reactions),
            (GROUP_OPERATIONS, self._groups),
            (GROUP_DRAFT_OPERATIONS, self._groups),
            (PAIRING_OPERATIONS, self._pairing),
            (PAIRING_PREVIEW_OPERATIONS, self._pairing),
            (CONTACT_INVITATION_OPERATIONS, self._pairing),
            (REQUEST_OPERATIONS, self._pairing),
            (INVITATION_OPERATIONS, self._invitations),
            (STOP_OPERATIONS, self._lifecycle),
            (APPLICATION_OPERATIONS, self._application),
            (WORKSPACE_PREVIEW_OPERATIONS, self._workspace),
            (WORKSPACE_JOIN_OPERATIONS, self._workspace),
            (WORKSPACE_PROMPT_JOIN_OPERATIONS, self._workspace),
            (WORKSPACE_LIST_OPERATIONS, self._workspace_admin),
            (WORKSPACE_REQUESTS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_APPROVE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DECLINE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_MEMBERS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_ROLE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_INVITATION_CREATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNELS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_CREATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_MEMBERS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_UPDATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_RECOVER_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_STATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_MEMBER_REMOVE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DRAFT_OPERATIONS, self._workspace_admin),
            (REMOTE_PROFILE_OPERATIONS, self._workspace_admin),
            (REMOTE_PROFILE_QUERY_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DISPLAY_DECIDE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DIRECT_OPEN_OPERATIONS, self._workspace_admin),
            (ROUTE_UPDATE_OPERATIONS, self._workspace_admin),
            (CONVERSATION_OPERATIONS, self._workspace_admin),
            (LINK_PREVIEW_OPERATIONS, self._workspace_admin),
            (CONNECTION_SUPPORT_OPERATIONS, self._workspace_admin),
            (CONNECTION_DOCUMENT_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINKS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS, self._workspace_admin),
            (WORKSPACE_POLICY_UPDATE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_METADATA_OPERATIONS, self._workspace_admin),
            (WORKSPACE_RETENTION_OPERATIONS, self._workspace_admin),
            (WORKSPACE_ADMIN_REQUEST_OPERATIONS, self._workspace_admin),
            (WORKSPACE_LIFECYCLE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_AUTHORITY_LOSS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_AUTHORITY_OPERATIONS, self._workspace_admin),
            (WORKSPACE_AUTHORITY_OFFER_OPERATIONS, self._workspace_admin),
            (WORKSPACE_EDGE_OPERATIONS, self._workspace_admin),
            (WORKSPACE_ADMISSION_OPERATIONS, self._workspace_admin),
            (WORKSPACE_TIMELINE_OPERATIONS, self._workspace_timeline),
            (WORKSPACE_SNAPSHOT_OPERATIONS, self._workspace_admin),
            (RUNTIME_QUERY_OPERATIONS, self._runtime),
            (RUNTIME_MUTATION_OPERATIONS, self._runtime),
            (WORKSPACE_ACCESS_OPERATIONS, self._workspace_admin),
            (WORKSPACE_HISTORY_OPERATIONS, self._workspace_admin),
            (WORKSPACE_CONNECTION_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICES_OPERATIONS, self._workspace_admin),
            (WORKSPACE_DEVICE_REMOVE_OPERATIONS, self._workspace_admin),
            (DIAGNOSTIC_OPERATIONS, self._diagnostics),
        ):
            if port is not None:
                bound.update(operations)
        self._operations = tuple(name for name in COMPONENT_OPERATIONS if name in bound)
        self._handle_key = handle_key
        self._transaction = transaction if transaction is not None else nullcontext()
        self._lock = RLock()
        self._caller = None
        self._negotiated = False
        self._closed = False

    def request(self, value):
        request_id = value.get("request_id") if isinstance(value, dict) else None
        if not isinstance(request_id, str) or REQUEST_ID.fullmatch(request_id) is None:
            request_id = None
        with self._lock, self._transaction:
            try:
                if self._stopped:
                    raise ApiFailure("forbidden")
                grant = self._grant()
                operation, params = parse_request(value, self._operations)
                key = value.get("idempotency_key") if isinstance(value, dict) else None
                if key is not None and operation not in {"message.enqueue", "events.ack",
                                                        "workspace.join",
                                                        "workspace.join_approve",
                                                        "workspace.join_decline",
                                                        "workspace.member_role",
                                                        "workspace.invitation_create",
                                                        "workspace.channel_create",
                                                        "workspace.channel_members_update",
                                                        "workspace.channel_update",
                                                        "workspace.channel_archive",
                                                        "workspace.device_link_create",
                                                        "workspace.device_link_submit",
                                                        "workspace.device_link_approve",
                                                        "workspace.device_link_decline",
                                                        "workspace.channel_transfer_offer",
                                                        "workspace.channel_transfer_accept",
                                                        "workspace.policy_update",
                                                        "workspace.device_remove"}:
                    raise ApiFailure("invalid_request")
                permission = PERMISSION_BY_OPERATION.get(operation)
                if permission is None:
                    raise ApiFailure("forbidden")
                if permission not in grant.permissions:
                    raise ApiFailure("forbidden")
                result = self._execute(grant, operation, params, key)
                return {"api_version": 1, "request_id": request_id, "ok": True, "result": result}
            except ApiFailure as error:
                code = error.code
            except Exception:
                code = "internal"
        return {"api_version": 1, "request_id": request_id, "ok": False,
                "error": {"code": code, "retry_after_ms": None}}

    @property
    def stopped(self):
        return self._stopped

    def detach(self):
        with self._lock:
            self._closed = True
            self._negotiated = False

    def _grant(self):
        if self._closed:
            raise ApiFailure("unauthenticated")
        grant = self._authorize()
        if not isinstance(grant, Grant) or (self._caller is not None and grant.caller != self._caller):
            self._closed = True
            raise ApiFailure("unauthenticated")
        self._caller = grant.caller
        return grant

    def _handle(self, grant, kind, profile, internal):
        material = json.dumps([grant.caller, kind, profile, internal], ensure_ascii=True,
                              separators=(",", ":")).encode("ascii")
        return hmac.new(self._handle_key, b"mesh-core-handle:v1:" + material, hashlib.sha256).hexdigest()

    def _operation_id(self, grant, profile, key):
        material = json.dumps([grant.caller, profile, key], ensure_ascii=True,
                              separators=(",", ":")).encode("ascii")
        digest = hmac.new(self._handle_key, b"mesh-core-operation:v1:" + material,
                          hashlib.sha256).digest()[:16]
        return str(uuid.UUID(bytes=digest))

    def _group_identifier(self, grant, profile, handle):
        group_id = next(
            (item.group_id for item in self._groups.list(profile)
             if self._handle(grant, "group", profile, item.group_id) == handle),
            None)
        if group_id is None:
            raise ApiFailure("forbidden")
        return group_id

    def _owner_snapshot(self, grant, snapshot):
        if not isinstance(snapshot, dict) or len(grant.profiles) != 1:
            return snapshot
        profile = grant.profiles[0]
        result = dict(snapshot)
        for key, kind in (("contacts", "peer"), ("groups", "group"),
                          ("group_invitations", "group_invitation"),
                          ("workspace_join_requests", "workspace_join_request"),
                          ("calls", "call"),
                          ("workspace_channels", "channel"),
                          ("workspace_device_transitions", "device_link"),
                          ("workspace_admin_requests", "workspace_admin_request"),
                          ("workspace_authority_transitions", "authority_transition"),
                          ("workspaces", "workspace")):
            values = result.get(key)
            if isinstance(values, list):
                result[key] = [self._snapshot_item(grant, kind, profile, item)
                               for item in values if isinstance(item, dict)]
        return result

    def _snapshot_item(self, grant, kind, profile, item):
        identifier = item.get("id")
        if not isinstance(identifier, str):
            return item
        handled = dict(item)
        handled["core_handle"] = self._handle(grant, kind, profile, identifier)
        if kind == "workspace" and isinstance(item.get("members"), list):
            members = []
            for member in item["members"]:
                if not isinstance(member, dict):
                    continue
                handled_member = self._snapshot_handle(grant, "member", profile, member)
                if isinstance(member.get("devices"), list):
                    handled_member["devices"] = [
                        self._snapshot_handle(grant, "device", profile, device)
                        for device in member["devices"] if isinstance(device, dict)]
                members.append(handled_member)
            handled["members"] = members
        return handled

    def _snapshot_handle(self, grant, kind, profile, item):
        identifier = item.get("id")
        if not isinstance(identifier, str):
            return item
        handled = dict(item)
        handled["core_handle"] = self._handle(grant, kind, profile, identifier)
        return handled

    def _workspace_channel_scope(self, grant, profiles, params):
        target, inside = self._workspace_scope(grant, profiles, params)
        return target, inside, self._channel_target(
            grant, target, inside, params["channel"])

    def _profile_target(self, profiles, params):
        target = profiles.get(params["profile"])
        if target is None:
            raise ApiFailure("forbidden")
        return target

    def _workspace_scope(self, grant, profiles, params):
        target = self._profile_target(profiles, params)
        return target, self._workspace_target(grant, target, params["workspace"])

    def _required_operation_id(self, grant, target, key):
        if key is None:
            raise ApiFailure("invalid_request")
        return self._operation_id(grant, target, key)

    def _execute(self, grant, operation, params, key=None):
        profiles = {self._handle(grant, "profile", profile, profile): profile for profile in grant.profiles}
        if operation == "runtime.capabilities":
            self._negotiated = True
            return self._capabilities(profiles)
        if not self._negotiated:
            raise ApiFailure("negotiation_required")
        if operation in WORKSPACE_OPERATIONS:
            return self._workspace_operation(grant, profiles, operation, params, key)
        if operation in STOP_OPERATIONS:
            result = stop_view(self._lifecycle.stop())
            self._stopped = True
            return result
        if operation in APPLICATION_OPERATIONS:
            if self._application is None:
                raise ApiFailure("unavailable")
            if operation == "application.snapshot":
                return self._owner_snapshot(grant, self._application.snapshot())
            return self._application.command(params["command"], params["payload"])
        profile = self._profile_target(profiles, params)
        if operation == "diagnostics.query":
            return diagnostics_view(params["profile"], self._diagnostics.query(profile), params["limit"],
                                    lambda internal: self._handle(grant, "connection", profile, internal))
        if operation in MESSAGE_OPERATIONS:
            return self._message(grant, profile, operation, params, key)
        if operation in RECEIVED_OPERATIONS:
            return self._received_messages(grant, profile, params)
        if operation in INTENT_OPERATIONS:
            return self._intent_operation(grant, profile, operation, params)
        if operation in GROUP_DRAFT_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            group_id = next(
                (item.group_id for item in self._groups.list(target)
                 if self._handle(grant, "group", target, item.group_id)
                 == params["group"]), None)
            if group_id is None:
                raise ApiFailure("forbidden")
            state = self._groups.save_draft(target, group_id, params["text"])
            return {"state": state}
        if operation in GROUP_OPERATIONS:
            if operation in {"group.invitation_accept", "group.invitation_decline"}:
                invitation_id = next(
                    (item.invitation_id for item in self._groups.invitations(profile)
                     if self._handle(grant, "group_invitation", profile, item.invitation_id)
                     == params["invitation"]),
                    None)
                if invitation_id is None:
                    raise ApiFailure("forbidden")
                if operation == "group.invitation_accept":
                    observation = self._groups.accept_invitation(profile, invitation_id)
                else:
                    observation = self._groups.decline_invitation(profile, invitation_id)
                return group_invitation_decision_view(
                    params["profile"], params["invitation"], observation)
            if operation in {"group.leave", "group.close", "group.member_remove",
                             "group.invitation_retry"}:
                group_id = self._group_identifier(grant, profile, params["group"])
                if operation in {"group.member_remove", "group.invitation_retry"}:
                    contact_id = self._peers(grant, profile).get(params["member"])
                    if contact_id is None:
                        raise ApiFailure("forbidden")
                    if operation == "group.invitation_retry":
                        observation = self._groups.retry_invitation(
                            profile, group_id, contact_id)
                    else:
                        observation = self._groups.remove(profile, group_id, contact_id)
                elif operation == "group.leave":
                    observation = self._groups.leave(profile, group_id)
                else:
                    observation = self._groups.close(profile, group_id)
                return group_membership_view(params["profile"], params["group"], observation)
            if operation == "group.message_enqueue":
                group_id = self._group_identifier(grant, profile, params["group"])
                observation = self._groups.send(profile, group_id, params["text"])
                return group_message_sent_view(params["profile"], params["group"],
                                               observation)
            if operation == "group.create":
                contacts = [self._peers(grant, profile).get(handle)
                            for handle in params["members"]]
                if any(contact is None for contact in contacts):
                    raise ApiFailure("forbidden")
                observation = self._groups.create(
                    profile, params["title"], contacts, params["posting_policy"])
                return group_view(
                    params["profile"],
                    self._handle(grant, "group", profile, observation.group_id),
                    observation)
            return group_list_view(
                params["profile"],
                [(self._handle(grant, "group", profile, item.group_id), item)
                 for item in self._groups.list(profile)])
        if operation in REACTION_OPERATIONS:
            observation = self._reactions.set(
                MessageScope(grant.caller, profile), params["message"],
                params["emoji"], params["active"])
            return reaction_view(params["profile"], params["message"], observation)
        if operation in SETTINGS_OPERATIONS:
            if operation == "settings.update":
                observation = self._settings.update(profile, params["settings"])
            else:
                observation = self._settings.get(profile)
            return network_settings_view(params["profile"], observation)
        if operation in CALL_OPERATIONS:
            if operation == "call.settings_update":
                observation = self._calls.update(profile, params["settings"])
            elif operation == "call.ice_servers":
                return call_ice_view(params["profile"], self._calls.ice(profile))
            elif operation == "call.control":
                return {"profile": params["profile"], "result": self._calls.control(
                    profile, params["action"], params)}
            elif operation == "call.media_query":
                call_id = next(
                    (item for item in self._calls.call_ids(profile)
                     if self._handle(grant, "call", profile, item) == params["call"]),
                    None)
                if call_id is None:
                    raise ApiFailure("forbidden")
                return call_media_view(
                    params["profile"], params["call"], self._calls.media(profile, call_id))
            else:
                observation = self._calls.get(profile)
            return call_settings_view(params["profile"], observation)
        if operation in DRAFT_OPERATIONS:
            contact = self._peers(grant, profile).get(params["peer"])
            if contact is None:
                raise ApiFailure("forbidden")
            if operation == "peer.draft_set":
                observation = self._drafts.set(profile, contact, params["text"])
            else:
                observation = self._drafts.get(profile, contact)
            return draft_view(params["profile"], params["peer"], observation)
        if operation in RELATIONSHIP_OPERATIONS:
            return self._relationship_operation(grant, profile, operation, params)
        if operation in CONTACT_INVITATION_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            result = self._pairing.contact_invitation(
                target, params["action"], params)
            return {"contact_invitation": result}
        if operation in PAIRING_PREVIEW_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._pairing.preview_invitation(target, params["document"])
        if operation in PAIRING_OPERATIONS:
            return self._pairing_operation(grant, profile, params)
        if operation in REQUEST_OPERATIONS:
            return self._pairing_request_operation(grant, profile, params)
        if operation in INVITATION_OPERATIONS:
            return self._invitation_operation(grant, profile, params)
        if operation in RECOVERY_TRANSFER_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._recovery.transfer(target, params["action"], params)
        if operation in RECOVERY_OPERATIONS:
            return self._recover(grant, profile, operation, params, key)
        return self._observe(grant, profile, operation, params)

    def _workspace_operation(self, grant, profiles, operation, params, key):
        if operation == "workspace.invitation_revoke":
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            invitation_id = next(
                (item for item in self._workspace_admin.invitation_ids(target, inside)
                 if self._handle(grant, "workspace_invitation", target, item)
                 == params["invitation"]), None)
            if invitation_id is None:
                raise ApiFailure("forbidden")
            state = self._workspace_admin.revoke_invitation(
                target, inside, invitation_id, operation_id)
            return {"profile": params["profile"], "workspace": params["workspace"],
                    "invitation": params["invitation"], "state": state}
        if operation in WORKSPACE_CONNECTION_OPERATIONS:
            target = self._profile_target(profiles, params)
            inside = (self._workspace_target(grant, target, params[workspace])
                      if workspace in params else None)
            operation_id = (self._required_operation_id(grant, target, key)
                            if params[action] in {prompt_submit} else None)
            result = self._workspace_admin.connection(
                target, inside, params[action], params, operation_id)
            view = {profile: params[profile], result: result}
            if inside is not None:
                view[workspace] = params[workspace]
            return view
        if operation in WORKSPACE_HISTORY_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = (self._required_operation_id(grant, target, key)
                            if params[action] in {prune, hide_message, hide_direct} else None)
            result = self._workspace_admin.history(
                target, inside, params[action], params, operation_id)
            return {profile: params[profile], workspace: params[workspace],
                    result: result}
        if operation in WORKSPACE_ACCESS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = (self._required_operation_id(grant, target, key)
                            if params[action] == send else None)
            result = self._workspace_admin.access_recommendation(
                target, inside, params[action], params, operation_id)
            return {profile: params[profile], workspace: params[workspace],
                    result: result}
        if operation in RUNTIME_QUERY_OPERATIONS:
            target = self._profile_target(profiles, params)
            result = self._runtime.query(target, params[action])
            return {profile: params[profile], result: result}
        if operation in RUNTIME_MUTATION_OPERATIONS:
            target = self._profile_target(profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            result = self._runtime.mutate(
                target, params[action], params, operation_id)
            return {profile: params[profile], result: result}
        if operation in WORKSPACE_SNAPSHOT_OPERATIONS:
            target = self._profile_target(profiles, params)
            return self._workspace_admin.snapshot(target)
        if operation in WORKSPACE_TIMELINE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if operation == "workspace.timeline_query":
                result = self._workspace_timeline.query(
                    target, inside, params["view"], params)
                if not isinstance(result, dict):
                    raise ApiFailure("internal")
                return {"profile": params["profile"], "workspace": params["workspace"],
                        "result": result}
            operation_id = self._required_operation_id(grant, target, key)
            result = self._workspace_timeline.mutate(
                target, inside, params["action"], params, operation_id)
            if not isinstance(result, dict):
                raise ApiFailure("internal")
            return {"profile": params["profile"], "workspace": params["workspace"],
                    "result": result}
        if operation in WORKSPACE_ADMISSION_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if operation == "workspace.admission_grant_list":
                rows = []
                for row in self._workspace_admin.admission_grants(target, inside):
                    handled = dict(row)
                    if isinstance(row.get("id"), str):
                        handled["admission_grant"] = self._handle(
                            grant, "admission_grant", target, row["id"])
                    rows.append(handled)
                return {"profile": params["profile"], "workspace": params["workspace"],
                        "grants": rows}
            operation_id = self._required_operation_id(grant, target, key)
            if operation == "workspace.admission_grant_create":
                member_id = next(
                    (item.member for item in self._workspace_admin.members(target, inside)
                     if self._handle(grant, "member", target, item.member)
                     == params["admin_member"]), None)
                device_id = next(
                    (item for item in self._workspace_admin.device_ids(target, inside)
                     if self._handle(grant, "device", target, item)
                     == params["admin_device"]), None)
                if member_id is None or device_id is None:
                    raise ApiFailure("forbidden")
                row = self._workspace_admin.create_admission_grant(
                    target, inside, member_id, device_id, params["max_admissions"],
                    params["lifetime_days"], params["v2_ready"], operation_id)
                view = dict(row)
                if isinstance(row.get("id"), str):
                    view["admission_grant"] = self._handle(
                        grant, "admission_grant", target, row["id"])
                return {"profile": params["profile"], "workspace": params["workspace"],
                        "state": "created", "grant": view}
            grant_id = next(
                (item for item in self._workspace_admin.admission_grant_ids(target, inside)
                 if self._handle(grant, "admission_grant", target, item)
                 == params["grant"]), None)
            if grant_id is None:
                raise ApiFailure("forbidden")
            if operation == "workspace.admission_grant_accept":
                state = self._workspace_admin.accept_admission_grant(
                    target, inside, grant_id, operation_id)
            else:
                state = self._workspace_admin.end_admission_grant(
                    target, inside, grant_id, operation_id)
            return {"profile": params["profile"], "workspace": params["workspace"],
                    "grant": params["grant"], "state": state}
        if operation in WORKSPACE_EDGE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            if operation == "workspace.admin_request_submit":
                member_id = None
                if "target_member" in params:
                    member_id = next(
                        (item.member for item in self._workspace_admin.members(target, inside)
                         if self._handle(grant, "member", target, item.member)
                         == params["target_member"]), None)
                    if member_id is None:
                        raise ApiFailure("forbidden")
                state = self._workspace_admin.submit_admin_request(
                    target, inside, params["request_kind"], member_id,
                    params.get("requested_role"), params.get("note", ""), operation_id)
            elif operation == "workspace.display_name_request":
                state = self._workspace_admin.request_display_name(
                    target, inside, params["display_name"], operation_id)
            else:
                state = self._workspace_admin.set_read_hint_sync(
                    target, inside, params["enabled"], operation_id)
            return workspace_edge_view(params["profile"], params["workspace"], state)
        if operation in WORKSPACE_AUTHORITY_OFFER_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            member_id = next(
                (item.member for item in self._workspace_admin.members(target, inside)
                 if self._handle(grant, "member", target, item.member)
                 == params["successor_member"]),
                None)
            device_id = next(
                (item for item in self._workspace_admin.device_ids(target, inside)
                 if self._handle(grant, "device", target, item) == params["successor_device"]),
                None)
            if member_id is None or device_id is None:
                raise ApiFailure("forbidden")
            state = self._workspace_admin.offer_authority_transition(
                target, inside, params["transition_kind"], member_id, device_id,
                params["outgoing_owner_role"], operation_id)
            return workspace_authority_offer_view(params["profile"], params["workspace"], state)
        if operation in WORKSPACE_AUTHORITY_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            transition_id = next(
                (item for item in self._workspace_admin.authority_transition_ids(target, inside)
                 if self._handle(grant, "authority_transition", target, item)
                 == params["transition"]),
                None)
            if transition_id is None:
                raise ApiFailure("forbidden")
            if operation == "workspace.authority_accept":
                state = self._workspace_admin.accept_authority_transition(
                    target, inside, transition_id, operation_id)
            else:
                state = self._workspace_admin.finalize_authority_transition(
                    target, inside, transition_id, operation_id)
            return workspace_authority_view(
                params["profile"], params["workspace"], params["transition"], state)
        if operation in WORKSPACE_AUTHORITY_LOSS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            state = self._workspace_admin.report_authority_loss(target, inside, operation_id)
            return workspace_authority_loss_view(params["profile"], params["workspace"], state)
        if operation in WORKSPACE_LIFECYCLE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            if operation == "workspace.close":
                state = self._workspace_admin.close_workspace(target, inside, operation_id)
            elif operation == "workspace.leave":
                state = self._workspace_admin.leave_workspace(target, inside, operation_id)
            else:
                state = self._workspace_admin.remove_workspace_data(
                    target, inside, params["confirmation"], operation_id)
            return workspace_lifecycle_view(params["profile"], params["workspace"], state)
        if operation in WORKSPACE_ADMIN_REQUEST_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            request_id = next(
                (item for item in self._workspace_admin.admin_request_ids(target, inside)
                 if self._handle(grant, "workspace_admin_request", target, item)
                 == params["request"]),
                None)
            if request_id is None:
                raise ApiFailure("forbidden")
            operation_id = self._required_operation_id(grant, target, key)
            if operation == "workspace.admin_request_approve":
                state = self._workspace_admin.decide_admin_request(
                    target, inside, request_id, True, operation_id)
            elif operation == "workspace.admin_request_decline":
                state = self._workspace_admin.decide_admin_request(
                    target, inside, request_id, False, operation_id)
            elif operation == "workspace.admin_request_cancel":
                state = self._workspace_admin.cancel_admin_request(
                    target, inside, request_id, operation_id)
            else:
                state = self._workspace_admin.dismiss_admin_request(
                    target, inside, request_id, operation_id)
            return workspace_admin_request_view(
                params["profile"], params["workspace"], params["request"], state)
        if operation in WORKSPACE_METADATA_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            value = self._workspace_admin.update_metadata(
                target, inside, params["name"], params["description"], operation_id)
            return workspace_metadata_view(params["profile"], params["workspace"], value)
        if operation in WORKSPACE_RETENTION_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            value = self._workspace_admin.update_retention(
                target, inside, params["retention_days"], operation_id)
            return workspace_retention_view(params["profile"], params["workspace"], value)
        if operation in WORKSPACE_QUERY_OPERATIONS:
            return self._workspace_query_operation(grant, profiles, operation, params)
        return self._workspace_mutation_operation(grant, profiles, operation, params, key)

    def _workspace_query_operation(self, grant, profiles, operation, params):
        if operation in WORKSPACE_LIST_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return workspace_list_view(params["profile"],
                                       self._workspace_entries(grant, target))
        if operation in WORKSPACE_REQUESTS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            requests = self._workspace_admin.requests(target, inside)
            return workspace_requests_view(
                params["profile"], params["workspace"],
                [(self._handle(grant, "join_request", target, item.request), item)
                 for item in requests])
        if operation in WORKSPACE_MEMBERS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            members = self._workspace_admin.members(target, inside)
            return workspace_members_view(
                params["profile"], params["workspace"],
                [(self._handle(grant, "member", target, item.member), item)
                 for item in members])
        if operation in WORKSPACE_CHANNELS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            channels = self._workspace_admin.channels(target, inside)
            return workspace_channels_view(
                params["profile"], params["workspace"],
                [(self._handle(grant, "channel", target, item.channel), item)
                 for item in channels])
        if operation in WORKSPACE_CHANNEL_MEMBERS_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            members = self._workspace_admin.members(target, inside)
            handles = {item.member: self._handle(grant, "member", target, item.member)
                       for item in members}
            current = [handles[item] for item in
                       self._workspace_admin.channel_members(target, inside, channel)
                       if item in handles]
            return workspace_channel_members_view(
                params["profile"], params["workspace"], params["channel"], current)
        if operation in WORKSPACE_DEVICES_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            members = {item.member: self._handle(grant, "member", target, item.member)
                       for item in self._workspace_admin.members(target, inside)}
            devices = self._workspace_admin.devices(target, inside)
            mapped = [(self._handle(grant, "device", target, item.device),
                       DeviceSummary(item.device, members.get(item.member, ""), item.current))
                      for item in devices]
            return workspace_devices_view(params["profile"], params["workspace"],
                                          [(handle, value) for handle, value in mapped])
        if operation in WORKSPACE_DEVICE_LINKS_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            requests = self._workspace_admin.device_link_requests(target, inside)
            return device_links_view(
                params["profile"], params["workspace"],
                [self._handle(grant, "device_link", target, item) for item in requests])
        if operation in WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            preview = self._workspace_admin.device_link_preview(
                target, params["document"])
            for handle, item in self._workspace_entries(grant, target):
                if item.workspace == preview.workspace:
                    return device_link_preview_view(params["profile"], handle, preview)
            raise ApiFailure("forbidden")
        if operation in WORKSPACE_PREVIEW_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return workspace_preview_view(params["profile"],
                                          self._workspace.preview(target, params["document"]))

    def _workspace_mutation_operation(self, grant, profiles, operation, params, key):
        if operation in WORKSPACE_ACCESS_MUTATION_OPERATIONS:
            return self._workspace_access_mutation(grant, profiles, operation, params, key)
        return self._workspace_resource_mutation(grant, profiles, operation, params, key)

    def _workspace_access_mutation(self, grant, profiles, operation, params, key):
        if operation in WORKSPACE_APPROVE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            request = self._join_request_target(grant, target, inside, params["request"])
            operation_id = self._required_operation_id(grant, target, key)
            approval = self._workspace_admin.approve(
                target, inside, request, operation_id)
            return workspace_approve_view(params["profile"], params["workspace"], approval)
        if operation in WORKSPACE_DECLINE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            request = self._join_request_target(grant, target, inside, params["request"])
            operation_id = self._required_operation_id(grant, target, key)
            declined = self._workspace_admin.decline(
                target, inside, request, operation_id)
            return workspace_decline_view(params["profile"], params["workspace"], declined)
        if operation in WORKSPACE_ROLE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            member = self._member_target(grant, target, inside, params["member"])
            if key is None:
                raise ApiFailure("invalid_request")
            change = self._workspace_admin.change_role(
                target, inside, member, params["role"],
                self._operation_id(grant, target, key))
            return workspace_member_role_view(
                params["profile"], params["workspace"], params["member"], change)
        if operation in WORKSPACE_INVITATION_CREATE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            invitation = self._workspace_admin.create_invitation(
                target, inside, self._operation_id(grant, target, key),
                params.get("connection_mode"),
                params.get("i2p_access_point"), params.get("i2p_label"))
            return workspace_invitation_create_view(
                params["profile"], params["workspace"], invitation)
        if operation in WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS or                 operation in WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            requests = self._workspace_admin.device_link_ids(target, inside)
            request_id = next(
                (item for item in requests
                 if self._handle(grant, "device_link", target, item) == params["request"]),
                None)
            if request_id is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            operation_id = self._operation_id(grant, target, key)
            if operation in WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS:
                state = self._workspace_admin.approve_device_link(
                    target, inside, request_id, operation_id)
            else:
                state = self._workspace_admin.decline_device_link(
                    target, inside, request_id, operation_id)
            return device_link_decision_view(
                params["profile"], params["workspace"], params["request"], state)
        if operation in WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            submitted = self._workspace_admin.device_link_submit(
                target, params["document"], self._operation_id(grant, target, key))
            for handle, item in self._workspace_entries(grant, target):
                if item.workspace == submitted.workspace:
                    return device_link_submit_view(params["profile"], handle, submitted)
            raise ApiFailure("internal")
        if operation in WORKSPACE_PROMPT_JOIN_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            operation_id = self._operation_id(grant, target, key)
            joined = self._workspace.submit_prompt(
                target, params["prompt"], operation_id)
            workspace = self._handle(grant, "workspace", target, joined.workspace)
            return workspace_join_view(params["profile"], workspace, joined)
        if operation in WORKSPACE_JOIN_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            operation_id = self._operation_id(grant, target, key)
            joined = self._workspace.join(target, params["document"], operation_id,
                                         params.get("i2p_consent") is True)
            workspace = self._handle(grant, "workspace", target, joined.workspace)
            return workspace_join_view(params["profile"], workspace, joined)

    def _workspace_resource_mutation(self, grant, profiles, operation, params, key):
        if operation in WORKSPACE_CHANNEL_CREATE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            visibility = params.get("visibility", "public")
            member_ids = tuple(
                self._member_target(grant, target, inside, handle)
                for handle in params.get("members", ()))
            created = self._workspace_admin.create_channel(
                target, inside, params["name"], self._operation_id(grant, target, key),
                visibility, member_ids)
            summary = ChannelSummary(
                self._handle(grant, "channel", target, created.channel),
                created.name, created.visibility, created.state)
            return workspace_channel_create_view(
                params["profile"], params["workspace"], summary)
        if operation in WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            member_ids = tuple(self._member_target(grant, target, inside, handle)
                               for handle in params["members"])
            self._workspace_admin.update_channel_members(
                target, inside, channel, member_ids,
                self._operation_id(grant, target, key))
            return workspace_channel_members_view(
                params["profile"], params["workspace"], params["channel"],
                sorted(params["members"]))
        if operation in WORKSPACE_CHANNEL_UPDATE_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            edited = self._workspace_admin.update_channel(
                target, inside, channel, params["name"], params["topic"],
                self._operation_id(grant, target, key), params.get("posting"))
            return workspace_channel_update_view(
                params["profile"], params["workspace"], params["channel"], edited)
        if operation in CONNECTION_DOCUMENT_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._workspace_admin.connection_document(
                target, params["action"], params)
        if operation in CONNECTION_SUPPORT_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._workspace_admin.connection_support(
                target, params["action"], params)
        if operation in LINK_PREVIEW_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._workspace_admin.link_preview(
                target, params["provider"], params["identifier"])
        if operation in CONVERSATION_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            result = self._workspace_admin.conversation(
                target, params["action"], params["kind"], params["target_id"], params)
            return {"conversation": result}
        if operation in ROUTE_UPDATE_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            result = self._workspace_admin.route_update(
                target, params["action"], params, None)
            return {"route": result}
        if operation in WORKSPACE_DIRECT_OPEN_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            member_id = self._member_target(
                grant, target, inside, params["member"])
            operation_id = self._required_operation_id(grant, target, key)
            direct = self._workspace_admin.open_direct(
                target, inside, member_id, operation_id)
            return {"id": direct["id"]}
        if operation in WORKSPACE_DISPLAY_DECIDE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            state = self._workspace_admin.decide_display_name(
                target, inside, params["request"], params["approve"], operation_id)
            return {"state": state}
        if operation in REMOTE_PROFILE_QUERY_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            return self._workspace_admin.remote_profiles(target)
        if operation in REMOTE_PROFILE_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            result = self._workspace_admin.remote_profile(
                target, params["action"], params)
            return {"remote_profile": result}
        if operation in WORKSPACE_DRAFT_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            state = self._workspace_admin.save_draft(
                target, inside, params["conversation"], params["text"],
                operation_id, params.get("thread_root"),
                params.get("mention_member_ids", []))
            return {"state": state}
        if operation in WORKSPACE_MEMBER_REMOVE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            member_id = self._member_target(
                grant, target, inside, params["member"])
            operation_id = self._required_operation_id(grant, target, key)
            state = self._workspace_admin.remove_member(
                target, inside, member_id, operation_id)
            return workspace_member_remove_view(
                params["profile"], params["workspace"], params["member"], state)
        if operation in WORKSPACE_CHANNEL_STATE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            channel_id = None
            if "channel" in params:
                channel_id = self._channel_target(
                    grant, target, inside, params["channel"])
            state = self._workspace_admin.channel_state(
                target, inside, params["action"], channel_id, params, operation_id)
            return workspace_channel_state_view(
                params["profile"], params["workspace"],
                params.get("channel"), state)
        if operation in WORKSPACE_CHANNEL_RECOVER_OPERATIONS:
            target, inside, channel_id = self._workspace_channel_scope(grant, profiles, params)
            operation_id = self._required_operation_id(grant, target, key)
            state = self._workspace_admin.recover_channel(
                target, inside, channel_id, operation_id)
            return workspace_channel_recover_view(
                params["profile"], params["workspace"], params["channel"], state)
        if operation in WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            archived = self._workspace_admin.archive_channel(
                target, inside, channel, self._operation_id(grant, target, key))
            return workspace_channel_archive_view(
                params["profile"], params["workspace"], params["channel"], archived)
        if operation in WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            link = self._workspace_admin.device_link_create(
                target, inside, self._operation_id(grant, target, key))
            return device_link_create_view(params["profile"], params["workspace"], link)
        if operation in WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            inside = self._workspace_target(grant, target, params["workspace"])
            device_id = next(
                (item for item in self._workspace_admin.device_ids(target, inside)
                 if self._handle(grant, "device", target, item) == params["device"]),
                None)
            if device_id is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            self._workspace_admin.request_device_removal(
                target, inside, device_id, self._operation_id(grant, target, key))
            return device_removal_view(params["profile"], params["workspace"],
                                       params["device"], "requested")
        if operation in WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS:
            target = profiles.get(params["profile"])
            if target is None:
                raise ApiFailure("forbidden")
            inside = self._workspace_target(grant, target, params["workspace"])
            removal_id = next(
                (item for item in self._workspace_admin.removal_ids(target, inside)
                 if self._handle(grant, "device_link", target, item) == params["request"]),
                None)
            if removal_id is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            operation_id = self._operation_id(grant, target, key)
            if operation == "workspace.device_removal_approve":
                state = self._workspace_admin.approve_device_removal(
                    target, inside, removal_id, operation_id)
            else:
                state = self._workspace_admin.decline_device_removal(
                    target, inside, removal_id, operation_id)
            return device_removal_view(params["profile"], params["workspace"],
                                       params["request"], state)
        if operation in WORKSPACE_DEVICE_REMOVE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            device_id = next(
                (item for item in self._workspace_admin.device_ids(target, inside)
                 if self._handle(grant, "device", target, item) == params["device"]),
                None)
            if device_id is None:
                raise ApiFailure("forbidden")
            if key is None:
                raise ApiFailure("invalid_request")
            self._workspace_admin.remove_device(
                target, inside, device_id, self._operation_id(grant, target, key))
            return workspace_device_remove_view(
                params["profile"], params["workspace"], params["device"], "removed")
        if operation in WORKSPACE_POLICY_UPDATE_OPERATIONS:
            target, inside = self._workspace_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            applied = self._workspace_admin.update_policies(
                target, inside, params["channel_creation"], params["posting"],
                params["invitation_requests"], self._operation_id(grant, target, key))
            return workspace_policies_view(params["profile"], params["workspace"], applied)
        if operation in WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            member_id = self._member_target(grant, target, inside, params["member"])
            if key is None:
                raise ApiFailure("invalid_request")
            self._workspace_admin.offer_channel_transfer(
                target, inside, channel, member_id,
                self._operation_id(grant, target, key))
            return workspace_channel_transfer_offer_view(
                params["profile"], params["workspace"], params["channel"],
                params["member"])
        if operation in WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS:
            target, inside, channel = self._workspace_channel_scope(grant, profiles, params)
            if key is None:
                raise ApiFailure("invalid_request")
            self._workspace_admin.accept_channel_transfer(
                target, inside, channel, self._operation_id(grant, target, key))
            return workspace_channel_transfer_accept_view(
                params["profile"], params["workspace"], params["channel"])

    def _capabilities(self, profiles):
        limits = {"frame_bytes": MAX_FRAME_BYTES, "request_json_depth": MAX_REQUEST_JSON_DEPTH,
                  "request_json_structural_tokens": MAX_REQUEST_JSON_TOKENS, "profiles": MAX_PROFILES,
                  "connections_per_profile": MAX_CONNECTIONS}
        if self._messages is not None:
            limits.update(peers_per_profile=MAX_PEERS, text_utf8_bytes=16384,
                          idempotency_seconds=IDEMPOTENCY_SECONDS,
                          enqueue_keys_per_caller_profile=MAX_CALLER_ENQUEUES,
                          enqueue_keys_per_vault=MAX_VAULT_ENQUEUES)
        if self._recovery is not None:
            limits.update(event_batch_count=MAX_BATCH, event_batch_bytes=MAX_BATCH_BYTES,
                          event_retention_count=MAX_EVENTS, event_retention_seconds=RETENTION_SECONDS,
                          recovery_scan_count=MAX_BATCH, cursor_bytes=MAX_CURSOR_BYTES,
                          acknowledgment_seconds=RETENTION_SECONDS,
                          acknowledgment_keys_per_caller_profile=MAX_CALLER_ACKNOWLEDGMENTS,
                          acknowledgment_keys_per_vault=MAX_VAULT_ACKNOWLEDGMENTS)
        if self._received is not None:
            limits.update(received_scan_count=MAX_BATCH, received_batch_bytes=MAX_BATCH_BYTES)
        if self._diagnostics is not None:
            limits.update(diagnostic_count=MAX_DIAGNOSTICS, diagnostic_bytes=MAX_DIAGNOSTIC_BYTES)
        return {"api_major": 1, "api_minor": 0, "stability": "experimental",
                "operations": list(self._operations), "profiles": list(profiles), "limits": limits}

    def _observe(self, grant, profile, operation, params):
        view = self._observations.profile(profile)
        if len(view.connections) > MAX_CONNECTIONS:
            raise ApiFailure("resource_exhausted")
        connections = {self._handle(grant, "connection", profile, internal): status
                       for internal, status in view.connections.items()}
        if operation == "profile.query":
            if (not isinstance(view.display_name, str) or not 1 <= len(view.display_name) <= 80
                    or not isinstance(view.destination, str)
                    or re.fullmatch(r"[a-f0-9]{32}", view.destination) is None):
                raise ApiFailure("internal")
            result = {"profile": params["profile"], "display_name": view.display_name,
                      "destination": view.destination, "connections": list(connections)}
            if self._messages is not None:
                result["peers"] = list(self._peers(grant, profile))
            return result
        status = connections.get(params["connection"])
        if status is None:
            raise ApiFailure("forbidden")
        return {"profile": params["profile"], "connection": params["connection"],
                "observation": connection_view(status)}

    def _peers(self, grant, profile):
        peers = self._messages.peers(profile)
        if len(peers) > MAX_PEERS:
            raise ApiFailure("resource_exhausted")
        return {self._handle(grant, "peer", profile, peer): peer for peer in peers}

    def _message(self, grant, profile, operation, params, key):
        scope = MessageScope(grant.caller, profile)
        if operation in {"peer.query", "message.enqueue"}:
            recipient = self._peers(grant, profile).get(params["peer" if operation == "peer.query" else "recipient"])
            if recipient is None:
                raise ApiFailure("forbidden")
            if operation == "peer.query":
                return peer_view(params["profile"], params["peer"], self._messages.peer(profile, recipient))
            accepted = self._messages.enqueue(scope, recipient, key, params["text"])
            return acceptance_view(params["profile"], accepted)
        message = self._messages.query(scope, params["message"])
        recipient = self._handle(grant, "peer", profile, message.recipient)
        return message_view(params["profile"], params["message"], recipient, message)

    def _recover(self, grant, profile, operation, params, key):
        scope = MessageScope(grant.caller, profile)
        if operation == "events.ack":
            accepted = self._recovery.acknowledge(scope, params["cursor"], key)
            return acknowledgment_view(params["profile"], accepted)
        if operation == "events.poll":
            page = self._recovery.poll(scope, params["cursor"], params["limit"])
            self._validate_recovery_cursor(page.next_cursor)
            if type(page.more) is not bool or len(page.events) > params["limit"]:
                raise ApiFailure("internal")
            return self._bounded_recovery({"profile": params["profile"], "events": [event_view(item) for item in page.events],
                                          "next_cursor": page.next_cursor, "more": page.more})
        page = self._recovery.snapshot(scope, params["cursor"], params["limit"])
        if len(page.messages) > params["limit"] or (page.next_cursor is None) == (page.events_cursor is None):
            raise ApiFailure("internal")
        self._validate_recovery_cursor(page.events_cursor if page.next_cursor is None else page.next_cursor)
        messages = [message_view(params["profile"], item.handle,
                    self._handle(grant, "peer", profile, item.value.recipient), item.value) for item in page.messages]
        return self._bounded_recovery({"profile": params["profile"], "messages": messages,
                                       "next_cursor": page.next_cursor, "events_cursor": page.events_cursor})

    def _channel_target(self, grant, profile, workspace, handle):
        for item in self._workspace_admin.channels(profile, workspace):
            if self._handle(grant, "channel", profile, item.channel) == handle:
                return item.channel
        raise ApiFailure("forbidden")

    def _member_target(self, grant, profile, workspace, handle):
        for item in self._workspace_admin.members(profile, workspace):
            if self._handle(grant, "member", profile, item.member) == handle:
                return item.member
        raise ApiFailure("forbidden")

    def _workspace_entries(self, grant, profile):
        return [(self._handle(grant, "workspace", profile, item.workspace), item)
                for item in self._workspace_admin.list(profile)]

    def _workspace_target(self, grant, profile, handle):
        for mapped, item in self._workspace_entries(grant, profile):
            if mapped == handle:
                return item.workspace
        raise ApiFailure("forbidden")

    def _join_request_target(self, grant, profile, workspace, handle):
        for request_id in self._workspace_admin.request_ids(profile, workspace):
            if self._handle(grant, "join_request", profile, request_id) == handle:
                return request_id
        raise ApiFailure("forbidden")

    def _invitation_operation(self, grant, profile, params):
        handle = self._handle(grant, "profile", profile, profile)
        return invitation_view(handle, self._invitations.create(
            profile,
            connection_mode=params.get("connection_mode"),
            manual_setup_id=params.get("manual_setup_id"),
            external_host=params.get("external_host"),
            external_port=params.get("external_port"),
            i2p_access_point=params.get("i2p_access_point"),
            i2p_label=params.get("i2p_label"),
        ))

    def _pairing_request_operation(self, grant, profile, params):
        contact = self._peers(grant, profile).get(params["peer"])
        if contact is None:
            raise ApiFailure("forbidden")
        observation = self._pairing.request(profile, contact)
        return pairing_request_view(params["profile"], params["peer"], observation)

    def _pairing_operation(self, grant, profile, params):
        observation = self._pairing.accept(profile, params["document"],
                                            i2p_consent=params.get("i2p_consent", False))
        peer = self._handle(grant, "peer", profile, observation.contact)
        return pairing_view(params["profile"], peer, observation)

    def _relationship_operation(self, grant, profile, operation, params):
        contact = self._peers(grant, profile).get(params["peer"])
        if contact is None:
            raise ApiFailure("forbidden")
        if operation == "peer.delete":
            observation = self._relationship.delete(profile, contact)
            return peer_delete_view(params["profile"], params["peer"], observation)
        if operation == "peer.unblock":
            observation = self._relationship.unblock(profile, contact)
            return peer_trust_view(params["profile"], params["peer"], observation)
        if operation == "peer.decide":
            observation = self._relationship.decide(
                profile, contact, params["accept"])
            return peer_trust_view(params["profile"], params["peer"], observation)
        if operation == "peer.update":
            observation = self._relationship.update(
                profile, contact, params["action"], params.get("display_name"))
            return peer_trust_view(params["profile"], params["peer"], observation)
        action = (self._relationship.approve if operation == "peer.approve"
                  else self._relationship.revoke)
        observation = action(profile, contact)
        return relationship_view(params["profile"], params["peer"], operation, observation)

    def _intent_operation(self, grant, profile, operation, params):
        contact = self._peers(grant, profile).get(params["peer"])
        if contact is None:
            raise ApiFailure("forbidden")
        action = self._intent.start if operation == "connection.start" else self._intent.stop
        observation = action(profile, contact)
        return intent_view(params["profile"], params["peer"], observation)

    def _received_messages(self, grant, profile, params):
        page = self._received.received(MessageScope(grant.caller, profile), params["cursor"], params["limit"])
        if type(page.more) is not bool or len(page.messages) > params["limit"]:
            raise ApiFailure("internal")
        if page.next_cursor is not None:
            self._validate_recovery_cursor(page.next_cursor)
        elif page.more:
            raise ApiFailure("internal")
        messages = [received_view(params["profile"], item.handle,
                                  self._handle(grant, "peer", profile, item.value.contact),
                                  item.value) for item in page.messages]
        return self._bounded_recovery({"profile": params["profile"], "messages": messages,
                                       "next_cursor": page.next_cursor, "more": page.more})

    @staticmethod
    def _validate_recovery_cursor(value):
        if not isinstance(value, str) or CURSOR.fullmatch(value) is None:
            raise ApiFailure("internal")

    @staticmethod
    def _bounded_recovery(result):
        # Leave room for the version, bounded request ID and response envelope.
        if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > MAX_BATCH_BYTES - 256:
            raise ApiFailure("internal")
        return result
