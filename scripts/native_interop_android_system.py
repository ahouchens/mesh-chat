"""Bounded emulator-console observations, independent of the ADB connection.

Labels describe matched log signatures, not established causes. Host read order
is not guest event order. Missing signatures do not prove absence of a failure.
Raw lines, PIDs, paths, addresses and messages are never retained.
"""
from collections import deque
import threading


LOG_TAGS = "*:s libc:f DEBUG:f AndroidRuntime:e Watchdog:e lmkd:i ActivityManager:i init:i adbd:i"
EVENTS = ("kernel_boot", "kernel_panic", "kernel_oom", "kernel_reboot",
          "native_signal", "java_fatal", "system_watchdog", "lowmemory_kill",
          "adbd_exit", "system_server_exit", "app_died")
CAP = 65535
PHASES = ("boot", "peer_start", "peer_initialize", "peer_runtime", "peer_stop", "cleanup")


def system_snapshot(value):
    """Reject a malformed diagnostic provider before publishing its observation."""
    fields = {"v", "counts", "events", "events_dropped", "oversized_lines", "counters_saturate_at",
              "reader_eof", "reader_failed", "classifier_failed"}
    if type(value) is not dict or set(value) != fields: return None
    if (type(value["v"]) is not int or value["v"] != 1
            or type(value["counters_saturate_at"]) is not int or value["counters_saturate_at"] != CAP): return None
    if any(type(value[key]) is not bool for key in ("reader_eof", "reader_failed", "classifier_failed")): return None
    counts, events = value["counts"], value["events"]
    if type(counts) is not dict or set(counts) != set(EVENTS): return None
    if any(type(n) is not int or not 0 <= n <= CAP for n in
           [*counts.values(), value["events_dropped"], value["oversized_lines"]]): return None
    if type(events) is not list or len(events) > 32: return None
    for event in events:
        if (type(event) is not dict or set(event) != {"event", "phase"}
                or type(event["event"]) is not str or event["event"] not in EVENTS
                or type(event["phase"]) is not str or event["phase"] not in PHASES): return None
    return {**value, "counts": dict(counts), "events": [dict(event) for event in events]}


def classify(line):
    if b"Linux version " in line: return "kernel_boot"
    if b"Kernel panic - not syncing:" in line: return "kernel_panic"
    if b"Out of memory: Killed process " in line: return "kernel_oom"
    if b"reboot: Restarting system" in line: return "kernel_reboot"
    if b"libc" in line and b"Fatal signal " in line: return "native_signal"
    if b"AndroidRuntime" in line and b"FATAL EXCEPTION:" in line: return "java_fatal"
    if b"Watchdog" in line and b"KILLING SYSTEM PROCESS" in line: return "system_watchdog"
    if b"lmkd" in line and b"Kill '" in line: return "lowmemory_kill"
    if b"init" in line and b"Service 'adbd'" in line and (b"exited" in line or b"killed" in line):
        return "adbd_exit"
    if b"system_server" in line and b"has died" in line: return "system_server_exit"
    if b"ActivityManager" in line and b"Process com.meshchat.runtime.smoke " in line and b"has died" in line:
        return "app_died"
    return None


class AndroidSystemObservation:
    def __init__(self):
        self._lock = threading.Lock()
        self._phase = "boot"
        self._events = deque(maxlen=32)
        self._counts = dict.fromkeys(EVENTS, 0)
        self._dropped = self._oversized = 0
        self._eof = self._reader_failed = self._classifier_failed = False
        self._thread = None

    def phase(self, value):
        if type(value) is str and value in PHASES:
            with self._lock: self._phase = value

    def start(self, stream):
        self._thread = threading.Thread(target=self.consume, args=(stream,), daemon=True)
        self._thread.start()

    def consume(self, stream):
        discarding = False
        try:
            while line := stream.readline(8193):
                oversized = len(line) > 8192
                if oversized or discarding:
                    if not discarding:
                        with self._lock: self._oversized = min(CAP, self._oversized + 1)
                    discarding = not line.endswith(b"\n")
                    continue
                try:
                    event = classify(line)
                    if event is not None:
                        with self._lock:
                            self._counts[event] = min(CAP, self._counts[event] + 1)
                            if len(self._events) == self._events.maxlen:
                                self._dropped = min(CAP, self._dropped + 1)
                            self._events.append({"event": event, "phase": self._phase})
                except Exception:
                    with self._lock: self._classifier_failed = True
            with self._lock: self._eof = True
        except Exception:
            with self._lock: self._reader_failed = True

    def finish(self, stream):
        # Called only after the exact emulator process has exited. Never close
        # a buffered stream while a live reader owns its lock.
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join(2)
            if self._thread.is_alive(): return False
        stream.close()
        return True

    def snapshot(self):
        with self._lock:
            return {"v": 1, "counts": dict(self._counts),
                    "events": [dict(item) for item in self._events],
                    "events_dropped": self._dropped, "oversized_lines": self._oversized,
                    "counters_saturate_at": CAP, "reader_eof": self._eof,
                    "reader_failed": self._reader_failed, "classifier_failed": self._classifier_failed}
