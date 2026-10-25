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

NATIVE_CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
]
MAX_ATTEMPT_SECONDS = 45.0
POLL_SECONDS = 1.0
BACKOFF_SECONDS = (1, 2, 5, 15, 30, 60)
BACKGROUND_STATES = {"background", "background_available", "suspended"}
DISCONNECTED_GRACE_SECONDS = 10.0


class BackgroundReconnectSupervisor:
    def __init__(self, service) -> None:
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, str] = {}
        self._attempt_session_id: str | None = None
        self._sessions_lock = threading.RLock()
        self._disconnected_since: dict[str, float] = {}

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
            if self._attempt_session_id:
                pending.append(self._attempt_session_id)
            self._sessions.clear()
            self._attempt_session_id = None
            self._disconnected_since.clear()
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
        try:
            self.service.native_webrtc_close(session_id)
        except Exception:
            pass

    def _session_live(self, session_id: str) -> bool:
        try:
            stats = self.service.native_webrtc_stats(session_id)
        except Exception:
            return False
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

    def _tick(self, failures: dict[str, int]) -> None:
        payload = self.service.reconnect_profiles()
        profiles = {item["id"]: item for item in payload.get("profiles", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)}
        background = self.service._workspace_lifecycle_state().get("state") in BACKGROUND_STATES
        with self._sessions_lock:
            existing = list(self._sessions.items())
        for profile_id, session_id in existing:
            profile = profiles.get(profile_id)
            if (not background or not profile or profile.get("state") == "stopped"
                    or not (profile.get("effective") or {}).get("ready")):
                with self._sessions_lock:
                    self._sessions.pop(profile_id, None)
                self._close_session(session_id)
                failures.pop(profile_id, None)
        if not background:
            return
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
                if self._session_live(session_id):
                    continue
                with self._sessions_lock:
                    self._sessions.pop(profile_id, None)
                self._close_session(session_id)
            # A foreground-created native connection survives backgrounding.
            # Reuse it until it fails; the service reservation also fences races.
            other = self.service.native_reconnect_session(profile_id)
            if other:
                if self._session_live(other):
                    continue
                self._close_session(other)
            attempts = failures.get(profile_id, 0)
            if attempts:
                self._stop.wait(BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS) - 1)])
            try:
                session_id = self._attempt(profile)
                with self._sessions_lock:
                    cancelled = self._stop.is_set() or self.service._shutdown.is_set()
                    if not cancelled:
                        self._sessions[profile_id] = session_id
                if cancelled:
                    self._close_session(session_id)
                    return
                failures[profile_id] = 0
            except Exception:
                failures[profile_id] = attempts + 1

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
                pending = self._attempt_session_id
                self._attempt_session_id = None
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
            self._attempt_session_id = session_id
        deadline = time.monotonic() + MAX_ATTEMPT_SECONDS
        if preferred:
            request = self._step(profile_id, service.reconnect_request_create, contact_id, attempt_id)
            self._step(profile_id, service.reconnect_publish, profile_id, request["document"], "request")
            offer_document = self._fetch(profile_id, "offer", deadline)
            offer = self._step(profile_id, service.verify_reconnect_offer, offer_document, profile_id)
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
        else:
            request_document = self._fetch(profile_id, "request", deadline)
            self._step(profile_id, service.verify_reconnect_request, request_document, profile_id)
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
            answer_document = self._fetch(profile_id, "answer", deadline)
            answer = self._step(profile_id, service.verify_reconnect_answer,
                answer_document, offer["document"], profile_id
            )
            self._step(profile_id, service.native_webrtc_apply_answer, session_id, answer["sdp"])
        self._wait_attached(profile_id, session_id, deadline)
        self._current_profile(profile_id)
        with self._sessions_lock:
            self._attempt_session_id = None
        return session_id

    def _fetch(self, profile_id: str, role: str, deadline: float) -> str:
        while not self._stop.is_set() and time.monotonic() < deadline:
            self._current_profile(profile_id)
            try:
                result = self.service.reconnect_fetch(profile_id, role)
            except Exception:
                result = None
            if isinstance(result, dict) and isinstance(result.get("document"), str) and result["document"]:
                return result["document"]
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError(f"background reconnect {role} timed out")

    def _wait_attached(self, profile_id: str, session_id: str, deadline: float) -> None:
        while not self._stop.is_set() and time.monotonic() < deadline:
            self._current_profile(profile_id)
            if self._session_live(session_id):
                return
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError("background reconnect DataChannel did not attach")
