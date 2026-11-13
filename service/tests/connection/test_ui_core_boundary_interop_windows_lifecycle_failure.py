"""Fixed Windows restart attribution keeps the original shutdown outcome."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_peers as peers
import native_interop_windows_observation as observation
from test_ui_core_boundary_interop_peers import windows_fixture


def test_exact_old_stop_kill_failure_retains_first_cause_through_cleanup(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    first = subprocess.CalledProcessError(1, ["PRIVATE_TASKKILL"], stderr=b"PRIVATE_STDERR")
    calls = []

    def kill(process):
        assert process is peer.process
        calls.append(1)
        if len(calls) == 1:
            raise first
        state["exit"] = -9

    monkeypatch.setattr(peer, "_kill_tree", kill)
    with pytest.raises(peers.PeerFailure, match="windows_shutdown_failed") as caught:
        peer.stop(crash=True, _origin="old_stop")
    assert calls == [1, 1] and all(stream.closed for stream in streams)
    observed = peer.failure_lifecycle_observation(caught.value)
    assert observed == {"origin": "old_stop", "stage": "kill_tree",
        "exception_kind": "called_process_error", "returncode": 1,
        "process_state": "running", "masked_start_kind": "none"}
    assert controller.windows_lifecycle_failure(peer, caught.value) == {"windows_lifecycle_failure": observed}
    assert controller.windows_lifecycle_failure(peer, peers.PeerFailure("windows_shutdown_failed")) == {}
    assert "PRIVATE" not in json.dumps(observed)


def test_wait_timeout_is_distinct_from_tree_kill_failure(monkeypatch):
    peer, _, state = windows_fixture(monkeypatch)
    original_wait = peer.process.wait
    first = [True]

    def wait(timeout):
        if first[0]:
            first[0] = False
            raise subprocess.TimeoutExpired("PRIVATE_PROCESS", timeout)
        return original_wait(timeout)

    peer.process.wait = wait
    with pytest.raises(peers.PeerFailure, match="windows_shutdown_failed") as caught:
        peer.stop(crash=True, _origin="old_stop")
    assert peer.failure_lifecycle_observation(caught.value) == {
        "origin": "old_stop", "stage": "wait", "exception_kind": "timeout_expired",
        "returncode": None, "process_state": "exited", "masked_start_kind": "none"}


def test_start_rollback_reports_masked_primary_start_kind(monkeypatch, tmp_path):
    peer = peers.WindowsPeer(tmp_path / "not-launched", tmp_path, b"k" * 32)
    state = {"exit": None, "kills": 0}
    streams = [SimpleNamespace(read=lambda *_: b"", close=lambda: None,
                               write=lambda *_: None, flush=lambda: None) for _ in range(3)]
    process = SimpleNamespace(pid=12345, stdin=streams[0], stdout=streams[1], stderr=streams[2],
        poll=lambda: state["exit"], wait=lambda timeout: state["exit"])
    monkeypatch.setattr(peers.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(peer, "private", lambda *args: (_ for _ in ()).throw(ValueError("PRIVATE_START")))

    def kill(owned):
        assert owned is process
        state["kills"] += 1
        if state["kills"] == 1:
            raise OSError("PRIVATE_KILL")
        state["exit"] = -9

    monkeypatch.setattr(peer, "_kill_tree", kill)
    with pytest.raises(peers.PeerFailure, match="windows_shutdown_failed") as caught:
        peer.start()
    assert state["kills"] == 2
    assert peer.failure_lifecycle_observation(caught.value) == {
        "origin": "start_rollback", "stage": "kill_tree", "exception_kind": "os_error",
        "returncode": None, "process_state": "running", "masked_start_kind": "other"}


def test_malformed_or_throwing_optional_projection_never_replaces_primary_error(monkeypatch):
    peer, _, _ = windows_fixture(monkeypatch)
    error = peers.PeerFailure("windows_shutdown_failed")
    peer.failure_lifecycle_observation = lambda _: {"origin": "old_stop", "raw": "PRIVATE"}
    assert controller.windows_lifecycle_failure(peer, error) == {}
    peer.failure_lifecycle_observation = lambda _: (_ for _ in ()).throw(RuntimeError("PRIVATE"))
    assert controller.windows_lifecycle_failure(peer, error) == {}


def test_next_stop_replaces_prior_exact_failure_attribution(monkeypatch):
    peer, _, _ = windows_fixture(monkeypatch)
    errors = iter((OSError("PRIVATE_FIRST"), OSError("PRIVATE_CLEANUP"),
                   subprocess.CalledProcessError(2, ["PRIVATE_SECOND"]),
                   subprocess.CalledProcessError(2, ["PRIVATE_CLEANUP"])))
    monkeypatch.setattr(peer, "_kill_tree", lambda _: (_ for _ in ()).throw(next(errors)))
    with pytest.raises(peers.PeerFailure) as first:
        peer.stop(crash=True, _origin="old_stop")
    assert peer.failure_lifecycle_observation(first.value)["exception_kind"] == "os_error"
    with pytest.raises(peers.PeerFailure) as second:
        peer.stop(crash=True, _origin="other_stop")
    assert peer.failure_lifecycle_observation(first.value) is None
    assert peer.failure_lifecycle_observation(second.value) == {
        "origin": "other_stop", "stage": "kill_tree", "exception_kind": "called_process_error",
        "returncode": 2, "process_state": "running", "masked_start_kind": "none"}


def test_returncode_and_process_state_are_bounded_without_raw_error():
    broken = SimpleNamespace(poll=lambda: (_ for _ in ()).throw(OSError("PRIVATE_POLL")))
    raw = subprocess.CalledProcessError(999, ["PRIVATE_COMMAND"], stderr=b"PRIVATE_STDERR")
    row = observation.lifecycle_row("old_stop", "kill_tree", raw, broken)
    assert row == {"origin": "old_stop", "stage": "kill_tree",
        "exception_kind": "called_process_error", "returncode": None,
        "process_state": "unknown", "masked_start_kind": "none"}
    assert observation.windows_lifecycle_snapshot({**row, "returncode": 999}) is None
    assert "PRIVATE" not in json.dumps(row)
