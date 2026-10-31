"""Private storage adapter for consistent snapshots and retained message changes."""

import json

from ..message_journal import JournalGap
from ..models import DeliveryState, TrustState
from ..received_messages import KIND as RECEIVED_KIND
from .errors import ApiFailure
from .messages import MAX_PEERS
from .recovery import (
    EventPage, ListedMessage, MAX_BATCH, MAX_BATCH_BYTES, MessageEvent, MessagePage,
    ReceivedMessage, ReceivedObservation, ReceivedPage,
)
from .service_messages import storage_errors
from .service_cursors import ServiceCursors
from .service_consumer_progress import ServiceConsumerProgress


class ServiceRecovery:
    def __init__(self, service, messages):
        self._store = service.store
        self._journal = service._message_journal
        self._messages = messages
        self._cursors = ServiceCursors(self._store, self._journal, messages._identifier)
        self._progress = ServiceConsumerProgress(self._store, self._journal, self._cursors, messages._identifier)

    def _authority(self, scope):
        self._messages._profile(scope.profile)
        contacts = self._store.items("contact", limit=MAX_PEERS + 1)
        if len(contacts) > MAX_PEERS:
            raise ApiFailure("resource_exhausted")
        authority = [(identifier, value.get("trust"), value.get("destination_hash")) for identifier, value in contacts]
        return self._messages._identifier("core-api-read-authority:v1", authority)

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
                previous = self._cursors.open(scope, authority, cursor, "snapshot")
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
                self._cursors.create(scope, authority, "snapshot", head, position) if more else None,
                None if more else self._cursors.create(scope, authority, "events", head))

    def acknowledge(self, scope, cursor, key):
        with storage_errors(), self._store.read_snapshot():
            return self._progress.acknowledge(scope, self._authority(scope), cursor, key)

    def received(self, scope, cursor, limit):
        with storage_errors(), self._store.read_snapshot():
            authority = self._authority(scope)
            position = ("" if cursor is None
                        else self._cursors.open(scope, authority, cursor, "received")["k"])
            messages, position, more = self._received_page(scope, position, limit)
            next_cursor = (self._cursors.create(scope, authority, "received",
                                                self._journal.head(), position)
                           if more else None)
            return ReceivedPage(messages, next_cursor, more)

    def _received_page(self, scope, position, limit):
        """Scan one bounded, authority-filtered index window for visible messages."""
        rows = self._store.items(RECEIVED_KIND, after=position or None, limit=MAX_BATCH + 1)
        messages, consumed, byte_count = [], 0, 0
        for key, index in rows[:MAX_BATCH]:
            record = self._received_record(index)
            if len(messages) == limit:
                break
            size = 0 if record is None else len(json.dumps(record["text"], ensure_ascii=True)) + 512
            if record is not None and byte_count + size > MAX_BATCH_BYTES - 4096:
                break
            position, consumed = key, consumed + 1
            if record is None:
                continue
            messages.append(self._received_message(scope, index, record))
            byte_count += size
        return tuple(messages), position, consumed < len(rows)

    def _received_record(self, index):
        """Return the message only while it is still inbound and readable."""
        record = self._store.get("message", index["message_id"])
        if (record is None or record.get("direction") != "inbound"
                or not self._readable(index["contact_id"])):
            return None
        return record

    def _received_message(self, scope, index, record):
        handle = self._messages._identifier("core-api-received:v1", scope.caller, scope.profile,
                                            index["message_id"])
        observation = ReceivedObservation(index["contact_id"], record["text"],
                                          DeliveryState(record["state"]).value,
                                          float(record["created_at"]))
        return ReceivedMessage(handle, observation)

    def poll(self, scope, cursor, limit):
        with storage_errors(), self._store.read_snapshot():
            authority = self._authority(scope)
            previous = (self._progress.resume(scope, authority) if cursor is None
                        else self._cursors.open(scope, authority, cursor, "events"))
            position = previous["h"]
            try:
                changes = self._journal.read(position, MAX_BATCH)
            except JournalGap as error:
                raise ApiFailure("resync_required") from error
            result = []
            for change in changes:
                handle = self._messages._identifier("core-api-message:v1", scope.caller, scope.profile, change["message_id"])
                index = self._store.get("api_message", handle)
                direction = change.get("direction")
                if not direction:
                    # Records written before the journal carried direction belong
                    # to this caller's own outbound enqueue stream.
                    direction = "outbound"
                visible = self._readable(change["contact_id"]) and (
                    (direction == "inbound") or self._owned(index, scope))
                if visible:
                    if len(result) == limit:
                        break
                    if direction == "inbound":
                        handle = self._messages._identifier("core-api-received:v1", scope.caller, scope.profile,
                                                           change["message_id"])
                    identifier = self._messages._identifier("core-api-event:v1", scope.caller, scope.profile,
                                                          self._journal.generation, change["sequence"])
                    result.append(MessageEvent(identifier, handle, change["type"], change["state"],
                                               change["timestamp"], direction))
                position = change["sequence"]
            return EventPage(tuple(result), self._cursors.create(scope, authority, "events", position),
                             position < self._journal.head())
