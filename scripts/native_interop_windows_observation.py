"""Fixed, failure-only Windows process retirement evidence for qualification."""

import subprocess


ORIGINS = frozenset({"old_stop", "start_rollback", "other_stop"})
STAGES = frozenset({"poll", "kill_tree", "shutdown", "wait", "unknown"})
KINDS = frozenset({"called_process_error", "timeout_expired", "os_error", "peer_failure", "other"})
STATES = frozenset({"running", "exited", "unknown"})


def exception_kind(error):
    from native_interop_peers import PeerFailure

    if type(error) is subprocess.CalledProcessError:
        return "called_process_error"
    if type(error) is subprocess.TimeoutExpired:
        return "timeout_expired"
    if type(error) is PeerFailure:
        return "peer_failure"
    if isinstance(error, OSError):
        return "os_error"
    return "other"


def process_state(process):
    try:
        return "running" if process.poll() is None else "exited"
    except Exception:
        return "unknown"


def lifecycle_row(origin, stage, error, process, masked_start_kind="none"):
    kind = exception_kind(error)
    code = error.returncode if type(error) is subprocess.CalledProcessError else None
    code = code if type(code) is int and 0 <= code <= 255 else None
    return {"origin": origin if origin in ORIGINS else "other_stop",
            "stage": stage if stage in STAGES else "unknown",
            "exception_kind": kind, "returncode": code,
            "process_state": process_state(process),
            "masked_start_kind": masked_start_kind if masked_start_kind in KINDS else "none"}


def windows_lifecycle_snapshot(value):
    allowed = {"origin", "stage", "exception_kind", "returncode", "process_state", "masked_start_kind"}
    if type(value) is not dict or set(value) != allowed:
        return None
    if (type(value["origin"]) is not str or value["origin"] not in ORIGINS
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["exception_kind"]) is not str or value["exception_kind"] not in KINDS
            or type(value["process_state"]) is not str or value["process_state"] not in STATES
            or type(value["masked_start_kind"]) is not str
            or value["masked_start_kind"] not in KINDS | {"none"}):
        return None
    code = value["returncode"]
    if (code is not None and (type(code) is not int or not 0 <= code <= 255)):
        return None
    if code is not None and value["exception_kind"] != "called_process_error":
        return None
    if value["origin"] != "start_rollback" and value["masked_start_kind"] != "none":
        return None
    return {key: value[key] for key in allowed}
