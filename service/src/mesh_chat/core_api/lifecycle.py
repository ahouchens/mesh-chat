"""Owner-authorized lifecycle port."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StopObservation:
    stopping: bool
    already_stopping: bool


class Lifecycle(Protocol):
    """Request shutdown; the owning host completes cleanup and closes."""

    def stop(self) -> StopObservation: ...
