"""Bounded testhost I/O attribution never changes an Android controller failure."""

from pathlib import Path
from io import BytesIO
import queue
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import native_interop_testhost_io_observation as io
import native_interop_peers as peers
from native_interop_peers import AndroidPeer, PeerFailure
from native_interop_controller import android_control_failure


def line(ordinal, stage, category="none", ms=7, capped=0):
    return f"INSTRUMENTATION_STATUS: mesh_interop_io=v1|{ordinal}|{stage}|{category}|{ms}|{capped}\n".encode()


def presence(device="device", forward="present", app_process="one"):
    return {"device": device, "forward": forward, "app_process": app_process}


def test_kotlin_emits_only_the_exact_fixed_status_format_and_request_markers():
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
    assert 'reportIo(ordinal, "initialize_dispatch_enter", "none", started)' in source
    assert 'reportIo(ordinal, "initialize_return", "none", started)' in source
    assert 'if (initializeRequest) reportIo(ordinal, "initialize_flush_complete", "none", started)' in source
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
    assert io.failure_snapshot({"statuses": captured, **presence()}, 12) is not None
    assert io.failure_snapshot({"statuses": captured, **presence()}, 13) is None


def test_failure_snapshot_rejects_oversize_and_bad_shape():
    row = {"last": {"ordinal": 4, "stage": "read_header", "category": "eof", "elapsed_ms": 0,
                    "elapsed_capped": False},
           **dict.fromkeys(io.MILESTONES, False)}
    unknown = presence("unknown", "unknown", "unknown")
    assert io.failure_snapshot({"statuses": [row], **unknown}, 4)
    assert io.failure_snapshot({"statuses": [row] * 3, **unknown}, 4) is None
    assert io.failure_snapshot({"statuses": [row], **presence(forward=[])}, 4) is None
    assert io.failure_snapshot({"statuses": [row], **presence(device=[])}, 4) is None
    assert io.failure_snapshot({"statuses": [row], **presence(app_process=[])}, 4) is None
    assert io.failure_snapshot({"statuses": [{**row, "raw": "PRIVATE"}], **unknown}, 4) is None
    assert io.snapshot({**row["last"], "elapsed_ms": 120001}) is None
    assert io.snapshot({**row["last"], "elapsed_capped": True}) is None
    assert io.snapshot(io.event(line(4, "read_header", ms=120000, capped=1))) is not None


def test_initialize_milestones_are_bounded_and_ordered():
    status = io.TesthostIoStatus()
    status.observe(line(2, "initialize_dispatch_enter"))
    before = status.matching(2)
    assert before[0]["initialize_dispatch_enter"] is True
    assert before[0]["initialize_return"] is False
    status.observe(line(2, "initialize_return"))
    status.observe(line(2, "initialize_flush_complete"))
    after = status.matching(2)
    assert after[0]["initialize_flush_complete"] is True
    assert io.failure_snapshot({"statuses": after, **presence()}, 2) is not None
    assert io.failure_snapshot({"statuses": [{**after[0], "initialize_dispatch_enter": False}],
                                **presence()}, 2) is None
    assert io.failure_snapshot({"statuses": [{**after[0], "initialize_return": False}],
                                **presence()}, 2) is None
    assert io.event(line(2, "initialize_return", "PRIVATE")) is None


def subprocess_adb(monkeypatch, replies):
    """Run each pinned probe against a real short-lived child process."""
    launch = subprocess.Popen
    expected = [
        ["adb", "-s", "emulator-5554", "get-state"],
        ["adb", "-s", "emulator-5554", "forward", "--list"],
        ["adb", "-s", "emulator-5554", "shell",
         f"pidof {AndroidPeer.APP}; echo MESH_PIDOF_EXIT:$?"],
    ]
    calls = []
    children = []
    def fake(args, **kwargs):
        assert args == expected[len(calls)]
        data, code, delay = replies[len(calls)]
        calls.append(args)
        script = f"import sys,time;time.sleep({delay});sys.stdout.buffer.write({data!r});sys.exit({code})"
        child = launch([sys.executable, "-c", script], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(io.subprocess, "Popen", fake)
    return calls, children


@pytest.mark.parametrize("replies,expected", [
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, 0),
      (b"123\nMESH_PIDOF_EXIT:0\n", 0, 0)],
     presence()),
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:99999 tcp:7890\n\n", 0, 0),
      (b"123\nMESH_PIDOF_EXIT:0\n", 0, 0)],
     presence(forward="absent")),
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, 0),
      (b"MESH_PIDOF_EXIT:1\n", 0, 0)],
     presence(app_process="absent")),
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, 0),
      (b"123 456\nMESH_PIDOF_EXIT:0\n", 0, 0)],
     presence(app_process="multiple")),
    ([(b"device\n", 0, 0), (b"\n", 0, 0), (b"123\nMESH_PIDOF_EXIT:0\n", 0, 0)],
     presence(forward="absent")),
    ([(b"offline\n", 0, 0), (b"", 1, 0), (b"", 1, 0)],
     presence("offline", "unknown", "unknown")),
    ([(b"", 1, 0), (b"", 1, 0), (b"", 1, 0)],
     presence("unknown", "unknown", "unknown")),
    ([(b"x" * 65, 0, 0), (b"", 1, 0), (b"", 1, 0)],
     presence("unknown", "unknown", "unknown")),
    ([(b"device\n", 0, 0), (b"x" * 2049, 0, 0), (b"PRIVATE\n", 0, 0)],
     presence(forward="unknown", app_process="unknown")),
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, 0), (b"x" * 129, 0, 0)],
     presence(app_process="unknown")),
    ([(b"device\n", 0, 0), (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, 0), (b"", 1, 0)],
     presence(app_process="unknown")),
])
def test_real_subprocess_categorizes_three_causal_outcomes(monkeypatch, replies, expected):
    calls, children = subprocess_adb(monkeypatch, replies)
    assert io.control_path_presence("adb", "12345", AndroidPeer.APP) == expected
    assert len(calls) == 3
    assert all(child.poll() is not None for child in children)


def test_real_subprocess_timeout_shares_budget_and_retires_child(monkeypatch):
    calls, children = subprocess_adb(monkeypatch, [(b"device\n", 0, 1)])
    started = time.monotonic()
    observed = io.control_path_presence("adb", "12345", AndroidPeer.APP, budget=.75)
    assert time.monotonic() - started < 1
    assert observed == presence("timeout", "timeout", "timeout")
    assert len(calls) == 1
    assert children[0].poll() is not None


def test_default_cap_includes_delayed_reader_and_child_retirement(monkeypatch):
    calls, children = subprocess_adb(monkeypatch, [(b"device\n", 0, 10)])
    started = time.monotonic()
    observed = io.control_path_presence("adb", "12345", AndroidPeer.APP)
    assert time.monotonic() - started < 3.5
    assert observed == presence("timeout", "timeout", "timeout")
    assert len(calls) == 1
    assert children[0].poll() is not None


def test_real_delayed_children_share_one_deadline(monkeypatch):
    replies = [
        (b"device\n", 0, .2),
        (b"emulator-5554 tcp:12345 tcp:7890\n\n", 0, .2),
        (b"123\nMESH_PIDOF_EXIT:0\n", 0, 2),
    ]
    calls, children = subprocess_adb(monkeypatch, replies)
    started = time.monotonic()
    observed = io.control_path_presence("adb", "12345", AndroidPeer.APP, budget=1.5)
    assert time.monotonic() - started < 1.8
    assert observed == presence(app_process="timeout")
    assert len(calls) == 3
    assert all(child.poll() is not None for child in children)


@pytest.mark.parametrize("output", [
    b"emulator-5554 tcp:12345 tcp:7890\n",
    b"emulator-5554 tcp:12345 tcp:7890\n\n\n",
    b"emulator-5554 tcp:12345 tcp:7890\n\nPRIVATE\n",
])
def test_forward_parser_rejects_noncanonical_padding(output):
    assert io._forward_label(output, 0, None, "12345") == "unknown"


@pytest.mark.parametrize("output,expected", [
    (b"MESH_PIDOF_EXIT:1\n", "absent"),
    (b"", "unknown"),
    (b"MESH_PIDOF_EXIT:127\n", "unknown"),
    (b"123\nMESH_PIDOF_EXIT:1\n", "unknown"),
    (b"PRIVATE\nMESH_PIDOF_EXIT:1\n", "unknown"),
])
def test_app_absence_requires_exact_remote_completion(output, expected):
    assert io._process_label(output, 0, None, "device") == expected
    assert io._process_label(output, 1, None, "device") == "unknown"


def test_header_eof_keeps_primary_failure_and_captures_presence(monkeypatch):
    monkeypatch.setattr("native_interop_peers.control_path_presence", lambda *_: presence(forward="absent"))
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
    assert observed["testhost_io"]["device"] == "device"
    assert observed["testhost_io"]["app_process"] == "one"
    assert observed["testhost_io"]["statuses"][0]["snapshot_dispatch_enter"] is True
    peer._testhost_io.observe(line(1, "snapshot_flush_complete"))
    assert observed["testhost_io"]["statuses"][0]["snapshot_flush_complete"] is False
    assert peer.failure_testhost_observation(PeerFailure("peer_closed")) is None


def test_broken_presence_observer_does_not_erase_transport_eof(monkeypatch):
    def broken(*_): raise RuntimeError("PRIVATE_FORWARD_ERROR")
    monkeypatch.setattr("native_interop_peers.control_path_presence", broken)
    peer = AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    peer.system_observation = SimpleNamespace(snapshot=lambda: {"private": "PRIVATE"})
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    observed = android_control_failure(peer, SimpleNamespace(process=None), caught.value)["android_control_failure"]
    assert caught.value.code == "peer_closed"
    assert observed["transport"]["eof_stage"] == "header"
    assert observed["testhost_io"]["device"] == "unknown"
    assert observed["testhost_io"]["forward"] == "unknown"
    assert observed["testhost_io"]["app_process"] == "unknown"
    assert observed["testhost_io"]["pre_probe"]["emulator_system"] is None
    assert "PRIVATE" not in str(observed)


def test_status_arriving_during_presence_sample_is_retained(monkeypatch):
    peer = AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    def sample(*_):
        peer._testhost_io.observe(line(1, "snapshot_dispatch_enter"))
        peer._testhost_io.observe(line(1, "snapshot_flush_complete"))
        return presence()
    monkeypatch.setattr("native_interop_peers.control_path_presence", sample)
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    observed = peer.failure_testhost_observation(caught.value)
    assert observed["forward"] == "present"
    assert observed["statuses"][0]["snapshot_dispatch_enter"] is True
    assert observed["statuses"][0]["snapshot_flush_complete"] is True


def test_initialize_eof_preserves_owned_state_before_probe_changes_it(monkeypatch):
    from native_interop_android_system import AndroidSystemObservation

    peer = AndroidPeer(b"k" * 32)
    peer.forward = "12345"
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b"")
    states = {"client": None, "server": None, "emulator": None}
    peer.process = SimpleNamespace(poll=lambda: states["client"])
    peer.adb_server_process = SimpleNamespace(poll=lambda: states["server"])
    peer.emulator_process = SimpleNamespace(poll=lambda: states["emulator"])
    peer._reader = SimpleNamespace(is_alive=lambda: True)
    peer.system_observation = AndroidSystemObservation()
    peer._testhost_io.observe(line(1, "initialize_dispatch_enter"))

    def sample(*_):
        states.update(client=255, server=1, emulator=1)
        peer._testhost_io.observe(line(1, "initialize_return"))
        peer._testhost_io.observe(line(1, "initialize_flush_complete"))
        peer.system_observation.consume(BytesIO(b"Kernel panic - not syncing: PRIVATE\n"))
        return presence("offline", "unknown", "unknown")

    monkeypatch.setattr("native_interop_peers.control_path_presence", sample)
    with pytest.raises(PeerFailure, match="peer_closed") as caught:
        peer._request("initialize", {})
    observed = peer.failure_testhost_observation(caught.value)
    assert observed["device"] == "offline"
    assert observed["statuses"][0]["initialize_flush_complete"] is True
    pre = observed["pre_probe"]
    assert pre["instrumentation_process"] == {"state": "running", "exit_status": None}
    assert pre["adb_server_process"] == {"state": "running", "exit_status": None}
    assert pre["emulator_process"] == {"state": "running", "exit_status": None}
    assert pre["instrumentation_reader"] == "alive"
    assert pre["emulator_system"]["counts"]["kernel_panic"] == 0
    assert pre["statuses"][0]["initialize_dispatch_enter"] is True
    assert pre["statuses"][0]["initialize_return"] is False
    assert peer.failure_transport_observation(caught.value)["process"] == {
        "state": "exited", "exit_status": 255}
    assert peer.system_observation.snapshot()["counts"]["kernel_panic"] == 1
    assert io.failure_snapshot({**observed, "pre_probe": {**pre, "private": "PRIVATE"}}, 1) is None
    assert io.failure_snapshot({**observed, "pre_probe": {
        **pre, "adb_server_process": {"state": "exited", "exit_status": True}}}, 1) is None


def test_reader_keeps_the_observation_owned_by_its_instrumentation_process(monkeypatch):
    class Stream:
        def __init__(self):
            self.lines = queue.Queue()

        def readline(self, _limit):
            return self.lines.get(timeout=5)

    stream = Stream()
    stream.lines.put(b"INSTRUMENTATION_STATUS: mesh_interop_port=12345\n")
    process = SimpleNamespace(stdout=stream, poll=lambda: None)
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(peers.socket, "create_connection", lambda *a, **k: object())
    peer = AndroidPeer(b"k" * 32)
    monkeypatch.setattr(peer, "_adb", lambda *a: "4567")
    monkeypatch.setattr(peer, "_request", lambda *a, **k: {})
    monkeypatch.setattr(peer, "inventory", lambda: {})
    monkeypatch.setattr(peer, "_initial_binding", lambda _: None)
    assert peer.start() == {}
    original = peer._testhost_io
    peer._testhost_io = io.TesthostIoStatus()
    stream.lines.put(line(1, "initialize_dispatch_enter"))
    stream.lines.put(b"")
    peer._reader.join(timeout=2)
    assert not peer._reader.is_alive()
    assert original.matching(1)[0]["initialize_dispatch_enter"] is True
    assert peer._testhost_io.matching(1) == []
