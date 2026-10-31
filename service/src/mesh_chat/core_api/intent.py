"""Narrow connection-intent port, separate from observation and policy."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IntentObservation:
    desired: str
    active: bool


class ConnectionIntent(Protocol):
    """Apply contact-wide intent and report the resulting desired state."""

    def start(self, profile: str, contact: str) -> IntentObservation: ...

    def stop(self, profile: str, contact: str) -> IntentObservation: ...
