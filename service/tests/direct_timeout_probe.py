"""Bounded, test-only worker attribution at the existing Direct reply timeout.

The shared record contains integer labels and allowlisted source locations only.
Neither the sampler nor the parent timeout path takes a service lock or calls a
worker. A missed sample is reported as unknown rather than borrowing an old one.
"""

import multiprocessing
import os
import sys
import threading
from itertools import islice


_COMMAND = {"answer": 1, "workspace_snapshot": 2, "other": 3}
_COMMAND_NAME = {value: key for key, value in _COMMAND.items()}
_PHASE = {"dequeued": 1, "waiting_dispatch": 2, "executing": 3, "reply_queued": 4}
_PHASE_NAME = {value: key for key, value in _PHASE.items()}

_TESTS = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
_SRC = os.path.normcase(os.path.abspath(os.path.join(_TESTS, "..", "src", "mesh_chat")))
_FILES = {
    os.path.join(_TESTS, "test_direct_setup_pipeline.py"): (1, "test_direct_setup_pipeline"),
    os.path.join(_TESTS, "test_direct_recovery_pipeline.py"): (2, "test_direct_recovery_pipeline"),
    os.path.join(_TESTS, "connection", "test_direct_timeout_probe.py"): (3, "test_direct_timeout_probe"),
    os.path.join(_TESTS, "direct_app_host_fixture.py"): (4, "direct_app_host_fixture"),
    os.path.join(_SRC, "direct_setup.py"): (5, "direct_setup"),
    os.path.join(_SRC, "direct_candidates.py"): (6, "direct_candidates"),
    os.path.join(_SRC, "workspace_service.py"): (7, "workspace_service"),
    os.path.join(_SRC, "service.py"): (8, "service"),
    os.path.join(_SRC, "connectivity.py"): (9, "connectivity"),
    os.path.join(_SRC, "direct_recovery.py"): (10, "direct_recovery"),
    os.path.join(_SRC, "vault.py"): (11, "vault"),
    os.path.join(_SRC, "network.py"): (12, "network"),
}
_FILES = {os.path.normcase(path): value for path, value in _FILES.items()}
_FILE_NAME = {code: label for code, label in _FILES.values()}

# Two single-writer rows, each guarded by its own odd/even publication counter.
_CG, _SEQ, _LABEL, _PHASE_CODE, _REV = range(5)
_SG, _SITE_SEQ, _SITE_REV, _SITE_FILE, _SITE_LINE, _OTHER_FILE, _OTHER_LINE, _TRUNCATED = range(5, 13)
_SIZE = 13


def new_probe():
    return multiprocessing.RawArray("i", _SIZE)


def command_label(operation, payload):
    if operation == "answer":
        return "answer"
    if (operation == "command" and type(payload) is dict
            and payload.get("command") == "workspace_snapshot"):
        return "workspace_snapshot"
    return "other"


def _read_row(shared, guard, fields):
    for _ in range(3):
        first = shared[guard]
        if first & 1:
            continue
        values = tuple(shared[index] for index in fields)
        if first == shared[guard] and not first & 1:
            return values
    return None


def _location(frame):
    for _ in range(32):
        if frame is None:
            return 0, 0, False
        mapped = _FILES.get(os.path.normcase(frame.f_code.co_filename))
        line = frame.f_lineno
        if mapped is not None and type(line) is int and 1 <= line <= 100000:
            return mapped[0], line, False
        frame = frame.f_back
    return 0, 0, frame is not None


class WorkerProbe:
    def __init__(self, shared, *, start_sampler=True):
        self.shared = shared
        self.sequence = 0
        self.revision = 0
        self.command_thread = threading.get_ident()
        self._stop = threading.Event()
        if start_sampler:
            try:
                threading.Thread(target=self._sample_loop, daemon=True,
                                 name="direct-test-timeout-sampler").start()
            except Exception:
                pass  # Observation cannot replace the worker's original result.

    def _publish(self, phase, label=None):
        shared = self.shared
        guard = shared[_CG]
        shared[_CG] = guard + 1
        if label is not None:
            self.sequence += 1
            shared[_SEQ] = self.sequence
            shared[_LABEL] = _COMMAND.get(label, _COMMAND["other"])
        self.revision += 1
        shared[_PHASE_CODE] = _PHASE[phase]
        shared[_REV] = self.revision
        shared[_CG] = guard + 2

    def begin(self, label):
        self._publish("dequeued", label)

    def waiting_dispatch(self):
        self._publish("waiting_dispatch")

    def executing(self):
        self._publish("executing")

    def reply_queued(self):
        self._publish("reply_queued")

    def sample_once(self):
        command = _read_row(self.shared, _CG, (_SEQ, _LABEL, _PHASE_CODE, _REV))
        if command is None or command[2] not in (_PHASE["waiting_dispatch"], _PHASE["executing"]):
            return
        frames = sys._current_frames()
        file_code, line, truncated = _location(frames.get(self.command_thread))
        other_file = other_line = 0
        # Other sites are context, never a claim about which thread owns a lock.
        for ident, frame in islice(frames.items(), 16):
            if ident == self.command_thread or ident == threading.get_ident():
                continue
            candidate_file, candidate_line, cut = _location(frame)
            truncated = truncated or cut
            if candidate_file and (other_file == 0 or (candidate_file, candidate_line) < (other_file, other_line)):
                other_file, other_line = candidate_file, candidate_line
        truncated = truncated or len(frames) > 16
        if _read_row(self.shared, _CG, (_SEQ, _LABEL, _PHASE_CODE, _REV)) != command:
            return
        shared = self.shared
        guard = shared[_SG]
        shared[_SG] = guard + 1
        shared[_SITE_SEQ] = command[0]
        shared[_SITE_REV] = command[3]
        shared[_SITE_FILE] = file_code
        shared[_SITE_LINE] = line
        shared[_OTHER_FILE] = other_file
        shared[_OTHER_LINE] = other_line
        shared[_TRUNCATED] = int(truncated)
        shared[_SG] = guard + 2

    def _sample_loop(self):
        while not self._stop.wait(.03):
            try:
                self.sample_once()
            except Exception:
                return  # A failing sampler is optional evidence only.

    def close(self):
        self._stop.set()


def _site(file_code, line):
    label = _FILE_NAME.get(file_code)
    return ({"file": label, "line": line} if label is not None
            and type(line) is int and 1 <= line <= 100000 else "unknown")


def timeout_note(shared, expected_sequence, expected_label, liveness):
    result = {"command": expected_label if expected_label in _COMMAND else "other",
              "phase": "unknown", "liveness": liveness if liveness in {"alive", "exited"} else "unknown",
              "site": "unknown", "other_site": "unknown", "other_truncated": False}
    if shared is None or result["liveness"] == "exited":
        return result
    command = _read_row(shared, _CG, (_SEQ, _LABEL, _PHASE_CODE, _REV))
    if (command is None or command[0] != expected_sequence
            or _COMMAND_NAME.get(command[1]) != result["command"]):
        return result
    site = _read_row(shared, _SG, (_SITE_SEQ, _SITE_REV, _SITE_FILE, _SITE_LINE,
                                    _OTHER_FILE, _OTHER_LINE, _TRUNCATED))
    if _read_row(shared, _CG, (_SEQ, _LABEL, _PHASE_CODE, _REV)) != command:
        return result
    result["phase"] = _PHASE_NAME.get(command[2], "unknown")
    if (site is not None and site[0] == expected_sequence and site[1] == command[3]
            and result["phase"] in {"waiting_dispatch", "executing"}):
        result["site"] = _site(site[2], site[3])
        result["other_site"] = _site(site[4], site[5])
        result["other_truncated"] = site[6] == 1
    return result
