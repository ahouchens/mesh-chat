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
        error = value.get("error")
        raise PeerFailure(error.get("code") if isinstance(error, dict) else None)
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
    EXCHANGE_TIMEOUT = 60

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
        process, responses = self.process, self._responses
        def exchange():
            process.stdin.write(encode({"v": 1, "id": identifier, "command": command, "payload": payload or {}}))
            process.stdin.flush()
            try:
                reply = responses.get(timeout=self.EXCHANGE_TIMEOUT)
            except queue.Empty:
                raise PeerFailure("peer_deadline") from None
            return checked_reply(reply, identifier)
        return self._bounded(exchange)

    def _bounded(self, action):
        """The whole OS write/read exchange has one deadline, including flush."""
        result = queue.Queue(maxsize=1)
        def execute():
            try: result.put((True, action()))
            except Exception as error: result.put((False, error))
        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        try:
            success, value = result.get(timeout=self.EXCHANGE_TIMEOUT)
        except queue.Empty:
            process = self.process
            try:
                if process is not None and process.poll() is None:
                    self._kill_tree(process)
                    process.wait(timeout=15)
                if self.client is not None:
                    self.client.close()
            except Exception:
                pass
            worker.join(5)
            raise PeerFailure("peer_deadline") from None
        worker.join(5)
        if not success:
            raise value
        return value

    def core(self, operation, params=None, key=None):
        if self.client is None:
            raise PeerFailure("peer_not_started")
        client = self.client
        return self._bounded(lambda: client.request(operation, params or {}, idempotency_key=key))

    def inventory(self):
        return self.private("qualification.inventory")

    def path(self, logical, physical):
        return self.private("qualification.path_evidence", {"logical_session": logical, "expected_physical": physical})

    def stop(self, *, crash=False):
        process = self.process
        if process is None:
            return
        failure, code = None, None
        try:
            if self.client is not None:
                self.client.close()
                self.client = None
            if crash:
                self._kill_tree(process)
                self.forced_exits += 1
            else:
                self.private("shutdown")
            code = process.wait(timeout=30)
        except Exception as error:
            failure = error if isinstance(error, PeerFailure) else PeerFailure("windows_shutdown_failed")
        finally:
            try:
                if process.poll() is None:
                    self._kill_tree(process)
                    process.wait(timeout=15)
            except Exception:
                if failure is None: failure = PeerFailure("windows_retirement_failed")
            self.process = None
            self.client = None
            for thread in (self._reader, self._stderr):
                thread.join(5)
                if thread.is_alive() and failure is None:
                    failure = PeerFailure("windows_reader_not_retired")
            for stream in (process.stdin, process.stdout, process.stderr):
                try: stream.close()
                except Exception:
                    if failure is None: failure = PeerFailure("windows_stream_not_closed")
        if failure is not None:
            raise failure
        if not crash:
            if code != 0:
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
        deadline = time.monotonic() + 60
        self.socket.settimeout(60)
        self.socket.sendall(encode({"id": identifier, "action": action, "payload": payload or {}}))
        def read(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PeerFailure("peer_deadline")
            self.socket.settimeout(remaining)
            return self.socket.recv(count)
        try:
            return checked_reply(receive(read), identifier)
        except TimeoutError:
            raise PeerFailure("peer_deadline") from None

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
                result = self._request("finish", {"delete_profile": delete_profile})
                if (not isinstance(result, dict) or result.get("closed") is not True
                        or result.get("resources_retired") is not True or result.get("store_retired") is not True):
                    raise PeerFailure("android_retirement_unverified")
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
