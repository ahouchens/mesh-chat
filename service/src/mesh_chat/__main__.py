from __future__ import annotations

import base64
import ctypes
import errno
import os
import select
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import MeshChatError, ValidationError
from .ipc import FrameWriter, IPC_VERSION, read_frame
from .service import MeshChatService
from .vault import VaultStore


PARENT_EXIT_GRACE_SECONDS = 5.0
PARENT_POLL_SECONDS = 0.5
WINDOWS_SYNCHRONIZE = 0x00100000
WINDOWS_WAIT_OBJECT_0 = 0x00000000
WINDOWS_WAIT_TIMEOUT = 0x00000102
WINDOWS_INFINITE = 0xFFFFFFFF

ParentExitWaiter = Callable[[], None]


def _validate_parent_pid(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 0xFFFFFFFF
        or value == os.getpid()
    ):
        raise ValidationError("Host process identifier is invalid")
    return value


def _windows_parent_exit_waiter(parent_pid: int) -> ParentExitWaiter:
    """Pin the exact Windows host process so PID reuse cannot fool the watchdog."""

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(WINDOWS_SYNCHRONIZE, False, parent_pid)
    if not handle:
        raise ValidationError("Host process is unavailable")
    initial = wait_for_single_object(handle, 0)
    if initial != WINDOWS_WAIT_TIMEOUT:
        close_handle(handle)
        raise ValidationError("Host process is unavailable")

    def wait_for_exit() -> None:
        try:
            if wait_for_single_object(handle, WINDOWS_INFINITE) != WINDOWS_WAIT_OBJECT_0:
                raise OSError("Host process wait failed")
        finally:
            close_handle(handle)

    return wait_for_exit


def _pidfd_parent_exit_waiter(parent_pid: int) -> ParentExitWaiter | None:
    """Use a Linux pidfd when supported, retaining exact process identity."""

    pidfd_open = getattr(os, "pidfd_open", None)
    if pidfd_open is None:
        return None
    try:
        descriptor = pidfd_open(parent_pid, 0)
    except ProcessLookupError as exc:
        raise ValidationError("Host process is unavailable") from exc
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EINVAL}:
            return None
        raise ValidationError("Host process monitoring is unavailable") from exc
    try:
        ready, _, _ = select.select([descriptor], [], [], 0)
    except Exception as exc:
        os.close(descriptor)
        raise ValidationError("Host process monitoring is unavailable") from exc
    if ready:
        os.close(descriptor)
        raise ValidationError("Host process is unavailable")

    def wait_for_exit() -> None:
        try:
            select.select([descriptor], [], [])
        finally:
            os.close(descriptor)

    return wait_for_exit


def _kqueue_parent_exit_waiter(parent_pid: int) -> ParentExitWaiter | None:
    """Pin a BSD/macOS process-exit event when kqueue process filters exist."""

    if not all(
        hasattr(select, name)
        for name in ("kqueue", "kevent", "KQ_FILTER_PROC", "KQ_NOTE_EXIT")
    ):
        return None
    queue = select.kqueue()
    event = select.kevent(
        parent_pid,
        filter=select.KQ_FILTER_PROC,
        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
        fflags=select.KQ_NOTE_EXIT,
    )
    try:
        ready = queue.control([event], 1, 0)
    except OSError as exc:
        queue.close()
        raise ValidationError("Host process is unavailable") from exc
    if ready:
        queue.close()
        raise ValidationError("Host process is unavailable")

    def wait_for_exit() -> None:
        try:
            queue.control([], 1, None)
        finally:
            queue.close()

    return wait_for_exit


def _polling_parent_exit_waiter(parent_pid: int) -> ParentExitWaiter:
    """Portable fallback for systems without an exact process-exit primitive."""

    def is_alive() -> bool:
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    if not is_alive():
        raise ValidationError("Host process is unavailable")

    def wait_for_exit() -> None:
        while is_alive():
            time.sleep(PARENT_POLL_SECONDS)

    return wait_for_exit


def _parent_exit_waiter(parent_pid: int) -> ParentExitWaiter:
    if sys.platform == "win32":
        return _windows_parent_exit_waiter(parent_pid)
    pidfd_waiter = _pidfd_parent_exit_waiter(parent_pid)
    if pidfd_waiter is not None:
        return pidfd_waiter
    kqueue_waiter = _kqueue_parent_exit_waiter(parent_pid)
    if kqueue_waiter is not None:
        return kqueue_waiter
    return _polling_parent_exit_waiter(parent_pid)


def _parent_death_watchdog(
    wait_for_exit: ParentExitWaiter,
    grace_seconds: float = PARENT_EXIT_GRACE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    exit_process: Callable[[int], Any] = os._exit,
) -> None:
    try:
        wait_for_exit()
    except Exception:
        # A broken monitor must fail closed instead of allowing an unowned
        # service to retain the protected profile indefinitely.
        pass
    sleep(grace_seconds)
    exit_process(0)


def _start_parent_watchdog(
    parent_pid: int,
    *,
    waiter_factory: Callable[[int], ParentExitWaiter] = _parent_exit_waiter,
    grace_seconds: float = PARENT_EXIT_GRACE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    exit_process: Callable[[int], Any] = os._exit,
) -> threading.Thread:
    wait_for_exit = waiter_factory(parent_pid)
    watchdog = threading.Thread(
        target=_parent_death_watchdog,
        args=(wait_for_exit, grace_seconds, sleep, exit_process),
        name="mesh-chat-parent-watchdog",
        daemon=True,
    )
    watchdog.start()
    return watchdog


def _error_response(command_id: Any, error: Exception) -> dict[str, Any]:
    code = error.code if isinstance(error, MeshChatError) else "internal_error"
    return {
        "type": "response",
        "id": command_id if isinstance(command_id, str) else None,
        "ok": False,
        "error": {"code": code},
    }


def _initialize(request: dict[str, Any], writer: FrameWriter) -> MeshChatService:
    if request.get("v") != IPC_VERSION or request.get("command") != "initialize":
        raise ValidationError("First command must initialize the service")
    payload = request.get("payload")
    if not isinstance(payload, dict) or set(payload) - {
        "profile_dir",
        "vault_key",
        "display_name",
        "parent_pid",
    } or not {"profile_dir", "vault_key", "parent_pid"}.issubset(payload):
        raise ValidationError("Initialization payload is invalid")
    profile_value = payload["profile_dir"]
    key_value = payload["vault_key"]
    parent_pid = _validate_parent_pid(payload["parent_pid"])
    if not isinstance(profile_value, str) or not profile_value or "\x00" in profile_value:
        raise ValidationError("Profile directory is invalid")
    if not isinstance(key_value, str) or len(key_value) > 128:
        raise ValidationError("Vault key is invalid")
    try:
        key = base64.b64decode(key_value, validate=True)
    except Exception as exc:
        raise ValidationError("Vault key is invalid") from exc
    _start_parent_watchdog(parent_pid)
    store = VaultStore(Path(profile_value), key)
    service = MeshChatService(store, Path(profile_value).resolve(), writer.write)
    display_name = payload.get("display_name")
    if display_name is not None and service.store.get("profile", "local") is None:
        service.create_profile(display_name)
    return service


def main() -> int:
    reader = sys.stdin.buffer
    writer = FrameWriter(sys.stdout.buffer)
    service: MeshChatService | None = None
    try:
        initial = read_frame(reader)
        try:
            service = _initialize(initial, writer)
            writer.write(
                {
                    "type": "response",
                    "id": initial.get("id"),
                    "ok": True,
                    "result": service.snapshot(),
                }
            )
        except Exception as exc:
            writer.write(_error_response(initial.get("id"), exc))
            return 2

        while True:
            request = read_frame(reader)
            command_id = request.get("id")
            try:
                result, should_stop = service.dispatch(request)
                writer.write({"type": "response", "id": command_id, **result})
                if should_stop:
                    break
            except Exception as exc:
                writer.write(_error_response(command_id, exc))
    except EOFError:
        pass
    except Exception:
        # Stderr is deliberately content-free: the desktop may retain it.
        print("mesh-chat-service: fatal protocol error", file=sys.stderr)
        return 3
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                print("mesh-chat-service: shutdown error", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
