"""Private capabilities supplied by the composition root, never public commands."""

from typing import Protocol

from .model import Adopted, ConnectionKey, Desired, Failed, Operation, Resource, Result, Work


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...


class PhaseExecutor(Protocol):
    """One bounded operation. Poll once; the reducer decides whether to retry."""

    def execute(self, work: Work, cancellation: Cancellation) -> Result | Failed | Adopted: ...

    def retire(self, resource: Resource) -> None:
        """Idempotent close of this exact resource, including a late allocation."""
        ...


class IntentStore(Protocol):
    def save(self, key: ConnectionKey, desired: Desired) -> None:
        """Return only after the existing protected-store transaction commits."""
        ...


class PairingHandoff(Protocol):
    def __call__(self, operation: Operation, resource: Resource) -> bool:
        """Revalidate approved capability binding after the owner releases it."""
        ...
