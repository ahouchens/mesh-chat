"""Negative controls for the packaged scenario, not native qualification."""
from pathlib import Path
import runpy

import pytest


@pytest.fixture
def scenario(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "tools/connection_harness"
    monkeypatch.syspath_prepend(str(directory))
    module = runpy.run_path(str(directory / "packaged_pairing_probe.py"))
    function = module["cancel_and_restart"]
    calls = []
    monkeypatch.setitem(function.__globals__, "start", lambda *args: calls.append(("start", args[1])))
    monkeypatch.setitem(function.__globals__, "connect", lambda *_args, **_kwargs: calls.append(("connect",)))
    monkeypatch.setitem(function.__globals__, "sleep", lambda _: None)
    return function, calls


class PeerFixture:
    def __init__(self, fault=None):
        self.fault = fault
        self.restarted = False
        self.checks = []
        self.denials = []
        self.actions = []

    def call(self, slot, command, **payload):
        if command == "native_webrtc_close":
            return {"state": "managed" if self.fault == "not_closed" else "closed"}
        assert command == "snapshot"
        invitation = {"id": "pending", "state": "pending", "expired": False}
        if self.fault == "expired": invitation["expired"] = True
        contacts = [{"trust": "approved"}] if self.fault == "approved" else []
        invitations = [invitation] if slot == 1 else []
        if self.fault == "lost_after_restart" and self.restarted: invitations = []
        return {"contacts": contacts, "messages": [], "contact_invitations": invitations}

    def reject(self, slot, command, expected_error, **payload):
        if self.fault == "stale_session" and self.restarted:
            raise RuntimeError("Retired native session still accepts commands")
        self.denials.append((slot, command, expected_error))

    def action(self, slot, action):
        self.actions.append((slot, action))
        if action == "counts": return {"close": 0 if self.fault == "no_native_disposal" else 1}
        assert action == "crash" and slot == 1
        self.restarted = True


def test_cancellation_restart_checks_precede_fresh_pairing(scenario):
    run, calls = scenario
    controller = PeerFixture()
    run(controller, [object(), object()], "pending")
    assert controller.checks == ["cancelled_pairing_retires_native_sessions",
                                 "pending_invitation_survives_restart_without_approval"]
    assert calls == [("start", 1), ("connect",)]
    assert len(controller.denials) == 8
    assert {denial[2] for denial in controller.denials} == {"native_unavailable"}


@pytest.mark.parametrize("fault", ["not_closed", "approved", "expired", "no_native_disposal",
                                  "lost_after_restart", "stale_session"])
def test_incomplete_cancellation_or_restart_cannot_proceed_to_fresh_pairing(scenario, fault):
    run, calls = scenario
    controller = PeerFixture(fault)
    with pytest.raises((AssertionError, RuntimeError)):
        run(controller, [object(), object()], "pending")
    assert ("connect",) not in calls


@pytest.mark.parametrize("fault", [None, "retired", "raw_fields", "diagnostic_failure"])
def test_approved_path_timeout_remains_failure_with_bounded_content_free_native_state(monkeypatch, fault):
    directory = Path(__file__).resolve().parents[2] / "tools/connection_harness"
    monkeypatch.syspath_prepend(str(directory))
    run = runpy.run_path(str(directory / "packaged_pairing_probe.py"))["approved_path"]
    original = TimeoutError("Primary readiness deadline")
    def fail_ready(*_): raise original
    monkeypatch.setitem(run.__globals__, "ready", fail_ready)
    class Controller:
        checks = []
        def call(self, slot, command, **payload):
            if fault == "diagnostic_failure": raise RuntimeError("RAW secret SDP/path")
            if command == "reconnect_profiles":
                if fault == "raw_fields":
                    return {"profiles": [{"contact_id": "peer", "connection": {"carrier": ["RAW secret"], "bridge": "RAW private path"}}]}
                # A foreign first profile must not supply another peer's state.
                return {"profiles": [{"contact_id": "foreign", "connection": {"carrier": "closing", "bridge": "restoring"}},
                    {"contact_id": "peer", "connection": {"carrier": "absent", "bridge": "detached"}}]}
            assert command == "native_webrtc_stats"
            if fault == "retired": raise RuntimeError("native_unavailable")
            return {"data_channel_state": ["RAW SDP"] if fault == "raw_fields" else "open",
                    "attached": "RAW token" if fault == "raw_fields" else False}
        def action(self, slot, action):
            assert action == "counts"
            if fault == "diagnostic_failure": raise RuntimeError("RAW host secret")
            return {"close": "RAW diagnostic" if fault == "raw_fields" else 10**20}
    controller = Controller()
    with pytest.raises(TimeoutError) as failure:
        run(controller, [(None, None, "peer"), (None, None, "peer")])
    assert failure.value is original and not controller.checks
    for value in (controller.phase, controller.error_code):
        assert len(value) <= 64 and value.isidentifier() and "RAW" not in value
    if fault is None:
        assert controller.phase == "approved_path_d0open_a00_c0999_d1open_a10_c1999"
        assert controller.error_code == "p0_absent_detached_p1_absent_detached"
    if fault == "retired": assert "unavailable" in controller.phase
