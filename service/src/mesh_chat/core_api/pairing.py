"""Narrow inbound-pairing port: accept verified signed material only."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PairingObservation:
    contact: str
    trust: str


@dataclass(frozen=True)
class PairingRequest:
    contact: str
    document: str


@dataclass(frozen=True)
class PairingIntentObservation:
    pairing: str
    state: str
    expires_at: float
    pairing_code: str | None


class Pairing(Protocol):
    def contact_invitation(self, profile: str, action: str, params: dict) -> dict: ...

    def preview_invitation(self, profile: str, document: str) -> dict: ...
    """Accept one signed invitation and send a signed request to a known peer."""

    def accept(self, profile: str, document: str, *, i2p_consent: bool = False) -> PairingObservation: ...

    def request(self, profile: str, contact: str) -> PairingRequest: ...
