"""Narrow inbound-pairing port: accept verified signed material only."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PairingObservation:
    contact: str
    trust: str


class Pairing(Protocol):
    """Accept one signed invitation document and report the resulting contact."""

    def accept(self, profile: str, document: str) -> PairingObservation: ...
