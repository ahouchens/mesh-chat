"""Frozen-process lifecycle probe; the private adapter has no carrier resources.

Exercises production initialization, encrypted persistence, private epoch changes
and process exit. It does not qualify WebRTC, RNS routing or message receipts.
"""
import base64
import os
from pathlib import Path
from queue import Queue
import subprocess
from threading import Event, Thread
from uuid import uuid4

from mesh_chat.ipc import FrameWriter, read_frame


class Runtime:
    def __init__(self, binary, *, shared=False):
        self.process = subprocess.Popen([str(binary), *(["--shared-webview"] if shared else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.writer = FrameWriter(self.process.stdin)
        self.responses = Queue(maxsize=16)
        self.inventory_seen = Event()
        self.epoch = None
        self.error = None
        self.stderr_bytes = 0
        self.fatal = False
        self._reader = Thread(target=self._read, daemon=True)
        self._stderr = Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr.start()

    def _read(self):
        try:
            while True:
                frame = read_frame(self.process.stdout)
                if frame.get("type") == "desktop_transport":
                    self._transport(frame)
                elif frame.get("type") == "response":
                    self.responses.put_nowait(frame)
                elif frame.get("type") == "direct_native" and frame.get("request") == {"op": "reset"}:
                    pass  # No native Direct resource exists in this lifecycle fixture.
                elif frame.get("type") != "event":
                    raise ValueError("Unexpected packaged output")
        except EOFError:
            pass
        except Exception as error:
            self.error = type(error).__name__

    def _transport(self, frame):
        epoch = frame.get("epoch")
        if self.epoch not in (None, epoch):
            raise ValueError("Private service epoch changed in one process")
        self.epoch = epoch
        operation = frame["request"]["op"]
        if operation not in {"inventory", "reset"}:
            raise ValueError("Empty lifecycle probe cannot allocate carriers")
        result = {"v": 1, "adapter_epoch": "a" * 32, "resources": []} if operation == "inventory" else None
        self.writer.write({"v": 1, "type": "desktop_transport_reply", "epoch": epoch,
                           "id": frame["id"], "ok": True, "result": result})
        if operation == "inventory":
            self.inventory_seen.set()

    def _read_stderr(self):
        tail = b""
        while chunk := self.process.stderr.read(4096):
            self.stderr_bytes += len(chunk)
            self.fatal |= b"Fatal Python error" in tail + chunk
            tail = chunk[-32:]

    def call(self, command, payload=None):
        request_id = uuid4().hex
        self.writer.write({"v": 1, "id": request_id, "command": command, "payload": payload or {}})
        response = self.responses.get(timeout=30)
        if self.error or response.get("id") != request_id or response.get("ok") is not True:
            raise RuntimeError("Packaged command failed: " + command)
        return response["result"]

    def initialize(self, profile, key):
        result = self.call("initialize", {"profile_dir": str(profile), "vault_key": base64.b64encode(key).decode(),
            "display_name": "Lifecycle qualification", "parent_pid": os.getpid()})
        identity = result["profile"]["destination_hash"]
        if not isinstance(identity, str) or len(identity) != 32:
            raise RuntimeError("Packaged identity is unavailable")
        return identity

    def shutdown(self):
        self.call("shutdown")
        # Keep the parent's stdin writer open: shutdown must stop its own reader.
        if self.process.wait(timeout=10) != 0:
            raise RuntimeError("Packaged shutdown was not clean")
        self._reader.join(timeout=2)
        self._stderr.join(timeout=2)
        if self.error or self.fatal or self.stderr_bytes > 65536:
            raise RuntimeError("Packaged lifecycle diagnostics failed")

    def crash(self):
        if os.name == "nt":
            taskkill = Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"
            subprocess.run([str(taskkill), "/PID", str(self.process.pid), "/T", "/F"],
                check=True, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.process.kill()
        if self.process.wait(timeout=10) == 0:
            raise RuntimeError("Crash probe did not terminate the process")

    def close(self):
        if self.process.poll() is None:
            self.crash()
        self._reader.join(timeout=2)
        self._stderr.join(timeout=2)
        if self._reader.is_alive() or self._stderr.is_alive():
            raise RuntimeError("Packaged probe readers did not stop")
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr): stream.close()


def exercise(binary, directory):
    epochs = []
    for shared in (False, True):
        runtime = Runtime(binary, shared=shared)
        try:
            runtime.initialize(directory / ("shared" if shared else "default"), os.urandom(32))
            if shared:
                if not runtime.inventory_seen.wait(5): raise RuntimeError("Private inventory was not executed")
                epochs.append(runtime.epoch)
            runtime.shutdown()
        finally:
            runtime.close()
    key = os.urandom(32)
    runtime = Runtime(binary, shared=True)
    try:
        identity = runtime.initialize(directory / "restart", key)
        if not runtime.inventory_seen.wait(5): raise RuntimeError("Private inventory was not executed")
        epochs.append(runtime.epoch)
        saved = runtime.call("set_hide_notification_previews", {"hidden": True, "operation_id": str(uuid4())})
        if saved["hide_previews"] is not True: raise RuntimeError("Preference was not committed")
        runtime.crash()
    finally:
        runtime.close()
    runtime = Runtime(binary, shared=True)
    try:
        if runtime.initialize(directory / "restart", key) != identity:
            raise RuntimeError("Identity changed across process death")
        if not runtime.inventory_seen.wait(5): raise RuntimeError("Restart inventory was not executed")
        epochs.append(runtime.epoch)
        if runtime.call("get_notification_state")["hide_previews"] is not True:
            raise RuntimeError("Committed preference was lost")
        runtime.shutdown()
    finally:
        runtime.close()
    if len(set(epochs)) != 3:
        raise RuntimeError("Replacement processes reused private service epochs")
    return {"processes_started": 4, "clean_shutdowns": 3, "forced_exits": 1, "private_epochs": 3}
