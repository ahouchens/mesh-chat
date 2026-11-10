from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Adopted, Authority, Bridge, Carrier, ConnectionKey, ConnectionState, ContextChanged, Desired,
    Failed, Failure, Health, Observed, Operation, Policy, Resource, Result, Retire, Tick, Work,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor, CapacityExceeded


def actor(name, **changes):
    return replace(ConnectionState(ConnectionKey("personal", name, "local", None),
                   "epoch", Authority(1, True, True, True), Desired.ENABLED), **changes)


def prepared_owner():
    owner = ConnectionSupervisor("epoch")
    resource = Resource("native", "exact-carrier")
    state = replace(actor("prepared"), key=ConnectionKey("contact", "prepared", "local", "remote"),
        carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 5))
    owner.register(state)
    admission = owner.prepare_carrier_retirement(state.key, resource, 0, 1, 5)
    return owner, state, admission


def test_only_actual_current_carrier_surrender_is_owner_retirement_witness():
    owner, state, admission = prepared_owner()
    owner.dispatch(state.key, Observed(admission.resource, 4, Health.ABSENT, Bridge.DETACHED))
    assert not admission.retired
    owner.tick(6)
    work, = owner.drain()
    stale = replace(work.operation, sequence=work.operation.sequence + 1)
    owner.dispatch(state.key, Result(stale, 7, allocated=admission.resource,
        observed_health=Health.ABSENT, observed_bridge=Bridge.DETACHED))
    assert not admission.retired and owner.snapshot(state.key).carrier is not None
    owner.dispatch(state.key, Result(work.operation, 8,
        observed_health=Health.ABSENT, observed_bridge=Bridge.DETACHED))
    assert admission.retired and Retire(admission.resource) in owner.drain()


def test_same_revision_authorization_denial_invalidates_instead_of_certifying_cleanup():
    owner, state, admission = prepared_owner()
    owner.dispatch(state.key, ContextChanged(6, authority=replace(state.authority, authorized=False)))
    assert admission.invalidated and not admission.retired
    assert Retire(admission.resource) in owner.drain()


def test_prepared_target_rejects_handoff_before_acceptance_without_holding_candidate():
    from test_pairing_runtime import ready_handoff
    owner, source = ready_handoff()
    resource = Resource("native", "current-target")
    state = replace(actor("target"), key=ConnectionKey("contact", "target", "local", "remote"),
        carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 0))
    owner.register(state)
    admission = owner.prepare_carrier_retirement(state.key, resource, 0, 1, .2)
    candidate = Resource("native", "replacement-candidate")
    assert not owner.commit_handoff(source.operation, candidate, state.key, .3)
    assert owner._handoffs[source.operation].target is None
    assert candidate not in owner._retiring and owner.snapshot(state.key).carrier.resource == resource
    owner.release_carrier_retirement(admission, .4, invalidated=True)
    assert owner.commit_handoff(source.operation, candidate, state.key, .5)


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


def test_discovery_cannot_readopt_a_carrier_awaiting_exact_cleanup():
    owner = ConnectionSupervisor("epoch")
    resource = Resource("native", "physical-manual-carrier")
    state = actor("one", carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 0))
    owner.register(state)
    owner.dispatch(state.key, ContextChanged(1, authority=Authority(2, True, True, True)))
    assert Retire(resource) in owner.drain()
    owner.tick(2)
    discovery = owner.drain()[0]
    owner.dispatch(state.key, Adopted(discovery.operation, 3, resource))
    assert owner.snapshot(state.key).carrier is None
    assert not owner.snapshot(state.key).blocked
    owner.resource_released(resource)
    owner.tick(20)
    discovery = next(effect for effect in owner.drain() if isinstance(effect, Work))
    owner.dispatch(state.key, Adopted(discovery.operation, 21, Resource("native", "new-physical")))
    assert owner.snapshot(state.key).carrier.resource.resource_id == "new-physical"


@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("completion", ["result", "failed", "adopted"])
@pytest.mark.parametrize("other_status", ["negotiating", "cancelled", "ready"])
def test_misrouted_allocation_cannot_retire_another_profiles_resource(stale, completion, other_status):
    owner = ConnectionSupervisor("epoch")
    one, two = actor("one"), actor("two")
    if other_status == "ready":
        two = replace(two, carrier=Carrier(Resource("native", "ready-carrier"),
                                          1, Health.OPEN, Bridge.READY, 0))
    owner.register(one)
    owner.register(two)
    owner.tick(0)
    first, second = owner.drain()
    if other_status == "cancelled":
        owner.retire(two.key, 1)
    elif other_status == "ready":
        owner.dispatch(two.key, Result(second.operation, 1,
                       observed_health=Health.OPEN, observed_bridge=Bridge.READY))
    owner.drain()
    other_before = owner.snapshot(two.key)
    if stale:
        owner.retire(one.key, 1)
        owner.drain()
    event = {"failed": Failed(first.operation, 2, Failure.TRANSIENT, allocated=second.resource),
             "result": Result(first.operation, 2, allocated=second.resource),
             "adopted": Adopted(first.operation, 2, second.resource)}[completion]
    owner.dispatch(one.key, event)
    assert Retire(second.resource) not in owner.drain()
    assert owner.snapshot(two.key) == other_before
    if not stale:
        assert owner.snapshot(one.key).blocked
