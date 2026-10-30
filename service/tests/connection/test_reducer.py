from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Authority, Bridge, Carrier, ConnectionKey, ConnectionState, ContextChanged,
    Desired, Execution, Failed, Failure, Health, Observed, Phase, Policy,
    Resource, Result, Step, Tick, Work,
)
from mesh_chat.connection.reducer import transition


def initial(**changes):
    state = ConnectionState(
        key=ConnectionKey("personal", "profile-1", "local", "remote"),
        runtime_epoch="runtime-1", authority=Authority(1, True, True, True),
        desired=Desired.ENABLED,
    )
    return replace(state, **changes)


def begin(state=None, now=0):
    result = transition(state or initial(), Tick(now))
    return result.state, next(effect for effect in result.effects if isinstance(effect, Work))


def complete(state, work, now=1, **kwargs):
    return transition(state, Result(work.operation, now, **kwargs))


def test_initial_negotiation_obeys_deterministic_roles():
    state, work = begin()
    assert work.phase is Phase.REQUEST
    assert state.negotiation.phase is Phase.REQUEST
    other = initial(authority=Authority(1, True, True, False))
    assert begin(other)[1].phase is Phase.WAIT_REQUEST


def test_offline_wait_does_not_allocate_work():
    state = initial(network_available=False)
    result = transition(state, Tick(0))
    assert result.state.reason == "network_unavailable"
    assert result.effects == ()


def test_phase_deadline_starts_after_previous_step_finishes():
    state, work = begin()
    result = complete(state, work, now=20)
    assert result.state.negotiation.phase is Phase.WAIT_OFFER
    assert result.state.negotiation.deadline == 20 + Policy().phase_timeout


def test_polling_keeps_deadline_and_releases_worker():
    state, work = begin()
    result = complete(state, work)
    state, poll = result.state, result.effects[0]
    result = complete(state, poll, now=2, pending=True)
    assert result.effects == ()
    assert result.state.negotiation.deadline == state.negotiation.deadline
    assert result.state.negotiation.operation is None
    assert transition(result.state, Tick(3)).effects == ()
    assert transition(result.state, Tick(7)).effects[0].phase is Phase.WAIT_OFFER


@pytest.mark.parametrize("execution", [Execution.LOCKED, Execution.PAUSED, Execution.SHUTTING_DOWN])
def test_execution_denial_cancels_without_retry(execution):
    state, work = begin()
    result = transition(state, ContextChanged(1, execution=execution))
    assert result.state.negotiation is None
    assert all(not isinstance(effect, Work) for effect in result.effects)
    late = transition(result.state, Result(work.operation, 2, allocated=work.resource))
    assert late.state.carrier is None
    assert late.effects[0].resource == work.resource


def test_stop_immediately_fences_late_success():
    state, work = begin()
    stopped = transition(state, ContextChanged(1, desired=Desired.STOPPED)).state
    late = complete(stopped, work, allocated=work.resource)
    assert late.state.desired is Desired.STOPPED
    assert late.state.carrier is None
    assert late.reason == "stale_completion"
    assert late.effects[0].resource == work.resource


def test_wrong_runtime_or_policy_cannot_advance():
    state, work = begin()
    for operation in (replace(work.operation, runtime_epoch="old"),
                      replace(work.operation, policy_revision=0)):
        result = transition(state, Result(operation, 1))
        assert result.state == state
        assert not result.effects


def test_revocation_retires_only_the_owned_resource():
    carrier = Carrier(Resource("adapter-1", "carrier-1"), 1, Health.OPEN, Bridge.READY, 0)
    state = initial(carrier=carrier)
    result = transition(state, ContextChanged(1, authority=Authority(2, False, False, True)))
    assert result.state.carrier is None
    assert result.effects[0].resource == carrier.resource
    assert all(not isinstance(effect, Work) for effect in result.effects)


def test_mailbox_loss_preserves_authorized_ready_carrier():
    carrier = Carrier(Resource("adapter-1", "carrier-1"), 1, Health.OPEN, Bridge.READY, 0)
    state = initial(carrier=carrier)
    result = transition(state, ContextChanged(1, authority=Authority(1, True, False, True)))
    assert result.state.carrier == carrier
    assert result.effects == ()


def test_network_hint_preserves_carrier_until_confirmed_loss():
    carrier = Carrier(Resource("adapter-1", "carrier-1"), 1, Health.OPEN, Bridge.READY, 0)
    state = initial(carrier=carrier)
    result = transition(state, ContextChanged(1, network_available=False))
    assert result.state.carrier == carrier
    assert all(effect.__class__.__name__ != "Retire" for effect in result.effects)


def test_health_event_uses_resource_identity_after_attempt_finishes():
    resource = Resource("adapter-1", "carrier-1")
    state = initial(carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 0))
    result = transition(state, Observed(resource, 2, Health.OPEN, Bridge.DETACHED))
    assert result.state.carrier.health is Health.OPEN
    assert result.state.carrier.bridge is Bridge.RESTORING
    assert result.effects[0].phase is Phase.ATTACH


def test_stale_resource_health_cannot_detach_replacement():
    resource = Resource("adapter-1", "replacement")
    state = initial(carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 0))
    result = transition(state, Observed(Resource("adapter-1", "old"), 2, Health.ABSENT, Bridge.DETACHED))
    assert result.state == state
    assert result.effects == ()


def test_readiness_requires_verified_binding_and_path():
    state, work = begin()
    for phase in (Phase.REQUEST, Phase.WAIT_OFFER, Phase.GATHER_ANSWER, Phase.PUBLISH_ANSWER):
        assert work.phase is phase
        result = complete(state, work)
        state, work = result.state, result.effects[0]
    assert work.phase is Phase.CHECKING
    rejected = complete(state, work, allocated=work.resource)
    assert rejected.state.carrier is None
    assert rejected.reason == "unverified_resource"
    result = complete(state, work, allocated=work.resource, verified=True)
    state, work = result.state, result.effects[0]
    assert state.carrier.bridge is Bridge.ATTACHING
    assert work.phase is Phase.ATTACH
    result = complete(state, work)
    state, work = result.state, result.effects[0]
    assert work.phase is Phase.PATH
    assert state.carrier.bridge is Bridge.PATH_PENDING
    result = complete(state, work)
    assert result.state.carrier.bridge is Bridge.READY
    assert result.state.negotiation is None
    assert result.effects == ()
    duplicate = complete(result.state, work, allocated=work.resource)
    assert duplicate.effects == ()
    assert duplicate.state.carrier == result.state.carrier


def test_backoff_is_capped_and_manual_wakes_cannot_bypass_cooldown():
    state, work = begin()
    failed = transition(state, Failed(work.operation, 1, Failure.RATE_LIMITED, retry_after=90))
    assert failed.state.retry_at == 91
    assert transition(failed.state, Tick(20)).effects == ()
    assert transition(failed.state, Tick(91)).effects


def test_timeout_uses_monotonic_deadline_and_fences_late_creation():
    state, work = begin()
    result = transition(state, Tick(46))
    assert result.state.negotiation is None
    assert result.reason == "phase_timeout"
    late = complete(result.state, work, now=47, allocated=work.resource)
    assert late.effects[0].resource == work.resource


def test_identical_trace_produces_identical_outputs():
    events = [Tick(0), ContextChanged(1, network_available=False), Tick(100),
              ContextChanged(101, network_available=True), Tick(102)]
    def replay():
        state = initial()
        outputs = []
        for event in events:
            result = transition(state, event)
            outputs.append(result)
            state = result.state
        return outputs
    assert replay() == replay()


def test_unknown_input_is_rejected():
    with pytest.raises(TypeError):
        transition(initial(), {"type": "grant_trust"})
