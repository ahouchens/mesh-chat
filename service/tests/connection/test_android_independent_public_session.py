"""Protocol checks for the installed public Android session runner."""

from pathlib import Path
import socket
import sys
import threading

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_android_independent_public_session as session


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
                        result = {"operations": [], "profiles": ["profile-a"] if len(observed) > 4 else []}
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
        assert session.run_phases(client, "a" * 64) == 6
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert [request.get("step") for request in observed[1:]] == list(range(1, 8))


def test_wrong_reply_id_fails_closed():
    client, server = socket.socketpair()
    try:
        server.sendall(session.encode_frame({"id": "different", "ok": True, "result": {}}))
        with pytest.raises(ValueError, match="public_session_reply"):
            session.exchange(client, {"id": "expected", "action": "authenticate", "nonce": "a" * 64})
    finally:
        client.close()
        server.close()


def test_port_deadline_kills_instrumentation_and_stops_app(monkeypatch):
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
            raise TimeoutError("port_deadline")

    monkeypatch.setattr(session, "verified_distribution", lambda: ({"source_commit": "a" * 40}, {}))
    monkeypatch.setattr(session.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(session, "adb", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(session, "instrument", lambda nonce: (Process(), None, MissingPort(), []))
    result = session.run()
    assert result["passed"] is False
    assert result["phase"] == "instrumentation"
    assert result["failure_type"] == "TimeoutError"
    assert result["cleanup"] is True
    assert calls[-4:] == ["kill", "wait", ("shell", "am", "force-stop", session.APP),
                          ("shell", "am", "force-stop", session.APP + ".test")]
