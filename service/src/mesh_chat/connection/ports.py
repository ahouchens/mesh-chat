"""Private capabilities supplied by the composition root, never public commands."""

from typing import Protocol

from .model import ConnectionKey, Desired, Failed, Resource, Result, Work


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...


class PhaseExecutor(Protocol):
    """One bounded operation. Poll once; the reducer decides whether to retry."""

    def execute(self, work: Work, cancellation: Cancellation) -> Result | Failed: ...

    def retire(self, resource: Resource) -> None:
        """Idempotent close of this exact resource, including a late allocation."""
        ...


class IntentStore(Protocol):
    def save(self, key: ConnectionKey, desired: Desired) -> None:
        """Return only after the existing protected-store transaction commits."""
        ...
