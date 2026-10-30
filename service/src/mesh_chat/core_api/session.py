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

from .views import (
    acceptance_view, acknowledgment_view, connection_view, event_view, message_view, peer_view, received_view,
)
from .errors import ApiFailure
from .limits import MAX_FRAME_BYTES, MAX_REQUEST_JSON_DEPTH, MAX_REQUEST_JSON_TOKENS
from .diagnostics import Diagnostics, MAX_DIAGNOSTICS, MAX_DIAGNOSTIC_BYTES
from .diagnostic_views import diagnostics_view
from .requests import (
    CURSOR, DIAGNOSTIC_OPERATIONS, MESSAGE_OPERATIONS, OPERATIONS, RECEIVED_OPERATIONS,
    RECOVERY_OPERATIONS, REQUEST_ID, parse_request,
)
from .messages import (
    IDEMPOTENCY_SECONDS, MAX_CALLER_ENQUEUES, MAX_PEERS, MAX_VAULT_ENQUEUES,
    MessageScope, Messages,
)
from .recovery import (
    MAX_BATCH, MAX_BATCH_BYTES, MAX_CALLER_ACKNOWLEDGMENTS, MAX_CURSOR_BYTES,
    MAX_VAULT_ACKNOWLEDGMENTS, ReceivedLog, Recovery,
)
from ..message_journal import MAX_EVENTS, RETENTION_SECONDS


MAX_PROFILES = 256
MAX_CONNECTIONS = 256


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
                 messages: Messages | None = None, recovery: Recovery | None = None,
                 diagnostics: Diagnostics | None = None, received: ReceivedLog | None = None):
        if not isinstance(handle_key, bytes) or not 32 <= len(handle_key) <= 64:
            raise ValueError("A protected handle key is required")
        self._authorize = authorize
        self._observations = observations
        self._messages = messages
        self._recovery = recovery
        self._diagnostics = diagnostics
        self._received = received
        self._operations = (OPERATIONS + (MESSAGE_OPERATIONS if messages is not None else ())
                            + (RECOVERY_OPERATIONS if recovery is not None else ())
                            + (RECEIVED_OPERATIONS if received is not None else ())
                            + (DIAGNOSTIC_OPERATIONS if diagnostics is not None else ()))
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
                operation, params = parse_request(value, self._operations)
                permission = {"message.enqueue": "send", "message.query": "read", "message.list": "read",
                              "message.received": "read", "events.poll": "read", "events.ack": "read",
                              "diagnostics.query": "diagnose"}.get(operation, "observe")
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
        if operation == "diagnostics.query":
            return diagnostics_view(params["profile"], self._diagnostics.query(profile), params["limit"],
                                    lambda internal: self._handle(grant, "connection", profile, internal))
        if operation in MESSAGE_OPERATIONS:
            return self._message(grant, profile, operation, params, key)
        if operation in RECEIVED_OPERATIONS:
            return self._received_messages(grant, profile, params)
        if operation in RECOVERY_OPERATIONS:
            return self._recover(grant, profile, operation, params, key)
        return self._observe(grant, profile, operation, params)

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
