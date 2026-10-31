"""Narrow peer-relationship port for explicit approval and revocation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RelationshipObservation:
    trust: str


class Relationship(Protocol):
    """Approve or revoke one peer and report the resulting trust state."""

    def approve(self, profile: str, contact: str) -> RelationshipObservation: ...

    def revoke(self, profile: str, contact: str) -> RelationshipObservation: ...
