"""Caller-scoped revisioned composer use cases and advertised bounds."""

from dataclasses import dataclass
from typing import Protocol

from .messages import Acceptance, MessageScope

COMPOSER_LIMITS = {
    "composer_text_utf8_bytes": 16384,
    "composers_per_caller_profile": 256,
    "composers_per_vault": 4096,
    "composer_update_idempotency_seconds": 3600,
    "composer_update_keys_per_caller_profile": 8192,
    "composer_update_keys_per_vault": 65536,
    "composer_send_idempotency_seconds": 604800,
    "composer_send_keys_per_caller_profile": 4096,
    "composer_send_keys_per_vault": 65536,
}


@dataclass(frozen=True)
class ComposerState:
    revision: str | None
    text: str
    update_key: str
    last_send: dict | None = None
    send_lookup: dict | None = None


@dataclass(frozen=True)
class ComposerUpdate:
    applied_revision: str
    changed: bool
    composer: ComposerState


@dataclass(frozen=True)
class ComposerAcceptance:
    acceptance: Acceptance
    revision: str
    disposition: str
    composer: ComposerState


class Composer(Protocol):
    def query(self, scope: MessageScope, peer: str, send_revision: str | None) -> ComposerState: ...
    def update(self, scope: MessageScope, peer: str, key: str,
               expected_revision: str | None, text: str) -> ComposerUpdate: ...
    def enqueue(self, scope: MessageScope, peer: str, key: str, revision: str) -> ComposerAcceptance: ...
