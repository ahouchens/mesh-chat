"""Bounded startup attribution, separate from subsequent rollback failures."""
import queue
import subprocess

from native_interop_android_observation import android_lifecycle_snapshot, android_transport_snapshot

STAGES = frozenset({"port_wait", "port_validate", "forward", "forward_validate", "connect",
                    "authenticate", "initialize", "inventory", "binding"})
KINDS = frozenset({"called_process_error", "timeout_expired", "os_error", "peer_failure", "queue_empty", "other"})
ERROR_CODES = frozenset({"invalid_android_port", "invalid_adb_forward", "peer_closed", "peer_deadline",
    "invalid_peer_reply", "peer_frame_budget", "peer_unavailable", "internal", "unauthorized", "other"})


def exception_kind(error, *, peer_failure=False):
    if peer_failure: return "peer_failure"
    if isinstance(error, subprocess.CalledProcessError): return "called_process_error"
    if isinstance(error, subprocess.TimeoutExpired): return "timeout_expired"
    if isinstance(error, OSError): return "os_error"
    if isinstance(error, queue.Empty): return "queue_empty"
    return "other"


def start_observation(stage, error, *, peer_failure=False, transport=None, lifecycle=None):
    code = getattr(error, "code", None) if peer_failure else None
    result = {"v": 1, "stage": stage, "exception_kind": exception_kind(error, peer_failure=peer_failure),
        "error_code": (code if type(code) is str and code in ERROR_CODES else "other") if peer_failure else None,
        "rollback_exception_kind": None}
    if transport is not None: result["transport"] = transport
    if lifecycle is not None: result["initial_lifecycle"] = lifecycle
    return start_failure_snapshot(result)


def start_failure_snapshot(value):
    required = {"v", "stage", "exception_kind", "error_code", "rollback_exception_kind"}
    optional = {"transport", "initial_lifecycle", "rollback_lifecycle"}
    if (type(value) is not dict or not required <= set(value) or set(value)-required-optional
            or type(value["v"]) is not int or value["v"] != 1
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["exception_kind"]) is not str or value["exception_kind"] not in KINDS):
        return None
    code, rollback = value["error_code"], value["rollback_exception_kind"]
    if ((value["exception_kind"] == "peer_failure" and (type(code) is not str or code not in ERROR_CODES))
            or (value["exception_kind"] != "peer_failure" and code is not None)
            or (rollback is not None and (type(rollback) is not str or rollback not in KINDS))
            or ("rollback_lifecycle" in value and rollback != "called_process_error")
            or ("initial_lifecycle" in value and value["exception_kind"] != "called_process_error")
            or ("transport" in value and code != "peer_closed")):
        return None
    result = {key: value[key] for key in required}
    for key in optional & set(value):
        selected = (android_transport_snapshot(value[key]) if key == "transport"
                    else android_lifecycle_snapshot(value[key]))
        if selected is None: return None
        result[key] = selected
    return result
