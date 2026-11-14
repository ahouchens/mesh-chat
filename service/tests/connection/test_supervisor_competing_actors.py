"""Deterministic scheduler evidence for INV01/INV14 and part of SC02/SC13.

Completion events stand in for effects; this does not exercise signed signaling.
"""

from mesh_chat.connection.model import (
    Authority, ConnectionKey, ConnectionState, Desired, Phase, Policy, Result, Work,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor


def test_competing_actors_keep_exact_resources_and_finite_fair_admission():
    policy = Policy(max_workers=2)
    owner = ConnectionSupervisor("current-runtime", policy)
    keys = (
        ConnectionKey("contact", "profile-a", "device-a", "peer-1"),
        ConnectionKey("contact", "profile-a", "device-a", "peer-2"),
        ConnectionKey("contact", "profile-a", "device-b", "peer-1"),
        ConnectionKey("workspace", "profile-a", "device-a", "peer-3"),
        ConnectionKey("personal", "profile-b", "device-c", "peer-4"),
        ConnectionKey("workspace", "profile-b", "device-c", "peer-5"),
    )
    for index, key in enumerate(keys):
        owner.register(ConnectionState(key, owner.runtime_epoch,
            Authority(1, True, True, index % 2 == 0), Desired.ENABLED))

    owner.tick(0)
    inflight = {}
    resources = {}
    admissions = {key: 0 for key in keys}
    first_admitted_at = {}
    second_admitted_at = {}
    slot_releases = 0

    def admit(effects):
        assert all(isinstance(effect, Work) for effect in effects)
        for work in effects:
            key = work.operation.key
            assert key not in inflight
            assert work.operation.runtime_epoch == owner.runtime_epoch
            state = owner.snapshot(key)
            assert state.negotiation is not None
            assert state.negotiation.operation == work.operation
            assert state.negotiation.resource == work.resource
            if key in resources:
                assert resources[key] == work.resource
            else:
                assert work.resource not in resources.values()
                resources[key] = work.resource
                first_admitted_at[key] = slot_releases
            admissions[key] += 1
            if admissions[key] == 2:
                second_admitted_at[key] = slot_releases
            inflight[key] = work
        assert len(inflight) <= policy.max_workers

    admit(owner.drain())
    assert set(inflight) == set(keys[:policy.max_workers])
    assert all(work.phase is Phase.DISCOVER for work in inflight.values())

    def complete_oldest(now):
        nonlocal slot_releases
        key = next(iter(inflight))
        work = inflight.pop(key)
        owner.dispatch(key, Result(work.operation, now))
        slot_releases += 1
        admit(owner.drain())
        return work

    first = complete_oldest(0.1)
    assert owner.snapshot(first.operation.key).negotiation.phase is Phase.REQUEST
    assert set(inflight) == {keys[1], keys[2]}

    # The old result cannot create a second attempt or disturb another key.
    before = {key: owner.snapshot(key).negotiation for key in keys}
    owner.dispatch(first.operation.key, Result(first.operation, 0.11))
    assert owner.drain() == ()
    assert {key: owner.snapshot(key).negotiation for key in keys} == before
    assert len(set(resources.values())) == len(resources)

    second = complete_oldest(0.2)
    assert owner.snapshot(second.operation.key).negotiation.phase is Phase.WAIT_REQUEST

    # With two active reservations, each completion must serve the next waiting
    # actor before a continuation. This bound is independent of phase details.
    first_admission_bound = len(keys) - policy.max_workers
    for index in range(2, first_admission_bound):
        complete_oldest((index + 1) / 10)
    assert set(first_admitted_at) == set(keys)
    assert max(first_admitted_at.values()) <= first_admission_bound
    assert len(resources) == len(keys)
    assert all(count == 1 for count in admissions.values())

    # Continue releasing slots. Every eligible actor receives a second turn
    # within one more full actor rotation, with its original exact resource.
    for index in range(len(keys)):
        complete_oldest((first_admission_bound + index + 1) / 10)
    assert set(second_admitted_at) == set(keys)
    assert max(second_admitted_at.values()) <= first_admission_bound + len(keys)
    assert len(set(resources.values())) == len(keys)
