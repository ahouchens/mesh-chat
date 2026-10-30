"""The only connection module allowed to know the concrete service surface."""

from time import monotonic, time
from uuid import uuid4

from ..errors import ContactNotApproved
from .adapters.reconnect import NativePort, ReconnectExecutor, SignalingPort
from .model import Execution
from .reconcile import authority_signature, connection_key
from .runtime import ConnectionRuntime


def native_runtime(service):
    def profiles():
        with service._dispatch_lock:
            return service.reconnect_profiles()

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
        native = NativePort(
            lambda *args: service.native_webrtc_offer(*args, runtime_owned=True),
            lambda *args: service.native_webrtc_accept(*args, runtime_owned=True),
            service.native_webrtc_apply_answer, service.native_webrtc_stats,
            service.webrtc_attach_native, service.native_webrtc_close,
        )
        return ReconnectExecutor(signaling, native, profile=fresh_profile,
                    ice=service.call_ice_servers, path=service.reconnect_path_status,
                    current=current, now=monotonic, wall_time=time)

    return ConnectionRuntime(uuid4().hex, factory, profiles=profiles, execution=execution,
                             activate=activate)
