"""Serialized actor ownership and fair, bounded admission; no external I/O."""

from collections import OrderedDict
from dataclasses import replace
from threading import RLock

from .diagnostics import Diagnostics
from .model import (
    Cancel, ConnectionKey, ConnectionState, ContextChanged, Desired, Event,
    Failed, Failure, Policy, Resource, Result, Retire, Work,
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
            if isinstance(event, (Result, Failed)):
                # An event for another actor cannot release its reservation.
                if event.operation.key != key:
                    raise ValueError("Completion belongs to another connection")
                self._running.pop(event.operation, None)
                if event.allocated and self._owned_elsewhere(key, event.allocated):
                    # A misrouted adapter result is not cleanup authority for
                    # another actor, including its canceled but still-live work.
                    event = Failed(event.operation, event.now, Failure.INTERNAL)
            result = transition(state, event)
            result = replace(result, state=replace(result.state, sequence=max(
                state.sequence + 1, result.state.sequence)))
            self._states[key] = result.state
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
            # Backpressure is explicit and no control event is silently lost.
            if len(self._control) > self.policy.max_actors * 4 + self.policy.max_workers:
                raise CapacityExceeded("Connection cleanup must be drained")
            return result.state

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
