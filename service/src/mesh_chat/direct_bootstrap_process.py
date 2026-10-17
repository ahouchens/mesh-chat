"""Bounded inherited-pipe supervisor for the desktop bootstrap interpreter."""
from __future__ import annotations

from concurrent.futures import Future
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

from .direct_bootstrap_worker import MAX_BYTES
from .errors import ValidationError
from .ipc import encode_frame, read_frame


class BootstrapProcess:
    def __init__(self):
        command = ([sys.executable] if getattr(sys, "frozen", False)
                   else [sys.executable, "-m", "mesh_chat"])
        environment = os.environ.copy()
        self._temporary = tempfile.TemporaryDirectory(prefix="mesh-bootstrap-parent-")
        environment["MESH_CHAT_BOOTSTRAP_DIRECTORY"] = self._temporary.name
        if not getattr(sys, "frozen", False):
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        try:
            self._process = subprocess.Popen([*command, "--direct-bootstrap"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except BaseException:
            self._temporary.cleanup()
            raise
        self._requests = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._closed = False
        self._pending = None
        self._thread = threading.Thread(target=self._run, name="mesh-bootstrap-private", daemon=True)
        self._thread.start()

    def request(self, operation, **payload):
        request = {"operation":operation, "payload":payload}
        frame = encode_frame(request, max_bytes=MAX_BYTES)
        future = Future()
        with self._lock:
            if self._closed or self._pending is not None:
                raise ValidationError("Bootstrap process is unavailable or busy")
            self._pending = future
            self._requests.put_nowait((frame, future))
        try:
            response = future.result(timeout=5)
            if not isinstance(response, dict) or response.get("ok") is not True or set(response) != {"ok", "result"}:
                raise ValidationError("Bootstrap process failed")
            return response["result"]
        except Exception as exc:
            self.close()
            raise ValidationError("Bootstrap process failed") from exc
        finally:
            with self._lock:
                if self._pending is future:
                    self._pending = None

    def _run(self):
        try:
            while True:
                item = self._requests.get()
                if item is None:
                    break
                frame, future = item
                self._process.stdin.write(frame)
                self._process.stdin.flush()
                response = read_frame(self._process.stdout, max_bytes=MAX_BYTES)
                with self._lock:
                    if not future.done():
                        future.set_result(response)
                    if self._closed:
                        break
        except Exception:
            self.close()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._pending is not None and not self._pending.done():
                self._pending.set_exception(ValidationError("Bootstrap process closed"))
            try:
                self._requests.put_nowait(None)
            except queue.Full:
                pass
        if self._process.poll() is None:
            self._process.kill()
        def reap():
            self._process.wait()
            for stream in (self._process.stdin, self._process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass
            self._temporary.cleanup()
        threading.Thread(target=reap, name="mesh-bootstrap-reaper", daemon=True).start()
