"""Scoped application requests after trusted host authentication.

This module does not authenticate IPC peers. A host must bind the authorizer to
an authenticated connection; callers never choose that function or its grants.
"""

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from threading import RLock
from typing import Protocol

from .views import acceptance_view, connection_view, message_view, peer_view
from .errors import ApiFailure
from .messages import (
    IDEMPOTENCY_SECONDS, MAX_CALLER_ENQUEUES, MAX_PEERS, MAX_VAULT_ENQUEUES,
    MessageScope, Messages,
)
from ..chat_text import validate_chat_text
from ..errors import ValidationError


OPERATIONS = ("runtime.capabilities", "profile.query", "connection.snapshot")
MESSAGE_OPERATIONS = ("peer.query", "message.enqueue", "message.query")
MAX_PROFILES = 256
MAX_CONNECTIONS = 256
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
HANDLE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{16,128}\Z")


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


class CoreSession:
    def __init__(self, authorize, observations: Observations, *, handle_key: bytes, transaction=None,
                 messages: Messages | None = None):
        if not isinstance(handle_key, bytes) or not 32 <= len(handle_key) <= 64:
            raise ValueError("A protected handle key is required")
        self._authorize = authorize
        self._observations = observations
        self._messages = messages
        self._operations = OPERATIONS + (MESSAGE_OPERATIONS if messages is not None else ())
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
                grant = self._grant()
                operation, params = self._parse(value)
                permission = {"message.enqueue": "send", "message.query": "read"}.get(operation, "observe")
                if permission not in grant.permissions:
                    raise ApiFailure("forbidden")
                result = self._execute(grant, operation, params, value.get("idempotency_key"))
                return {"api_version": 1, "request_id": request_id, "ok": True, "result": result}
            except ApiFailure as error:
                code = error.code
            except Exception:
                code = "internal"
        return {"api_version": 1, "request_id": request_id, "ok": False,
                "error": {"code": code, "retry_after_ms": None}}

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

    def _parse(self, value):
        if not isinstance(value, dict):
            raise ApiFailure("invalid_request")
        fields = {"api_version", "request_id", "operation", "params"}
        if value.get("operation") == "message.enqueue":
            fields.add("idempotency_key")
        if set(value) != fields:
            raise ApiFailure("invalid_request")
        if type(value["api_version"]) is not int or value["api_version"] != 1:
            raise ApiFailure("incompatible_version")
        identifier = value["request_id"]
        if not isinstance(identifier, str) or REQUEST_ID.fullmatch(identifier) is None:
            raise ApiFailure("invalid_request")
        operation = value["operation"]
        if not isinstance(operation, str) or operation not in self._operations:
            raise ApiFailure("unsupported_operation")
        if operation == "message.enqueue":
            return operation, self._enqueue_params(value)
        fields = {"runtime.capabilities": set(), "profile.query": {"profile"},
                  "connection.snapshot": {"profile", "connection"},
                  "peer.query": {"profile", "peer"},
                  "message.query": {"profile", "message"}}[operation]
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != fields
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params

    @staticmethod
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

    def _handle(self, grant, kind, profile, internal):
        material = json.dumps([grant.caller, kind, profile, internal], ensure_ascii=True,
                              separators=(",", ":")).encode("ascii")
        return hmac.new(self._handle_key, b"mesh-core-handle:v1:" + material, hashlib.sha256).hexdigest()

    def _execute(self, grant, operation, params, key=None):
        profiles = {self._handle(grant, "profile", profile, profile): profile for profile in grant.profiles}
        if operation == "runtime.capabilities":
            self._negotiated = True
            return self._capabilities(profiles)
        if not self._negotiated:
            raise ApiFailure("negotiation_required")
        profile = profiles.get(params["profile"])
        if profile is None:
            raise ApiFailure("forbidden")
        if operation in MESSAGE_OPERATIONS:
            return self._message(grant, profile, operation, params, key)
        return self._observe(grant, profile, operation, params)

    def _capabilities(self, profiles):
        limits = {"frame_bytes": 4194304, "profiles": MAX_PROFILES,
                  "connections_per_profile": MAX_CONNECTIONS}
        if self._messages is not None:
            limits.update(peers_per_profile=MAX_PEERS, text_utf8_bytes=16384,
                          idempotency_seconds=IDEMPOTENCY_SECONDS,
                          enqueue_keys_per_caller_profile=MAX_CALLER_ENQUEUES,
                          enqueue_keys_per_vault=MAX_VAULT_ENQUEUES)
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
