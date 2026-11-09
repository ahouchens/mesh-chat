"""Fixed native CI workloads; only a known pull-request diff may use smoke."""

from pathlib import PurePosixPath

PATH_CASES = (("direct", "windows"), ("direct", "android"), ("turn_udp", "windows"),
              ("turn_tcp", "windows"), ("turn_tls", "windows"), ("impaired", "windows"))
LEVEL = "packaged_windows_android_emulator_native_interop"
SCOPE = "Actual frozen Windows and optimized Android own-UID hosts, production encrypted mailbox, native packets and authenticated receipts; no physical or UI media qualification"


def selected_workload(event, paths):
    known = isinstance(paths, list) and bool(paths) and all(
        isinstance(path, str) and path and "\\" not in path
        and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
        for path in paths)
    return "quick" if event == "pull_request" and known else "full"


def workload(name):
    if not isinstance(name, str) or name not in {"quick", "full"}:
        raise ValueError("Unknown required native workload")
    full = name == "full"
    return {"name": name, "paths": PATH_CASES if full else PATH_CASES[:3],
            "iterations": 100 if full else 5, "cold_start_every": 10,
            "level": LEVEL if full else LEVEL + "_quick_smoke",
            "scope": SCOPE if full else "Actual frozen Windows and optimized Android own-UID smoke: both direct initiators, TURN UDP, five receipt iterations and one cold restart; no full transport/fault/100-iteration qualification"}
