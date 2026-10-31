"""Message use-case port; public sessions do not depend on storage or transports."""

from dataclasses import dataclass
from typing import Protocol


MAX_PEERS = 256
IDEMPOTENCY_SECONDS = 7 * 86400
MAX_CALLER_ENQUEUES = 4096
MAX_VAULT_ENQUEUES = 65536


@dataclass(frozen=True)
class MessageScope:
    caller: str
    profile: str


@dataclass(frozen=True)
class Acceptance:
    message: str
    accepted_at: float
    idempotency_expires_at: float


@dataclass(frozen=True)
class MessageObservation:
    recipient: str
    text: str
    state: str
    created_at: float


@dataclass(frozen=True)
class PeerObservation:
    display_name: str
    destination: str
    trust: str


class Messages(Protocol):
    def peers(self, profile: str) -> tuple[str, ...]: ...
    def peer(self, profile: str, recipient: str) -> PeerObservation: ...
    def enqueue(self, scope: MessageScope, recipient: str, key: str, text: str) -> Acceptance: ...
    def query(self, scope: MessageScope, message: str) -> MessageObservation: ...
