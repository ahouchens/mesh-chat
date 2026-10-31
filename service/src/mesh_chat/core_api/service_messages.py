"""Private service adapter. The host holds its dispatch lock for every operation.

Message, replay receipt, scoped query index and quota share one vault commit.
Only the existing durable outbox executes delivery; acceptance performs no I/O
on a peer transport and makes no delivery claim.
"""

from contextlib import contextmanager
import json
import sqlite3
import time

from ..chat_text import validate_chat_text
from ..errors import StorageUnavailable, ValidationError
from ..models import DeliveryState, MessageKind, TrustState
from .errors import ApiFailure
from .messages import (
    Acceptance, IDEMPOTENCY_SECONDS, MAX_CALLER_ENQUEUES, MAX_PEERS,
    MAX_VAULT_ENQUEUES, MessageObservation, PeerObservation,
)


@contextmanager
def storage_errors():
    try:
        yield
    except (StorageUnavailable, OSError, sqlite3.DatabaseError) as error:
        raise ApiFailure("unavailable") from error


class ServiceMessages:
    def __init__(self, service):
        self._service = service
        self._store = service.store

    def _profile(self, profile):
        if profile != "local":
            raise ApiFailure("forbidden")
        if self._service._identity is None:
            raise ApiFailure("locked")
        if self._store.get("profile", profile) is None:
            raise ApiFailure("not_found")

    def peers(self, profile):
        with storage_errors():
            self._profile(profile)
            contacts = self._store.items("contact", limit=MAX_PEERS + 1)
            if len(contacts) > MAX_PEERS:
                raise ApiFailure("resource_exhausted")
            return tuple(identifier for identifier, _ in contacts)

    def peer(self, profile, recipient):
        with storage_errors():
            self._profile(profile)
            contact = self._store.get("contact", recipient)
            if contact is None:
                raise ApiFailure("forbidden")
            return PeerObservation(contact["display_name"], contact["destination_hash"], contact["trust"])

    def _approved_contact(self, recipient):
        contact = self._store.get("contact", recipient)
        if contact is None or contact.get("trust") not in {TrustState.APPROVED.value, TrustState.VERIFIED.value}:
            raise ApiFailure("forbidden")
        return contact

    def _identifier(self, namespace, *parts):
        # One length-delimited value prevents caller/key delimiter ambiguity.
        return self._store.opaque_id(namespace, json.dumps(parts, ensure_ascii=True, separators=(",", ":")))

    def enqueue(self, scope, recipient, key, text):
        with storage_errors():
            self._profile(scope.profile)
            contact = self._approved_contact(recipient)
            try:
                validate_chat_text(text)
            except ValidationError as error:
                raise ApiFailure("invalid_request") from error
            identifier = self._identifier("core-api-enqueue:v1", scope.caller, scope.profile, "message.enqueue", key)
            digest = self._identifier("core-api-payload:v1", recipient, "text", text)
            previous = self._store.get("api_enqueue", identifier)
            if previous is not None:
                return self._replay(previous, digest)
            return self._commit(scope, contact, identifier, digest, text)

    def _replay(self, previous, digest):
        if previous["digest"] != digest:
            raise ApiFailure("idempotency_conflict")
        message = self._store.get("message", previous["message_id"])
        if previous["expires_at"] <= time.time() or message is None:
            raise ApiFailure("idempotency_expired")
        self._wake_outbox(message)
        return Acceptance(previous["handle"], previous["accepted_at"], previous["expires_at"])

    def _commit(self, scope, contact, identifier, digest, text):
        quota_id = self._identifier("core-api-enqueue-quota:v1", scope.caller, scope.profile)
        count = (self._store.get("api_enqueue_quota", quota_id) or {"count": 0})["count"]
        if count >= MAX_CALLER_ENQUEUES or self._store.record_count("api_enqueue") >= MAX_VAULT_ENQUEUES:
            raise ApiFailure("resource_exhausted")
        message = self._service._outbound_record(contact, MessageKind.CHAT, text)
        handle = self._identifier("core-api-message:v1", scope.caller, scope.profile, message["id"])
        accepted = message["created_at"]
        expires = accepted + IDEMPOTENCY_SECONDS
        receipt = {"digest": digest, "message_id": message["id"], "handle": handle,
                   "accepted_at": accepted, "expires_at": expires}
        index = {"caller": scope.caller, "profile": scope.profile, "message_id": message["id"]}
        self._store.put_and_delete([
            ("message", message["id"], message),
            ("api_enqueue", identifier, receipt),
            ("api_message", handle, index),
            ("api_enqueue_quota", quota_id, {"count": count + 1}),
        ], [("conversation_hidden", self._service._conversation_marker_id("direct", contact["id"]))])
        self._wake_outbox(message)
        return Acceptance(handle, accepted, expires)

    def _wake_outbox(self, message):
        # These hints follow the durable commit. Restart reconstructs the queue
        # from message records even if the process dies before either hint.
        try:
            if message["state"] == DeliveryState.QUEUED.value:
                self._service._queue_direct_retry(message["id"])
            self._service._changed()
        except Exception:
            pass  # Retry/restart recovers the outbox; acceptance is already durable.

    def query(self, scope, handle):
        with storage_errors():
            self._profile(scope.profile)
            index = self._store.get("api_message", handle)
            if index is None or (index["caller"], index["profile"]) != (scope.caller, scope.profile):
                raise ApiFailure("forbidden")
            message = self._store.get("message", index["message_id"])
            if message is None:
                raise ApiFailure("not_found")
            self._approved_contact(message["contact_id"])
            if message["kind"] != MessageKind.CHAT.value or message["direction"] != "outbound":
                raise ApiFailure("internal")
            validate_chat_text(message["text"])
            state = DeliveryState(message["state"]).value
            return MessageObservation(message["contact_id"], message["text"], state, message["created_at"])
