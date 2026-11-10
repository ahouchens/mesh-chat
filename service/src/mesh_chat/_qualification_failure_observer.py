"""Default-off, invocation-local producer custody for private qualification.

Only immutable selected literals leave this module. Exception references are
temporary source witnesses, never a callback argument or a diagnostic payload.
The source hooks are pure bookkeeping and contain their own failures.
"""
from contextvars import ContextVar
import json
import re
import socket
import ssl
from urllib.error import HTTPError, URLError

from .errors import NetworkUnavailable, StorageUnavailable, ValidationError


_ACTIVE = ContextVar("qualification_core_failure", default=None)
_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_STAGES = {
    "runtime.capabilities": frozenset({"core_admission", "capabilities", "session_escape", "frame_encode"}),
    "call.ice_servers": frozenset({"core_admission", "ice_adapter", "ice_service", "ice_return", "ice_view",
        "broker_url", "broker_request", "tls_context", "broker_open", "broker_status", "broker_read",
        "broker_size", "broker_json", "broker_validate", "session_escape", "frame_encode"}),
}
_KNOWN_CAUSES = {ssl.SSLCertVerificationError: "certificate_verification", ssl.SSLError: "tls_other",
    socket.gaierror: "name_resolution", TimeoutError: "timeout", HTTPError: "http_error",
    json.JSONDecodeError: "json_decode", FileNotFoundError: "file_not_found", PermissionError: "permission_denied"}
_CATEGORIES = frozenset({"network_unavailable", "api_internal", "invalid_observation", "validation",
                         "storage_unavailable", "unexpected", "response_encoding"})
_CAUSES = frozenset(_KNOWN_CAUSES.values()) | {"other", "none", "unknown"}


def _cause(error):
    return BaseException.__dict__["__cause__"].__get__(error, BaseException)


def _affine(error, leaf):
    for depth in range(3):
        if error is leaf:
            return True
        if depth == 2:
            break
        error = _cause(error)
        if error is None:
            break
    return False


def _classify_cause(error):
    reason_used = False
    for depth in range(3):
        known = _KNOWN_CAUSES.get(type(error))
        if known is not None:
            return known
        if type(error) is URLError and not reason_used:
            reason_used = True
            reason = object.__getattribute__(error, "reason")
            known = _KNOWN_CAUSES.get(type(reason))
            if known is not None:
                return known
        following = _cause(error)
        if following is None:
            return "none" if depth == 0 and not reason_used else "other"
        if depth == 2:
            return "unknown"
        error = following


def _category(error):
    # ApiFailure is identified by the source catch which selected its code.
    from .core_api.errors import ApiFailure
    if isinstance(error, NetworkUnavailable):
        return "network_unavailable"
    if isinstance(error, ApiFailure):
        return "api_internal"
    if isinstance(error, ValidationError):
        return "validation"
    if isinstance(error, StorageUnavailable):
        return "storage_unavailable"
    return "unexpected"


class Invocation:
    def __init__(self, publication, caller, scope):
        self.publication, self.caller, self.scope = publication, caller, scope
        self.closed = self.disabled = False
        self.routed = self.admitted = self.framed = False
        self.request_id = self.operation = None
        self.leaf = self.outcome = None
        self.sealed = False

    def discard(self):
        self.disabled = True
        self.leaf = self.outcome = None
        self.sealed = False

    def close(self):
        self.closed = True
        self.leaf = self.outcome = None
        self.publication = None

    def route(self, service, host, installing, publication, event):
        if (self.routed or host is not None or installing
                or not self.publication.matches_route(service, publication, event)):
            self.discard()
        else:
            self.routed = True

    def admit(self, service, caller, scope):
        if (not self.routed or self.admitted or service is not self.publication.service()
                or type(caller) is not str or caller != self.caller
                or type(scope) is not str or scope != self.scope or scope != "owner"):
            self.discard()
        else:
            self.admitted = True

    def frame(self, request_id, operation):
        if (not self.admitted or self.framed or type(request_id) is not str
                or _REQUEST_ID.fullmatch(request_id) is None or type(operation) is not str
                or operation not in _STAGES):
            self.discard()
        else:
            self.framed = True
            self.request_id, self.operation = request_id, operation

    def grant(self, caller):
        if type(caller) is not str or caller != self.caller:
            self.discard()

    def caught(self, error, stage, category=None):
        if not self.framed or stage not in _STAGES[self.operation]:
            self.discard()
            return
        if self.leaf is not None and _affine(error, self.leaf[0]):
            return
        self.leaf = (error, stage, category)

    def success(self):
        self.leaf = self.outcome = None
        self.sealed = False

    def failure(self, error, code):
        self.outcome = None
        self.sealed = False
        if code != "internal" or not self.framed:
            self.leaf = None
            return
        stage, category = "core_admission", None
        if self.leaf is not None and _affine(error, self.leaf[0]):
            _, stage, category = self.leaf
        # This private token exists only for the actual source-selected outcome.
        self.outcome = (object(), stage, category or _category(error), _classify_cause(error))
        self.leaf = None

    def wire_failure(self, error, stage):
        self.success()
        self.caught(error, stage, "response_encoding" if stage == "frame_encode" else None)
        self.failure(error, "internal")

    def seal(self, request_id, code):
        self.sealed = (self.outcome is not None and type(request_id) is str
                       and request_id == self.request_id and type(code) is str and code == "internal")
        if not self.sealed:
            self.leaf = self.outcome = None

    def snapshot(self):
        if not self.sealed or not self.admitted or self.outcome is None:
            return None
        _, stage, category, cause = self.outcome
        if (type(stage) is not str or stage not in _STAGES[self.operation]
                or type(category) is not str or category not in _CATEGORIES
                or type(cause) is not str or cause not in _CAUSES
                or (category == "response_encoding") != (stage == "frame_encode")
                or (category == "invalid_observation" and stage not in {"ice_return", "ice_view"})):
            return None
        value = {"v": 1, "request_id": self.request_id, "operation": self.operation,
                 "error_code": "internal", "stage": stage, "category": category, "cause": cause}
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
        return encoded if len(encoded.encode("utf-8")) <= 1024 else None


def note(action, *selected):
    """Source-only custody; never calls external code and never raises."""
    invocation = None
    try:
        invocation = _ACTIVE.get()
        if invocation is not None and not invocation.closed and not invocation.disabled:
            getattr(invocation, action)(*selected)
    except Exception:
        if invocation is not None:
            # Do not rely on a possibly faulty instance method for fail-closed.
            invocation.disabled = True
            invocation.leaf = invocation.outcome = None
            invocation.sealed = False


def enter(invocation):
    outer = _ACTIVE.get()
    if outer is not None and not outer.closed:
        outer.discard()
        invocation = None
    return _ACTIVE.set(invocation)


def reset(token):
    _ACTIVE.reset(token)


def clear():
    _ACTIVE.set(None)
