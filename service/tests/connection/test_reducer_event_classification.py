"""Cross-state event boundaries using the production connection reducer.

Adapter epoch changes and persistence failures have no reducer Event variant;
those boundaries are documented separately from this pure-policy evidence.
"""

from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Adopted, Authority, Bridge, ConnectionKey, ConnectionState, ContextChanged,
    Desired, Failed, Failure, Health, Observed, Phase, Resource, Result, Retire,
    Tick, Work,
)
from mesh_chat.connection.reducer import transition


def initial(**changes):
    state = ConnectionState(
        ConnectionKey("contact", "profile", "local-device", "remote-device"),
        "runtime", Authority(1, True, True, True), Desired.ENABLED,
    )
    return replace(state, **changes)


def ready_carrier():
    outcome = transition(initial(), Tick(0))
    for now in range(1, len(Phase) + 1):
        work, = outcome.effects
        assert isinstance(work, Work)
        outcome = transition(outcome.state, Result(
            work.operation, now,
            allocated=work.resource if work.phase is Phase.CHECKING else None,
            verified=work.phase is Phase.CHECKING,
        ))
        if outcome.state.carrier is not None and outcome.state.carrier.bridge is Bridge.READY:
            assert outcome.state.negotiation is None
            return outcome.state, work
    pytest.fail("Successful production trace did not reach messaging readiness")


def test_stale_authority_cannot_revoke_a_current_negotiation():
    state = initial(authority=Authority(2, True, True, True))
    started = transition(state, Tick(0))
    work, = started.effects
    stale = transition(started.state, ContextChanged(1,
        authority=Authority(1, False, False, False)))
    assert stale.reason == "stale_authority"
    assert stale.effects == ()
    assert stale.state.negotiation.operation == work.operation
    assert stale.state.authority.authorized
    continued = transition(stale.state, Result(work.operation, 2))
    assert continued.state.negotiation.phase is Phase.REQUEST


def test_rate_limit_survives_stop_and_restart_without_early_work():
    started = transition(initial(), Tick(0))
    work, = started.effects
    limited = transition(started.state, Failed(work.operation, 1,
        Failure.RATE_LIMITED, retry_after=90))
    assert limited.state.retry_at == 91
    stopped = transition(limited.state, ContextChanged(2, desired=Desired.STOPPED))
    restarted = transition(stopped.state, ContextChanged(3, desired=Desired.ENABLED))
    assert transition(restarted.state, Tick(90)).effects == ()
    due = transition(restarted.state, Tick(91))
    next_work, = due.effects
    assert next_work.phase is Phase.DISCOVER
    assert next_work.operation != work.operation


@pytest.mark.parametrize("completion", [Result, Failed, Adopted])
def test_old_completion_neither_blocks_ready_carrier_nor_retires_its_resource(completion):
    state, old_work = ready_carrier()
    resource = state.carrier.resource

    def late(allocated):
        if completion is Failed:
            return Failed(old_work.operation, 20, Failure.RATE_LIMITED,
                          retry_after=120, allocated=allocated)
        return completion(old_work.operation, 20, allocated=allocated)

    same = transition(state, late(resource))
    assert same.state.carrier == state.carrier
    assert same.state.negotiation is None
    assert same.state.retry_at == state.retry_at
    assert same.effects == ()

    orphan = Resource(resource.adapter_epoch, "late-unowned-allocation")
    foreign = transition(same.state, late(orphan))
    assert foreign.state.carrier == state.carrier
    assert foreign.effects == (Retire(orphan),)
    assert Retire(resource) not in foreign.effects


def test_observation_cannot_restore_a_bridge_before_current_repair_completes():
    state, _ = ready_carrier()
    resource = state.carrier.resource
    lost = transition(state, Observed(resource, 20, Health.OPEN, Bridge.DETACHED))
    attach, = lost.effects
    assert attach.phase is Phase.ATTACH and attach.resource == resource
    assert lost.state.carrier.bridge is Bridge.RESTORING
    asserted = transition(lost.state, Observed(resource, 21, Health.OPEN, Bridge.READY))
    assert asserted.state.carrier.bridge is Bridge.RESTORING
    assert asserted.state.negotiation.operation == attach.operation
    assert asserted.effects == ()
    attached = transition(asserted.state, Result(attach.operation, 22))
    path, = attached.effects
    assert path.phase is Phase.PATH and path.resource == resource
    assert attached.state.carrier.bridge is Bridge.PATH_PENDING
    ready = transition(attached.state, Result(path.operation, 23))
    assert ready.state.carrier.bridge is Bridge.READY


def test_stopped_actor_ignores_old_ready_observation():
    state, _ = ready_carrier()
    resource = state.carrier.resource
    stopped = transition(state, ContextChanged(20, desired=Desired.STOPPED))
    assert Retire(resource) in stopped.effects
    observed = transition(stopped.state, Observed(resource, 21, Health.OPEN, Bridge.READY))
    assert observed.state.carrier is None
    assert observed.effects == ()
    assert transition(observed.state, Tick(22)).effects == ()


def test_old_carrier_observation_cannot_restore_a_replacing_negotiation():
    state, _ = ready_carrier()
    old = state.carrier.resource
    lost = transition(state, Observed(old, 20, Health.ABSENT, Bridge.DETACHED))
    assert Retire(old) in lost.effects
    replacement = transition(lost.state, Tick(lost.state.retry_at))
    work, = replacement.effects
    assert work.phase is Phase.DISCOVER and work.resource != old
    observed = transition(replacement.state, Observed(old, 22, Health.OPEN, Bridge.READY))
    assert observed.state.negotiation.operation == work.operation
    assert observed.state.carrier is None
    assert observed.effects == ()
    continued = transition(observed.state, Result(work.operation, 23))
    assert continued.state.negotiation.phase is Phase.REQUEST
