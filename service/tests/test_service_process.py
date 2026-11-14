from __future__ import annotations

import base64
import io
import os
from types import SimpleNamespace
from typing import Any

import pytest

import mesh_chat.__main__ as service_main
from mesh_chat.errors import ProfileInUse, StorageUnavailable, ValidationError, WorkspaceAlreadyKnown
from mesh_chat.core_api.pipe_endpoint import PipeRetirementPending


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


def test_saved_workspace_reason_is_allowlisted_over_the_sidecar_boundary() -> None:
    allowed = service_main._error_response(
        "one", WorkspaceAlreadyKnown("saved", reason="request_stopped"))
    assert allowed["error"] == {
        "code": "workspace_already_known",
        "details": {"reason": "request_stopped"},
    }
    rejected = service_main._error_response(
        "two", WorkspaceAlreadyKnown("saved", reason="private-document-text"))
    assert rejected["error"] == {"code": "workspace_already_known"}


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
        def __init__(self, store, profile_dir, emit, *, direct_native=None):
            self.store = store
            assert direct_native is not None
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


@pytest.mark.parametrize("primary_error,expected_status", [(False, 0), (True, 3)])
def test_main_retries_pending_pipe_before_dependent_shutdown_and_preserves_primary(
    monkeypatch, primary_error, expected_status
) -> None:
    events = []
    original_hook = service_main.threading.excepthook
    initial = {"v": 1, "id": "start", "command": "initialize", "payload": {}}
    service = SimpleNamespace(_direct_native=None, snapshot=lambda: {},
                              close=lambda: events.append("service"))
    class Endpoint:
        calls = 0
        def close(self):
            self.calls += 1
            events.append("endpoint")
            if self.calls == 1:
                raise PipeRetirementPending("worker still active")
    endpoint = Endpoint()
    class Reader:
        def __init__(self, *_args, **_kwargs): pass
        def read(self):
            if primary_error:
                raise OSError("primary command failure")
            raise EOFError()
        def close(self): events.append("reader")
    monkeypatch.setattr(service_main.sys, "argv", ["mesh-chat-service"])
    monkeypatch.setattr(service_main.sys, "stdin", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(service_main.sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(service_main, "interruptible_input", lambda value: value)
    monkeypatch.setattr(service_main, "FrameWriter", lambda _: SimpleNamespace(write=lambda value: None))
    monkeypatch.setattr(service_main, "read_frame", lambda _: initial)
    monkeypatch.setattr(service_main, "_initialize", lambda *_: service)
    monkeypatch.setattr(service_main, "_start_core_api_endpoint", lambda _: endpoint)
    monkeypatch.setattr(service_main, "NativeFrameReader", Reader)
    monkeypatch.setattr(service_main, "report_failure", lambda stage, error, *_:
                        events.append((stage, str(error))))
    monkeypatch.setattr(service_main.time, "sleep", lambda _: events.append("backoff"))
    assert service_main.main() == expected_status
    assert endpoint.calls == 2
    assert events[-3:] == ["endpoint", "reader", "service"]
    assert events.index("service") > events.index("reader")
    assert ("shutdown", "worker still active") in events
    if primary_error:
        assert events[0] == ("read_command", "primary command failure")
    assert service_main.threading.excepthook is original_hook
