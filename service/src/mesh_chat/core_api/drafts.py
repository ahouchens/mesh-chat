"""Typed direct-message draft port."""

from dataclasses import dataclass
from typing import Protocol
from .messages import MessageScope


@dataclass(frozen=True)
class DraftObservation:
    text: str


class Drafts(Protocol):
    def get(self, scope: MessageScope, contact: str) -> DraftObservation: ...

    def set(self, scope: MessageScope, contact: str, text: str) -> DraftObservation: ...
