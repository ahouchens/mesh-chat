"""Typed call-settings port for the local profile."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CallSettingsObservation:
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallMediaObservation:
    media: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallIceObservation:
    ice: dict[str, Any] = field(default_factory=dict)


class CallSettings(Protocol):
    def get(self, profile: str) -> CallSettingsObservation: ...

    def ice(self, profile: str) -> CallIceObservation: ...

    def call_ids(self, profile: str) -> tuple[str, ...]: ...

    def media(self, profile: str, call_id: str) -> CallMediaObservation: ...

    def update(self, profile: str, settings: dict[str, Any]) -> CallSettingsObservation: ...

    def control(self, profile: str, action: str, params: dict[str, Any], operation_id: str) -> dict: ...
