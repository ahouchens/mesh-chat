"""One-peer RNS bootstrap engine for a dedicated private process.

Never instantiate in the main service interpreter. The parent retains authority,
durable state and the native socket; this engine has no network interfaces except
its bounded packet adapter. Its control surface is not a service command.
"""
from __future__ import annotations

import queue
import tempfile
import time
import uuid
from pathlib import Path
import RNS

from .direct_packet_adapter import MeshDirectInterface, ProfileBudget, scoped_message_allowed
from .direct_packet_policy import PacketPolicy
from .errors import ValidationError
from .network import ReticulumNetwork
from .reticulum_config import NetworkSettings
from .workspace_protocol import _destination_for
from .workspace_wire import build_workspace_fields


class BootstrapEngine:
    MAX_MESSAGE_BYTES = 512 * 1024
    MAX_EVENTS = 8
    # Admission root delivery is allowed, but channel or ordinary workspace
    # payloads require a subsequent admitted connection.
    KINDS = frozenset({"workspace_join", "workspace_join_receipt", "workspace_manifest_root"})

    def __init__(self, private_identity, peer_identity, workspace_id, expires_at, *, directory=None):
        if RNS.Reticulum.get_instance() is not None:
            raise ValidationError("Bootstrap requires a dedicated interpreter")
        if (not isinstance(private_identity, bytes) or len(private_identity) != 64
                or not isinstance(peer_identity, bytes) or len(peer_identity) != 64
                or type(expires_at) is not int or not time.time() < expires_at <= time.time()+300):
            raise ValidationError("Bootstrap authorization is invalid")
        try:
            if str(uuid.UUID(workspace_id)) != workspace_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Bootstrap workspace is invalid") from exc
        identity, peer = RNS.Identity(create_keys=False), RNS.Identity(create_keys=False)
        identity.load_private_key(private_identity)
        peer.load_public_key(peer_identity)
        self.peer = _destination_for(peer)
        if self.peer == _destination_for(identity):
            raise ValidationError("Bootstrap peer is local")
        self.workspace_id, self.peer_identity = workspace_id, peer_identity
        self.expires_at = expires_at
        self.deadline = time.monotonic()+max(0, expires_at-time.time())
        self.events = queue.Queue(maxsize=self.MAX_EVENTS)
        self.session = object()
        self.network = self.interface = None
        self.closed = False
        self._temporary = tempfile.TemporaryDirectory(prefix="mesh-bootstrap-", dir=directory)
        try:
            self.network = ReticulumNetwork(Path(self._temporary.name), identity, "",
                NetworkSettings(nearby_discovery=False, lan_fallback=False), self._inbound, self._status)
            self.network.remember_contact(peer_identity, self.peer)
            self.interface = MeshDirectInterface(RNS.Transport, budget=ProfileBudget(max_sessions=1))
            self.interface.name = "Mesh Direct bootstrap"
            self.interface.packet_policy = PacketPolicy(self.network.destination_hash, self.peer)
            self.network.reticulum._add_interface(self.interface, mode=self.interface.MODE_POINT_TO_POINT)
            if not self.interface._isolated():
                raise ValidationError("Bootstrap context is not isolated")
        except BaseException:
            self.close()
            raise

    def _check(self, *, online=False):
        if self.closed or time.monotonic() >= self.deadline or time.time() >= self.expires_at:
            raise ValidationError("Bootstrap engine expired")
        if not self.interface._isolated() or (online and not self.interface.check_health()):
            raise ValidationError("Bootstrap carrier is unavailable")

    def activate(self):
        """Parent invokes only after native mutual authentication and lease check."""
        self._check()
        self.interface.activate(self.session, expires_at=self.deadline, pending=True)
        self.network.router.announce(self.network.destination_hash)

    def _enqueue(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            # Parent can retry durable controls; never evict an earlier admission.
            pass

    def _inbound(self, message):
        if (self.closed or not message.signature_validated
                or not scoped_message_allowed(message, self.peer, self.workspace_id, pending=True)):
            return
        from .workspace_wire import parse_workspace_payload
        if parse_workspace_payload(message).kind not in self.KINDS:
            return
        packed = message.packed
        if isinstance(packed, bytes) and 1 <= len(packed) <= self.MAX_MESSAGE_BYTES:
            self._enqueue({"kind":"inbound", "packed":packed})

    def _status(self, logical_id, state, native_id):
        self._enqueue({"kind":"status", "logical_id":logical_id, "state":state.value, "native_id":native_id})

    def send(self, *, kind, logical_id, document, expires_at):
        self._check(online=True)
        if kind not in self.KINDS:
            raise ValidationError("Bootstrap payload is not permitted")
        fields = build_workspace_fields(kind=kind, logical_id=logical_id, workspace_id=self.workspace_id,
            expires_at=min(expires_at, self.expires_at), document=document)
        return self.network.send_with_fields(logical_id=logical_id, recipient_public_key=self.peer_identity,
            recipient_destination=self.peer, text="", fields=fields)

    def exchange(self, packets):
        self._check(online=True)
        if (not isinstance(packets, list) or len(packets) > 32
                or any(not isinstance(item, bytes) or not 1 <= len(item) <= 516 for item in packets)):
            raise ValidationError("Bootstrap packet batch is invalid")
        for packet in packets:
            self.interface.receive(self.session, packet)
        outgoing = []
        for _ in range(32):
            packet = self.interface.take_outgoing(self.session)
            if packet is None:
                break
            outgoing.append(packet)
        events = []
        # One maximal LXMF object plus a packet batch stays under Android's
        # Binder transaction limit after base64 encoding in the private worker.
        for _ in range(1):
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return {"packets":outgoing, "events":events,
                "recipient_ready":self.network.recipient_ready(self.peer)}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.interface is not None:
                self.interface.detach()
            if self.network is not None:
                self.network.shutdown()
        finally:
            while not self.events.empty():
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self._temporary.cleanup()
