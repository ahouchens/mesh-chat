"""Bounded testhost I/O attribution never changes an Android controller failure."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import native_interop_testhost_io_observation as io
from native_interop_peers import AndroidPeer, PeerFailure
from native_interop_controller import android_control_failure


def line(ordinal, stage, category="none", ms=7, capped=0):
    return f"INSTRUMENTATION_STATUS: mesh_interop_io=v1|{ordinal}|{stage}|{category}|{ms}|{capped}\n".encode()


def test_kotlin_emits_only_the_exact_fixed_status_format_and_snapshot_markers():
    source = (ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime"
              / "PackagedNativeInteropBoundaryTest.kt").read_text(encoding="utf-8")
    assert '"v1|$ordinal|$stage|$category|$elapsed|$capped"' in source
    assert 'rawElapsed.coerceAtMost(120_000L)' in source
    assert 'if (rawElapsed > 120_000L) 1 else 0' in source
    assert source.count('reportIo(ordinal, stage, "none", started)') == 0
    assert 'reportIo(ordinal, stage, category, started)' in source
    for kind, category in (("EOFException", "eof"), ("SocketTimeoutException", "timeout"),
                           ("IOException", "io")):
        assert f'is {kind} -> "{category}"' in source
        assert io.event(line(17, "read_header", category))["category"] == category
    assert '"mesh_interop_start_ordinal"' in source
    assert '"mesh_interop_start_ordinal", str(self._sequence + 1)' in (ROOT / "scripts/native_interop_peers.py").read_text()
    for stage in io.STAGES:
        assert f'"{stage}"' in source
        assert io.event(line(17, stage)) == {"ordinal": 17, "stage": stage, "category": "none",
                                             "elapsed_ms": 7, "elapsed_capped": False}


@pytest.mark.parametrize("invalid", [
    line(0, "read_header"), line(100000000, "read_header"),
    line(1, "unknown"), line(1, "read_body", "private_exception"),
    b"INSTRUMENTATION_STATUS: mesh_interop_io=v1|1|read_header|none|7\nPRIVATE\n",
    line(1, "read_header") + b"x" * 200,
    line(1, "read_header", ms=120001),
])
def test_parser_rejects_unbounded_or_noncanonical_status(invalid):
    assert io.event(invalid) is None


def test_ordinal_window_retains_current_and_one_predecessor_and_late_status_is_frozen():
    status = io.TesthostIoStatus()
    for ordinal in (10, 11, 12):
        status.observe(line(ordinal, "read_header"))
    status.observe(line(12, "snapshot_dispatch_enter"))
    captured = status.matching(12)
    assert [entry["last"]["ordinal"] for entry in captured] == [11, 12]
    assert captured[-1]["snapshot_dispatch_enter"] is True
    status.observe(line(12, "snapshot_flush_complete"))
    assert captured[-1]["snapshot_flush_complete"] is False
    assert status.matching(12)[-1]["snapshot_flush_complete"] is True
    status.observe(line(10, "flush"))
    assert status.matching(12)[-1]["last"]["stage"] == "snapshot_flush_complete"
    assert io.failure_snapshot({"statuses": captured, "forward": "present"}, 12) is not None
    assert io.failure_snapshot({"statuses": captured, "forward": "present"}, 13) is None


def test_failure_snapshot_rejects_oversize_and_bad_shape():
    row = {"last": {"ordinal": 4, "stage": "read_header", "category": "eof", "elapsed_ms": 0,
                    "elapsed_capped": False},
           "snapshot_dispatch_enter": False, "snapshot_flush_complete": False}
    assert io.failure_snapshot({"statuses": [row], "forward": "unknown"}, 4)
    assert io.failure_snapshot({"statuses": [row] * 3, "forward": "unknown"}, 4) is None
    assert io.failure_snapshot({"statuses": [row], "forward": []}, 4) is None
    assert io.failure_snapshot({"statuses": [{**row, "raw": "PRIVATE"}], "forward": "unknown"}, 4) is None
    assert io.snapshot({**row["last"], "elapsed_ms": 120001}) is None
    assert io.snapshot({**row["last"], "elapsed_capped": True}) is None
    assert io.snapshot(io.event(line(4, "read_header", ms=120000, capped=1))) is not None


def test_forward_sample_timeout_is_bounded_and_kills_only_its_process(monkeypatch):
    events = []
    class Reader:
        def read(self, _):
            import time
            time.sleep(3.1)
            return b""
        def close(self): events.append("close")
    class Process:
        stdout = Reader()
        def poll(self): return None
        def kill(self): events.append("kill")
        def wait(self, timeout): events.append("wait"); return 0
    def launch(args, **_):
        assert args == ["adb", "-s", "emulator-5554", "forward", "--list"]
        return Process()
    monkeypatch.setattr(io.subprocess, "Popen", launch)
    assert io.forward_presence("adb", "12345") == "timeout"
    assert events[:2] == ["kill", "wait"]


@pytest.mark.parametrize("output,expected", [
    (b"emulator-5554 tcp:12345 tcp:7890\n", "present"),
    (b"emulator-5554 tcp:99999 tcp:7890\n", "absent"),
    (b"PRIVATE payload\n", "unknown"),
    (b"x" * 2049, "unknown"),
])
def test_forward_sample_retains_only_fixed_presence(monkeypatch, output, expected):
    class Reader:
        def read(self, size): return output[:size]
        def close(self): pass
    class Process:
        stdout = Reader()
        def poll(self): return 0
        def wait(self, timeout): return 0
    monkeypatch.setattr(io.subprocess, "Popen", lambda *a, **k: Process())
    assert io.forward_presence("adb", "12345") == expected


def test_header_eof_keeps_primary_failure_and_captures_forward_label(monkeypatch):
    monkeypatch.setattr("native_interop_peers.forward_presence", lambda *_: "absent")
    peer = AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    peer._testhost_io.observe(line(1, "snapshot_dispatch_enter"))
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    assert caught.value.code == "peer_closed"
    observed = android_control_failure(peer, SimpleNamespace(process=None), caught.value)["android_control_failure"]
    assert observed["transport"]["eof_stage"] == "header"
    assert observed["testhost_io"]["forward"] == "absent"
    assert observed["testhost_io"]["statuses"][0]["snapshot_dispatch_enter"] is True
    peer._testhost_io.observe(line(1, "snapshot_flush_complete"))
    assert observed["testhost_io"]["statuses"][0]["snapshot_flush_complete"] is False
    assert peer.failure_testhost_observation(PeerFailure("peer_closed")) is None


def test_broken_forward_observer_does_not_erase_transport_eof(monkeypatch):
    def broken(*_): raise RuntimeError("PRIVATE_FORWARD_ERROR")
    monkeypatch.setattr("native_interop_peers.forward_presence", broken)
    peer = AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    observed = android_control_failure(peer, SimpleNamespace(process=None), caught.value)["android_control_failure"]
    assert caught.value.code == "peer_closed"
    assert observed["transport"]["eof_stage"] == "header"
    assert "testhost_io" not in observed


def test_status_arriving_during_forward_sample_is_retained(monkeypatch):
    peer = AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    def sample(*_):
        peer._testhost_io.observe(line(1, "snapshot_dispatch_enter"))
        peer._testhost_io.observe(line(1, "snapshot_flush_complete"))
        return "present"
    monkeypatch.setattr("native_interop_peers.forward_presence", sample)
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    observed = peer.failure_testhost_observation(caught.value)
    assert observed["forward"] == "present"
    assert observed["statuses"][0]["snapshot_dispatch_enter"] is True
    assert observed["statuses"][0]["snapshot_flush_complete"] is True
