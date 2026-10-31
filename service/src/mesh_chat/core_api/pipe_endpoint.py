"""Private Windows named-pipe endpoint for the core API.

The endpoint is owned by the trusted host process. Its security descriptor
grants only SYSTEM and the current user, it rejects remote clients, it refuses
to reuse an existing pipe name, and it admits a connection only when the client's
executable image exactly matches a host-supplied allowlist. It serves one
authenticated client at a time and never starts a second runtime.

All pipe I/O is overlapped so shutdown can cancel a pending accept or read
instead of blocking forever on a handle close.

This is the Windows host binding; Android still requires its own Binder binding.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import threading
import time

from . import host
from .pipe_policy import allowed_images as validate_images, image_allowed, pipe_name


INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255
BUFFER_BYTES = 65536
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_ACCESS_DENIED = 5
TOKEN_QUERY = 0x0008
TOKEN_USER = 1
SDDL_REVISION_1 = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


def _bind():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
    kernel.DisconnectNamedPipe.restype = wintypes.BOOL
    kernel.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
    kernel.GetOverlappedResult.restype = wintypes.BOOL
    kernel.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
        ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
    kernel.CancelIoEx.restype = wintypes.BOOL
    kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetNamedPipeClientProcessId.restype = wintypes.BOOL
    kernel.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
    return kernel, advapi


class _Duplex:
    """Overlapped byte duplex over one connected pipe handle."""

    def __init__(self, kernel, handle, stop, idle_timeout):
        self._kernel = kernel
        self._handle = handle
        self._stop = stop
        self._idle_timeout = idle_timeout
        self._last_activity = time.monotonic()
        self._buffer = bytearray()

    def _event(self):
        event = self._kernel.CreateEventW(None, True, False, None)
        if not event:
            raise OSError(ctypes.get_last_error(), "Core API pipe event failed")
        return event

    def _finish(self, overlapped, written, event):
        try:
            if not self._kernel.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                    ctypes.byref(written), False):
                error = ctypes.get_last_error()
                if error in {ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED, ERROR_OPERATION_ABORTED}:
                    return False
                raise OSError(error, "Core API pipe operation failed")
            return True
        finally:
            self._kernel.CloseHandle(event)

    def readline(self, limit):
        while True:
            index = self._buffer.find(b"\n")
            if index >= 0:
                line = bytes(self._buffer[:index + 1])
                del self._buffer[:index + 1]
                return line
            if len(self._buffer) > limit:
                raise ValueError("Core API frame exceeds its ceiling")
            chunk = self._read(min(max(limit + 1 - len(self._buffer), 1), BUFFER_BYTES))
            if chunk == b"":
                return b""
            self._buffer.extend(chunk)

    def _read(self, size):
        event = self._event()
        overlapped = OVERLAPPED()
        overlapped.hEvent = event
        data = ctypes.create_string_buffer(size)
        read = wintypes.DWORD()
        if not self._kernel.ReadFile(self._handle, data, size, ctypes.byref(read),
                                     ctypes.byref(overlapped)):
            error = ctypes.get_last_error()
            if error != ERROR_IO_PENDING:
                self._kernel.CloseHandle(event)
                if error in {ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED, ERROR_OPERATION_ABORTED}:
                    return b""
                raise OSError(error, "Core API pipe read failed")
            while self._kernel.WaitForSingleObject(event, 50) == WAIT_TIMEOUT:
                if (self._stop.is_set()
                        or time.monotonic() - self._last_activity >= self._idle_timeout):
                    self._kernel.CancelIoEx(self._handle, ctypes.byref(overlapped))
                    self._kernel.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                     ctypes.byref(read), False)
                    self._kernel.CloseHandle(event)
                    return b""
        if not self._finish(overlapped, read, event):
            return b""
        self._last_activity = time.monotonic()
        return data.raw[:read.value]

    def write(self, payload):
        view = bytes(payload)
        total = 0
        while total < len(view):
            chunk = view[total:total + BUFFER_BYTES]
            event = self._event()
            overlapped = OVERLAPPED()
            overlapped.hEvent = event
            written = wintypes.DWORD()
            if not self._kernel.WriteFile(self._handle, chunk, len(chunk), ctypes.byref(written),
                                          ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    self._kernel.CloseHandle(event)
                    raise OSError(error, "Core API pipe write failed")
                while self._kernel.WaitForSingleObject(event, 50) == WAIT_TIMEOUT:
                    if self._stop.is_set():
                        self._kernel.CancelIoEx(self._handle, ctypes.byref(overlapped))
                        self._kernel.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                         ctypes.byref(written), False)
                        self._kernel.CloseHandle(event)
                        raise OSError(ERROR_OPERATION_ABORTED, "Core API pipe write canceled")
            if not self._finish(overlapped, written, event) or written.value == 0:
                raise OSError("Core API pipe write failed")
            self._last_activity = time.monotonic()
            total += written.value
        return total

    def flush(self):
        return None


@dataclass(frozen=True)
class PipeConfig:
    """Validated host facts for one endpoint; callers cannot choose defaults."""

    caller: str
    permissions: tuple
    allowed_images: tuple
    max_clients: int = 4
    idle_timeout: float = 60.0

    def __post_init__(self):
        host.host_grant(self.caller, self.permissions)
        validate_images(self.allowed_images)
        if type(self.max_clients) is not int or not 1 <= self.max_clients <= 8:
            raise ValueError("Core API endpoint client budget is invalid")
        if type(self.idle_timeout) not in {int, float} or not 0.1 <= self.idle_timeout <= 3600:
            raise ValueError("Core API endpoint idle timeout is invalid")


class PipeEndpoint:
    """One host-owned endpoint; callers cannot choose its name or allowlist."""

    def __init__(self, name, config):
        if os.name != "nt":
            raise RuntimeError("The core API pipe endpoint requires Windows")
        if not isinstance(config, PipeConfig):
            raise ValueError("Core API endpoint configuration is required")
        self.kernel, self.advapi = _bind()
        self._name = pipe_name(name)
        self._images = config.allowed_images
        self._grant = host.host_grant(config.caller, config.permissions)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._handles = set()
        self._error = None
        self._threads = []
        self._max_clients = config.max_clients
        self._idle_timeout = float(config.idle_timeout)
        self.rejected = 0
        self.accepted = 0
        self.failure = None

    @property
    def name(self):
        return self._name

    def start(self, service):
        if self._threads:
            raise RuntimeError("Core API endpoint is already running")
        try:
            first = self._create(first=True)
        except OSError as error:
            self._error = error
            self._ready.set()
            raise
        self._ready.set()
        first_worker = threading.Thread(target=self._serve_client, args=(service, first),
                                        name="mesh-core-api-pipe-0", daemon=True)
        first_worker.start()
        self._threads.append(first_worker)
        for index in range(1, self._max_clients):
            worker = threading.Thread(target=self._serve_client, args=(service, None),
                                      name=f"mesh-core-api-pipe-{index}", daemon=True)
            worker.start()
            self._threads.append(worker)

    def close(self):
        self._stop.set()
        with self._lock:
            handles = tuple(self._handles)
        for handle in handles:
            # Cancels a pending accept/read so the worker returns instead of
            # blocking on a synchronous handle close.
            self.kernel.CancelIoEx(handle, None)
        for thread in self._threads:
            thread.join(5)
        with self._lock:
            stale = tuple(self._handles)
            self._handles.clear()
        for handle in stale:
            self.kernel.CloseHandle(handle)

    def _serve_client(self, service, handle):
        while not self._stop.is_set():
            if handle is None:
                try:
                    handle = self._create()
                except OSError as error:
                    self.failure = f"{type(error).__name__}: {error}"[:120]
                    return
            try:
                if not self._connect(handle):
                    continue
                image = self._client_image(handle)
                if not image_allowed(image, self._images):
                    with self._lock:
                        self.rejected += 1
                    continue
                with self._lock:
                    self.accepted += 1
                session = host.bind_host_stream(service, caller=self._grant.caller,
                                                permissions=self._grant.permissions,
                                                profiles=self._grant.profiles)
                session.serve(_Duplex(self.kernel, handle, self._stop, self._idle_timeout),
                              _Duplex(self.kernel, handle, self._stop, self._idle_timeout))
            except (OSError, ValueError) as error:
                if self._stop.is_set():
                    return
                self.failure = f"{type(error).__name__}: {error}"[:120]
            finally:
                with self._lock:
                    self._handles.discard(handle)
                self.kernel.DisconnectNamedPipe(handle)
                self.kernel.CloseHandle(handle)
                handle = None

    def _security(self):
        token = wintypes.HANDLE()
        if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), TOKEN_QUERY,
                                            ctypes.byref(token)):
            raise OSError(ctypes.get_last_error(), "Core API endpoint cannot read its token")
        try:
            size = wintypes.DWORD()
            self.advapi.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            if not self.advapi.GetTokenInformation(token, TOKEN_USER, buffer, size,
                                                   ctypes.byref(size)):
                raise OSError(ctypes.get_last_error(), "Core API endpoint cannot read its user")
            sid = ctypes.c_void_p.from_buffer(buffer).value
            text = wintypes.LPWSTR()
            if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise OSError(ctypes.get_last_error(), "Core API endpoint cannot format its user")
            try:
                sddl = f"D:(A;;GA;;;SY)(A;;GA;;;{text.value})"
            finally:
                self.kernel.LocalFree(text)
        finally:
            self.kernel.CloseHandle(token)
        descriptor = ctypes.c_void_p()
        size = wintypes.ULONG()
        if not self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, SDDL_REVISION_1, ctypes.byref(descriptor), ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "Core API endpoint security descriptor failed")
        return descriptor

    def _create(self, first=False):
        descriptor = self._security()
        attributes = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
        handle = self.kernel.CreateNamedPipeW(
            self._name,
            PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0),
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES, BUFFER_BYTES, BUFFER_BYTES, 0, ctypes.byref(attributes))
        if handle == INVALID_HANDLE_VALUE or handle is None:
            error = ctypes.get_last_error()
            self.kernel.LocalFree(descriptor)
            raise OSError(error, "Core API endpoint cannot create its pipe")
        self.kernel.LocalFree(descriptor)
        with self._lock:
            self._handles.add(handle)
        return handle

    def _connect(self, handle):
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise OSError(ctypes.get_last_error(), "Core API pipe event failed")
        overlapped = OVERLAPPED()
        overlapped.hEvent = event
        try:
            if self.kernel.ConnectNamedPipe(handle, ctypes.byref(overlapped)):
                return True
            error = ctypes.get_last_error()
            if error == ERROR_PIPE_CONNECTED:
                return True
            if error != ERROR_IO_PENDING:
                if error in {ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED, ERROR_ACCESS_DENIED}:
                    return False
                raise OSError(error, "Core API endpoint cannot accept a client")
            while self.kernel.WaitForSingleObject(event, 50) == WAIT_TIMEOUT:
                if self._stop.is_set():
                    self.kernel.CancelIoEx(handle, ctypes.byref(overlapped))
                    raise OSError(ERROR_OPERATION_ABORTED, "Core API endpoint stopped")
            return True
        finally:
            self.kernel.CloseHandle(event)

    def _client_image(self, handle):
        pid = wintypes.ULONG()
        if not self.kernel.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)):
            return None
        process = self.kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not self.kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                return None
            return buffer.value[:length.value]
        finally:
            self.kernel.CloseHandle(process)
