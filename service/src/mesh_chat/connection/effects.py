"""Bounded external work, cooperative cancellation and retained reservations."""

from dataclasses import dataclass
from queue import Queue
from threading import Event, RLock, Thread
from time import monotonic

from .model import Cancel, Failed, Failure, Policy, Resource, Retire, Work
from .ports import PhaseExecutor


@dataclass(frozen=True)
class CleanupResult:
    resource: Resource
    succeeded: bool


class BoundedEffectRunner:
    def __init__(self, executor: PhaseExecutor, policy: Policy = Policy(), *, now=monotonic):
        self._executor = executor
        self._policy = policy
        self._now = now
        self._lock = RLock()
        self._closed = False
        self._workers = {}
        self._work_bytes = {}
        self._deadlines = {}
        self._cleanup = {}
        self._cleanup_deadlines = {}
        # Completed work retains a reservation until the owner consumes it.
        self._completed = Queue(maxsize=policy.max_workers + policy.max_effects)

    @property
    def active(self):
        with self._lock:
            return len(self._workers)

    @property
    def idle(self):
        with self._lock:
            return not self._workers and not self._cleanup

    def stalled(self):
        """A deadline never frees a reservation for an uncooperative call."""
        with self._lock:
            now = self._now()
            return (any(thread.is_alive() and now >= self._deadlines[operation]
                        for operation, (_, thread) in self._workers.items())
                    or any(thread.is_alive() and now >= self._cleanup_deadlines[resource]
                           for resource, thread in self._cleanup.items()))

    def submit(self, effect):
        with self._lock:
            if isinstance(effect, Cancel):
                current = self._workers.get(effect.operation)
                if current:
                    current[0].set()
                return True
            if isinstance(effect, Retire):
                if effect.resource in self._cleanup or len(self._cleanup) >= 1:
                    return False
                thread = Thread(target=self._retire, args=(effect.resource,),
                                name="mesh-connection-retire", daemon=True)
                self._cleanup[effect.resource] = thread
                self._cleanup_deadlines[effect.resource] = self._now() + self._policy.phase_timeout
                thread.start()
                return True
            if not isinstance(effect, Work):
                raise TypeError("Unsupported connection effect")
            if (self._closed or effect.operation in self._workers
                    or len(self._workers) >= self._policy.max_workers):
                return False
            size = len(repr(effect).encode("utf-8"))
            if sum(self._work_bytes.values()) + size > self._policy.max_effect_bytes:
                return False
            cancelled = Event()
            thread = Thread(target=self._execute, args=(effect, cancelled),
                            name="mesh-connection-effect", daemon=True)
            self._workers[effect.operation] = (cancelled, thread)
            self._work_bytes[effect.operation] = size
            self._deadlines[effect.operation] = effect.deadline + self._policy.disconnect_grace
            thread.start()
            return True

    def _execute(self, work, cancelled):
        try:
            if cancelled.is_set() or self._now() >= work.deadline:
                result = Failed(work.operation, self._now(), Failure.TRANSIENT)
            else:
                result = self._executor.execute(work, cancelled)
                if result.operation != work.operation:
                    raise ValueError("Effect returned the wrong operation")
        except Exception:
            # Native exceptions may contain SDP, addresses or credentials.
            result = Failed(work.operation, self._now(), Failure.INTERNAL, allocated=work.resource)
        self._completed.put(result)

    def _retire(self, resource):
        try:
            self._executor.retire(resource)
            result = CleanupResult(resource, True)
        except Exception:
            result = CleanupResult(resource, False)
        self._completed.put(result)

    def next_completion(self, timeout=0):
        result = self._completed.get(timeout=timeout)
        with self._lock:
            if isinstance(result, CleanupResult):
                self._cleanup.pop(result.resource, None)
                self._cleanup_deadlines.pop(result.resource, None)
            else:
                self._workers.pop(result.operation, None)
                self._work_bytes.pop(result.operation, None)
                self._deadlines.pop(result.operation, None)
        return result

    def close(self, timeout=2.0):
        with self._lock:
            self._closed = True
            for cancelled, _ in self._workers.values():
                cancelled.set()
            threads = [thread for _, thread in self._workers.values()]
            threads.extend(self._cleanup.values())
        deadline = monotonic() + timeout
        for thread in threads:
            thread.join(max(0, deadline - monotonic()))
        # The composition root must keep keys alive if any work remains.
        return not any(thread.is_alive() for thread in threads)
