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
from typing import Callable

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
WAIT_FAILED = 0xFFFFFFFF
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
RETIRE_JOIN_SECONDS = 5.0


class PipeRetirementPending(RuntimeError):
    """A pipe worker or exact handle still belongs to the endpoint."""


@dataclass(frozen=True, eq=False)
class PipeClientAdmission:
    """Trusted per-connection authority; release must be idempotent."""

    authorize: Callable[[], bool]
    release: Callable[[], None]

    def __post_init__(self):
        if not callable(self.authorize) or not callable(self.release):
            raise ValueError("Core API client admission hooks are invalid")


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


def _cancel_and_complete(kernel, handle, overlapped, transferred):
    """A cancellation request does not retire the pending OVERLAPPED state."""
    try:
        kernel.CancelIoEx(handle, ctypes.byref(overlapped))
    finally:
        kernel.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                   ctypes.byref(transferred), True)


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

    def readline(self, limit, *, deadline=None):
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Core API pipe read deadline expired")
            index = self._buffer.find(b"\n")
            if index >= 0:
                if index + 1 > limit:
                    raise ValueError("Core API frame exceeds its ceiling")
                line = bytes(self._buffer[:index + 1])
                del self._buffer[:index + 1]
                return line
            if len(self._buffer) > limit:
                raise ValueError("Core API frame exceeds its ceiling")
            chunk = self._read(min(max(limit + 1 - len(self._buffer), 1), BUFFER_BYTES),
                               deadline=deadline)
            if chunk == b"":
                return b""
            self._buffer.extend(chunk)

    def _read(self, size, *, deadline=None):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Core API pipe read deadline expired")
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
            outcome = self._kernel.WaitForSingleObject(event, 50)
            while outcome == WAIT_TIMEOUT:
                if (self._stop.is_set()
                        or time.monotonic() - self._last_activity >= self._idle_timeout
                        or (deadline is not None and time.monotonic() >= deadline)):
                    try:
                        _cancel_and_complete(self._kernel, self._handle, overlapped, read)
                    finally:
                        self._kernel.CloseHandle(event)
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Core API pipe read deadline expired")
                    return b""
                outcome = self._kernel.WaitForSingleObject(event, 50)
            if outcome != WAIT_OBJECT_0:
                try:
                    _cancel_and_complete(self._kernel, self._handle, overlapped, read)
                finally:
                    self._kernel.CloseHandle(event)
                raise OSError("Core API pipe read wait failed")
        if not self._finish(overlapped, read, event):
            return b""
        self._last_activity = time.monotonic()
        if deadline is not None and self._last_activity >= deadline:
            raise TimeoutError("Core API pipe read deadline expired")
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
                outcome = self._kernel.WaitForSingleObject(event, 50)
                while outcome == WAIT_TIMEOUT:
                    if self._stop.is_set():
                        try:
                            _cancel_and_complete(self._kernel, self._handle, overlapped, written)
                        finally:
                            self._kernel.CloseHandle(event)
                        raise OSError(ERROR_OPERATION_ABORTED, "Core API pipe write canceled")
                    outcome = self._kernel.WaitForSingleObject(event, 50)
                if outcome != WAIT_OBJECT_0:
                    try:
                        _cancel_and_complete(self._kernel, self._handle, overlapped, written)
                    finally:
                        self._kernel.CloseHandle(event)
                    raise OSError("Core API pipe write wait failed")
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
    scope: str = "consumer"
    private_native: bool = False
    private_profile_bootstrap: bool = False
    private_composer_legacy: bool = False

    def __post_init__(self):
        host.host_grant(self.caller, self.permissions, scope=self.scope,
                        private_profile_bootstrap=self.private_profile_bootstrap)
        if type(self.private_native) is not bool or (self.private_native and self.scope != "owner"):
            raise ValueError("Private native binding requires the application owner")
        if type(self.private_composer_legacy) is not bool or (self.private_composer_legacy and self.scope != "owner"):
            raise ValueError("Private composer migration requires the application owner")
        validate_images(self.allowed_images)
        if type(self.max_clients) is not int or not 1 <= self.max_clients <= 8:
            raise ValueError("Core API endpoint client budget is invalid")
        if type(self.idle_timeout) not in {int, float} or not 0.1 <= self.idle_timeout <= 3600:
            raise ValueError("Core API endpoint idle timeout is invalid")


class PipeEndpoint:
    """One host-owned endpoint; callers cannot choose its name or allowlist."""

    def __init__(self, name, config, *, admit_client=None):
        if os.name != "nt":
            raise RuntimeError("The core API pipe endpoint requires Windows")
        if not isinstance(config, PipeConfig):
            raise ValueError("Core API endpoint configuration is required")
        if admit_client is not None and not callable(admit_client):
            raise ValueError("Core API client admission must be a host callback")
        self.kernel, self.advapi = _bind()
        self._name = pipe_name(name)
        self._images = config.allowed_images
        self._admit_client = admit_client
        self._grant = host.host_grant(config.caller, config.permissions,
                                      scope=config.scope,
                                      private_profile_bootstrap=config.private_profile_bootstrap)
        self._scope = config.scope
        self._private_native = config.private_native
        self._private_profile_bootstrap = config.private_profile_bootstrap
        self._private_composer_legacy = config.private_composer_legacy
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._handles = set()
        self._query_handles = set()
        self._admissions = set()
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
            for handle in tuple(self._handles):
                # This requests cancellation; the worker still owns its handle
                # until the pending OVERLAPPED operation and worker complete.
                try:
                    self.kernel.CancelIoEx(handle, None)
                except OSError:
                    pass
        deadline = time.monotonic() + RETIRE_JOIN_SECONDS
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self._threads):
            raise PipeRetirementPending("Core API pipe workers are still active")
        with self._lock:
            for handle in tuple(self._handles):
                self._close_handle_locked(handle)
            for handle in tuple(self._query_handles):
                self._close_query_handle_locked(handle)
            for admission in tuple(self._admissions):
                self._release_admission_locked(admission)
            if self._handles or self._query_handles or self._admissions:
                raise PipeRetirementPending("Core API pipe custody is not retired")

    def _close_handle_locked(self, handle):
        """Only a positive CloseHandle releases endpoint custody."""
        try:
            closed = self.kernel.CloseHandle(handle)
        except Exception:
            closed = False
        if closed:
            self._handles.discard(handle)
        elif self.failure is None:
            self.failure = "Core API pipe handle close failed"
        return bool(closed)

    def _retire_worker_handle(self, handle):
        try:
            self.kernel.DisconnectNamedPipe(handle)
        except Exception:
            pass  # Closing the exact handle still retires a disconnected pipe.
        with self._lock:
            return self._close_handle_locked(handle)

    def _close_query_handle_locked(self, handle):
        try:
            closed = self.kernel.CloseHandle(handle)
        except Exception:
            closed = False
        if closed:
            self._query_handles.discard(handle)
        elif self.failure is None:
            self.failure = "Core API client process handle close failed"
        return bool(closed)

    def _release_admission_locked(self, admission):
        try:
            admission.release()
        except Exception:
            if self.failure is None:
                self.failure = "Core API client admission release failed"
            return False
        self._admissions.discard(admission)
        return True

    def _client_pid(self, handle):
        pid = wintypes.ULONG()
        if not self.kernel.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)) or pid.value == 0:
            return None
        return pid.value

    def _serve_client(self, service, handle):
        while not self._stop.is_set():
            if handle is None:
                try:
                    handle = self._create()
                except OSError as error:
                    self.failure = f"{type(error).__name__}: {error}"[:120]
                    return
            admission = None
            try:
                if self._connect(handle):
                    stream = _Duplex(self.kernel, handle, self._stop, self._idle_timeout)
                    pid = self._client_pid(handle)
                    image = self._client_image(handle, pid) if pid is not None else None
                    allowed = not self._stop.is_set() and image_allowed(image, self._images)
                    if allowed and self._admit_client is not None:
                        try:
                            admission = self._admit_client(pid, stream)
                        except Exception:
                            if self.failure is None:
                                self.failure = "Core API client admission failed"
                            admission = None
                        allowed = isinstance(admission, PipeClientAdmission)
                        if not allowed and admission is not None:
                            if self.failure is None:
                                self.failure = "Core API client admission returned invalid custody"
                            admission = None
                    if not allowed:
                        with self._lock:
                            self.rejected += 1
                    else:
                        if admission is not None:
                            with self._lock:
                                self._admissions.add(admission)
                        with self._lock:
                            self.accepted += 1
                        session = host.bind_host_stream(service, caller=self._grant.caller,
                                                        permissions=self._grant.permissions,
                                                        profiles=self._grant.profiles,
                                                        scope=self._scope,
                                                        private_native=self._private_native,
                                                        private_profile_bootstrap=self._private_profile_bootstrap,
                                                        private_composer_legacy=self._private_composer_legacy,
                                                        authorize=admission.authorize if admission else None)
                        session.serve(stream, stream)
            except (OSError, ValueError) as error:
                if self._stop.is_set():
                    return
                self.failure = f"{type(error).__name__}: {error}"[:120]
            finally:
                if admission is not None:
                    with self._lock:
                        self._release_admission_locked(admission)
                retired = self._retire_worker_handle(handle)
                handle = None
            if not retired:
                return  # Keep the exact handle for close() to retry.

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
            outcome = self.kernel.WaitForSingleObject(event, 50)
            while outcome == WAIT_TIMEOUT:
                if self._stop.is_set():
                    transferred = wintypes.DWORD()
                    _cancel_and_complete(self.kernel, handle, overlapped, transferred)
                    raise OSError(ERROR_OPERATION_ABORTED, "Core API endpoint stopped")
                outcome = self.kernel.WaitForSingleObject(event, 50)
            if outcome != WAIT_OBJECT_0:
                transferred = wintypes.DWORD()
                _cancel_and_complete(self.kernel, handle, overlapped, transferred)
                raise OSError("Core API pipe accept wait failed")
            transferred = wintypes.DWORD()
            if not self.kernel.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                                   ctypes.byref(transferred), False):
                error = ctypes.get_last_error()
                if error in {ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED, ERROR_OPERATION_ABORTED}:
                    return False
                raise OSError(error, "Core API endpoint cannot accept a client")
            return True
        finally:
            self.kernel.CloseHandle(event)

    def _client_image(self, handle, pid=None):
        pid = self._client_pid(handle) if pid is None else pid
        if pid is None:
            return None
        process = self.kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return None
        with self._lock:
            self._query_handles.add(process)
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not self.kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                return None
            return buffer.value[:length.value]
        finally:
            with self._lock:
                if not self._close_query_handle_locked(process):
                    self._stop.set()  # A failed query-handle close blocks new admissions.
