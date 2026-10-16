"""Socket-free phase-1 adapter proof; never registered in shipping settings.

Only a private native/service packet pump holds the opaque session token. The
token guards stale/cross-peer callbacks; it is not a replacement for native TLS
authentication. A caller activates only after durable service authorization and
native authentication. Pending mode requires a dedicated non-routing context.
"""
from collections import deque
import threading
import time

import RNS
from RNS.Interfaces.Interface import Interface

from mesh_chat.errors import ValidationError
from mesh_chat.workspace_wire import parse_workspace_payload


class ProfileBudget:
    """One shared pool per protected profile, including replacement sessions."""
    def __init__(self, *, max_sessions=8, max_bytes=512 * 1024):
        self.max_sessions, self.max_bytes = max_sessions, max_bytes
        self._lock = threading.Lock()
        self._owners = {}
        self.queued_bytes = 0

    def attach(self, owner):
        with self._lock:
            if owner in self._owners or len(self._owners) >= self.max_sessions:
                raise ValueError("Direct profile session budget exhausted")
            self._owners[owner] = 0

    def reserve(self, owner, size):
        with self._lock:
            if owner not in self._owners or self.queued_bytes + size > self.max_bytes:
                return False
            self._owners[owner] += size
            self.queued_bytes += size
            return True

    def release(self, owner, size):
        with self._lock:
            if size < 0 or size > self._owners.get(owner, 0):
                raise ValueError("Invalid direct queue accounting")
            self._owners[owner] -= size
            self.queued_bytes -= size

    def detach(self, owner):
        with self._lock:
            self.queued_bytes -= self._owners.pop(owner, 0)


def scoped_message_allowed(message, peer_destination, workspace_id, *, pending):
    """Post-LXMF scope gate; production signature/admission checks still run."""
    if peer_destination is None or getattr(message, "source_hash", None) != peer_destination:
        return False
    try:
        wire = parse_workspace_payload(message)
    except (ValidationError, AttributeError, TypeError):
        return False
    return wire.workspace_id == workspace_id and (not pending or wire.kind in {
        "workspace_join", "workspace_join_receipt", "workspace_manifest_root",
        "workspace_channel_record", "workspace_channel_manifest",
    })


class MeshDirectInterface(Interface):
    MAX_PACKET = 516
    MAX_ITEMS = 128
    MAX_BYTES = 64 * 1024

    def __init__(self, owner, *, budget, clock=time.monotonic):
        super().__init__()
        self.owner = owner
        self.name = "Mesh Direct proof"
        self.IN = self.OUT = self.receives = True
        self.FWD = self.RPT = False
        self.HW_MTU = 500
        self.mode = Interface.MODE_POINT_TO_POINT
        self._clock = clock
        self._lock = threading.RLock()
        self._packets = deque()
        self._bytes = 0
        self._session = None
        self._deadline = 0
        self._pending = False
        self._budgets = {}
        self.dropped = 0
        self._profile_budget = budget
        self.packet_policy = None

    def activate(self, session, *, expires_at, pending=False):
        with self._lock:
            if self.detached or self._session is not None or session is None:
                raise ValueError("A direct interface has exactly one session")
            now = self._clock()
            if expires_at <= now:
                raise ValueError("Direct session already expired")
            if pending and not self._isolated():
                raise ValueError("Pending direct transport requires isolated RNS")
            self._profile_budget.attach(self)
            self._pending = pending
            self._session = session
            self._deadline = min(expires_at, now + 300) if pending else expires_at
            self._budgets = {direction: [0, 0, 32.0, now] for direction in ("in", "out")}
            self.online = True

    def _isolated(self):
        return not RNS.Reticulum.transport_enabled() and not any(
            interface is not self for interface in RNS.Transport.interfaces
        )

    def check_health(self):
        with self._lock:
            if self.online and (self._clock() >= self._deadline or
                                (self._pending and not self._isolated())):
                self.detach()
            return self.online and not self.detached

    def _allow(self, data, direction):
        if not self.check_health() or not isinstance(data, bytes) or not 1 <= len(data) <= self.MAX_PACKET:
            return False
        if self.packet_policy is not None and not self.packet_policy.allow(data, direction):
            return False
        if self._pending:
            budget = self._budgets[direction]
            now = self._clock()
            budget[2] = min(32.0, budget[2] + max(0, now - budget[3]) * 32)
            budget[3] = now
            if budget[0] >= 4096 or budget[1] + len(data) > 2 * 1024 * 1024 or budget[2] < 1:
                return False
            budget[0] += 1
            budget[1] += len(data)
            budget[2] -= 1
        return True

    def process_outgoing(self, data):
        with self._lock:
            if (not self._allow(data, "out") or len(self._packets) >= self.MAX_ITEMS
                    or self._bytes + len(data) > self.MAX_BYTES):
                self.dropped += 1
                return
            if not self._profile_budget.reserve(self, len(data)):
                self.dropped += 1
                return
            self._packets.append(data)
            self._bytes += len(data)

    def take_outgoing(self, session):
        with self._lock:
            if session is not self._session or not self.check_health() or not self._packets:
                return None
            packet = self._packets.popleft()
            self._bytes -= len(packet)
            self._profile_budget.release(self, len(packet))
            self.txb += len(packet)
            return packet

    def receive(self, session, data):
        with self._lock:
            if session is not self._session or not self._allow(data, "in"):
                self.dropped += 1
                return False
            self.rxb += len(data)
        self.owner.inbound(data, self)
        return True

    def engine_lost(self, session):
        with self._lock:
            if session is self._session:
                self.detach()

    def detach(self):
        with self._lock:
            self.online = False
            self.detached = True
            self._session = None
            self._packets.clear()
            self._bytes = 0
            self._profile_budget.detach(self)

    def __str__(self):
        return "MeshDirectInterface[proof]"
