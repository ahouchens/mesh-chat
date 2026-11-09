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
RECOVERY_TRANSFER_OPERATIONS = ("recovery.transfer",)
RECEIVED_OPERATIONS = ("message.received",)
INTENT_OPERATIONS = ("connection.start", "connection.stop")
RELATIONSHIP_OPERATIONS = ("peer.approve", "peer.revoke", "peer.unblock", "peer.delete", "peer.update", "peer.decide")
DRAFT_OPERATIONS = ("peer.draft_get", "peer.draft_set")
CALL_CONTROL_OPERATIONS = ("call.control",)
CALL_OPERATIONS = ("call.settings_query", "call.settings_update", "call.ice_servers",
                    "call.media_query")
SETTINGS_OPERATIONS = ("settings.query", "settings.update")
REACTION_OPERATIONS = ("message.reaction_set",)
GROUP_DRAFT_OPERATIONS = ("group.draft_set",)
GROUP_OPERATIONS = ("group.query", "group.create", "group.message_enqueue",
                    "group.leave", "group.close", "group.member_remove",
                    "group.invitation_accept", "group.invitation_decline",
                    "group.invitation_retry")
PAIRING_OPERATIONS = ("peer.pairing_accept",)
PAIRING_PREVIEW_OPERATIONS = ("peer.pairing_preview",)
CONTACT_INVITATION_OPERATIONS = ("contact.invitation",)
REQUEST_OPERATIONS = ("peer.pairing_request",)
INVITATION_OPERATIONS = ("peer.pairing_create",)
STOP_OPERATIONS = ("runtime.stop",)
APPLICATION_OPERATIONS = ("application.snapshot",)
NATIVE_COMMAND_OPERATIONS = ("native.command",)
PROFILE_CREATE_OPERATIONS = ("profile.create",)
BOOTSTRAP_PREVIEW_OPERATIONS = ("bootstrap.preview",)
WORKSPACE_PREVIEW_OPERATIONS = ("workspace.invitation_preview",)
WORKSPACE_JOIN_OPERATIONS = ("workspace.join",)
WORKSPACE_PROMPT_JOIN_OPERATIONS = ("workspace.join_prompt",)
WORKSPACE_CREATE_OPERATIONS = ("workspace.create",)
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
WORKSPACE_CHANNEL_RECOVER_OPERATIONS = ("workspace.channel_recover",)
WORKSPACE_CHANNEL_STATE_OPERATIONS = ("workspace.channel_state",)
WORKSPACE_MEMBER_REMOVE_OPERATIONS = ("workspace.member_remove",)
WORKSPACE_DRAFT_OPERATIONS = ("workspace.draft_set",)
REMOTE_PROFILE_OPERATIONS = ("remote_profile.mutate",)
REMOTE_PROFILE_QUERY_OPERATIONS = ("remote_profile.query",)
WORKSPACE_DISPLAY_DECIDE_OPERATIONS = ("workspace.display_name_decide",)
WORKSPACE_DIRECT_OPEN_OPERATIONS = ("workspace.direct_open",)
ROUTE_UPDATE_OPERATIONS = ("route.update",)
CONVERSATION_OPERATIONS = ("conversation.mutate",)
LINK_PREVIEW_OPERATIONS = ("link.preview",)
CONNECTION_SUPPORT_OPERATIONS = ("connection.support",)
CONNECTION_DOCUMENT_OPERATIONS = ("connection.document",)
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
WORKSPACE_ACCESS_OPERATIONS = ("workspace.access_recommendation",)
WORKSPACE_HISTORY_OPERATIONS = ("workspace.history",)
WORKSPACE_CONNECTION_OPERATIONS = ("workspace.connection",)
RUNTIME_QUERY_OPERATIONS = ("runtime.query",)
RUNTIME_MUTATION_OPERATIONS = ("runtime.mutate",)
WORKSPACE_SNAPSHOT_OPERATIONS = ("workspace.snapshot",)
WORKSPACE_TIMELINE_OPERATIONS = ("workspace.timeline_query",
                                "workspace.timeline_mutation")
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
    WORKSPACE_PROMPT_JOIN_OPERATIONS,
    WORKSPACE_CHANNEL_RECOVER_OPERATIONS,
    WORKSPACE_CHANNEL_STATE_OPERATIONS,
    WORKSPACE_MEMBER_REMOVE_OPERATIONS,
    WORKSPACE_DRAFT_OPERATIONS,
    REMOTE_PROFILE_OPERATIONS,
    REMOTE_PROFILE_QUERY_OPERATIONS,
    WORKSPACE_DISPLAY_DECIDE_OPERATIONS,
    WORKSPACE_DIRECT_OPEN_OPERATIONS,
    ROUTE_UPDATE_OPERATIONS,
    CONVERSATION_OPERATIONS,
    LINK_PREVIEW_OPERATIONS,
    CONNECTION_SUPPORT_OPERATIONS,
    CONNECTION_DOCUMENT_OPERATIONS,
    WORKSPACE_METADATA_OPERATIONS,
    WORKSPACE_RETENTION_OPERATIONS,
    WORKSPACE_AUTHORITY_LOSS_OPERATIONS,
    WORKSPACE_AUTHORITY_OPERATIONS,
    WORKSPACE_AUTHORITY_OFFER_OPERATIONS,
    WORKSPACE_ACCESS_OPERATIONS,
    WORKSPACE_HISTORY_OPERATIONS,
    WORKSPACE_CONNECTION_OPERATIONS,
    RUNTIME_QUERY_OPERATIONS,
    RUNTIME_MUTATION_OPERATIONS,
    WORKSPACE_SNAPSHOT_OPERATIONS,
    WORKSPACE_TIMELINE_OPERATIONS,
    WORKSPACE_ADMISSION_OPERATIONS,
    WORKSPACE_EDGE_OPERATIONS,
    WORKSPACE_LIFECYCLE_OPERATIONS,
    WORKSPACE_ADMIN_REQUEST_OPERATIONS,
    WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS,
    WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS,
    WORKSPACE_PREVIEW_OPERATIONS,
    WORKSPACE_JOIN_OPERATIONS,
    WORKSPACE_CREATE_OPERATIONS,
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


# Envelope identity is defined once for parsing and session admission. Contract
# tests bind this inventory to operations-v1.json, including composite operations.
KEYED_OPERATIONS = frozenset({
    "call.control",
    "connection.retry",
    "events.ack",
    "message.enqueue",
    "profile.create",
    "profile.lock",
    "profile.select",
    "profile.unlock",
    "remote_profile.mutate",
    "route.update",
    "runtime.mutate",
    "workspace.access_recommendation",
    "workspace.admin_request_approve",
    "workspace.admin_request_cancel",
    "workspace.admin_request_decline",
    "workspace.admin_request_dismiss",
    "workspace.admin_request_submit",
    "workspace.admission_grant_accept",
    "workspace.admission_grant_create",
    "workspace.admission_grant_end",
    "workspace.admission_grant_list",
    "workspace.authority_accept",
    "workspace.authority_finalize",
    "workspace.authority_loss_report",
    "workspace.authority_offer",
    "workspace.channel_archive",
    "workspace.channel_create",
    "workspace.channel_members_update",
    "workspace.channel_recover",
    "workspace.channel_state",
    "workspace.channel_transfer_accept",
    "workspace.channel_transfer_offer",
    "workspace.channel_update",
    "workspace.close",
    "workspace.connection",
    "workspace.create",
    "workspace.device_link_approve",
    "workspace.device_link_create",
    "workspace.device_link_decline",
    "workspace.device_link_submit",
    "workspace.device_remove",
    "workspace.direct_open",
    "workspace.display_name_decide",
    "workspace.display_name_request",
    "workspace.draft_set",
    "workspace.history",
    "workspace.invitation_create",
    "workspace.invitation_revoke",
    "workspace.join",
    "workspace.join_approve",
    "workspace.join_decline",
    "workspace.join_prompt",
    "workspace.leave",
    "workspace.member_remove",
    "workspace.member_role",
    "workspace.metadata_update",
    "workspace.policy_update",
    "workspace.read_hint_sync",
    "workspace.remove_data",
    "workspace.retention_update",
    "workspace.timeline_mutation",
})

OPTIONAL_KEY_OPERATIONS = frozenset({
    "workspace.access_recommendation", "workspace.history", "workspace.connection",
    "group.draft_set", "peer.update", "conversation.mutate", "peer.decide",
    "link.preview", "contact.invitation", "recovery.transfer", "connection.support",
    "remote_profile.query", "connection.document", "peer.pairing_preview",
})


def parse_request(value, operations):
    try:
        return _parse_request(value, operations)
    except (KeyError, TypeError, ValueError) as error:
        raise ApiFailure("invalid_request") from error


def _parse_request(value, operations):
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
    if operation in KEYED_OPERATIONS - OPTIONAL_KEY_OPERATIONS or (
            operation in OPTIONAL_KEY_OPERATIONS and "idempotency_key" in value):
        fields.add("idempotency_key")
    if set(value) != fields:
        raise ApiFailure("invalid_request")
    if "idempotency_key" in value:
        key = value["idempotency_key"]
        if not isinstance(key, str) or IDEMPOTENCY_KEY.fullmatch(key) is None:
            raise ApiFailure("invalid_request")
    params = value["params"]
    if not isinstance(params, dict):
        raise ApiFailure("invalid_request")
    if "profile" in params and (not isinstance(params["profile"], str)
                                or HANDLE.fullmatch(params["profile"]) is None):
        raise ApiFailure("invalid_request")
    if "workspace" in params and (not isinstance(params["workspace"], str)
                                  or HANDLE.fullmatch(params["workspace"]) is None):
        raise ApiFailure("invalid_request")
    if operation == "group.draft_set" and (
            not isinstance(params.get("group"), str)
            or HANDLE.fullmatch(params["group"]) is None):
        raise ApiFailure("invalid_request")
    _component_field_bounds(operation, params)
    if operation == "message.enqueue":
        return operation, _enqueue_params(value)
    if operation == "events.ack":
        return operation, _acknowledgment_params(value)
    if operation == "diagnostics.query":
        return operation, _diagnostic_params(value["params"])
    if operation in PROFILE_CREATE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"display_name"}
                or not isinstance(params["display_name"], str)
                or not 1 <= len(params["display_name"].strip()) <= 80):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in BOOTSTRAP_PREVIEW_OPERATIONS:
        if (set(params) != {"kind", "document"}
                or params["kind"] not in {"personal", "workspace", "device_link"}
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"].encode("utf-8")) <= 1048576):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in APPLICATION_OPERATIONS:
        params = value["params"]
        if params != {}:
            raise ApiFailure("invalid_request")
        return operation, {}
    if operation in NATIVE_COMMAND_OPERATIONS:
        params = value["params"]
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
    if operation in WORKSPACE_CONNECTION_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        allowed = {
            "reconnect_status": {"profile", "workspace", "action"},
            "reconnect_consent": {"profile", "workspace", "action",
                                  "auto_reconnect", "allow_direct_ip_disclosure",
                                  "relay_consent_scope"},
            "invite_contact": {"profile", "workspace", "action", "contact_id"},
            "prompt_preview": {"profile", "action", "prompt_id"},
            "prompt_submit": {"profile", "action", "prompt_id"},
            "prompt_dismiss": {"profile", "action", "prompt_id"},
            "device_link_preview": {"profile", "action", "device_link"},
        }
        if not isinstance(params, dict) or action not in allowed or set(params) != allowed[action]:
            raise ApiFailure("invalid_request")
        if not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None:
            raise ApiFailure("invalid_request")
        if "workspace" in params and (not isinstance(params["workspace"], str)
                                      or HANDLE.fullmatch(params["workspace"]) is None):
            raise ApiFailure("invalid_request")
        if action == "reconnect_consent" and (type(params["auto_reconnect"]) is not bool
                                              or type(params["allow_direct_ip_disclosure"]) is not bool
                                              or params["relay_consent_scope"] not in {"workspace", "profile"}):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_HISTORY_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        required = {"profile", "workspace", "action"}
        optional = set()
        if action in {"status", "start", "cancel"}:
            required |= {"conversation"}
        elif action == "prune":
            optional |= {"max_events"}
        elif action == "revisions":
            required |= {"event_id"}
            optional |= {"cursor", "limit"}
        elif action == "tombstones":
            required |= {"conversation"}
            optional |= {"cursor", "limit"}
        elif action == "hide_message":
            required |= {"event_id"}
        elif action == "hide_direct":
            required |= {"conversation"}
        if (not isinstance(params, dict) or action not in {"status", "prune", "revisions",
                                                          "tombstones", "hide_message", "hide_direct",
                                                          "start", "cancel"}
                or not required <= set(params) or set(params) - required - optional):
            raise ApiFailure("invalid_request")
        if any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
               for key in ("profile", "workspace")):
            raise ApiFailure("invalid_request")
        if "max_events" in params and (type(params["max_events"]) is not int
                                  or not 1 <= params["max_events"] <= 5000):
            raise ApiFailure("invalid_request")
        if "limit" in params and (type(params["limit"]) is not int
                                  or not 1 <= params["limit"] <= 100):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_ACCESS_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        required = {"profile", "workspace", "action"}
        optional = set()
        if action in {"create"}:
            optional |= {"remote_profile_id", "lifetime_days"}
        elif action in {"send", "preview"}:
            required |= {"recommendation"}
        elif action in {"preview_by_id", "apply_by_id"}:
            required |= {"recommendation_id"}
        elif action in {"apply"}:
            required |= {"recommendation", "consent"}
        if action == "apply_by_id":
            required |= {"consent"}
        if (not isinstance(params, dict) or action not in {"list", "create", "send", "preview",
                                                          "preview_by_id", "apply", "apply_by_id"}
                or not required <= set(params) or set(params) - required - optional):
            raise ApiFailure("invalid_request")
        if any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
               for key in ("profile", "workspace")):
            raise ApiFailure("invalid_request")
        if action == "create" and (type(params.get("lifetime_days", 7)) is not int
                                   or not 1 <= params.get("lifetime_days", 7) <= 90):
            raise ApiFailure("invalid_request")
        if action in {"apply", "apply_by_id"} and type(params["consent"]) is not bool:
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in RUNTIME_QUERY_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "action"}
                or params["action"] not in {"background", "notifications"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in RUNTIME_MUTATION_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        allowed = {"background_set": {"profile", "action", "enabled"},
                   "notification_previews": {"profile", "action", "hidden"},
                   "notification_open": {"profile", "action", "notification_id"}}
        if not isinstance(params, dict) or action not in allowed or set(params) != allowed[action]:
            raise ApiFailure("invalid_request")
        if action == "background_set" and type(params["enabled"]) is not bool:
            raise ApiFailure("invalid_request")
        if action == "notification_previews" and type(params["hidden"]) is not bool:
            raise ApiFailure("invalid_request")
        if action == "notification_open" and (not isinstance(params["notification_id"], str)
                                              or not 1 <= len(params["notification_id"]) <= 160):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_SNAPSHOT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in RECOVERY_TRANSFER_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        required = {"profile", "action"} | ({"identifier"} if action == "export"
                                              else {"document", "workspace_id"})
        if (action not in {"export", "import"} or not isinstance(params, dict)
                or set(params) != required
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or any(not isinstance(params[key], str) or not params[key]
                       for key in required - {"profile", "action"})):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_TIMELINE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or not isinstance(params.get("profile"), str)
                or not isinstance(params.get("workspace"), str)
                or HANDLE.fullmatch(params["profile"]) is None
                or HANDLE.fullmatch(params["workspace"]) is None):
            raise ApiFailure("invalid_request")
        if operation == "workspace.timeline_query":
            view = params.get("view")
            allowed = {"profile", "workspace", "view", "cursor", "limit",
                       "thread_root", "query", "scope", "channel", "conversation"}
            if view not in {"threads", "thread_messages", "mentions", "search",
                            "channel_messages", "direct_messages"}:
                raise ApiFailure("invalid_request")
            if set(params) - allowed:
                raise ApiFailure("invalid_request")
            if view == "channel_messages" and not isinstance(params.get("channel"), str):
                raise ApiFailure("invalid_request")
            if view == "direct_messages" and not isinstance(params.get("conversation"), str):
                raise ApiFailure("invalid_request")
            if view in {"thread_messages"} and not isinstance(params.get("thread_root"), str):
                raise ApiFailure("invalid_request")
            if view == "search" and (not isinstance(params.get("query"), str)
                                     or not 2 <= len(params["query"]) <= 200):
                raise ApiFailure("invalid_request")
            if "cursor" in params and params["cursor"] is not None and not isinstance(params["cursor"], str):
                raise ApiFailure("invalid_request")
            if "limit" in params and (type(params["limit"]) is not int
                                      or not 1 <= params["limit"] <= 100):
                raise ApiFailure("invalid_request")
            return operation, params
        action = params.get("action")
        if action not in {"thread_reply", "thread_read", "mentions_read",
                          "notification_preference", "workspace_read", "direct_read",
                          "channel_message", "direct_message",
                          "message_edit", "message_delete", "reaction_set"}:
            raise ApiFailure("invalid_request")
        required = {"profile", "workspace", "action"}
        if action == "message_edit":
            required |= {"event_id", "mutation_event_id", "text"}
        elif action == "message_delete":
            required |= {"event_id", "mutation_event_id"}
        elif action == "reaction_set":
            required |= {"event_id", "mutation_event_id", "emoji", "active"}
        elif action in {"channel_message", "direct_message"}:
            required |= {"conversation", "text", "event_id"}
        elif action == "thread_reply":
            required |= {"conversation", "thread_root", "text", "event_id"}
        elif action == "thread_read":
            required |= {"thread_root", "high_water"}
        elif action == "mentions_read":
            required |= {"high_water"}
        elif action == "workspace_read":
            required |= {"channel", "high_water"}
        elif action == "direct_read":
            required |= {"conversation", "high_water"}
        else:
            required |= {"conversation", "mode"}
        allowed = required | ({"mention_member_ids"}
                              if action in {"channel_message", "direct_message", "message_edit"}
                              else set())
        if not required <= set(params) or set(params) - allowed:
            raise ApiFailure("invalid_request")
        for key in required - {"profile", "workspace", "action", "high_water",
                                "text", "event_id", "mode", "mutation_event_id",
                                "emoji", "active"}:
            if key == "conversation" and action == "notification_preference" and params[key] is None:
                continue
            if not isinstance(params[key], str):
                raise ApiFailure("invalid_request")
        if action == "reaction_set" and type(params["active"]) is not bool:
            raise ApiFailure("invalid_request")
        if action == "message_edit" and (
                not isinstance(params["text"], str)
                or not params["text"].strip()
                or len(params["text"].encode("utf-8")) > 16384):
            raise ApiFailure("invalid_request")
        if action in {"channel_message", "direct_message"} and (
                not isinstance(params["text"], str)
                or not params["text"].strip()
                or len(params["text"].encode("utf-8")) > 16384
                or ("mention_member_ids" in params
                    and (not isinstance(params["mention_member_ids"], list)
                         or any(not isinstance(item, str)
                                for item in params["mention_member_ids"])))):
            raise ApiFailure("invalid_request")
        if action == "thread_reply" and (not isinstance(params["text"], str)
                                        or not params["text"].strip()
                                        or len(params["text"].encode("utf-8")) > 16384):
            raise ApiFailure("invalid_request")
        if action == "notification_preference" and params["mode"] not in {
                "all", "mentions", "none", "mentions_only", "muted"}:
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
                    or not 1 <= params["max_admissions"] <= 5
                    or type(params["lifetime_days"]) is not int
                    or not 1 <= params["lifetime_days"] <= 7
                    or type(params["v2_ready"]) is not bool):
                raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_EDGE_OPERATIONS:
        params = value["params"]
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
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "transition_kind",
                                   "successor_member", "successor_device",
                                   "outgoing_owner_role"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "successor_member", "successor_device"))
                or params["transition_kind"] not in {"ownership_transfer", "same_owner_rotation"}
                or params["outgoing_owner_role"] not in {"admin", "member"}):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_AUTHORITY_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "transition"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "transition"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_AUTHORITY_LOSS_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_LIFECYCLE_OPERATIONS:
        params = value["params"]
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
        if (not isinstance(params, dict)
                or not {"profile", "document"} <= set(params)
                or set(params) - {"profile", "document", "i2p_consent"}
                or ("i2p_consent" in params and type(params["i2p_consent"]) is not bool)
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
    if operation in CONNECTION_DOCUMENT_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        if action == "preview_direct": required = {"profile", "action", "document"}
        elif action == "create_reply": required = {"profile", "action", "invitation", "purpose"}
        elif action == "preview_reply": required = {"profile", "action", "response"}
        else: raise ApiFailure("invalid_request")
        if (not isinstance(params, dict) or set(params) != required
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or (action == "create_reply" and params["purpose"] not in {"personal", "workspace"})
                or any(not isinstance(params[key], str) or not params[key]
                       for key in required - {"profile", "action"})):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in CONNECTION_SUPPORT_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        required = {"profile", "action"}
        if action == "help": required.add("contact_id")
        if action not in {"help", "diagnostics", "clear"} or not isinstance(params, dict) \
                or set(params) != required \
                or not isinstance(params["profile"], str) \
                or HANDLE.fullmatch(params["profile"]) is None \
                or (action == "help" and (not isinstance(params["contact_id"], str)
                                          or not params["contact_id"])):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in LINK_PREVIEW_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "provider", "identifier"}
                or any(not isinstance(params[key], str) or not params[key]
                       for key in ("profile", "provider", "identifier"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in CONVERSATION_OPERATIONS:
        params = value["params"]
        expected = {"profile", "action", "kind", "target_id"}
        if params.get("action") == "reaction_set" if isinstance(params, dict) else False:
            expected |= {"message_id", "emoji", "active"}
        if (not isinstance(params, dict)
                or set(params) != expected
                or params["action"] not in {"delete", "restore", "reaction_set"}
                or params["kind"] not in {"direct", "group"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["target_id"], str) or not params["target_id"]):
            raise ApiFailure("invalid_request")
        if params["action"] == "reaction_set" and (
                not isinstance(params["message_id"], str) or not params["message_id"]
                or not isinstance(params["emoji"], str) or not 1 <= len(params["emoji"]) <= 16
                or type(params["active"]) is not bool):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in ROUTE_UPDATE_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        if action not in {"preview", "apply", "create"}:
            raise ApiFailure("invalid_request")
        required = {"profile", "action"}
        required |= ({"update"} if action in {"preview", "apply"}
                     else {"scope_kind", "scope_id"})
        optional = {"peer_destination"} if action == "create" else set()
        if (not isinstance(params, dict) or not required <= set(params) or set(params) - required - optional
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        if action in {"preview", "apply"}:
            if not isinstance(params["update"], str) or not 1 <= len(params["update"]) <= 1048576:
                raise ApiFailure("invalid_request")
        else:
            if (params["scope_kind"] not in {"contact", "workspace_device"}
                    or not isinstance(params["scope_id"], str) or not params["scope_id"]):
                raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DIRECT_OPEN_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "member"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "member"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DISPLAY_DECIDE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "request", "approve"}
                or any(not isinstance(params[key], str) or not params[key]
                       for key in ("profile", "workspace", "request"))
                or type(params["approve"]) is not bool):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in REMOTE_PROFILE_QUERY_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in REMOTE_PROFILE_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        if action not in {"create", "test", "retry", "remove", "remove_propagation",
                          "approve_propagation"}:
            raise ApiFailure("invalid_request")
        allowed = {"profile", "action"}
        optional = set()
        if action == "create":
            allowed |= {"label", "endpoints"}
            optional |= {"propagation_node", "allow_private"}
        else:
            allowed |= {"remote_profile_id"}
        if not isinstance(params, dict) or not allowed <= set(params) or set(params) - allowed - optional:
            raise ApiFailure("invalid_request")
        if not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None:
            raise ApiFailure("invalid_request")
        if action == "create":
            endpoints = params["endpoints"]
            if (not isinstance(params["label"], str) or not params["label"].strip()
                    or not isinstance(endpoints, list) or not 1 <= len(endpoints) <= 8
                    or any(not isinstance(item, dict)
                           or set(item) != {"host", "port"}
                           or not isinstance(item["host"], str)
                           or not 1 <= len(item["host"]) <= 255
                           or type(item["port"]) is not int
                           or not 1 <= item["port"] <= 65535
                           for item in endpoints)
                    or (params.get("propagation_node") is not None
                        and (not isinstance(params["propagation_node"], str)
                             or len(params["propagation_node"]) > 32))
                    or type(params.get("allow_private", False)) is not bool):
                raise ApiFailure("invalid_request")
        elif not isinstance(params["remote_profile_id"], str) or not params["remote_profile_id"]:
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_DRAFT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or not {"profile", "workspace", "conversation", "text"} <= set(params)
                or set(params) - {"profile", "workspace", "conversation", "text",
                                  "thread_root", "mention_member_ids"}
                or not isinstance(params["conversation"], str) or not params["conversation"]
                or not isinstance(params["text"], str)
                or len(params["text"].encode("utf-8")) > 16384
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace"))
                or ("thread_root" in params and (not isinstance(params["thread_root"], str)
                                                 or not params["thread_root"]))
                or ("mention_member_ids" in params
                    and (not isinstance(params["mention_member_ids"], list)
                         or any(not isinstance(item, str) for item in params["mention_member_ids"])))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_MEMBER_REMOVE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "workspace", "member"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "member"))):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_STATE_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        if action not in {"subscribe", "mute", "leave", "sync"}:
            raise ApiFailure("invalid_request")
        allowed = {"profile", "workspace", "action"}
        if action != "sync":
            allowed.add("channel")
        if action == "subscribe":
            allowed.add("subscribed")
        elif action == "mute":
            allowed.add("muted")
        if not isinstance(params, dict) or set(params) != allowed:
            raise ApiFailure("invalid_request")
        if any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
               for key in ("profile", "workspace")):
            raise ApiFailure("invalid_request")
        if "channel" in params and (not isinstance(params["channel"], str)
                                     or HANDLE.fullmatch(params["channel"]) is None):
            raise ApiFailure("invalid_request")
        if action == "subscribe" and type(params["subscribed"]) is not bool:
            raise ApiFailure("invalid_request")
        if action == "mute" and type(params["muted"]) is not bool:
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_CHANNEL_RECOVER_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "workspace", "channel"}
                or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                       for key in ("profile", "workspace", "channel"))):
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
    if operation in WORKSPACE_CREATE_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict)
                or set(params) != {"profile", "name", "description"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["name"], str) or not 1 <= len(params["name"].strip()) <= 64
                or not isinstance(params["description"], str)
                or len(params["description"].strip()) > 250):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in WORKSPACE_PROMPT_JOIN_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "prompt"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["prompt"], str) or not params["prompt"]):
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
    if operation in CONTACT_INVITATION_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        if action == "receive":
            required = {"profile", "action", "document", "peer"}
            allowed = required | {"workspace_document"}
        elif action == "decide":
            required = {"profile", "action", "invitation", "accept"}
            allowed = required
        else:
            raise ApiFailure("invalid_request")
        if not isinstance(params, dict) or not required <= set(params) or set(params) - allowed:
            raise ApiFailure("invalid_request")
        if not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None:
            raise ApiFailure("invalid_request")
        if action == "receive":
            if (not isinstance(params["document"], str) or not params["document"]
                    or not isinstance(params["peer"], str) or not params["peer"]
                    or ("workspace_document" in params
                        and (not isinstance(params["workspace_document"], str)
                             or not params["workspace_document"]))):
                raise ApiFailure("invalid_request")
        elif not isinstance(params["invitation"], str) or type(params["accept"]) is not bool:
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in PAIRING_PREVIEW_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str) or not params["document"]):
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
    if operation in GROUP_DRAFT_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "group", "text"}
                or any(not isinstance(params[key], str) for key in ("profile", "group"))
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["text"], str)
                or len(params["text"].encode("utf-8")) > 16384):
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
    if operation in CALL_CONTROL_OPERATIONS:
        params = value["params"]
        action = params.get("action") if isinstance(params, dict) else None
        allowed = {
            "start": {"profile", "action", "contact_id", "media", "sdp", "dtls_fingerprint"},
            "answer": {"profile", "action", "call_id", "sdp", "dtls_fingerprint"},
            "restart": {"profile", "action", "call_id", "sdp", "dtls_fingerprint"},
            "answer_restart": {"profile", "action", "call_id", "sdp", "dtls_fingerprint"},
            "end": {"profile", "action", "call_id", "reason"},
            "candidate": {"profile", "action", "call_id", "candidate"},
            "signal_publish": {"profile", "action", "document", "role",
                               "session_id", "mailbox_token"},
            "signal_fetch": {"profile", "action", "session", "role", "mailbox_token"},
        }
        if not isinstance(params, dict) or action not in allowed:
            raise ApiFailure("invalid_request")
        required = allowed[action] - {"session_id", "mailbox_token"}
        if not required <= set(params) or set(params) - allowed[action]:
            raise ApiFailure("invalid_request")
        if not isinstance(params["profile"], str) or HANDLE.fullmatch(params["profile"]) is None:
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
        if operation == "peer.decide":
            if (not isinstance(params, dict)
                    or set(params) != {"profile", "peer", "accept"}
                    or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                           for key in ("profile", "peer"))
                    or type(params["accept"]) is not bool):
                raise ApiFailure("invalid_request")
            return operation, params
        if operation == "peer.update":
            action = params.get("action") if isinstance(params, dict) else None
            expected = {"profile", "peer", "action"}
            if action == "rename": expected.add("display_name")
            if (action not in {"rename", "verify", "unverify"}
                    or not isinstance(params, dict) or set(params) != expected
                    or any(not isinstance(params[key], str) or HANDLE.fullmatch(params[key]) is None
                           for key in ("profile", "peer"))
                    or (action == "rename" and (not isinstance(params["display_name"], str)
                                                or not 1 <= len(params["display_name"]) <= 80))):
                raise ApiFailure("invalid_request")
            return operation, params
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
    + RECOVERY_TRANSFER_OPERATIONS
    + RECEIVED_OPERATIONS
    + INTENT_OPERATIONS
    + RELATIONSHIP_OPERATIONS
    + DRAFT_OPERATIONS
    + CALL_OPERATIONS
    + CALL_CONTROL_OPERATIONS
    + SETTINGS_OPERATIONS
    + REACTION_OPERATIONS
    + GROUP_OPERATIONS
    + GROUP_DRAFT_OPERATIONS
    + PAIRING_OPERATIONS
    + PAIRING_PREVIEW_OPERATIONS
    + CONTACT_INVITATION_OPERATIONS
    + REQUEST_OPERATIONS
    + INVITATION_OPERATIONS
    + STOP_OPERATIONS
    + APPLICATION_OPERATIONS
    + NATIVE_COMMAND_OPERATIONS
    + PROFILE_CREATE_OPERATIONS
    + BOOTSTRAP_PREVIEW_OPERATIONS
    + WORKSPACE_PREVIEW_OPERATIONS
    + WORKSPACE_JOIN_OPERATIONS
    + WORKSPACE_PROMPT_JOIN_OPERATIONS
    + WORKSPACE_CREATE_OPERATIONS
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
    + WORKSPACE_CHANNEL_RECOVER_OPERATIONS
    + WORKSPACE_CHANNEL_STATE_OPERATIONS
    + WORKSPACE_MEMBER_REMOVE_OPERATIONS
    + WORKSPACE_DRAFT_OPERATIONS
    + REMOTE_PROFILE_OPERATIONS
    + REMOTE_PROFILE_QUERY_OPERATIONS
    + WORKSPACE_DISPLAY_DECIDE_OPERATIONS
    + WORKSPACE_DIRECT_OPEN_OPERATIONS
    + ROUTE_UPDATE_OPERATIONS
    + CONVERSATION_OPERATIONS
    + LINK_PREVIEW_OPERATIONS
    + CONNECTION_SUPPORT_OPERATIONS
    + CONNECTION_DOCUMENT_OPERATIONS
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
    + WORKSPACE_TIMELINE_OPERATIONS
    + WORKSPACE_SNAPSHOT_OPERATIONS
    + RUNTIME_QUERY_OPERATIONS
    + RUNTIME_MUTATION_OPERATIONS
    + WORKSPACE_ACCESS_OPERATIONS
    + WORKSPACE_HISTORY_OPERATIONS
    + WORKSPACE_CONNECTION_OPERATIONS
    + WORKSPACE_DEVICES_OPERATIONS
    + WORKSPACE_DEVICE_REMOVE_OPERATIONS
    + WORKSPACE_DEVICE_REMOVAL_DECIDE_OPERATIONS
    + WORKSPACE_DEVICE_REMOVAL_REQUEST_OPERATIONS
    + DIAGNOSTIC_OPERATIONS
)


# Composite operations share bounded field types; branches above enforce their
# action-specific required fields. Keep identifiers in public Core spelling.
_COMPONENT_STRING_LIMITS = {
    "workspace.timeline_query": {"conversation": 160, "channel": 160,
        "thread_root": 160, "cursor": 256},
    "workspace.timeline_mutation": {"conversation": 160, "channel": 160,
        "thread_root": 160, "high_water": 160, "event_id": 160,
        "mutation_event_id": 160, "emoji": 16},
    "workspace.draft_set": {"conversation": 160, "thread_root": 160},
    "workspace.display_name_decide": {"request": 160},
    "workspace.history": {"conversation": 160, "event_id": 160, "cursor": 256},
    "workspace.access_recommendation": {"remote_profile_id": 160,
        "recommendation": 8192, "recommendation_id": 160},
    "workspace.connection": {"contact_id": 160, "prompt_id": 160,
        "device_link": 16384},
    "remote_profile.mutate": {"remote_profile_id": 160, "label": 64},
    "route.update": {"scope_id": 160, "peer_destination": 160},
    "conversation.mutate": {"target_id": 160, "message_id": 160},
    "link.preview": {"identifier": 64},
    "contact.invitation": {"peer": 160, "invitation": 160},
    "recovery.transfer": {"identifier": 160, "workspace_id": 160},
    "workspace.join_prompt": {"prompt": 160},
    "call.control": {"contact_id": 160, "call_id": 160, "sdp": 65536,
        "dtls_fingerprint": 256, "reason": 64, "candidate": 4096,
        "document": 65536, "session": 256, "session_id": 256,
        "mailbox_token": 4096},
}


def _component_field_bounds(operation, params):
    for field, maximum in _COMPONENT_STRING_LIMITS.get(operation, {}).items():
        if field not in params:
            continue
        value = params[field]
        if field == "high_water" and type(value) is int and 0 <= value <= 2**53 - 1:
            continue
        if (value is None and operation == "workspace.timeline_mutation"
                and params.get("action") == "notification_preference"
                and field == "conversation"):
            continue
        if value is None and field in {"cursor", "remote_profile_id"}:
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= maximum:
            raise ApiFailure("invalid_request")
    if operation == "link.preview" and params.get("provider") not in {"youtube", "x"}:
        raise ApiFailure("invalid_request")
    if operation == "call.control":
        if "media" in params and params["media"] not in {"audio", "video"}:
            raise ApiFailure("invalid_request")
        if "role" in params and params["role"] not in {"caller", "callee", "offer", "answer"}:
            raise ApiFailure("invalid_request")
    if operation in {"workspace.timeline_mutation", "workspace.draft_set"} and "mention_member_ids" in params:
        mentions = params["mention_member_ids"]
        if (not isinstance(mentions, list) or len(mentions) > 32
                or any(not isinstance(item, str) or not 1 <= len(item) <= 160 for item in mentions)):
            raise ApiFailure("invalid_request")
