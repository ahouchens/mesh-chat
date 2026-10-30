"""Scoped, read-only application requests after trusted host authentication.

This module does not authenticate IPC peers. A host must bind the authorizer to
an authenticated connection; callers never choose that function or its grants.
"""

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from threading import RLock
from typing import Protocol

from .views import connection_view


OPERATIONS = ("runtime.capabilities", "profile.query", "connection.snapshot")
MAX_PROFILES = 256
MAX_CONNECTIONS = 256
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
HANDLE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


@dataclass(frozen=True)
class Grant:
    caller: str
    permissions: frozenset[str]
    profiles: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.caller, str) or not 1 <= len(self.caller) <= 256
                or type(self.permissions) is not frozenset or type(self.profiles) is not tuple
                or len(self.profiles) > MAX_PROFILES or len(set(self.profiles)) != len(self.profiles)
                or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in self.profiles)):
            raise ValueError("Invalid trusted caller grant")


@dataclass(frozen=True)
class ProfileObservation:
    display_name: str
    destination: str
    connections: dict[str, dict]


class Observations(Protocol):
    def profile(self, internal_profile: str) -> ProfileObservation: ...


class ApiFailure(Exception):
    def __init__(self, code):
        self.code = code


class CoreSession:
    def __init__(self, authorize, observations: Observations, *, handle_key: bytes, transaction=None):
        if not isinstance(handle_key, bytes) or not 32 <= len(handle_key) <= 64:
            raise ValueError("A protected handle key is required")
        self._authorize = authorize
        self._observations = observations
        self._handle_key = handle_key
        self._transaction = transaction if transaction is not None else nullcontext()
        self._lock = RLock()
        self._caller = None
        self._negotiated = False
        self._closed = False

    def request(self, value):
        request_id = value.get("request_id") if isinstance(value, dict) else None
        if not isinstance(request_id, str) or REQUEST_ID.fullmatch(request_id) is None:
            request_id = None
        with self._lock, self._transaction:
            try:
                grant = self._grant()
                operation, params = self._parse(value)
                result = self._query(grant, operation, params)
                return {"api_version": 1, "request_id": request_id, "ok": True, "result": result}
            except ApiFailure as error:
                code = error.code
            except Exception:
                code = "internal"
        return {"api_version": 1, "request_id": request_id, "ok": False,
                "error": {"code": code, "retry_after_ms": None}}

    def detach(self):
        with self._lock:
            self._closed = True
            self._negotiated = False

    def _grant(self):
        if self._closed:
            raise ApiFailure("unauthenticated")
        grant = self._authorize()
        if not isinstance(grant, Grant) or (self._caller is not None and grant.caller != self._caller):
            self._closed = True
            raise ApiFailure("unauthenticated")
        self._caller = grant.caller
        if "observe" not in grant.permissions:
            raise ApiFailure("forbidden")
        return grant

    @staticmethod
    def _parse(value):
        if not isinstance(value, dict) or set(value) != {"api_version", "request_id", "operation", "params"}:
            raise ApiFailure("invalid_request")
        if type(value["api_version"]) is not int or value["api_version"] != 1:
            raise ApiFailure("incompatible_version")
        identifier = value["request_id"]
        if not isinstance(identifier, str) or REQUEST_ID.fullmatch(identifier) is None:
            raise ApiFailure("invalid_request")
        operation = value["operation"]
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ApiFailure("unsupported_operation")
        fields = {"runtime.capabilities": set(), "profile.query": {"profile"},
                  "connection.snapshot": {"profile", "connection"}}[operation]
        params = value["params"]
        if (not isinstance(params, dict) or set(params) != fields
                or any(not isinstance(item, str) or HANDLE.fullmatch(item) is None for item in params.values())):
            raise ApiFailure("invalid_request")
        return operation, params

    def _handle(self, grant, kind, profile, internal):
        material = json.dumps([grant.caller, kind, profile, internal], ensure_ascii=True,
                              separators=(",", ":")).encode("ascii")
        return hmac.new(self._handle_key, b"mesh-core-handle:v1:" + material, hashlib.sha256).hexdigest()

    def _query(self, grant, operation, params):
        profiles = {self._handle(grant, "profile", profile, profile): profile for profile in grant.profiles}
        if operation == "runtime.capabilities":
            self._negotiated = True
            return {"api_major": 1, "api_minor": 0, "stability": "experimental",
                    "operations": list(OPERATIONS), "profiles": list(profiles),
                    "limits": {"frame_bytes": 4194304, "profiles": MAX_PROFILES,
                               "connections_per_profile": MAX_CONNECTIONS}}
        if not self._negotiated:
            raise ApiFailure("negotiation_required")
        profile = profiles.get(params["profile"])
        if profile is None:
            raise ApiFailure("forbidden")
        view = self._observations.profile(profile)
        if len(view.connections) > MAX_CONNECTIONS:
            raise ApiFailure("resource_exhausted")
        connections = {self._handle(grant, "connection", profile, internal): status
                       for internal, status in view.connections.items()}
        if operation == "profile.query":
            if (not isinstance(view.display_name, str) or not 1 <= len(view.display_name) <= 80
                    or not isinstance(view.destination, str)
                    or re.fullmatch(r"[a-f0-9]{32}", view.destination) is None):
                raise ApiFailure("internal")
            return {"profile": params["profile"], "display_name": view.display_name,
                    "destination": view.destination, "connections": list(connections)}
        status = connections.get(params["connection"])
        if status is None:
            raise ApiFailure("forbidden")
        return {"profile": params["profile"], "connection": params["connection"],
                "observation": connection_view(status)}
