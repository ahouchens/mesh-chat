"""Owner transition evidence only; native packet and restart qualification is separate."""

from copy import deepcopy
from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Authority, ConnectionKey, ConnectionState, ContextChanged, Desired, Execution,
    Failed, Failure, Phase, Resource, Result, Work,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor


PENDING = {Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.PUBLISH_OFFER,
           Phase.PUBLISH_ANSWER, Phase.WAIT_ANSWER, Phase.APPLY_ANSWER, Phase.CHECKING}
PHYSICAL = Resource("native", "native-physical")


def reconnect(preferred=False):
    key = ConnectionKey("contact", "peer", "local", "remote")
    owner = ConnectionSupervisor("epoch")
    owner.register(ConnectionState(key, "epoch", Authority(1, True, True, preferred), Desired.ENABLED))
    owner.tick(0)
    return owner, key


def complete(owner, key, work, now):
    owner.dispatch(key, Result(work.operation, now, verified=True,
        allocated=work.resource if work.phase in {Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.CHECKING} else None))


def gathered_owner():
    owner, key = reconnect()
    now = 0.01
    while True:
        work, = owner.drain()
        assert isinstance(work, Work)
        if work.phase is Phase.GATHER_OFFER:
            return owner, key, work, now
        complete(owner, key, work, now)
        now += 0.01


@pytest.mark.parametrize("preferred", [False, True])
def test_pending_hint_tracks_both_protocol_roles_without_granting_a_carrier(preferred):
    owner, key = reconnect(preferred)
    now, seen = 0.01, set()
    for _ in range(12):
        state = owner.snapshot(key)
        if state.carrier is not None:
            assert not owner.pending_native_negotiation(key, state.carrier.resource, PHYSICAL, now)
            break
        step = state.negotiation
        expected = step.phase in PENDING
        before = deepcopy((owner._states, owner._pending, owner._running, owner._retiring))
        assert owner.pending_native_negotiation(key, step.resource, PHYSICAL, now) is expected
        assert (owner._states, owner._pending, owner._running, owner._retiring) == before
        work, = owner.drain()
        assert owner.pending_native_negotiation(key, step.resource, PHYSICAL, now) is expected
        if work.phase in {Phase.WAIT_ANSWER, Phase.CHECKING}:
            owner.dispatch(key, Result(work.operation, now, pending=True))
            polling = owner.snapshot(key).negotiation
            assert polling.operation is None and polling.deadline == step.deadline
            assert owner.pending_native_negotiation(key, step.resource, PHYSICAL, now)
            assert not owner.pending_native_negotiation(key, step.resource, PHYSICAL, polling.deadline)
            now = polling.poll_at
            owner.tick(now)
            assert owner.pending_native_negotiation(key, step.resource, PHYSICAL, now)
            work, = owner.drain()
            seen.add("poll:" + work.phase.value)
        seen.add(work.phase)
        complete(owner, key, work, now)
        now += 0.01
    else:
        pytest.fail("Verified checking never committed the carrier")
    assert Phase.CHECKING in seen and "poll:checking" in seen
    assert (Phase.GATHER_ANSWER if preferred else Phase.GATHER_OFFER) in seen
    if not preferred:
        assert "poll:wait_answer" in seen


@pytest.mark.parametrize("transition", ["revoke", "stop", "pause", "expire", "retire", "fail"])
def test_pending_hint_ends_on_real_owner_invalidation(transition):
    owner, key, work, now = gathered_owner()
    assert owner.pending_native_negotiation(key, work.resource, PHYSICAL, now)
    if transition == "revoke":
        owner.dispatch(key, ContextChanged(now, authority=replace(owner.snapshot(key).authority, authorized=False)))
    elif transition == "stop": owner.dispatch(key, ContextChanged(now, desired=Desired.STOPPED))
    elif transition == "pause": owner.dispatch(key, ContextChanged(now, execution=Execution.PAUSED))
    elif transition == "expire":
        now = work.deadline
        owner.tick(now)
    elif transition == "retire": owner.retire(key, now)
    else: owner.dispatch(key, Failed(work.operation, now, Failure.REVOKED, allocated=work.resource))
    assert not owner.pending_native_negotiation(key, work.resource, PHYSICAL, now)
