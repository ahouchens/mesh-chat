"""Pinned-RNS packet routing bounds for the private direct service adapter.

This filter does not authenticate RNS packets: RNS still validates signatures,
Link proofs and encryption. It limits the destinations allowed to reach RNS.
IFAC and routed headers are deliberately unsupported in this socket-free proof.
"""
from collections import OrderedDict
import time

import RNS


class PacketPolicy:
    def __init__(self, local, peer, *, clock=time.monotonic, link_lifetime=300):
        if len(local) != 16 or len(peer) != 16 or local == peer:
            raise ValueError("Expected two distinct RNS destinations")
        if isinstance(link_lifetime,bool) or not isinstance(link_lifetime,(int,float)) or not 0 < link_lifetime <= 3600:
            raise ValueError("Invalid authorized link lifetime")
        self.link_lifetime = link_lifetime
        self.local, self.peer, self.clock = local, peer, clock
        self.links = OrderedDict()
        self.receipts = OrderedDict()
        self.path_request = RNS.Destination.hash(None, "rnstransport", "path", "request")

    def _prune(self, entries):
        now = self.clock()
        for key, expiry in list(entries.items()):
            if now >= expiry:
                del entries[key]

    def allow(self, raw, direction):
        if direction not in {"in", "out"} or not isinstance(raw, bytes) or not 20 <= len(raw) <= 500:
            return False
        # IFAC is decoded inside RNS, after this boundary. Reject it rather than
        # interpreting masked header fields as authorized destinations.
        if raw[0] & 0x80:
            return False
        packet = RNS.Packet(None, raw)
        if (not packet.unpack() or packet.header_type != RNS.Packet.HEADER_1
                or packet.transport_type != RNS.Transport.BROADCAST or packet.hops != 0):
            return False
        self._prune(self.links)
        self._prune(self.receipts)
        target = self.local if direction == "in" else self.peer
        source = self.peer if direction == "in" else self.local
        if packet.destination_type == RNS.Destination.PLAIN:
            return (packet.packet_type == RNS.Packet.DATA
                    and packet.destination_hash == self.path_request
                    and packet.context == RNS.Packet.NONE
                    and packet.data[:16] == target and len(packet.data) > 16)
        if packet.packet_type == RNS.Packet.ANNOUNCE:
            return packet.destination_type == RNS.Destination.SINGLE and packet.destination_hash == source
        if packet.packet_type == RNS.Packet.LINKREQUEST:
            if packet.destination_type != RNS.Destination.SINGLE or packet.destination_hash != target:
                return False
            if len(packet.data) not in {RNS.Link.ECPUBSIZE, RNS.Link.ECPUBSIZE + RNS.Link.LINK_MTU_SIZE}:
                return False
            link_id = RNS.Link.link_id_from_lr_packet(packet)
            if link_id not in self.links and len(self.links) >= 32:
                return False
            # Replaying the same request must not extend authorization.
            self.links.setdefault(link_id, self.clock() + self.link_lifetime)
            return True
        if packet.destination_hash in self.links:
            return (packet.destination_type == RNS.Destination.LINK
                    and packet.packet_type in {RNS.Packet.DATA, RNS.Packet.PROOF})
        if packet.packet_type == RNS.Packet.PROOF:
            return (direction, packet.destination_hash) in self.receipts
        if packet.packet_type != RNS.Packet.DATA or packet.destination_type != RNS.Destination.SINGLE or packet.destination_hash != target:
            return False
        receipt = ("out" if direction == "in" else "in", packet.getTruncatedHash())
        if receipt not in self.receipts and len(self.receipts) >= 256:
            return False
        self.receipts.setdefault(receipt, self.clock() + 120)
        return True
