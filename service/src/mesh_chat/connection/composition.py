"""The only connection module allowed to know the concrete service surface."""

from time import monotonic, time
from uuid import uuid4

from ..errors import ContactNotApproved, NativeUnavailable
from .adapters.reconnect import NativePort, ReconnectExecutor, SignalingPort
from .model import Execution, Resource
from .reconcile import authority_signature, connection_key
from .runtime import ConnectionRuntime


def native_runtime(service):
    def profiles():
        with service._dispatch_lock:
            payload = service.reconnect_profiles()
            return {**payload, "profiles": [
                {**profile, "manual_carrier_authorized": service.native_manual_carrier_authorized(profile["id"])}
                for profile in payload["profiles"]
            ]}

    def execution():
        if service._shutdown.is_set():
            return Execution.SHUTTING_DOWN
        if service._identity is None:
            return Execution.LOCKED
        background = service._workspace_lifecycle_state().get("state") in {
            "background", "background_available", "suspended"}
        if background and not service._background_availability_enabled():
            return Execution.PAUSED
        return Execution.AVAILABLE

    def activate(contact_id):
        with service._dispatch_lock:
            # Reconciliation may enable a default, but cannot undo explicit Stop.
            service.reconnect_start(contact_id, automatic=True)

    def factory(current, cached_profile):
        def fresh_profile(key):
            cached = cached_profile(key)
            if cached.get("state") == "stopped":
                return cached
            for value in profiles()["profiles"]:
                if connection_key(value) == key:
                    if authority_signature(value) != authority_signature(cached):
                        raise ContactNotApproved("Connection authority revision changed")
                    return value
            raise ContactNotApproved("Connection profile was removed")

        signaling = SignalingPort(
            service.reconnect_request_create, service.reconnect_offer_create,
            service.reconnect_answer_create, service.verify_reconnect_request,
            service.verify_reconnect_offer, service.verify_reconnect_answer,
            service.reconnect_publish, service.reconnect_fetch,
        )
        bindings = _NativeBindings(service)
        native = NativePort(
            lambda *args: service.native_webrtc_offer(*args, runtime_owned=True),
            lambda *args: service.native_webrtc_accept(*args, runtime_owned=True),
            service.native_webrtc_apply_answer, bindings.stats,
            bindings.attach, bindings.close,
            lambda key: _claim_carrier(service, key),
        )
        return ReconnectExecutor(signaling, native, profile=fresh_profile,
                    ice=service.call_ice_servers, path=service.reconnect_path_status,
                    current=current, now=monotonic, wall_time=time)

    return ConnectionRuntime(uuid4().hex, factory, profiles=profiles, execution=execution,
                             activate=activate)


def _claim_carrier(service, key):
    with service._dispatch_lock:
        session = service.claim_native_reconnect_carrier(key.profile_id, key.local_device, key.remote_device)
        return Resource("native", service._native_resources.require(session)) if session is not None else None


class _NativeBindings:
    """Adopted handles name physical peers; generated attempt IDs are never reused."""

    def __init__(self, service):
        self.service = service

    def _session(self, resource):
        session = self.service._native_resources.resolve(resource)
        if session is not None:
            return session
        if resource.startswith("connection-"):
            return resource
        raise NativeUnavailable("Adopted native allocation was retired")

    def stats(self, resource):
        with self.service._dispatch_lock:
            return self.service.native_webrtc_stats(self._session(resource))

    def attach(self, resource):
        with self.service._dispatch_lock:
            session = self._session(resource)
            physical = self.service._native_resources.require(session)
        return self.service.webrtc_attach_native(session, expected_physical=physical)

    def close(self, resource):
        if resource.startswith("connection-"):
            return self.service.native_webrtc_close(resource)
        session = self.service._native_resources.resolve(resource)
        if session is not None:
            return self.service.native_webrtc_close(session, expected_physical=resource)
