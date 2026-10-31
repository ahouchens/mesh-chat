"""Cancellable reads on a borrowed inherited pipe, without buffered I/O locks.

Wrap before the first frame is read. Only this reader may consume the descriptor;
mixing buffered reads would lose bytes already prefetched by the buffered stream.
The application owns the descriptor and closes it after the reader has stopped.
"""
import io
import os
import select
import stat
from threading import Event


def _windows_available(descriptor):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    handle = msvcrt.get_osfhandle(descriptor)
    peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                     ctypes.POINTER(wintypes.DWORD)]
    peek.restype = wintypes.BOOL

    def available():
        count = wintypes.DWORD()
        if not peek(handle, None, 0, None, ctypes.byref(count), None):
            error = ctypes.get_last_error()
            if error in (109, 232, 233):  # broken, closing or disconnected pipe
                return -1
            raise ctypes.WinError(error)
        return count.value

    return available


class InheritedInput:
    def __init__(self, descriptor):
        self._descriptor = descriptor
        self._cancelled = Event()
        self._available = (_windows_available(descriptor) if os.name == "nt" else
                           lambda: 65536 if select.select([descriptor], [], [], 0)[0] else 0)

    def read(self, length):
        if length <= 0:
            return b""
        while not self._cancelled.is_set():
            available = self._available()
            if available < 0:
                return b""
            if available:
                return os.read(self._descriptor, min(length, available, 65536))
            self._cancelled.wait(.01)
        raise EOFError("Inherited input stopped")

    def cancel(self):
        self._cancelled.set()


def interruptible_input(stream):
    if isinstance(stream, InheritedInput):
        return stream
    try:
        descriptor = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        return stream  # Finite in-memory readers used by protocol tests.
    return InheritedInput(descriptor) if stat.S_ISFIFO(os.fstat(descriptor).st_mode) else stream
