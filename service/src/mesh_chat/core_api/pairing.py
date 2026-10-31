"""Narrow inbound-pairing port: accept verified signed material only."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PairingObservation:
    contact: str
    trust: str


class Pairing(Protocol):
    """Accept one signed invitation and send a signed request to a known peer."""

    def accept(self, profile: str, document: str) -> PairingObservation: ...

    def request(self, profile: str, contact: str) -> None: ...
