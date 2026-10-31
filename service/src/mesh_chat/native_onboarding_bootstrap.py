"""Temporary, exact-peer contact control over isolated RNS, never a chat bridge."""
import base64
from collections import deque
import threading
import time

import LXMF

from .app_protocol import parse_payload
from .contact_bootstrap import ContactBootstrapScope
from .direct_bootstrap_process import BootstrapProcess
from .errors import ContactNotApproved, NativeUnavailable, ValidationError
from .models import DeliveryState
from .network import validate_unknown_source_signature
from .invitations import _b64decode


class PendingContactCarrier:
    def __init__(self, service, session, public_identity, expires_at):
        self.service, self.session = service, session
        self.physical = service._native_resources.require(session)
        self.peer = bytes.fromhex(service._native_webrtc_peers[session])
        self.public_identity = public_identity
        self.expires_at = min(expires_at, int(time.time()) + 300)
        self.deadline = time.monotonic() + max(0, self.expires_at - time.time())
        self.scope = ContactBootstrapScope()
        self._stop, self._open = threading.Event(), threading.Event()
        self._packets, self._sent = deque(), {}
        self._worker_lock = threading.Lock()
        self._worker = None
        self._thread = None
        self.ready = self.transfer_ready = False

    def current(self):
        service = self.service
        if (self._stop.is_set() or service._shutdown.is_set() or service._identity is None
                or not service._native_work_allowed()
                or time.monotonic() >= self.deadline or time.time() >= self.expires_at):
            return False
        lifecycle = getattr(service, "_workspace_lifecycle_state", lambda: {})()
        if (lifecycle.get("state") in {"background", "background_available", "suspended"}
                and not service._background_availability_enabled()):
            return False
        contact = service._contact_by_destination(self.peer.hex())
        return (getattr(service, "_pending_contact_carriers", {}).get(self.session) is self
            and self.session in service._native_webrtc_live
            and service._native_resources.current(self.session, self.physical)
            and service._native_webrtc_peers.get(self.session) == self.peer.hex()
            and (not contact or contact["trust"] not in {"blocked", "identity_changed"}))

    def start(self):
        service = self.service
        self._require_current()
        factory = getattr(service, "_direct_bootstrap_factory",
            lambda: BootstrapProcess(directory=service.store.profile_dir))
        if factory is None:
            raise NativeUnavailable("Isolated contact bootstrap is unavailable")
        self._worker = factory()
        self._require_current()
        self._request("initialize_contact", private_identity=service._identity.get_private_key().hex(),
            peer_identity=self.public_identity.hex(), expires_at=self.expires_at)
        self._thread = threading.Thread(target=self._run, name="mesh-contact-bootstrap", daemon=True)
        self._thread.start()

    def opened(self):
        self._open.set()

    def _request(self, operation, **payload):
        with self._worker_lock:
            self._require_current()
            return self._worker.request(operation, **payload)

    def _require_current(self):
        if not self.current():
            raise NativeUnavailable("Contact bootstrap scope is no longer current")

    def receive(self, encoded):
        if not self.current(): return
        packet = base64.b64decode(encoded, validate=True)
        if not 1 <= len(packet) <= 516 or len(self._packets) >= 128:
            raise ValidationError("Contact bootstrap packet budget exhausted")
        self._packets.append(packet.hex())

    def send(self, contact, message):
        if not self.current() or contact["destination_hash"] != self.peer.hex():
            return False
        if message["kind"] not in self.scope.KINDS:
            return False
        if not self.ready:
            return True  # The existing durable outbox owns retry scheduling.
        if message["id"] in self._sent:
            return True
        if len(self._sent) >= 16:
            raise NativeUnavailable("Contact bootstrap control budget exhausted")
        self._sent[message["id"]] = message["kind"]
        try:
            native_id = self._request("send", kind=message["kind"], logical_id=message["id"],
                document=message.get("invitation") or "", expires_at=int(message["expires_at"]))
            if not self.current():
                self._sent.pop(message["id"], None)
                return False
            self.service._on_native_status_locked(message["id"], DeliveryState.SENDING, native_id)
            return True
        except Exception:
            self._sent.pop(message["id"], None)
            raise

    def _event(self, event):
        if not self.current():
            return
        service = self.service
        if event.get("kind") == "inbound":
            packed = base64.b64decode(event["packed"], validate=True)
            if not 1 <= len(packed) <= 32 * 1024:
                raise ValidationError("Contact bootstrap message budget exhausted")
            message = LXMF.LXMessage.unpack_from_bytes(packed)
            if not validate_unknown_source_signature(message, self.public_identity):
                raise ValidationError("Contact bootstrap signature is invalid")
            message.signature_validated = True
            if not self.scope.accepts(message, service.network.destination_hash, self.peer):
                raise ValidationError("Contact bootstrap message is out of scope")
            payload = parse_payload(message)
            service._on_inbound_locked(message)
            if payload.kind.value == "contact_accept":
                contact = service._contact_by_destination(self.peer.hex())
                self.transfer_ready = bool(contact and contact["trust"] in {"approved", "verified"})
        elif event.get("kind") == "status":
            kind = self._sent.get(event.get("logical_id"))
            if kind is None:
                raise ValidationError("Contact bootstrap status is uncorrelated")
            state = DeliveryState(event["state"])
            if state not in {DeliveryState.SENDING, DeliveryState.RECEIVED_BY_ENDPOINT, DeliveryState.QUEUED}:
                raise ValidationError("Contact bootstrap status overstates transport evidence")
            service._on_native_status_locked(event["logical_id"], state, event["native_id"])
            if state in {DeliveryState.QUEUED, DeliveryState.FAILED}:
                self._sent.pop(event["logical_id"], None)
            if kind == "contact_accept" and state == DeliveryState.RECEIVED_BY_ENDPOINT:
                self.transfer_ready = True
        else:
            raise ValidationError("Contact bootstrap event is invalid")

    def _exchange(self):
        with self.service._dispatch_lock:
            if not self.current(): return False
            packets = [self._packets.popleft() for _ in range(min(32, len(self._packets)))]
        result = self._request("exchange", packets=packets)
        if (not isinstance(result, dict) or set(result) != {"packets", "events", "recipient_ready"}
                or not isinstance(result["packets"], list) or len(result["packets"]) > 32
                or not isinstance(result["events"], list) or len(result["events"]) > 1
                or type(result["recipient_ready"]) is not bool):
            raise ValidationError("Contact bootstrap exchange is invalid")
        with self.service._dispatch_lock:
            if not self.current(): return False
            self.ready = result["recipient_ready"]
            for encoded in result["packets"]:
                if not self.current(): return False
                if not isinstance(encoded, str) or not 2 <= len(encoded) <= 1032:
                    raise ValidationError("Contact bootstrap packet is invalid")
                self.service._native_webrtc_host().send(self.physical, bytes.fromhex(encoded))
            for event in result["events"]: self._event(event)
        return self.current()

    def _run(self):
        try:
            while not self._open.wait(.05):
                with self.service._dispatch_lock:
                    if not self.current(): return
            with self.service._dispatch_lock:
                if not self.current(): return
            self._request("activate")
            while not self._stop.is_set() and self._exchange(): self._stop.wait(.025)
        except Exception:
            pass
        finally:
            with self.service._dispatch_lock:
                owned = getattr(self.service, "_pending_contact_carriers", {}).get(self.session) is self
                self.close()
                if owned:
                    self.service._pending_contact_carriers.pop(self.session, None)
                    self.service.native_webrtc_close(self.session, expected_physical=self.physical)

    def close(self):
        self._stop.set()
        self._open.set()
        self.ready = False
        self._packets.clear()
        if self._worker is not None: self._worker.close()

    def wait(self, timeout=None):
        if self._thread is None: return True
        if self._thread is threading.current_thread(): return False
        self._thread.join(timeout)
        return not self._thread.is_alive()


def begin(service, session, verified):
    if getattr(service, "_connection_policy", "legacy") != "shared-native" or service.network is None:
        return
    service._require_native_work()
    contact = service._contact_by_destination(verified.signer_destination)
    if contact and contact["trust"] in {"blocked", "identity_changed"}:
        raise ContactNotApproved("Contact cannot establish an onboarding scope")
    if contact and contact["trust"] in {"approved", "verified"}:
        return
    import json
    public = _b64decode(json.loads(verified.serialized)["signer_public_key"])
    pending = getattr(service, "_pending_contact_carriers", None)
    if pending is None:
        pending = service._pending_contact_carriers = {}
    if session in pending: return
    if pending or getattr(service.network, "_direct_bootstrap", None) is not None:
        raise NativeUnavailable("Another isolated onboarding scope is active")
    carrier = PendingContactCarrier(service, session, public, verified.expires_at)
    pending[session] = carrier
    try:
        carrier.start()
        if service._native_webrtc_descriptions[session].get("packet_open"):
            carrier.opened()
    except Exception:
        pending.pop(session, None)
        carrier.close()
        raise


def retire(service, session):
    with service._dispatch_lock:
        carrier = getattr(service, "_pending_contact_carriers", {}).pop(session, None)
        if carrier is not None: carrier.close()
