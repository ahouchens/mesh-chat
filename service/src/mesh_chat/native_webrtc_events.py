"""Bounded JNI callback ingress with lifecycle capacity separate from packets."""

from collections import OrderedDict, deque
from queue import Empty
from threading import Condition
from time import monotonic


class NativeEventInbox:
    LIFECYCLE = frozenset({"open", "closed", "ice", "channel", "signaling", "gathering"})

    def __init__(self, *, control_count=512, control_bytes=65536,
                 data_count=256, data_bytes=2 * 1024 * 1024):
        if min(control_count, control_bytes, data_count, data_bytes) <= 0:
            raise ValueError("Native event budgets must be positive")
        self._limits = control_count, control_bytes, data_count, data_bytes
        self._condition = Condition()
        self._control = OrderedDict()
        self._data = deque()
        self._control_bytes = self._data_bytes = 0
        self._failed = self._overflow = self._shutdown = False
        self._packet_drops = 0

    def put_nowait(self, item):
        with self._condition:
            if item is None:
                self._shutdown = True
                self._condition.notify_all()
                return
            if self._shutdown or self._failed:
                return
            event, session, data = item
            if (not isinstance(session, str) or not 1 <= len(session) <= 128
                    or not isinstance(data, str)):
                self._fail_closed()
                return
            size = len(session.encode("utf-8")) + len(data.encode("utf-8")) + 32
            control_count, control_bytes, data_count, data_bytes = self._limits
            if event in self.LIFECYCLE:
                if item in self._control:
                    return
                if (len(data) > 160 or len(self._control) >= control_count
                        or self._control_bytes + size > control_bytes):
                    self._fail_closed()
                    return
                self._control[item] = size
                self._control_bytes += size
            elif event in {"message", "control"}:
                if (len(data) > (1500 if event == "message" else 90000)
                        or len(self._data) >= data_count or self._data_bytes + size > data_bytes):
                    if event == "message":
                        self._packet_drops += 1
                    else:
                        self._fail_closed()
                    return
                self._data.append((item, size))
                self._data_bytes += size
            else:
                self._fail_closed()
                return
            self._condition.notify()

    def _fail_closed(self):
        self._failed = self._overflow = True
        self._control.clear()
        self._data.clear()
        self._control_bytes = self._data_bytes = 0
        self._condition.notify_all()

    def get(self, timeout=None):
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while True:
                if self._shutdown:
                    return None
                if self._overflow:
                    self._overflow = False
                    return "overflow", "", ""
                if self._control:
                    item, size = self._control.popitem(last=False)
                    self._control_bytes -= size
                    return item
                if self._data:
                    item, size = self._data.popleft()
                    self._data_bytes -= size
                    return item
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise Empty
                self._condition.wait(remaining)

    def get_nowait(self):
        return self.get(timeout=0)

    def statistics(self):
        with self._condition:
            return {"lifecycle_count": len(self._control), "data_count": len(self._data),
                    "lifecycle_bytes": self._control_bytes, "data_bytes": self._data_bytes,
                    "packet_drops": self._packet_drops, "failed": self._failed}
