"""Typed call-settings port for the local profile."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CallSettingsObservation:
    settings: dict[str, Any] = field(default_factory=dict)


class CallSettings(Protocol):
    def get(self, profile: str) -> CallSettingsObservation: ...

    def update(self, profile: str, settings: dict[str, Any]) -> CallSettingsObservation: ...
