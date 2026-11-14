"""Exact Windows process-handle custody without endpoint or runtime wiring."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from mesh_chat.app_owned_admission import ProcessIdentity
from mesh_chat.app_owned_windows_process import (
    PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE, WAIT_OBJECT_0, WAIT_TIMEOUT,
    WindowsProcessHandle, WindowsProcessPort,
)


def test_rejects_invalid_pid_before_open_process():
    kernel = Mock()
    port = WindowsProcessPort(kernel=kernel)
    for pid in (0, -1, True, 0x100000000, "7"):
        with pytest.raises(ValueError):
            port.open(pid)
    kernel.OpenProcess.assert_not_called()


def test_failed_creation_query_keeps_unclosed_handle_for_explicit_retry():
    kernel = Mock()
    kernel.OpenProcess.return_value = 314
    kernel.GetProcessTimes.return_value = False
    kernel.CloseHandle.side_effect = [False, False, True]
    port = WindowsProcessPort(kernel=kernel)

    with pytest.raises(OSError, match="GetProcessTimes"):
        port.open(42)
    kernel.OpenProcess.assert_called_once_with(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, 42)
    assert kernel.CloseHandle.call_count == 1
    assert port.retire() is False
    assert port.retire() is True
    assert port.retire() is True
    assert kernel.CloseHandle.call_count == 3


def test_failed_image_query_closes_acquired_handle_atomically(monkeypatch):
    kernel = Mock()
    kernel.OpenProcess.return_value = 315
    kernel.QueryFullProcessImageNameW.return_value = False
    kernel.CloseHandle.return_value = True
    port = WindowsProcessPort(kernel=kernel)
    monkeypatch.setattr(port, "_creation_time", lambda _handle: 1)

    with pytest.raises(OSError, match="QueryFullProcessImageNameW"):
        port.open(43)
    kernel.CloseHandle.assert_called_once_with(315)
    assert port.retire() is True
    kernel.CloseHandle.assert_called_once()


def test_open_rejects_exited_or_error_state_and_closes_pin(monkeypatch):
    for state, error in ((WAIT_OBJECT_0, ProcessLookupError),
                         (0xFFFFFFFF, OSError)):
        kernel = Mock()
        kernel.OpenProcess.return_value = 316
        kernel.WaitForSingleObject.return_value = state
        kernel.CloseHandle.return_value = True
        port = WindowsProcessPort(kernel=kernel)
        monkeypatch.setattr(port, "_creation_time", lambda _handle: 1)
        monkeypatch.setattr(port, "_image", lambda _handle: r"C:\test\helper.exe")
        with pytest.raises(error):
            port.open(44)
        kernel.WaitForSingleObject.assert_called_once_with(316, 0)
        kernel.CloseHandle.assert_called_once_with(316)


def test_wait_distinguishes_live_exit_and_error_and_close_retries():
    kernel = Mock()
    identity = ProcessIdentity(45, 1, r"C:\test\helper.exe")
    pin = WindowsProcessHandle(kernel, 317, identity)
    kernel.WaitForSingleObject.side_effect = [WAIT_TIMEOUT, WAIT_OBJECT_0, 0xFFFFFFFF]
    assert pin.identity is identity
    assert pin.is_alive() is True
    assert pin.is_alive() is False
    with pytest.raises(OSError, match="WaitForSingleObject"):
        pin.is_alive()
    kernel.CloseHandle.side_effect = [False, True]
    with pytest.raises(OSError, match="CloseHandle"):
        pin.close()
    kernel.WaitForSingleObject.side_effect = None
    kernel.WaitForSingleObject.return_value = WAIT_TIMEOUT
    assert pin.is_alive() is True
    pin.close()
    pin.close()
    assert kernel.CloseHandle.call_count == 2
    with pytest.raises(ValueError, match="closed"):
        pin.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows process objects")
def test_current_process_pin_has_live_generation_and_image():
    pin = WindowsProcessPort().open(os.getpid())
    try:
        assert pin.identity.pid == os.getpid()
        assert pin.identity.creation_time > 0
        assert os.path.isabs(pin.identity.image)
        assert os.path.basename(pin.identity.image).casefold() == (
            os.path.basename(sys.executable).casefold())
        assert pin.is_alive() is True
    finally:
        pin.close()
    pin.close()
    with pytest.raises(ValueError, match="closed"):
        pin.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows process objects")
def test_helper_pin_observes_exit_through_same_handle():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    pin = None
    try:
        pin = WindowsProcessPort().open(child.pid)
        assert pin.identity.pid == child.pid
        assert pin.identity.creation_time > 0
        assert pin.is_alive() is True
        child.terminate()
        child.wait(timeout=5)
        assert pin.is_alive() is False
        assert pin.identity.pid == child.pid
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if pin is not None:
            pin.close()
