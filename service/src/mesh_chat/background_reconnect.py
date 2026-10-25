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


class BackgroundReconnectSupervisor:
    def __init__(self, service) -> None:
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, str] = {}
        self._attempt_session_id: str | None = None

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
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        pending = [*self._sessions.values()]
        if self._attempt_session_id:
            pending.append(self._attempt_session_id)
        self._sessions.clear()
        self._attempt_session_id = None
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
                payload = self.service.reconnect_profiles()
            except Exception:
                self._stop.wait(5.0)
                continue
            try:
                lifecycle = self.service._workspace_lifecycle_state().get("state")
            except Exception:
                lifecycle = "foreground"
            if lifecycle in {"foreground", "active"}:
                # The renderer coordinator owns attempts while the app is
                # visible. Keeping a second native PC here would create a
                # duplicate path after resume.
                for session_id in self._sessions.values():
                    try:
                        self.service.native_webrtc_close(session_id)
                    except Exception:
                        pass
                self._sessions.clear()
                self._stop.wait(5.0)
                continue
            profiles = payload.get("profiles", [])
            if not isinstance(profiles, list):
                profiles = []
            for profile in profiles:
                if self._stop.is_set() or self.service._shutdown.is_set():
                    return
                if not isinstance(profile, dict):
                    continue
                effective = profile.get("effective") or {}
                if not effective.get("ready"):
                    continue
                profile_id = profile.get("id")
                contact_id = profile.get("contact_id")
                if not isinstance(profile_id, str) or not isinstance(contact_id, str):
                    continue
                if not profile.get("active"):
                    # An explicit per-contact stop must survive a background
                    # supervisor restart. Otherwise reactivate a consented
                    # profile the same way the renderer coordinator does.
                    if profile.get("state") == "stopped":
                        continue
                    try:
                        self.service.reconnect_start(contact_id)
                    except Exception:
                        continue
                session_id = self._sessions.get(profile_id)
                if session_id:
                    try:
                        stats = self.service.native_webrtc_stats(session_id)
                    except Exception:
                        stats = None
                    if isinstance(stats, dict) and stats.get("attached"):
                        continue
                    self._sessions.pop(profile_id, None)
                attempts = failures.get(profile_id, 0)
                delay = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS) - 1)]
                if attempts:
                    self._stop.wait(delay)
                    if self._stop.is_set():
                        return
                try:
                    self._sessions[profile_id] = self._attempt(profile)
                    failures[profile_id] = 0
                except Exception:
                    failures[profile_id] = attempts + 1
                    pending = self._attempt_session_id
                    self._attempt_session_id = None
                    if pending:
                        try:
                            self.service.native_webrtc_close(pending)
                        except Exception:
                            pass
            self._stop.wait(5.0)

    def _attempt(self, profile: dict[str, Any]) -> str:
        service = self.service
        profile_id = profile["id"]
        contact_id = profile["contact_id"]
        preferred = bool((profile.get("effective") or {}).get("preferred"))
        ice = service.call_ice_servers()
        attempt_id = uuid.uuid4().hex
        session_id = f"background-{attempt_id[:20]}"
        self._attempt_session_id = session_id
        deadline = time.monotonic() + MAX_ATTEMPT_SECONDS
        if preferred:
            request = service.reconnect_request_create(contact_id, attempt_id)
            service.reconnect_publish(profile_id, request["document"], "request")
            offer_document = self._fetch(profile_id, "offer", deadline)
            offer = service.verify_reconnect_offer(offer_document, profile_id)
            native = service.native_webrtc_accept(
                session_id,
                offer["sdp"],
                ice,
                NATIVE_CHANNELS,
            )
            answer = service.reconnect_answer_create(
                contact_id,
                offer_document,
                native["sdp"],
                native["fingerprint"],
            )
            service.reconnect_publish(profile_id, answer["document"], "answer")
        else:
            request_document = self._fetch(profile_id, "request", deadline)
            service.verify_reconnect_request(request_document, profile_id)
            native = service.native_webrtc_offer(
                session_id,
                ice,
                NATIVE_CHANNELS,
            )
            offer = service.reconnect_offer_create(
                contact_id,
                request_document,
                native["sdp"],
                native["fingerprint"],
            )
            service.reconnect_publish(profile_id, offer["document"], "offer")
            answer_document = self._fetch(profile_id, "answer", deadline)
            answer = service.verify_reconnect_answer(
                answer_document, offer["document"], profile_id
            )
            service.native_webrtc_apply_answer(session_id, answer["sdp"])
        self._wait_attached(session_id, deadline)
        self._attempt_session_id = None
        return session_id

    def _fetch(self, profile_id: str, role: str, deadline: float) -> str:
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                result = self.service.reconnect_fetch(profile_id, role)
            except Exception:
                result = None
            if isinstance(result, dict) and isinstance(result.get("document"), str):
                return result["document"]
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError(f"background reconnect {role} timed out")

    def _wait_attached(self, session_id: str, deadline: float) -> None:
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                stats = self.service.native_webrtc_stats(session_id)
            except Exception:
                stats = None
            if isinstance(stats, dict) and stats.get("attached"):
                return
            self._stop.wait(POLL_SECONDS)
        raise TimeoutError("background reconnect DataChannel did not attach")
