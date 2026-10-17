"""Private native DATAGRAM to isolated RNS bootstrap supervision."""
from __future__ import annotations

import base64
import threading
import time
from types import SimpleNamespace

import LXMF

from .direct_bootstrap import BootstrapEngine
from .direct_bootstrap_process import BootstrapProcess
from .errors import RecipientKeysUnavailable, ValidationError
from .models import DeliveryState
from .network import validate_unknown_source_signature
from .workspace_protocol import _destination_for, _identity_from_public_key
from .workspace_wire import parse_workspace_payload


class BootstrapCarrier:
    def __init__(self, service, prepared, authority, parameters, *, state_changed, control_received=None):
        self.service, self.prepared, self.authority = service, prepared, authority
        self.network = service.network
        self.peer = _destination_for(_identity_from_public_key(authority.peer_identity))
        self.workspace_id = authority.workspace_id
        self._changed, self._control_received = state_changed, control_received
        self._stop = threading.Event()
        self._worker_lock = threading.Lock()
        self._ready = False
        self._worker = self._lease = None
        self._thread = None
        try:
            if getattr(self.network, "_direct_bootstrap", None) is not None:
                raise ValidationError("Another bootstrap connection is active")
            self._lease = service._direct_sessions.open(authority.expires_at-time.time(), authority.check,
                key=("invitation", authority.checked.offer_authority.scope["digest"]))
            factory = getattr(service, "_direct_bootstrap_factory", BootstrapProcess)
            if factory is None:
                raise ValidationError("Bootstrap process is unavailable on this platform")
            self._worker = factory()
            self._request("initialize", private_identity=service._identity.get_private_key().hex(),
                peer_identity=authority.peer_identity.hex(), workspace_id=self.workspace_id,
                expires_at=authority.expires_at)
            service._direct_native.request("activate", id=prepared.handle, **parameters)
            self.network._direct_bootstrap = self
        except BaseException:
            self.close()
            raise

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise ValidationError("Bootstrap carrier already started or retired")
        self._thread = threading.Thread(target=self._run, name="mesh-bootstrap-carrier", daemon=True)
        self._thread.start()

    @property
    def ready(self):
        return self._ready and not self._stop.is_set()

    def _request(self, operation, **payload):
        with self._worker_lock:
            if self._stop.is_set():
                raise ValidationError("Bootstrap carrier is retired")
            return self._worker.request(operation, **payload)

    def handles(self, destination, fields, text=""):
        if destination != self.peer or self._stop.is_set():
            return False
        try:
            wire = parse_workspace_payload(SimpleNamespace(get_fields=lambda:fields, content=text))
            return wire.workspace_id == self.workspace_id and wire.kind in BootstrapEngine.KINDS
        except ValidationError:
            return False

    def send(self, *, logical_id, recipient_public_key, recipient_destination, text, fields, propagated=False):
        if (recipient_public_key != self.authority.peer_identity or propagated
                or not self.handles(recipient_destination, fields, text)):
            raise ValidationError("Bootstrap scope does not authorize this payload")
        if not self.ready:
            raise RecipientKeysUnavailable("Bootstrap recipient keys are unavailable")
        wire = parse_workspace_payload(SimpleNamespace(get_fields=lambda:fields, content=text))
        if wire.logical_id != logical_id:
            raise ValidationError("Bootstrap delivery identifier changed")
        return self._request("send", kind=wire.kind, logical_id=logical_id,
                             document=wire.document, expires_at=wire.expires_at)

    def _receive(self, event):
        if not isinstance(event, dict):
            raise ValidationError("Bootstrap event is invalid")
        if event.get("kind") == "inbound":
            packed = base64.b64decode(event["packed"], validate=True)
            if not 1 <= len(packed) <= BootstrapEngine.MAX_MESSAGE_BYTES:
                raise ValidationError("Bootstrap message is too large")
            message = LXMF.LXMessage.unpack_from_bytes(packed)
            if (message.source_hash != self.peer or message.destination_hash != self.network.destination_hash
                    or not validate_unknown_source_signature(message, self.authority.peer_identity)):
                raise ValidationError("Bootstrap message signature is invalid")
            wire = parse_workspace_payload(message)
            if wire.workspace_id != self.workspace_id or wire.kind not in BootstrapEngine.KINDS:
                raise ValidationError("Bootstrap message scope is invalid")
            message.signature_validated = True
            if wire.kind == "workspace_direct_binding" and self._control_received is not None:
                self.network._defer_callback(self._control_received, wire.document, kind="inbound")
            else:
                self.network._on_inbound(message)
        elif event.get("kind") == "status":
            self.network._defer_callback(self.network._status_callback, event["logical_id"],
                DeliveryState(event["state"]), event["native_id"])
        else:
            raise ValidationError("Bootstrap event is invalid")

    def _run(self):
        activated = False
        next_check = 0
        try:
            while not self._stop.is_set():
                if time.monotonic() >= next_check:
                    if not self._lease.check():
                        return
                    next_check = time.monotonic()+.25
                native = self.service._direct_native.request("poll", id=self.prepared.handle)
                if (not isinstance(native, dict) or set(native) != {"state", "packets"}
                        or type(native["state"]) is not int or native["state"] not in (0,1,2)
                        or not isinstance(native["packets"], list) or len(native["packets"]) > 32):
                    raise ValidationError("Native bootstrap response is invalid")
                if native["state"] == 2:
                    return
                if native["state"] == 1:
                    if not activated:
                        self._request("activate")
                        activated = True
                        self._changed("bootstrap_connected")
                    result = self._request("exchange", packets=native["packets"])
                    if (not isinstance(result, dict) or set(result) != {"packets","events","recipient_ready"}
                            or not isinstance(result["packets"],list) or len(result["packets"]) > 32
                            or not isinstance(result["events"],list) or len(result["events"]) > 1
                            or type(result["recipient_ready"]) is not bool):
                        raise ValidationError("Bootstrap worker response is invalid")
                    self._ready = result["recipient_ready"]
                    if result["packets"]:
                        self.service._direct_native.request("send", id=self.prepared.handle, packets=result["packets"])
                    for event in result["events"]:
                        self._receive(event)
                self._stop.wait(.025)
        except Exception:
            pass
        finally:
            self.close()
            self._changed("refresh_required")

    def close(self):
        self._stop.set()
        self._ready = False
        if getattr(self.network, "_direct_bootstrap", None) is self:
            self.network._direct_bootstrap = None
        if self._lease is not None:
            self._lease.cancel()
        try:
            if self._worker is not None:
                self._worker.close()
        finally:
            self.prepared.close()
