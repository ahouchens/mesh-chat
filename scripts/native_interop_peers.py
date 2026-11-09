"""Controller clients for actual frozen Windows and own-UID Android hosts.

No service is constructed in this module. Runtime messages use the production
Core pipe/Binder path; inspector calls use the explicit qualification binding.
"""

import base64
import json
import os
from pathlib import Path
import queue
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MAX_FRAME = 4 * 1024 * 1024
HEADER = struct.Struct(">I")
SAFE_ERROR = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class PeerFailure(RuntimeError):
    def __init__(self, code="peer_unavailable"):
        self.code = code if isinstance(code, str) and SAFE_ERROR.fullmatch(code) else "peer_unavailable"
        super().__init__(self.code)


def checked_reply(value, identifier):
    if not isinstance(value, dict) or value.get("id") != identifier or type(value.get("ok")) is not bool:
        raise PeerFailure("invalid_peer_reply")
    if value["ok"] is not True:
        raise PeerFailure(value.get("error", {}).get("code"))
    return value.get("result")


def encode(value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    if not 1 < len(raw) <= MAX_FRAME:
        raise PeerFailure("peer_frame_budget")
    return HEADER.pack(len(raw)) + raw


def receive(read):
    def exact(length):
        chunks = bytearray()
        while len(chunks) < length:
            part = read(length - len(chunks))
            if not part:
                raise PeerFailure("peer_closed")
            chunks.extend(part)
        return bytes(chunks)
    length, = HEADER.unpack(exact(4))
    if not 1 < length <= MAX_FRAME:
        raise PeerFailure("peer_frame_budget")
    try:
        value = json.loads(exact(length))
    except (UnicodeError, ValueError):
        raise PeerFailure("invalid_peer_frame") from None
    if not isinstance(value, dict):
        raise PeerFailure("invalid_peer_frame")
    return value


def child_environment(environment=os.environ):
    # Artifact/job bearers belong to the controller, never the product runtime.
    return {key: value for key, value in environment.items()
            if not key.startswith(("GITHUB_", "ACTIONS_", "INPUT_"))}


class WindowsPeer:
    def __init__(self, binary, directory, key):
        if sys.platform != "win32" or len(key) != 32:
            raise PeerFailure("windows_required")
        self.binary, self.directory, self.key = Path(binary), Path(directory).resolve(), key
        self.process = self.client = None
        self.processes_started, self.clean_exits, self.forced_exits = 0, 0, 0
        self._sequence = 0

    def start(self):
        from mesh_chat.core_api.pipe_client import connect
        from mesh_chat.core_api.client import CoreClient
        if self.process is not None:
            raise PeerFailure("peer_already_started")
        self._responses = queue.Queue(maxsize=32)
        pipe = r"\\.\pipe\mesh-native-qualification-" + uuid4().hex
        environment = {**child_environment(), "MESH_CHAT_CORE_API_PIPE": pipe,
                       "MESH_CHAT_CORE_API_CLIENT_IMAGE": str(Path(sys.executable).resolve())}
        self.process = subprocess.Popen([str(self.binary), "--qualification-native-webrtc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        self.processes_started += 1
        process, responses = self.process, self._responses
        def reader():
            try:
                while True:
                    value = receive(process.stdout.read)
                    if value.get("type") != "event":
                        responses.put(value, timeout=1)
            except Exception:
                try: responses.put_nowait(None)
                except queue.Full: pass
        def drain():
            while process.stderr.read(65536):
                pass  # Raw runtime diagnostics can contain signed setup material.
        self._reader = threading.Thread(target=reader, daemon=True)
        self._stderr = threading.Thread(target=drain, daemon=True)
        self._reader.start()
        self._stderr.start()
        try:
            self.private("initialize", {"profile_dir": str(self.directory),
                "vault_key": base64.b64encode(self.key).decode(), "parent_pid": os.getpid(),
                "display_name": "Mesh qualification"})
            connection = connect(pipe, timeout=15)
            self.client = CoreClient.open(connection.readline, connection.write, connection.close)
            return self.inventory()
        except Exception:
            self.stop(crash=True)
            raise

    def private(self, command, payload=None):
        if self.process is None:
            raise PeerFailure("peer_not_started")
        self._sequence += 1
        identifier = f"qualification:{self._sequence}"
        self.process.stdin.write(encode({"v": 1, "id": identifier, "command": command, "payload": payload or {}}))
        self.process.stdin.flush()
        try:
            reply = self._responses.get(timeout=60)
        except queue.Empty:
            raise PeerFailure("peer_deadline") from None
        return checked_reply(reply, identifier)

    def core(self, operation, params=None, key=None):
        if self.client is None:
            raise PeerFailure("peer_not_started")
        return self.client.request(operation, params or {}, idempotency_key=key)

    def inventory(self):
        return self.private("qualification.inventory")

    def path(self, logical, physical):
        return self.private("qualification.path_evidence", {"logical_session": logical, "expected_physical": physical})

    def stop(self, *, crash=False):
        process = self.process
        if process is None:
            return
        if self.client is not None:
            self.client.close()
            self.client = None
        if crash:
            self._kill_tree(process)
            self.forced_exits += 1
        else:
            try:
                self.private("shutdown")
            except Exception:
                self._kill_tree(process)
                process.wait(timeout=15)
                raise
        code = process.wait(timeout=30)
        self._reader.join(5)
        self._stderr.join(5)
        self.process = None
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        if not crash:
            if code != 0 or self._reader.is_alive() or self._stderr.is_alive():
                raise PeerFailure("unclean_windows_exit")
            self.clean_exits += 1

    @staticmethod
    def _kill_tree(process):
        # One-file PyInstaller has a bootloader parent and runtime child. Kill
        # this exact launched tree so a retained child cannot hold the vault.
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       check=True, capture_output=True, timeout=15)


class AndroidPeer:
    APP = "com.meshchat.runtime.smoke"
    RUNNER = APP + ".test/androidx.test.runner.AndroidJUnitRunner"
    TEST = "com.meshchat.runtime.PackagedNativeInteropBoundaryTest"

    def __init__(self, key, *, adb="adb", directory_id=None):
        if len(key) != 32:
            raise PeerFailure("invalid_vault_key")
        self.key, self.adb = key, adb
        self.directory_id = directory_id or uuid4().hex
        if re.fullmatch(r"[a-f0-9]{32}", self.directory_id) is None:
            raise PeerFailure("invalid_profile_leaf")
        self.process = self.socket = None
        self.forward = None
        self._sequence = 0
        self.processes_started, self.clean_exits, self.forced_exits = 0, 0, 0

    def _adb(self, *args):
        return subprocess.check_output([self.adb, *args], stderr=subprocess.DEVNULL, timeout=30).decode().strip()

    def start(self):
        if self.process is not None:
            raise PeerFailure("peer_already_started")
        nonce = os.urandom(32).hex()
        self.process = subprocess.Popen([self.adb, "shell", "am", "instrument", "-w", "-r",
            "-e", "class", self.TEST, "-e", "mesh_interop_nonce", nonce, self.RUNNER],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.processes_started += 1
        ports = queue.Queue(maxsize=2)
        process = self.process
        def reader():
            while line := process.stdout.readline(8193):
                if len(line) > 8192:
                    continue
                match = re.fullmatch(rb"INSTRUMENTATION_STATUS: mesh_interop_port=([0-9]{1,5})\r?\n", line)
                if match:
                    try: ports.put_nowait(int(match[1]))
                    except queue.Full: pass
        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        try:
            port = ports.get(timeout=90)
            if not 1024 <= port <= 65535:
                raise PeerFailure("invalid_android_port")
            self.forward = self._adb("forward", "tcp:0", f"tcp:{port}")
            if re.fullmatch(r"[0-9]{1,5}", self.forward) is None:
                raise PeerFailure("invalid_adb_forward")
            self.socket = socket.create_connection(("127.0.0.1", int(self.forward)), timeout=60)
            self._request("authenticate", {"nonce": nonce})
            self._request("initialize", {"directory_id": self.directory_id, "vault_key": base64.b64encode(self.key).decode()})
            return self.inventory()
        except Exception:
            self.stop(crash=True)
            raise PeerFailure("android_host_start_failed") from None

    def _request(self, action, payload=None):
        if self.socket is None:
            raise PeerFailure("peer_not_started")
        self._sequence += 1
        identifier = f"qualification:{self._sequence}"
        self.socket.sendall(encode({"id": identifier, "action": action, "payload": payload or {}}))
        return checked_reply(receive(self.socket.recv), identifier)

    def core(self, operation, params=None, key=None):
        return self._request("core", {"operation": operation, "params": params or {}, "idempotency_key": key})

    def inventory(self):
        return self._request("inspect", {"command": "qualification.inventory", "payload": {}})

    def path(self, logical, physical):
        return self._request("inspect", {"command": "qualification.path_evidence", "payload": {
            "logical_session": logical, "expected_physical": physical}})

    def stop(self, *, crash=False, delete_profile=False):
        process = self.process
        if process is None:
            return
        finished = False
        try:
            if crash:
                self._adb("shell", "am", "force-stop", self.APP)
                self.forced_exits += 1
            else:
                self._request("finish", {"delete_profile": delete_profile})
                finished = True
            code = process.wait(timeout=30)
            self._reader.join(5)
            if not crash:
                if code != 0 or self._reader.is_alive():
                    raise PeerFailure("unclean_android_exit")
                self.clean_exits += 1
        finally:
            if self.socket is not None:
                self.socket.close()
                self.socket = None
            if not crash and not finished:
                self._adb("shell", "am", "force-stop", self.APP)
            if self.forward is not None:
                self._adb("forward", "--remove", "tcp:" + self.forward)
                self.forward = None
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            self.process = None
