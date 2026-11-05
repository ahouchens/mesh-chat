"""Typed direct-message draft port."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DraftObservation:
    text: str


class Drafts(Protocol):
    def get(self, profile: str, contact: str) -> DraftObservation: ...

    def set(self, profile: str, contact: str, text: str) -> DraftObservation: ...
