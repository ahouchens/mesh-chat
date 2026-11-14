"""Ordinary public SDK host plus a separate real Edge media answerer for R5."""

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time

from packaged_call_io import BoundedWriter
from packaged_call_windows_job import WindowsJob
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

    def __init__(self, node: Path, edge: Path, temporary_root: Path):
        self.node, self.edge = Path(node), Path(edge)
        self.temporary_root = Path(temporary_root).resolve(strict=True)
        self.process = None
        self.responses = queue.Queue(maxsize=2)
        self.reader = self.writer = self.job = self.directory = None
        self.sequence = 0
        self.deadline = None
        self.retired = False
        self.faulted = False
        self.cleanup = {}
        self.closed = False
        self.close_result = False
        self.profile_removed = False

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
        try:
            if not self.temporary_root.is_dir() or self.temporary_root.is_symlink():
                raise ValueError("browser_temp_root_invalid")
            self.directory = Path(tempfile.mkdtemp(prefix="mesh-call-edge-", dir=self.temporary_root)).resolve(strict=True)
            self.job = WindowsJob()
            # The Node protocol waits for an exact start frame. Edge cannot be
            # spawned until this process is assigned to the kill-on-close job.
            self.process = subprocess.Popen([str(self.node), str(BROWSER), str(self.edge), str(self.directory)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=BROWSER.parent, shell=False, bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.writer = BoundedWriter(self.process.stdin, self._terminate_job)
            self.job.assign(self.process)
            self.writer.write(b'{"start":true}\n', min(deadline, time.monotonic() + 5))
            try: line = self.responses.get(timeout=remaining(deadline, 45))
            except queue.Empty: raise TimeoutError("browser_ready_deadline") from None
            if line != b'{"ready":true}\n':
                raise ValueError("browser_not_ready")
        except Exception:
            self.faulted = True
            self._terminate_job()
            raise
        return self

    def _terminate_job(self):
        try:
            job_zero = self.job is None or not self.job.assigned or self.job.terminate()
            if self.process is not None:
                if self.process.poll() is None: self.process.kill()
                self.process.wait(timeout=5)
            if self.reader is not None: self.reader.join(timeout=2)
            return (job_zero and (self.process is None or self.process.poll() is not None)
                    and (self.reader is None or not self.reader.is_alive()))
        except Exception:
            return False

    def request(self, action, **params):
        if self.process is None or self.retired or self.faulted or action not in {"answer", "observe", "close"}:
            raise ValueError("browser_request")
        self.sequence += 1
        request_id = self.sequence
        payload = {"id": request_id, "action": action, **params}
        data = frame(payload)
        if len(data) > MAX_BROWSER_FRAME:
            raise ValueError("browser_frame_limit")
        deadline = min(self.deadline, time.monotonic() + 30)
        self.writer.write(data, deadline)
        try: line = self.responses.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            self.faulted = True
            self._terminate_job()
            raise TimeoutError("browser_reply_deadline") from None
        if line is None:
            self.faulted = True
            raise ValueError("browser_output")
        response = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object)
        if (type(response) is not dict or response.get("id") != request_id
                or response.get("ok") is not True or type(response.get("value")) is not dict):
            raise ValueError("browser_reply")
        if action == "close":
            self.retired = (response["value"].get("stopped") is True
                            and response["value"].get("browserRetired") is True
                            and response["value"].get("devtoolsClosed") is True)
        return response["value"]

    def close(self):
        if self.closed: return self.close_result
        if self.process is not None and not self.retired and self.process.poll() is None and not self.faulted:
            try: self.request("close")
            except Exception: self.faulted = True
        if self.faulted: self._terminate_job()
        closed = threading.Event()
        close_errors = []
        if self.process is not None:
            def close_input():
                try: self.process.stdin.close()
                except Exception as error: close_errors.append(error)
                finally: closed.set()
            closer = threading.Thread(target=close_input, daemon=True)
            closer.start()
            if not closed.wait(5): self._terminate_job()
            closer.join(timeout=2)
            try: code = self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._terminate_job()
                code = self.process.poll()
        else:
            code = None
            closed.set()
            closer = None
        if self.reader is not None: self.reader.join(timeout=2)
        try: job_zero, forced = self.job.close() if self.job is not None else (self.process is None, False)
        except Exception: job_zero, forced = False, True
        if job_zero and self.directory is not None and not self.profile_removed:
            try:
                target = self.directory.resolve(strict=True)
                if (target.parent != self.temporary_root or not target.name.startswith("mesh-call-edge-")
                        or self.directory.is_symlink()):
                    raise ValueError("browser_profile_ownership")
                shutil.rmtree(target)
                self.profile_removed = not os.path.lexists(target)
            except Exception:
                self.profile_removed = False
        self.cleanup = {"writer_retired": self.writer is None or self.writer.retired,
                        "reader_retired": self.reader is None or not self.reader.is_alive(),
                        "stdin_closed": closed.is_set() and not close_errors and
                            (closer is None or not closer.is_alive()),
                        "node_retired": self.process is None or self.process.poll() is not None,
                        "job_zero_and_released": job_zero, "edge_profile_removed": self.profile_removed}
        self.closed = all(self.cleanup.values())
        self.close_result = self.retired and code == 0 and not forced and all(self.cleanup.values())
        return self.close_result
