"""Pure lifecycle decisions. Every deadline is driven by an explicit input."""

from dataclasses import replace
from hashlib import sha256

from .model import (
    Adopted, Bridge, Cancel, Carrier, ConnectionState, ContextChanged, Desired, Event,
    Effect, Execution, Failed, Failure, Health, Observed, Operation, Phase, Resource,
    Result, Retire, Step, Tick, Transition, Work,
)

NEXT_PHASE = {
    Phase.REQUEST: Phase.WAIT_OFFER,
    Phase.WAIT_REQUEST: Phase.GATHER_OFFER,
    Phase.GATHER_OFFER: Phase.PUBLISH_OFFER,
    Phase.PUBLISH_OFFER: Phase.WAIT_ANSWER,
    Phase.WAIT_ANSWER: Phase.APPLY_ANSWER,
    Phase.WAIT_OFFER: Phase.GATHER_ANSWER,
    Phase.GATHER_ANSWER: Phase.PUBLISH_ANSWER,
    Phase.PUBLISH_ANSWER: Phase.CHECKING,
    Phase.APPLY_ANSWER: Phase.CHECKING,
    Phase.CHECKING: Phase.ATTACH,
    Phase.ATTACH: Phase.PATH,
}
POLL_PHASES = frozenset({Phase.WAIT_REQUEST, Phase.WAIT_OFFER, Phase.WAIT_ANSWER,
                         Phase.CHECKING, Phase.PATH})
BLOCKING_FAILURES = frozenset({Failure.CONFIGURATION, Failure.REVOKED,
                              Failure.UNSUPPORTED, Failure.INTERNAL})


def _work(state: ConnectionState, phase: Phase, resource: Resource, now: float,
          deadline: float | None = None) -> Transition:
    sequence = state.sequence + 1
    operation = Operation(state.runtime_epoch, state.key, state.generation,
                          state.authority.revision, sequence)
    timeout = (state.policy.gather_timeout if phase in
               {Phase.GATHER_OFFER, Phase.GATHER_ANSWER} else state.policy.phase_timeout)
    if phase is Phase.INSPECT:
        timeout = min(timeout, state.policy.poll_interval)
    deadline = now + timeout if deadline is None else deadline
    step = Step(phase, resource, deadline, now, operation)
    return Transition(replace(state, sequence=sequence, negotiation=step, reason=phase.value),
                      (Work(operation, phase, resource, deadline),), phase.value)


def _cancel(state: ConnectionState) -> tuple[Effect, ...]:
    step = state.negotiation
    if step is None:
        return ()
    effects: tuple[Effect, ...] = (Cancel(step.operation),) if step.operation else ()
    if state.carrier is None or state.carrier.resource != step.resource:
        effects += (Retire(step.resource),)
    return effects


def _failure(state: ConnectionState, now: float, reason: str,
             blocked: bool = False, retry_after: float = 0, jitter: float = 0) -> Transition:
    delay = state.policy.backoff[min(state.failures, len(state.policy.backoff) - 1)]
    delay = min(state.policy.backoff[-1], delay * (1 + state.policy.jitter_fraction * jitter))
    effects = _cancel(state)
    if state.negotiation and state.negotiation.phase is Phase.INSPECT and state.carrier:
        carrier = state.carrier
        state = replace(state, carrier=replace(carrier, health=Health.SUSPECT,
                        observed_at=carrier.observed_at if carrier.health is Health.SUSPECT else now))
    return Transition(replace(state, negotiation=None, failures=state.failures + 1,
                              retry_at=now + max(delay, retry_after), blocked=blocked,
                              reason=reason), effects, reason)


def _eligible(state: ConnectionState) -> bool:
    return (state.desired is Desired.ENABLED and state.execution is Execution.AVAILABLE
            and state.authority.authorized)


def _tick(state: ConnectionState, event: Tick) -> Transition:
    if not _eligible(state):
        return Transition(state, reason="ineligible")
    carrier = state.carrier
    if (carrier and carrier.health is Health.SUSPECT
            and event.now - carrier.observed_at >= state.policy.disconnect_grace):
        result = _failure(replace(state, carrier=None), event.now, "carrier_lost")
        return replace(result, effects=(Retire(carrier.resource),) + result.effects)
    step = state.negotiation
    if step:
        if event.now >= step.deadline:
            return _failure(state, event.now, "phase_timeout", jitter=event.jitter)
        if step.operation is None and event.now >= step.poll_at:
            return _work(state, step.phase, step.resource, event.now, step.deadline)
        return Transition(state, reason="pending")
    if carrier:
        if (event.now >= max(state.inspect_at, state.retry_at) and not state.blocked
                and (carrier.health is Health.SUSPECT or carrier.bridge is Bridge.READY)):
            return _work(state, Phase.INSPECT, carrier.resource, event.now)
        if carrier.health is Health.SUSPECT:
            return Transition(state, reason="health_unknown")
        if carrier.bridge is Bridge.READY:
            return Transition(state, reason="ready")
        if event.now >= state.retry_at and not state.blocked:
            return _work(state, Phase.ATTACH, carrier.resource, event.now)
        return Transition(state, reason="bridge_retry_wait")
    if state.blocked or event.now < state.retry_at:
        return Transition(state, reason="blocked" if state.blocked else "retry_wait")
    state = replace(state, generation=state.generation + 1)
    key = state.key
    binding = repr((key.scope, key.profile_id, key.local_device, key.remote_device))
    actor = sha256(binding.encode("utf-8")).hexdigest()[:24]
    resource = Resource(state.adapter_epoch,
                        f"connection-{state.runtime_epoch}-{actor}-{state.generation}")
    return _work(state, Phase.DISCOVER, resource, event.now)


def _context(state: ConnectionState, event: ContextChanged) -> Transition:
    if event.authority and event.authority.revision < state.authority.revision:
        return Transition(state, reason="stale_authority")
    changed = {name: getattr(event, name) for name in
               ("authority", "desired", "execution", "network_available")
               if getattr(event, name) is not None}
    new = replace(state, **changed)
    authority_changed = new.authority != state.authority
    if not _eligible(new):
        effects = _cancel(state)
        if state.carrier:
            effects += (Retire(state.carrier.resource),)
        return Transition(replace(new, negotiation=None, carrier=None, reason="ineligible"),
                          effects, "ineligible")
    effects = ()
    if new.authority.revision != state.authority.revision:
        effects = _cancel(state)
        # A new consent revision must be revalidated before retaining a carrier.
        if state.carrier:
            effects += (Retire(state.carrier.resource),)
        new = replace(new, negotiation=None, carrier=None, blocked=False)
    elif authority_changed or new.desired != state.desired:
        new = replace(new, blocked=False)
    if not new.network_available and new.negotiation:
        effects += _cancel(new)
        new = replace(new, negotiation=None, reason="network_unavailable")
    return Transition(new, effects, "context_changed")


def _stale(state: ConnectionState, event: Result | Failed | Adopted) -> Transition:
    effects: tuple[Effect, ...] = ()
    if event.allocated:
        owned = ((state.carrier and state.carrier.resource == event.allocated)
                 or (state.negotiation and state.negotiation.resource == event.allocated))
        if not owned:
            effects = (Retire(event.allocated),)
    return Transition(state, effects, "stale_completion")


def _result(state: ConnectionState, event: Result | Failed | Adopted) -> Transition:
    step = state.negotiation
    if step is None or step.operation != event.operation:
        return _stale(state, event)
    if event.now >= step.deadline:
        result = _failure(state, event.now, "phase_timeout")
        if event.allocated and event.allocated != step.resource:
            result = replace(result, effects=result.effects + (Retire(event.allocated),))
        return result
    if isinstance(event, Adopted):
        if (step.phase is not Phase.DISCOVER or state.carrier is not None
                or event.allocated.adapter_epoch != state.adapter_epoch or not _eligible(state)):
            result = _failure(state, event.now, "invalid_adoption", blocked=True)
            return replace(result, effects=result.effects + (Retire(event.allocated),))
        # Verified identity does not prove the carrier is open or has a route.
        state = replace(state, carrier=Carrier(event.allocated, state.authority.revision,
                        Health.SUSPECT, Bridge.DETACHED, event.now), negotiation=None)
        return _work(state, Phase.INSPECT, event.allocated, event.now)
    if (isinstance(event, Failed) and step.phase is Phase.DISCOVER and event.allocated
            and event.allocated.adapter_epoch == state.adapter_epoch):
        # A claim may succeed before a cancellation or transport failure. Its
        # handle differs from the discovery placeholder and still needs cleanup.
        result = _failure(state, event.now, event.failure.value,
                          event.failure in BLOCKING_FAILURES, event.retry_after, event.jitter)
        return replace(result, effects=result.effects + (Retire(event.allocated),))
    if event.allocated and event.allocated != step.resource:
        result = _failure(state, event.now, "wrong_resource", blocked=True)
        return replace(result, effects=result.effects + (Retire(event.allocated),))
    if isinstance(event, Failed):
        return _failure(state, event.now, event.failure.value,
                        event.failure in BLOCKING_FAILURES, event.retry_after, event.jitter)
    if step.phase is Phase.DISCOVER:
        if not state.network_available or not state.authority.signaling_available:
            reason = "network_unavailable" if not state.network_available else "signaling_unavailable"
            return Transition(replace(state, negotiation=None, reason=reason,
                              retry_at=event.now + state.policy.poll_interval), reason=reason)
        phase = Phase.REQUEST if state.authority.preferred else Phase.WAIT_REQUEST
        return _work(state, phase, step.resource, event.now)
    if step.phase is Phase.INSPECT:
        if event.observed_health is None or event.observed_bridge is None:
            return _failure(state, event.now, "missing_observation", blocked=True)
        state = replace(state, negotiation=None, inspect_at=event.now + state.policy.poll_interval)
        return _observed(state, Observed(step.resource, event.now,
                                        event.observed_health, event.observed_bridge))
    if event.pending:
        if step.phase not in POLL_PHASES:
            return _failure(state, event.now, "invalid_pending", blocked=True)
        return Transition(replace(state, negotiation=replace(step, operation=None,
                          poll_at=event.now + state.policy.poll_interval)), reason="poll_wait")
    if step.phase is Phase.CHECKING:
        if not event.verified or event.allocated != step.resource:
            return _failure(state, event.now, "unverified_resource", blocked=True)
        state = replace(state, carrier=Carrier(step.resource, state.authority.revision,
                        Health.OPEN, Bridge.ATTACHING, event.now))
    if step.phase is Phase.ATTACH:
        if not state.carrier or state.carrier.resource != step.resource:
            return _failure(state, event.now, "missing_carrier", blocked=True)
        state = replace(state, carrier=replace(state.carrier, bridge=Bridge.PATH_PENDING))
    if step.phase is Phase.PATH:
        if not state.carrier or state.carrier.resource != step.resource:
            return _failure(state, event.now, "missing_carrier", blocked=True)
        return Transition(replace(state, negotiation=None, failures=0, retry_at=0,
                          inspect_at=event.now + state.policy.poll_interval,
                          carrier=replace(state.carrier, bridge=Bridge.READY,
                                          observed_at=event.now), reason="ready"), reason="ready")
    return _work(state, NEXT_PHASE[step.phase], step.resource, event.now)


def _observed(state: ConnectionState, event: Observed) -> Transition:
    carrier = state.carrier
    if carrier is None or carrier.resource != event.resource or event.now < carrier.observed_at:
        return Transition(state, reason="stale_observation")
    if event.health in {Health.ABSENT, Health.CLOSING}:
        result = _failure(replace(state, carrier=None), event.now, "carrier_lost")
        return replace(result, effects=(Retire(carrier.resource),) + result.effects)
    observed_at = (carrier.observed_at if carrier.health is event.health is Health.SUSPECT
                   else event.now)
    bridge = event.bridge
    # Health reports can invalidate readiness, never establish path evidence.
    if bridge is Bridge.READY and carrier.bridge is not Bridge.READY:
        bridge = carrier.bridge
    carrier = replace(carrier, health=event.health, bridge=bridge, observed_at=observed_at)
    state = replace(state, carrier=carrier)
    if (event.health is Health.OPEN and bridge is Bridge.DETACHED
            and state.negotiation is None and _eligible(state)):
        state = replace(state, carrier=replace(carrier, bridge=Bridge.RESTORING))
        if event.now >= state.retry_at and not state.blocked:
            return _work(state, Phase.ATTACH, carrier.resource, event.now)
    return Transition(state, reason="observed")


def transition(state: ConnectionState, event: Event) -> Transition:
    """Exhaustive event classification; untrusted mappings are never events."""
    if isinstance(event, (Tick, Failed)) and not 0 <= event.jitter <= 1:
        raise ValueError("Jitter input must be between zero and one")
    if isinstance(event, Tick):
        return _tick(state, event)
    if isinstance(event, ContextChanged):
        return _context(state, event)
    if isinstance(event, (Result, Failed, Adopted)):
        return _result(state, event)
    if isinstance(event, Observed):
        return _observed(state, event)
    raise TypeError("Unsupported connection event")
