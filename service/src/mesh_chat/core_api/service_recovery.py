"""Private storage adapter for consistent snapshots and retained message changes."""

import json
import math
import time

from ..errors import StorageUnavailable, ValidationError
from ..message_journal import JournalGap, RETENTION_SECONDS
from ..models import TrustState
from .errors import ApiFailure
from .messages import MAX_PEERS
from .recovery import EventPage, ListedMessage, MAX_BATCH, MAX_BATCH_BYTES, MessageEvent, MessagePage
from .service_messages import storage_errors


class ServiceRecovery:
    def __init__(self, service, messages):
        self._store = service.store
        self._journal = service._message_journal
        self._messages = messages

    def _authority(self, scope):
        self._messages._profile(scope.profile)
        contacts = self._store.items("contact", limit=MAX_PEERS + 1)
        if len(contacts) > MAX_PEERS:
            raise ApiFailure("resource_exhausted")
        authority = [(identifier, value.get("trust"), value.get("destination_hash")) for identifier, value in contacts]
        return self._messages._identifier("core-api-read-authority:v1", authority)

    def _scope_key(self, scope):
        return self._messages._identifier("core-api-recovery:v1", scope.caller, scope.profile)

    def _cursor(self, scope, authority, purpose, head, position=""):
        return self._store.seal_private_cursor(self._scope_key(scope), {
            "v": 1, "g": self._journal.generation, "a": authority, "p": purpose,
            "h": head, "k": position, "x": time.time() + RETENTION_SECONDS,
        })

    def _open(self, scope, authority, cursor, purpose):
        try:
            value = self._store.open_private_cursor(self._scope_key(scope), cursor)
        except ValidationError as error:
            raise ApiFailure("invalid_request") from error
        except StorageUnavailable as error:
            raise ApiFailure("forbidden") from error
        if value.get("v") != 1 or value.get("g") != self._journal.generation or value.get("a") != authority:
            raise ApiFailure("resync_required")
        if value.get("p") != purpose:
            raise ApiFailure("invalid_request")
        expiry = value.get("x")
        if (type(expiry) not in {int, float} or not math.isfinite(expiry) or expiry <= time.time()
                or type(value.get("h")) is not int or not 0 <= value["h"] <= self._journal.head()):
            raise ApiFailure("resync_required")
        return value

    @staticmethod
    def _owned(index, scope):
        return index is not None and (index.get("caller"), index.get("profile")) == (scope.caller, scope.profile)

    def _readable(self, contact_id):
        contact = self._store.get("contact", contact_id)
        return contact is not None and contact.get("trust") in {TrustState.APPROVED.value, TrustState.VERIFIED.value}

    def snapshot(self, scope, cursor, limit):
        with storage_errors(), self._store.read_snapshot():
            authority = self._authority(scope)
            head, position = self._journal.head(), ""
            if cursor is not None:
                previous = self._open(scope, authority, cursor, "snapshot")
                if previous["h"] != head:
                    raise ApiFailure("resync_required")
                position = previous["k"]
            rows = self._store.items("api_message", after=position, limit=MAX_BATCH + 1)
            result, consumed, byte_count = [], 0, 0
            for handle, index in rows[:MAX_BATCH]:
                if self._owned(index, scope):
                    record = self._store.get("message", index["message_id"])
                    if record is not None and self._readable(record["contact_id"]):
                        message = self._messages.query(scope, handle)
                        size = len(json.dumps(message.text, ensure_ascii=True)) + 512
                        if len(result) == limit or byte_count + size > MAX_BATCH_BYTES - 4096:
                            break
                        result.append(ListedMessage(handle, message))
                        byte_count += size
                position, consumed = handle, consumed + 1
            more = consumed < len(rows)
            return MessagePage(tuple(result),
                self._cursor(scope, authority, "snapshot", head, position) if more else None,
                None if more else self._cursor(scope, authority, "events", head))

    def poll(self, scope, cursor, limit):
        with storage_errors(), self._store.read_snapshot():
            authority = self._authority(scope)
            if cursor is None:
                raise ApiFailure("resync_required")
            previous = self._open(scope, authority, cursor, "events")
            position = previous["h"]
            try:
                changes = self._journal.read(position, MAX_BATCH)
            except JournalGap as error:
                raise ApiFailure("resync_required") from error
            result = []
            for change in changes:
                handle = self._messages._identifier("core-api-message:v1", scope.caller, scope.profile, change["message_id"])
                index = self._store.get("api_message", handle)
                if self._owned(index, scope) and self._readable(change["contact_id"]):
                    if len(result) == limit:
                        break
                    identifier = self._messages._identifier("core-api-event:v1", scope.caller, scope.profile,
                                                          self._journal.generation, change["sequence"])
                    result.append(MessageEvent(identifier, handle, change["type"], change["state"], change["timestamp"]))
                position = change["sequence"]
            return EventPage(tuple(result), self._cursor(scope, authority, "events", position),
                             position < self._journal.head())
