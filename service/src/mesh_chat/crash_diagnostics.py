"""Content-free failure evidence for the desktop host's bounded stderr capture."""
from __future__ import annotations

import json
import queue
import sys

from .errors import ValidationError

PREFIX = "mesh-chat-diagnostic:"
STAGES = {"read_initial", "initialize", "read_command", "dispatch", "write_response", "shutdown", "thread"}
MODULES = {"__main__", "ipc", "direct_native", "service", "vault", "network", "webrtc_interface", "reconnect_service"}
COMMANDS = {"initialize", "snapshot", "workspace_snapshot", "webrtc_packet", "webrtc_attach", "webrtc_detach",
            "signal_fetch", "signal_publish", "reconnect_profiles", "reconnect_capabilities_get", "reconnect_capabilities_store"}


def failure_record(stage: str, error: BaseException, command=None, reader=None) -> dict:
    category = "unexpected_error"
    for kind, name in ((queue.Full, "command_queue_full"), (ValidationError, "validation_error"),
                       (BrokenPipeError, "broken_pipe"), (EOFError, "end_of_stream"),
                       (MemoryError, "out_of_memory"), (OSError, "os_error"),
                       (ValueError, "value_error"), (RuntimeError, "runtime_error")):
        if isinstance(error, kind):
            category = name
            break
    frames = []
    trace = error.__traceback__
    while trace is not None:
        module = trace.tb_frame.f_globals.get("__name__", "")
        short = module.removeprefix("mesh_chat.") if isinstance(module, str) else ""
        if module == f"mesh_chat.{short}" and short in MODULES:
            frames.append({"module": short, "line": trace.tb_lineno})
        trace = trace.tb_next
    record = {"v": 1, "stage": stage if stage in STAGES else "unknown", "category": category,
              "last_command": command if isinstance(command, str) and command in COMMANDS else "other",
              "frames": frames[-8:]}
    if reader is not None:
        record["pending_commands"] = reader._requests.qsize()
        record["queue_capacity"] = reader._requests.maxsize
    return record


def report_failure(stage: str, error: BaseException, command=None, reader=None) -> None:
    try:
        # Never serialize exception messages, frame locals, paths or payloads.
        print(PREFIX + json.dumps(failure_record(stage, error, command, reader), separators=(",", ":")),
              file=sys.stderr, flush=True)
    except Exception:
        pass  # Diagnostics must never replace the original failure.
