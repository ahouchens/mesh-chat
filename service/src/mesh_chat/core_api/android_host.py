"""Android host binding: frames over Binder behind a host-fixed caller grant.

The Kotlin Binder service derives the caller package from ``Binder.getCallingUid``
and checks the signature permission before calling here. This module never accepts
a caller, grant or profile scope from the frame itself; the allowlist is a host
decision. Binder transaction limits are narrower than the facade ceiling, so the
Kotlin side caps frames before they arrive.

The application's own UID receives the ``owner`` scope (approval in addition to
the consumer grants); signature-permission packages receive ``consumer`` only.
"""

import threading
from weakref import WeakSet

from .composition import bind_service_stream
from .limits import MAX_FRAME_BYTES
from .session import Grant
from .wire_codec import encode_frame


# Third-party consumers may pair and connect, but never administer a vault.
CONSUMER_PERMISSIONS = frozenset({"observe", "read", "send", "pair", "connect", "diagnose"})
# The application's own UID may also approve workspace operations.
OWNER_PERMISSIONS = CONSUMER_PERMISSIONS | {"approve"}
SCOPES = {"consumer": CONSUMER_PERMISSIONS, "owner": OWNER_PERMISSIONS}
MAX_CALLERS = 8
MAX_CALLER_CHARS = 200

_lock = threading.RLock()
_sessions: dict[tuple[str, str], object] = {}
_service = None
_retired_services = WeakSet()


def _failure(code):
    return encode_frame({"api_version": 1, "request_id": None, "ok": False,
                         "error": {"code": code, "retry_after_ms": None}})


def _caller(value):
    if not isinstance(value, str) or not value or len(value) > MAX_CALLER_CHARS:
        return None
    return value if all(0x20 <= ord(character) <= 0x7E for character in value) else None


def exchange(service, caller, frame, scope="consumer"):
    """Exchange one frame for one Binder caller; never widens the host grant."""
    global _service
    permissions = SCOPES.get(scope) if isinstance(scope, str) else None
    if permissions is None:
        return _failure("forbidden")
    name = _caller(caller)
    if name is None:
        return _failure("forbidden")
    if not isinstance(frame, (bytes, bytearray)) or not 0 < len(frame) <= MAX_FRAME_BYTES:
        return _failure("invalid_request")
    key = (name, scope)
    with _lock:
        if service in _retired_services:
            return _failure("unavailable")
        if service is None or service._shutdown.is_set():
            if service is None or service is _service:
                if _service is not None:
                    _retired_services.add(_service)
                _detach_sessions()
                _service = None
            return _failure("unavailable")
        if _service is not service:
            if _service is not None:
                _retired_services.add(_service)
            _detach_sessions()
            _service = service
        session = _sessions.get(key)
        if session is None:
            if len(_sessions) >= MAX_CALLERS:
                return _failure("resource_exhausted")
            grant = Grant(name, permissions, ("local",))
            session = bind_service_stream(service, lambda: grant,
                                          private_native=scope == "owner")
            _sessions[key] = session
        reply = session.exchange(bytes(frame))
        if session.stopped:
            _sessions.pop(key, None)
        return reply


def close_all():
    """Detach every caller session without stopping the app-owned service."""
    global _service
    with _lock:
        _detach_sessions()
        _service = None


def _detach_sessions():
    sessions = tuple(_sessions.values())
    _sessions.clear()
    for session in sessions:
        session.close()


def active_callers():
    with _lock:
        return sorted({name for name, _ in _sessions})
