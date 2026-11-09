"""Private pairing policy traces; these are simulated, not transport evidence."""
from dataclasses import replace
from threading import Event
from time import monotonic

import pytest

from mesh_chat.connection.model import (
    Authority, ConnectionKey, ConnectionState, ContextChanged, Desired, Failed,
    Failure, Phase, Result, Retire, Tick, Work,
)
from mesh_chat.connection.projection import snapshot
from mesh_chat.connection.reducer import transition
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.connection.model import Execution


def pairing(preferred=True):
    return ConnectionState(ConnectionKey("pairing", "intent", "local", None), "epoch",
                           Authority(1, True, True, preferred), Desired.ENABLED)


@pytest.mark.parametrize("preferred", [False, True])
def test_initial_pairing_uses_owner_phases_then_releases_without_claiming_message_readiness(preferred):
    state = pairing(preferred)
    expected = ([Phase.DISCOVER, Phase.GATHER_OFFER, Phase.PUBLISH_OFFER, Phase.WAIT_ANSWER,
                 Phase.APPLY_ANSWER, Phase.CHECKING] if preferred else
                [Phase.DISCOVER, Phase.GATHER_ANSWER, Phase.PUBLISH_ANSWER, Phase.CHECKING])
    result = transition(state, Tick(0))
    for index, phase in enumerate(expected):
        work, = result.effects
        assert isinstance(work, Work) and work.phase is phase
        result = transition(result.state, Result(work.operation, (index + 1) / 10,
            allocated=work.resource if phase is Phase.CHECKING else None,
            verified=phase is Phase.CHECKING, handoff=phase is Phase.CHECKING))
    state = result.state
    assert state.pairing_terminal and state.reason == "pairing_ready"
    assert state.carrier is None and state.negotiation is None and result.effects == ()
    assert not snapshot(state, 1)["messaging_ready"]
    resumed = transition(state, ContextChanged(2, authority=Authority(2, True, True, preferred), desired=Desired.ENABLED))
    assert transition(resumed.state, Tick(100)).effects == ()


def test_pairing_phase_timeout_is_terminal_and_never_reallocates_behind_uncertain_reply():
    start = transition(pairing(), Tick(0))
    work, = start.effects
    failed = transition(start.state, Tick(work.deadline))
    assert failed.state.pairing_terminal and failed.state.desired is Desired.STOPPED
    assert Retire(work.resource) in failed.effects
    for now in (100, 1000):
        failed = transition(failed.state, ContextChanged(now, desired=Desired.ENABLED))
        assert transition(failed.state, Tick(now)).effects == ()


def test_pairing_poll_reuses_one_resource_and_owner_deadline():
    result = transition(pairing(), Tick(0))
    for index in range(3):
        work, = result.effects
        result = transition(result.state, Result(work.operation, (index + 1) / 10))
    work, = result.effects
    assert work.phase is Phase.WAIT_ANSWER
    pending = transition(result.state, Result(work.operation, 0.5, pending=True))
    assert pending.effects == ()
    polled = transition(pending.state, Tick(pending.state.negotiation.poll_at))
    next_work, = polled.effects
    assert next_work.resource == work.resource and next_work.deadline == work.deadline


def test_pairing_revocation_retires_late_exact_allocation_and_cannot_transfer():
    result = transition(pairing(), Tick(0))
    work, = result.effects
    revoked = transition(result.state, ContextChanged(0.1, authority=Authority(2, False, False, True)))
    late = transition(revoked.state, Result(work.operation, 0.2, allocated=work.resource, verified=True, handoff=True))
    assert late.reason == "stale_completion" and late.effects == (Retire(work.resource),)
    assert not snapshot(late.state, 1)["messaging_ready"]


def test_ordinary_reconnect_cannot_skip_attachment_and_path_with_pairing_handoff():
    state = replace(pairing(), key=ConnectionKey("contact", "peer", "local", "remote"))
    result = transition(state, Tick(0))
    work, = result.effects
    failed = transition(result.state, Result(work.operation, 0.1, allocated=work.resource, handoff=True))
    assert failed.reason == "invalid_handoff" and failed.state.blocked
    assert Retire(work.resource) in failed.effects


@pytest.mark.parametrize("handoff_fails", [False, True])
def test_actual_runtime_handoff_is_once_and_exception_keeps_exact_cleanup(handoff_fails):
    results, retired, attempts = [], [], []
    profile = {"id": "intent", "scope_kind": "pairing", "local_device_id": "local",
               "active": True, "effective": {"ready": True, "preferred": True}}
    class Executor:
        def execute(self, work, cancellation):
            result = Result(work.operation, monotonic(),
                allocated=work.resource if work.phase is Phase.CHECKING else None,
                verified=work.phase is Phase.CHECKING, handoff=work.phase is Phase.CHECKING)
            results.append(result)
            return result
        def retire(self, resource): retired.append(resource)
    def handoff(operation, resource):
        attempts.append((operation, resource))
        if handoff_fails: raise OSError("handoff failed after owner release")
        return True
    runtime = ConnectionRuntime("epoch", lambda *_: Executor(), profiles=lambda: {"profiles": [profile]},
        execution=lambda: Execution.AVAILABLE, activate=lambda _: pytest.fail("Pairing activated reconnect"), handoff=handoff)
    try:
        deadline = monotonic() + 3
        while not attempts and monotonic() < deadline:
            runtime.step()
            Event().wait(0.002)
        assert len(attempts) == 1
        handed = next(result for result in results if result.handoff)
        # Duplicate handoff and an older allocation result exercise the real
        # completion queue after the original actor has surrendered its lease.
        runtime.runner._completed.put(handed)
        runtime.runner._completed.put(replace(results[1], allocated=handed.allocated))
        for _ in range(10):
            runtime.step()
            Event().wait(0.002)
        assert len(attempts) == 1
        if handoff_fails:
            assert attempts[0][1] in retired
        else:
            assert retired == []
        assert not runtime.snapshots()["intent"]["messaging_ready"]
    finally:
        runtime.stop()
        runtime.wait()
