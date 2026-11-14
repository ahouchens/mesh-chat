"""Controller custody failures cannot turn into a successful public pair report."""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_pair_controller as controller


SOURCE = "a" * 40
TREE = "b" * 40
CONTEXT = {"repository": "owner/repository", "repository_id": 1, "run_id": 2,
           "run_attempt": 1, "source_commit": SOURCE, "pair_id": "c" * 32}


def setup(monkeypatch, tmp_path, role="windows", *, failed_phase=None):
    calls = []
    peer = SimpleNamespace(deadline=840, retired=False, process=None, workspace_cleaned=False,
                           sequence=20, data=tmp_path / "profile")
    def event(name):
        calls.append(name)
        if name == failed_phase:
            raise RuntimeError("sensitive upstream text that must not be reported")
    def open_peer():
        peer.process = object()
        event("open")
    def finish_peer():
        event("finish")
        peer.retired = True
    def cleanup():
        event("workspace_cleanup")
        peer.workspace_cleaned = True
    def close():
        event("android_close")
        return True
    peer.open, peer.finish, peer.cleanup_workspace, peer.close = open_peer, finish_peer, cleanup, close
    exchange = SimpleNamespace(connect=lambda deadline: event("connect"), close=lambda: event("exchange_close"))
    monkeypatch.setattr(controller, "admitted_context", lambda *args: dict(CONTEXT))
    monkeypatch.setattr(controller, "runner_temp", lambda: tmp_path)
    monkeypatch.setattr(controller.evidence, "source_identity", lambda expected: (SOURCE, TREE))
    def inputs(*args):
        event("inputs")
        return {"artifact": "d" * 64}
    monkeypatch.setattr(controller, "producer_inputs", inputs)
    monkeypatch.setattr(controller, "verify_downloads", lambda *args: event("download_bytes"))
    monkeypatch.setattr(controller, "create_peer", lambda *args: peer)
    monkeypatch.setattr(controller, "create_exchange", lambda *args: exchange)
    flow = {"public_request_count": 20}
    def run_flow(*args, **kwargs):
        event("flow")
        assert kwargs["deadline"] == 840
        return deepcopy(flow)
    monkeypatch.setattr(controller, "run_role", run_flow)
    monkeypatch.setattr(controller.evidence, "verify_flow", lambda *args: None)
    def finish(_role, selected, requests=None):
        selected.finish()
    monkeypatch.setattr(controller, "finish_peer", finish)
    ticks = iter([0, 0, 1, 2])
    return calls, peer, lambda: next(ticks)


@pytest.mark.parametrize("role", ["windows", "android"])
def test_owned_session_finishes_before_successful_cleanup(monkeypatch, tmp_path, role):
    calls, peer, clock = setup(monkeypatch, tmp_path, role)
    result = controller.run(role, SOURCE, clock=clock)
    assert result["passed"] is True and result["session"] == {"finished": True, "cleanup": True}
    assert calls.index("connect") < calls.index("open") < calls.index("flow") < calls.index("finish")
    assert calls.index("download_bytes") < calls.index("connect")
    ending = "workspace_cleanup" if role == "windows" else "android_close"
    assert calls.index("finish") < calls.index(ending) < calls.index("exchange_close")
    assert not list(tmp_path.glob("mesh-public-pair-setup-*"))


@pytest.mark.parametrize("phase", ["download_bytes", "connect", "open", "flow", "finish", "workspace_cleanup", "exchange_close"])
def test_failure_preserves_primary_outcome_and_prevents_success(monkeypatch, tmp_path, phase):
    calls, peer, clock = setup(monkeypatch, tmp_path, failed_phase=phase)
    result = controller.run("windows", SOURCE, clock=clock)
    assert result["passed"] is False
    assert "sensitive" not in str(result)
    if phase == "download_bytes":
        assert "connect" not in calls and "open" not in calls
    if phase in {"open", "flow", "finish"}:
        assert "workspace_cleanup" not in calls
        assert result["session"]["cleanup"] is False
    assert not list(tmp_path.glob("mesh-public-pair-setup-*"))


def test_changed_producer_inputs_retain_finished_windows_workspace(monkeypatch, tmp_path):
    calls, peer, clock = setup(monkeypatch, tmp_path)
    inputs = iter([{"artifact": "d" * 64}, {"artifact": "e" * 64}])
    monkeypatch.setattr(controller, "producer_inputs", lambda *args: next(inputs))
    result = controller.run("windows", SOURCE, clock=clock)
    assert result["passed"] is False and result["failure_phase"] == "final_binding"
    assert peer.retired and not peer.workspace_cleaned


def test_android_failure_still_closes_its_owned_installation(monkeypatch, tmp_path):
    calls, peer, clock = setup(monkeypatch, tmp_path, "android", failed_phase="flow")
    result = controller.run("android", SOURCE, "emulator-5554", clock=clock)
    assert result["passed"] is False and result["failure_phase"] == "public_flow"
    assert "android_close" in calls and "finish" not in calls
    assert result["session"] == {"finished": False, "cleanup": True}


def test_admission_failure_never_installs_or_publishes(monkeypatch, tmp_path):
    calls, peer, clock = setup(monkeypatch, tmp_path)
    def denied(*args):
        raise ValueError("wrong job")
    monkeypatch.setattr(controller, "admitted_context", denied)
    result = controller.run("windows", SOURCE, clock=clock)
    assert result["passed"] is False and result["failure_phase"] == "admission"
    assert calls == [] and peer.process is None


@pytest.mark.parametrize("role,serial,platform,job", [
    ("windows", None, "win32", "windows_public"),
    ("android", "emulator-5554", "linux", "android_public"),
])
def test_actual_admission_requires_exact_job_and_disposable_platform(monkeypatch, role, serial, platform, job):
    environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_JOB": job,
        "GITHUB_SHA": SOURCE, "GITHUB_REPOSITORY": "owner/repository", "GITHUB_REPOSITORY_ID": "1",
        "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_TOKEN": "read-token", "ACTIONS_RUNTIME_TOKEN": "runtime-token"}
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(controller.sys, "platform", platform)
    assert controller.admitted_context(role, SOURCE, serial)["source_commit"] == SOURCE
    monkeypatch.setenv("GITHUB_JOB", "native_windows_peer")
    with pytest.raises(ValueError, match="admission"):
        controller.admitted_context(role, SOURCE, serial)


def test_windows_finish_binds_actual_request_count_before_profile_check(monkeypatch):
    peer = SimpleNamespace(finish=lambda: True, sequence=5, data=Path("not-read"))
    with pytest.raises(ValueError, match="public_request_count"):
        controller.finish_peer("windows", peer, requests=6)


def test_android_finish_binds_acknowledged_request_count():
    peer = SimpleNamespace(finish=lambda: 5)
    with pytest.raises(ValueError, match="public_request_count"):
        controller.finish_peer("android", peer, requests=6)
