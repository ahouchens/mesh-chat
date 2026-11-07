"""Typed reaction port over caller-scoped API message handles."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReactionObservation:
    scope: str
    emoji: str
    active: bool


class Reactions(Protocol):
    def set(self, scope, handle, emoji, active) -> ReactionObservation: ...
