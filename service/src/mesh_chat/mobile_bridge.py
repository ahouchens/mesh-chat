"""In-process bridge used by the Android and iOS Tauri plugins.

Desktop builds deliberately keep using the framed sidecar protocol.  Mobile
platforms cannot spawn that executable safely, so their native plugin embeds
CPython and calls this small JSON boundary on a dedicated worker thread.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .errors import MeshChatError, ValidationError, WORKSPACE_ALREADY_KNOWN_REASONS, WorkspaceAlreadyKnown
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
_events: deque[dict[str, Any]] = deque(maxlen=256)
_event_overflow = False


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


def _emit(value: dict[str, Any]) -> None:
    # Network callbacks can emit from an RNS worker while a renderer command is
    # executing.  Keep event delivery independent from the service lifecycle
    # lock so a command waiting for that worker cannot deadlock the bridge.
    global _event_overflow
    overflow = False
    with _events_lock:
        overflow = len(_events) == _events.maxlen
        _events.append(value)
        if overflow:
            _event_overflow = True
    if overflow:
        # Persist the gap after releasing the event lock. A renderer refresh
        # can then request bounded authoritative reconciliation instead of
        # treating a coalesced/dequeued event stream as complete.
        service = _service
        if service is not None:
            service._mark_workspace_invalidation_overflow()


def initialize(raw: str) -> str:
    """Start the shared service from a native app-private directory."""

    global _service, _native_channel
    try:
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

        with _service_lock:
            if _service is not None:
                return _dumps({"ok": True, "result": _service.snapshot()})
            install_embedded_runtime_guards()
            profile_dir = Path(profile_value).resolve()
            store = VaultStore(
                profile_dir,
                vault_key,
                native_mobile_protection=platform_value,
            )
            try:
                channel = NativeChannel()
                service = MeshChatService(store, profile_dir, _emit, direct_native=channel)
                if platform_value == "android":
                    from .direct_bootstrap_mobile import AndroidBootstrapProcess
                    service._direct_bootstrap_factory = AndroidBootstrapProcess
                else:
                    service._direct_bootstrap_factory = None
                if display_name is not None and service.store.get("profile", "local") is None:
                    service.create_profile(display_name)
            except Exception:
                store.close()
                raise
            _service = service
            _native_channel = channel
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
                _service.close()
                _service = None
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
        channel = _native_channel
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


def shutdown() -> str:
    global _service, _event_overflow, _native_channel
    try:
        with _service_lock:
            if _service is not None:
                _service.close()
                _service = None
            _native_channel = None
        with _events_lock:
            _events.clear()
            _event_overflow = False
        return _dumps({"ok": True, "result": None})
    except Exception as exc:
        return _error(exc)
