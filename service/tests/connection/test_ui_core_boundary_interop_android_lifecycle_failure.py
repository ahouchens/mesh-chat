"""Failure-only attribution of the Android peer's existing ADB lifecycle calls."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_android_observation as observation
import native_interop_peers as peers


@pytest.mark.parametrize("arguments,site", [
    (("forward", "tcp:0", "tcp:4321"), "forward_add"),
    (("shell", "am", "force-stop", peers.AndroidPeer.APP), "force_stop"),
    (("forward", "--remove", "tcp:12345"), "forward_remove"),
])
def test_lifecycle_adb_failure_records_exact_site_without_changing_command(
        monkeypatch, arguments, site):
    peer = peers.AndroidPeer(b"k" * 32)
    process = SimpleNamespace(code=None)
    process.poll = lambda: process.code
    peer.process = process
    peer._instrumentation_status.observe(b"INSTRUMENTATION_RESULT: shortMsg=Process crashed.\n")
    error = subprocess.CalledProcessError(17, ["PRIVATE_COMMAND"],
        output=b"PRIVATE_OUTPUT", stderr=b"PRIVATE_STDERR")
    calls = []

    def check_output(argv, **kwargs):
        calls.append((argv, kwargs))
        raise error

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer._adb(*arguments)
    assert caught.value is error
    assert calls == [([peer.adb, *arguments], {"stderr": subprocess.PIPE, "timeout": 30})]
    observation = peer.failure_lifecycle_observation(error)
    assert observation == {"v": 1, "site": site, "exit_status": 17, "stderr_category": "other",
        "instrumentation_process": {"state": "running", "exit_status": None},
        "instrumentation": {"reader_eof": False, "code": None, "marker": "process_crash"}}
    process.code = 0
    peer._instrumentation_status.ended()
    assert peer.failure_lifecycle_observation(error) == observation
    assert peer.failure_lifecycle_observation(subprocess.CalledProcessError(17, ["PRIVATE_COMMAND"])) is None
    assert "PRIVATE" not in json.dumps(observation)


def test_cleanup_adb_failure_replaces_earlier_error_without_false_attribution(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.forward = "12345"
    peer.process = SimpleNamespace(poll=lambda: None)
    first = subprocess.CalledProcessError(9, ["PRIVATE_FORCE_STOP"])
    cleanup = subprocess.CalledProcessError(11, ["PRIVATE_FORWARD_REMOVE"])
    calls = []

    def check_output(argv, **kwargs):
        calls.append(argv[1:])
        raise first if argv[1] == "shell" else cleanup

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer.stop(crash=True)
    assert caught.value is cleanup
    assert calls == [["shell", "am", "force-stop", peer.APP],
                     ["forward", "--remove", "tcp:12345"]]
    assert peer.failure_lifecycle_observation(first) is None
    assert peer.failure_lifecycle_observation(cleanup)["site"] == "forward_remove"


def test_force_stop_failure_survives_successful_forward_cleanup(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.forward = "12345"
    events = []
    peer.process = SimpleNamespace(poll=lambda: None, kill=lambda: events.append("kill"),
        wait=lambda timeout: events.append(("wait", timeout)),
        stdout=SimpleNamespace(close=lambda: events.append("stdout_close")))
    failure = subprocess.CalledProcessError(13, ["PRIVATE_FORCE_STOP"])
    calls = []

    def check_output(argv, **kwargs):
        calls.append(argv[1:])
        if argv[1] == "shell":
            raise failure
        return b""

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer.stop(crash=True)
    assert caught.value is failure
    assert calls == [["shell", "am", "force-stop", peer.APP],
                     ["forward", "--remove", "tcp:12345"]]
    assert events == ["kill", ("wait", 10), "stdout_close"]
    assert peer.failure_lifecycle_observation(failure)["site"] == "force_stop"
    assert peer.process is None


def test_lifecycle_report_uses_precleanup_emulator_state_and_no_private_text(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: -9)
    emulator_state = SimpleNamespace(code=None)
    emulator = SimpleNamespace(process=SimpleNamespace(poll=lambda: emulator_state.code))
    error = subprocess.CalledProcessError(7, ["PRIVATE_COMMAND"], stderr=b"PRIVATE_STDERR")
    monkeypatch.setattr(peers.subprocess, "check_output", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(subprocess.CalledProcessError):
        peer._adb("shell", "am", "force-stop", peer.APP)
    projected = controller.android_lifecycle_failure(peer, emulator, error)
    assert projected == {"android_lifecycle_failure": {
        "site": "force_stop", "exit_status": 7, "stderr_category": "other",
        "instrumentation_process": {"state": "exited", "exit_status": -9},
        "instrumentation": {"reader_eof": False, "code": None, "marker": None},
        "emulator_process": {"state": "running", "exit_status": None},
        "cleanup_failure_sites": []}}
    emulator_state.code = 0
    assert projected["android_lifecycle_failure"]["emulator_process"] == {"state": "running", "exit_status": None}
    assert "PRIVATE" not in json.dumps(projected)


@pytest.mark.parametrize("observer", [
    lambda error: {"site": "PRIVATE_SITE"},
    lambda error: {"v": 1, "site": "force_stop", "exit_status": "PRIVATE_STATUS"},
    lambda error: {"raw": "PRIVATE_PAYLOAD"},
    lambda error: (_ for _ in ()).throw(RuntimeError("PRIVATE_OBSERVER")),
])
def test_malformed_or_throwing_lifecycle_projection_is_omitted(observer):
    peer = peers.AndroidPeer(b"k" * 32)
    peer.failure_lifecycle_observation = observer
    error = subprocess.CalledProcessError(1, ["PRIVATE_COMMAND"])
    emulator = SimpleNamespace(process=None)
    assert controller.android_lifecycle_failure(peer, emulator, error) == {}


def test_lifecycle_projection_is_omitted_for_stale_error():
    peer = peers.AndroidPeer(b"k" * 32)
    error = subprocess.CalledProcessError(1, ["PRIVATE_COMMAND"])
    emulator = SimpleNamespace(process=None)
    assert controller.android_lifecycle_failure(peer, emulator, error) == {}


def test_throwing_observation_construction_cannot_replace_adb_error(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    error = subprocess.CalledProcessError(3, ["PRIVATE_COMMAND"])
    calls = []

    def check_output(argv, **kwargs):
        calls.append(argv)
        raise error

    def broken(_):
        raise RuntimeError("PRIVATE_OBSERVER")

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    monkeypatch.setattr(peers, "android_lifecycle_snapshot", broken)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer._adb("shell", "am", "force-stop", peer.APP)
    assert caught.value is error
    assert calls == [[peer.adb, "shell", "am", "force-stop", peer.APP]]
    assert peer.failure_lifecycle_observation(error) is None


def test_throwing_projection_cannot_change_attributed_error(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    error = subprocess.CalledProcessError(3, ["PRIVATE_COMMAND"])
    peer.failure_lifecycle_observation = lambda _: {"v": 1}
    monkeypatch.setattr(observation, "android_lifecycle_snapshot",
        lambda _: (_ for _ in ()).throw(RuntimeError("PRIVATE_PROJECTION")))
    assert controller.android_lifecycle_failure(peer, SimpleNamespace(process=None), error) == {}


def test_forward_failure_keeps_existing_start_wrapper_and_cleanup_order(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    error = subprocess.CalledProcessError(4, ["PRIVATE_FORWARD"])
    calls = []

    class Output:
        lines = [b"INSTRUMENTATION_STATUS: mesh_interop_port=1234\n", b""]

        def readline(self, size):
            return self.lines.pop(0)

        def close(self):
            pass

    process = SimpleNamespace(stdout=Output(), poll=lambda: 0, wait=lambda timeout: 0)
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *args, **kwargs: process)

    def check_output(argv, **kwargs):
        calls.append(argv[1:])
        if argv[1] == "forward":
            raise error
        return b""

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    with pytest.raises(peers.PeerFailure, match="android_host_start_failed") as caught:
        peer.start()
    assert type(caught.value) is peers.PeerFailure
    assert calls == [["forward", "tcp:0", "tcp:1234"],
                     ["shell", "am", "force-stop", peer.APP]]
    assert peer.failure_lifecycle_observation(caught.value) is None
    assert peer.process is None


def test_start_cleanup_failure_keeps_primary_forward_error(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    forward = subprocess.CalledProcessError(4, ["PRIVATE_FORWARD"])
    cleanup = subprocess.CalledProcessError(8, ["PRIVATE_FORCE_STOP"])
    calls = []

    class Output:
        lines = [b"INSTRUMENTATION_STATUS: mesh_interop_port=1234\n", b""]

        def readline(self, size):
            return self.lines.pop(0)

        def close(self):
            pass

    process = SimpleNamespace(stdout=Output(), poll=lambda: 0, wait=lambda timeout: 0)
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *args, **kwargs: process)

    def check_output(argv, **kwargs):
        calls.append(argv[1:])
        raise forward if argv[1] == "forward" else cleanup

    monkeypatch.setattr(peers.subprocess, "check_output", check_output)
    with pytest.raises(peers.PeerFailure, match="android_host_start_failed") as caught:
        peer.start()
    assert calls == [["forward", "tcp:0", "tcp:1234"],
                     ["shell", "am", "force-stop", peer.APP]]
    observed = peer.failure_start_observation(caught.value)
    assert observed["stage"] == "forward"
    assert observed["exception_kind"] == "called_process_error"
    assert observed["initial_lifecycle"]["site"] == "forward_add"
    assert observed["rollback_lifecycle"]["site"] == "force_stop"
    assert peer.failure_start_observation(peers.PeerFailure("android_host_start_failed")) is None
    assert peer.failure_lifecycle_observation(cleanup)["site"] == "force_stop"
    assert peer.failure_lifecycle_observation(cleanup)["stop_origin"] == "start_rollback"
    assert peer.failure_lifecycle_observation(cleanup)["masked_start_kind"] == "called_process_error"
    assert peer.process is None


@pytest.mark.parametrize("status", [0, 256, -65, True, "PRIVATE_STATUS"])
def test_unbounded_or_malformed_exit_status_is_not_retained(monkeypatch, status):
    peer = peers.AndroidPeer(b"k" * 32)
    error = subprocess.CalledProcessError(status, ["PRIVATE_COMMAND"])
    monkeypatch.setattr(peers.subprocess, "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer._adb("shell", "am", "force-stop", peer.APP)
    assert caught.value is error
    assert peer.failure_lifecycle_observation(error)["exit_status"] is None


@pytest.mark.parametrize("peer_cleanup,emulator_cleanup,projection_throws", [
    (False, False, False), (True, True, False), (False, False, True),
])
def test_main_reports_same_error_before_cleanup_and_retains_cleanup_labels(
        tmp_path, monkeypatch, peer_cleanup, emulator_cleanup, projection_throws):
    import connection_ci

    events = []
    peer = peers.AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: None)
    error = subprocess.CalledProcessError(19, ["PRIVATE_COMMAND"], stderr=b"PRIVATE_STDERR")
    monkeypatch.setattr(peers.subprocess, "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer._adb("forward", "--remove", "tcp:12345")
    assert caught.value is error

    def stop(**kwargs):
        events.append("peer_stop")
        peer.process = None
        if peer_cleanup:
            raise RuntimeError("PRIVATE_PEER_CLEANUP")

    peer.stop = stop
    emulator_state = SimpleNamespace(code=None)
    emulator_process = SimpleNamespace(poll=lambda: emulator_state.code)

    def close():
        events.append("emulator_close")
        emulator_state.code = 0
        if emulator_cleanup:
            raise RuntimeError("PRIVATE_EMULATOR_CLEANUP")

    emulator = SimpleNamespace(process=emulator_process, start=lambda *args, **kwargs: None, close=close)
    instance = controller.Controller("android", peer, None, None, {"source_commit": "a" * 40})
    instance.phase = "cold_start_receipts"
    instance.run = lambda: (_ for _ in ()).throw(error)
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: emulator)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    if projection_throws:
        monkeypatch.setattr(controller, "android_lifecycle_failure",
            lambda *args: (_ for _ in ()).throw(RuntimeError("PRIVATE_PROJECTION")))
    output = tmp_path / "android_lifecycle_failure.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    report = json.loads(output.read_text())
    assert report["failure_type"] == "CalledProcessError"
    if projection_throws:
        assert "android_lifecycle_failure" not in report
    else:
        lifecycle = report["android_lifecycle_failure"]
        assert lifecycle["site"] == "forward_remove" and lifecycle["exit_status"] == 19
        assert lifecycle["instrumentation_process"] == {"state": "running", "exit_status": None}
        assert lifecycle["emulator_process"] == {"state": "running", "exit_status": None}
        assert lifecycle["cleanup_failure_sites"] == (
            ["peer_stop", "emulator_close"] if peer_cleanup else [])
    assert report.get("cleanup_failed", False) is peer_cleanup
    assert events == ["peer_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(report)
