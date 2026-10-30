"""Bounded snapshot/replay port, independent of storage and transport details."""

from dataclasses import dataclass
from typing import Protocol

from .messages import MessageObservation, MessageScope


MAX_BATCH = 128
MAX_BATCH_BYTES = 1048576
MAX_CURSOR_BYTES = 1024
MAX_CALLER_ACKNOWLEDGMENTS = 4096
MAX_VAULT_ACKNOWLEDGMENTS = 65536


@dataclass(frozen=True)
class ListedMessage:
    handle: str
    value: MessageObservation


@dataclass(frozen=True)
class MessagePage:
    messages: tuple[ListedMessage, ...]
    next_cursor: str | None
    events_cursor: str | None


@dataclass(frozen=True)
class MessageEvent:
    identifier: str
    message: str
    type: str
    state: str | None
    timestamp: float


@dataclass(frozen=True)
class EventPage:
    events: tuple[MessageEvent, ...]
    next_cursor: str
    more: bool


@dataclass(frozen=True)
class Acknowledgment:
    checkpoint: str
    acknowledged_at: float
    expires_at: float


@dataclass(frozen=True)
class ReceivedObservation:
    contact: str
    text: str
    state: str
    created_at: float


@dataclass(frozen=True)
class ReceivedMessage:
    handle: str
    value: ReceivedObservation


@dataclass(frozen=True)
class ReceivedPage:
    messages: tuple[ReceivedMessage, ...]
    next_cursor: str | None
    more: bool


class Recovery(Protocol):
    def snapshot(self, scope: MessageScope, cursor: str | None, limit: int) -> MessagePage: ...
    def poll(self, scope: MessageScope, cursor: str | None, limit: int) -> EventPage: ...
    def acknowledge(self, scope: MessageScope, cursor: str, key: str) -> Acknowledgment: ...


class ReceivedLog(Protocol):
    """Chronological read of received messages, separate from replay cursors."""

    def received(self, scope: MessageScope, cursor: str | None, limit: int) -> ReceivedPage: ...
