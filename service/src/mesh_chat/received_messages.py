"""Ordered, content-free index of received chat messages.

The index is a durable domain projection: it commits inside the same vault
transaction as the visible message record, so a reader never observes a message
without its position or a position without its message. It stores no text; the
authoritative message record remains the only copy of the content.
"""

from .errors import StorageUnavailable
from .models import MessageKind
from .record_projection import Projection


KIND = "received_message"
MAX_IDENTIFIER = 256
MAX_MICROSECONDS = (1 << 56) - 1


def index_key(created_at, identifier):
    """Return a record ID whose lexicographic order is chronological order."""
    if (type(created_at) not in {int, float} or not 0 <= created_at <= MAX_MICROSECONDS / 1_000_000
            or not isinstance(identifier, str) or not 1 <= len(identifier) <= MAX_IDENTIFIER):
        raise StorageUnavailable("Invalid received message identity")
    micros = int(round(created_at * 1_000_000))
    if not 0 <= micros <= MAX_MICROSECONDS:
        raise StorageUnavailable("Invalid received message timestamp")
    return f"{micros:016x}-{identifier}"


class ReceivedMessages:
    """Project inbound chat messages into a bounded chronological index."""

    def __init__(self, store):
        self._store = store
        store.register_projection("message", self._project)

    def _project(self, changes):
        records, deletions = [], []
        for change in changes:
            before = self._entry(change.before)
            after = self._entry(change.after)
            if before is not None and (after is None or before[0] != after[0]):
                deletions.append((KIND, before[0]))
            if after is not None and after != before:
                records.append((KIND, after[0], after[1]))
        return Projection(tuple(records), tuple(deletions))

    @staticmethod
    def _entry(value):
        if (value is None or value.get("kind") != MessageKind.CHAT.value
                or value.get("direction") != "inbound"):
            return None
        identifier, contact = value.get("id"), value.get("contact_id")
        if (not isinstance(contact, str) or not 1 <= len(contact) <= MAX_IDENTIFIER):
            raise StorageUnavailable("Invalid received message contact")
        created_at = value.get("created_at")
        key = index_key(created_at, identifier)
        return key, {"message_id": identifier, "contact_id": contact, "created_at": float(created_at)}
