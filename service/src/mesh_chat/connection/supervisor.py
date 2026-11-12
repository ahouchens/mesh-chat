"""Serialized actor ownership and fair, bounded admission; no external I/O."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from math import isfinite
from threading import RLock

from .diagnostics import Diagnostics, validated_pairing_retirement
from .model import (
    Adopted, Bridge, Cancel, ConnectionKey, ConnectionState, ContextChanged, Desired, Event,
    Execution, Failed, Failure, Health, HandoffLease, Operation, Phase, Policy, Resource, Result, Retire, Tick, Work,
)
from .reducer import transition


class CapacityExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class _PairingRetirement:
    operation: Operation
    source: Resource
    phase: Phase
    event: str
    reason: str
    gather_work: Work | None = None
    gather_deadline: float | None = None
    gather_failed_at: float | None = None


@dataclass
class _PairingTrace:
    source: Work | None = None
    last_work: Work | None = None
    retirement: _PairingRetirement | None = None


@dataclass(eq=False)
class _CarrierRetirementAdmission:
    key: ConnectionKey
    resource: Resource
    generation: int
    revision: int
    successor: int | None = None
    retired: bool = False
    invalidated: bool = False


class ConnectionSupervisor:
    def __init__(self, runtime_epoch: str, policy: Policy = Policy()):
        self.runtime_epoch = runtime_epoch
        self.policy = policy
        self._lock = RLock()
        self._states: dict[ConnectionKey, ConnectionState] = {}
        self._pending: OrderedDict[ConnectionKey, Work] = OrderedDict()
        self._running = {}
        self._control = OrderedDict()
        self._retired = set()
        self._retiring = set()
        self._handoffs: dict[Operation, HandoffLease] = {}
        self._surrendered = {}
        self._handoff_committed = set()
        # One trace per already registered pairing actor, never per poll/result.
        # Bindings stay private; the shared payload-free Record ring is unchanged.
        self._pairing_traces: dict[ConnectionKey, _PairingTrace] = {}
        self._carrier_retirements: dict[ConnectionKey, _CarrierRetirementAdmission] = {}
        self._committing_retirement: _CarrierRetirementAdmission | None = None
        self.diagnostics = Diagnostics(policy.max_diagnostics)

    def register(self, state: ConnectionState):
        with self._lock:
            if state.key in self._states or state.runtime_epoch != self.runtime_epoch:
                raise ValueError("Connection owner already exists or epoch mismatch")
            if len(self._states) >= self.policy.max_actors:
                raise CapacityExceeded("Connection actor capacity reached")
            self._states[state.key] = replace(state, policy=self.policy)
            if state.key.scope == "pairing":
                self._pairing_traces[state.key] = _PairingTrace()

    def snapshot(self, key: ConnectionKey):
        with self._lock:
            return self._states[key]

    def retire_current_carrier(self, key, resource, generation, revision, now):
        """Compare the current owner and submit its normal retirement atomically."""
        with self._lock:
            state = self._states.get(key)
            if (state is None or state.runtime_epoch != self.runtime_epoch
                    or key.scope == "pairing" or key in self._retired
                    or state.generation != generation or state.authority.revision != revision
                    or not state.authority.authorized or state.desired is not Desired.ENABLED
                    or state.execution is not Execution.AVAILABLE
                    or state.carrier is None or state.carrier.resource != resource
                    or state.carrier.health is not Health.OPEN or state.carrier.bridge is not Bridge.READY
                    or resource in self._retiring or self._owned_elsewhere(key, resource)
                    or any(lease.resource == resource for lease in self._handoffs.values())
                    or (state.negotiation is not None and state.negotiation.phase is not Phase.INSPECT)):
                return False
            event = ContextChanged(now, desired=Desired.STOPPED)
            effects = transition(state, event).effects
            limit = self.policy.max_actors * 4 + self.policy.max_workers
            if (len(set(self._control) | set(effects)) > limit
                    or len(self._retiring | {effect.resource for effect in effects
                                            if isinstance(effect, Retire)}) > limit):
                return False
            self.dispatch(key, event)
            return True

    def snapshots(self):
        with self._lock:
            return tuple(self._states.values())

    def prepare_carrier_retirement(self, key, resource, generation, revision, now):
        """Admit one current owner without stopping its carrier or inspection."""
        with self._lock:
            state = self._states.get(key)
            if (state is None or key in self._carrier_retirements or key.scope != "contact"
                    or key in self._retired or state.runtime_epoch != self.runtime_epoch
                    or state.generation != generation or state.authority.revision != revision
                    or not state.authority.authorized or state.desired is not Desired.ENABLED
                    or state.execution is not Execution.AVAILABLE
                    or state.carrier is None or state.carrier.resource != resource
                    or state.carrier.health is not Health.OPEN or state.carrier.bridge is not Bridge.READY
                    or resource in self._retiring or self._owned_elsewhere(key, resource)
                    or any(lease.resource == resource or lease.target == key for lease in self._handoffs.values())
                    or (state.negotiation is not None and state.negotiation.phase is not Phase.INSPECT)):
                raise ValueError("Carrier retirement owner changed")
            admission = _CarrierRetirementAdmission(key, resource, generation, revision)
            self._carrier_retirements[key] = admission
            self.dispatch(key, ContextChanged(now, retirement_prepared=True))
            return admission

    def retirement_admission_valid(self, admission):
        with self._lock:
            state = self._states.get(admission.key)
            return bool(self._carrier_retirements.get(admission.key) is admission
                        and not admission.invalidated and state is not None
                        and state.runtime_epoch == self.runtime_epoch
                        and state.generation == admission.generation
                        and state.authority.revision in {admission.revision, admission.successor}
                        and state.execution is Execution.AVAILABLE
                        and (state.carrier is None or state.carrier.resource == admission.resource))

    def allow_retirement_projection(self, admission, revision):
        """The runtime has attested the one exact cleanup-derived revision."""
        with self._lock:
            state = self._states.get(admission.key)
            if (not self.retirement_admission_valid(admission) or not admission.retired
                    or admission.successor is not None or revision != admission.revision + 1
                    or state is None or state.carrier is not None
                    or state.authority.revision != admission.revision):
                return False
            admission.successor = revision
            return True

    def release_carrier_retirement(self, admission, now, *, invalidated=False):
        with self._lock:
            if invalidated:
                admission.invalidated = True
            if self._carrier_retirements.get(admission.key) is admission:
                del self._carrier_retirements[admission.key]
                self.dispatch(admission.key, ContextChanged(now, retirement_prepared=False))

    def commit_carrier_retirement(self, admission, now):
        with self._lock:
            if not self.retirement_admission_valid(admission):
                raise ValueError("Carrier retirement owner changed")
            state = self._states[admission.key]
            if admission.retired:
                if state.carrier is not None:
                    raise ValueError("Carrier retirement owner changed")
                return
            if (state.carrier is None or state.carrier.resource != admission.resource
                    or not state.authority.authorized or state.desired is not Desired.ENABLED):
                raise ValueError("Carrier retirement owner changed")
            self._committing_retirement = admission
            try:
                self.dispatch(admission.key, ContextChanged(now, desired=Desired.STOPPED))
            finally:
                self._committing_retirement = None

    def _observe_carrier_retirement(self, state, event, result):
        admission = self._carrier_retirements.get(state.key)
        if admission is None:
            return result
        invalid = (state.generation != admission.generation
                   or result.state.generation != admission.generation
                   or result.state.authority.revision not in {admission.revision, admission.successor}
                   or result.state.execution is not Execution.AVAILABLE
                   or (not result.state.authority.authorized
                       and result.state.authority.revision != admission.successor)
                   or (result.state.carrier is not None and result.state.carrier.resource != admission.resource))
        if isinstance(event, ContextChanged):
            projection = admission.retired and event.authority is not None and (
                event.authority.revision == admission.successor)
            invalid |= (event.desired is Desired.STOPPED and state.desired is not Desired.STOPPED
                        and self._committing_retirement is not admission and not projection)
        if invalid:
            admission.invalidated = True
            del self._carrier_retirements[state.key]
            return replace(result, state=replace(result.state, retirement_prepared=False))
        current = not isinstance(event, (Result, Failed, Adopted)) or (
            state.negotiation is not None and state.negotiation.operation == event.operation)
        if (current and state.carrier is not None and state.carrier.resource == admission.resource
                and result.state.carrier is None
                and Retire(admission.resource) in result.effects):
            admission.retired = True
        return result

    def is_current(self, work: Work):
        with self._lock:
            state = self._states.get(work.operation.key)
            return bool(state and state.negotiation
                        and state.negotiation.operation == work.operation)

    def dispatch(self, key: ConnectionKey, event: Event):
        with self._lock:
            state = self._states.get(key)
            if state is None:
                raise KeyError("Connection must be explicitly registered")
            if isinstance(event, (Result, Failed, Adopted)):
                # An event for another actor cannot release its reservation.
                if event.operation.key != key:
                    raise ValueError("Completion belongs to another connection")
                self._running.pop(event.operation, None)
                surrendered = self._surrendered.get(key, ())
                lease = next((value for value in self._handoffs.values()
                              if value.resource == event.allocated), None)
                if lease is not None and event.now >= lease.deadline:
                    self.reject_handoff(lease.operation)
                if event.allocated in surrendered or (lease and lease.target != key):
                    event = Failed(event.operation, event.now, Failure.INTERNAL)
                elif event.allocated and self._owned_elsewhere(key, event.allocated):
                    # A misrouted adapter result is not cleanup authority for
                    # another actor, including its canceled but still-live work.
                    event = Failed(event.operation, event.now, Failure.INTERNAL)
                elif event.allocated in self._retiring:
                    event = Failed(event.operation, event.now, Failure.TRANSIENT)
            result = self._observe_carrier_retirement(state, event, transition(state, event))
            result = replace(result, state=replace(result.state, sequence=max(
                state.sequence + 1, result.state.sequence)))
            self._trace_pairing_retirement(state, event, result)
            self._states[key] = result.state
            if (isinstance(event, Result) and event.handoff and event.allocated
                    and state.negotiation and state.negotiation.operation == event.operation
                    and result.state.reason == "pairing_ready"):
                self._handoffs[event.operation] = HandoffLease(event.operation,
                    event.allocated, event.allocated, event.now + self.policy.phase_timeout)
                self._surrendered[key] = (event.allocated,)
            if (isinstance(event, Adopted) and result.state.carrier
                    and result.state.carrier.resource == event.allocated):
                for operation, lease in tuple(self._handoffs.items()):
                    if lease.resource == event.allocated and lease.target == key:
                        del self._handoffs[operation]
            self.diagnostics.record(state, event, result)
            pending = self._pending.get(key)
            if pending and not self.is_current(pending):
                del self._pending[key]
            for effect in result.effects:
                if isinstance(effect, Work):
                    # Move continuations behind other eligible actors.
                    self._pending.pop(key, None)
                    self._pending[key] = effect
                else:
                    # At most a cancellation and exact retirement per owned
                    # resource. Deduplication keeps repeated callbacks bounded.
                    self._control[effect] = None
                    if isinstance(effect, Retire):
                        self._retiring.add(effect.resource)
            # Backpressure is explicit and no control event is silently lost.
            if len(self._control) > self.policy.max_actors * 4 + self.policy.max_workers:
                raise CapacityExceeded("Connection cleanup must be drained")
            if len(self._retiring) > self.policy.max_actors * 4 + self.policy.max_workers:
                raise CapacityExceeded("Connection cleanup must complete")
            return result.state

    def _trace_pairing_retirement(self, state, event, result):
        trace = self._pairing_traces.get(state.key)
        if trace is None:
            return
        for effect in result.effects:
            if isinstance(effect, Work):
                if trace.source is None and effect.phase is Phase.DISCOVER:
                    trace.source = effect
                if (trace.source is not None and effect.resource == trace.source.resource
                        and effect.operation.key == trace.source.operation.key
                        and effect.operation.runtime_epoch == trace.source.operation.runtime_epoch
                        and effect.operation.generation == trace.source.operation.generation):
                    trace.last_work = effect
        step, anchor = state.negotiation, trace.source
        if (trace.retirement is not None or step is None or anchor is None
                or step.resource != anchor.resource
                or not any(isinstance(effect, Retire) and effect.resource == step.resource
                           for effect in result.effects)):
            return
        if isinstance(event, (Result, Failed, Adopted)):
            if step.operation is None or event.operation != step.operation:
                return  # Cleanup of a stale result is not this actor's cause.
            operation = step.operation
        elif isinstance(event, (Tick, ContextChanged)):
            operation = step.operation
            if operation is None:
                last = trace.last_work
                if last is None or (last.phase, last.resource) != (step.phase, step.resource):
                    return
                operation = last.operation
        else:
            return
        if (operation.key != state.key or operation.runtime_epoch != self.runtime_epoch
                or operation.generation != state.generation
                or operation.generation != anchor.operation.generation
                or operation.policy_revision != state.authority.revision):
            return
        event_name = {Tick: "tick", Failed: "failed", Result: "result", Adopted: "adopted",
                      ContextChanged: "context_changed"}.get(type(event), "unknown")
        gather = trace.last_work
        exact_work = bool(step.phase is Phase.GATHER_ANSWER and gather is not None
            and gather.phase is Phase.GATHER_ANSWER and gather.operation == operation
            and gather.resource == step.resource == anchor.resource
            and gather.deadline == step.deadline)
        exact_deadline = bool(exact_work and isinstance(event, Tick)
                              and result.reason == "phase_timeout" and event.now >= gather.deadline)
        exact_failed = bool(exact_work and isinstance(event, Failed)
            and event.failure is Failure.INVALID_DOCUMENT and result.reason == "invalid_document"
            and event.allocated == gather.resource and isfinite(event.now)
            and event.now < gather.deadline)
        trace.retirement = _PairingRetirement(operation, anchor.resource, step.phase,
                                             event_name, result.reason,
                                             gather if exact_deadline or exact_failed else None,
                                             gather.deadline if exact_deadline else None,
                                             event.now if exact_failed else None)

    def pairing_retirement_diagnostic(self, *, key, runtime_epoch, source):
        """Read only the cause bound to this native intent's original source."""
        unknown = {"phase": "unknown", "event": "unknown", "reason": "unknown"}
        with self._lock:
            trace = self._pairing_traces.get(key)
            if trace is None or trace.source is None or trace.retirement is None:
                return unknown
            anchor, cause = trace.source, trace.retirement
            if (runtime_epoch != self.runtime_epoch or source != anchor.resource
                    or cause.source != source or anchor.operation.key != key
                    or cause.operation.key != key
                    or anchor.operation.runtime_epoch != runtime_epoch
                    or cause.operation.runtime_epoch != runtime_epoch
                    or cause.operation.generation != anchor.operation.generation):
                return unknown
            return validated_pairing_retirement({"phase": cause.phase.value, "event": cause.event,
                                                 "reason": cause.reason}) or unknown

    def pairing_gather_deadline_diagnostic(self, *, key, runtime_epoch, source):
        """Private exact-work custody for the timeout that retired this intent."""
        with self._lock:
            trace = self._pairing_traces.get(key)
            if trace is None or trace.source is None or trace.retirement is None:
                return None
            anchor, cause = trace.source, trace.retirement
            work = cause.gather_work
            if (work is None or cause.gather_deadline is None
                    or cause.phase is not Phase.GATHER_ANSWER or cause.event != "tick"
                    or cause.reason != "phase_timeout" or key.scope != "pairing"
                    or runtime_epoch != self.runtime_epoch or source != anchor.resource
                    or cause.source != source or anchor.operation.key != key
                    or anchor.operation.runtime_epoch != runtime_epoch
                    or cause.operation != work.operation or work.operation.key != key
                    or work.operation.runtime_epoch != runtime_epoch
                    or work.operation.generation != anchor.operation.generation
                    or work.operation.policy_revision != anchor.operation.policy_revision
                    or work.resource != source or work.phase is not Phase.GATHER_ANSWER
                    or work.deadline != cause.gather_deadline):
                return None
            return work, cause.gather_deadline

    def pairing_gather_failed_diagnostic(self, *, key, runtime_epoch, source):
        """Private exact-work custody for an accepted invalid-document result."""
        with self._lock:
            trace = self._pairing_traces.get(key)
            if trace is None or trace.source is None or trace.retirement is None:
                return None
            anchor, cause = trace.source, trace.retirement
            work, cutoff = cause.gather_work, cause.gather_failed_at
            if (work is None or cutoff is None or not isfinite(cutoff)
                    or cause.phase is not Phase.GATHER_ANSWER or cause.event != "failed"
                    or cause.reason != "invalid_document" or key.scope != "pairing"
                    or runtime_epoch != self.runtime_epoch or source != anchor.resource
                    or cause.source != source or anchor.operation.key != key
                    or anchor.operation.runtime_epoch != runtime_epoch
                    or cause.operation != work.operation or work.operation.key != key
                    or work.operation.runtime_epoch != runtime_epoch
                    or work.operation.generation != anchor.operation.generation
                    or work.operation.policy_revision != anchor.operation.policy_revision
                    or work.resource != source or work.phase is not Phase.GATHER_ANSWER
                    or not cutoff < work.deadline):
                return None
            return work, cutoff

    def commit_handoff(self, operation: Operation, resource: Resource, target: ConnectionKey, now: float):
        """Atomically bind pending custody to one receiver, before publication."""
        with self._lock:
            lease = self._handoffs.get(operation)
            if lease is not None and now >= lease.deadline:
                self.reject_handoff(operation)
                return False
            if (lease is None or lease.target is not None or target.scope == "pairing"
                    or target in self._carrier_retirements
                    or resource.adapter_epoch != lease.source.adapter_epoch
                    or any(other.resource == resource for source, other in self._handoffs.items()
                           if source != operation)
                    or resource in self._retiring or lease.source in self._retiring
                    or self._owned_elsewhere(operation.key, resource)):
                return False
            self._handoffs[operation] = replace(lease, resource=resource, target=target)
            self._surrendered[operation.key] = (lease.source, resource)
            self._handoff_committed.add(operation)
            return True

    def handoff_committed(self, operation: Operation):
        with self._lock:
            return operation in self._handoff_committed

    def pending_handoff_adoption(self, key: ConnectionKey, resource: Resource, now: float) -> bool:
        """Observe existing pending custody; never advance or grant a lease."""
        with self._lock:
            state = self._states.get(key)
            if (state is None or state.key != key or key.scope == "pairing" or key in self._retired
                    or state.runtime_epoch != self.runtime_epoch or state.carrier is not None
                    or not state.authority.authorized or state.desired is not Desired.ENABLED
                    or state.execution is not Execution.AVAILABLE or state.blocked):
                return False
            step = state.negotiation
            if (step is None or step.phase is not Phase.DISCOVER or step.operation is None
                    or not now < step.deadline):
                return False
            operation = step.operation
            work = self._running.get(operation)
            if (operation.key != key or operation.runtime_epoch != self.runtime_epoch
                    or operation.generation != state.generation
                    or operation.policy_revision != state.authority.revision
                    or work is None or work.operation != operation
                    or work.phase is not Phase.DISCOVER or work.resource != step.resource
                    or work.deadline != step.deadline or not now < work.deadline
                    or resource in self._surrendered.get(key, ())
                    or self._owned_elsewhere(key, resource)):
                return False
            leases = [(operation, lease) for operation, lease in self._handoffs.items()
                      if lease.resource == resource]
            if len(leases) != 1:
                return False
            source_operation, lease = leases[0]
            return bool(source_operation == lease.operation and lease.target == key
                        and lease.operation in self._handoff_committed
                        and lease.operation.key.scope == "pairing"
                        and lease.operation.runtime_epoch == self.runtime_epoch
                        and resource.adapter_epoch == lease.source.adapter_epoch
                        and now < lease.deadline
                        and resource not in self._retiring and lease.source not in self._retiring)

    def reject_handoff(self, operation: Operation):
        with self._lock:
            lease = self._handoffs.pop(operation, None)
            if lease is not None:
                trace = self._pairing_traces.get(operation.key)
                if (trace is not None and trace.source is not None and trace.last_work is not None
                        and trace.retirement is None and trace.last_work.operation == operation
                        and trace.last_work.phase is Phase.CHECKING
                        and trace.source.resource == lease.source
                        and trace.source.operation.runtime_epoch == operation.runtime_epoch
                        and trace.source.operation.generation == operation.generation):
                    trace.retirement = _PairingRetirement(operation, lease.source, Phase.CHECKING,
                                                         "handoff_rejected", "handoff_rejected")
                self._control[Retire(lease.resource)] = None
                self._retiring.add(lease.resource)

    def revoke_handoffs(self, keys=None):
        with self._lock:
            for operation, lease in tuple(self._handoffs.items()):
                if keys is None or operation.key in keys or lease.target in keys:
                    self.reject_handoff(operation)

    def resource_released(self, resource: Resource):
        """Only confirmed cleanup releases the private retirement reservation."""
        with self._lock:
            self._retiring.discard(resource)

    def _owned_elsewhere(self, key: ConnectionKey, resource: Resource) -> bool:
        for other, state in self._states.items():
            if other != key and (
                (state.carrier and state.carrier.resource == resource)
                or (state.negotiation and state.negotiation.resource == resource)
            ):
                return True
        return any(work.operation.key != key and work.resource == resource
                   for work in self._running.values())

    def tick(self, now: float, jitter: float = 0):
        from .model import Tick
        with self._lock:
            for operation, lease in tuple(self._handoffs.items()):
                target = self._states.get(lease.target)
                if (now >= lease.deadline or (target is not None and (
                        not target.authority.authorized or target.desired is Desired.STOPPED))):
                    self.reject_handoff(operation)
            for key in tuple(self._states):
                if key not in self._retired:
                    self.dispatch(key, Tick(now, jitter))

    def retire(self, key: ConnectionKey, now: float):
        with self._lock:
            self.dispatch(key, ContextChanged(now, desired=Desired.STOPPED))
            self._retired.add(key)

    def restore(self, key: ConnectionKey):
        """Resume ticks after protected reconciliation; preserve all fences and counters."""
        with self._lock:
            if key not in self._states:
                raise KeyError("Connection must be explicitly registered")
            self._retired.discard(key)

    def drain(self):
        with self._lock:
            effects = list(self._control)
            self._control.clear()
            while self._pending and len(self._running) < self.policy.max_workers:
                _, work = self._pending.popitem(last=False)
                if self.is_current(work):
                    self._running[work.operation] = work
                    effects.append(work)
            return tuple(effects)
