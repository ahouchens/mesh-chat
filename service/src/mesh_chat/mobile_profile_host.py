"""Trusted Android composition for an existing OS key slot and runtime Core.

The native provider is an object installed by Kotlin, never request JSON. The
catalog holds derived handle authority; openers fetch the original key afresh.
"""
import base64
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

from .core_api.android_host import MAX_CALLERS, SCOPES
from .core_api.errors import ApiFailure
from .core_api.runtime_host import CoreRuntimeHost, RegisteredProfile
from .core_api.session import Grant
from .core_api.wire_codec import decode_frame, encode_frame
from .errors import NativeUnavailable

PROFILE_SLOT = "primary"
AUTH_LIFETIME = 60


def native_key(value):
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError
        key = base64.b64decode(value, validate=True)
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise NativeUnavailable("Native key slot is unavailable") from None


def provider_identity(provider, *, namespace="mesh-chat"):
    try:
        directory = Path(str(provider.profileDirectory())).resolve()
        caller = str(provider.ownerCaller())
        if (namespace not in {"mesh-chat", "mesh-core-runtime"}
                or directory.name != "profile-v1" or directory.parent.name != namespace
                or not directory.is_absolute() or not 1 <= len(caller) <= 200
                or any(not 0x20 <= ord(character) <= 0x7E for character in caller)):
            raise ValueError
        return directory, caller
    except Exception:
        raise NativeUnavailable("Native profile provider is unavailable") from None


class NativeMobileProfileHost:
    def __init__(self, provider, catalog_store, *, open_profile, publish,
                 active=None, emit=lambda _: None, now=monotonic, public_only=False):
        if type(public_only) is not bool:
            raise NativeUnavailable("Native profile host binding is invalid")
        self.public_only = public_only
        self._namespace = "mesh-core-runtime" if public_only else "mesh-chat"
        self.directory, self.caller = provider_identity(provider, namespace=self._namespace)
        if (catalog_store.profile_dir.resolve() != self.directory.parent / "host-v1"
                or (active is not None and (active.store.profile_dir.resolve() != self.directory
                    or getattr(active, "_connection_policy", None) != "shared-native"))):
            raise NativeUnavailable("Native profile path or owner policy changed")
        self.provider, self.store = provider, catalog_store
        self._now, self._emit = now, emit
        self._sessions, self._session_lock = {}, RLock()
        self._challenges, self._auth_lock, self._issuing = {}, RLock(), None
        self._generation, self._last_context = uuid4().hex, None
        self._closed = False
        self._native_lock_key = None
        cached = catalog_store.get("host_profile", PROFILE_SLOT)
        if active is None and cached is None:
            raise NativeUnavailable("Initial slot registration requires its current profile")
        try:
            handle_key = (bytes.fromhex(active.store.opaque_id("core-api-handle-key", "v1")) if active is not None
                          else bytes.fromhex(cached["handle_key"]))
            label = ((active.store.get("profile", "local") or {}).get("display_name", "Profile") if active is not None
                     else cached["display_name"])
            def opener():
                # This closure retains only the provider, not a decrypt key.
                return open_profile(self.directory, native_key(str(self.provider.profileKey())))
            registered = RegisteredProfile(PROFILE_SLOT, label, handle_key, opener)
            self.core = CoreRuntimeHost(catalog_store, (registered,), selected=PROFILE_SLOT,
                publish=publish, credential_authorizer=self._credential_authorized, active=active)
        except Exception:
            raise NativeUnavailable("Native profile registration is unavailable") from None

    def rebind(self, provider):
        if provider_identity(provider, namespace=self._namespace) != (self.directory, self.caller):
            raise NativeUnavailable("Native profile provider binding changed")
        with self._auth_lock:
            self._challenges.clear()
            self.provider = provider

    def _grant(self, caller, scope):
        permissions = SCOPES.get(scope)
        if (self._closed or permissions is None or not isinstance(caller, str)
                or not 1 <= len(caller) <= 200 or any(not 0x20 <= ord(char) <= 0x7E for char in caller)
                or (scope == "owner" and caller != self.caller)):
            raise ApiFailure("forbidden")
        return Grant(caller, permissions | ({"profile_owner"} if scope == "owner" else set()), (PROFILE_SLOT,))

    def context(self):
        catalog = self.core.catalog(self._grant(self.caller, "owner"))
        status = self.core.lifecycle.query()
        return {"profile": catalog["selected_profile"], "revision": status["revision"],
                "state": status["state"], "host_generation": self._generation}

    def _notify(self):
        context = self.context()
        if self._last_context != context:
            self._emit({"type": "event", "event": "profile_lifecycle", **context})
            self._last_context = context

    def exchange(self, caller, frame, scope):
        identifier = None
        try:
            self._grant(caller, scope)
            if not isinstance(frame, (bytes, bytearray)) or not 0 < len(frame) <= 4194304:
                raise ApiFailure("invalid_request")
            request = decode_frame(frame)
            if not isinstance(request, dict):
                raise ApiFailure("invalid_request")
            identifier, operation = request.get("request_id"), request.get("operation")
            with self._session_lock:
                session = self._sessions.get((caller, scope))
                if session is None:
                    if len(self._sessions) >= MAX_CALLERS:
                        raise ApiFailure("resource_exhausted")
                    session = self.core.bind(lambda: self._grant(caller, scope),
                        private_native=scope == "owner" and not self.public_only,
                        private_composer_legacy=scope == "owner" and not self.public_only,
                        private_profile_bootstrap=scope == "owner")
                    self._sessions[caller, scope] = session
            before = self.context()
            reply = session.exchange(bytes(frame))
            if operation not in {"runtime.capabilities", "profile.catalog", "profile.lock", "profile.select", "profile.unlock"}:
                if before != self.context():
                    raise ApiFailure("resync_required")
            self._notify()
            return reply
        except ApiFailure as error:
            code = error.code
        except (ValueError, TypeError, RecursionError):
            code = "invalid_request"
        except Exception:
            code = "unavailable"
        return encode_frame({"api_version": 1, "request_id": identifier, "ok": False,
                             "error": {"code": code, "retry_after_ms": None}})

    def begin_authentication(self, profile):
        with self._auth_lock:
            context = self.context()
            if profile != context["profile"]:
                raise ApiFailure("forbidden")
            if context["state"] == "retiring":
                raise ApiFailure("unavailable")
            now = self._now()
            self._challenges = {key: value for key, value in self._challenges.items() if value[1] > now}
            if len(self._challenges) >= 8:
                raise ApiFailure("resource_exhausted")
            challenge = uuid4().hex
            self._challenges[challenge] = dict(context), now + AUTH_LIFETIME
            return {"challenge": challenge, **context}

    def cancel_authentication(self, challenge):
        with self._auth_lock:
            self._challenges.pop(challenge, None)

    def _credential_authorized(self, caller, profile_id):
        challenge = self._issuing
        return (not self._closed and challenge is not None and caller == self.caller and profile_id == PROFILE_SLOT
                and self.provider.consumeAuthorization(challenge, caller, profile_id) is True)

    def complete_authentication(self, challenge):
        with self._auth_lock:
            admitted = self._challenges.pop(challenge, None)
            if admitted is None or admitted[1] <= self._now() or admitted[0] != self.context():
                raise ApiFailure("resync_required")
            try:
                self._issuing = challenge
                token = self.core.issue_unlock_credential(self.caller, PROFILE_SLOT)
                if admitted[0] != self.context():
                    raise ApiFailure("resync_required")
            finally:
                self._issuing = None
            return {"credential_handle": token, "expires_in_ms": AUTH_LIFETIME * 1000,
                    "revision": admitted[0]["revision"], "host_generation": self._generation}

    def lock(self):
        # Legacy native Lock is still a real host-bound Core request. Runtime
        # metadata and catalog survive; no initializer opens a locked slot.
        if self._native_lock_key is None:
            self._native_lock_key = str(uuid4())
        for operation, params, key in (
            ("runtime.capabilities", {}, None),
            ("profile.lock", {"profile": self.context()["profile"]}, self._native_lock_key),
        ):
            request = {"api_version": 1, "request_id": "native:lock", "operation": operation, "params": params}
            if key is not None:
                request["idempotency_key"] = key
            reply = decode_frame(self.exchange(self.caller, encode_frame(request), "owner"))
            if not reply.get("ok"):
                raise ApiFailure(reply["error"]["code"])
        context = self.context()
        if context["state"] != "locked":
            raise ApiFailure("unavailable")
        self._native_lock_key = None
        return context

    def close(self):
        if self._closed:
            self.store.close()
            return
        sessions = ()
        try:
            # Serialize host teardown with Core admission. Close framed clients
            # after releasing this lock: a client may already be waiting on it.
            with self.core._lock:
                # Host termination can drain an interrupted unlock without
                # authorizing it to open again. Its old-host journal intent
                # deliberately resolves to resync after a cold host restart.
                self.core.lifecycle.retire_for_host_shutdown()
                if self.core.lifecycle.query()["state"] != "locked":
                    raise NativeUnavailable("Native profile retirement is incomplete")
                self._closed = True
                with self._session_lock:
                    sessions, self._sessions = tuple(self._sessions.values()), {}
                self.store.close()
                self._challenges.clear()
        finally:
            for session in sessions:
                session.close()
