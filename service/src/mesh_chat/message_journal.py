"""Bounded, content-free domain changes committed with their message records."""

import time
from uuid import uuid4

from .errors import StorageUnavailable
from .record_projection import Projection
from .models import DeliveryState


MAX_EVENTS = 2048
RETENTION_SECONDS = 7 * 86400
PUBLIC_FIELDS = ("kind", "contact_id", "direction", "text", "state", "created_at", "expires_at")
DELIVERY_STATES = {state.value for state in DeliveryState}


class JournalGap(Exception):
    """The requested change range is no longer available in its entirety."""


class MessageJournal:
    def __init__(self, store, *, clock=time.time):
        self._store = store
        self._clock = clock
        metadata = store.update_record("message_event_meta", "local", lambda previous: previous or {
            "version": 1, "generation": uuid4().hex, "head": 0, "capacity": MAX_EVENTS,
        })
        if metadata.get("version") != 1 or metadata.get("capacity") != MAX_EVENTS:
            raise StorageUnavailable("Unsupported message journal")
        self.generation = metadata["generation"]
        store.register_projection("message", self._project)

    def head(self):
        return self._store.get("message_event_meta", "local")["head"]

    def _slot(self, sequence):
        return self._store.opaque_id("message-event-slot:v1", str(sequence % MAX_EVENTS))

    @staticmethod
    def _public(value):
        if value is None or value.get("kind") != "chat":
            return None
        return tuple(value.get(field) for field in PUBLIC_FIELDS)

    def _project(self, changes):
        metadata = self._store.get("message_event_meta", "local")
        head = metadata["head"]
        writes = {}
        for change in changes:
            before, after = self._public(change.before), self._public(change.after)
            if before == after:
                continue
            source = change.after if after is not None else change.before
            contact = source.get("contact_id")
            if (not isinstance(contact, str) or not 1 <= len(contact) <= 256
                    or not isinstance(change.identifier, str) or not 1 <= len(change.identifier) <= 256):
                raise StorageUnavailable("Invalid message journal identity")
            head += 1
            if head > 9007199254740991:
                raise StorageUnavailable("Message journal sequence exhausted")
            writes[self._slot(head)] = {
                "sequence": head, "message_id": change.identifier, "contact_id": contact,
                "type": "message.changed" if after is not None else "message.removed",
                "state": source.get("state") if after is not None and source.get("state") in DELIVERY_STATES else None,
                "timestamp": self._clock(),
            }
        if not writes:
            return Projection()
        return Projection((
            ("message_event_meta", "local", {**metadata, "head": head}),
            *(("message_event", identifier, value) for identifier, value in writes.items()),
        ))

    def read(self, after, limit):
        if type(after) is not int or type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("Invalid journal range")
        with self._store.read_snapshot():
            head = self.head()
            if not max(0, head - MAX_EVENTS) <= after <= head:
                raise JournalGap()
            result = []
            for sequence in range(after + 1, min(head, after + limit) + 1):
                record = self._store.get("message_event", self._slot(sequence))
                if (record is None or record["sequence"] != sequence
                        or record["timestamp"] <= self._clock() - RETENTION_SECONDS):
                    raise JournalGap()
                result.append(record)
            return result
