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


def test_typed_public_core_error_keeps_numbered_session_usable():
    client, server = socket.socketpair()
    try:
        for reply in ({"id": "auth", "ok": True, "result": {"authenticated": True}},
                      {"id": "phase:1", "ok": False, "error": {"code": "locked"}},
                      {"id": "phase:2", "ok": True, "result": {"profiles": ["p"]}}):
            server.sendall(session.encode_frame(reply))
        protocol = session.PublicProtocol(client, "a" * 64, time.monotonic() + 5)
        with pytest.raises(session.PublicCoreError) as failure:
            protocol.request("profile.query", {"profile": "p"})
        assert failure.value.code == "locked"
        assert protocol.request("runtime.capabilities") == {"profiles": ["p"]}
        assert protocol.step == 2 and protocol.failed is False
    finally:
        client.close()
        server.close()


def test_public_protocol_rejects_private_operation_before_frame():
    protocol = object.__new__(session.PublicProtocol)
    protocol.finished = False
    protocol.failed = False
    protocol.step = 0
    with pytest.raises(ValueError, match="public_request"):
        protocol.request("native.command", {"command": "anything"})
    assert protocol.step == 0


def test_127_requests_reserve_step_128_for_successful_finish(monkeypatch):
    sent = []
    protocol = object.__new__(session.PublicProtocol)
    protocol.sock, protocol.deadline = object(), time.monotonic() + 5
    protocol.step, protocol.created = 126, True
    protocol.finished = protocol.failed = False
    def reply(sock, request, deadline):
        sent.append(request)
        return {"completed": True, "requests": 127} if request["action"] == "finish" else {}
    monkeypatch.setattr(session, "exchange", reply)
    assert protocol.request("runtime.capabilities") == {}
    assert protocol.step == 127
    with pytest.raises(ValueError, match="public_request"):
        protocol.request("runtime.capabilities")
    assert len(sent) == 1
    assert protocol.finish() == 127 and protocol.finished is True
    assert [item["step"] for item in sent] == [127, 128]


def test_exact_serial_is_used_for_read_only_admission(monkeypatch):
    calls = []
    monkeypatch.setattr(session.subprocess, "check_output", lambda args, **kwargs:
                        calls.append(args) or ("device" if args[-1] == "get-state" else "1"))
    session.admit_emulator("emulator-5554")
    assert calls == [["adb", "-s", "emulator-5554", "get-state"],
                     ["adb", "-s", "emulator-5554", "shell", "getprop", "ro.kernel.qemu"]]


def test_partial_startup_forward_failure_retires_owned_process(monkeypatch):
    calls = []

    class Process:
        def poll(self): return None
        def kill(self): calls.append("kill")
        def wait(self, timeout): calls.append("wait")

    class Reader:
        def join(self, timeout): calls.append("join")
        def is_alive(self): return False

    class Port:
        def get(self, timeout): return 37777

    def targeted_adb(serial, *args, **kwargs):
        calls.append((serial, args))
        if args[:1] == ("forward",):
            raise RuntimeError("forward_failed")
        return "Success"

    monkeypatch.setattr(session, "verified_distribution", lambda expected: ({"source_commit": expected}, {}))
    monkeypatch.setattr(session, "admit_emulator", lambda serial: None)
    monkeypatch.setattr(session.subprocess, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(session, "adb", targeted_adb)
    monkeypatch.setattr(session, "instrument", lambda serial, nonce:
                        (Process(), Reader(), Port(), [], threading.Event()))
    peer = session.AndroidPublicSession("a" * 40, "emulator-5554")
    with pytest.raises(RuntimeError, match="forward_failed"):
        peer.open()
    assert peer.cleanup is True and peer.confirmed_shutdown is False
    assert calls[:2] == [["adb", "-s", "emulator-5554", "uninstall", session.APP],
                         ["adb", "-s", "emulator-5554", "uninstall", session.APP + ".test"]]
    assert calls[-5:] == ["kill", "wait", "join",
                          ("emulator-5554", ("shell", "am", "force-stop", session.APP)),
                          ("emulator-5554", ("shell", "am", "force-stop", session.APP + ".test"))]


@pytest.mark.parametrize("exit_code", [0, 1])
def test_explicit_finish_requires_confirmed_instrumentation_shutdown(monkeypatch, exit_code):
    calls = []

    class Protocol:
        def finish(self): calls.append("finish_frame"); return 4

    class Socket:
        def close(self): calls.append("socket_close")

    class Process:
        def wait(self, timeout): calls.append("process_wait"); return exit_code

    class Reader:
        def join(self, timeout): calls.append("reader_join")
        def is_alive(self): return False

    peer = session.AndroidPublicSession("a" * 40, "emulator-5554")
    peer.identity, peer.artifacts = {"source_commit": "a" * 40}, {}
    peer.protocol, peer.sock, peer.process, peer.reader = Protocol(), Socket(), Process(), Reader()
    peer.observed, peer.overflow = [b"OK (1 test)\n"], threading.Event()
    peer.deadline = time.monotonic() + 5
    monkeypatch.setattr(session, "verified_distribution", lambda expected: (peer.identity, peer.artifacts))
    if exit_code == 0:
        assert peer.finish() == 4 and peer.confirmed_shutdown is True
        assert calls == ["finish_frame", "socket_close", "process_wait", "reader_join"]
    else:
        with pytest.raises(RuntimeError, match="instrumentation_failure"):
            peer.finish()
        assert peer.confirmed_shutdown is False


def test_finish_deadline_cannot_claim_shutdown(monkeypatch):
    class Protocol:
        def finish(self): return 4

    class Socket:
        def close(self): pass

    class Process:
        def wait(self, timeout): raise AssertionError("deadline must be checked first")

    peer = session.AndroidPublicSession("a" * 40, "emulator-5554")
    peer.protocol, peer.sock, peer.process = Protocol(), Socket(), Process()
    peer.deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="session_deadline"):
        peer.finish()
    assert peer.confirmed_shutdown is False


def test_context_exit_without_finish_retires_owned_test(monkeypatch):
    calls = []

    class Process:
        def poll(self): return None
        def kill(self): calls.append("kill")
        def wait(self, timeout): calls.append("wait")

    class Reader:
        def join(self, timeout): calls.append("join")
        def is_alive(self): return False

    peer = session.AndroidPublicSession("a" * 40, "emulator-5554")
    peer.process, peer.reader, peer.owned = Process(), Reader(), True
    monkeypatch.setattr(session, "adb", lambda serial, *args, **kwargs: calls.append((serial, args)))
    peer.__exit__(None, None, None)
    assert peer.cleanup is True and peer.confirmed_shutdown is False
    assert calls == ["kill", "wait", "join",
                     ("emulator-5554", ("shell", "am", "force-stop", session.APP)),
                     ("emulator-5554", ("shell", "am", "force-stop", session.APP + ".test"))]
    with pytest.raises(ValueError, match="public_session_closed"):
        peer.request("runtime.capabilities")


def test_context_exit_surfaces_cleanup_failure_without_replacing_primary_error(monkeypatch):
    peer = session.AndroidPublicSession("a" * 40, "emulator-5554")
    monkeypatch.setattr(peer, "close", lambda: False)
    with pytest.raises(RuntimeError, match="public_session_cleanup_failed"):
        peer.__exit__(None, None, None)
    original = ValueError("primary_request_failure")
    assert peer.__exit__(ValueError, original, None) is None


def test_overall_deadline_rejects_next_phase_without_sending_it():
    client, server = socket.socketpair()
    try:
        server.sendall(session.encode_frame({"id": "auth", "ok": True,
                                              "result": {"authenticated": True}}))
        protocol = session.PublicProtocol(client, "a" * 64, time.monotonic() + 0.01)
        assert session.read_frame(server)["action"] == "authenticate"
        time.sleep(0.02)
        with pytest.raises(TimeoutError, match="session_deadline"):
            protocol.request("runtime.capabilities")
        assert protocol.step == 1
    finally:
        client.close()
        server.close()


def test_standalone_smoke_uses_adapter_and_retains_report_scope(monkeypatch):
    client, server = socket.socketpair()
    calls = []

    class Process:
        exited = False
        def poll(self): return 0 if self.exited else None
        def wait(self, timeout): self.exited = True; return 0

    class Reader:
        def join(self, timeout): pass
        def is_alive(self): return False

    class Port:
        def get(self, timeout): return 37777

    def host():
        try:
            while True:
                frame = session.read_frame(server)
                if frame["action"] == "authenticate":
                    result = {"authenticated": True}
                elif frame["action"] == "finish":
                    result = {"completed": True, "requests": 6}
                elif frame["operation"] == "runtime.capabilities":
                    result = {"operations": [], "profiles": ["p"]}
                elif frame["operation"] == "application.snapshot":
                    result = {"profile": {"id": "p"} if frame["step"] > 3 else None,
                              "contacts": [], "messages": []}
                elif frame["operation"] == "profile.query":
                    result = {"destination": "public-destination"}
                else:
                    assert frame["operation"] == "profile.create"
                    result = {"created": True}
                server.sendall(session.encode_frame({"id": frame["id"], "ok": True, "result": result}))
                if frame["action"] == "finish": break
        finally:
            server.close()

    thread = threading.Thread(target=host)
    thread.start()
    monkeypatch.setattr(session, "verified_distribution", lambda expected:
                        ({"source_commit": expected, "source_tree": "b" * 40}, {"apk": "c" * 64}))
    monkeypatch.setattr(session, "admit_emulator", lambda serial: None)
    monkeypatch.setattr(session.subprocess, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(session, "adb", lambda serial, *args, **kwargs:
                        calls.append((serial, args)) or ("37778" if args[:1] == ("forward",)
                        and args[1:2] != ("--remove",) else "Success"))
    monkeypatch.setattr(session, "instrument", lambda serial, nonce:
                        (Process(), Reader(), Port(), [b"OK (1 test)\n"], threading.Event()))
    monkeypatch.setattr(session.socket, "create_connection", lambda *args, **kwargs: client)
    result = session.run("a" * 40, "emulator-5554")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result["passed"] is True and result["checks"] == list(session.CHECKS)
    assert result["scope"] == session.SCOPE and result["requests"] == 6
    assert result["cleanup"] is True and result["emulator_serial"] == "emulator-5554"
    assert ("emulator-5554", ("forward", "--remove", "tcp:37778")) in calls


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
