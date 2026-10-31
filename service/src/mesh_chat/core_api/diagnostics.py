"""Read-only diagnostics port; no storage, network or native adapter capabilities."""

from dataclasses import dataclass
from typing import Protocol


MAX_DIAGNOSTICS = 256
MAX_DIAGNOSTIC_BYTES = 262144


@dataclass(frozen=True)
class DiagnosticObservation:
    captured_at: float
    available: bool
    runtime_failure: str | None
    connections: dict[str, dict]


class Diagnostics(Protocol):
    def query(self, profile: str) -> DiagnosticObservation: ...
