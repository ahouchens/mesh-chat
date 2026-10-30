"""Transaction-local projection port. Implementations perform no external I/O."""

from dataclasses import dataclass
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class RecordChange:
    identifier: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class Projection:
    records: tuple[tuple[str, str, dict[str, Any]], ...] = ()
    deletions: tuple[tuple[str, str], ...] = ()


class ProjectRecords(Protocol):
    def __call__(self, changes: Iterable[RecordChange]) -> Projection: ...
