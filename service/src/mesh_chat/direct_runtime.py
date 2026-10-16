"""Private, ephemeral service leases. No sockets, IPC commands or durable state.

A native owner must bind each lease to its own session and consume cancellation.
A successful check is not TLS authentication or permission to attach an adapter.
"""
from __future__ import annotations

import math
import threading
import time

from .errors import ValidationError


class SessionLease:
    def __init__(self, registry, deadline, check_authority):
        self._registry = registry
        self._deadline = deadline
        self._check_authority = check_authority
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._reason = None

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    @property
    def reason(self):
        return self._reason

    def cancel(self, reason="cancelled"):
        with self._lock:
            if not self.cancelled:
                self._reason = reason
                self._cancelled.set()
        self._registry._release(self)

    def check(self):
        if self.cancelled:
            return False
        if self._registry.clock() >= self._deadline:
            self.cancel("expired")
            return False
        try:
            self._check_authority()
        except Exception:
            self.cancel("authority_unavailable")
        if self._registry.clock() >= self._deadline:
            self.cancel("expired")
        return not self.cancelled


class SessionRegistry:
    MAX_SESSIONS = 8
    MAX_LIFETIME = 3600

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._sessions = set()
        self._closed = False

    def open(self, remaining, check_authority):
        if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
                or not math.isfinite(remaining) or not 0 < remaining <= self.MAX_LIFETIME):
            raise ValidationError("Direct runtime lifetime is invalid")
        deadline = self.clock() + remaining
        check_authority()
        with self._lock:
            if self._closed:
                raise ValidationError("Direct runtime is closed")
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise ValidationError("Direct runtime session budget exhausted")
            if self.clock() >= deadline:
                raise ValidationError("Direct runtime authorization expired")
            lease = SessionLease(self, deadline, check_authority)
            self._sessions.add(lease)
            return lease

    def _release(self, lease):
        with self._lock:
            self._sessions.discard(lease)

    def retire_all(self, reason="cancelled", *, close=False):
        with self._lock:
            self._closed = self._closed or close
            sessions, self._sessions = self._sessions, set()
        # No authority callbacks or native I/O during teardown.
        for lease in sessions:
            lease.cancel(reason)
