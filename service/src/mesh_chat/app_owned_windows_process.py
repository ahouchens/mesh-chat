"""Windows process-object custody for the private app-owned admission roster.

The caller owns every handle returned by open. If an identity query fails
and Windows refuses to close the newly opened handle, the port retains it for
an explicit retire retry. This module does not admit pipe clients itself.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from threading import RLock

from .app_owned_admission import MAX_PID, ProcessIdentity
from .core_api.pipe_policy import MAX_IMAGE_LENGTH


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


def _bind_kernel():
    if os.name != "nt":
        raise OSError("Windows process handles require Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _failure(operation: str) -> OSError:
    return OSError(ctypes.get_last_error(), operation)


def _alive(kernel, handle: int) -> bool:
    result = kernel.WaitForSingleObject(handle, 0)
    if result == WAIT_TIMEOUT:
        return True
    if result == WAIT_OBJECT_0:
        return False
    raise _failure("WaitForSingleObject")


class WindowsProcessHandle:
    """One exact process object, with serialized wait and close operations."""

    def __init__(self, kernel, handle: int, identity: ProcessIdentity):
        self._kernel = kernel
        self._handle = handle
        self._identity = identity
        self._lock = RLock()

    @property
    def identity(self) -> ProcessIdentity:
        return self._identity

    def is_alive(self) -> bool:
        with self._lock:
            if self._handle is None:
                raise ValueError("Process handle is closed")
            return _alive(self._kernel, self._handle)

    def close(self) -> None:
        with self._lock:
            if self._handle is None:
                return
            if not self._kernel.CloseHandle(self._handle):
                raise _failure("CloseHandle")
            self._handle = None


class WindowsProcessPort:
    """Open only live process objects with pinned generation and image."""

    def __init__(self, *, kernel=None):
        self._kernel = _bind_kernel() if kernel is None else kernel
        self._retained: list[int] = []
        self._lock = RLock()

    def _creation_time(self, handle: int) -> int:
        created, exited, kernel_time, user_time = (_FileTime() for _ in range(4))
        if not self._kernel.GetProcessTimes(handle, ctypes.byref(created),
                ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise _failure("GetProcessTimes")
        return (created.high << 32) | created.low

    def _image(self, handle: int) -> str:
        image = ctypes.create_unicode_buffer(MAX_IMAGE_LENGTH + 1)
        length = wintypes.DWORD(len(image))
        if not self._kernel.QueryFullProcessImageNameW(handle, 0, image,
                ctypes.byref(length)):
            raise _failure("QueryFullProcessImageNameW")
        if not 1 <= length.value <= MAX_IMAGE_LENGTH:
            raise ValueError("Process image path is invalid")
        return image[:length.value]

    def _retain_if_close_fails(self, handle: int) -> None:
        try:
            if self._kernel.CloseHandle(handle):
                return
        except Exception:
            pass
        with self._lock:
            self._retained.append(handle)

    def open(self, pid: int) -> WindowsProcessHandle:
        if type(pid) is not int or not 1 <= pid <= MAX_PID:
            raise ValueError("Process identifier is invalid")
        with self._lock:
            handle = self._kernel.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                raise _failure("OpenProcess")
            try:
                identity = ProcessIdentity(pid, self._creation_time(handle),
                                           self._image(handle))
                if not _alive(self._kernel, handle):
                    raise ProcessLookupError("Process exited during admission")
                return WindowsProcessHandle(self._kernel, handle, identity)
            except BaseException:
                self._retain_if_close_fails(handle)
                raise

    def retire(self) -> bool:
        """Retry handles retained after failed acquisition cleanup."""
        with self._lock:
            pending = self._retained
            self._retained = []
            for handle in pending:
                try:
                    if self._kernel.CloseHandle(handle):
                        continue
                except Exception:
                    pass
                self._retained.append(handle)
            return not self._retained
