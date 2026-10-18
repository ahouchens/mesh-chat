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
        self._sockets = [{key:owned[key] for key in ("id", "host", "port", "certificate")}]
        self._sources = {}
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

    def diagnostic_counts(self):
        """Coarse provenance only; never export sockets, addresses or keys."""
        with self._lock:
            counts = {key:0 for key in ("ipv4", "ipv6", "local_global", "pcp", "upnp", "upnp_ipv6", "nat_pmp")}
            for candidate in self._candidates:
                counts["ipv6" if ":" in candidate["host"] else "ipv4"] += 1
                source = self._sources.get((candidate["host"], candidate["port"]))
                if source in counts:
                    counts[source] += 1
            return counts

    @property
    def family(self):
        if len({":" in item["host"] for item in self._sockets}) > 1:
            return None
        return socket.AF_INET6 if ":" in self._owned["host"] else socket.AF_INET

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
        if len(self._sockets) > 1:
            paths = self._native.request("inspect_paths", id=self.handle)
            if paths != self._sockets:
                self.close()
                raise ValidationError("Direct route socket ownership changed")
        with self._lock:
            self._check()
            return {"session_id": self._owned["session"], "generation": self._owned["generation"],
                    "certificate": bytes.fromhex(self._owned["certificate"]),
                    "candidates": deepcopy(self._candidates), "expires_at": self.expires_at}

    def _add_mapping(self, mapping, owned=None):
        owned = self._owned if owned is None else owned
        with self._lock:
            if self._closed:
                c.remove_port_mapping(mapping.record())
                raise ValidationError("Direct native preparation expired")
            self._mappings.append(mapping.record())
        if (mapping.protocol != "udp" or mapping.internal_port != owned["port"]
                or mapping.internal_host != owned["host"]
                or c.classify_address(mapping.external_host) not in {"public_ipv4", "public_ipv6"}
                or type(mapping.lifetime) is not int or mapping.lifetime <= 0
                or type(mapping.external_port) is not int or not 1 <= mapping.external_port <= 65535):
            raise ValidationError("Direct mapping does not match native socket")
        if (str(ipaddress.ip_address(mapping.external_host)) != mapping.external_host
                or ipaddress.ip_address(mapping.external_host).version != ipaddress.ip_address(owned["host"]).version):
            raise ValidationError("Direct mapping address family changed")
        expiry = min(self.expires_at, int(self._clock()) + mapping.lifetime)
        self._add_candidate(mapping.external_host, mapping.external_port, expiry)
        self._sources[(mapping.external_host, mapping.external_port)] = mapping.method

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
            self._candidates = [item for item in self._candidates if (item["host"],item["port"]) != (host,port)] + [candidate]
            self._candidates = [{**item,"expires_at":min(item["expires_at"],self.expires_at)} for item in self._candidates]
            self._sources.setdefault((host,port), "local_global")
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
                       clock=time.time, monotonic=time.monotonic, recovery=False, preferred_port=0, preferred_external_port=0,
                       sleep=time.sleep, multiple=False):
    if type(preferred_port) is not int or not 0 <= preferred_port <= 65535:
        raise ValidationError("Invalid local port hint")
    if type(expires_at) is not int:
        raise ValidationError("Direct candidate preparation is invalid")
    remaining = expires_at-clock()
    if (type(generation) is not int or not 1 <= generation < 2**63
            or type(expires_at) is not int or not 1 <= remaining <= (3600 if recovery else 300)
            or family not in (None, socket.AF_INET, socket.AF_INET6)):
        raise ValidationError("Direct candidate preparation is invalid")
    routes = c.default_routes() if routes is None else list(routes)
    eligible = [route for route in routes if route.local_address
        and (family is None or route.family == family)
        and c.classify_address(route.local_address) in {"public_ipv4", "public_ipv6", "rfc1918", "shared"}]
    eligible.sort(key=lambda route: (c.classify_address(route.local_address) != "public_ipv6", route.metric))
    eligible = list({(r.local_address,r.interface):r for r in reversed(eligible)}.values())[::-1][:4]
    route = eligible[0] if eligible else None
    local = route.local_address if route else ("::" if family == socket.AF_INET6 else "0.0.0.0")
    address = f"[{local}]:{preferred_port}" if ":" in local else f"{local}:{preferred_port}"
    operation = "prepare_recovery" if recovery else "prepare"
    # QUIC close drains asynchronously. Give an owned port hint a bounded
    # chance to become free before changing the only address the peer knows.
    # These are local bind attempts, never network probes.
    for retry in range(21):
        remaining = expires_at-clock()
        if remaining <= 0:
            raise ValidationError("Direct candidate preparation expired")
        try:
            owned = native.request(operation, address=address, generation=generation, remaining_ms=int(remaining*1000))
            break
        except ValidationError:
            if not preferred_port:
                raise
            if recovery and retry < 20:
                sleep(.25)
                continue
            address = f"[{local}]:0" if ":" in local else f"{local}:0"
            owned = native.request(operation, address=address, generation=generation, remaining_ms=int(remaining*1000))
            break
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
        preparation = (RecoveryPreparation if recovery else NativePreparation)(native, owned, expires_at, clock=clock, monotonic=monotonic)
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
                mapping = c.create_port_mapping(owned["port"], lifetime=lifetime, routes=[route], protocol="udp", **({"preferred_external_port": preferred_external_port} if recovery else {}))
                preparation._add_mapping(mapping)
            except OSError:
                preparation.reason = "no_public_candidate"
        preparation.document_fields()  # Recheck after potentially slow router operations.
        if multiple and not recovery:
            seen = {(local, route.interface if route else None)}
            for alternative in eligible[1:]:
                if len(preparation._sockets) >= 4:
                    break
                key = (alternative.local_address, alternative.interface)
                if key in seen:
                    continue
                seen.add(key)
                preparation.document_fields()
                host = alternative.local_address
                address = f"[{host}]:0" if ":" in host else f"{host}:0"
                try:
                    extra = native.request("prepare_path", id=preparation.handle, address=address)
                except ValidationError:
                    continue  # A failed local bind/capacity must not discard a usable path.
                if (not isinstance(extra,dict) or set(extra) != {"id","host","port","certificate"}
                        or extra["id"] != preparation.handle or extra["host"] != host
                        or extra["certificate"] != owned["certificate"]
                        or type(extra["port"]) is not int or not 1 <= extra["port"] <= 65535):
                    raise ValidationError("Additional native route ownership is invalid")
                preparation._sockets.append(dict(extra))
                lifetime = max(1,int(preparation.expires_at-clock()))
                kind = c.classify_address(host)
                if kind in {"public_ipv4","public_ipv6"}:
                    preparation._add_candidate(host, extra["port"], preparation.expires_at)
                    if kind == "public_ipv6":
                        try:
                            preparation._add_mapping(c.map_upnp_ipv6_pinhole(host,extra["port"],lifetime=lifetime,
                                routes=[r for r in routes if r.interface == alternative.interface],protocol="udp"), extra)
                        except OSError:
                            pass
                else:
                    try:
                        preparation._add_mapping(c.create_port_mapping(extra["port"],lifetime=lifetime,routes=[alternative],protocol="udp"), extra)
                    except OSError:
                        pass
            preparation.document_fields()
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


class RecoveryPreparation(NativePreparation):
    """Independent socket and candidate leases; renew only the still-owned UDP socket."""
    def _add_candidate(self, host, port, expiry):
        with self._lock:
            self._check()
            self._candidates = [{"host": host, "port": port, "expires_at": min(expiry, self.expires_at)}]
            self.reason = "candidates_prepared_unverified"

    def document_fields(self):
        fields = super().document_fields()
        # Expired hints are never re-signed as currently mapped candidates.
        fields["candidates"] = [c for c in fields["candidates"] if c["expires_at"] > self._clock()]
        fields["expires_at"] = min([fields["expires_at"]] + [c["expires_at"] for c in fields["candidates"]])
        return fields

    def cleanup_records(self):
        with self._lock:
            return deepcopy(self._mappings)

    def renew(self, persist, *, lifetime=3600):
        """Persist/sign the actual renewal result before returning it for export.

        Caller serializes renewal per preparation. Failure invalidates the
        advertised mapping; the still-authenticated connection may remain usable.
        """
        self.document_fields()
        with self._lock:
            old = deepcopy(self._mappings)
        if not old:
            return False
        renewed = []
        try:
            for record in old:
                renewed.append(c.renew_port_mapping(record, lifetime=min(lifetime, max(1,int(self.expires_at-self._clock())))))
            self.document_fields()  # Ownership may have disappeared during router I/O.
            with self._lock:
                self._check()
                self._mappings = []
                self._candidates = []
            for mapping in renewed:
                self._add_mapping(mapping)
            fields = self.document_fields()
            persist(fields, self.cleanup_records())
            # Do not remove a renewed tuple or IPv6 pinhole sharing the same ID.
            for record in old:
                if not any((record["method"], record["external_host"],record["external_port"],record.get("cleanup",{}).get("unique_id")) ==
                           (r.method,r.external_host,r.external_port,r.cleanup.get("unique_id")) for r in renewed):
                    try: c.remove_port_mapping(record)
                    except OSError: pass
            return True
        except Exception:
            if self._closed:
                for mapping in renewed:
                    try: c.remove_port_mapping(mapping.record())
                    except OSError: pass
                raise
            with self._lock:
                self._candidates = []
                self.reason = "mapping_renewal_failed"
                # Retain cleanup references until close, including failed renewals.
                self._mappings = old + [r.record() for r in renewed if r.record() not in old]
            try: persist(self.document_fields(), self.cleanup_records())
            except Exception:
                self.close()
                raise
            return False


    def migrate(self, route, persist):
        """Rebind a live QUIC client, then map and sign that exact new socket."""
        self.document_fields()
        old = self.cleanup_records()
        address = f"[{route.local_address}]:0" if ":" in route.local_address else f"{route.local_address}:0"
        owned = self._native.request("migrate",id=self.handle,address=address)
        if (not isinstance(owned,dict) or set(owned) != {"host","port"}
                or owned["host"] != route.local_address or type(owned["port"]) is not int
                or not 1 <= owned["port"] <= 65535):
            self.close()
            raise ValidationError("Migration lost socket ownership")
        with self._lock:
            self._owned.update(owned)
            self._candidates = []
            self._mappings = []
        try:
            self.document_fields()
            kind = c.classify_address(owned["host"])
            lifetime = max(1,int(self.expires_at-self._clock()))
            if kind in {"public_ipv4","public_ipv6"}:
                self._add_candidate(owned["host"],owned["port"],self.expires_at)
            else:
                try:
                    self._add_mapping(c.create_port_mapping(owned["port"],lifetime=lifetime,routes=[route],protocol="udp"))
                except OSError:
                    self.reason = "no_public_candidate"
            persist(self.document_fields(),self.cleanup_records())
        except Exception:
            self.close()
            raise
        finally:
            current=self.cleanup_records()
            for record in old:
                if not any((record["external_host"],record["external_port"]) ==
                           (r["external_host"],r["external_port"]) for r in current):
                    try: c.remove_port_mapping(record)
                    except OSError: pass
