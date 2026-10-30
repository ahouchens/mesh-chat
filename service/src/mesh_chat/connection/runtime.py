"""Drive the production supervisor without running I/O in its critical section."""

from collections import OrderedDict
from dataclasses import replace
from queue import Empty
from random import SystemRandom
from threading import Event, RLock, Thread
from time import monotonic

from .effects import BoundedEffectRunner, CleanupResult
from .model import (
    Bridge, Cancel, ConnectionState, ContextChanged, Desired, Execution, Failed,
    Failure, Health, Observed, Policy, Retire, Work,
)
from .projection import snapshot
from .reconcile import authority, authority_signature, connection_key, desired
from .supervisor import CapacityExceeded, ConnectionSupervisor


class ConnectionRuntime:
    def __init__(self, runtime_epoch, executor_factory, *, profiles, execution,
                 stats, activate, policy=Policy(), now=monotonic):
        self.owner = ConnectionSupervisor(runtime_epoch, policy)
        self.profiles = profiles
        self.execution = execution
        self.stats = stats
        self.activate = activate
        self.now = now
        self._random = SystemRandom().random
        self._lock = RLock()
        self._profile_values = {}
        self._signatures = {}
        self._veto = set()
        self._pending = OrderedDict()
        self._cleanup_failed = set()
        self._stop = Event()
        self._thread = None
        self._last_health = 0
        self._failure = None
        self.executor = executor_factory(self.owner.is_current, self.profile)
        self.runner = BoundedEffectRunner(self.executor, policy, now=now)

    def profile(self, key):
        with self._lock:
            if key in self._veto or self._stop.is_set():
                return {"state": "stopped"}
            return dict(self._profile_values[key])

    def fence(self, contact_id=None):
        """Immediately deny work, before the caller attempts a durable Stop."""
        with self._lock:
            for key, profile in self._profile_values.items():
                if contact_id is None or contact_id in {profile.get("contact_id"), key.profile_id}:
                    self._veto.add(key)
                    self.owner.dispatch(key, ContextChanged(self.now(), desired=Desired.STOPPED))

    def committed_start(self, contact_id=None):
        with self._lock:
            for key, profile in self._profile_values.items():
                if contact_id is None or contact_id in {profile.get("contact_id"), key.profile_id}:
                    self._veto.discard(key)

    def synchronize(self):
        payload = self.profiles()
        execution = self.execution()
        values = payload.get("profiles", ())
        if len(values) > self.owner.policy.max_actors:
            raise CapacityExceeded("Connection profile budget exceeded")
        # Explicit opt-outs are never activated by reconciliation.
        for profile in values:
            if (profile.get("state") != "stopped" and not profile.get("active")
                    and (profile.get("effective") or {}).get("ready")):
                key = connection_key(profile)
                if key not in self._veto:
                    self.activate(profile["contact_id"])
        now = self.now()
        with self._lock:
            seen = set()
            for profile in values:
                key = connection_key(profile)
                seen.add(key)
                signature = authority_signature(profile)
                previous = self._signatures.get(key)
                revision = 1 if previous is None else previous[1] + (previous[0] != signature)
                self._signatures[key] = (signature, revision)
                self._profile_values[key] = dict(profile)
                intent = Desired.STOPPED if key in self._veto else desired(profile)
                if previous is None:
                    self.owner.register(ConnectionState(key, self.owner.runtime_epoch,
                                        authority(profile, revision), intent, execution))
                else:
                    self.owner.dispatch(key, ContextChanged(now, authority(profile, revision), intent, execution))
            for key in self._profile_values.keys() - seen:
                self._veto.add(key)
                self.owner.retire(key, now)
                del self._profile_values[key]

    def _completions(self):
        while True:
            try:
                event = self.runner.next_completion()
            except Empty:
                return
            if isinstance(event, CleanupResult):
                if not event.succeeded:
                    self._cleanup_failed.add(event.resource)
                    self._failure = "cleanup_failed"
                else:
                    self._cleanup_failed.discard(event.resource)
            else:
                if isinstance(event, Failed):
                    event = replace(event, jitter=self._random())
                self.owner.dispatch(event.operation.key, event)

    def _effects(self):
        for effect in self.owner.drain():
            self._pending[effect] = None
        for effect in tuple(self._pending):
            if isinstance(effect, Work) and not self.owner.is_current(effect):
                del self._pending[effect]
                self.owner.dispatch(effect.operation.key,
                                    Failed(effect.operation, self.now(), Failure.TRANSIENT))
            elif self.runner.submit(effect):
                del self._pending[effect]
        if len(self._pending) > self.owner.policy.max_actors * 4:
            raise CapacityExceeded("Connection effects are backpressured")

    def step(self):
        self._completions()
        self.synchronize()
        now = self.now()
        if now - self._last_health >= self.owner.policy.poll_interval:
            self._last_health = now
            for state in self.owner.snapshots():
                if state.carrier:
                    try:
                        value = self.stats(state.carrier.resource.resource_id)
                        ice = value.get("ice_connection_state")
                        health = (Health.OPEN if ice in {"connected", "completed"}
                                  else Health.ABSENT if ice in {"closed", "failed"} else Health.SUSPECT)
                        bridge = state.carrier.bridge if value.get("attached") else Bridge.DETACHED
                    except Exception:
                        health, bridge = Health.SUSPECT, state.carrier.bridge
                    self.owner.dispatch(state.key, Observed(state.carrier.resource, now, health, bridge))
            for resource in self._cleanup_failed:
                self._pending[Retire(resource)] = None
        self.owner.tick(now, jitter=self._random())
        self._effects()

    def snapshots(self):
        now = self.now()
        return {state.key.profile_id: snapshot(state, now) for state in self.owner.snapshots()}

    def start(self):
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="mesh-connection-runtime", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:
                # A failed authority refresh cannot leave old permission live.
                self._failure = "runtime_fault"
                self.fence()
                self._effects()
            self._stop.wait(0.25)

    def stop(self, timeout=2):
        self._stop.set()
        self.fence()
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                return False
        self._completions()
        self._effects()
        self.runner.close(timeout)
        self._completions()
        self._effects()
        return (self.runner.idle and not self._pending
                and not self._cleanup_failed and self.runner.close(0))

    def wait(self):
        """Used by the service finalizer before releasing protected keys."""
        if self._thread:
            self._thread.join()
        while True:
            self.runner.close(0.25)
            self._completions()
            for resource in self._cleanup_failed:
                self._pending[Retire(resource)] = None
            self._effects()
            if (self.runner.idle and not self._pending
                    and not self._cleanup_failed and self.runner.close(0)):
                return
