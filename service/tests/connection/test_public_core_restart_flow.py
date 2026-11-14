"""Owner-restart flow uses public requests, one Android lifetime and fixed phases."""

import hashlib
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_restart_flow as restart


PAIR_ID = "a" * 32
DESTINATIONS = {"windows": "1" * 32, "android": "2" * 32}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def baseline(role, count=20):
    other = "android" if role == "windows" else "windows"
    return {"v": 1, "role": role, "pair_id": PAIR_ID,
            "self_destination_sha256": digest(DESTINATIONS[role]),
            "peer_destination_sha256": digest(DESTINATIONS[other]),
            "explicit_decision": "request_approved" if role == "windows" else "invitation_accepted",
            "contact_count": 1, "contact_trust": "approved", "messaging_ready": True,
            "pairing_transferred": True, "cancel_preserved_transferred": True,
            "outbound_text_sha256": digest(restart._text(PAIR_ID, role)),
            "outbound_message_count": 1, "outbound_delivered": True,
            "inbound_text_sha256": digest(restart._text(PAIR_ID, other)),
            "inbound_message_count": 1, "public_request_count": count}


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Process:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


class Protocol:
    def __init__(self, count):
        self.step = count


class Peer:
    def __init__(self, role, clock, *, changed_original=False, duplicate_post=False, failed_stop=False):
        self.role, self.clock = role, clock
        self.other = "android" if role == "windows" else "windows"
        self.deadline = 840.0
        self.process = Process()
        self.data = "same-owned-efs-data"
        self.retired = self.confirmed_shutdown = False
        self.protocol = Protocol(20) if role == "android" else None
        self.sequence = 20 if role == "windows" else None
        self.incarnation = 1
        self.calls = []
        self.reopen_calls = []
        self.post_sent = False
        self.changed_original = changed_original
        self.duplicate_post = duplicate_post
        self.failed_stop = failed_stop

    def snapshot(self):
        original_out = restart._text(PAIR_ID, self.role)
        original_in = restart._text(PAIR_ID, self.other)
        messages = [
            {"id": "original-out", "kind": "chat", "direction": "outbound", "text": original_out,
             "contact_id": "contact-1", "state": "delivered"},
            {"id": "original-in" if not self.changed_original or self.incarnation == 1 else "changed-in",
             "kind": "chat", "direction": "inbound", "text": original_in, "contact_id": "contact-1"},
        ]
        if self.post_sent:
            messages.extend([
                {"id": "post-out", "kind": "chat", "direction": "outbound",
                 "text": restart._text(PAIR_ID, self.role, restart=True),
                 "contact_id": "contact-1", "state": "delivered"},
                {"id": "post-in", "kind": "chat", "direction": "inbound",
                 "text": restart._text(PAIR_ID, self.other, restart=True), "contact_id": "contact-1"},
            ])
            if self.duplicate_post:
                messages.append(dict(messages[-1], id="post-in-duplicate"))
        return {"profile": {"display_name": "Independent " + self.role,
                            "destination_hash": DESTINATIONS[self.role]},
                "contacts": [{"id": "contact-1", "core_handle": f"peer-{self.incarnation}",
                              "destination_hash": DESTINATIONS[self.other], "trust": "approved"}],
                "messages": messages}

    def request(self, operation, params=None, key=None):
        self.calls.append((self.incarnation, operation, params, key))
        if self.role == "android":
            self.protocol.step += 1
        else:
            self.sequence += 1
        profile = f"profile-{self.incarnation}"
        if operation == "runtime.capabilities":
            return {"profiles": [profile], "operations": ["profile.query", "connection.snapshot",
                                                         "message.enqueue", "message.query"]}
        if operation == "profile.query":
            assert params == {"profile": profile}
            return {"destination": DESTINATIONS[self.role], "connections": ["connection-1"]}
        if operation == "application.snapshot":
            return self.snapshot()
        if operation == "connection.snapshot":
            assert params == {"profile": profile, "connection": "connection-1"}
            return {"observation": {"messaging_ready": True}}
        if operation == "message.enqueue":
            assert params == {"profile": profile, "recipient": f"peer-{self.incarnation}",
                              "kind": "text", "text": restart._text(PAIR_ID, self.role, restart=True)}
            assert isinstance(key, str) and len(key) >= 16
            self.post_sent = True
            return {"accepted": True, "message": "post-out"}
        if operation == "message.query":
            assert params == {"profile": profile, "message": "post-out"}
            return {"message": "post-out", "text": restart._text(PAIR_ID, self.role, restart=True),
                    "recipient": f"peer-{self.incarnation}", "state": "delivered"}
        raise AssertionError(operation)

    def finish(self):
        assert self.role == "windows"
        if self.failed_stop:
            raise RuntimeError("positive_retirement_missing")
        self.process.code = 0
        self.retired = True
        return True

    def reopen_same_data(self, deadline):
        assert self.role == "windows" and self.retired and self.process.poll() == 0
        self.reopen_calls.append(deadline)
        self.process = Process()
        self.incarnation += 1
        self.sequence = 0
        self.retired = False
        self.deadline = deadline
        return self


class Exchange:
    def __init__(self, clock, *, extra_payload=False, late_phase=False):
        self.clock = clock
        self.events = []
        self.extra_payload = extra_payload
        self.late_phase = late_phase

    def publish(self, phase, payload, deadline):
        self.events.append(("publish", phase, payload))
        if self.late_phase:
            self.clock.now = deadline

    def receive(self, phase, deadline):
        self.events.append(("receive", phase, None))
        if self.late_phase:
            self.clock.now = deadline
        return {"private": "payload"} if self.extra_payload else {}


def run(role, monkeypatch, **peer_options):
    clock = Clock()
    peer = Peer(role, clock, **peer_options)
    exchange = Exchange(clock)
    baseline_deadlines = []

    def fresh(_role, _peer, _exchange, *, pair_id, deadline, clock, sleep):
        assert (_role, _peer, _exchange, pair_id) == (role, peer, exchange, PAIR_ID)
        baseline_deadlines.append(deadline)
        return baseline(role)

    monkeypatch.setattr(restart, "run_fresh_role", fresh)
    result = restart.run_restart_role(role, peer, exchange, pair_id=PAIR_ID,
                                      overall_deadline=1200, clock=clock.clock, sleep=clock.sleep)
    return result, peer, exchange, baseline_deadlines


def test_windows_restarts_positive_owner_and_preserves_public_state(monkeypatch):
    result, peer, exchange, deadlines = run("windows", monkeypatch)
    assert deadlines == [540]  # Flow's own 60-second reserve makes the effective cutoff 480.
    assert peer.reopen_calls == [840]
    assert peer.incarnation == 2 and peer.process.poll() is None
    assert result["request_counts"] == {"baseline": 20, "before_stop": 23, "after_reopen": 12}
    assert [event[:2] for event in exchange.events] == [
        ("publish", "owner_stopped"), ("receive", "android_continuous"),
        ("publish", "owner_reopened"), ("publish", "restart_ready"),
        ("receive", "restart_ready"), ("publish", "restart_done"),
        ("receive", "restart_done")]
    assert all(payload == {} for action, _, payload in exchange.events if action == "publish")
    assert not any(op.startswith("peer.") or op == "contact.invitation" for _, op, _, _ in peer.calls)


def test_android_remains_one_session_and_reserves_finish_frame(monkeypatch):
    result, peer, exchange, deadlines = run("android", monkeypatch)
    assert deadlines == [540]
    assert peer.incarnation == 1 and peer.process.poll() is None and not peer.confirmed_shutdown
    assert result["request_counts"]["total"] == peer.protocol.step <= 126
    assert [event[:2] for event in exchange.events[:3]] == [
        ("receive", "owner_stopped"), ("publish", "android_continuous"),
        ("receive", "owner_reopened")]
    assert not any(op.startswith("peer.") or op == "contact.invitation" for _, op, _, _ in peer.calls)


@pytest.mark.parametrize("role", ["windows", "android"])
def test_original_message_change_and_post_duplicate_fail(monkeypatch, role):
    failure = "public_restart_state_changed" if role == "windows" else "public_restart_duplicate_inbound"
    with pytest.raises(ValueError, match=failure):
        run(role, monkeypatch, **({"changed_original": True} if role == "windows" else {"duplicate_post": True}))


def test_failed_positive_owner_stop_cannot_publish_restart_phase(monkeypatch):
    clock = Clock()
    peer, exchange = Peer("windows", clock, failed_stop=True), Exchange(clock)
    monkeypatch.setattr(restart, "run_fresh_role", lambda *_args, **_kwargs: baseline("windows"))
    with pytest.raises(RuntimeError, match="positive_retirement_missing"):
        restart.run_restart_role("windows", peer, exchange, pair_id=PAIR_ID,
                                 overall_deadline=1200, clock=clock.clock, sleep=clock.sleep)
    assert exchange.events == []


@pytest.mark.parametrize("role", ["windows", "android"])
def test_session_replacement_between_fresh_pair_and_restart_is_rejected(monkeypatch, role):
    clock = Clock()
    peer, exchange = Peer(role, clock), Exchange(clock)
    def swapped(*_args, **_kwargs):
        peer.process = Process()
        return baseline(role)
    monkeypatch.setattr(restart, "run_fresh_role", swapped)
    with pytest.raises(ValueError, match=("public_restart_owner_not_running" if role == "windows"
                                          else "public_restart_android_not_running")):
        restart.run_restart_role(role, peer, exchange, pair_id=PAIR_ID,
                                 overall_deadline=1200, clock=clock.clock, sleep=clock.sleep)
    assert exchange.events == []


def test_baseline_cutoff_and_insufficient_admission_fail_closed(monkeypatch):
    clock = Clock()
    peer, exchange = Peer("windows", clock), Exchange(clock)
    with pytest.raises(TimeoutError, match="public_restart_admission_deadline"):
        restart.run_restart_role("windows", peer, exchange, pair_id=PAIR_ID,
                                 overall_deadline=390, clock=clock.clock, sleep=clock.sleep)
    assert peer.calls == []
    def late_baseline(*_args, **_kwargs):
        clock.now = 480
        return baseline("windows")
    monkeypatch.setattr(restart, "run_fresh_role", late_baseline)
    with pytest.raises(TimeoutError, match="public_restart_baseline_deadline"):
        restart.run_restart_role("windows", peer, exchange, pair_id=PAIR_ID,
                                 overall_deadline=1200, clock=clock.clock, sleep=clock.sleep)
    assert peer.calls == []


def test_phase_deadline_and_payload_are_strict(monkeypatch):
    clock = Clock()
    peer = Peer("android", clock)
    monkeypatch.setattr(restart, "run_fresh_role", lambda *_args, **_kwargs: baseline("android"))
    with pytest.raises(ValueError, match="public_restart_phase_payload"):
        restart.run_restart_role("android", peer, Exchange(clock, extra_payload=True),
                                 pair_id=PAIR_ID, overall_deadline=1200,
                                 clock=clock.clock, sleep=clock.sleep)
    clock = Clock()
    peer = Peer("android", clock)
    with pytest.raises(TimeoutError, match="public_restart_phase_deadline"):
        restart.run_restart_role("android", peer, Exchange(clock, late_phase=True),
                                 pair_id=PAIR_ID, overall_deadline=1200,
                                 clock=clock.clock, sleep=clock.sleep)


def test_android_request_budget_rejects_before_extra_send():
    clock = Clock()
    peer = Peer("android", clock)
    scenario = restart.RestartFlow("android", peer, Exchange(clock), PAIR_ID, 1200,
                                   clock.clock, clock.sleep)
    scenario.baseline = baseline("android", 96)
    scenario.additional = 30
    before = len(peer.calls)
    with pytest.raises(ValueError, match="public_restart_request_budget"):
        scenario._request("application.snapshot")
    assert len(peer.calls) == before


def test_windows_request_budget_resets_only_after_positive_reopen():
    clock = Clock()
    peer = Peer("windows", clock)
    scenario = restart.RestartFlow("windows", peer, Exchange(clock), PAIR_ID, 1200,
                                   clock.clock, clock.sleep)
    scenario.baseline = baseline("windows", 96)
    with pytest.raises(ValueError, match="public_restart_request_budget"):
        scenario._request("application.snapshot")
    assert peer.calls == []
    scenario.reopened = True
    scenario.after_reopen = 96
    with pytest.raises(ValueError, match="public_restart_request_budget"):
        scenario._request("application.snapshot")
    assert peer.calls == []
