"""Minimal Windows named-pipe client for the private core API CLI."""

import ctypes
from ctypes import wintypes
import os
import time

from .limits import MAX_FRAME_BYTES


if os.name != "nt":  # pragma: no cover - import guard
    raise RuntimeError("The core API pipe client requires Windows")

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2
BUFFER_BYTES = 65536

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class PipeClient:
    def __init__(self, handle):
        self._handle = handle
        self._buffer = bytearray()

    def write(self, payload):
        view = memoryview(payload)
        total = 0
        while total < len(view):
            chunk = view[total:total + BUFFER_BYTES]
            written = wintypes.DWORD()
            if not _kernel32.WriteFile(self._handle, chunk, len(chunk), ctypes.byref(written), None):
                raise OSError(ctypes.get_last_error(), "core API pipe write failed")
            if written.value == 0:
                raise OSError("core API pipe write stalled")
            total += written.value
        return total

    def readline(self, limit=MAX_FRAME_BYTES + 1):
        while True:
            index = self._buffer.find(b"\n")
            if index >= 0:
                line = bytes(self._buffer[:index + 1])
                del self._buffer[:index + 1]
                return line
            if len(self._buffer) > limit:
                raise OSError("core API frame exceeds its ceiling")
            chunk = ctypes.create_string_buffer(BUFFER_BYTES)
            read = wintypes.DWORD()
            if not _kernel32.ReadFile(self._handle, chunk, BUFFER_BYTES, ctypes.byref(read), None):
                error = ctypes.get_last_error()
                if error in (109, 233):
                    return b""
                raise OSError(error, "core API pipe read failed")
            if read.value == 0:
                return b""
            self._buffer.extend(chunk.raw[:read.value])

    def close(self):
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def connect(name, timeout=5.0):
    if not isinstance(name, str) or not name:
        raise ValueError("A host pipe name is required")
    deadline = time.monotonic() + timeout
    while True:
        handle = _kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                                       OPEN_EXISTING, 0, None)
        if handle != INVALID_HANDLE_VALUE:
            return PipeClient(handle)
        error = ctypes.get_last_error()
        if error not in {ERROR_PIPE_BUSY, ERROR_FILE_NOT_FOUND} or time.monotonic() > deadline:
            raise OSError(error, "core API pipe connection failed")
        time.sleep(0.02)
