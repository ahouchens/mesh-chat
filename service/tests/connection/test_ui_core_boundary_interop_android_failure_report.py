"""Report the failing owned control processes before cleanup changes their state."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
from native_interop_peers import AndroidPeer, PeerFailure


def failed_android_main(tmp_path, monkeypatch, *, peer_cleanup=False, emulator_cleanup=False,
                        replacement=False, observer=None, gateway_cleanup=None):
    import connection_ci
    events = []
    process = SimpleNamespace(code=None)
    process.poll = lambda: process.code
    emulator_process = SimpleNamespace(code=-9)
    def emulator_poll():
        events.append("emulator_poll")
        return emulator_process.code
    emulator_process.poll = emulator_poll
    peer = AndroidPeer(b"k" * 32)
    peer.process = process
    peer.socket = SimpleNamespace(settimeout=lambda _: None, sendall=lambda _: None,
                                  recv=lambda _: b"")
    with pytest.raises(PeerFailure) as caught:
        peer.core("application.snapshot")
    assert caught.value.code == "peer_closed"
    original = caught.value
    if observer == "broken":
        def broken(_): raise RuntimeError("PRIVATE_OBSERVER")
        peer.failure_transport_observation = broken
    elif observer == "malformed":
        peer.failure_transport_observation = lambda _: {"raw": "PRIVATE_PAYLOAD"}
    def stop(**_):
        events.append("peer_stop")
        process.code = 0
        if peer_cleanup: raise RuntimeError("PRIVATE_PEER_CLEANUP")
    peer.stop = stop
    def close():
        events.append("emulator_close")
        emulator_process.code = 0
        if emulator_cleanup: raise RuntimeError("PRIVATE_EMULATOR_CLEANUP")
    emulator = SimpleNamespace(process=emulator_process, start=lambda *args, **kwargs: None, close=close)
    gateway = None
    if gateway_cleanup is not None:
        def gateway_close():
            events.append("gateway_before_cleanup")
            if gateway_cleanup: raise RuntimeError("PRIVATE_GATEWAY_CLEANUP")
        gateway = SimpleNamespace(ready=lambda _: events.append("gateway_ready"),
            coverage=lambda _: None, before_cleanup=gateway_close)
    instance = controller.Controller("android", peer, None, None, {"source_commit": "a" * 40})
    instance.phase = "impaired_authenticated_receipts"
    def execute():
        raise PeerFailure("peer_closed") if replacement else original
    instance.run = execute
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
    output = tmp_path / "android_control_failure.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main(gateway=gateway) == 1
    return json.loads(output.read_text()), events


@pytest.mark.parametrize("peer_cleanup,emulator_cleanup", [(False, False), (True, False), (False, True), (True, True)])
def test_main_captures_process_state_before_cleanup_and_preserves_primary_failure(
        tmp_path, monkeypatch, peer_cleanup, emulator_cleanup):
    report, events = failed_android_main(tmp_path, monkeypatch,
        peer_cleanup=peer_cleanup, emulator_cleanup=emulator_cleanup)
    assert report["error_code"] == "peer_closed" and report["passed"] is False
    observation = report["android_control_failure"]
    assert observation["emulator_process"] == {"state": "exited", "exit_status": -9}
    assert events == ["emulator_poll", "peer_stop", "emulator_close"]
    assert observation["cleanup_failure_sites"] == (
        (["peer_stop"] if peer_cleanup else []) + (["emulator_close"] if emulator_cleanup else []))
    assert report.get("cleanup_failed", False) is (peer_cleanup or emulator_cleanup)
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("observer,replacement", [(None, True), ("broken", False), ("malformed", False)])
def test_optional_or_stale_observation_does_not_change_report_or_cleanup(tmp_path, monkeypatch, observer, replacement):
    report, events = failed_android_main(tmp_path, monkeypatch, observer=observer, replacement=replacement)
    assert report["error_code"] == "peer_closed"
    assert "android_control_failure" not in report
    assert events == ["peer_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("failed", [False, True])
def test_gateway_cleanup_label_is_separate_and_emulator_cleanup_still_runs(tmp_path, monkeypatch, failed):
    report, events = failed_android_main(tmp_path, monkeypatch, gateway_cleanup=failed)
    assert report["error_code"] == "peer_closed"
    assert events == ["gateway_ready", "emulator_poll", "peer_stop", "gateway_before_cleanup", "emulator_close"]
    assert report["android_control_failure"]["cleanup_failure_sites"] == (["gateway_before_cleanup"] if failed else [])
    assert report.get("cleanup_failed", False) is failed
    assert "PRIVATE" not in json.dumps(report)
