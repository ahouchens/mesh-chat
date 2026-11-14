"""Guest failure evidence must survive ADB loss without retaining private logs."""
import io
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))


def observer():
    from native_interop_android_system import AndroidSystemObservation
    return AndroidSystemObservation()


def test_kernel_and_guest_events_survive_socket_and_adb_loss_without_raw_text():
    value = observer()
    value.phase("peer_start")
    value.consume(io.BytesIO(
        b"[ 0.0] Linux version PRIVATE_KERNEL\n"
        b"F/libc (123): Fatal signal 11 (SIGSEGV), code 1 in PRIVATE_THREAD\n"
        b"[ 25.0] Kernel panic - not syncing: PRIVATE_CAUSE\n"
        b"PRIVATE_VAULT_KEY PRIVATE_PATH PRIVATE_MESSAGE\n"))
    result = value.snapshot()
    assert [e["event"] for e in result["events"]] == ["kernel_boot", "native_signal", "kernel_panic"]
    assert all(e["phase"] == "peer_start" for e in result["events"])
    assert result["reader_eof"] is True
    assert "PRIVATE" not in json.dumps(result)


def test_oversized_lines_are_discarded_including_their_tail():
    value = observer()
    value.consume(io.BytesIO(b"x" * 9000 + b"Kernel panic - not syncing: PRIVATE\n"
                             b"[ 1.0] Out of memory: Killed process 123 PRIVATE\n"))
    result = value.snapshot()
    assert [e["event"] for e in result["events"]] == ["kernel_oom"]
    assert result["oversized_lines"] == 1


def test_event_history_is_bounded_and_reports_truncation():
    value = observer()
    value.consume(io.BytesIO(b"F/libc (1): Fatal signal 6 (SIGABRT) PRIVATE\n" * 80))
    result = value.snapshot()
    assert len(result["events"]) == 32 and result["events_dropped"] == 48
    assert result["counts"]["native_signal"] == 80
    assert len(json.dumps(result)) < 8192
    result["events"].clear()
    assert len(value.snapshot()["events"]) == 32


def test_classifier_failure_does_not_stop_draining(monkeypatch):
    import native_interop_android_system as module
    value = observer()
    stream = io.BytesIO(b"one\ntwo\n")
    monkeypatch.setattr(module, "classify", lambda _: (_ for _ in ()).throw(ValueError("PRIVATE")))
    value.consume(stream)
    result = value.snapshot()
    assert stream.tell() == len(stream.getvalue())
    assert result["classifier_failed"] is True and result["reader_eof"] is True
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("phase", ["PRIVATE", [], None])
def test_unrecognized_phase_is_never_retained(phase):
    value = observer()
    value.phase(phase)
    value.consume(io.BytesIO(b"[ 0.0] Linux version PRIVATE\n"))
    assert value.snapshot()["events"][0]["phase"] == "boot"


def test_real_pipe_is_drained_beyond_pipe_capacity_and_retired():
    value = observer()
    child = subprocess.Popen([sys.executable, "-B", "-c",
        "import sys; sys.stdout.buffer.write(b'F/libc: Fatal signal 6 PRIVATE\\n' * 40000)"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        value.start(child.stdout)
        assert child.wait(timeout=20) == 0
        assert value.finish(child.stdout) is True
        result = value.snapshot()
        assert result["reader_eof"] is True and result["counts"]["native_signal"] == 40000
        assert len(result["events"]) == 32 and child.stdout.closed
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=5)
        value.finish(child.stdout)


def test_emulator_reader_start_failure_retires_exact_process_and_pipe(monkeypatch, tmp_path):
    from test_ui_core_boundary_interop_peers import scripted_android, assert_android_cleaned
    import native_interop_android_system as module
    script = scripted_android(monkeypatch, tmp_path)
    error = RuntimeError("PRIVATE_THREAD_START")
    monkeypatch.setattr(module.threading.Thread, "start", lambda _: (_ for _ in ()).throw(error))
    with pytest.raises(RuntimeError) as caught:
        script.emulator.start(script.apks)
    assert caught.value is error
    assert_android_cleaned(script)


def test_emulator_start_preserves_primary_and_separate_failed_cleanup(monkeypatch, tmp_path):
    from test_ui_core_boundary_interop_peers import scripted_android, assert_android_cleaned
    import native_interop_android_system as module
    script = scripted_android(monkeypatch, tmp_path)
    primary = RuntimeError("PRIVATE_START")
    cleanup = OSError("PRIVATE_CLEANUP")
    close = script.emulator.close
    monkeypatch.setattr(module.threading.Thread, "start", lambda _: (_ for _ in ()).throw(primary))
    monkeypatch.setattr(script.emulator, "close", lambda: (_ for _ in ()).throw(cleanup))
    with pytest.raises(RuntimeError) as caught:
        script.emulator.start(script.apks)
    assert caught.value is primary
    assert primary.__cause__ is cleanup
    result = script.emulator.failure_start_observation(primary)
    assert result == {"process": {"state": "running", "exit_status": None},
                      "cleanup_exception_kind": "os_error"}
    assert script.emulator.failure_start_observation(RuntimeError("PRIVATE_START")) is None
    result["process"]["state"] = "PRIVATE_MUTATION"
    assert script.emulator.failure_start_observation(primary)["process"]["state"] == "running"
    assert "PRIVATE" not in json.dumps(script.emulator.failure_start_observation(primary))
    close()
    assert_android_cleaned(script)


def test_emulator_retains_custody_until_console_reader_finishes(monkeypatch, tmp_path):
    from test_ui_core_boundary_interop_peers import scripted_android
    import native_interop_peers as peers
    script = scripted_android(monkeypatch, tmp_path)
    script.emulator.start(script.apks)
    value = script.emulator.observation
    value._thread.join(2)
    running = [True]
    value._thread = SimpleNamespace(ident=1, join=lambda _: None, is_alive=lambda: running[0])
    exact = script.emulator.process
    with pytest.raises(peers.PeerFailure, match="emulator_observer_retirement_failed"):
        script.emulator.close()
    assert script.emulator.process is exact and not exact.stdout.closed
    assert script.emulator.root.exists()
    running[0] = False
    script.emulator.close()
    assert script.emulator.process is None and exact.stdout.closed
    assert not script.emulator.root.exists()


def test_reader_error_is_distinct_from_eof_and_does_not_retain_exception():
    value = observer()
    value.consume(SimpleNamespace(readline=lambda _: (_ for _ in ()).throw(OSError("PRIVATE"))))
    result = value.snapshot()
    assert result["reader_failed"] is True and result["reader_eof"] is False
    assert "PRIVATE" not in json.dumps(result)


def test_counters_saturate_without_stopping_the_reader():
    value = observer()
    stream = io.BytesIO(b"F/libc: Fatal signal 6\n" * 65600)
    value.consume(stream)
    result = value.snapshot()
    assert result["counts"]["native_signal"] == result["events_dropped"] == 65535
    assert stream.tell() == len(stream.getvalue()) and result["reader_eof"]


@pytest.mark.parametrize("change", [{"raw": "PRIVATE"}, {"counts": {}}, {"v": True},
    {"events": [{"event": "PRIVATE", "phase": "boot"}]}, {"events_dropped": True},
    {"counters_saturate_at": 65535.0}])
def test_malformed_snapshot_is_rejected(change):
    from native_interop_android_system import system_snapshot
    value = observer().snapshot()
    assert system_snapshot(value) == value
    assert system_snapshot({**value, **change}) is None


@pytest.mark.parametrize("broken", [False, True])
def test_controller_retains_primary_failure_and_snapshots_before_cleanup(monkeypatch, tmp_path, broken):
    import connection_ci
    import native_interop_controller as controller
    import native_interop_peers as peers
    value = observer()
    value.phase("peer_initialize")
    value.consume(io.BytesIO(b"[ 1.0] Kernel panic - not syncing: PRIVATE\n"))
    if broken:
        monkeypatch.setattr(value, "snapshot", lambda: (_ for _ in ()).throw(ValueError("PRIVATE")))
    emulator = SimpleNamespace(start=lambda *a, **k: None, observation=value,
        close=lambda: value.phase("cleanup"))
    peer = SimpleNamespace(process=None)
    error = peers.PeerFailure("peer_closed")
    # Fail before Controller construction, after assigning the actual observer.
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *a: (_ for _ in ()).throw(error))
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *a: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **k: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: emulator)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *a: peer)
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    result = json.loads(output.read_text())
    assert result["error_code"] == "peer_closed" and result["passed"] is False
    assert "PRIVATE" not in json.dumps(result)
    if broken: assert "android_system_observation" not in result
    else:
        assert result["android_system_observation"]["events"] == [
            {"event": "kernel_panic", "phase": "peer_initialize"}]
