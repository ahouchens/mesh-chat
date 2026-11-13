"""Identifier-free observations of the existing Android controller boundary."""

import re
import threading


BYTE_CAP = 65536
READ_CAP = 64
ACTIONS = frozenset({"authenticate", "initialize", "core", "inspect", "finish", "other"})
CORE_OPERATIONS = frozenset({"application.snapshot", "message.query", "message.enqueue",
                             "runtime.capabilities", "other"})
STAGES = frozenset({"header", "body"})
MARKERS = frozenset({"process_crash", "error", "instrumentation_failed"})
PROCESS_STATES = frozenset({"absent", "running", "exited", "unknown"})
INSTRUMENTATION_CODES = frozenset({"-1", "0", "1"})


def process_observation(process):
    """Observe only the already-owned process handle; never wait or read output."""
    if process is None:
        return {"state": "absent", "exit_status": None}
    try:
        code = process.poll()
    except Exception:
        return {"state": "unknown", "exit_status": None}
    if code is None:
        return {"state": "running", "exit_status": None}
    if type(code) is int and -255 <= code <= 255:
        return {"state": "exited", "exit_status": code}
    return {"state": "unknown", "exit_status": None}


class InstrumentationStatus:
    """Reduce already-consumed stdout lines to fixed labels, never raw text."""

    def __init__(self):
        self._lock = threading.Lock()
        self._eof = False
        self._code = None
        self._marker = None

    def observe(self, line):
        if type(line) is not bytes or len(line) > 8192:
            return
        with self._lock:
            match = re.fullmatch(rb"INSTRUMENTATION_CODE: (-1|0|1)\r?\n", line)
            if match is not None:
                self._code = match[1].decode("ascii")
            if re.fullmatch(rb"INSTRUMENTATION_RESULT: shortMsg=Process crashed\.\r?\n", line):
                self._marker = "process_crash"
            elif line.startswith(b"INSTRUMENTATION_FAILED:"):
                if self._marker != "process_crash":
                    self._marker = "instrumentation_failed"
            elif (line.startswith(b"INSTRUMENTATION_RESULT: shortMsg=")
                  or line.startswith(b"INSTRUMENTATION_STATUS: Error=")):
                if self._marker != "process_crash":
                    self._marker = "error"

    def ended(self):
        with self._lock:
            self._eof = True

    def snapshot(self):
        with self._lock:
            return {"reader_eof": self._eof, "code": self._code, "marker": self._marker}


def android_transport_snapshot(value):
    """Validate the exact bounded DTO before it can enter a retained report."""
    fields = {"v", "action", "operation", "eof_stage", "received_bytes",
              "received_bytes_capped", "read_calls", "read_calls_capped",
              "process", "instrumentation"}
    if type(value) is not dict or set(value) != fields or type(value["v"]) is not int or value["v"] != 1:
        return None
    action, operation = value["action"], value["operation"]
    if (type(action) is not str or action not in ACTIONS
            or (operation is not None and (type(operation) is not str or operation not in CORE_OPERATIONS))
            or (action == "core") != (operation is not None)
            or type(value["eof_stage"]) is not str or value["eof_stage"] not in STAGES):
        return None
    byte_count, read_count = value["received_bytes"], value["read_calls"]
    if (type(byte_count) is not int or not 0 <= byte_count <= BYTE_CAP
            or type(read_count) is not int or not 1 <= read_count <= READ_CAP
            or type(value["received_bytes_capped"]) is not bool
            or type(value["read_calls_capped"]) is not bool
            or (value["received_bytes_capped"] and byte_count != BYTE_CAP)
            or (value["read_calls_capped"] and read_count != READ_CAP)
            or (value["eof_stage"] == "body" and byte_count < 4)):
        return None
    process, status = value["process"], value["instrumentation"]
    if (type(process) is not dict or set(process) != {"state", "exit_status"}
            or type(process["state"]) is not str or process["state"] not in PROCESS_STATES
            or (process["state"] == "exited") != (type(process["exit_status"]) is int)
            or (type(process["exit_status"]) is int and not -255 <= process["exit_status"] <= 255)
            or type(status) is not dict or set(status) != {"reader_eof", "code", "marker"}
            or type(status["reader_eof"]) is not bool
            or (status["code"] is not None and (type(status["code"]) is not str
                                                or status["code"] not in INSTRUMENTATION_CODES))
            or (status["marker"] is not None and (type(status["marker"]) is not str
                                                  or status["marker"] not in MARKERS))):
        return None
    return {**value, "process": dict(process), "instrumentation": dict(status)}
