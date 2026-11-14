"""Ordinary public SDK host plus a separate real Edge media answerer for R5."""

import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from windows_public_consumer_session import (
    MAX_FRAME, PUBLIC_OPERATIONS, PublicCoreError, WindowsPublicConsumerSession, frame, remaining,
    reply, unique_object,
)


CALL_OPERATIONS = frozenset({"call.ice_servers", "call.media_query", "call.control"})
BROWSER = Path(__file__).resolve().parents[1] / "examples/typescript-independent-consumer/browser-media.mjs"
MAX_BROWSER_FRAME = 256 * 1024


class CallPeerSession(WindowsPublicConsumerSession):
    """The R5 app admits only the three extra public operations it needs."""

    def request(self, operation, params=None, key=None):
        if (self.process is None or self.retired or self.faulted or type(operation) is not str
                or operation not in PUBLIC_OPERATIONS | CALL_OPERATIONS
                or type(params) not in {dict, type(None)}
                or (operation == "call.control" and (type(params) is not dict
                    or params.get("action") not in {"answer", "end"}))
                or (key is not None and (type(key) is not str
                    or re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", key) is None))):
            raise ValueError("public_call_request")
        if not self.request_lock.acquire(blocking=False):
            raise ValueError("concurrent_public_call_request")
        try:
            self.sequence += 1
            request_id = f"win:{self.sequence}"
            command = {"id": request_id, "operation": operation,
                       "params": params if params is not None else {}}
            if key is not None:
                command["idempotency_key"] = key
            self._write(frame(command))
            try: line = self.responses.get(timeout=remaining(self.deadline, 30))
            except queue.Empty: raise TimeoutError("public_call_reply_deadline") from None
            if (line is None or self.output_failure.is_set() or len(line) > MAX_FRAME
                    or not line.endswith(b"\n")):
                raise ValueError("public_call_output")
            return reply(json.loads(line.decode("utf-8"), object_pairs_hook=unique_object), request_id)
        except PublicCoreError:
            raise
        except Exception:
            self.faulted = True
            raise
        finally:
            self.request_lock.release()


class BrowserProcess:
    """A private pipe to an owned browser process; no SDP enters retained logs."""

    def __init__(self, node: Path, edge: Path):
        self.node, self.edge = Path(node), Path(edge)
        self.process = None
        self.responses = queue.Queue(maxsize=2)
        self.reader = None
        self.sequence = 0
        self.deadline = None
        self.retired = False

    def _read(self):
        try:
            while line := self.process.stdout.readline(MAX_BROWSER_FRAME + 1):
                if len(line) > MAX_BROWSER_FRAME or not line.endswith(b"\n"):
                    self.responses.put_nowait(None)
                    return
                self.responses.put(line, timeout=1)
        except Exception:
            try: self.responses.put_nowait(None)
            except queue.Full: pass

    def open(self, deadline):
        if self.process is not None or not self.edge.is_file() or self.edge.name.lower() != "msedge.exe":
            raise ValueError("browser_admission")
        self.deadline = deadline
        self.process = subprocess.Popen([str(self.node), str(BROWSER), str(self.edge)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=BROWSER.parent, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            try: line = self.responses.get(timeout=remaining(deadline, 45))
            except queue.Empty: raise TimeoutError("browser_ready_deadline") from None
            if line != b'{"ready":true}\n':
                raise ValueError("browser_not_ready")
        except Exception:
            if self.process.poll() is None: self.process.kill()
            self.process.wait(timeout=5)
            self.reader.join(timeout=2)
            raise
        return self

    def request(self, action, **params):
        if self.process is None or self.retired or action not in {"answer", "observe", "close"}:
            raise ValueError("browser_request")
        self.sequence += 1
        request_id = self.sequence
        payload = {"id": request_id, "action": action, **params}
        data = frame(payload)
        if len(data) > MAX_BROWSER_FRAME:
            raise ValueError("browser_frame_limit")
        self.process.stdin.write(data)
        self.process.stdin.flush()
        try: line = self.responses.get(timeout=remaining(self.deadline, 30))
        except queue.Empty: raise TimeoutError("browser_reply_deadline") from None
        if line is None:
            raise ValueError("browser_output")
        response = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object)
        if (type(response) is not dict or response.get("id") != request_id
                or response.get("ok") is not True or type(response.get("value")) is not dict):
            raise ValueError("browser_reply")
        if action == "close":
            self.retired = (response["value"].get("browserRetired") is True
                            and response["value"].get("devtoolsClosed") is True
                            and response["value"].get("profileRemoved") is True)
        return response["value"]

    def close(self):
        if self.process is None:
            return True
        if not self.retired and self.process.poll() is None:
            try: self.request("close")
            except Exception: pass
        self.process.stdin.close()
        try: code = self.process.wait(timeout=min(10, remaining(self.deadline)))
        except (subprocess.TimeoutExpired, TimeoutError):
            self.process.kill()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: return False
            return False
        self.reader.join(timeout=2)
        return self.retired and code == 0 and not self.reader.is_alive()
