"""Strict public request parsing, without authority, storage or runtime effects."""

import re

from ..chat_text import validate_chat_text
from ..errors import ValidationError
from .errors import ApiFailure
from .recovery import MAX_BATCH
from .diagnostics import MAX_DIAGNOSTICS


OPERATIONS = ("runtime.capabilities", "profile.query", "connection.snapshot")
MESSAGE_OPERATIONS = ("peer.query", "message.enqueue", "message.query")
RECOVERY_OPERATIONS = ("message.list", "events.poll", "events.ack")
RECEIVED_OPERATIONS = ("message.received",)
INTENT_OPERATIONS = ("connection.start", "connection.stop")
RELATIONSHIP_OPERATIONS = ("peer.approve", "peer.revoke", "peer.unblock", "peer.delete")
DRAFT_OPERATIONS = ("peer.draft_get", "peer.draft_set")
CALL_OPERATIONS = ("call.settings_query", "call.settings_update", "call.ice_servers",
                    "call.media_query")
SETTINGS_OPERATIONS = ("settings.query", "settings.update")
REACTION_OPERATIONS = ("message.reaction_set",)
GROUP_OPERATIONS = ("group.query", "group.create", "group.message_enqueue",
                    "group.leave", "group.close", "group.member_remove",
                    "group.invitation_accept", "group.invitation_decline",
                    "group.invitation_retry")
PAIRING_OPERATIONS = ("peer.pairing_accept",)
REQUEST_OPERATIONS = ("peer.pairing_request",)
INVITATION_OPERATIONS = ("peer.pairing_create",)
STOP_OPERATIONS = ("runtime.stop",)
APPLICATION_OPERATIONS = ("application.snapshot", "application.command")
WORKSPACE_PREVIEW_OPERATIONS = ("workspace.invitation_preview",)
WORKSPACE_JOIN_OPERATIONS = ("workspace.join",)
WORKSPACE_LIST_OPERATIONS = ("workspace.query",)
WORKSPACE_REQUESTS_OPERATIONS = ("workspace.join_requests",)
WORKSPACE_APPROVE_OPERATIONS = ("workspace.join_approve",)
WORKSPACE_DECLINE_OPERATIONS = ("workspace.join_decline",)
WORKSPACE_MEMBERS_OPERATIONS = ("workspace.members",)
WORKSPACE_ROLE_OPERATIONS = ("workspace.member_role",)
WORKSPACE_INVITATION_CREATE_OPERATIONS = ("workspace.invitation_create",)
WORKSPACE_CHANNELS_OPERATIONS = ("workspace.channels",)
WORKSPACE_CHANNEL_CREATE_OPERATIONS = ("workspace.channel_create",)
WORKSPACE_CHANNEL_MEMBERS_OPERATIONS = ("workspace.channel_members",)
WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS = ("workspace.channel_members_update",)
WORKSPACE_CHANNEL_UPDATE_OPERATIONS = ("workspace.channel_update",)
WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS = ("workspace.channel_archive",)
WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS = ("workspace.device_link_create",)
WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS = ("workspace.device_link_preview",)
WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS = ("workspace.device_link_submit",)
WORKSPACE_DEVICE_LINKS_OPERATIONS = ("workspace.device_links",)
WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS = ("workspace.device_link_approve",)
WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS = ("workspace.device_link_decline",)
WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS = ("workspace.channel_transfer_offer",)
WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS = ("workspace.channel_transfer_accept",)
WORKSPACE_POLICY_UPDATE_OPERATIONS = ("workspace.policy_update",)
WORKSPACE_METADATA_OPERATIONS = ("workspace.metadata_update",)
WORKSPACE_RETENTION_OPERATIONS = ("workspace.retention_update",)
WORKSPACE_AUTHORITY_LOSS_OPERATIONS = ("workspace.authority_loss_report",)
WORKSPACE_AUTHORITY_OPERATIONS = ("workspace.authority_accept", "workspace.authority_finalize")
WORKSPACE_AUTHORITY_OFFER_OPERATIONS = ("workspace.authority_offer",)
WORKSPACE_ADMISSION_OPERATIONS = ("workspace.invitation_revoke",
                                "workspace.admission_grant_list",
                                "workspace.admission_grant_create",
                                "workspace.admission_grant_accept",
                                "workspace.admission_grant_end")
WORKSPACE_EDGE_OPERATIONS = ("workspace.admin_request_submit",
                             "workspace.display_name_request",
                             "workspace.read_hint_sync")
WORKSPACE_LIFECYCLE_OPERATIONS = ("workspace.close", "workspace.leave",
                                  "workspace.remove_data")
WORKSPACE_ADMIN_REQUEST_OPERATIONS = ("workspace.admin_request_approve",
                                      "workspace.admin_request_decline",
                                      "workspace.admin_request_cancel",
                                      "workspace.admin_request_dismiss")
WORKSPACE_DEVICES_OPERATIONS = ("workspace.devices",)
WORKSPACE_DEVICE_REMOVE_OPERATIONS = ("workspace.device_remove",)
WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS = ("workspace.device_removal_request",)
WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS = ("workspace.device_removal_approve",
                                              "workspace.device_removal_decline")
WORKSPACE_QUERY_OPERATIONS = frozenset().union(
    WORKSPACE_LIST_OPERATIONS,
    WORKSPACE_REQUESTS_OPERATIONS,
    WORKSPACE_MEMBERS_OPERATIONS,
    WORKSPACE_CHANNELS_OPERATIONS,
    WORKSPACE_CHANNEL_MEMBERS_OPERATIONS,
    WORKSPACE_DEVICES_OPERATIONS,
    WORKSPACE_DEVICE_LINKS_OPERATIONS,
    WORKSPACE_PREVIEW_OPERATIONS,
    WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS,
)

WORKSPACE_ACCESS_MUTATION_OPERATIONS = frozenset().union(
    WORKSPACE_APPROVE_OPERATIONS,
    WORKSPACE_DECLINE_OPERATIONS,
    WORKSPACE_ROLE_OPERATIONS,
    WORKSPACE_INVITATION_CREATE_OPERATIONS,
    WORKSPACE_JOIN_OPERATIONS,
    WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS,
)

WORKSPACE_OPERATIONS = frozenset().union(
    WORKSPACE_PREVIEW_OPERATIONS,
    WORKSPACE_JOIN_OPERATIONS,
    WORKSPACE_LIST_OPERATIONS,
    WORKSPACE_REQUESTS_OPERATIONS,
    WORKSPACE_APPROVE_OPERATIONS,
    WORKSPACE_DECLINE_OPERATIONS,
    WORKSPACE_MEMBERS_OPERATIONS,
    WORKSPACE_ROLE_OPERATIONS,
    WORKSPACE_INVITATION_CREATE_OPERATIONS,
    WORKSPACE_CHANNELS_OPERATIONS,
    WORKSPACE_CHANNEL_CREATE_OPERATIONS,
    WORKSPACE_CHANNEL_MEMBERS_OPERATIONS,
    WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS,
    WORKSPACE_CHANNEL_UPDATE_OPERATIONS,
    WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS,
    WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS,
    WORKSPACE_DEVICE_LINKS_OPERATIONS,
    WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS,
    WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS,
    WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS,
    WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS,
    WORKSPACE_POLICY_UPDATE_OPERATIONS,
    WORKSPACE_DEVICES_OPERATIONS,
    WORKSPACE_DEVICE_REMOVE_OPERATIONS,
)

DIAGNOSTIC_OPERATIONS = ("diagnostics.query",)
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
HANDLE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{16,128}\Z")
CURSOR = re.compile(r"[A-Za-z0-9_-]{16,1024}\Z")


def parse_request(value, operations):
    if not isinstance(value, dict):
        raise ApiFailure("invalid_request")
    fields = {"api_version", "request_id", "operation", "params"}
    if not fields <= set(value) or set(value) - fields - {"idempotency_key"}:
        raise ApiFailure("invalid_request")
    if type(value["api_version"]) is not int or value["api_version"] != 1:
        raise ApiFailure("incompatible_version")
    identifier = value["request_id"]
    if not isinstance(identifier, str) or REQUEST_ID.fullmatch(identifier) is None:
        raise ApiFailure("invalid_request")
    operation = value["operation"]
    if not isinstance(operation, str) or operation not in operations:
        raise ApiFailure("unsupported_operation")
    if operation in ("message.enqueue", "events.ack", "workspace.join",
                      "workspace.join_approve", "workspace.join_decline",
                      "workspace.member_role", "workspace.channel_create",
                      "workspace.channel_members_update", "workspace.channel_update",
                      "workspace.channel_archive", "workspace.device_link_create",
                      "workspace.device_link_submit", "workspace.device_link_approve",
                      "workspace.device_link_decline", "workspace.channel_transfer_offer",
                      "workspace.channel_transfer_accept", "workspace.policy_update",
                      "workspace.device_remove", "workspace.invitation_create"):
        fields.add("idempotency_key")
    if set(value) != fields:
        raise ApiFailure("invalid_request")
    if operation == "message.enqueue":
        return operation, _enqueue_params(value)
    if operation == "events.ack":
        return operation, _acknowledgment_params(value)
    if operation == "diagnostics.query":
        return operation, _diagnostic_params(value["params"])
    if operation in APPLICATION_OPERATIONS:
        params = value["params"]
        if operation == "application.snapshot":
            if params != {}:
                raise ApiFailure("invalid_request")
            return operation, {}
        if (not isinstance(params, dict) or set(params) != {"command", "payload"}
                or not isinstance(params["command"], str)
                or not 1 <= len(params["command"]) <= 80
                or not isinstance(params["payload"], dict)):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in RECOVERY_OPERATIONS:
        return operation, _recovery_params(value["params"])
    if operation in RECEIVED_OPERATIONS:
        return operation, _recovery_params(value["params"])
    if operation in WORKSPACE_LIST_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_REQUESTS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_APPROVE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "request"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNELS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICES_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "device"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "device"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "request"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "request"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_REMOVE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "device"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_ADMISSION_OPERATIONS:
        params = value["params"]
        if operation == "workspace.invitation_revoke":
            expected = {"profile", "workspace", "invitation"}
        elif operation == "workspace.admission_grant_list":
            expected = {"profile", "workspace"}
        elif operation == "workspace.admission_grant_create":
            expected = {"profile", "workspace", "admin_member", "admin_device",
                        "max_admissions", "lifetime_days", "v2_ready"}
        else:
            expected = {"profile", "workspace", "grant"}
        if not isinstance(params, dict) or set(params) != expected:
            raise ApiFailure("invalid_request")
        if any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
               for key in ("profile", "workspace")):
            raise ApiFailure("invalid_request")
        for key in ("admin_member", "admin_device", "grant", "invitation"):
            if key in params and (not isinstance(params[key], str)
                                  or HANDLE.fullmatch(params[key]) is None):
                raise ApiFailure("invalid_request")
        if operation == "workspace.admission_grant_create":
            if (type(params["max_admissions"]) is not int
                    or not 1 <= params["max_admissions"] <= 50
                    or type(params["lifetime_days"]) is not int
                    or not 1 <= params["lifetime_days"] <= 90
                    or type(params["v2_ready"]) is not bool):
                raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_EDGE_OPERATIONS:
        params = value[params]
        if operation == "workspace.admin_request_submit":
            allowed = {"profile", "workspace", "request_kind"}
            optional = {"target_member", "requested_role", "note"}
            valid = (isinstance(params, dict) and allowed <= set(params)
                     and not set(params) - allowed - optional
                     and isinstance(params.get("request_kind"), str)
                     and params["request_kind"] in {"invitation", "member_removal", "role_change"}
                     and isinstance(params.get("note", ""), str)
                     and len(params.get("note", "")) <= 500
                     and (params.get("requested_role") in {None, "admin", "member"}))
        elif operation == "workspace.display_name_request":
            valid = (isinstance(params, dict) and set(params) == {"profile", "workspace", "display_name"}
                     and isinstance(params["display_name"], str)
                     and 1 <= len(params["display_name"].strip()) <= 64)
        else:
            valid = (isinstance(params, dict) and set(params) == {"profile", "workspace", "enabled"}
                     and type(params["enabled"]) is bool)
        if not valid or any(not isinstance(params.get(key), str)
                            or HANDLE.fullmatch(params[key]) is None
                            for key in ("profile", "workspace")):
            raise ApiFailure("invalid_request")
        if "target_member" in params and (not isinstance(params["target_member"], str)
                                          or HANDLE.fullmatch(params["target_member"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_AUTHORITY_OFFER_OPERATIONS:
        params = value[params]
        if (not isinstance(params, dict)
                or set(params) != {profile, workspace, transition_kind,
                                   successor_member, successor_device,
                                   outgoing_owner_role}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in (profile, workspace, successor_member, successor_device))
                or params[transition_kind] not in {owner_rotation, device_handoff, owner_handoff}
                or params[outgoing_owner_role] not in {admin, member}):
            raise ApiFailure(invalid_request)
        return operation, params
    if operation in WORKSPACE_AUTHORITY_OPERATIONS:
        params = value[params]
        if (not isinstance(params, dict)
                or set(params) != {profile, workspace, transition}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in (profile, workspace, transition))):
            raise ApiFailure(invalid_request)
        return operation, params
    if operation in WORKSPACE_AUTHORITY_LOSS_OPERATIONS:
        params = value[params]
        if (not isinstance(params, dict) or set(params) != {profile, workspace}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in (profile, workspace))):
            raise ApiFailure(invalid_request)
        return operation, params
    if operation in WORKSPACE_LIFECYCLE_OPERATIONS:
        params = value[params]
        expected = ({"profile", "workspace", "confirmation"}
                    if operation == "workspace.remove_data" else {"profile", "workspace"})
        if (not isinstance(params, dict) or set(params) != expected
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace"))
                or (operation == "workspace.remove_data"
                    and (not isinstance(params["confirmation"], str)
                         or not 1 <= len(params["confirmation"]) <= 128))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_ADMIN_REQUEST_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "request"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "request"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_METADATA_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "name", "description"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace"))
                or not isinstance(params["name"], str) or not 1 <= len(params["name"].strip()) <= 128
                or not isinstance(params["description"], str) or len(params["description"]) > 1000):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_RETENTION_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "retention_days"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace"))
                or params["retention_days"] not in {None, 30, 90, 365}):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_POLICY_UPDATE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "channel_creation",
                                   "posting", "invitation_requests"}
                or "idempotency_key" not in value
                or params.get("channel_creation") not in {"all_members", "owner_and_admins"}
                or params.get("posting") not in {"all_members", "owner_and_admins"}
                or params.get("invitation_requests") not in {"owner_only", "owner_and_admins",
                                                             "all_members_request"}
                or any(not isinstance(params.get(name), str) or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace",
                                                            "channel", "member"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "channel"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_LINKS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS or             operation in WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "request"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or "idempotency_key" not in value
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 65536):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 65536):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "channel"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_MEMBERS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "channel"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace",
                                                            "channel", "members"}
                or "idempotency_key" not in value
                or not isinstance(params.get("members"), list)
                or not 1 <= len(params["members"]) <= 8
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params["members"])
                or any(not isinstance(params.get(name), str) or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace", "channel"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_UPDATE_OPERATIONS:
        params = value["params"]
        allowed = {"profile", "workspace", "channel", "name", "topic", "posting"}
        if (not isinstance(params, dict) or not {"profile", "workspace",
                                                 "channel", "name", "topic"} <= set(params)
                or set(params) - allowed
                or params.get("posting", "inherit") not in
                {"inherit", "all_members", "owner_and_admins"}
                or "idempotency_key" not in value
                or not isinstance(params.get("name"), str) or not 1 <= len(params["name"]) <= 64
                or not isinstance(params.get("topic"), str) or len(params["topic"]) > 1024
                or any(not isinstance(params.get(name), str) or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace", "channel"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_INVITATION_CREATE_OPERATIONS:
        params = value["params"]
        allowed = {"profile", "workspace", "connection_mode",
                   "i2p_access_point", "i2p_label"}
        mode = params.get("connection_mode") if isinstance(params, dict) else None
        if (not isinstance(params, dict)
                or not {"profile", "workspace"} <= set(params)
                or set(params) - allowed
                or mode not in {None, "webrtc", "email", "i2p", "participant"}
                or "idempotency_key" not in value
                or any(not isinstance(params.get(name), str)
                       or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace"))
                or (mode == "i2p"
                    and (not isinstance(params.get("i2p_access_point"), str)
                         or not 1 <= len(params["i2p_access_point"]) <= 128
                         or (params.get("i2p_label") is not None
                             and (not isinstance(params["i2p_label"], str)
                                  or len(params["i2p_label"]) > 64))))
                or (mode != "i2p"
                    and ("i2p_access_point" in params or "i2p_label" in params))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_CREATE_OPERATIONS:
        params = value["params"]
        allowed = {"profile", "workspace", "name", "visibility", "members"}
        if (not isinstance(params, dict) or not {"profile", "workspace", "name"} <= set(params)
                or set(params) - allowed or "idempotency_key" not in value
                or params.get("visibility", "public") not in {"public", "private"}
                or not isinstance(params.get("name"), str) or not 1 <= len(params["name"]) <= 64
                or any(not isinstance(params.get(name), str) or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace"))):
            raise ApiFailure("invalid_request")
        members = params.get("members")
        if members is not None:
            if (params.get("visibility") != "private" or not isinstance(members, list)
                    or not 1 <= len(members) <= 8
                    or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                           for item in members)):
                raise ApiFailure("invalid_request")
        elif params.get("visibility") == "private":
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_ROLE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "member", "role"}
                or "idempotency_key" not in value
                or params.get("role") not in {"admin", "member"}
                or any(not isinstance(params.get(name), str) or HANDLE.fullmatch(params[name]) is None
                       for name in ("profile", "workspace", "member"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_MEMBERS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DECLINE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "request"}
                or "idempotency_key" not in value
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_PREVIEW_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 1048576
                or ("i2p_consent" in params and type(params["i2p_consent"]) is not bool)):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_JOIN_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or "idempotency_key" not in value
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 1048576):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in STOP_OPERATIONS:
        if value["params"] != {}:
            raise ApiFailure("invalid_request")
        return operation, {}
    if operation in INVITATION_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or not {"profile"} <= set(params)
                or set(params) - {"profile", "connection_mode", "manual_setup_id",
                                  "external_host", "external_port", "i2p_access_point",
                                  "i2p_label"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        mode = params.get("connection_mode")
        if mode is not None and mode not in {"manual", "participant", "nearby",
                                             "remote", "webrtc", "email", "i2p"}:
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in REQUEST_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "peer"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in PAIRING_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or not {"profile", "document"} <= set(params)
                or set(params) - {"profile", "document", "i2p_consent"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 1048576):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in GROUP_OPERATIONS:
        params = value["params"]
        expected = ({"profile"} if operation == "group.query"
                    else {"profile", "group", "text"} if operation == "group.message_enqueue"
                    else {"profile", "invitation"} if operation in {
                        "group.invitation_accept", "group.invitation_decline"}
                    else {"profile", "group", "member"} if operation in {
                        "group.member_remove", "group.invitation_retry"}
                    else {"profile", "group"} if operation in {"group.leave", "group.close"}
                    else {"profile", "title", "posting_policy", "members"})
        if (not isinstance(params, dict) or set(params) != expected
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or (operation in {"group.invitation_accept", "group.invitation_decline"}
                    and (not isinstance(params["invitation"], str)
                         or HANDLE.fullmatch(params["invitation"]) is None))
                or (operation in {"group.leave", "group.close", "group.member_remove",
                                 "group.invitation_retry"}
                    and (not isinstance(params["group"], str)
                         or HANDLE.fullmatch(params["group"]) is None))
                or (operation in {"group.member_remove", "group.invitation_retry"}
                    and (not isinstance(params["member"], str)
                         or HANDLE.fullmatch(params["member"]) is None))
                or (operation == "group.message_enqueue"
                    and (not isinstance(params["group"], str)
                         or HANDLE.fullmatch(params["group"]) is None
                         or not isinstance(params["text"], str)
                         or not 1 <= len(params["text"].encode("utf-8")) <= 16384))
                or (operation == "group.create"
                    and (not isinstance(params["title"], str)
                         or not 1 <= len(params["title"].strip()) <= 128
                         or params["posting_policy"] not in {"members", "owner_admins"}
                         or not isinstance(params["members"], list)
                         or not params["members"]
                         or any(not isinstance(item, str)
                                or HANDLE.fullmatch(item) is None
                                for item in params["members"])))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in REACTION_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "message", "emoji", "active"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "message"))
                or not isinstance(params["emoji"], str)
                or not 1 <= len(params["emoji"]) <= 16
                or type(params["active"]) is not bool):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in SETTINGS_OPERATIONS:
        params = value["params"]
        expected = {"profile"} | ({"settings"} if operation == "settings.update" else set())
        if (not isinstance(params, dict) or set(params) != expected
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or (operation == "settings.update"
                    and not isinstance(params["settings"], dict))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in CALL_OPERATIONS:
        params = value["params"]
        expected = ({"profile"} if operation in {"call.settings_query", "call.ice_servers"}
                    else {"profile", "call"} if operation == "call.media_query"
                    else {"profile", "settings"})
        if (not isinstance(params, dict) or set(params) != expected
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or (operation == "call.settings_update"
                    and not isinstance(params["settings"], dict))
                or (operation == "call.media_query"
                    and (not isinstance(params["call"], str)
                         or HANDLE.fullmatch(params["call"]) is None))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in DRAFT_OPERATIONS:
        params = value["params"]
        expected = {"profile", "peer"} | ({"text"} if operation == "peer.draft_set" else set())
        if (not isinstance(params, dict) or set(params) != expected
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "peer"))
                or (operation == "peer.draft_set"
                    and (not isinstance(params["text"], str)
                         or len(params["text"].encode("utf-8")) > 16384))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in RELATIONSHIP_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "peer"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in INTENT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "peer"}
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None
                       for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params
    fields = {"runtime.capabilities": set(), "profile.query": {"profile"},
              "connection.snapshot": {"profile", "connection"},
              "peer.query": {"profile", "peer"},
              "message.query": {"profile", "message"}}[operation]
    params = value["params"]
    if (not isinstance(params, dict) or set(params) != fields
            or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None for item in params.values())):
        raise ApiFailure("invalid_request")
    return operation, params


def _diagnostic_params(params):
    if (not isinstance(params, dict) or set(params) != {"profile", "limit"}
            or not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None
            or type(params["limit"]) is not int or not 1 <= params["limit"] <= MAX_DIAGNOSTICS):
        raise ApiFailure("invalid_request")
    return params


def _acknowledgment_params(value):
    key, params = value["idempotency_key"], value["params"]
    if (not isinstance(key, str) or IDEMPOTENCY_KEY.fullmatch(key) is None
            or not isinstance(params, dict) or set(params) != {"profile", "cursor"}
            or not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None
            or not isinstance(params["cursor"], str) or CURSOR.fullmatch(params["cursor"]) is None):
        raise ApiFailure("invalid_request")
    return params


def _recovery_params(params):
    if (not isinstance(params, dict) or set(params) != {"profile", "cursor", "limit"}
            or not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None
            or type(params["limit"]) is not int or not 1 <= params["limit"] <= MAX_BATCH
            or (params["cursor"] is not None and (not isinstance(params["cursor"], str)
                or CURSOR.fullmatch(params["cursor"]) is None))):
        raise ApiFailure("invalid_request")
    return params


def _enqueue_params(value):
    key = value["idempotency_key"]
    params = value["params"]
    if (not isinstance(key, str) or IDEMPOTENCY_KEY.fullmatch(key) is None
            or not isinstance(params, dict) or set(params) != {"profile", "recipient", "kind", "text"}
            or params["kind"] != "text"
            or any(not isinstance(params[name], str) or HANDLE.fullmatch(params[name]) is None
                   for name in ("profile", "recipient"))):
        raise ApiFailure("invalid_request")
    try:
        validate_chat_text(params["text"])
    except ValidationError as error:
        raise ApiFailure("invalid_request") from error
    return params


# The order in which a fully bound session advertises its operations. It is not
# part of the public contract (clients compare membership), so this tuple is the
# single place that knows the composition order.
COMPONENT_OPERATIONS = (
    OPERATIONS
    + MESSAGE_OPERATIONS
    + RECOVERY_OPERATIONS
    + RECEIVED_OPERATIONS
    + INTENT_OPERATIONS
    + RELATIONSHIP_OPERATIONS
    + DRAFT_OPERATIONS
    + CALL_OPERATIONS
    + SETTINGS_OPERATIONS
    + REACTION_OPERATIONS
    + GROUP_OPERATIONS
    + PAIRING_OPERATIONS
    + REQUEST_OPERATIONS
    + INVITATION_OPERATIONS
    + STOP_OPERATIONS
    + APPLICATION_OPERATIONS
    + WORKSPACE_PREVIEW_OPERATIONS
    + WORKSPACE_JOIN_OPERATIONS
    + WORKSPACE_LIST_OPERATIONS
    + WORKSPACE_REQUESTS_OPERATIONS
    + WORKSPACE_APPROVE_OPERATIONS
    + WORKSPACE_DECLINE_OPERATIONS
    + WORKSPACE_MEMBERS_OPERATIONS
    + WORKSPACE_ROLE_OPERATIONS
    + WORKSPACE_INVITATION_CREATE_OPERATIONS
    + WORKSPACE_CHANNELS_OPERATIONS
    + WORKSPACE_CHANNEL_CREATE_OPERATIONS
    + WORKSPACE_CHANNEL_MEMBERS_OPERATIONS
    + WORKSPACE_CHANNEL_MEMBERS_UPDATE_OPERATIONS
    + WORKSPACE_CHANNEL_UPDATE_OPERATIONS
    + WORKSPACE_CHANNEL_ARCHIVE_OPERATIONS
    + WORKSPACE_DEVICE_LINK_CREATE_OPERATIONS
    + WORKSPACE_DEVICE_LINK_PREVIEW_OPERATIONS
    + WORKSPACE_DEVICE_LINK_SUBMIT_OPERATIONS
    + WORKSPACE_DEVICE_LINKS_OPERATIONS
    + WORKSPACE_DEVICE_LINK_APPROVE_OPERATIONS
    + WORKSPACE_DEVICE_LINK_DECLINE_OPERATIONS
    + WORKSPACE_CHANNEL_TRANSFER_OFFER_OPERATIONS
    + WORKSPACE_CHANNEL_TRANSFER_ACCEPT_OPERATIONS
    + WORKSPACE_POLICY_UPDATE_OPERATIONS
    + WORKSPACE_METADATA_OPERATIONS
    + WORKSPACE_RETENTION_OPERATIONS
    + WORKSPACE_ADMIN_REQUEST_OPERATIONS
    + WORKSPACE_LIFECYCLE_OPERATIONS
    + WORKSPACE_AUTHORITY_LOSS_OPERATIONS
    + WORKSPACE_AUTHORITY_OPERATIONS
    + WORKSPACE_AUTHORITY_OFFER_OPERATIONS
    + WORKSPACE_EDGE_OPERATIONS
    + WORKSPACE_ADMISSION_OPERATIONS
    + WORKSPACE_DEVICES_OPERATIONS
    + WORKSPACE_DEVICE_REMOVE_OPERATIONS
    + WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS
    + WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS
    + DIAGNOSTIC_OPERATIONS
)
