"""Android host binding: frames over Binder behind a host-fixed caller grant.

The Kotlin Binder service derives the caller package from ``Binder.getCallingUid``
and checks the signature permission before calling here. This module never accepts
a caller, grant or profile scope from the frame itself; the allowlist is a host
decision. Binder transaction limits are narrower than the facade ceiling, so the
Kotlin side caps frames before they arrive.
"""

import threading

from .composition import bind_service_stream
from .errors import ApiFailure
from .limits import MAX_FRAME_BYTES
from .session import Grant
from .wire_codec import encode_frame


# Third-party consumers never receive runtime ownership or approval rights.
PERMISSIONS = frozenset({"observe", "read", "send", "pair", "connect", "diagnose"})
MAX_CALLERS = 8
MAX_CALLER_CHARS = 200

_lock = threading.RLock()
_sessions: dict[str, object] = {}


def _failure(code):
    return encode_frame({"api_version": 1, "request_id": None, "ok": False,
                         "error": {"code": code, "retry_after_ms": None}})


def _caller(value):
    if not isinstance(value, str) or not value or len(value) > MAX_CALLER_CHARS:
        return None
    return value if all(0x20 <= ord(character) <= 0x7E for character in value) else None


def exchange(service, caller, frame):
    """Exchange one frame for one Binder caller; never widens the host grant."""
    if service is None:
        return _failure("unavailable")
    name = _caller(caller)
    if name is None:
        return _failure("forbidden")
    if not isinstance(frame, (bytes, bytearray)) or not 0 < len(frame) <= MAX_FRAME_BYTES:
        return _failure("invalid_request")
    with _lock:
        session = _sessions.get(name)
        if session is None:
            if len(_sessions) >= MAX_CALLERS:
                return _failure("resource_exhausted")
            grant = Grant(name, PERMISSIONS, ("local",))
            session = bind_service_stream(service, lambda: grant)
            _sessions[name] = session
        reply = session.exchange(bytes(frame))
        if session.stopped:
            _sessions.pop(name, None)
        return reply


def close_all():
    """Detach every caller session without stopping the app-owned service."""
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()


def active_callers():
    with _lock:
        return sorted(_sessions)
