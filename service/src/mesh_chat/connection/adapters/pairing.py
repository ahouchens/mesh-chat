"""Execute one initial pairing phase; the supervisor owns polls and custody.

Signed documents and pairing capabilities stay in private domain contexts.
No renderer, SDK or adapter retry loop owns a native allocation.
"""
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from ...errors import ContactNotApproved, IdentityMismatch, NativeUnavailable, ValidationError
from ..model import Failed, Failure, Phase, Result


@dataclass(frozen=True)
class PairingPort:
    context: Callable
    reserve: Callable
    fetch_offer: Callable
    gather_offer: Callable
    gather_answer: Callable
    publish_offer: Callable
    publish_answer: Callable
    fetch_answer: Callable
    apply_answer: Callable
    ready: Callable
    retire: Callable
    mark_gather_work: Callable | None = None
    mark_gather_failure: Callable | None = None


_NATIVE_GATHER_CODES = {
    "native_webrtc_answer_failed": "answer_failed",
    "native_webrtc_network_monitor_failed": "network_monitor_failed",
    "native_webrtc_session_closed": "session_closed",
    "native_webrtc_disposal_timeout": "disposal_timeout",
    "native_webrtc_no_candidates": "no_candidates",
    "native_webrtc_missing_data_channel": "missing_data_channel",
    "native_webrtc_sdp_failed": "sdp_failed",
}


def _gather_exception_labels(error):
    """Classify fixed literals only; never copy a native error message."""
    if isinstance(error, NativeUnavailable):
        args = error.args
        code = (_NATIVE_GATHER_CODES.get(args[0], "unknown")
                if len(args) == 1 and type(args[0]) is str else "unknown")
        return "native_unavailable", code
    if isinstance(error, IdentityMismatch):
        return "identity_mismatch", "not_applicable"
    if isinstance(error, ValidationError):
        return "validation_error", "not_applicable"
    return "unknown", "unknown"


class PairingExecutor:
    def __init__(self, ports: PairingPort, *, current, now, capacity=32):
        self.ports, self.current, self.now = ports, current, now
        self.capacity = capacity
        self._contexts = {}
        self._lock = RLock()
        self._handlers = {
            Phase.WAIT_OFFER: ports.fetch_offer,
            Phase.GATHER_OFFER: ports.gather_offer,
            Phase.GATHER_ANSWER: ports.gather_answer,
            Phase.PUBLISH_OFFER: ports.publish_offer,
            Phase.PUBLISH_ANSWER: ports.publish_answer,
            Phase.WAIT_ANSWER: ports.fetch_answer,
            Phase.APPLY_ANSWER: ports.apply_answer,
            Phase.CHECKING: lambda context: not ports.ready(context),
        }

    def _check(self, work, cancellation):
        if (cancellation.is_set() or not self.current(work)
                or self.now() >= work.deadline):
            raise ContactNotApproved("Pairing operation is no longer current")
        return self.ports.context(work.operation.key)

    def execute(self, work, cancellation):
        context = None
        try:
            context = self._check(work, cancellation)
            with self._lock:
                previous = self._contexts.get(work.resource)
                if previous is not None and previous is not context:
                    raise NativeUnavailable("Pairing allocation context changed")
                if previous is None:
                    if len(self._contexts) >= self.capacity:
                        raise NativeUnavailable("Pairing allocation capacity reached")
                    self._contexts[work.resource] = context
            if work.phase is Phase.DISCOVER:
                self.ports.reserve(context, work.resource)
                pending = False
            else:
                if work.phase in {Phase.GATHER_OFFER, Phase.GATHER_ANSWER} and self.ports.mark_gather_work is not None:
                    try:
                        self.ports.mark_gather_work(context, work)
                    except Exception:
                        pass  # Private observation cannot change a pairing result.
                pending = bool(self._handlers[work.phase](context))
            if self._check(work, cancellation) is not context:
                raise ContactNotApproved("Pairing authority changed")
            ready = work.phase is Phase.CHECKING and not pending
            return Result(work.operation, self.now(), pending=pending,
                          allocated=work.resource, verified=ready, handoff=ready)
        except ContactNotApproved:
            failure = Failure.REVOKED
        except (IdentityMismatch, ValidationError) as error:
            if (work.phase in {Phase.GATHER_OFFER, Phase.GATHER_ANSWER} and context is not None
                    and self.ports.mark_gather_failure is not None):
                try:
                    kind, code = _gather_exception_labels(error)
                    self.ports.mark_gather_failure(context, work, kind, code)
                except Exception:
                    pass  # Observation cannot change the primary classified failure.
            failure = Failure.INVALID_DOCUMENT
        except Exception:
            # Unknown native/signaling outcomes terminate this admitted intent.
            # A new user intent is required; no replacement allocation occurs.
            failure = Failure.TRANSIENT
        return Failed(work.operation, self.now(), failure, allocated=work.resource)

    def owns(self, resource):
        with self._lock:
            return any(resource == source or resource.resource_id == context.get("physical")
                       for source, context in self._contexts.items())

    def retire(self, resource):
        with self._lock:
            match = next(((source, context) for source, context in self._contexts.items()
                          if resource == source or resource.resource_id == context.get("physical")), None)
        if match is not None:
            source, context = match
            self.ports.retire(context, resource)
            with self._lock:
                self._contexts.pop(source, None)


class PairingAndReconnectExecutor:
    def __init__(self, pairing, reconnect):
        self.pairing, self.reconnect = pairing, reconnect

    def execute(self, work, cancellation):
        executor = self.pairing if work.operation.key.scope == "pairing" else self.reconnect
        return executor.execute(work, cancellation)

    def retire(self, resource):
        executor = self.pairing if self.pairing.owns(resource) else self.reconnect
        return executor.retire(resource)
