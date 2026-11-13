"""Identifier-free observations of the existing Android controller boundary."""

import re
import subprocess


BYTE_CAP = 65536
READ_CAP = 64
ACTIONS = frozenset({"authenticate", "initialize", "core", "inspect", "finish", "other"})
CORE_OPERATIONS = frozenset({"application.snapshot", "message.query", "message.enqueue",
                             "runtime.capabilities", "other"})
STAGES = frozenset({"header", "body"})
MARKERS = frozenset({"process_crash", "error", "instrumentation_failed"})
PROCESS_STATES = frozenset({"absent", "running", "exited", "unknown"})
INSTRUMENTATION_CODES = frozenset({"-1", "0", "1"})
LIFECYCLE_SITES = frozenset({"forward_add", "force_stop", "forward_remove"})
STDERR_CATEGORIES = frozenset({"listener_not_found", "device_offline", "no_device",
    "multiple_devices", "transport_closed", "other", "unavailable"})
STOP_STAGES = frozenset({"force_stop", "finish", "process_wait", "reader_join", "exit_check"})
STOP_EXCEPTION_KINDS = frozenset({"called_process_error", "timeout_expired", "os_error", "other"})
STOP_ORIGINS = frozenset({"old_stop", "start_rollback", "other_stop"})


def adb_stderr_category(stderr, arguments):
    """Classify bounded complete ADB text; never export text or a port."""
    if type(stderr) is not bytes or len(stderr) > 4096:
        return "unavailable"
    text = stderr.strip()
    if (len(arguments) == 3 and arguments[:2] == ("forward", "--remove")
            and type(arguments[2]) is str and re.fullmatch(r"tcp:[0-9]{1,5}", arguments[2])
            and text == b"adb: error: listener '" + arguments[2].encode('ascii') + b"' not found"):
        return "listener_not_found"
    return {b"adb: error: device offline": "device_offline",
        b"adb: error: no devices/emulators found": "no_device",
        b"adb: error: more than one device/emulator": "multiple_devices",
        b"adb: error: closed": "transport_closed"}.get(text, "other")


def stop_failure(stage, error):
    kind = ("called_process_error" if isinstance(error, subprocess.CalledProcessError) else
            "timeout_expired" if isinstance(error, subprocess.TimeoutExpired) else
            "os_error" if isinstance(error, OSError) else "other")
    return {"stage": stage, "exception_kind": kind}


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


def android_lifecycle_snapshot(value):
    """Copy only fixed labels and bounded owned-process state from a failed ADB call."""
    required = {"v", "site", "exit_status", "instrumentation_process", "instrumentation"}
    if (type(value) is not dict or not required <= set(value)
            or set(value) - required - {"stderr_category", "prior_failure", "stop_origin", "masked_start_kind"}
            or type(value["v"]) is not int or value["v"] != 1
            or type(value["site"]) is not str or value["site"] not in LIFECYCLE_SITES):
        return None
    if 'stderr_category' in value and (type(value['stderr_category']) is not str
            or value['stderr_category'] not in STDERR_CATEGORIES):
        return None
    if 'stop_origin' in value and (type(value['stop_origin']) is not str or value['stop_origin'] not in STOP_ORIGINS):
        return None
    if 'masked_start_kind' in value and (value.get('stop_origin') != 'start_rollback'
            or type(value['masked_start_kind']) is not str or value['masked_start_kind'] not in STOP_EXCEPTION_KINDS):
        return None
    if 'prior_failure' in value:
        prior = value['prior_failure']
        if (type(prior) is not dict or set(prior) != {'stage', 'exception_kind'}
                or type(prior['stage']) is not str or prior['stage'] not in STOP_STAGES
                or type(prior['exception_kind']) is not str or prior['exception_kind'] not in STOP_EXCEPTION_KINDS):
            return None
    code = value["exit_status"]
    if code is not None and (type(code) is not int or not -64 <= code <= 255 or code == 0):
        return None
    process = value["instrumentation_process"]
    if (type(process) is not dict or set(process) != {"state", "exit_status"}
            or type(process["state"]) is not str or process["state"] not in PROCESS_STATES
            or (process["state"] == "exited") != (type(process["exit_status"]) is int)
            or (process["state"] != "exited" and process["exit_status"] is not None)
            or (type(process["exit_status"]) is int and not -255 <= process["exit_status"] <= 255)):
        return None
    status = value["instrumentation"]
    if status is not None and (type(status) is not dict or set(status) != {"reader_eof", "code", "marker"}
            or type(status["reader_eof"]) is not bool
            or (status["code"] is not None and (type(status["code"]) is not str
                or status["code"] not in INSTRUMENTATION_CODES))
            or (status["marker"] is not None and (type(status["marker"]) is not str
                or status["marker"] not in MARKERS))):
        return None
    return {**value, **({'prior_failure': dict(value['prior_failure'])} if 'prior_failure' in value else {}),
            "instrumentation_process": dict(process),
            "instrumentation": dict(status) if status is not None else None}


class InstrumentationStatus:
    """Reduce already-consumed stdout lines to fixed labels, never raw text."""

    def __init__(self):
        self._state = (False, None, None)

    def observe(self, line):
        if type(line) is not bytes or len(line) > 8192:
            return
        eof, code, marker = self._state
        match = re.fullmatch(rb"INSTRUMENTATION_CODE: (-1|0|1)\r?\n", line)
        if match is not None:
            code = match[1].decode("ascii")
        if re.fullmatch(rb"INSTRUMENTATION_RESULT: shortMsg=Process crashed\.\r?\n", line):
            marker = "process_crash"
        elif line.startswith(b"INSTRUMENTATION_FAILED:"):
            if marker != "process_crash":
                marker = "instrumentation_failed"
        elif (line.startswith(b"INSTRUMENTATION_RESULT: shortMsg=")
              or line.startswith(b"INSTRUMENTATION_STATUS: Error=")):
            if marker != "process_crash":
                marker = "error"
        self._state = (eof, code, marker)

    def ended(self):
        _, code, marker = self._state
        self._state = (True, code, marker)

    def snapshot(self):
        eof, code, marker = self._state
        return {"reader_eof": eof, "code": code, "marker": marker}


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
            or (value["eof_stage"] == "header" and (byte_count >= 4 or read_count > 4
                or value["received_bytes_capped"] or value["read_calls_capped"]))
            or (value["eof_stage"] == "body" and byte_count < 4)):
        return None
    process, status = value["process"], value["instrumentation"]
    if (type(process) is not dict or set(process) != {"state", "exit_status"}
            or type(process["state"]) is not str or process["state"] not in PROCESS_STATES
            or (process["state"] == "exited") != (type(process["exit_status"]) is int)
            or (process["state"] != "exited" and process["exit_status"] is not None)
            or (type(process["exit_status"]) is int and not -255 <= process["exit_status"] <= 255)
            or type(status) is not dict or set(status) != {"reader_eof", "code", "marker"}
            or type(status["reader_eof"]) is not bool
            or (status["code"] is not None and (type(status["code"]) is not str
                                                or status["code"] not in INSTRUMENTATION_CODES))
            or (status["marker"] is not None and (type(status["marker"]) is not str
                                                  or status["marker"] not in MARKERS))):
        return None
    return {**value, "process": dict(process), "instrumentation": dict(status)}
