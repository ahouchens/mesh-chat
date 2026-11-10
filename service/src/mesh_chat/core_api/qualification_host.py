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
from uuid import UUID

from ..errors import ContactNotApproved, ValidationError
from ..connection.diagnostics import validated_pairing_retirement
from ..native_path_evidence import validate_sample_request

PAIRING_COMMANDS = frozenset({"qualification.pairing_begin", "qualification.pairing_status", "qualification.pairing_cancel"})
COMMANDS = frozenset({"qualification.inventory", "qualification.path_evidence",
                      "qualification.retire_carrier"}) | PAIRING_COMMANDS
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
    commands = COMMANDS

    def __init__(self, current_service, *, authorize=lambda: True, caller="inherited-controller"):
        if (not callable(current_service) or not callable(authorize) or not isinstance(caller, str)
                or not 1 <= len(caller) <= 200 or any(not 0x20 <= ord(char) <= 0x7E for char in caller)):
            raise ValueError("Trusted qualification caller is invalid")
        self._current_service = current_service
        self._authorize, self._caller = authorize, caller

    def dispatch(self, command, payload):
        if command not in COMMANDS or not isinstance(payload, dict):
            raise ValidationError("Qualification request is invalid")
        service = self._current_service()
        if service is None or service._shutdown.is_set():
            raise ValidationError("Qualification service is unavailable")
        if command in PAIRING_COMMANDS:
            return self._pairing(service, command, payload)
        if command == "qualification.retire_carrier":
            return self._retire_carrier(service, payload)
        if command == "qualification.inventory":
            if not payload:
                return service.native_webrtc_inspection_resources()
            operation = self._retirement_operation(service, payload, {"operation_id", "request_id"})
            with service._dispatch_lock:
                retirement = service.native_pairing_retirement_observation(operation, payload["request_id"])
                result = service.native_webrtc_inspection_resources()
                result["carrier_retirement"] = retirement
                self._retirement_service(service, operation)
                return result
        if set(payload) != {"logical_session", "expected_physical", "sample_request"} or any(
            not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(character) < 0x20 for character in value)
            for value in payload.values()
        ):
            raise ValidationError("Qualification request is invalid")
        validate_sample_request(payload["sample_request"])
        return service.native_webrtc_path_evidence(payload["logical_session"], payload["expected_physical"],
                                                 payload["sample_request"])

    def _operation_id(self, service, operation_id):
        try:
            if type(operation_id) is not str or str(UUID(operation_id)) != operation_id:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError("Qualification pairing operation is invalid") from None
        digest = service.store.opaque_id("qualification-pairing-operation", self._caller, operation_id)
        return str(UUID(bytes=bytes.fromhex(digest)[:16]))

    def _retirement_operation(self, service, payload, fields):
        if set(payload) != fields:
            raise ValidationError("Qualification retirement request is invalid")
        validate_sample_request(payload["request_id"])
        operation = self._operation_id(service, payload["operation_id"])
        self._retirement_service(service, operation)
        return operation

    def _retirement_service(self, service, operation):
        try:
            if self._pairing_service() is not service:
                raise ContactNotApproved("Qualification service changed")
        except ContactNotApproved:
            service.native_pairing_invalidate_retirement(operation)
            raise

    def _retire_carrier(self, service, payload):
        operation = self._retirement_operation(service, payload, {
            "action", "operation_id", "request_id", "logical_session", "expected_physical",
            "expected_service_incarnation", "expected_adapter_epoch"})
        if type(payload["action"]) is not str or payload["action"] not in {"prepare", "commit"}:
            raise ValidationError("Qualification retirement action is invalid")
        for name in ("expected_service_incarnation", "expected_adapter_epoch"):
            validate_sample_request(payload[name])
        if any(type(payload[name]) is not str or not 1 <= len(payload[name]) <= 128
               or any(not (character.isascii() and (character.isalnum() or character in "_-"))
                      for character in payload[name])
               for name in ("logical_session", "expected_physical")):
            raise ValidationError("Qualification retirement resource is invalid")
        with service._dispatch_lock:
            self._retirement_service(service, operation)
            return service.native_pairing_retire_carrier(operation, **{
                name: value for name, value in payload.items() if name != "operation_id"})

    def _pairing_service(self):
        service = self._current_service()
        if (service is None or service._shutdown.is_set() or service._identity is None
                or getattr(service, "_connection_policy", None) != "shared-native"):
            raise ContactNotApproved("Qualification pairing service is unavailable")
        try:
            if self._authorize() is not True:
                raise ValueError
            path = service.store.profile_dir.resolve()
            if not path.name.startswith("mesh-qualification-"):
                raise ValueError
            _check_marker(path, service.store._key)
        except Exception:
            raise ContactNotApproved("Qualification pairing authority is unavailable") from None
        return service

    def _pairing(self, service, command, payload):
        required = {"operation_id", "role"} if command == "qualification.pairing_begin" else {"operation_id"}
        allowed = required | {"pairing_code", "allow_direct_ip_disclosure"} if command.endswith("_begin") else required
        if (not required <= set(payload) or set(payload) - allowed
                or not isinstance(payload["operation_id"], str)):
            raise ValidationError("Qualification pairing request is invalid")
        try:
            if str(UUID(payload["operation_id"])) != payload["operation_id"]:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError("Qualification pairing operation is invalid") from None
        if command.endswith("_begin"):
            role, code = payload["role"], payload.get("pairing_code")
            if (not isinstance(role, str) or role not in {"offer", "answer"}
                    or type(payload.get("allow_direct_ip_disclosure", False)) is not bool
                    or (role == "offer" and "pairing_code" in payload)
                    or (role == "answer" and (not isinstance(code, str) or not 1 <= len(code.encode("utf-8")) <= 2048))):
                raise ValidationError("Qualification pairing request is invalid")
        if self._pairing_service() is not service:
            raise ContactNotApproved("Qualification service changed")
        # Profile-key/caller derivation is stable across a cold reopen. Domain
        # global receipts remain the only canonical mutation journal.
        digest = service.store.opaque_id("qualification-pairing-operation", self._caller, payload["operation_id"])
        operation_id = str(UUID(bytes=bytes.fromhex(digest)[:16]))
        if command == "qualification.pairing_begin":
            bound_service, epoch = weakref.ref(service), service._runtime_incarnation
            def authorized():
                try:
                    current = self._pairing_service()
                    return current is bound_service() and current._runtime_incarnation == epoch
                except Exception:
                    return False
            with service._dispatch_lock:
                if self._pairing_service() is not service:
                    raise ContactNotApproved("Qualification service changed")
                if service.native_pairing_retirement_pending():
                    raise ContactNotApproved("Qualification carrier retirement is pending")
                result = service.native_pairing_begin(operation_id, role=payload["role"], authorized=authorized,
                    pairing_code=payload.get("pairing_code"),
                    allow_direct_ip_disclosure=payload.get("allow_direct_ip_disclosure", False))
        elif command == "qualification.pairing_status":
            result = service.native_pairing_qualification_status(operation_id)
        else:
            result = service.native_pairing_cancel(operation_id)
        projected = {"operation_id": payload["operation_id"], **{key: result[key] for key in
                     ("state", "expires_at", "pairing_code") if key in result}}
        if command == "qualification.pairing_status" and result.get("state") in {"retiring", "retired"}:
            retirement = validated_pairing_retirement(result.get("retirement"))
            if retirement is not None:
                projected["retirement"] = retirement
        return projected


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
            def current_service():
                current = _android_service() if _android_service is not None else None
                return current if current is mobile_bridge._service else None
            def authorized():
                _android_own_uid()
                return True
            return QualificationControl(current_service, authorize=authorized,
                caller="android-own-uid").dispatch(value["command"], value["payload"])
    return _android_result(control)
