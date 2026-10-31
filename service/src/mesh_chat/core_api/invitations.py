"""Narrow port for creating signed pairing material for the local profile."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InvitationObservation:
    file: str
    link: str
    expires_at: float


class Invitations(Protocol):
    """Create the current signed invitation without changing durable state."""

    def create(self, profile: str) -> InvitationObservation: ...
