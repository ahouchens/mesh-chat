"""Application runtime status and notification actions.

Native background execution and OS notifications are platform details; this
port exposes only the state the renderer may observe and the policy it may set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .service_messages import storage_errors


class ApplicationRuntime(Protocol):
    def query(self, profile: str, action: str) -> dict: ...

    def mutate(self, profile: str, action: str,
               params: dict[str, Any], operation_id: str) -> dict: ...


@dataclass
class ServiceApplicationRuntime:
    service: Any

    def query(self, profile, action):
        if action == "background":
            return dict(self.service.background_availability_status())
        if action == "notifications":
            return dict(self.service.notification_state())
        raise ValueError("unsupported runtime query")

    def mutate(self, profile, action, params, operation_id):
        with storage_errors():
            if action == "background_set":
                return dict(self.service.set_background_availability(
                    params["enabled"], operation_id=operation_id))
            if action == "notification_previews":
                return dict(self.service.set_hide_notification_previews(
                    params["hidden"], operation_id))
            if action == "notification_open":
                return dict(self.service.open_notification_target(params["notification_id"]))
            raise ValueError("unsupported runtime action")
