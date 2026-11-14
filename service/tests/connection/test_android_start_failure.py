"""Preserve the startup cause when cleanup of an owned Android peer also fails."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_peers as peers


@pytest.mark.parametrize("stage", ["authenticate", "initialize", "inventory", "binding",
                                   "initialize_eof", "initialize_eof_status"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_startup_cause_survives_offline_rollback(monkeypatch, stage, cleanup_fails):
    from native_interop_android_system import AndroidSystemObservation
    peer = peers.AndroidPeer(b"k" * 32)
    peer.system_observation = AndroidSystemObservation()
    process = SimpleNamespace(stdout=io.BytesIO(b"INSTRUMENTATION_STATUS: mesh_interop_port=1234\n"),
        poll=lambda: 255, wait=lambda timeout: 255)
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *a, **k: process)
    calls = []
    def adb(argv, **kwargs):
        args = argv[1:]
        calls.append(args)
        if args[:2] == ["forward", "tcp:0"]:
            return b"4567"
        if cleanup_fails:
            raise subprocess.CalledProcessError(1, ["PRIVATE_COMMAND"],
                stderr=b"adb: error: device offline")
        return b""
    monkeypatch.setattr(peers.subprocess, "check_output", adb)
    monkeypatch.setattr(peers.socket, "create_connection", lambda *a, **k: SimpleNamespace(
        close=lambda: None, settimeout=lambda _: None, sendall=lambda _: None, recv=lambda _: b""))
    original = peers.PeerFailure("internal")
    expected_stage = "initialize" if stage.startswith("initialize_eof") else stage
    def operation(name):
        if name == expected_stage:
            if stage.startswith("initialize_eof"):
                if stage == "initialize_eof_status":
                    peer._testhost_io.observe(
                        b"INSTRUMENTATION_STATUS: mesh_interop_io=v1|1|initialize_dispatch_enter|none|7|0\n")
                peer.system_observation.consume(io.BytesIO(b"[ 1.0] Kernel panic - not syncing: PRIVATE\n"))
                return peers.AndroidPeer._request(peer, name, {})
            raise original
        return {}
    monkeypatch.setattr(peer, "_request", lambda name, payload: operation(name))
    monkeypatch.setattr(peer, "inventory", lambda: operation("inventory"))
    monkeypatch.setattr(peer, "_initial_binding", lambda value: operation("binding"))
    with pytest.raises(peers.PeerFailure, match="android_host_start_failed") as caught:
        peer.start()
    value = peer.failure_start_observation(caught.value)
    assert value["stage"] == expected_stage and value["exception_kind"] == "peer_failure"
    assert value["error_code"] == ("peer_closed" if stage.startswith("initialize_eof") else "internal")
    if stage.startswith("initialize_eof"):
        assert value["transport"]["action"] == "initialize"
        assert value["transport"]["eof_stage"] == "header"
        assert value["request_ordinal"] == 1
        testhost = value["testhost_io"]
        assert testhost["pre_probe"]["instrumentation_process"] == {"state": "exited", "exit_status": 255}
        assert testhost["pre_probe"]["adb_server_process"] == {"state": "absent", "exit_status": None}
        assert testhost["pre_probe"]["emulator_process"] == {"state": "absent", "exit_status": None}
        assert testhost["pre_probe"]["emulator_system"]["counts"]["kernel_panic"] == 1
        assert testhost["pre_probe"]["statuses"] == ([] if stage == "initialize_eof" else testhost["statuses"])
        if stage == "initialize_eof_status":
            from native_interop_android_start import start_failure_snapshot
            assert testhost["statuses"][0]["initialize_dispatch_enter"] is True
            assert testhost["statuses"][0]["initialize_return"] is False
            assert start_failure_snapshot({**value, "request_ordinal": 2}) is None
        assert peer._transport_failure is None  # stop reset it; retained copy survives.
        assert peer.system_observation.snapshot()["events"] == [
            {"event": "kernel_panic", "phase": "peer_initialize"}]
    assert value["rollback_exception_kind"] == ("called_process_error" if cleanup_fails else None)
    if cleanup_fails:
        assert value["rollback_lifecycle"]["site"] == "forward_remove"
        assert value["rollback_lifecycle"]["stderr_category"] == "device_offline"
        assert value["rollback_lifecycle"]["prior_failure"]["stage"] == "force_stop"
        assert peer.process is process  # Failed cleanup retains exact custody.
    else:
        assert peer.process is None
    assert calls == [["forward", "tcp:0", "tcp:1234"],
                     ["shell", "am", "force-stop", peer.APP],
                     ["forward", "--remove", "tcp:4567"]]
    projected = controller.android_start_failure(peer, SimpleNamespace(process=None), caught.value)
    assert projected["android_start_failure"]["stage"] == expected_stage
    if stage.startswith("initialize_eof"):
        assert projected["android_start_failure"]["testhost_io"] == value["testhost_io"]
    assert "PRIVATE" not in json.dumps(projected)
    assert controller.android_start_failure(peer, None, original) == {}
    assert peer.failure_start_observation(peers.PeerFailure("android_host_start_failed")) is None


def test_start_observer_failure_cannot_replace_primary_or_prevent_cleanup(monkeypatch):
    peer = peers.AndroidPeer(b"k" * 32)
    process = SimpleNamespace(stdout=io.BytesIO(b"INSTRUMENTATION_STATUS: mesh_interop_port=1234\n"),
        poll=lambda: 0, wait=lambda timeout: 0)
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *a, **k: process)
    calls = []
    def adb(argv, **kwargs):
        calls.append(argv[1:])
        if argv[1] == "forward":
            raise subprocess.CalledProcessError(1, ["PRIVATE"])
        return b""
    monkeypatch.setattr(peers.subprocess, "check_output", adb)
    monkeypatch.setattr(peer, "failure_transport_observation", lambda error: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    with pytest.raises(peers.PeerFailure, match="android_host_start_failed"):
        peer.start()
    assert calls[-1] == ["shell", "am", "force-stop", peer.APP]
    assert peer.process is None


@pytest.mark.parametrize("change", [
    {"stage": "PRIVATE"}, {"exception_kind": []}, {"error_code": "PRIVATE"},
    {"rollback_exception_kind": True}, {"private": "PRIVATE"},
    {"transport": {}}, {"rollback_lifecycle": {}}, {"v": True},
    {"testhost_io": {}}, {"request_ordinal": 1},
])
def test_start_snapshot_rejects_malformed_or_private_fields(change):
    from native_interop_android_start import start_failure_snapshot
    value = {"v": 1, "stage": "initialize", "exception_kind": "peer_failure",
        "error_code": "internal", "rollback_exception_kind": None, **change}
    assert start_failure_snapshot(value) is None


def test_bad_initialize_testhost_dto_cannot_erase_primary_start_attribution():
    from native_interop_android_start import start_observation, start_failure_snapshot

    original = peers.PeerFailure("peer_closed")
    selected = start_observation("initialize", original, peer_failure=True,
                                 testhost_io={"private": "PRIVATE"}, request_ordinal=2)
    assert selected["stage"] == "initialize" and selected["error_code"] == "peer_closed"
    assert "testhost_io" not in selected and "PRIVATE" not in json.dumps(selected)
    assert start_failure_snapshot({**selected, "request_ordinal": 2,
                                   "testhost_io": {"private": "PRIVATE"}}) is None


def test_start_projection_rejects_throwing_or_unrelated_provider():
    error = peers.PeerFailure("android_host_start_failed")
    peer = SimpleNamespace(failure_start_observation=lambda _: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    assert controller.android_start_failure(peer, None, error) == {}


@pytest.mark.parametrize("projection_throws", [False, True])
def test_controller_keeps_start_failure_when_final_cleanup_fails(tmp_path, monkeypatch, projection_throws):
    import connection_ci
    error = peers.PeerFailure("android_host_start_failed")
    value = {"v": 1, "stage": "initialize", "exception_kind": "peer_failure",
        "error_code": "peer_closed", "rollback_exception_kind": "called_process_error"}
    peer = peers.AndroidPeer(b"k" * 32)
    peer.process = SimpleNamespace(poll=lambda: 255)
    peer._start_failure = (error, value)
    events = []
    def stop(**kwargs):
        events.append("peer_stop")
        raise OSError("PRIVATE_CLEANUP")
    peer.stop = stop
    emulator = SimpleNamespace(process=SimpleNamespace(poll=lambda: None),
        start=lambda *a, **k: None, close=lambda: events.append("emulator_close"))
    instance = controller.Controller("android", peer, None, None, {"source_commit": "a" * 40})
    instance.phase = "cold_start_receipts"
    instance.run = lambda: (_ for _ in ()).throw(error)
    monkeypatch.setattr(controller, "Controller", lambda *a, **k: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *a: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **k: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: emulator)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *a: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *a: SimpleNamespace(close=lambda: None))
    if projection_throws:
        monkeypatch.setattr(controller, "android_start_failure", lambda *a: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    result = json.loads(output.read_text())
    assert result["failure_type"] == "PeerFailure" and result["error_code"] == error.code
    assert result["passed"] is False and result["cleanup_failed"] is True
    if projection_throws:
        assert "android_start_failure" not in result
    else:
        assert result["android_start_failure"]["stage"] == "initialize"
        assert result["android_start_failure"]["cleanup_failure_sites"] == ["peer_stop"]
    assert events == ["peer_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(result)
