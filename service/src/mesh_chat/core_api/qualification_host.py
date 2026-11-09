"""Private, fresh-profile packaged qualification control, outside public Core.

Only the trusted sidecar launch flag constructs this port. Possessing an owner
Core grant never creates it. Endpoint tuples may reach the inherited controller
for transient fault correlation; controllers must redact them from artifacts.
"""
import base64
import hashlib
import hmac
import json
import os
import weakref
from pathlib import Path

from ..errors import ValidationError

COMMANDS = frozenset({"qualification.inventory", "qualification.path_evidence"})
MARKER = ".mesh-qualification-v1"
_android_service = None


def _marker_tag(path, key, nonce):
    body = json.dumps(["mesh-qualification-v1", os.path.normcase(str(path)), nonce], separators=(",", ":")).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _check_marker(path, key):
    marker = path / MARKER
    if marker.is_symlink() or marker.resolve().parent != path or marker.stat().st_size > 1024:
        raise ValueError()
    value = json.loads(marker.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"v", "nonce", "tag"}
            or type(value["v"]) is not int or value["v"] != 1
            or not isinstance(value["nonce"], str) or len(value["nonce"]) != 32
            or not isinstance(value["tag"], str)
            or not hmac.compare_digest(value["tag"], _marker_tag(path, key, value["nonce"]))):
        raise ValueError()


def reserve_fresh_profile(request):
    """Atomically reserve a new synthetic leaf; never open an existing vault."""
    payload = request.get("payload") if isinstance(request, dict) else None
    if (not isinstance(request, dict) or request.get("v") != 1 or request.get("command") != "initialize"
            or not isinstance(payload, dict)
            or set(payload) != {"profile_dir", "vault_key", "display_name", "parent_pid"}
            or payload["display_name"] != "Mesh qualification"
            or not isinstance(payload["profile_dir"], str)):
        raise ValidationError("Qualification initialization is invalid")
    path = Path(payload["profile_dir"])
    if (not path.is_absolute() or path != path.resolve()
            or not path.name.startswith("mesh-qualification-") or len(path.name) > 128):
        raise ValidationError("Qualification profile directory is invalid")
    try:
        key = base64.b64decode(payload["vault_key"], validate=True)
        if len(key) != 32:
            raise ValueError()
        if type(payload["parent_pid"]) is not int or payload["parent_pid"] < 1:
            raise ValueError()
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise ValueError()
            _check_marker(path, key)
        else:
            path.mkdir()  # Atomically reserves first boot. Never marks an old vault.
    except Exception as error:
        raise ValidationError("A fresh qualification profile is required") from error
    return path


def mark_initialized_profile(request):
    """After VaultStore applies platform protection, persist reopen admission."""
    payload = request["payload"]
    path = Path(payload["profile_dir"]).resolve()
    key = base64.b64decode(payload["vault_key"], validate=True)
    marker = path / MARKER
    if marker.exists():
        _check_marker(path, key)
        return
    nonce = os.urandom(16).hex()
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"v": 1, "nonce": nonce, "tag": _marker_tag(path, key, nonce)}, stream)
        stream.flush()
        os.fsync(stream.fileno())


class QualificationControl:
    def __init__(self, current_service):
        self._current_service = current_service

    def dispatch(self, command, payload):
        if command not in COMMANDS or not isinstance(payload, dict):
            raise ValidationError("Qualification request is invalid")
        service = self._current_service()
        if service is None or service._shutdown.is_set():
            raise ValidationError("Qualification service is unavailable")
        if command == "qualification.inventory":
            if payload:
                raise ValidationError("Qualification request is invalid")
            return service.native_webrtc_inspection_resources()
        if set(payload) != {"logical_session", "expected_physical"} or any(
            not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(character) < 0x20 for character in value)
            for value in payload.values()
        ):
            raise ValidationError("Qualification request is invalid")
        return service.native_webrtc_path_evidence(payload["logical_session"], payload["expected_physical"])


def _android_own_uid():
    """Direct host invocation only; no Binder caller may borrow owner authority."""
    try:
        from java import jclass
        if jclass("android.os.Binder").getCallingUid() != jclass("android.os.Process").myUid():
            raise ValueError()
    except Exception as error:
        raise ValidationError("Qualification requires the Android host UID") from error


def _android_result(action):
    try:
        _android_own_uid()
        return json.dumps({"ok": True, "result": action()}, separators=(",", ":"), allow_nan=False)
    except Exception as error:
        return json.dumps({"ok": False, "error": {"code": getattr(error, "code", "unavailable")}})


def android_initialize(raw):
    """Own-UID Chaquopy entry, after NativeWebRtcBridge.attach(context).

    Never called by mobile command(), Core exchange, or a renderer allowlist.
    Only an existing qualification marker allows a cold-start reopen.
    """
    def initialize():
        global _android_service
        from .. import mobile_bridge
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
            raise ValidationError("Qualification initialization is invalid")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"profile_dir", "vault_key", "display_name", "platform"} or payload["platform"] != "android":
            raise ValidationError("Qualification initialization is invalid")
        initial = {"v": 1, "command": "initialize", "payload": {
            key: value for key, value in payload.items() if key != "platform"}}
        initial["payload"]["parent_pid"] = os.getpid()
        with mobile_bridge._service_lock:
            if mobile_bridge._service is not None:
                raise ValidationError("Qualification requires a detached mobile runtime")
            reserve_fresh_profile(initial)
            response = json.loads(mobile_bridge.initialize_native(raw))
            if not response.get("ok"):
                raise ValidationError("Qualification mobile initialization failed")
            mark_initialized_profile(initial)
            _android_service = weakref.ref(mobile_bridge._service)
            return response["result"]
    return _android_result(initialize)


def android_control(raw):
    """Own-UID direct private inventory/path control against the exact instance."""
    def control():
        from .. import mobile_bridge
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
            raise ValidationError("Qualification request is invalid")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"command", "payload"}:
            raise ValidationError("Qualification request is invalid")
        with mobile_bridge._service_lock:
            service = _android_service() if _android_service is not None else None
            if service is None or service is not mobile_bridge._service:
                raise ValidationError("Qualification service is unavailable")
            return QualificationControl(lambda: service).dispatch(value["command"], value["payload"])
    return _android_result(control)
