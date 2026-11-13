"""In-process bridge used by the Android and iOS Tauri plugins.

Desktop builds deliberately keep using the framed sidecar protocol.  Mobile
platforms cannot spawn that executable safely, so their native plugin embeds
CPython and calls this small JSON boundary on a dedicated worker thread.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .errors import MeshChatError, NativeUnavailable, ValidationError, WORKSPACE_ALREADY_KNOWN_REASONS, WorkspaceAlreadyKnown
from .direct_native import NativeChannel
from .network import install_embedded_runtime_guards
from .service import MeshChatService
from .vault import VaultStore

IPC_VERSION = 1
MAX_JSON_BYTES = 64 * 1024
# Match the renderer payload bounds in src-tauri/src/lib.rs. The native bridge
# adds a command envelope around that payload, so reserve separate, bounded
# headroom rather than applying the smaller default request limit to invitations.
MAX_RENDERER_PAYLOAD_BYTES = 32 * 1024
MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES = 128 * 1024
MAX_COMMAND_ENVELOPE_BYTES = 1024
COMMAND_PAYLOAD_LIMITS = {
    "webrtc_onboarding_offer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "verify_webrtc_onboarding_offer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "webrtc_onboarding_answer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "verify_webrtc_onboarding_answer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "native_webrtc_offer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "native_webrtc_accept": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "native_webrtc_apply_answer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "native_webrtc_bind_onboarding": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "signal_publish": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "reconnect_offer_create": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "reconnect_answer_create": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "verify_reconnect_offer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "verify_reconnect_answer": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "reconnect_publish": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "start_call": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "answer_call": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "restart_call": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "answer_call_restart": MAX_WEBRTC_SIGNALING_PAYLOAD_BYTES,
    "preview_direct_connection": 2 * 1024 * 1024,
    "prepare_direct_answer": 2 * 1024 * 1024,
    "prepare_direct_ready": 2 * 1024 * 1024,
    "accept_direct_ready": 2 * 1024 * 1024,
    "connect_direct_setup": 2 * 1024 * 1024,
    "preview_workspace_device_link": 700 * 1024,
    "submit_workspace_device_link": 700 * 1024,
    "preview_workspace_invitation": 600 * 1024,
    "submit_workspace_join": 600 * 1024,
    "create_connection_reply": 600 * 1024,
    "preview_connection_reply": 41 * 1024,
    "connect_using_reply": 41 * 1024,
    "preview_route_update": 25 * 1024,
    "apply_route_update": 25 * 1024,
}
MAX_COMMAND_JSON_BYTES = max(COMMAND_PAYLOAD_LIMITS.values()) + MAX_COMMAND_ENVELOPE_BYTES
_service_lock = threading.RLock()
_events_lock = threading.Lock()
_service: MeshChatService | None = None
_native_channel: NativeChannel | None = None
_service_binding: tuple | None = None
_event_incarnation: str | None = None
_retiring_service: MeshChatService | None = None
_retiring_channel: NativeChannel | None = None
_opening_channel: NativeChannel | None = None
_events: deque[dict[str, Any]] = deque(maxlen=256)
_event_overflow = False
_profile_host = None
_profile_install_lock = threading.RLock()
_profile_installing = False
_retiring_catalog = None


class _StoreRetirement:
    """Exact custody when a store opened but no service could be constructed."""
    def __init__(self, store):
        self.store = store
        self._shutdown = threading.Event()
        self._shutdown.set()
        self._store_closed = False
        self._runtime_incarnation = uuid.uuid4().hex
        self._lock = threading.Lock()

    def close(self):
        with self._lock:
            if not self._store_closed:
                self.store.close()
                self._store_closed = True


def _loads(raw: str, *, maximum=MAX_JSON_BYTES) -> dict[str, Any]:
    if not isinstance(raw, str) or not 1 <= len(raw.encode("utf-8")) <= maximum:
        raise ValidationError("Mobile bridge request is invalid")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError("Mobile bridge request is invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("Mobile bridge request is invalid")
    return value


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _error(exc: Exception) -> str:
    code = exc.code if isinstance(exc, MeshChatError) else "internal_error"
    error: dict[str, Any] = {"code": code}
    # A saved-workspace refusal is actionable only when the renderer can
    # distinguish a changed invitation from an active/terminal request.
    if (isinstance(exc, WorkspaceAlreadyKnown)
            and exc.reason in WORKSPACE_ALREADY_KNOWN_REASONS):
        error["details"] = {"reason": exc.reason}
    return _dumps({"ok": False, "error": error})


def _emit(value: dict[str, Any], *, incarnation: str | None = None) -> None:
    # Network callbacks can emit from an RNS worker while a renderer command is
    # executing.  Keep event delivery independent from the service lifecycle
    # lock so a command waiting for that worker cannot deadlock the bridge.
    global _event_overflow
    overflow = False
    service = _service
    with _events_lock:
        if incarnation is not None and incarnation != _event_incarnation:
            return
        overflow = len(_events) == _events.maxlen
        _events.append(value)
        if overflow:
            _event_overflow = True
    if overflow:
        # Persist the gap after releasing the event lock. A renderer refresh
        # can then request bounded authoritative reconciliation instead of
        # treating a coalesced/dequeued event stream as complete.
        shutdown = getattr(service, "_shutdown", None)
        if (service is not None and service is _service and not (shutdown is not None and shutdown.is_set())
                and (incarnation is None or incarnation == _event_incarnation)):
            service._mark_workspace_invalidation_overflow()


def initialize_native(raw: str) -> str:
    """Trusted host entry; JSON cannot opt into a different connection owner."""
    return initialize(raw, connection_policy="shared-native")


def _profile_error(error):
    from .core_api.errors import ApiFailure
    return (_dumps({"ok": False, "error": {"code": error.code}})
            if isinstance(error, ApiFailure) else _error(error))


def _profile_host_event(value):
    global _retiring_service, _retiring_channel
    with _service_lock:
        if _retiring_service is not None and _retiring_service._store_closed:
            _retiring_service = _retiring_channel = None
    host = _profile_host
    publish = getattr(host.provider, "publicationChanged", None) if host is not None else None
    if callable(publish):
        publish(_dumps(value))
    _emit(value)


def _publish_profile_service(service):
    global _service, _native_channel, _service_binding, _event_incarnation
    global _retiring_service, _retiring_channel, _event_overflow
    with _service_lock:
        if service is not None and _retiring_service is not None and not _retiring_service._store_closed:
            raise NativeUnavailable("Previous mobile profile is still retiring")
        if _service is not None and _service is not service:
            _retiring_service, _retiring_channel = _service, _native_channel
        _service = service
        _native_channel = getattr(service, "_mobile_channel", None)
        _service_binding = getattr(service, "_mobile_binding", None)
        with _events_lock:
            _event_incarnation = getattr(service, "_mobile_event_incarnation", None)
            _events.clear()
            _event_overflow = False
        if _retiring_service is not None and _retiring_service._store_closed:
            _retiring_service = _retiring_channel = None


def _open_profile_slot(directory, key, *, native_channel=True):
    global _retiring_service, _retiring_channel, _opening_channel
    from .direct_bootstrap_mobile import AndroidBootstrapProcess
    from .service import NativeStartupIncomplete
    with _service_lock:
        if (_service is not None or _opening_channel is not None
                or (_retiring_service is not None and not _retiring_service._store_closed)):
            raise NativeUnavailable("Previous mobile profile is still retiring")
    channel, incarnation = NativeChannel() if native_channel else None, uuid.uuid4().hex
    store = VaultStore(directory, key, native_mobile_protection="android")
    service = None
    try:
        host = _profile_host
        if host is not None:
            from .mobile_profile_host import PROFILE_SLOT
            if bytes.fromhex(store.opaque_id("core-api-handle-key", "v1")) != host.core.profiles[PROFILE_SLOT].handle_key:
                raise NativeUnavailable("Native key slot authority changed")
        with _service_lock:
            if _retiring_service is not None and _retiring_service._store_closed:
                _retiring_service = _retiring_channel = None
            _opening_channel = channel
        # The app's native dispatcher may still hold keyless transport objects
        # from the previous profile. Acknowledge its reset before any service
        # worker can allocate or restore resources for this profile.
        if channel is not None:
            channel.request("reset")
        else:
            # This app-owned host has no Rust direct-UDP dispatcher. Its actual
            # JNI WebRTC host must have acknowledged every previous lease.
            from .native_webrtc_host import android_host
            accounting = json.loads(str(android_host().resourceAccounting()))
            result = accounting.get("result") or {}
            if (accounting.get("ok") is not True or result.get("complete") is not True
                    or type(result.get("reserved_count")) is not int or result["reserved_count"] != 0):
                raise NativeUnavailable("Native WebRTC retirement is incomplete")
            if store.get("settings", "network") is None:
                from .reticulum_config import NetworkSettings
                store.put("settings", "network",
                    NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
        service = MeshChatService(store, directory, lambda value: _emit(value, incarnation=incarnation),
                                  direct_native=channel, connection_policy="shared-native")
        service._direct_bootstrap_factory = AndroidBootstrapProcess
    except Exception as error:
        failed = getattr(error, "retiring_service", service)
        if failed is None:
            try:
                store.close()
            except Exception:
                failed = _StoreRetirement(store)
                with _service_lock:
                    _retiring_service, _retiring_channel = failed, channel
                raise NativeStartupIncomplete(failed) from error
        else:
            failed._mobile_channel = channel
            failed._mobile_event_incarnation = incarnation
            try:
                failed.close()
            except Exception:
                with _service_lock:
                    _retiring_service, _retiring_channel = failed, channel
                raise NativeStartupIncomplete(failed) from error
            if not failed._store_closed:
                with _service_lock:
                    _retiring_service, _retiring_channel = failed, channel
                raise NativeStartupIncomplete(failed) from error
        raise
    finally:
        with _service_lock:
            if _opening_channel is channel:
                _opening_channel = None
    service._mobile_channel, service._mobile_event_incarnation = channel, incarnation
    service._mobile_binding = (str(directory), hashlib.sha256(key).digest(), "android", "shared-native")
    return service


def initialize_native_host(provider, display_name=None):
    """Kotlin-only object capability; a registered cold start stays locked."""
    return _initialize_native_host(provider, display_name, public_only=False)


def initialize_app_owned_host(provider):
    """Installing application's object capability; no Tauri or renderer port."""
    return _initialize_native_host(provider, None, public_only=True)


def _initialize_native_host(provider, display_name, *, public_only):
    global _profile_installing
    with _profile_install_lock:
        with _service_lock:
            _profile_installing = True
        try:
            return _install_native_host(provider, display_name, public_only=public_only)
        finally:
            with _service_lock:
                _profile_installing = False


def _close_retiring_catalog():
    global _retiring_catalog
    if _retiring_catalog is not None:
        _retiring_catalog.close()
        _retiring_catalog = None


def _install_native_host(provider, display_name, *, public_only):
    global _profile_host
    global _retiring_catalog
    from .mobile_profile_host import NativeMobileProfileHost, native_key, provider_identity, PROFILE_SLOT
    catalog = None
    created_profile = False
    try:
        directory, _ = provider_identity(provider,
            namespace="mesh-core-runtime" if public_only else "mesh-chat")
        with _profile_install_lock:
            if _profile_host is not None:
                if _profile_host.public_only != public_only:
                    raise NativeUnavailable("Native runtime ownership cannot change")
                _profile_host.rebind(provider)
                active = _profile_host.core.lifecycle.active
                return (_dumps({"ok": True, "result": active.snapshot()}) if active is not None
                        else _dumps({"ok": False, "error": {"code": "locked"}}))
            with _service_lock:
                if _retiring_service is not None:
                    _close_service()
                    if _retiring_service is not None:
                        raise NativeUnavailable("Previous mobile profile is still retiring")
            _close_retiring_catalog()
            catalog = VaultStore(directory.parent / "host-v1", native_key(str(provider.catalogKey())),
                                 native_mobile_protection="android")
            if catalog.get("host_profile", PROFILE_SLOT) is None and _service is None:
                try:
                    active = _open_profile_slot(directory, native_key(str(provider.profileKey())),
                        **({"native_channel": False} if public_only else {}))
                    created_profile = True
                    _publish_profile_service(active)
                    if display_name is not None and active.store.get("profile", "local") is None:
                        active.create_profile(display_name)
                except Exception as error:
                    failed = getattr(error, "retiring_service", None)
                    if failed is not None:
                        # The opener itself already retained its response channel.
                        created_profile = True
                    raise
            active = _service
            if active is not None:
                active._mobile_channel, active._mobile_event_incarnation = _native_channel, _event_incarnation
                active._mobile_binding = _service_binding
            opener = ((lambda directory, key: _open_profile_slot(directory, key, native_channel=False))
                      if public_only else _open_profile_slot)
            host = NativeMobileProfileHost(provider, catalog, open_profile=opener,
                publish=_publish_profile_service, active=active, emit=_profile_host_event, public_only=public_only)
            _profile_host = host
            catalog = None  # The runtime host now owns the independent catalog.
            host._notify()
            return (_dumps({"ok": True, "result": active.snapshot()}) if active is not None
                    else _dumps({"ok": False, "error": {"code": "locked"}}))
    except Exception as error:
        try:
            if created_profile:
                with _service_lock:
                    _close_service()
        except Exception as cleanup_error:
            error = cleanup_error
        finally:
            if catalog is not None:
                _retiring_catalog = catalog
                try:
                    _close_retiring_catalog()
                except Exception:
                    pass  # Exact metadata key ownership survives failed close.
        return _profile_error(error)


def _native_profile_call(operation, *args):
    try:
        host = _profile_host
        if host is None:
            from .core_api.errors import ApiFailure
            raise ApiFailure("unsupported_operation")
        return _dumps({"ok": True, "result": getattr(host, operation)(*args)})
    except Exception as error:
        return _profile_error(error)


def begin_profile_unlock_auth(profile):
    return _native_profile_call("begin_authentication", profile)


def complete_profile_unlock_auth(challenge):
    return _native_profile_call("complete_authentication", challenge)


def cancel_profile_unlock_auth(challenge):
    return _native_profile_call("cancel_authentication", challenge)


def lock_profile_host():
    return _native_profile_call("lock")


def profile_runtime_context():
    return _native_profile_call("context")


def initialize(raw: str, *, connection_policy="legacy") -> str:
    """Start from an app-private directory; policy is a trusted host option only."""

    global _service, _native_channel, _service_binding, _event_incarnation, _retiring_service, _retiring_channel
    try:
        if connection_policy not in {"legacy", "shared-native"}:
            raise ValidationError("Mobile connection policy is invalid")
        request = _loads(raw)
        if set(request) - {"profile_dir", "vault_key", "display_name", "platform"}:
            raise ValidationError("Mobile initialization request is invalid")
        profile_value = request.get("profile_dir")
        key_value = request.get("vault_key")
        platform_value = request.get("platform")
        display_name = request.get("display_name")
        if (
            not isinstance(profile_value, str)
            or not profile_value
            or "\x00" in profile_value
            or not isinstance(key_value, str)
            or len(key_value) > 128
            or platform_value not in {"android", "ios"}
            or (display_name is not None and not isinstance(display_name, str))
        ):
            raise ValidationError("Mobile initialization request is invalid")
        try:
            vault_key = base64.b64decode(key_value, validate=True)
        except Exception as exc:
            raise ValidationError("Vault key is invalid") from exc
        if len(vault_key) != 32:
            raise ValidationError("Vault key is invalid")
        profile_dir = Path(profile_value).resolve()
        binding = (str(profile_dir), hashlib.sha256(vault_key).digest(), platform_value, connection_policy)

        with _service_lock:
            if _profile_host is not None or _profile_installing or _retiring_catalog is not None:
                raise NativeUnavailable("Native profile host owns initialization")
            if _retiring_service is not None:
                _close_service()
                if _retiring_service is not None:
                    raise NativeUnavailable("Previous mobile runtime is still retiring")
            if _service is not None:
                if _service_binding != binding or _service._shutdown.is_set():
                    raise ValidationError("Mobile runtime binding cannot change while running")
                return _dumps({"ok": True, "result": _service.snapshot()})
            install_embedded_runtime_guards()
            store = VaultStore(
                profile_dir,
                vault_key,
                native_mobile_protection=platform_value,
            )
            service = None
            incarnation = uuid.uuid4().hex
            with _events_lock:
                _event_incarnation = incarnation
            try:
                channel = NativeChannel()
                service = MeshChatService(store, profile_dir,
                                          lambda value: _emit(value, incarnation=incarnation), direct_native=channel,
                                          connection_policy=connection_policy)
                if platform_value == "android":
                    from .direct_bootstrap_mobile import AndroidBootstrapProcess
                    service._direct_bootstrap_factory = AndroidBootstrapProcess
                else:
                    service._direct_bootstrap_factory = None
                if display_name is not None and service.store.get("profile", "local") is None:
                    service.create_profile(display_name)
            except Exception as error:
                with _events_lock:
                    _event_incarnation = None
                    _events.clear()
                failed_service = getattr(error, "retiring_service", service)
                if failed_service is not None:
                    _retiring_service, _retiring_channel = failed_service, channel
                    _close_service()
                else:
                    store.close()
                raise
            _service = service
            _native_channel = channel
            _service_binding = binding
            return _dumps({"ok": True, "result": service.snapshot()})
    except Exception as exc:
        return _error(exc)


def command(raw: str) -> str:
    """Dispatch one renderer-approved command to the embedded service."""

    global _service
    try:
        request = _loads(raw, maximum=MAX_COMMAND_JSON_BYTES)
        command_name = request.get("command")
        if not isinstance(command_name, str):
            raise ValidationError("Mobile command is invalid")
        maximum = COMMAND_PAYLOAD_LIMITS.get(command_name, MAX_RENDERER_PAYLOAD_BYTES)
        payload = request.get("payload", {})
        if (
            len(raw.encode("utf-8")) > maximum + MAX_COMMAND_ENVELOPE_BYTES
            or len(_dumps(payload).encode("utf-8")) > maximum
        ):
            raise ValidationError("Mobile command is too large")
        with _service_lock:
            if _service is None:
                raise ValidationError("Mobile service is not initialized")
            envelope = {
                "v": IPC_VERSION,
                "id": str(uuid.uuid4()),
                "command": command_name,
                "payload": payload,
            }
            response, should_stop = _service.dispatch(envelope)
            if should_stop:
                _close_service()
            return _dumps(response)
    except Exception as exc:
        return _error(exc)


def drain_events() -> str:
    global _event_overflow
    with _events_lock:
        values = list(_events)
        _events.clear()
        if _event_overflow:
            marker = {
                "type": "event",
                "event": "state_changed",
                "resource_kind": "event_overflow",
                "overflow": True,
            }
            values = [marker, *values[1:]] if values else [marker]
            _event_overflow = False
    return _dumps({"ok": True, "result": values})


def direct_exchange(raw: str) -> str:
    """Native-only pump; deliberately independent of a waiting command lock."""
    try:
        request = _loads(raw)
        if (set(request) != {"responses"} or not isinstance(request["responses"], list)
                or len(request["responses"]) > 8):
            raise ValidationError("Direct exchange is invalid")
        channel = _native_channel or _retiring_channel or _opening_channel
        if channel is None:
            return _dumps({"ok": True, "result": []})
        for response in request["responses"]:
            channel.receive(response)
        return _dumps({"ok": True, "result": channel.drain(limit=1)})
    except Exception as exc:
        return _error(exc)


def native_webrtc_event(event: str, session_id: str, data: str = "") -> str:
    """Native WebRTC callback boundary. Never raises into the WebRTC thread."""
    try:
        event = str(event)
        session_id = str(session_id)
        data = str(data)
        # A command can hold _service_lock while waiting for this very JNI
        # callback. Keep a strong snapshot without taking the command lock;
        # the service's queue rejects work once shutdown begins.
        service = _service
        if service is not None:
            service.native_webrtc_event(event, session_id, data)
        return _dumps({"ok": True, "result": None})
    except Exception as exc:
        return _error(exc)


def core_exchange(caller: str, frame_b64: str, scope: str = "consumer") -> str:
    """Binder host entry: caller, grant scope and allowlist are host decisions.

    Frames travel base64-encoded because the Binder service already treats them
    as opaque bytes, and because a string boundary is thinner than a converted
    byte array across Chaquopy.
    """

    from .core_api.android_host import exchange
    from .core_api.wire_codec import encode_frame
    from ._qualification_failure_observer import note

    try:
        if not isinstance(caller, str) or not isinstance(frame_b64, str) \
                or not isinstance(scope, str):
            raise ValidationError("Core API bridge request is invalid")
        if len(frame_b64) > 4 * 1024 * 1024 * 4 // 3 + 4:
            raise ValidationError("Core API frame is too large")
        try:
            frame = base64.b64decode(frame_b64, validate=True)
        except Exception as exc:
            raise ValidationError("Core API frame is not valid base64") from exc
        with _service_lock:
            host, service, installing = _profile_host, _service, _profile_installing
            note("route", service, host, installing, _service_binding, _event_incarnation)
        if installing and host is None:
            reply = encode_frame({"api_version": 1, "request_id": None, "ok": False,
                "error": {"code": "unavailable", "retry_after_ms": None}})
        else:
            reply = host.exchange(caller, frame, scope) if host is not None else exchange(service, caller, frame, scope)
        return base64.b64encode(reply).decode("ascii")
    except Exception:
        note("discard")
        return base64.b64encode(encode_frame({
            "api_version": 1, "request_id": None, "ok": False,
            "error": {"code": "invalid_request", "retry_after_ms": None},
        })).decode("ascii")


def _close_service() -> None:
    global _service, _native_channel, _service_binding, _event_incarnation, _event_overflow
    global _retiring_service, _retiring_channel
    if _service is not None:
        _retiring_service, _service = _service, None
        _retiring_channel, _native_channel = _native_channel, None
        _service_binding = None
    with _events_lock:
        _event_incarnation = None
        _events.clear()
        _event_overflow = False
    service = _retiring_service
    if service is not None:
        qualification = sys.modules.get("mesh_chat.core_api.qualification_host")
        if qualification is not None:
            try:
                qualification._forget_android_publication(service)
            except Exception:
                pass
        from .core_api.android_host import retire
        service._shutdown.set()
        publication_error = None
        try:
            retire(service)
        except Exception as error:
            publication_error = error
        try:
            service.close()
        finally:
            if service._store_closed and publication_error is None:
                _retiring_service = _retiring_channel = None
        if publication_error is not None:
            raise NativeUnavailable("Profile host session retirement is incomplete") from publication_error


def shutdown() -> str:
    global _profile_host
    try:
        with _profile_install_lock:
            host = _profile_host
            if host is not None:
                host.close()
                _profile_host = None
            with _service_lock:
                _close_service()
                if (_service is not None or _native_channel is not None
                        or _retiring_service is not None or _retiring_channel is not None or _opening_channel is not None):
                    raise NativeUnavailable("Mobile runtime retirement is incomplete")
            _close_retiring_catalog()
        return _dumps({"ok": True, "result": None})
    except Exception as exc:
        return _error(exc)
