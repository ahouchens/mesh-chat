"""Windows-only integration evidence for the private core API pipe endpoint.

This file lives outside the required connection inventory because it cannot run
on the Linux runners. It is executed on Windows before a push.
"""

import ctypes
from ctypes import wintypes
import io
import json
import os
import time
import uuid

import pytest

if os.name != "nt":
    pytest.skip("Windows named pipes are required", allow_module_level=True)

from mesh_chat.core_api.pipe_endpoint import PipeEndpoint
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_FRAME = 4 * 1024 * 1024

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]


class Client:
    def __init__(self, handle):
        self._handle = handle
        self._buffer = bytearray()

    def write(self, payload):
        written = wintypes.DWORD()
        if not kernel32.WriteFile(self._handle, payload, len(payload), ctypes.byref(written), None):
            raise OSError(ctypes.get_last_error(), "client write failed")
        return written.value

    def readline(self, limit=MAX_FRAME):
        while True:
            index = self._buffer.find(b"\n")
            if index >= 0:
                line = bytes(self._buffer[:index + 1])
                del self._buffer[:index + 1]
                return line
            if len(self._buffer) > limit:
                raise AssertionError("client frame exceeded its ceiling")
            data = ctypes.create_string_buffer(4096)
            read = wintypes.DWORD()
            if not kernel32.ReadFile(self._handle, data, 4096, ctypes.byref(read), None):
                error = ctypes.get_last_error()
                if error in (109, 233):
                    return b""
                raise OSError(error, "client read failed")
            if read.value == 0:
                return b""
            self._buffer.extend(data.raw[:read.value])

    def close(self):
        kernel32.CloseHandle(self._handle)


def connect(name, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                                      OPEN_EXISTING, 0, None)
        if handle != INVALID_HANDLE_VALUE:
            return Client(handle)
        if time.monotonic() > deadline:
            raise AssertionError(f"pipe unavailable: {ctypes.get_last_error()}")
        time.sleep(0.02)


def current_image():
    """The real image path; a Windows venv launcher differs from sys.executable."""
    process = kernel32.OpenProcess(0x1000, False, os.getpid())
    assert process
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        assert kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length))
        return buffer.value[:length.value]
    finally:
        kernel32.CloseHandle(process)


def endpoint(name, images=None, caller="mesh-chat-desktop", permissions=("observe", "read", "send")):
    return PipeEndpoint(name, allowed_images=images or (current_image(),),
                        caller=caller, permissions=permissions)


def pipe_name():
    return rf"\\.\pipe\mesh-chat-test-{uuid.uuid4().hex[:16]}"


def frame(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def request(operation, **params):
    return frame({"api_version": 1, "request_id": "windows:1", "operation": operation, "params": params})


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    instance = MeshChatService(store, tmp_path, lambda _: None)
    if store.get("profile", "local") is None:
        instance.create_profile("Alex")
    yield instance
    instance.close()


def test_endpoint_serves_a_negotiated_session_to_an_allowed_client(service):
    name = pipe_name()
    server = endpoint(name)
    server.start(service)
    try:
        client = connect(name)
        client.write(request("runtime.capabilities"))
        line = client.readline()
        assert line != b"", f"no reply rejected={server.rejected} accepted={server.accepted} failure={server.failure}"
        reply = json.loads(line)
        assert reply["ok"] is True
        assert "message.received" in reply["result"]["operations"]
        client.close()
        deadline = time.monotonic() + 5
        while server.accepted < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.accepted == 1
    finally:
        server.close()


def test_an_unlisted_client_image_is_rejected_without_a_session(service):
    name = pipe_name()
    server = endpoint(name, images=(r"C:\Windows\System32\notepad.exe",))
    server.start(service)
    try:
        client = connect(name)
        try:
            client.write(request("runtime.capabilities"))
        except OSError:
            pass
        assert client.readline() == b""
        client.close()
        deadline = time.monotonic() + 5
        while server.rejected < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.rejected == 1 and server.accepted == 0
    finally:
        server.close()


def test_clients_are_served_one_at_a_time(service):
    name = pipe_name()
    server = endpoint(name)
    server.start(service)
    try:
        for _ in range(2):
            client = connect(name)
            client.write(request("runtime.capabilities"))
            assert json.loads(client.readline())["ok"] is True
            client.close()
        deadline = time.monotonic() + 5
        while server.accepted < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.accepted == 2
    finally:
        server.close()


def test_a_second_endpoint_cannot_reuse_a_live_pipe_name(service):
    name = pipe_name()
    first = endpoint(name)
    first.start(service)
    try:
        with pytest.raises(OSError):
            endpoint(name).start(service)
    finally:
        first.close()


def test_the_endpoint_refuses_untrusted_configuration():
    with pytest.raises(ValueError):
        endpoint(r"\\.\pipe\other-endpoint")
    with pytest.raises(ValueError):
        endpoint(pipe_name(), permissions=("runtime_owner",))
    with pytest.raises(ValueError):
        endpoint(pipe_name(), images=("relative.exe",))

def test_bounded_concurrent_clients_are_served_independently(service):
    name = pipe_name()
    server = endpoint(name)
    server.start(service)
    try:
        first, second = connect(name), connect(name)
        first.write(request("runtime.capabilities"))
        second.write(request("runtime.capabilities"))
        assert json.loads(first.readline())["ok"] is True
        assert json.loads(second.readline())["ok"] is True
        deadline = time.monotonic() + 5
        while server.accepted < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.accepted == 2
        first.close()
        second.close()
    finally:
        server.close()


def test_client_budget_is_bounded():
    for value in (0, 9, True, "4"):
        with pytest.raises(ValueError):
            PipeEndpoint(pipe_name(), allowed_images=(current_image(),),
                         caller="mesh-chat-desktop", permissions=("observe",), max_clients=value)

def test_cli_queries_the_endpoint_over_the_host_pipe(service):
    from mesh_chat.core_api.cli import run

    name = pipe_name()
    server = endpoint(name)
    server.start(service)
    try:
        client = connect(name)
        out, err = io.StringIO(), io.StringIO()
        try:
            assert run(["--pipe", name, "capabilities"], client, out, err) == 0
        finally:
            client.close()
        result = json.loads(out.getvalue())
        assert "message.received" in result["operations"]
        assert err.getvalue() == ""
    finally:
        server.close()

def test_idle_client_is_disconnected_and_does_not_hold_a_worker(service):
    name = pipe_name()
    server = PipeEndpoint(name, allowed_images=(current_image(),), caller="mesh-chat-desktop",
                          permissions=("observe", "read"), idle_timeout=0.5)
    server.start(service)
    try:
        idle = connect(name)
        assert idle.readline() == b""
        idle.close()
        client = connect(name)
        client.write(request("runtime.capabilities"))
        assert json.loads(client.readline())["ok"] is True
        client.close()
    finally:
        server.close()


def test_idle_timeout_is_bounded():
    for value in (0, -1, 3601, "60", True):
        with pytest.raises(ValueError):
            PipeEndpoint(pipe_name(), allowed_images=(current_image(),),
                         caller="mesh-chat-desktop", permissions=("observe",), idle_timeout=value)
