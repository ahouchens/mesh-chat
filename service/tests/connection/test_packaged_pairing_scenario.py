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
