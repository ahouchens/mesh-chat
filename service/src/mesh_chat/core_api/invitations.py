"""Narrow port for creating signed pairing material for the local profile."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InvitationObservation:
    file: str
    link: str
    text: str
    expires_at: float
    host_session_id: str | None = None


class Invitations(Protocol):
    """Create the current signed invitation without changing durable state."""

    def create(self, profile: str, *, connection_mode=None, manual_setup_id=None,
               external_host=None, external_port=None, i2p_access_point=None,
               i2p_label=None) -> InvitationObservation: ...
