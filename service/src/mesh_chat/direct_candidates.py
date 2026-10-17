"""Local-route and router evidence for the exact private native-owned socket.

No public observer, discovery socket, renderer endpoint API, or TCP mapping reuse.
An empty candidate set is a valid version-2 reply, never proof of reachability.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
import uuid
from copy import deepcopy

from . import connectivity as c
from .errors import ValidationError


class NativePreparation:
    def __init__(self, native, owned, expires_at, *, clock=time.time, monotonic=time.monotonic):
        self._native = native
        self._owned = dict(owned)
        self._clock, self._monotonic = clock, monotonic
        self.expires_at = expires_at
        self._deadline = monotonic() + max(0, expires_at-clock())
        self._lock = threading.Lock()
        self._closed = False
        self._mappings = []
        self._candidates = []
        self.reason = "no_public_candidate"
        self._timer = threading.Timer(max(0, expires_at-clock()), self.close)
        self._timer.daemon = True
        self._timer.start()

    @property
    def handle(self):
        return self._owned["id"]

    def _check(self):
        if (self._closed or self._clock() >= self.expires_at
                or self._monotonic() >= self._deadline):
            raise ValidationError("Direct native preparation expired")

    def document_fields(self):
        with self._lock:
            self._check()
        current = self._native.request("inspect", id=self.handle)
        expected = {key: self._owned[key] for key in ("id", "host", "port", "certificate")}
        if current != expected:
            self.close()
            raise ValidationError("Direct candidate socket ownership changed")
        with self._lock:
            self._check()
            return {"session_id": self._owned["session"], "generation": self._owned["generation"],
                    "certificate": bytes.fromhex(self._owned["certificate"]),
                    "candidates": deepcopy(self._candidates), "expires_at": self.expires_at}

    def _add_mapping(self, mapping):
        with self._lock:
            if self._closed:
                c.remove_port_mapping(mapping.record())
                raise ValidationError("Direct native preparation expired")
            self._mappings.append(mapping.record())
        if (mapping.protocol != "udp" or mapping.internal_port != self._owned["port"]
                or mapping.internal_host != self._owned["host"]
                or c.classify_address(mapping.external_host) not in {"public_ipv4", "public_ipv6"}
                or type(mapping.lifetime) is not int or mapping.lifetime <= 0
                or type(mapping.external_port) is not int or not 1 <= mapping.external_port <= 65535):
            raise ValidationError("Direct mapping does not match native socket")
        if (str(ipaddress.ip_address(mapping.external_host)) != mapping.external_host
                or ipaddress.ip_address(mapping.external_host).version != ipaddress.ip_address(self._owned["host"]).version):
            raise ValidationError("Direct mapping address family changed")
        expiry = min(self.expires_at, int(self._clock()) + mapping.lifetime)
        self._add_candidate(mapping.external_host, mapping.external_port, expiry)

    def _add_candidate(self, host, port, expiry):
        with self._lock:
            self._check()
            self.expires_at = min(self.expires_at, expiry)
            self._deadline = min(self._deadline, self._monotonic()+max(0, self.expires_at-self._clock()))
            self._timer.cancel()
            self._timer = threading.Timer(max(0, self._deadline-self._monotonic()), self.close)
            self._timer.daemon = True
            self._timer.start()
            candidate = {"host": host, "port": port, "expires_at": self.expires_at}
            self._candidates = [candidate]
            self.reason = "candidates_prepared_unverified"

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            mappings, self._mappings = self._mappings, []
        self._timer.cancel()
        try:
            self._native.request("close", id=self.handle)
        except Exception:
            pass
        for mapping in mappings:
            try:
                c.remove_port_mapping(mapping)
            except Exception:
                pass


def prepare_candidates(native, *, generation, expires_at, family=None, routes=None,
                       clock=time.time, monotonic=time.monotonic):
    if type(expires_at) is not int:
        raise ValidationError("Direct candidate preparation is invalid")
    remaining = expires_at-clock()
    if (type(generation) is not int or not 1 <= generation < 2**63
            or type(expires_at) is not int or not 1 <= remaining <= 300
            or family not in (None, socket.AF_INET, socket.AF_INET6)):
        raise ValidationError("Direct candidate preparation is invalid")
    routes = c.default_routes() if routes is None else list(routes)
    eligible = [route for route in routes if route.local_address
        and (family is None or route.family == family)
        and c.classify_address(route.local_address) in {"public_ipv4", "public_ipv6", "rfc1918", "shared"}]
    eligible.sort(key=lambda route: (c.classify_address(route.local_address) != "public_ipv6", route.metric))
    route = eligible[0] if eligible else None
    local = route.local_address if route else ("::" if family == socket.AF_INET6 else "0.0.0.0")
    address = f"[{local}]:0" if ":" in local else f"{local}:0"
    owned = native.request("prepare", address=address, generation=generation, remaining_ms=int(remaining*1000))
    preparation = None
    try:
        if (not isinstance(owned, dict) or set(owned) != {"id", "session", "generation", "host", "port", "certificate"}
                or type(owned["id"]) is not int or owned["id"] <= 0
                or type(owned["generation"]) is not int or owned["generation"] != generation or owned["host"] != local
                or type(owned["port"]) is not int or not 1 <= owned["port"] <= 65535
                or str(uuid.UUID(owned["session"])) != owned["session"]
                or not isinstance(owned["certificate"], str)
                or not 1 <= len(bytes.fromhex(owned["certificate"])) <= 16384):
            raise ValidationError("Native socket preparation is invalid")
        preparation = NativePreparation(native, owned, expires_at, clock=clock, monotonic=monotonic)
        kind = c.classify_address(local)
        lifetime = max(1, int(expires_at-clock()))
        if kind in {"public_ipv4", "public_ipv6"}:
            preparation._add_candidate(local, owned["port"], expires_at)
            if kind == "public_ipv6":
                try:
                    # IGD discovery may use IPv4 on the SAME interface; the
                    # pinhole still names the native-bound global IPv6 tuple.
                    mapping = c.map_upnp_ipv6_pinhole(local, owned["port"], lifetime=lifetime,
                        routes=[item for item in routes if item.interface == route.interface], protocol="udp")
                    preparation._add_mapping(mapping)
                except OSError:
                    pass  # Global address is a candidate, never a firewall-success claim.
        elif route is not None:
            try:
                mapping = c.create_port_mapping(owned["port"], lifetime=lifetime, routes=[route], protocol="udp")
                preparation._add_mapping(mapping)
            except OSError:
                preparation.reason = "no_public_candidate"
        preparation.document_fields()  # Recheck after potentially slow router operations.
        return preparation
    except Exception:
        if preparation is not None:
            preparation.close()
        elif isinstance(owned, dict) and type(owned.get("id")) is int:
            try:
                native.request("close", id=owned["id"])
            except Exception:
                pass
        raise
