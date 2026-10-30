from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Authority, ConnectionKey, ConnectionState, ContextChanged, Desired,
    Policy, Result, Tick, Work,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor, CapacityExceeded


def actor(name, **changes):
    return replace(ConnectionState(ConnectionKey("personal", name, "local", None),
                   "epoch", Authority(1, True, True, True), Desired.ENABLED), **changes)


def test_concurrency_bound_and_fair_admission():
    owner = ConnectionSupervisor("epoch", Policy(max_workers=2))
    for name in ("one", "two", "three"):
        owner.register(actor(name))
    owner.tick(0)
    work = owner.drain()
    assert len(work) == 2
    assert owner.drain() == ()
    first = work[0]
    owner.dispatch(first.operation.key, Result(first.operation, 1))
    next_work = owner.drain()
    assert len(next_work) == 1
    assert next_work[0].operation.key.profile_id == "three"


def test_cancel_keeps_native_reservation_until_completion():
    owner = ConnectionSupervisor("epoch", Policy(max_workers=1))
    one, two = actor("one"), actor("two")
    owner.register(one)
    owner.register(two)
    owner.tick(0)
    work = owner.drain()[0]
    owner.dispatch(one.key, ContextChanged(1, desired=Desired.STOPPED))
    assert not any(isinstance(effect, Work) for effect in owner.drain())
    owner.dispatch(one.key, Result(work.operation, 2, allocated=work.resource))
    effects = owner.drain()
    assert any(isinstance(effect, Work) and effect.operation.key == two.key for effect in effects)
    assert owner.snapshot(one.key).carrier is None


def test_late_completion_does_not_register_removed_actor():
    owner = ConnectionSupervisor("epoch")
    state = actor("one")
    owner.register(state)
    owner.tick(0)
    work = owner.drain()[0]
    owner.retire(state.key, 1)
    owner.dispatch(state.key, Result(work.operation, 2, allocated=work.resource))
    assert owner.snapshot(state.key).desired is Desired.STOPPED
    with pytest.raises(ValueError):
        owner.register(state)


def test_actor_budget_fails_explicitly():
    owner = ConnectionSupervisor("epoch", Policy(max_actors=1))
    owner.register(actor("one"))
    with pytest.raises(CapacityExceeded):
        owner.register(actor("two"))


def test_resource_identifiers_are_distinct_across_profiles_and_scopes():
    owner = ConnectionSupervisor("epoch")
    owner.register(actor("one"))
    owner.register(actor("two"))
    owner.tick(0)
    work = owner.drain()
    assert work[0].resource != work[1].resource


def test_private_state_snapshot_is_immutable():
    owner = ConnectionSupervisor("epoch")
    state = actor("one")
    owner.register(state)
    with pytest.raises(AttributeError):
        owner.snapshot(state.key).desired = Desired.STOPPED
