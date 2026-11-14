"""Bounded, identifier-free Android testhost I/O evidence for socket EOF."""

import re
import subprocess
import threading
import time

from native_interop_android_observation import INSTRUMENTATION_CODES, MARKERS, PROCESS_STATES
from native_interop_android_system import system_snapshot


STAGES = frozenset({"read_header", "read_body", "dispatch", "write_header", "write_body",
                    "flush", "snapshot_dispatch_enter", "snapshot_flush_complete",
                    "initialize_dispatch_enter", "initialize_return", "initialize_flush_complete"})
MILESTONES = ("snapshot_dispatch_enter", "snapshot_flush_complete",
              "initialize_dispatch_enter", "initialize_return", "initialize_flush_complete")
CATEGORIES = frozenset({"none", "eof", "timeout", "io", "protocol", "other"})
STATUS = re.compile(rb"INSTRUMENTATION_STATUS: mesh_interop_io=v1\|([1-9][0-9]{0,7})\|"
                    rb"(read_header|read_body|dispatch|write_header|write_body|flush|"
                    rb"snapshot_dispatch_enter|snapshot_flush_complete|initialize_dispatch_enter|"
                    rb"initialize_return|initialize_flush_complete)\|"
                    rb"(none|eof|timeout|io|protocol|other)\|([0-9]{1,6})\|([01])\r?\n\Z")
MAX_MS = 120000


def event(line):
    """Accept only one complete, small instrumentation status line."""
    if type(line) is not bytes or len(line) > 192:
        return None
    match = STATUS.fullmatch(line)
    if match is None:
        return None
    ordinal, stage, category, elapsed, capped = match.groups()
    return snapshot({"ordinal": int(ordinal), "stage": stage.decode("ascii"),
            "category": category.decode("ascii"), "elapsed_ms": int(elapsed),
            "elapsed_capped": capped == b"1"})


def snapshot(value):
    if (type(value) is not dict or set(value) != {"ordinal", "stage", "category", "elapsed_ms", "elapsed_capped"}
            or type(value["ordinal"]) is not int or not 1 <= value["ordinal"] <= 99999999
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["category"]) is not str or value["category"] not in CATEGORIES
            or type(value["elapsed_ms"]) is not int or not 0 <= value["elapsed_ms"] <= MAX_MS
            or type(value["elapsed_capped"]) is not bool
            or (value["elapsed_capped"] and value["elapsed_ms"] != MAX_MS)):
        return None
    return dict(value)


class TesthostIoStatus:
    def __init__(self):
        self._latest = ()

    def observe(self, line):
        row = event(line)
        if row is None:
            return
        previous = self._latest
        if previous and row["ordinal"] < previous[-1]["last"]["ordinal"]:
            return
        if previous and row["ordinal"] > previous[-1]["last"]["ordinal"] + 1:
            previous = ()
        same = previous[-1] if previous and previous[-1]["last"]["ordinal"] == row["ordinal"] else None
        entry = {"last": row, **{name: bool(same and same[name]) or row["stage"] == name
                                 for name in MILESTONES}}
        self._latest = tuple(item for item in previous if item["last"]["ordinal"] == row["ordinal"] - 1)[-1:] + (entry,)

    def matching(self, ordinal):
        if type(ordinal) is not int or not 1 <= ordinal <= 99999999:
            return []
        return [{"last": dict(item["last"]), **{name: item[name] for name in MILESTONES}}
                for item in self._latest if item["last"]["ordinal"] in (ordinal - 1, ordinal)]


def reader_observation(reader):
    """Inspect the already-owned reader without joining it."""
    if reader is None:
        return "absent"
    try:
        alive = reader.is_alive()
        return "alive" if alive is True else "ended" if alive is False else "unknown"
    except Exception:
        return "unknown"


def _process_snapshot(value):
    if (type(value) is not dict or set(value) != {"state", "exit_status"}
            or type(value["state"]) is not str or value["state"] not in PROCESS_STATES
            or (value["state"] == "exited") != (type(value["exit_status"]) is int)
            or (value["state"] != "exited" and value["exit_status"] is not None)
            or (type(value["exit_status"]) is int and not -255 <= value["exit_status"] <= 255)):
        return None
    return dict(value)


def _instrumentation_snapshot(value):
    if (type(value) is not dict or set(value) != {"reader_eof", "code", "marker"}
            or type(value["reader_eof"]) is not bool
            or (value["code"] is not None and (type(value["code"]) is not str
                or value["code"] not in INSTRUMENTATION_CODES))
            or (value["marker"] is not None and (type(value["marker"]) is not str
                or value["marker"] not in MARKERS))):
        return None
    return dict(value)


def _statuses_snapshot(value, ordinal):
    if (type(ordinal) is not int or not 1 <= ordinal <= 99999999
            or type(value) is not list or len(value) > 2):
        return None
    selected = []
    for entry in value:
        if (type(entry) is not dict or set(entry) != {"last", *MILESTONES}
                or any(type(entry[name]) is not bool for name in MILESTONES)):
            return None
        row = snapshot(entry["last"])
        if row is None or row["ordinal"] not in (ordinal - 1, ordinal):
            return None
        if selected and row["ordinal"] <= selected[-1]["last"]["ordinal"]:
            return None
        if (entry["snapshot_flush_complete"] and not entry["snapshot_dispatch_enter"]
                or entry["initialize_return"] and not entry["initialize_dispatch_enter"]
                or entry["initialize_flush_complete"] and not entry["initialize_return"]
                or (entry["snapshot_dispatch_enter"] or entry["snapshot_flush_complete"])
                    and (entry["initialize_dispatch_enter"] or entry["initialize_return"]
                         or entry["initialize_flush_complete"])):
            return None
        selected.append({"last": row, **{name: entry[name] for name in MILESTONES}})
    return selected


def pre_probe_snapshot(value, ordinal):
    """Retain only observations from owned handles before any ADB probe."""
    fields = {"instrumentation_process", "instrumentation_reader", "adb_server_process",
              "emulator_process", "instrumentation", "emulator_system", "statuses"}
    if type(value) is not dict or set(value) != fields:
        return None
    processes = {key: _process_snapshot(value[key]) for key in
                 ("instrumentation_process", "adb_server_process", "emulator_process")}
    status = _instrumentation_snapshot(value["instrumentation"])
    rows = _statuses_snapshot(value["statuses"], ordinal)
    system = system_snapshot(value["emulator_system"]) if value["emulator_system"] is not None else None
    if (any(item is None for item in processes.values()) or status is None or rows is None
            or (value["emulator_system"] is not None and system is None)
            or type(value["instrumentation_reader"]) is not str
            or value["instrumentation_reader"] not in {"absent", "alive", "ended", "unknown"}):
        return None
    return {**processes, "instrumentation_reader": value["instrumentation_reader"],
            "instrumentation": status, "emulator_system": system, "statuses": rows}


def failure_snapshot(value, ordinal):
    """Validate an EOF observation with separate pre- and post-probe states."""
    fields = {"statuses", "device", "forward", "app_process"}
    if (type(value) is not dict or not fields <= set(value) or set(value) - fields - {"pre_probe"}
            or type(value["device"]) is not str
            or value["device"] not in {"device", "offline", "unauthorized", "other", "unknown", "timeout"}
            or type(value["forward"]) is not str
            or value["forward"] not in {"present", "absent", "unknown", "timeout"}
            or type(value["app_process"]) is not str
            or value["app_process"] not in {"absent", "one", "multiple", "unknown", "timeout"}):
        return None
    rows = _statuses_snapshot(value["statuses"], ordinal)
    pre = pre_probe_snapshot(value["pre_probe"], ordinal) if "pre_probe" in value else None
    if rows is None or ("pre_probe" in value and pre is None):
        return None
    return {"statuses": rows, "device": value["device"], "forward": value["forward"],
            "app_process": value["app_process"], **({"pre_probe": pre} if pre is not None else {})}


def _bounded_adb(argv, deadline, limit, cleanup_slice):
    """Return one capped output and exit code under the caller's shared deadline."""
    if time.monotonic() >= deadline:
        return None, None, "timeout"
    process = None
    result = {}
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        def read():
            try: result["data"] = process.stdout.read(limit + 1)
            except Exception: result["error"] = True
            finally:
                try: process.stdout.close()
                except Exception: pass
        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        worker.join(max(0, deadline - time.monotonic()))
        if worker.is_alive():
            return None, None, "timeout"
        if result.get("error") or len(result.get("data", b"")) > limit:
            return None, None, "unknown"
        try:
            code = process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return None, None, "timeout"
        return result["data"], code, None
    except Exception:
        return None, None, "unknown"
    finally:
        if process is not None:
            try:
                if process.poll() is None: process.kill()
                process.wait(timeout=cleanup_slice)
            except Exception: pass


def _device_label(data, code, failure):
    if failure is not None or code != 0:
        return failure or "unknown"
    return {b"device": "device", b"offline": "offline", b"unauthorized": "unauthorized"}.get(
        data.strip(), "other" if re.fullmatch(rb"[a-z_-]{1,32}", data.strip()) else "unknown")


def _forward_label(data, code, failure, forward):
    if failure is not None or code != 0 or type(forward) is not str or re.fullmatch(r"[0-9]{1,5}", forward) is None:
        return failure or "unknown"
    # The ADB server formats each listener with '\n'; adb_query_command adds
    # one more '\n' after the complete result, including an empty result.
    if not data.endswith(b"\n"):
        return "unknown"
    payload = data[:-1]
    if payload and not payload.endswith(b"\n"):
        return "unknown"
    lines = payload.splitlines()
    if any(re.fullmatch(rb"[A-Za-z0-9_.:-]{1,64} tcp:[0-9]{1,5} tcp:[0-9]{1,5}", line) is None
           for line in lines):
        return "unknown"
    if any(re.fullmatch(rb"emulator-5554 tcp:" + forward.encode("ascii") + rb" tcp:[0-9]{1,5}", line)
           for line in lines):
        return "present"
    return "absent"


def _process_label(data, code, failure, device):
    if failure is not None:
        return failure
    if device != "device" or code != 0:
        return "unknown"
    # A bare adb exit 1 with empty stdout can mean either no PID or transport
    # loss. Only a marker emitted after remote pidof proves its exit status.
    match = re.fullmatch(rb"(?:([0-9]{1,10}(?: [0-9]{1,10})*)\r?\n)?"
                         rb"MESH_PIDOF_EXIT:([0-9]{1,3})\r?\n", data)
    if match is None:
        return "unknown"
    pids, remote_code = match.groups()
    if remote_code == b"1" and pids is None:
        return "absent"
    if remote_code != b"0" or pids is None:
        return "unknown"
    return "one" if len(pids.split()) == 1 else "multiple"


def control_path_presence(adb, forward, app, *, budget=3.4):
    """Sample pinned ADB device, owned forward, and fixed app under one deadline."""
    unknown = {"device": "unknown", "forward": "unknown", "app_process": "unknown"}
    if (type(adb) is not str or not adb or type(app) is not str
            or re.fullmatch(r"[a-z][a-z0-9_.]{1,127}", app) is None):
        return unknown
    budget = min(3.4, max(0, budget))
    cleanup_slice = min(.15, budget / 6)
    deadline = time.monotonic() + budget - 3 * cleanup_slice
    prefix = [adb, "-s", "emulator-5554"]
    device = _device_label(*_bounded_adb(prefix + ["get-state"], deadline, 64, cleanup_slice))
    forward_state = _forward_label(*_bounded_adb(prefix + ["forward", "--list"], deadline, 2048,
                                                 cleanup_slice), forward)
    command = f"pidof {app}; echo MESH_PIDOF_EXIT:$?"
    process = _process_label(*_bounded_adb(prefix + ["shell", command], deadline, 128,
                                           cleanup_slice), device)
    return {"device": device, "forward": forward_state, "app_process": process}
