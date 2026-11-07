"""INV02/03/05: interrupt every reachable phase, including both offer roles.

This is deterministic production-reducer evidence, not native disposal or
packaged Windows/Android parity. States come from actual successful traces.
"""

from dataclasses import replace

import pytest

from mesh_chat.connection.model import (
    Adopted, Authority, Bridge, Cancel, ConnectionKey, ConnectionState, ContextChanged,
    Desired, Execution, Failed, Failure, Health, Phase, Resource, Result, Retire, Tick, Work,
)
from mesh_chat.connection.reducer import transition


def reachable_phases():
    phases = {}
    for preferred in (False, True):
        state = ConnectionState(ConnectionKey("personal", "profile", "local", "remote"),
                                "runtime", Authority(1, True, True, preferred), desired=Desired.ENABLED)
        state = transition(state, Tick(0)).state
        for _ in range(len(Phase)):
            step = state.negotiation
            assert step is not None
            phases.setdefault(step.phase, state)
            if step.phase is Phase.INSPECT:
                break
            now = step.poll_at + 0.1
            state = transition(state, Result(step.operation, now,
                allocated=step.resource if step.phase is Phase.CHECKING else None,
                verified=step.phase is Phase.CHECKING)).state
            if state.negotiation is None:
                assert state.carrier is not None and state.carrier.bridge is Bridge.READY
                state = transition(state, Tick(state.inspect_at)).state
        else:
            pytest.fail("Successful trace did not reach carrier inspection")
    assert set(phases) == set(Phase), "A new phase needs an executing trace"
    return phases


@pytest.fixture(scope="module")
def phases():
    return reachable_phases()


def interruption(state, name):
    now = state.negotiation.poll_at + 0.2
    authority = state.authority
    changes = {
        "stop": {"desired": Desired.STOPPED},
        "lock": {"execution": Execution.LOCKED},
        "pause": {"execution": Execution.PAUSED},
        "shutdown": {"execution": Execution.SHUTTING_DOWN},
        "revocation": {"authority": replace(authority, revision=authority.revision + 1, authorized=False)},
        "consent_revision": {"authority": replace(authority, revision=authority.revision + 1)},
        "partition": {"network_available": False},
    }
    return ContextChanged(now, **changes[name])


def late_completion(state, kind, now):
    step = state.negotiation
    if kind == "success":
        return Result(step.operation, now, allocated=step.resource, verified=True,
                      observed_health=Health.OPEN, observed_bridge=Bridge.READY)
    if kind == "failure":
        return Failed(step.operation, now, Failure.TRANSIENT, allocated=step.resource)
    return Adopted(step.operation, now, Resource(state.adapter_epoch, "late-adoption"))


@pytest.mark.parametrize("phase", list(Phase), ids=lambda phase: phase.value)
@pytest.mark.parametrize("ending", ["stop", "lock", "pause", "shutdown", "revocation", "consent_revision", "partition"])
@pytest.mark.parametrize("completion", ["success", "failure", "adoption"])
def test_every_phase_fences_late_completion_and_exact_resource_disposal(phases, phase, ending, completion):
    state = phases[phase]
    event = interruption(state, ending)
    cancelled = transition(state, event)
    assert cancelled.state.negotiation is None
    assert Cancel(state.negotiation.operation) in cancelled.effects
    assert not any(isinstance(effect, Work) for effect in cancelled.effects)
    if ending != "partition":
        assert cancelled.state.carrier is None
    else:
        # A network fact alone does not prove a retained carrier has died.
        assert cancelled.state.carrier == state.carrier

    late = late_completion(state, completion, event.now + 0.1)
    result = transition(cancelled.state, late)
    assert result.state == cancelled.state
    assert result.reason == "stale_completion"
    owned = cancelled.state.carrier and cancelled.state.carrier.resource == late.allocated
    assert result.effects == (() if owned else (Retire(late.allocated),))

    # Restoring consent/execution may begin a replacement. An old completion
    # cannot cancel its work, change readiness, or retire its exact resource.
    restored = transition(cancelled.state, ContextChanged(event.now + 0.2,
        authority=replace(state.authority, revision=state.authority.revision + 2),
        desired=Desired.ENABLED, execution=Execution.AVAILABLE, network_available=True)).state
    replacement = transition(restored, Tick(event.now + 0.3)).state
    assert replacement.negotiation is not None
    assert replacement.negotiation.operation != state.negotiation.operation
    fenced = transition(replacement, replace(late, now=event.now + 0.4))
    assert fenced.state == replacement
    assert Retire(replacement.negotiation.resource) not in fenced.effects
    assert not any(isinstance(effect, (Work, Cancel)) for effect in fenced.effects)
