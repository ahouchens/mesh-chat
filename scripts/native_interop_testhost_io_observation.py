"""Bounded, identifier-free Android testhost I/O evidence for socket EOF."""

import re
import subprocess
import threading


STAGES = frozenset({"read_header", "read_body", "dispatch", "write_header", "write_body",
                    "flush", "snapshot_dispatch_enter", "snapshot_flush_complete"})
CATEGORIES = frozenset({"none", "eof", "timeout", "io", "protocol", "other"})
STATUS = re.compile(rb"INSTRUMENTATION_STATUS: mesh_interop_io=v1\|([1-9][0-9]{0,7})\|"
                    rb"(read_header|read_body|dispatch|write_header|write_body|flush|"
                    rb"snapshot_dispatch_enter|snapshot_flush_complete)\|"
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
        entry = {"last": row,
                 "snapshot_dispatch_enter": bool(same and same["snapshot_dispatch_enter"])
                     or row["stage"] == "snapshot_dispatch_enter",
                 "snapshot_flush_complete": bool(same and same["snapshot_flush_complete"])
                     or row["stage"] == "snapshot_flush_complete"}
        self._latest = tuple(item for item in previous if item["last"]["ordinal"] == row["ordinal"] - 1)[-1:] + (entry,)

    def matching(self, ordinal):
        if type(ordinal) is not int or not 1 <= ordinal <= 99999999:
            return []
        return [{"last": dict(item["last"]),
                 "snapshot_dispatch_enter": item["snapshot_dispatch_enter"],
                 "snapshot_flush_complete": item["snapshot_flush_complete"]}
                for item in self._latest if item["last"]["ordinal"] in (ordinal - 1, ordinal)]


def failure_snapshot(value, ordinal):
    """Validate one captured EOF observation before report retention."""
    if (type(ordinal) is not int or not 1 <= ordinal <= 99999999
            or type(value) is not dict or set(value) != {"statuses", "forward"}
            or type(value["forward"]) is not str
            or value["forward"] not in {"present", "absent", "unknown", "timeout"}
            or type(value["statuses"]) is not list or len(value["statuses"]) > 2):
        return None
    selected = []
    for entry in value["statuses"]:
        if (type(entry) is not dict or set(entry) != {"last", "snapshot_dispatch_enter", "snapshot_flush_complete"}
                or type(entry["snapshot_dispatch_enter"]) is not bool
                or type(entry["snapshot_flush_complete"]) is not bool):
            return None
        row = snapshot(entry["last"])
        if row is None or row["ordinal"] not in (ordinal - 1, ordinal):
            return None
        if selected and row["ordinal"] <= selected[-1]["last"]["ordinal"]:
            return None
        if entry["snapshot_flush_complete"] and not entry["snapshot_dispatch_enter"]:
            return None
        selected.append({"last": row, "snapshot_dispatch_enter": entry["snapshot_dispatch_enter"],
                         "snapshot_flush_complete": entry["snapshot_flush_complete"]})
    return {"statuses": selected, "forward": value["forward"]}


def forward_presence(adb, forward):
    """Sample one mapping with a three second read and at most 0.2 second cleanup."""
    if (type(adb) is not str or not adb or type(forward) is not str
            or re.fullmatch(r"[0-9]{1,5}", forward) is None):
        return "unknown"
    process = None
    result = {}
    try:
        process = subprocess.Popen([adb, "-s", "emulator-5554", "forward", "--list"], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        def read():
            try: result["data"] = process.stdout.read(2049)
            except Exception: result["error"] = True
            finally:
                try: process.stdout.close()
                except Exception: pass
        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        worker.join(3)
        if worker.is_alive():
            return "timeout"
        if result.get("error") or len(result.get("data", b"")) > 2048:
            return "unknown"
        try:
            if process.wait(timeout=0) != 0:
                return "unknown"
        except subprocess.TimeoutExpired:
            return "timeout"
        data = result["data"]
        lines = data.splitlines()
        if any(re.fullmatch(rb"[A-Za-z0-9_.:-]{1,64} tcp:[0-9]{1,5} tcp:[0-9]{1,5}", line) is None
               for line in lines):
            return "unknown"
        if any(re.fullmatch(rb"emulator-5554 tcp:" + forward.encode("ascii") + rb" tcp:[0-9]{1,5}", line)
               for line in lines):
            return "present"
        return "absent"
    except Exception:
        return "unknown"
    finally:
        if process is not None:
            try:
                if process.poll() is None: process.kill()
                process.wait(timeout=0.2)
            except Exception: pass
