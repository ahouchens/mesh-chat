"""Serialized actor ownership and fair, bounded admission; no external I/O."""

from collections import OrderedDict
from dataclasses import replace
from threading import RLock

from .diagnostics import Diagnostics
from .model import (
    Adopted, Cancel, ConnectionKey, ConnectionState, ContextChanged, Desired, Event,
    Failed, Failure, HandoffLease, Operation, Policy, Resource, Result, Retire, Work,
)
from .reducer import transition


class CapacityExceeded(RuntimeError):
    pass


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
        self.diagnostics = Diagnostics(policy.max_diagnostics)

    def register(self, state: ConnectionState):
        with self._lock:
            if state.key in self._states or state.runtime_epoch != self.runtime_epoch:
                raise ValueError("Connection owner already exists or epoch mismatch")
            if len(self._states) >= self.policy.max_actors:
                raise CapacityExceeded("Connection actor capacity reached")
            self._states[state.key] = replace(state, policy=self.policy)

    def snapshot(self, key: ConnectionKey):
        with self._lock:
            return self._states[key]

    def snapshots(self):
        with self._lock:
            return tuple(self._states.values())

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
                if event.allocated in surrendered or (lease and lease.target != key):
                    event = Failed(event.operation, event.now, Failure.INTERNAL)
                elif event.allocated and self._owned_elsewhere(key, event.allocated):
                    # A misrouted adapter result is not cleanup authority for
                    # another actor, including its canceled but still-live work.
                    event = Failed(event.operation, event.now, Failure.INTERNAL)
                elif event.allocated in self._retiring:
                    event = Failed(event.operation, event.now, Failure.TRANSIENT)
            result = transition(state, event)
            result = replace(result, state=replace(result.state, sequence=max(
                state.sequence + 1, result.state.sequence)))
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

    def commit_handoff(self, operation: Operation, resource: Resource, target: ConnectionKey):
        """Atomically bind pending custody to one receiver, before publication."""
        with self._lock:
            lease = self._handoffs.get(operation)
            if (lease is None or lease.target is not None or target.scope == "pairing"
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

    def reject_handoff(self, operation: Operation):
        with self._lock:
            lease = self._handoffs.pop(operation, None)
            if lease is not None:
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
