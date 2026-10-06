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

from .errors import MeshChatError, ValidationError
from .network import install_embedded_runtime_guards
from .service import MeshChatService
from .vault import VaultStore

IPC_VERSION = 1
MAX_JSON_BYTES = 64 * 1024
_service_lock = threading.RLock()
_events_lock = threading.Lock()
_service: MeshChatService | None = None
_events: deque[dict[str, Any]] = deque(maxlen=256)


def _loads(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not 1 <= len(raw.encode("utf-8")) <= MAX_JSON_BYTES:
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
    return _dumps({"ok": False, "error": {"code": code}})


def _emit(value: dict[str, Any]) -> None:
    # Network callbacks can emit from an RNS worker while a renderer command is
    # executing.  Keep event delivery independent from the service lifecycle
    # lock so a command waiting for that worker cannot deadlock the bridge.
    with _events_lock:
        _events.append(value)


def initialize(raw: str) -> str:
    """Start the shared service from a native app-private directory."""

    global _service
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
                service = MeshChatService(store, profile_dir, _emit)
                if display_name is not None and service.store.get("profile", "local") is None:
                    service.create_profile(display_name)
            except Exception:
                store.close()
                raise
            _service = service
            return _dumps({"ok": True, "result": service.snapshot()})
    except Exception as exc:
        return _error(exc)


def command(raw: str) -> str:
    """Dispatch one renderer-approved command to the embedded service."""

    global _service
    try:
        request = _loads(raw)
        with _service_lock:
            if _service is None:
                raise ValidationError("Mobile service is not initialized")
            envelope = {
                "v": IPC_VERSION,
                "id": str(uuid.uuid4()),
                "command": request.get("command"),
                "payload": request.get("payload", {}),
            }
            response, should_stop = _service.dispatch(envelope)
            if should_stop:
                _service.close()
                _service = None
            return _dumps(response)
    except Exception as exc:
        return _error(exc)


def drain_events() -> str:
    with _events_lock:
        values = list(_events)
        _events.clear()
    return _dumps({"ok": True, "result": values})


def shutdown() -> str:
    global _service
    try:
        with _service_lock:
            if _service is not None:
                _service.close()
                _service = None
        with _events_lock:
            _events.clear()
        return _dumps({"ok": True, "result": None})
    except Exception as exc:
        return _error(exc)
