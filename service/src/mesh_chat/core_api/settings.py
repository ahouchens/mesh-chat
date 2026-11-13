"""Typed network-settings port for the local profile."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class NetworkSettingsObservation:
    settings: dict[str, Any] = field(default_factory=dict)


class NetworkSettings(Protocol):
    def get(self, profile: str) -> NetworkSettingsObservation: ...

    def update(self, profile: str, settings: dict[str, Any]) -> NetworkSettingsObservation: ...
