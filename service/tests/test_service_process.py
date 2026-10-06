from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from typing import Any

import pytest

import mesh_chat.__main__ as service_main
from mesh_chat.errors import ProfileInUse, StorageUnavailable, ValidationError


def _initialize_request(parent_pid: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "id": "initialize-test",
        "command": "initialize",
        "payload": {
            "profile_dir": "test-profile",
            "vault_key": base64.b64encode(bytes(range(32))).decode("ascii"),
            "display_name": None,
            "parent_pid": parent_pid,
        },
    }


def test_profile_lock_and_storage_failures_have_distinct_codes() -> None:
    locked = service_main._error_response("one", ProfileInUse("Profile is already open"))
    unprotected = service_main._error_response(
        "two", StorageUnavailable("Windows EFS is unavailable")
    )

    assert locked["error"]["code"] == "profile_in_use"
    assert unprotected["error"]["code"] == "protected_storage_unavailable"


@pytest.mark.parametrize(
    "value",
    [None, "123", True, 0, -1, 0x1_0000_0000],
)
def test_parent_pid_validation_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(ValidationError):
        service_main._validate_parent_pid(value)


def test_parent_pid_validation_rejects_the_service_itself() -> None:
    with pytest.raises(ValidationError):
        service_main._validate_parent_pid(os.getpid())


def test_desktop_initialize_requires_parent_pid() -> None:
    request = _initialize_request(1 if os.getpid() != 1 else 2)
    del request["payload"]["parent_pid"]

    with pytest.raises(ValidationError, match="payload"):
        service_main._initialize(request, SimpleNamespace(write=lambda _value: None))


def test_parent_watchdog_starts_before_vault_open(monkeypatch) -> None:
    events: list[tuple[str, Any]] = []
    parent_pid = 1 if os.getpid() != 1 else 2

    monkeypatch.setattr(
        service_main,
        "_start_parent_watchdog",
        lambda value: events.append(("watchdog", value)),
    )

    class FakeStore:
        def __init__(self, profile_dir, key):
            events.append(("vault", profile_dir))

    class FakeService:
        def __init__(self, store, profile_dir, emit):
            self.store = store
            events.append(("service", profile_dir))

    monkeypatch.setattr(service_main, "VaultStore", FakeStore)
    monkeypatch.setattr(service_main, "MeshChatService", FakeService)

    service_main._initialize(
        _initialize_request(parent_pid), SimpleNamespace(write=lambda _value: None)
    )

    assert events[0] == ("watchdog", parent_pid)
    assert events[1][0] == "vault"


def test_parent_watchdog_waits_for_grace_then_exits_without_killing_test_runner() -> None:
    events: list[tuple[str, Any]] = []

    watchdog = service_main._start_parent_watchdog(
        4242,
        waiter_factory=lambda parent_pid: lambda: events.append(("dead", parent_pid)),
        grace_seconds=0.25,
        sleep=lambda seconds: events.append(("grace", seconds)),
        exit_process=lambda code: events.append(("exit", code)),
    )
    watchdog.join(timeout=1)

    assert watchdog.daemon is True
    assert watchdog.is_alive() is False
    assert events == [("dead", 4242), ("grace", 0.25), ("exit", 0)]


def test_watchdog_monitor_failure_also_fails_closed() -> None:
    events: list[tuple[str, Any]] = []

    def failed_wait() -> None:
        raise OSError("monitor failed")

    service_main._parent_death_watchdog(
        failed_wait,
        grace_seconds=0,
        sleep=lambda seconds: events.append(("grace", seconds)),
        exit_process=lambda code: events.append(("exit", code)),
    )

    assert events == [("grace", 0), ("exit", 0)]
