"""Drive the production supervisor without running I/O in its critical section."""

from collections import OrderedDict
from dataclasses import replace
from queue import Empty
from random import SystemRandom
from threading import Event, RLock, Thread
from time import monotonic

from .effects import BoundedEffectRunner, CleanupResult
from .model import (
    ConnectionState, ContextChanged, Desired, Execution, Failed,
    Failure, Policy, Retire, Work,
)
from .projection import snapshot
from .reconcile import authority, authority_signature, connection_key, desired
from .supervisor import CapacityExceeded, ConnectionSupervisor


class ConnectionRuntime:
    def __init__(self, runtime_epoch, executor_factory, *, profiles, execution,
                 activate, policy=Policy(), now=monotonic):
        self.owner = ConnectionSupervisor(runtime_epoch, policy)
        self.profiles = profiles
        self.execution = execution
        self.activate = activate
        self.now = now
        self._random = SystemRandom().random
        self._lock = RLock()
        self._profile_values = {}
        self._profile_keys = {}
        self._signatures = {}
        self._veto = set()
        self._contact_fences = set()
        self._all_fenced = False
        self._resumed = set()
        self._pending = OrderedDict()
        self._cleanup_failed = set()
        self._stop = Event()
        self._thread = None
        self._retry_cleanup_at = 0
        self._failure = None
        self.executor = executor_factory(self.owner.is_current, self.profile)
        self.runner = BoundedEffectRunner(self.executor, policy, now=now)

    def profile(self, key):
        with self._lock:
            if self._is_fenced(key, self._profile_values[key]) or self._stop.is_set():
                return {"state": "stopped"}
            return dict(self._profile_values[key])

    def _is_fenced(self, key, profile):
        identifiers = {key.profile_id, profile.get("contact_id")}
        return (key in self._veto or bool(identifiers & self._contact_fences)
                or (self._all_fenced and not identifiers & self._resumed))

    def permits_carrier(self, profile_id, resource):
        """Private bridge lease check; packet traffic does not run the reducer."""
        with self._lock:
            if self._stop.is_set():
                return False
            for key in self._profile_keys.get(profile_id, ()):
                profile = self._profile_values[key]
                state = self.owner.snapshot(key)
                if (not self._is_fenced(key, profile) and state.carrier is not None
                        and state.carrier.resource == resource and state.authority.authorized
                        and state.desired is Desired.ENABLED and state.execution is Execution.AVAILABLE):
                    return True
            return False

    def fence(self, contact_id=None):
        """Immediately deny work, before the caller attempts a durable Stop."""
        with self._lock:
            if contact_id is None:
                self._all_fenced = True
                self._resumed.clear()
            else:
                if len(self._contact_fences) >= self.owner.policy.max_actors:
                    self._all_fenced = True
                    self._resumed.clear()
                else:
                    self._contact_fences.add(contact_id)
                self._resumed.discard(contact_id)
            for key, profile in self._profile_values.items():
                if contact_id is None or contact_id in {profile.get("contact_id"), key.profile_id}:
                    self._veto.add(key)
                    self.owner.dispatch(key, ContextChanged(self.now(), desired=Desired.STOPPED))

    def committed_start(self, contact_id=None):
        with self._lock:
            if contact_id is None:
                self._all_fenced = False
                self._contact_fences.clear()
                self._resumed.clear()
            else:
                if self._all_fenced and len(self._resumed) >= self.owner.policy.max_actors:
                    raise CapacityExceeded("Connection intent budget exceeded")
                self._contact_fences.discard(contact_id)
                if self._all_fenced:
                    self._resumed.add(contact_id)
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
                    and not profile.get("manual_carrier_authorized")
                    and authority(profile, 0).authorized):
                key = connection_key(profile)
                if not self._is_fenced(key, profile):
                    self.activate(profile["contact_id"])
        now = self.now()
        with self._lock:
            seen = set()
            profile_keys = {}
            for profile in values:
                key = connection_key(profile)
                seen.add(key)
                profile_keys.setdefault(key.profile_id, []).append(key)
                signature = authority_signature(profile)
                previous = self._signatures.get(key)
                revision = 1 if previous is None else previous[1] + (previous[0] != signature)
                if previous is not None and key not in self._profile_values:
                    self.owner.restore(key)
                intent = Desired.STOPPED if self._is_fenced(key, profile) else desired(profile)
                if previous is None:
                    self.owner.register(ConnectionState(key, self.owner.runtime_epoch,
                                        authority(profile, revision), intent, execution))
                else:
                    self.owner.dispatch(key, ContextChanged(now, authority(profile, revision), intent, execution))
                self._signatures[key] = (signature, revision)
                self._profile_values[key] = dict(profile)
            for key in self._profile_values.keys() - seen:
                self._veto.add(key)
                self.owner.retire(key, now)
                del self._profile_values[key]
            self._profile_keys = profile_keys

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
        if self.runner.stalled():
            self.quarantine()
        if self._failure == "adapter_quarantined":
            self.fence()
            self._effects()
            return
        self.synchronize()
        now = self.now()
        if now >= self._retry_cleanup_at:
            self._retry_cleanup_at = now + self.owner.policy.poll_interval
            for resource in self._cleanup_failed:
                self._pending[Retire(resource)] = None
        self.owner.tick(now, jitter=self._random())
        self._effects()

    def quarantine(self):
        """Private host fault: only a new runtime may restore adapter authority."""
        self._failure = "adapter_quarantined"
        self.fence()

    def snapshots(self):
        now = self.now()
        return {state.key.profile_id: {**snapshot(state, now), "runtime_failure": self._failure}
                for state in self.owner.snapshots()}

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
            Event().wait(0.05)
