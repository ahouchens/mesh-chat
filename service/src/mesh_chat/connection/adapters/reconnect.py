"""Execute single signed-protocol operations through explicitly injected ports.

Documents stay here, never in diagnostics or public connection projections.
Each mailbox operation polls once. The production reducer owns all waits.
"""

from dataclasses import dataclass, field
from hashlib import sha256
from threading import RLock
from typing import Any, Callable

from ...errors import (
    ContactNotApproved, IdentityMismatch, MailboxNotConfigured,
    MailboxRateLimited, MailboxUnauthorized, NativeUnavailable,
    NetworkUnavailable, ReconnectReplayed, ValidationError,
)
from ..model import Failed, Failure, Phase, Result, Resource, Work

CHANNELS = (
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
)


@dataclass(frozen=True)
class SignalingPort:
    request: Callable[..., dict]
    offer: Callable[..., dict]
    answer: Callable[..., dict]
    verify_request: Callable[..., dict]
    verify_offer: Callable[..., dict]
    verify_answer: Callable[..., dict]
    publish: Callable[..., Any]
    fetch: Callable[..., dict]


@dataclass(frozen=True)
class NativePort:
    offer: Callable[..., dict]
    accept: Callable[..., dict]
    apply_answer: Callable[..., dict]
    stats: Callable[[str], dict]
    attach: Callable[[str], dict]
    close: Callable[[str], Any]


@dataclass
class Exchange:
    profile: dict
    request: dict = field(default_factory=dict)
    offer: dict = field(default_factory=dict)
    answer: dict = field(default_factory=dict)
    native: dict = field(default_factory=dict)
    verified: bool = False


class ReconnectExecutor:
    def __init__(self, signaling: SignalingPort, native: NativePort, *,
                 profile, ice, path, current, now, wall_time, max_profiles=256):
        self.signaling = signaling
        self.native = native
        self.profile = profile
        self.ice = ice
        self.path = path
        self.current = current
        self.now = now
        self.wall_time = wall_time
        self.max_profiles = max_profiles
        self._lock = RLock()
        self._exchanges: dict[Resource, Exchange] = {}
        self._requests = {}
        self._completed_requests = {}
        self._handlers = {
            Phase.REQUEST: self._request,
            Phase.WAIT_REQUEST: self._wait_request,
            Phase.WAIT_OFFER: self._wait_offer,
            Phase.GATHER_OFFER: self._gather_offer,
            Phase.GATHER_ANSWER: self._gather_answer,
            Phase.PUBLISH_OFFER: self._publish_offer,
            Phase.PUBLISH_ANSWER: self._publish_answer,
            Phase.WAIT_ANSWER: self._wait_answer,
            Phase.APPLY_ANSWER: self._apply_answer,
            Phase.CHECKING: self._checking,
            Phase.ATTACH: self._attach,
            Phase.PATH: self._path,
        }

    def _check(self, work, cancellation):
        if cancellation.is_set() or not self.current(work):
            raise ContactNotApproved("Connection operation was cancelled")
        profile = self.profile(work.operation.key)
        reasons = set((profile.get("effective") or {}).get("reasons") or ())
        ready = (profile.get("effective") or {}).get("ready")
        signaling_required = work.phase not in {Phase.CHECKING, Phase.ATTACH, Phase.PATH}
        if (profile.get("state") == "stopped" or not profile.get("active")
                or not (ready or (not signaling_required and reasons == {"mailbox_not_configured"}))):
            raise ContactNotApproved("Connection authority is unavailable")
        return profile

    def execute(self, work: Work, cancellation):
        try:
            profile = self._check(work, cancellation)
            with self._lock:
                exchange = self._exchanges.get(work.resource)
                if exchange is None:
                    if len(self._exchanges) >= self.max_profiles:
                        return Failed(work.operation, self.now(), Failure.INTERNAL)
                    exchange = self._exchanges[work.resource] = Exchange(profile)
            # Check authority around each operation, including compound signing
            # and publication phases. A canceled JNI call may still allocate.
            def call(operation, *args):
                self._check(work, cancellation)
                value = operation(*args)
                self._check(work, cancellation)
                return value
            pending = self._handlers[work.phase](work, exchange, call)
            return Result(work.operation, self.now(), pending=pending,
                          allocated=work.resource if work.phase in {
                              Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.CHECKING} else None,
                          verified=exchange.verified)
        except (NativeUnavailable, NetworkUnavailable, TimeoutError, OSError):
            return Failed(work.operation, self.now(), Failure.TRANSIENT, allocated=work.resource)
        except (IdentityMismatch, ReconnectReplayed, ValidationError) as error:
            if isinstance(error, MailboxNotConfigured):
                return Failed(work.operation, self.now(), Failure.CONFIGURATION)
            # Invalid mailbox content is not a new signed attempt. Poll at the
            # reducer's bounded cadence until this phase's existing deadline.
            if work.phase in {Phase.WAIT_REQUEST, Phase.WAIT_OFFER, Phase.WAIT_ANSWER}:
                return Result(work.operation, self.now(), pending=True)
            return Failed(work.operation, self.now(), Failure.INVALID_DOCUMENT)
        except ContactNotApproved:
            # The candidate's exact handle is retired even when creation
            # finished after cancellation. Never retire a profile by lookup.
            return Failed(work.operation, self.now(), Failure.REVOKED, allocated=work.resource)
        except MailboxUnauthorized:
            return Failed(work.operation, self.now(), Failure.CONFIGURATION)
        except MailboxRateLimited as error:
            return Failed(work.operation, self.now(), Failure.RATE_LIMITED,
                          retry_after=max(0, float(getattr(error, "retry_after", 60))))

    def retire(self, resource):
        self.native.close(resource.resource_id)
        with self._lock:
            self._exchanges.pop(resource, None)

    def _request(self, work, exchange, call):
        key = work.operation.key
        request = self._requests.get(key)
        if not request or request["expires_at"] <= self.wall_time():
            if key not in self._requests and len(self._requests) >= self.max_profiles:
                raise NativeUnavailable("Request capacity reached")
            attempt = sha256(work.resource.resource_id.encode("utf-8")).hexdigest()
            request = call(self.signaling.request, exchange.profile["contact_id"], attempt)
            self._requests[key] = request
        exchange.request = request
        call(self.signaling.publish, key.profile_id, request["document"], "request")
        return False

    def _fetch(self, work, role, call):
        value = call(self.signaling.fetch, work.operation.key.profile_id, role)
        return value.get("document") if value else None

    def _wait_request(self, work, exchange, call):
        document = self._fetch(work, "request", call)
        if not document or document == self._completed_requests.get(work.operation.key):
            return True
        verified = call(self.signaling.verify_request, document, work.operation.key.profile_id)
        exchange.request = {**verified, "document": document}
        return False

    def _wait_offer(self, work, exchange, call):
        document = self._fetch(work, "offer", call)
        if not document:
            return True
        verified = call(self.signaling.verify_offer, document, work.operation.key.profile_id)
        if verified["attempt_id"] != exchange.request["attempt_id"]:
            raise IdentityMismatch("Offer belongs to another request")
        exchange.offer = {**verified, "document": document}
        return False

    def _configuration(self, exchange, call):
        ice = call(self.ice)
        if not exchange.profile.get("allow_direct_ip_disclosure"):
            ice = {**ice, "iceTransportPolicy": "relay"}
        return ice

    def _gather_offer(self, work, exchange, call):
        exchange.native = call(self.native.offer, work.resource.resource_id,
                               self._configuration(exchange, call), list(CHANNELS), work.operation.key.profile_id)
        return False

    def _gather_answer(self, work, exchange, call):
        exchange.native = call(self.native.accept, work.resource.resource_id, exchange.offer["sdp"],
                               self._configuration(exchange, call), list(CHANNELS), work.operation.key.profile_id)
        return False

    def _publish_offer(self, work, exchange, call):
        exchange.offer = call(self.signaling.offer, exchange.profile["contact_id"],
                              exchange.request["document"], exchange.native["sdp"], exchange.native["fingerprint"])
        call(self.signaling.publish, work.operation.key.profile_id, exchange.offer["document"], "offer")
        return False

    def _publish_answer(self, work, exchange, call):
        exchange.answer = call(self.signaling.answer, exchange.profile["contact_id"],
                               exchange.offer["document"], exchange.native["sdp"], exchange.native["fingerprint"])
        call(self.signaling.publish, work.operation.key.profile_id, exchange.answer["document"], "answer")
        exchange.verified = True
        self._requests.pop(work.operation.key, None)
        return False

    def _wait_answer(self, work, exchange, call):
        document = self._fetch(work, "answer", call)
        if not document:
            return True
        exchange.answer = call(self.signaling.verify_answer, document, exchange.offer["document"],
                               work.operation.key.profile_id)
        exchange.verified = True
        return False

    def _apply_answer(self, work, exchange, call):
        call(self.native.apply_answer, work.resource.resource_id, exchange.answer["sdp"])
        return False

    def _checking(self, work, exchange, call):
        stats = call(self.native.stats, work.resource.resource_id)
        return not (exchange.verified and stats.get("data_channel_state") == "open"
                    and stats.get("ice_connection_state") in {"connected", "completed"})

    def _attach(self, work, exchange, call):
        call(self.native.attach, work.resource.resource_id)
        return False

    def _path(self, work, exchange, call):
        value = call(self.path, exchange.profile["contact_id"])
        ready = bool(value.get("has_path") and value.get("ready"))
        if ready and not (exchange.profile.get("effective") or {}).get("preferred"):
            key = work.operation.key
            if key not in self._completed_requests and len(self._completed_requests) >= self.max_profiles:
                raise NativeUnavailable("Replay cache capacity reached")
            self._completed_requests[key] = exchange.request["document"]
        return not ready
