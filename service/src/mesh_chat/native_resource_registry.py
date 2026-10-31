"""Bound logical UI handles to private, non-reused native resource identities."""

from threading import RLock
import re
from uuid import uuid4

from .errors import NativeUnavailable


class NativeResourceRegistry:
    def __init__(self, limit=16):
        self._limit = limit
        self._epoch = uuid4().hex
        self._sequence = 0
        self._logical = {}
        self._physical = {}
        self._closed = set()
        self._lock = RLock()

    def reserve(self, logical):
        with self._lock:
            if logical in self._logical or len(self._logical) >= self._limit:
                raise NativeUnavailable("Native resource reservation unavailable")
            self._sequence += 1
            physical = f"native-{self._epoch}-{self._sequence}"
            self._logical[logical] = physical
            self._physical[physical] = logical
            return physical

    def physical(self, logical):
        with self._lock:
            return self._logical.get(logical)

    def restore(self, logical, physical):
        """Private startup registration after protected binding reconciliation."""
        with self._lock:
            if (logical in self._logical or physical in self._physical or len(self._logical) >= self._limit
                    or not isinstance(physical, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", physical)):
                raise NativeUnavailable("Native resource restoration unavailable")
            self._logical[logical] = physical
            self._physical[physical] = logical

    def require(self, logical):
        physical = self.physical(logical)
        if physical is None:
            raise NativeUnavailable("Native resource is no longer reserved")
        return physical

    def resolve(self, physical):
        with self._lock:
            return self._physical.get(physical)

    def current(self, logical, physical):
        with self._lock:
            return physical is not None and self._logical.get(logical) == physical

    def confirm_closed(self, logical, physical):
        with self._lock:
            if self.current(logical, physical):
                self._closed.add(physical)

    def closed(self, logical):
        with self._lock:
            return self._logical.get(logical) in self._closed

    def release(self, logical, physical):
        with self._lock:
            if not self.current(logical, physical):
                return False
            del self._logical[logical]
            del self._physical[physical]
            self._closed.discard(physical)
            return True
