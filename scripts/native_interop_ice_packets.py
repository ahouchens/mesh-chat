"""Bounded passive IPv4/UDP ICE observations, not authenticated ICE results.

RFC 8445 section 7.2.2 defines USERNAME as remote:local ufrags. RFC 8489
defines Binding types, padded attributes and the transaction identifier.
No packets, addresses, ufrags or transaction identifiers leave this module.
"""

import hashlib
import os
import re
import struct

MAX_TRANSACTIONS = 1024
MAX_COUNT = 65535
DIRECTIONS = ("egress", "ingress")
COUNTERS = ("requests", "transactions", "success_responses", "error_responses")
REASONS = frozenset({"uncorrelated", "capture_gap", "malformed", "limit", "ambiguous",
                     "unavailable", "expired", "identity_changed"})
SCOPE = "android_gateway_ipv4_udp_stun"


def correlation(value):
    fields = ("local_ufrag_sha256", "remote_ufrag_sha256")
    if (type(value) is not dict or set(value) != set(fields)
            or any(type(value[k]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[k]) is None for k in fields)
            or value[fields[0]] == value[fields[1]]):
        return None
    return tuple(value[k] for k in fields)


def unavailable(reason="unavailable"):
    return {"availability": "unavailable", "scope": SCOPE,
            "reason": reason if reason in REASONS else "unavailable", "egress": None, "ingress": None}


def validated_snapshot(value):
    if type(value) is not dict or set(value) != {"availability", "scope", "reason", *DIRECTIONS}:
        return None
    if value["scope"] != SCOPE or type(value["availability"]) is not str:
        return None
    if value["availability"] == "unavailable":
        if (type(value["reason"]) is str and value["reason"] in REASONS
                and all(value[d] is None for d in DIRECTIONS)):
            return dict(value)
    elif value["availability"] == "selected" and value["reason"] is None:
        for direction in DIRECTIONS:
            row = value[direction]
            if (type(row) is not dict or set(row) != set(COUNTERS)
                    or any(type(v) is not int or not 0 <= v <= MAX_COUNT for v in row.values())
                    or row["transactions"] > row["requests"]):
                return None
        if not any(value[d]["transactions"] for d in DIRECTIONS):
            return None
        return {**value, **{d: dict(value[d]) for d in DIRECTIONS}}
    return None


def _binding(payload):
    if len(payload) < 8 or payload[4:8] != b"\x21\x12\xa4\x42":
        return None
    if len(payload) < 20 or len(payload) > 2048:
        raise ValueError()
    kind, length = struct.unpack("!HH", payload[:4])
    if length % 4 or length + 20 != len(payload):
        raise ValueError()
    if kind not in (1, 0x101, 0x111):
        return None
    username = None
    position = 20
    while position < len(payload):
        if position + 4 > len(payload): raise ValueError()
        attribute, size = struct.unpack("!HH", payload[position:position + 4])
        start = position + 4
        position = start + size + (-size % 4)
        if position > len(payload): raise ValueError()
        if attribute == 6:
            if username is not None: raise ValueError()
            username = payload[start:start + size]
    pair = None
    if kind == 1 and username is not None:
        parts = username.split(b":")
        if len(parts) != 2 or any(re.fullmatch(rb"[A-Za-z0-9+/]{4,256}", part) is None for part in parts):
            raise ValueError()
        pair = tuple(hashlib.sha256(part).hexdigest() for part in parts)
    return kind, payload[8:20], pair


class IcePackets:
    """Retain bounded request metadata only; any capture gap invalidates absence claims."""

    def __init__(self):
        self._salt = os.urandom(32)
        self._requests = {}
        self._counts = {}
        self._reason = None

    def invalidate(self, reason):
        if self._reason is None:
            self._reason = reason if reason in REASONS else "unavailable"
        self._requests.clear()
        self._counts.clear()

    def _increment(self, pair, direction, name):
        if pair not in self._counts:
            if len(self._counts) >= 32: raise OverflowError()
            self._counts[pair] = {d: dict.fromkeys(COUNTERS, 0) for d in DIRECTIONS}
        row = self._counts[pair][direction]
        if row[name] >= MAX_COUNT: raise OverflowError()
        row[name] += 1

    def observe(self, packet, direction):
        if self._reason is not None: return
        try:
            self._observe(packet, direction)
        except OverflowError:
            self.invalidate("limit")
        except Exception:
            self.invalidate("malformed")

    def _observe(self, packet, direction):
        if direction not in DIRECTIONS or len(packet) < 20 or packet[0] >> 4 != 4:
            raise ValueError()
        if packet[9] != 17: return
        header = (packet[0] & 15) * 4
        total, fragment = struct.unpack("!HH", packet[2:4] + packet[6:8])
        if fragment & 0x3fff or header < 20 or total > len(packet) or header + 8 > total:
            raise ValueError()
        udp = packet[header:total]
        length = struct.unpack("!H", udp[4:6])[0]
        if length != len(udp) or length < 8: raise ValueError()
        binding = _binding(udp[8:])
        if binding is None: return
        kind, transaction, username_pair = binding
        source, destination = packet[12:16] + udp[:2], packet[16:20] + udp[2:4]
        if kind == 1:
            if username_pair is None: return  # STUN discovery is not an ICE generation.
            pair = username_pair[::-1] if direction == "egress" else username_pair
            flow = hashlib.sha256(self._salt + source + destination).digest()
            key = direction, flow, transaction
            previous = self._requests.get(key)
            if previous is not None and previous != pair:
                self.invalidate("ambiguous")
                return
            self._increment(pair, direction, "requests")
            if previous is None:
                if len(self._requests) >= MAX_TRANSACTIONS: raise OverflowError()
                self._requests[key] = pair
                self._increment(pair, direction, "transactions")
        else:
            flow = hashlib.sha256(self._salt + destination + source).digest()
            other = "ingress" if direction == "egress" else "egress"
            pair = self._requests.get((other, flow, transaction))
            if pair is not None:
                self._increment(pair, direction, "success_responses" if kind == 0x101 else "error_responses")

    def snapshot(self, target):
        pair = correlation(target)
        if self._reason is not None: return unavailable(self._reason)
        if pair is None: return unavailable()
        if pair not in self._counts: return unavailable("uncorrelated")
        return {"availability": "selected", "scope": SCOPE, "reason": None,
                **{direction: dict(self._counts[pair][direction]) for direction in DIRECTIONS}}
