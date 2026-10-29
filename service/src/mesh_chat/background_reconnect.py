"""Bounded mailbox reconnect supervisor for the Android availability service.

The renderer coordinator remains responsible for foreground UI attempts. This
thread exists so an unlocked-but-backgrounded process can establish a *native*
WebRTC data channel after a process restart without a WebView.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from .errors import IdentityMismatch, ValidationError

NATIVE_CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
]
MAX_PHASE_WAIT_SECONDS = 45.0
POLL_SECONDS = 5.0
BACKOFF_SECONDS = (1, 2, 5, 15, 30, 60)
BACKGROUND_STATES = {"background", "background_available", "suspended"}
DISCONNECTED_GRACE_SECONDS = 10.0
MAX_CONCURRENT_ATTEMPTS = 2


class BackgroundReconnectSupervisor:
    def __init__(self, service) -> None:
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, str] = {}
        self._attempt_sessions: dict[str, str] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._retry_at: dict[str, float] = {}
        self._requests: dict[str, dict[str, Any]] = {}
        self._completed_requests: dict[str, str] = {}
        self._last_scheduled: dict[str, float] = {}
        self._sessions_lock = threading.RLock()
        self._disconnected_since: dict[str, float] = {}
        self._unavailable_since: dict[str, float] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mesh-chat-background-reconnect",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._sessions_lock:
            pending = [*self._sessions.values()]
            pending.extend(self._attempt_sessions.values())
            self._sessions.clear()
            # Workers retain ownership until their blocking native call returns.
            # They must close again if creation finishes after this first close.
            self._disconnected_since.clear()
            self._unavailable_since.clear()
        for session_id in pending:
            try:
                self.service.native_webrtc_close(session_id)
            except Exception:
                pass

    def _run(self) -> None:
        failures: dict[str, int] = {}
        self._stop.wait(2.0)
        while not self._stop.is_set() and not self.service._shutdown.is_set():
            try:
                self._tick(failures)
            except Exception:
                # Initialization, locking and mailbox failures are retried.
                pass
            self._stop.wait(5.0)

    def _close_session(self, session_id: str) -> None:
        self._disconnected_since.pop(session_id, None)
        self._unavailable_since.pop(session_id, None)
        try:
            self.service.native_webrtc_close(session_id)
        except Exception:
            pass

    def _session_live(self, session_id: str) -> bool | None:
        try:
            stats = self.service.native_webrtc_stats(session_id)
        except Exception:
            since = self._unavailable_since.setdefault(session_id, time.monotonic())
            # Unknown health preserves an existing transport briefly, but may
            # never count as a successful attachment for a new negotiation.
            return None if time.monotonic() - since < DISCONNECTED_GRACE_SECONDS else False
        self._unavailable_since.pop(session_id, None)
        if not isinstance(stats, dict) or not stats.get("attached"):
            return False
        state = stats.get("ice_connection_state")
        if state in {"connected", "completed"}:
            self._disconnected_since.pop(session_id, None)
            return True
        if state == "disconnected":
            since = self._disconnected_since.setdefault(session_id, time.monotonic())
            return time.monotonic() - since < DISCONNECTED_GRACE_SECONDS
        return False

    @staticmethod
    def _retain_established(profile: dict[str, Any] | None) -> bool:
        if not profile or profile.get("state") == "stopped":
            return False
        effective = profile.get("effective") or {}
        reasons = effective.get("reasons") or []
        # A mailbox is needed to negotiate a replacement. An authenticated
        # live transport remains usable when only the mailbox is removed.
        return bool(effective.get("ready") or reasons and set(reasons) == {"mailbox_not_configured"})

    def _tick(self, failures: dict[str, int]) -> None:
        payload = self.service.reconnect_profiles()
        profiles = {item["id"]: item for item in payload.get("profiles", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)}
        background = self.service._workspace_lifecycle_state().get("state") in BACKGROUND_STATES
        with self._sessions_lock:
            existing = list(self._sessions.items())
        for profile_id, session_id in existing:
            profile = profiles.get(profile_id)
            if (not self._retain_established(profile)
                    or (not (profile.get("effective") or {}).get("ready")
                        and self._session_live(session_id) is False)):
                with self._sessions_lock:
                    self._sessions.pop(profile_id, None)
                self._close_session(session_id)
                failures.pop(profile_id, None)
        if not background:
            # The renderer discovers these service-owned sessions by profile
            # ID. Yield new negotiations, but preserve established native
            # transports when the person returns to the app.
            return
        eligible = []
        for profile_id, profile in profiles.items():
            if self._stop.is_set() or self.service._shutdown.is_set():
                return
            if not (profile.get("effective") or {}).get("ready") or profile.get("state") == "stopped":
                continue
            contact_id = profile.get("contact_id")
            if not isinstance(contact_id, str):
                continue
            if not profile.get("active"):
                self.service.reconnect_start(contact_id)
            with self._sessions_lock:
                session_id = self._sessions.get(profile_id)
            if session_id:
                if self._session_live(session_id) is not False:
                    continue
                with self._sessions_lock:
                    self._sessions.pop(profile_id, None)
                self._close_session(session_id)
            # A foreground-created native connection survives backgrounding.
            # Reuse it until it fails; the service reservation also fences races.
            other = self.service.native_reconnect_session(profile_id)
            with self._sessions_lock:
                if profile_id in self._workers:
                    continue
            if other:
                if self._session_live(other) is not False:
                    continue
                self._close_session(other)
            eligible.append(profile)
        # Health checks above always run, even while every negotiation slot is
        # occupied. Retry deadlines belong to each contact, never to the loop.
        with self._sessions_lock:
            for profile in sorted(eligible, key=lambda p: self._last_scheduled.get(p["id"], 0)):
                profile_id = profile["id"]
                if len(self._workers) >= MAX_CONCURRENT_ATTEMPTS:
                    break
                if profile_id in self._workers or self._retry_at.get(profile_id, 0) > time.monotonic():
                    continue
                worker = threading.Thread(target=self._attempt_worker, args=(profile, failures),
                                          name="mesh-chat-reconnect-peer", daemon=True)
                self._workers[profile_id] = worker
                self._last_scheduled[profile_id] = time.monotonic()
                worker.start()

    def _attempt_worker(self, profile, failures) -> None:
        profile_id = profile["id"]
        try:
            session_id = self._attempt(profile)
            try:
                self._current_profile(profile_id)
            except Exception:
                self._close_session(session_id)
                return
            with self._sessions_lock:
                cancelled = self._stop.is_set() or self.service._shutdown.is_set()
                if not cancelled:
                    self._sessions[profile_id] = session_id
                    failures[profile_id] = 0
                    self._retry_at.pop(profile_id, None)
            if cancelled:
                self._close_session(session_id)
        except Exception:
            with self._sessions_lock:
                count = failures.get(profile_id, 0)
                failures[profile_id] = count + 1
                self._retry_at[profile_id] = time.monotonic() + BACKOFF_SECONDS[min(count, len(BACKOFF_SECONDS) - 1)]
        finally:
            with self._sessions_lock:
                self._workers.pop(profile_id, None)

    def _current_profile(self, profile_id: str) -> dict[str, Any]:
        if self._stop.is_set() or self.service._shutdown.is_set():
            raise RuntimeError("Background reconnect stopped")
        if self.service._workspace_lifecycle_state().get("state") not in BACKGROUND_STATES:
            raise RuntimeError("Background reconnect yielded to the foreground")
        for profile in self.service.reconnect_profiles().get("profiles", []):
            if profile.get("id") == profile_id:
                if profile.get("active") and profile.get("state") != "stopped" and (profile.get("effective") or {}).get("ready"):
                    return profile
                break
        raise RuntimeError("Background reconnect profile is no longer eligible")

    def _step(self, profile_id: str, operation, *args, **kwargs):
        self._current_profile(profile_id)
        result = operation(*args, **kwargs)
        self._current_profile(profile_id)
        return result

    def _attempt(self, profile: dict[str, Any]) -> str:
        try:
            return self._negotiate(profile)
        except Exception:
            with self._sessions_lock:
                pending = self._attempt_sessions.pop(profile["id"], None)
            if pending:
                self._close_session(pending)
            raise

    def _negotiate(self, profile: dict[str, Any]) -> str:
        service = self.service
        profile_id = profile["id"]
        profile = self._current_profile(profile_id)
        contact_id = profile["contact_id"]
        preferred = bool((profile.get("effective") or {}).get("preferred"))
        ice = self._step(profile_id, service.call_ice_servers)
        if not profile.get("allow_direct_ip_disclosure"):
            ice = {**ice, "iceTransportPolicy": "relay"}
        attempt_id = uuid.uuid4().hex
        session_id = f"background-{attempt_id[:20]}"
        with self._sessions_lock:
            self._attempt_sessions[profile_id] = session_id
        # Native offer/answer creation can each spend 20 seconds gathering ICE.
        # Each network wait gets its own bounded budget after the preceding
        # step completes; otherwise valid answers arrive after a shared expiry.
        if preferred:
            # A peer may still be answering the previous mailbox request when
            # our polling window ends. Rotating on every retry can keep both
            # peers permanently one attempt apart after a restart.
            request = self._requests.get(profile_id)
            if request is None or request["expires_at"] <= time.time():
                request = self._step(profile_id, service.reconnect_request_create, contact_id, attempt_id)
                self._requests[profile_id] = request
            attempt_id = request["attempt_id"]
            self._step(profile_id, service.reconnect_publish, profile_id, request["document"], "request")
            def verify_offer(document):
                offer = service.verify_reconnect_offer(document, profile_id)
                if offer.get("attempt_id") != attempt_id:
                    raise IdentityMismatch("Offer belongs to an earlier request")
                return offer
            offer_document, offer = self._fetch(profile_id, "offer",
                time.monotonic() + MAX_PHASE_WAIT_SECONDS, verify_offer)
            native = self._step(profile_id, service.native_webrtc_accept,
                session_id,
                offer["sdp"],
                ice,
                NATIVE_CHANNELS,
                profile_id, background=True,
            )
            answer = self._step(profile_id, service.reconnect_answer_create,
                contact_id,
                offer_document,
                native["sdp"],
                native["fingerprint"],
            )
            self._step(profile_id, service.reconnect_publish, profile_id, answer["document"], "answer")
            self._requests.pop(profile_id, None)
        else:
            def verify_request(document):
                request = service.verify_reconnect_request(document, profile_id)
                if document == self._completed_requests.get(profile_id):
                    raise IdentityMismatch("Request belongs to an established connection")
                return request
            request_document, _ = self._fetch(profile_id, "request",
                time.monotonic() + MAX_PHASE_WAIT_SECONDS,
                verify_request)
            native = self._step(profile_id, service.native_webrtc_offer,
                session_id,
                ice,
                NATIVE_CHANNELS,
                profile_id, background=True,
            )
            offer = self._step(profile_id, service.reconnect_offer_create,
                contact_id,
                request_document,
                native["sdp"],
                native["fingerprint"],
            )
            self._step(profile_id, service.reconnect_publish, profile_id, offer["document"], "offer")
            _, answer = self._fetch(profile_id, "answer",
                time.monotonic() + MAX_PHASE_WAIT_SECONDS,
                lambda document: service.verify_reconnect_answer(document, offer["document"], profile_id))
            self._step(profile_id, service.native_webrtc_apply_answer, session_id, answer["sdp"])
        self._wait_attached(profile_id, session_id, time.monotonic() + MAX_PHASE_WAIT_SECONDS)
        self._current_profile(profile_id)
        if not preferred:
            # The mailbox retains the last request after a successful exchange.
            # After a disconnect, wait for the peer's new request instead of
            # publishing an offer for a connection it has already retired.
            self._completed_requests[profile_id] = request_document
        with self._sessions_lock:
            self._attempt_sessions.pop(profile_id, None)
        return session_id

    def _fetch(self, profile_id: str, role: str, deadline: float, verify) -> tuple[str, dict]:
        while not self._stop.is_set() and time.monotonic() < deadline:
            self._current_profile(profile_id)
            try:
                result = self.service.reconnect_fetch(profile_id, role)
            except Exception:
                result = None
            if isinstance(result, dict) and isinstance(result.get("document"), str) and result["document"]:
                try:
                    verified = self._step(profile_id, verify, result["document"])
                    return result["document"], verified
                except (IdentityMismatch, ValidationError):
                    # Mailboxes retain previous replies until TTL expiry. A
                    # stale or invalid reply must not destroy the current peer.
                    pass
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError(f"background reconnect {role} timed out")

    def _wait_attached(self, profile_id: str, session_id: str, deadline: float) -> None:
        while not self._stop.is_set() and time.monotonic() < deadline:
            self._current_profile(profile_id)
            if self._session_live(session_id) is True:
                return
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError("background reconnect DataChannel did not attach")
