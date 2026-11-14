"""A boot comparison must retain both outcomes without qualifying messaging."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_emulator_boot_diagnostic as diagnostic


def context(monkeypatch):
    source = "a" * 40
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_JOB": "android_restart_diagnostic", "GITHUB_SHA": source,
        "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic, "binding", lambda _: {"source_commit": source,
        "source_tree": "b" * 40, "source_blobs": {"test": "c" * 40}})
    monkeypatch.setattr(diagnostic, "package_versions", lambda: {"emulator": {"revision": "36.6.11"}})
    return source


def test_launch_matches_actual_current_owner_and_declares_only_old_new_difference(monkeypatch, tmp_path):
    from test_ui_core_boundary_interop_peers import scripted_android, assert_android_cleaned
    import native_interop_peers as peers
    script = scripted_android(monkeypatch, tmp_path)
    launch = peers.subprocess.Popen
    captured = []
    def capture(command, **options):
        captured.append((command, options))
        return launch(command, **options)
    monkeypatch.setattr(peers.subprocess, "Popen", capture)
    script.emulator.start(script.apks)
    assert diagnostic.launch_command(script.emulator, "current_logcat") == captured[0]
    old_command, old_options = diagnostic.launch_command(script.emulator, "baseline_b8")
    assert old_command == captured[0][0][:-2]
    assert "-show-kernel" not in captured[0][0]
    assert captured[0][0][-2:] == ["-logcat", diagnostic.LOG_TAGS]
    assert old_options == {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True}
    script.emulator.close()
    assert_android_cleaned(script)


def test_startup_console_retains_fixed_errors_and_discards_oversized_tail():
    console = diagnostic.BootConsole()
    console.consume(io.BytesIO(b"ERROR | Not enough disk space PRIVATE_PATH\n"
        + b"x" * 9000 + b"unknown option: PRIVATE_OPTION\n"
        b"[0] Linux version PRIVATE_VERSION\nPRIVATE_KEY\n"))
    result = console.snapshot()
    assert result["counts"]["disk_insufficient"] == 1
    assert result["counts"]["unknown_option"] == 0
    assert result["counts"]["kernel_boot"] == 1
    assert result["reader_eof"] is True and result["oversized_lines"] == 1
    assert "PRIVATE" not in json.dumps(result)


def test_completed_control_is_on_disk_before_second_case_is_interrupted(monkeypatch, tmp_path):
    source = context(monkeypatch)
    output = tmp_path / "report.json"
    def run_case(variant, update):
        if variant == "current_logcat":
            update({"variant": variant, "status": "running", "stage": "boot"})
            saved = json.loads(output.read_text())
            assert saved["passed"] is False and saved["status"] == "running"
            assert saved["attempts"][0]["passed"] is True
            raise KeyboardInterrupt()
        result = {"variant": variant, "status": "completed", "passed": True, "cleanup_failures": []}
        update(result)
        return result
    monkeypatch.setattr(diagnostic, "run_case", run_case)
    with pytest.raises(KeyboardInterrupt):
        diagnostic.run(source, output)
    assert json.loads(output.read_text())["attempts"][1]["stage"] == "boot"


def test_uncertain_retirement_fences_next_case_and_keeps_declared_pair(monkeypatch, tmp_path):
    source = context(monkeypatch)
    calls = []
    def run_case(variant, update):
        calls.append(variant)
        result = {"variant": variant, "status": "completed", "passed": False,
                  "cleanup_failures": [{"exception_kind": "OSError"}]}
        update(result)
        return result
    monkeypatch.setattr(diagnostic, "run_case", run_case)
    report = diagnostic.run(source, tmp_path / "report.json")
    assert calls == ["baseline_b8"]
    assert report["attempts"][1] == {"variant": "current_logcat", "status": "not_run",
                                     "reason": "prior_cleanup_unresolved", "passed": False}
    assert not report["passed"]


def test_diagnostic_pass_never_qualifies_native_interop(monkeypatch, tmp_path):
    from native_interop_evidence import verify_report
    source = context(monkeypatch)
    def run_case(variant, update):
        result = {"variant": variant, "status": "completed", "passed": True, "cleanup_failures": []}
        update(result)
        return result
    monkeypatch.setattr(diagnostic, "run_case", run_case)
    report = diagnostic.run(source, tmp_path / "report.json")
    assert report["passed"] and report["diagnostic_only"]
    assert len(report["attempts"]) == 2
    with pytest.raises(ValueError):
        verify_report(report, source, "b" * 40, "android", workload="full")


def test_retirement_waits_for_exact_process_reader_and_then_restores_environment(monkeypatch, tmp_path):
    root = tmp_path / "owned-avd"
    root.mkdir()
    (root / "temporary.img").write_text("synthetic")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("ANDROID_SERIAL", "emulator-5554")
    exits = [None]
    events = []
    process = SimpleNamespace(pid=123, stdout=io.BytesIO(b""), poll=lambda: exits[0],
                              wait=lambda timeout: events.append(("wait", timeout)))
    def adb(*args):
        assert args == ("emu", "kill")
        events.append("kill")
        exits[0] = 0
    emulator = SimpleNamespace(process=process, root=root, name=root.name,
                               old_environment={"ANDROID_SERIAL": "previous"}, _adb=adb)
    stalled = SimpleNamespace(finish=lambda _: (_ for _ in ()).throw(diagnostic.PeerFailure("emulator_observer_retirement_failed")))
    with pytest.raises(diagnostic.PeerFailure):
        diagnostic.retire(emulator, stalled)
    assert emulator.process is process and root.exists() and not process.stdout.closed
    assert events == ["kill", ("wait", 30)]
    diagnostic.retire(emulator, diagnostic.BootConsole())
    assert emulator.process is None and not root.exists() and process.stdout.closed
    assert diagnostic.os.environ["ANDROID_SERIAL"] == "previous"


def test_real_console_pipe_drains_beyond_capacity():
    console = diagnostic.BootConsole()
    process = subprocess.Popen([sys.executable, "-B", "-c",
        "import sys; sys.stdout.buffer.write(b'unknown option: PRIVATE\\n' * 40000)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        console.start(process.stdout)
        assert process.wait(timeout=20) == 0
        console.finish(process.stdout)
        assert console.snapshot()["counts"]["unknown_option"] == 40000
        assert "PRIVATE" not in json.dumps(console.snapshot())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        console.finish(process.stdout)


def test_early_exit_is_captured_before_cleanup_without_losing_primary(monkeypatch):
    process = SimpleNamespace(stdout=io.BytesIO(b"ERROR | Not enough disk space PRIVATE_PATH\n"), poll=lambda: 2)
    emulator = SimpleNamespace(sdk=Path("PRIVATE_SDK"), name="owned", process=None)
    monkeypatch.setattr(diagnostic, "AndroidEmulator", lambda: emulator)
    monkeypatch.setattr(diagnostic, "prepare_avd", lambda _: None)
    monkeypatch.setattr(diagnostic.subprocess, "Popen", lambda *a, **k: process)
    def failed_cleanup(owned, console):
        assert owned.process is process
        console.finish(process.stdout)
        raise OSError("PRIVATE_CLEANUP")
    monkeypatch.setattr(diagnostic, "retire", failed_cleanup)
    checkpoints = []
    result = diagnostic.run_case("current_logcat", lambda value: checkpoints.append(json.loads(json.dumps(value))))
    assert result["primary_failure"] == {"stage": "boot", "exception_kind": "PeerFailure",
                                         "error_code": "emulator_exited_during_boot"}
    assert result["process_before_cleanup"] == {"state": "exited", "exit_status": 2}
    assert result["cleanup_failures"] == [{"exception_kind": "OSError"}]
    assert result["console"]["counts"]["disk_insufficient"] == 1
    assert not result["passed"] and checkpoints[-1]["status"] == "completed"
    assert "PRIVATE" not in json.dumps(result)


def test_retirement_waits_for_owned_adb_listing_before_releasing_avd(monkeypatch, tmp_path):
    root = tmp_path / "owned-avd"
    root.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    emulator = SimpleNamespace(sdk=tmp_path / "sdk", name=root.name, root=root, serial="emulator-5554",
        old_environment={}, _transport_owned=True,
        process=SimpleNamespace(stdout=None, poll=lambda: 0))
    replies = iter(["List of devices attached\nemulator-5554\toffline\n"] * 2 + ["List of devices attached\n"])
    calls = []
    def devices(argv, **options):
        assert argv == [str(emulator.sdk / "platform-tools/adb"), "devices"]
        calls.append(argv)
        assert root.exists()
        return next(replies)
    monkeypatch.setattr(diagnostic.subprocess, "check_output", devices)
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _: None)
    diagnostic.retire(emulator, diagnostic.BootConsole())
    assert len(calls) == 3 and emulator._transport_owned is False
    assert emulator.process is None and not root.exists()


@pytest.mark.parametrize("foreign", [False, True])
def test_retirement_keeps_avd_when_transport_is_unresolved_or_foreign(monkeypatch, tmp_path, foreign):
    root = tmp_path / "owned-avd"
    root.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    emulator = SimpleNamespace(sdk=tmp_path / "sdk", name=root.name, root=root, serial="emulator-5554",
        old_environment={}, _transport_owned=True,
        process=SimpleNamespace(stdout=None, poll=lambda: 0))
    monkeypatch.setattr(diagnostic.subprocess, "check_output", lambda *a, **k:
        "List of devices attached\n" + ("unrelated-device\tdevice\n" if foreign else "emulator-5554\toffline\n"))
    now = [0]
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(diagnostic.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    with pytest.raises(diagnostic.PeerFailure, match="unowned_android_device_present" if foreign else "emulator_transport_retirement_failed"):
        diagnostic.retire(emulator, diagnostic.BootConsole())
    assert root.exists() and emulator._transport_owned
    assert now[0] <= 30
