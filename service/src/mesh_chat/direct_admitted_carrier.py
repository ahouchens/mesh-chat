"""Service-owned admitted packet adapter over an already authenticated native path."""
import queue
import threading
import time

import RNS

from .direct_binding import _parse
from .errors import ValidationError
from .direct_packet_adapter import MeshDirectInterface
from .direct_packet_policy import PacketPolicy
from .workspace_protocol import _destination_for, _identity_from_public_key


def retire_interface_links(interface, peer):
    """RNS links bind to an interface; a new QUIC path must establish new links."""
    seen=set()
    for link in list(RNS.Transport.active_links)+list(RNS.Transport.pending_links):
        if id(link) in seen or getattr(link,"attached_interface",None) is not interface:
            continue
        seen.add(id(link))
        try: link.teardown()
        except Exception: pass
    try:
        if RNS.Transport.next_hop_interface(peer) is interface:
            RNS.Transport.expire_path(peer)
    except Exception:
        pass


class AdmittedCarrier:
    def __init__(self, service, prepared, raw, expected, certificate, bootstrap_authority, state_changed, initial_packets=(), runtime_lease=None):
        self.service, self.prepared, self.authority = service, prepared, bootstrap_authority
        self._changed = state_changed
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self._lost = threading.Event()
        self.peer_seen = threading.Event()
        self.expected = expected
        self.binding, self.certificate = raw, certificate
        self.recovery = runtime_lease is not None
        self.peer_seen_at = 0.0
        self.native_seen_at = 0.0
        self._peer = _destination_for(_identity_from_public_key(expected.issuer_public_identity))
        self._incoming, self._outgoing = queue.Queue(maxsize=32), queue.Queue(maxsize=32)
        self._lease = self._interface = self._pump = None
        self._session = object()
        try:
            for packet in initial_packets:
                data = bytes.fromhex(packet)
                self._observe(data)
                self._incoming.put_nowait(data)
            self._lease = runtime_lease or service._track_direct_workspace_session(raw, expected, certificate)
            self._interface = MeshDirectInterface(RNS.Transport, budget=service._direct_packet_budget)
            self._interface.name = "Mesh Direct admitted"
            self._interface.packet_policy = PacketPolicy(service.network.destination_hash,
                _destination_for(_identity_from_public_key(expected.issuer_public_identity)),
                link_lifetime=min(3600,max(1,prepared.expires_at-time.time())) if self.recovery else 300)
            service.network.reticulum._add_interface(self._interface, mode=self._interface.MODE_POINT_TO_POINT)
            self._interface.activate(self._session, expires_at=time.monotonic()+max(0,
                (prepared.expires_at if self.recovery else min(_parse(raw)["expires_at"],prepared.expires_at))-time.time()))
            self._pump = service._open_direct_packet_pump(self._interface, self._session,
                self._incoming, self._outgoing, self._lost, self._stop, self._lease.check)
            self._thread = threading.Thread(target=self._run, name="mesh-direct-admitted", daemon=True)
        except BaseException:
            self.close()
            raise

    def start(self):
        self._thread.start()
        self.service.network.router.announce(self.service.network.destination_hash)
        self.refresh_path()

    def refresh_path(self):
        RNS.Transport.request_path(self._peer,on_interface=self._interface)

    def _observe(self, data):
        packet = RNS.Packet(None,data)
        if (packet.unpack() and packet.packet_type == RNS.Packet.ANNOUNCE
                and packet.destination_hash == self._peer
                and RNS.Identity.validate_announce(packet, only_validate_signature=True)):
            self.peer_seen_at = time.monotonic()
            self.peer_seen.set()

    def _run(self):
        next_announce = time.monotonic()+3
        try:
            while not self._stop.is_set():
                if self.recovery and time.monotonic() >= next_announce:
                    self.service.network.router.announce(self.service.network.destination_hash)
                    next_announce = time.monotonic()+5
                result = self.service._direct_native.request("poll", id=self.prepared.handle)
                if (not isinstance(result,dict) or set(result) not in ({"state","packets"}, {"state","packets","statistics"})
                        or type(result["state"]) is not int or result["state"] not in (0,1,2)
                        or not isinstance(result["packets"],list) or len(result["packets"]) > 32
                        or any(not isinstance(packet,str) or not 2 <= len(packet) <= 1032 for packet in result["packets"])):
                    raise ValidationError("Native admitted packet batch is invalid")
                self.native_seen_at = time.monotonic()
                if result["state"] != 1:
                    break
                for packet in result["packets"]:
                    data = bytes.fromhex(packet)
                    self._observe(data)
                    try:
                        self._incoming.put_nowait(data)
                    except queue.Full:
                        pass  # RNS owns reliability; bound memory on overload.
                outgoing = []
                for _ in range(32):
                    try:
                        outgoing.append(self._outgoing.get_nowait().hex())
                    except queue.Empty:
                        break
                if outgoing:
                    self.service._direct_native.request("send", id=self.prepared.handle, packets=outgoing)
                self._stop.wait(.025)
        except Exception:
            pass
        finally:
            self.close()
            self._changed("refresh_required")

    def close(self):
        with self._close_lock:
            if self._closed: return
            self._closed = True
        self._stop.set()
        self._lost.set()
        if self._pump is not None:
            self._pump.stop()
        if self._lease is not None:
            self._lease.cancel()
        if self._interface is not None:
            retire_interface_links(self._interface,self._peer)
            self._interface.detach()
            try:
                RNS.Transport.interfaces.remove(self._interface)
            except ValueError:
                pass
        self.prepared.close()
