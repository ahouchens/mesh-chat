"""Failure injection around restart custody, independent of the public flow."""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_restart_controller as controller
from test_public_core_restart_evidence import evidence_pair


def setup(monkeypatch, tmp_path, role="windows", *, fail=None):
    reports, context, tree, inputs, _ = evidence_pair()
    calls, ticks = [], [0]
    peer = SimpleNamespace(process=None, retired=False, workspace_cleaned=False)
    def event(name):
        calls.append(name)
        if name == fail:
            raise RuntimeError("private product and credential text")
    def open_peer():
        peer.process = object()
        event("open")
    def finish(_role, selected, requests=None):
        assert selected is peer and _role == role
        if requests is not None:
            assert requests == (12 if role == "windows" else 38)
        event("finish")
        peer.retired = True
    def cleanup():
        event("workspace_cleanup")
        peer.workspace_cleaned = True
    def close():
        event("android_close")
        return True
    peer.open, peer.cleanup_workspace, peer.close = open_peer, cleanup, close
    def connect(deadline):
        assert deadline < 1200
        event("connect")
    exchange = SimpleNamespace(connect=connect, close=lambda: event("exchange_close"))
    monkeypatch.setenv("PUBLIC_PAIR_SCENARIO", "owner_restart")
    monkeypatch.setattr(controller.installed, "admitted_context", lambda *args: dict(context))
    monkeypatch.setattr(controller.installed, "runner_temp", lambda: tmp_path)
    monkeypatch.setattr(controller.baseline_evidence, "source_identity", lambda *args: (context["source_commit"], tree))
    monkeypatch.setattr(controller.installed, "producer_inputs", lambda *args: deepcopy(inputs[role]))
    monkeypatch.setattr(controller.installed, "verify_downloads", lambda *args: event("download_bytes"))
    monkeypatch.setattr(controller.installed, "create_peer", lambda *args: peer)
    monkeypatch.setattr(controller.installed, "create_exchange", lambda *args: exchange)
    monkeypatch.setattr(controller.installed, "finish_peer", finish)
    def flow(*args, **kwargs):
        assert kwargs["overall_deadline"] == 1201
        event("flow")
        return deepcopy(reports[role]["flow"])
    monkeypatch.setattr(controller, "run_restart_role", flow)
    verify = controller.evidence.verify_role_report
    def verify_report(*args):
        event("report")
        return verify(*args)
    monkeypatch.setattr(controller.evidence, "verify_role_report", verify_report)
    def clock():
        ticks[0] += 1
        return ticks[0]
    return calls, peer, clock, context["source_commit"]


@pytest.mark.parametrize("role", ["windows", "android"])
def test_success_requires_retirement_and_valid_report_before_windows_data_removal(monkeypatch, tmp_path, role):
    calls, peer, clock, source = setup(monkeypatch, tmp_path, role)
    result = controller.run(role, source, clock=clock)
    assert result["passed"] is True
    assert result["session"] == {"finished": True, "cleanup": True,
                                 "owner_incarnations_finished": 2 if role == "windows" else 1}
    assert calls.index("download_bytes") < calls.index("connect") < calls.index("open")
    assert calls.index("flow") < calls.index("finish") < calls.index("exchange_close") < calls.index("report")
    if role == "windows":
        assert calls.index("report") < calls.index("workspace_cleanup") < len(calls) - 1
        assert calls[-1] == "report"
    else:
        assert "android_close" in calls and "workspace_cleanup" not in calls
    assert not list(tmp_path.glob("mesh-public-restart-setup-*"))


@pytest.mark.parametrize("phase", ["download_bytes", "connect", "open", "flow", "finish", "exchange_close", "report"])
def test_any_failure_retains_windows_data_and_does_not_invent_owner_count(monkeypatch, tmp_path, phase):
    calls, peer, clock, source = setup(monkeypatch, tmp_path, fail=phase)
    result = controller.run("windows", source, clock=clock)
    assert result["passed"] is False and not peer.workspace_cleaned
    assert "workspace_cleanup" not in calls and "private" not in str(result)
    assert result["session"]["owner_incarnations_finished"] is None
    assert not list(tmp_path.glob("mesh-public-restart-setup-*"))


def test_changed_source_after_restart_preserves_retired_windows_data(monkeypatch, tmp_path):
    calls, peer, clock, source = setup(monkeypatch, tmp_path)
    identities = iter([(source, "b" * 40), ("e" * 40, "b" * 40)])
    monkeypatch.setattr(controller.baseline_evidence, "source_identity", lambda *args: next(identities))
    result = controller.run("windows", source, clock=clock)
    assert result["passed"] is False and result["failure_phase"] == "final_binding"
    assert peer.retired and not peer.workspace_cleaned


@pytest.mark.parametrize("failure", ["flow", "android_close"])
def test_android_always_closes_owned_session_and_remains_failed(monkeypatch, tmp_path, failure):
    calls, peer, clock, source = setup(monkeypatch, tmp_path, "android", fail=failure)
    result = controller.run("android", source, "emulator-5554", clock=clock)
    assert result["passed"] is False and "android_close" in calls
    assert result["session"]["owner_incarnations_finished"] is None


@pytest.mark.parametrize("mode", [None, "fresh", "restart"])
def test_restart_requires_explicit_scenario_before_any_installation(monkeypatch, tmp_path, mode):
    calls, peer, clock, source = setup(monkeypatch, tmp_path)
    monkeypatch.delenv("PUBLIC_PAIR_SCENARIO") if mode is None else monkeypatch.setenv("PUBLIC_PAIR_SCENARIO", mode)
    result = controller.run("windows", source, clock=clock)
    assert result["passed"] is False and result["failure_phase"] == "admission"
    assert not calls and peer.process is None


def test_cleanup_overrun_cannot_pass_on_precleanup_duration(monkeypatch, tmp_path):
    calls, peer, _, source = setup(monkeypatch, tmp_path)
    times = iter([1, 2, 3, 4, 1202])
    result = controller.run("windows", source, clock=lambda: next(times))
    assert peer.workspace_cleaned
    assert result["passed"] is False and result["duration_seconds"] == 1201
    assert result["session"]["owner_incarnations_finished"] is None
