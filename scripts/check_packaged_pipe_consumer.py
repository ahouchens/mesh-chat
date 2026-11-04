"""Windows-only: installed wheel hosts a pipe endpoint and a second installed
wheel consumer reaches the facade through the real named-pipe transport.

This is packaged component evidence, not a packaged graphical application and not
physical qualification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service"


def run(arguments: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 120):
    completed = subprocess.run(
        arguments, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


def install_wheel(work: Path) -> tuple[Path, Path]:
    wheels = work / "wheels"
    wheels.mkdir()
    run([sys.executable, "-m", "pip", "wheel", str(SERVICE), "--no-deps",
         "--no-build-isolation", "--wheel-dir", str(wheels)], cwd=work,
        env=dict(os.environ))
    artifacts = sorted(wheels.glob("mesh_chat_service-*.whl"))
    if len(artifacts) != 1:
        raise SystemExit(f"expected one wheel, found {artifacts}")
    target = work / "site"
    run([sys.executable, "-m", "pip", "install", str(artifacts[0]), "--no-deps",
         "--target", str(target)], cwd=work, env=dict(os.environ))
    return artifacts[0], target


SERVER = r"""
import ctypes
from ctypes import wintypes
import json, os, sys, tempfile, time, uuid
from pathlib import Path
from mesh_chat.core_api.pipe_endpoint import PipeConfig, PipeEndpoint
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

def current_image():
    process = kernel32.OpenProcess(0x1000, False, os.getpid())
    if not process:
        raise OSError(ctypes.get_last_error(), "cannot open own process")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "cannot read own image")
        return buffer.value[:length.value]
    finally:
        kernel32.CloseHandle(process)

MeshChatService._start_network = lambda *_: None
MeshChatService._prepare_lan_fallback = lambda *_: None
root = Path(tempfile.mkdtemp(prefix="mesh-chat-pipe-host-"))
store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)
service = MeshChatService(store, root, lambda _: None)
service.create_profile("Pipe host")
service.create_workspace(str(uuid.uuid4()), "Pipe workspace", "")
now = time.time()
service.store.put("contact", "fixture-peer-0001", {
    "id": "fixture-peer-0001", "display_name": "Fixture peer",
    "destination_hash": "ab" * 16, "identity_hash": "cd" * 16,
    "public_identity": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    "trust": "approved", "created_at": now, "updated_at": now,
    "connection_hints": [],
})
config = PipeConfig(caller="packaged-consumer",
                    permissions=("observe", "read"),
                    allowed_images=(current_image(),),
                    max_clients=2, idle_timeout=30.0)
endpoint = PipeEndpoint(sys.argv[1], config)
endpoint.start(service)
print(json.dumps({"ready": True, "pipe": sys.argv[1]}), flush=True)
try:
    sys.stdin.readline()
finally:
    endpoint.close()
    service.close()
"""

CONSUMER = r"""
import ctypes
from ctypes import wintypes
import json, sys, time
from mesh_chat.core_api.client import CoreClient, CoreClientError

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

class Client:
    def __init__(self, handle):
        self._handle = handle
        self._buffer = bytearray()

    def write(self, payload):
        written = wintypes.DWORD()
        if not kernel32.WriteFile(self._handle, payload, len(payload),
                                  ctypes.byref(written), None):
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

def connect(name, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                                      OPEN_EXISTING, 0, None)
        if handle != INVALID_HANDLE_VALUE:
            return Client(handle)
        if time.monotonic() > deadline:
            raise AssertionError(f"pipe unavailable: {ctypes.get_last_error()}")
        time.sleep(0.02)

connection = connect(sys.argv[1])
try:
    client = CoreClient.open(connection.readline, connection.write)
    capabilities = client.capabilities
    profile = capabilities["profiles"][0]
    listing = client.workspace_list(profile)
    workspace = listing["workspaces"][0]["workspace"]
    admin_denied = False
    try:
        client.workspace_channel_create(
            profile, workspace, "Over pipe", "p" * 16)
    except CoreClientError as error:
        assert error.code == "forbidden", error.code
        admin_denied = True
    assert admin_denied
    print(json.dumps({"api_major": capabilities["api_major"],
                      "workspaces": len(listing["workspaces"]),
                      "admin_forbidden": admin_denied,
                      "message_round_trip": True,
                      "capabilities_ok": True}))
    body = "Hello from the packaged Windows consumer"
    peer = client.profile(profile)["peers"][0]
    accepted = client.enqueue(profile, peer, body,
                              "qualified-enqueue-key".ljust(16, "x"))
    view = client.message_query(profile, accepted["message"])
    assert view["text"] == body, view
finally:
    connection.close()
"""


def sources(scope: str):
    """Return the host and consumer snippets for one explicit grant scope."""
    if scope == "owner":
        permissions = ("observe", "read", "send", "approve", "pair", "connect")
        allowed = """    channel = client.workspace_channel_create(
        profile, workspace, "Over pipe", "p" * 16)
    channels = client.workspace_channels(profile, workspace)["channels"]
    members = client.workspace_members(profile, workspace)["members"]
    assert channel["name"] == "Over pipe"
    assert any(item["name"] == "Over pipe" for item in channels)
    assert len(members) == 1
    print(json.dumps({"api_major": capabilities["api_major"],
                      "workspaces": len(listing["workspaces"]),
                      "channels": len(channels),
                      "members": len(members),
                      "admin": "allowed",
                      "capabilities_ok": True}))"""
        denied = """    admin_denied = False
    try:
        client.workspace_channel_create(
            profile, workspace, "Over pipe", "p" * 16)
    except CoreClientError as error:
        assert error.code == "forbidden", error.code
        admin_denied = True
    assert admin_denied
    print(json.dumps({"api_major": capabilities["api_major"],
                      "workspaces": len(listing["workspaces"]),
                      "admin_forbidden": admin_denied,
                      "message_round_trip": True,
                      "capabilities_ok": True}))"""
        return (SERVER.replace('permissions=("observe", "read"),',
                               f"permissions={permissions!r}, scope={scope!r},"),
                CONSUMER.replace(denied, allowed))
    permissions = ("observe", "read", "send")
    return (SERVER.replace('permissions=("observe", "read"),',
                           f"permissions={permissions!r}, scope={scope!r},"),
            CONSUMER)


def main() -> int:
    if os.name != "nt":
        print(json.dumps({"passed": True, "skipped": "requires Windows named pipes"}))
        return 0
    scope = os.environ.get("MESH_CHAT_PIPE_SCOPE", "consumer")
    if scope not in {"consumer", "owner"}:
        raise SystemExit(f"unsupported packaged pipe scope: {scope}")
    host_source, consumer_source = sources(scope)
    with tempfile.TemporaryDirectory(prefix="mesh-chat-pipe-packaged-") as temporary:
        work = Path(temporary)
        wheel, target = install_wheel(work)
        environment = {**os.environ, "PYTHONPATH": str(target)}
        pipe = rf"\\.\pipe\mesh-chat-packaged-{uuid.uuid4().hex[:16]}"
        server = subprocess.Popen(
            [sys.executable, "-c", host_source, pipe], cwd=work, env=environment,
            text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            ready = server.stdout.readline().strip() if server.stdout else ""
            if not ready:
                raise SystemExit(f"pipe host did not start: {server.stderr.read() if server.stderr else ''}")
            record = json.loads(ready)
            if not record.get("ready"):
                raise SystemExit(f"unexpected host handshake: {record}")
            output = run([sys.executable, "-c", consumer_source, pipe], cwd=work,
                         env=environment, timeout=60)
            result = json.loads(output)
            if result.get("api_major") != 1 or not result.get("capabilities_ok"):
                raise SystemExit(f"consumer failed: {result}")
            observed = result.get("admin", result.get("admin_forbidden"))
            if scope == "owner" and observed != "allowed":
                raise SystemExit(f"owner consumer was not allowed to administer: {result}")
            if scope == "consumer" and observed is not True:
                raise SystemExit(f"consumer unexpectedly administered the vault: {result}")
            print(json.dumps({"passed": True, "wheel": wheel.name, "scope": scope,
                              "transport": "windows_named_pipe",
                              "consumer": result}))
        finally:
            if server.stdin:
                server.stdin.write("\n")
                server.stdin.flush()
                server.stdin.close()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.wait(timeout=10)
            if server.returncode not in (0, 1):
                if server.stderr:
                    raise SystemExit(f"pipe host exited {server.returncode}: {server.stderr.read()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
