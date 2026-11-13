"""Failure-only Android controller observations contain no host output or payloads."""

from io import BytesIO
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_peers as peers
from native_interop_android_observation import (
    InstrumentationStatus, android_transport_snapshot, process_observation,
)


class Socket:
    def __init__(self, reply):
        self.reply = BytesIO(reply)
        self.requests = 0
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, value):
        self.requests += 1
        assert peers.receive(BytesIO(value).read)["action"] == "core"

    def recv(self, count):
        return self.reply.read(min(count, 2))


@pytest.mark.parametrize("reply,stage,received,reads", [
    (b"\x00\x01", "header", 2, 2),
    (b"\x00\x00\x00\x06{}", "body", 6, 4),
])
def test_exact_android_eof_records_only_bounded_frame_progress(reply, stage, received, reads):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = Socket(reply)
    peer.process = type("Process", (), {"poll": lambda self: None})()
    with pytest.raises(peers.PeerFailure, match="peer_closed") as caught:
        peer.core("application.snapshot")
    value = peer.failure_transport_observation(caught.value)
    assert value == {"v": 1, "action": "core", "operation": "application.snapshot",
                     "eof_stage": stage, "received_bytes": received, "received_bytes_capped": False,
                     "read_calls": reads, "read_calls_capped": False,
                     "process": {"state": "running", "exit_status": None},
                     "instrumentation": {"reader_eof": False, "code": None, "marker": None}}
    assert peer.socket.requests == 1
    assert peer.failure_transport_observation(peers.PeerFailure("peer_closed")) is None


def test_successful_request_clears_exact_prior_failure():
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = Socket(b"")
    with pytest.raises(peers.PeerFailure) as caught:
        peer.core("message.query")
    assert peer.failure_transport_observation(caught.value)["operation"] == "message.query"
    peer.socket = Socket(peers.encode({"id": "qualification:2", "ok": True, "result": {}}))
    assert peer.core("message.query") == {}
    assert peer.failure_transport_observation(caught.value) is None


def test_eof_progress_is_capped_without_retaining_response_bytes():
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = Socket((70000).to_bytes(4, "big") + b"x" * 65537)
    with pytest.raises(peers.PeerFailure, match="peer_closed") as caught:
        peer.core("application.snapshot")
    value = peer.failure_transport_observation(caught.value)
    assert value["eof_stage"] == "body"
    assert value["received_bytes"] == 65536 and value["received_bytes_capped"] is True
    assert value["read_calls"] == 64 and value["read_calls_capped"] is True
    assert "xxxx" not in str(value)


def test_non_eof_error_and_observer_failure_preserve_primary_error(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = Socket(b"\x00\x00\x00\x01")
    with pytest.raises(peers.PeerFailure, match="peer_frame_budget") as caught:
        peer.core("application.snapshot")
    assert peer.failure_transport_observation(caught.value) is None
    peer.socket = Socket(b"")
    monkeypatch.setattr(peers, "process_observation", lambda _: (_ for _ in ()).throw(RuntimeError("secret")))
    with pytest.raises(peers.PeerFailure, match="peer_closed") as eof:
        peer.core("application.snapshot")
    assert peer.failure_transport_observation(eof.value) is None
    def broken_observer(*_):
        raise RuntimeError("PRIVATE")
    with pytest.raises(peers.PeerFailure, match="peer_closed"):
        peers.receive(BytesIO(b"").read, on_eof=broken_observer)


def test_process_and_stdout_projection_reject_untrusted_values():
    assert process_observation(None) == {"state": "absent", "exit_status": None}
    assert process_observation(type("Running", (), {"poll": lambda self: None})()) == {
        "state": "running", "exit_status": None}
    assert process_observation(type("Exited", (), {"poll": lambda self: -9})()) == {
        "state": "exited", "exit_status": -9}
    for value in (True, 999999, "PRIVATE_STATUS"):
        assert process_observation(type("Bad", (), {"poll": lambda self, v=value: v})()) == {
            "state": "unknown", "exit_status": None}
    status = InstrumentationStatus()
    for line in (b"INSTRUMENTATION_CODE: 99\n", b"INSTRUMENTATION_CODE: PRIVATE\n",
                 b"PRIVATE_SIGNED_SDP", b"INSTRUMENTATION_RESULT: shortMsg=PRIVATE\n"):
        status.observe(line)
    assert status.snapshot() == {"reader_eof": False, "code": None, "marker": "error"}
    status.observe(b"INSTRUMENTATION_CODE: -1\n")
    status.ended()
    assert status.snapshot() == {"reader_eof": True, "code": "-1", "marker": "error"}
    status.observe(b"INSTRUMENTATION_RESULT: shortMsg=Process crashed.\n")
    assert status.snapshot()["marker"] == "process_crash"
    status.observe(b"INSTRUMENTATION_STATUS: Error=PRIVATE\n")
    assert status.snapshot()["marker"] == "process_crash"


def test_transport_projection_rejects_extra_or_malformed_fields():
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = Socket(b"")
    with pytest.raises(peers.PeerFailure) as caught:
        peer.core("application.snapshot")
    valid = peer.failure_transport_observation(caught.value)
    assert valid is not None
    for mutation in ({"secret": "PRIVATE"}, {"eof_stage": ["header"]},
                     {"received_bytes": True}, {"process": {"state": "exited", "exit_status": "PRIVATE"}},
                     {"process": {"state": "running", "exit_status": "PRIVATE_RAW"}},
                     {"process": {"state": "unknown", "exit_status": True}},
                     {"process": {"state": "absent", "exit_status": 0}},
                     {"received_bytes": 4}, {"read_calls": 5}, {"received_bytes_capped": True},
                     {"read_calls_capped": True},
                     {"instrumentation": {"reader_eof": False, "code": "PRIVATE", "marker": None}}):
        assert android_transport_snapshot({**valid, **mutation}) is None


def test_existing_request_timeout_does_not_become_eof_evidence():
    peer = peers.AndroidPeer(b"k" * 32)
    class Timed(Socket):
        def recv(self, count):
            raise TimeoutError()
    peer.socket = Timed(b"")
    with pytest.raises(peers.PeerFailure, match="peer_deadline") as caught:
        peer.core("application.snapshot")
    assert peer.failure_transport_observation(caught.value) is None
    assert peer.socket.requests == 1
    assert peer.socket.timeouts and all(0 < value <= 60 for value in peer.socket.timeouts)


def test_optional_status_constructor_failure_keeps_android_port_and_requests(monkeypatch):
    def unavailable_status():
        raise RuntimeError("PRIVATE")
    monkeypatch.setattr(peers, "InstrumentationStatus", unavailable_status)
    peer = peers.AndroidPeer(b"k" * 32)
    assert peer._instrumentation_status is None
    class Process:
        stdout = BytesIO(b"INSTRUMENTATION_STATUS: mesh_interop_port=12345\n")
        def poll(self): return None
    process = Process()
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(peer, "_adb", lambda *args: "45678")
    response = b"".join(peers.encode({"id": f"qualification:{index}", "ok": True,
                                      "result": {}}) for index in range(1, 4))
    class StartSocket(Socket):
        def sendall(self, value):
            self.requests += 1
            assert peers.receive(BytesIO(value).read)["action"] in {"authenticate", "initialize", "inspect"}
    connection = StartSocket(response)
    monkeypatch.setattr(peers.socket, "create_connection", lambda *args, **kwargs: connection)
    assert peer.start() == {}
    assert connection.requests == 3
    assert peer._instrumentation_status is None
