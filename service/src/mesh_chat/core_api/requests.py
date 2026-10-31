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
RELATIONSHIP_OPERATIONS = ("peer.approve", "peer.revoke")
PAIRING_OPERATIONS = ("peer.pairing_accept",)
INVITATION_OPERATIONS = ("peer.pairing_create",)
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
    if operation in ("message.enqueue", "events.ack"):
        fields.add("idempotency_key")
    if set(value) != fields:
        raise ApiFailure("invalid_request")
    if operation == "message.enqueue":
        return operation, _enqueue_params(value)
    if operation == "events.ack":
        return operation, _acknowledgment_params(value)
    if operation == "diagnostics.query":
        return operation, _diagnostic_params(value["params"])
    if operation in RECOVERY_OPERATIONS:
        return operation, _recovery_params(value["params"])
    if operation in RECEIVED_OPERATIONS:
        return operation, _recovery_params(value["params"])
    if operation in INVITATION_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None):
            raise ApiFailure("invalid_request")
        return operation, params
    if operation in PAIRING_OPERATIONS:
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != {"profile", "document"}
                or not isinstance(params["profile"], str)
                or HANDLE.fullmatch(params["profile"]) is None
                or not isinstance(params["document"], str)
                or not 1 <= len(params["document"]) <= 1048576):
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
