from __future__ import annotations

import threading
from typing import Any
from unittest.mock import Mock

import pytest

from mesh_chat.service import MeshChatService


class CacheSpy:
    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}
        self.lookups: list[str] = []
        self.writes: list[str] = []

    def command_response(self, command_id: str) -> dict[str, Any] | None:
        self.lookups.append(command_id)
        return self.responses.get(command_id)

    def remember_command(self, command_id: str, response: dict[str, Any]) -> None:
        self.writes.append(command_id)
        self.responses.setdefault(command_id, response)


def service_with_cache(cache: CacheSpy) -> MeshChatService:
    service = object.__new__(MeshChatService)
    service._dispatch_lock = threading.RLock()
    service.store = cache
    service._execute = Mock(return_value={"value": "fresh"})
    return service


@pytest.mark.parametrize("command", ["snapshot", "search", "connection_help"])
def test_observational_commands_do_not_use_durable_idempotency_cache(command: str) -> None:
    cache = CacheSpy()
    service = service_with_cache(cache)
    request = {"v": 1, "id": f"{command}-id", "command": command, "payload": {}}

    first, _ = service.dispatch(request)
    second, _ = service.dispatch(request)

    assert first == second == {"ok": True, "result": {"value": "fresh"}}
    assert service._execute.call_count == 2
    assert cache.lookups == []
    assert cache.writes == []


def test_mutating_command_response_remains_idempotent() -> None:
    cache = CacheSpy()
    service = service_with_cache(cache)
    request = {"v": 1, "id": "send-id", "command": "send_message", "payload": {}}

    first, _ = service.dispatch(request)
    second, _ = service.dispatch(request)

    assert first == second == {"ok": True, "result": {"value": "fresh"}}
    service._execute.assert_called_once_with("send_message", {})
    assert cache.lookups == ["send-id", "send-id"]
    assert cache.writes == ["send-id"]
