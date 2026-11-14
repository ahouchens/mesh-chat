"""Protocol checks for the installed public Android session runner."""

from pathlib import Path
import io
import queue
import socket
import sys
import threading
import time

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_android_independent_public_session as session
from test_app_owned_mobile_host import ordinary
from test_mobile_bootstrap import mobile_request


def test_frame_rejects_oversize_and_truncation():
    with pytest.raises(ValueError, match="frame_budget"):
        session.encode_frame({"payload": "x" * 65536})
    left, right = socket.socketpair()
    try:
        left.sendall(b"\x00\x00\x00\x02{")
        left.shutdown(socket.SHUT_WR)
        with pytest.raises(EOFError, match="public_session_closed"):
            session.read_frame(right)
    finally:
        left.close()
        right.close()


def test_status_accepts_only_bounded_public_port():
    assert session.status_port(b"INSTRUMENTATION_STATUS: mesh_public_port=37777\r\n") == 37777
    assert session.status_port(b"INSTRUMENTATION_STATUS: mesh_interop_port=37777\n") is None
    with pytest.raises(ValueError, match="public_session_port"):
        session.status_port(b"INSTRUMENTATION_STATUS: mesh_public_port=80\n")


def test_phase_sequence_requires_same_connection_and_finishes():
    client, server = socket.socketpair()
    observed = []

    def host():
        try:
            while True:
                request = session.read_frame(server)
                observed.append(request)
                action = request["action"]
                if action == "authenticate":
                    result = {"authenticated": True}
                elif action == "finish":
                    result = {"completed": True, "requests": 6}
                else:
                    operation = request["operation"]
                    if operation == "runtime.capabilities":
                        result = {"operations": [], "profiles": ["profile-a"]}
                    elif operation == "application.snapshot":
                        result = {"profile": {"id": "profile-a"} if len(observed) > 6 else None,
                                  "contacts": [], "messages": []}
                    elif operation == "profile.query":
                        result = {"destination": "public-destination"}
                    else:
                        assert operation == "profile.create"
                        assert request["idempotency_key"].startswith("public-session-")
                        result = {"created": True}
                server.sendall(session.encode_frame({"id": request["id"], "ok": True, "result": result}))
                if action == "finish":
                    break
        finally:
            server.close()

    thread = threading.Thread(target=host)
    thread.start()
    try:
        assert session.run_phases(client, "a" * 64, time.monotonic() + 5) == 6
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert [request.get("step") for request in observed[1:]] == list(range(1, 8))


def test_normal_core_owner_handle_is_stable_across_profile_creation(ordinary):
    assert ordinary.profile
    client, server = socket.socketpair()
    client.settimeout(5)
    errors = []

    def host():
        try:
            while True:
                frame = session.read_frame(server)
                if frame["action"] == "authenticate":
                    reply = {"id": frame["id"], "ok": True, "result": {"authenticated": True}}
                elif frame["action"] == "finish":
                    reply = {"id": frame["id"], "ok": True, "result": {"completed": True, "requests": 6}}
                else:
                    core = ordinary.request(frame["operation"], frame["params"], frame.get("idempotency_key"))
                    reply = {"id": frame["id"], "ok": core["ok"]}
                    reply["result" if core["ok"] else "error"] = core["result" if core["ok"] else "error"]
                server.sendall(session.encode_frame(reply))
                if frame["action"] == "finish":
                    break
        except Exception as error:
            errors.append(error)
        finally:
            server.close()

    thread = threading.Thread(target=host)
    thread.start()
    try:
        assert session.run_phases(client, "a" * 64, time.monotonic() + 10) == 6
        assert ordinary.request("runtime.capabilities")["result"]["profiles"] == [ordinary.profile]
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive() and not errors


def test_wrong_reply_id_fails_closed():
    client, server = socket.socketpair()
    try:
        server.sendall(session.encode_frame({"id": "different", "ok": True, "result": {}}))
        with pytest.raises(ValueError, match="public_session_reply"):
            session.exchange(client, {"id": "expected", "action": "authenticate", "nonce": "a" * 64})
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize("failure", ["deadline", "overflow"])
def test_failed_output_admission_kills_instrumentation_and_stops_app(monkeypatch, failure):
    calls = []

    class Process:
        def poll(self):
            return None

        def kill(self):
            calls.append("kill")

        def wait(self, timeout):
            calls.append("wait")
            return -9

    class MissingPort:
        def get(self, timeout):
            if failure == "deadline":
                raise queue.Empty
            return "overflow"

    class Reader:
        def join(self, timeout):
            calls.append("join")

        def is_alive(self):
            return False

    monkeypatch.setattr(session, "verified_distribution", lambda expected: ({"source_commit": expected}, {}))
    monkeypatch.setattr(session, "admit_emulator", lambda serial: None)
    monkeypatch.setattr(session.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(session, "adb", lambda *args, **kwargs: calls.append(args) or "Success")
    monkeypatch.setattr(session, "instrument", lambda serial, nonce:
                        (Process(), Reader(), MissingPort(), [], threading.Event()))
    result = session.run("a" * 40, "emulator-5554")
    assert result["passed"] is False
    assert result["phase"] == "instrumentation"
    assert result["failure_type"] == ("TimeoutError" if failure == "deadline" else "ValueError")
    assert result["cleanup"] is True
    assert calls[-5:] == ["kill", "wait", "join", ("emulator-5554", "shell", "am", "force-stop", session.APP),
                          ("emulator-5554", "shell", "am", "force-stop", session.APP + ".test")]


def test_source_preflight_failure_makes_no_adb_mutation(monkeypatch):
    calls = []
    def invalid(expected):
        raise ValueError("source_commit")
    monkeypatch.setattr(session, "verified_distribution", invalid)
    monkeypatch.setattr(session, "adb", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(session.subprocess, "run", lambda *args, **kwargs: calls.append("uninstall"))
    result = session.run("a" * 40, "emulator-5554")
    assert result["passed"] is False and result["phase"] == "distribution"
    assert result["cleanup"] is True and calls == []


@pytest.mark.parametrize("serial,qemu", [("physical-123", "1"), ("emulator-5554", "0")])
def test_non_emulator_admission_refuses_before_mutation(monkeypatch, serial, qemu):
    calls = []
    monkeypatch.setattr(session, "verified_distribution", lambda expected: ({"source_commit": expected}, {}))
    monkeypatch.setattr(session, "adb", lambda selected, *args, **kwargs:
                        calls.append((selected, args)) or ("device" if args == ("get-state",) else qemu))
    monkeypatch.setattr(session.subprocess, "run", lambda *args, **kwargs: calls.append("uninstall"))
    result = session.run("a" * 40, serial)
    assert result["passed"] is False and result["phase"] == "emulator_admission"
    assert "uninstall" not in calls
    assert all(args != ("shell", "am", "force-stop", session.APP) for _, args in calls)


def test_bounded_output_reader_marks_overflow(monkeypatch):
    class Process:
        stdout = io.BytesIO(b"x" * 8193 + b"\n")

    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: Process())
    process, reader, ports, observed, overflow = session.instrument("emulator-5554", "a" * 64)
    reader.join(timeout=2)
    assert not reader.is_alive() and overflow.is_set()
    assert ports.get_nowait() == "overflow" and observed == []


def test_total_output_budget_rejects_without_retaining_extra_lines(monkeypatch):
    class Process:
        stdout = io.BytesIO(b"line\n" * 60000)

    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: Process())
    _, reader, ports, observed, overflow = session.instrument("emulator-5554", "a" * 64)
    reader.join(timeout=2)
    assert not reader.is_alive() and overflow.is_set()
    assert ports.get_nowait() == "overflow"
    assert sum(map(len, observed)) <= 256000


def test_session_deadline_applies_to_each_partial_read():
    left, right = socket.socketpair()
    try:
        left.sendall(b"\x00")
        with pytest.raises(TimeoutError):
            session.read_exact(right, 4, time.monotonic() + 0.02)
    finally:
        left.close()
        right.close()
