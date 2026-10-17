"""Private native request correlation, independent of service dispatch locks.

Never register this boundary in service.dispatch or a renderer command table.
Desktop uses inherited frames; mobile drains a separate native-only queue.
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from collections import deque
from concurrent.futures import Future, TimeoutError

from .errors import ValidationError

MAX_BYTES = 64 * 1024
OPERATIONS = frozenset({"prepare", "inspect", "arm", "rearm", "activate", "send", "poll", "close", "reset"})


class NativeChannel:
    def __init__(self, send=None):
        self._lock = threading.Lock()
        self._pending = {}
        self._queue = deque()
        self._send = send
        self._closed = False
        self._send_gate = threading.Lock()
        self._reset_in_flight = False

    def request(self, operation, *, timeout=5, **payload):
        if operation not in OPERATIONS or not 0 < timeout <= 10:
            raise ValidationError("Direct native request is invalid")
        request = {"v": 1, "type": "direct_native", "id": str(uuid.uuid4()),
                   "request": {**payload, "op": operation}}
        if len(json.dumps(request).encode("utf-8")) > MAX_BYTES:
            raise ValidationError("Direct native request exceeds its budget")
        future = Future()
        with self._lock:
            if self._closed:
                raise ValidationError("Direct native channel is closed")
            if self._reset_in_flight:
                raise ValidationError("Direct native channel is retiring")
            if len(self._pending) >= 8:
                raise ValidationError("Direct native request budget exhausted")
            self._pending[request["id"]] = future
            if self._send is None:
                self._queue.append(request)
        try:
            if self._send is not None:
                try:
                    with self._send_gate:
                        with self._lock:
                            if request["id"] not in self._pending:
                                raise ValidationError("Direct native work was retired")
                        self._send(request)
                except ValidationError:
                    raise
                except Exception:
                    self.close()
                    raise
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            # An unknown outcome cannot safely preserve any native ownership.
            self.close()
            raise ValidationError("Direct native request timed out") from exc
        finally:
            with self._lock:
                self._pending.pop(request["id"], None)

    def receive(self, response):
        if (not isinstance(response, dict)
                or set(response) != {"type", "id", "ok", "result"}
                or response["type"] != "direct_native_reply"
                or not isinstance(response["id"], str)
                or type(response["ok"]) is not bool
                or len(json.dumps(response).encode("utf-8")) > MAX_BYTES):
            self.close()
            raise ValidationError("Direct native response is invalid")
        with self._lock:
            future = self._pending.pop(response["id"], None)
            if future is None:
                return False
            if response["ok"]:
                future.set_result(response["result"])
            else:
                future.set_exception(ValidationError("Direct native operation failed"))
        return True

    def drain(self, limit=8):
        with self._lock:
            result = [self._queue.popleft() for _ in range(min(limit, len(self._queue)))]
            return result

    def close(self):
        self.retire(close=True)

    def retire(self, *, close=False):
        with self._lock:
            if self._closed:
                return
            self._closed = close
            pending, self._pending = self._pending, {}
            self._queue.clear()
            reset = {"v": 1, "type": "direct_native", "id": str(uuid.uuid4()),
                     "request": {"op": "reset"}}
            if self._send is None:
                self._queue.append(reset)
            start_reset = self._send is not None and not self._reset_in_flight
            self._reset_in_flight = self._reset_in_flight or start_reset
            for future in pending.values():
                future.set_exception(ValidationError("Direct native channel is closed" if close else "Direct native work was retired"))
        if start_reset:
            def send_reset():
                try:
                    with self._send_gate:
                        self._send(reset)
                except Exception:
                    self.close()
                finally:
                    with self._lock:
                        self._reset_in_flight = False
            threading.Thread(target=send_reset, daemon=True, name="mesh-chat-native-retire").start()


class NativeFrameReader:
    """Read inherited frames while a dispatch worker waits for native results."""
    def __init__(self, stream, channel):
        self._requests = queue.Queue(maxsize=8)
        self._error = None
        self._stopped = threading.Event()
        self._channel = channel
        self._thread = threading.Thread(target=self._run, args=(stream,), daemon=True,
                                        name="mesh-chat-private-reader")
        self._thread.start()

    def _run(self, stream):
        from .ipc import read_frame
        try:
            while not self._stopped.is_set():
                value = read_frame(stream)
                if value.get("type") == "direct_native_reply":
                    self._channel.receive(value)
                else:
                    # Never block the sole reader behind renderer work: overflow
                    # closes the channel and wakes a dispatch waiting on native.
                    self._requests.put_nowait(value)
        except Exception as exc:
            self._error = exc
            self._channel.close()

    def read(self):
        while True:
            if self._error is not None and (not isinstance(self._error, EOFError) or self._requests.empty()):
                raise self._error
            try:
                return self._requests.get(timeout=0.1)
            except queue.Empty:
                continue

    def close(self):
        self._stopped.set()
        self._channel.close()
