"""Narrow peer-relationship port for explicit approval and revocation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RelationshipObservation:
    trust: str


@dataclass(frozen=True)
class PeerDeletionObservation:
    deleted: bool


class Relationship(Protocol):
    """Approve, revoke, unblock or delete one peer."""

    def approve(self, profile: str, contact: str) -> RelationshipObservation: ...

    def revoke(self, profile: str, contact: str) -> RelationshipObservation: ...

    def unblock(self, profile: str, contact: str) -> RelationshipObservation: ...

    def delete(self, profile: str, contact: str) -> PeerDeletionObservation: ...
