import socket
import uuid

import pytest

from mesh_chat import connectivity as c
from mesh_chat.direct_candidates import prepare_candidates
from mesh_chat.errors import ValidationError

V4 = c.RouteInfo(socket.AF_INET, "wifi", "192.168.1.1", "192.168.1.20", 1)
V6 = c.RouteInfo(socket.AF_INET6, "wifi", "fe80::1", "2001:4860::20", 1)


class Native:
    def __init__(self):
        self.calls = []
        self.owned = None
        self.changed = False

    def request(self, operation, **payload):
        self.calls.append((operation, payload))
        if operation == "prepare":
            host = payload["address"].rsplit(":", 1)[0].strip("[]")
            self.owned = {"id": 1, "session": str(uuid.uuid4()), "generation": payload["generation"],
                "host": host, "port": 45678, "certificate": b"native certificate".hex()}
            return dict(self.owned)
        if operation == "inspect":
            result = {key: self.owned[key] for key in ("id", "host", "port", "certificate")}
            if self.changed:
                result["port"] += 1
            return result


def prepare(native, **kwargs):
    return prepare_candidates(native, generation=1, expires_at=1300, clock=lambda:1000,
                              monotonic=lambda:100, **kwargs)


def test_udp_mapping_uses_native_port_and_selected_interface(monkeypatch):
    native, removed = Native(), []
    def mapping(port, **options):
        assert native.calls[0][0] == "prepare"
        assert port == native.owned["port"] == 45678
        assert options == {"lifetime":300,"routes":[V4],"protocol":"udp"}
        return c.MappingResult("pcp", "93.184.216.34", 55000, V4.local_address, port, 120, {}, "udp")
    monkeypatch.setattr(c, "create_port_mapping", mapping)
    monkeypatch.setattr(c, "remove_port_mapping", removed.append)
    prepared = prepare(native, routes=[V4])
    try:
        fields = prepared.document_fields()
        assert fields["candidates"] == [{"host":"93.184.216.34","port":55000,"expires_at":1120}]
        assert fields["expires_at"] == 1120
        assert prepared._timer.interval == 120
        fields["candidates"].clear()
        assert len(prepared.document_fields()["candidates"]) == 1
    finally:
        prepared.close()
    prepared.close()
    assert len(removed) == 1 and removed[0]["protocol"] == "udp"
    assert native.calls[-1] == ("close", {"id":1})


@pytest.mark.parametrize("routes", [[], [V4]])
def test_no_public_tuple_still_prepares_reply_without_claiming_reachability(monkeypatch, routes):
    def unavailable(*args, **kwargs):
        raise c.ConnectivityError("pcp", "pcp_no_response")
    monkeypatch.setattr(c, "create_port_mapping", unavailable)
    native = Native()
    prepared = prepare(native, routes=routes)
    try:
        assert prepared.document_fields()["candidates"] == []
        assert prepared.reason == "no_public_candidate"
    finally:
        prepared.close()


@pytest.mark.parametrize("fault", ["host", "port", "protocol", "external", "lifetime"])
def test_mapping_substitution_is_rejected_and_removed(monkeypatch, fault):
    fields = dict(method="pcp", external_host="93.184.216.34", external_port=55000,
                  internal_host=V4.local_address, internal_port=45678, lifetime=300, cleanup={}, protocol="udp")
    changes = {"host": {"internal_host":"192.168.2.20"}, "port":{"internal_port":45679},
        "protocol":{"protocol":"tcp"}, "external":{"external_host":"100.64.0.1"}, "lifetime":{"lifetime":0}}
    fields.update(changes[fault])
    removed = []
    monkeypatch.setattr(c, "create_port_mapping", lambda *a, **k: c.MappingResult(**fields))
    monkeypatch.setattr(c, "remove_port_mapping", removed.append)
    native = Native()
    with pytest.raises(ValidationError):
        prepare(native, routes=[V4])
    assert len(removed) == 1 and native.calls[-1][0] == "close"


def test_public_ipv6_pinhole_matches_owned_tuple_and_interface(monkeypatch):
    other = c.RouteInfo(socket.AF_INET, "other", "10.0.0.1", "10.0.0.2", 1)
    def pinhole(host, port, **options):
        assert host == V6.local_address and port == 45678
        assert options["routes"] == [V4, V6]
        assert options["protocol"] == "udp"
        raise c.ConnectivityError("upnp", "upnp_no_discovery")
    monkeypatch.setattr(c, "map_upnp_ipv6_pinhole", pinhole)
    native = Native()
    prepared = prepare(native, routes=[V4, V6, other])
    try:
        assert prepared.document_fields()["candidates"][0]["host"] == V6.local_address
        assert prepared.reason == "candidates_prepared_unverified"
    finally:
        prepared.close()


def test_native_socket_change_and_slow_mapping_cannot_be_advertised(monkeypatch):
    native = Native()
    removed = []
    def mapping(*args, **kwargs):
        native.changed = True
        return c.MappingResult("pcp", "93.184.216.34", 55000, V4.local_address, 45678, 300, {}, "udp")
    monkeypatch.setattr(c, "create_port_mapping", mapping)
    monkeypatch.setattr(c, "remove_port_mapping", removed.append)
    with pytest.raises(ValidationError, match="ownership"):
        prepare(native, routes=[V4])
    assert len(removed) == 1
    native, now = Native(), [1000]
    def delayed(*args, **kwargs):
        now[0] = 1301
        return c.MappingResult("pcp", "93.184.216.34", 55000, V4.local_address, 45678, 300, {}, "udp")
    monkeypatch.setattr(c, "create_port_mapping", delayed)
    with pytest.raises(ValidationError, match="expired"):
        prepare_candidates(native, generation=1, expires_at=1300, routes=[V4], clock=lambda:now[0])
    assert len(removed) == 2


def test_direct_public_ipv4_does_not_map_or_select_an_unowned_port(monkeypatch):
    native = Native()
    route = c.RouteInfo(socket.AF_INET, "public", None, "93.184.216.34", 1)
    monkeypatch.setattr(c, "create_port_mapping", lambda *a, **k: pytest.fail("unnecessary mapping"))
    monkeypatch.setattr(c, "select_available_port", lambda *a, **k: pytest.fail("discovery socket"))
    prepared = prepare(native, routes=[route])
    try:
        assert prepared.document_fields()["candidates"] == [{"host":route.local_address,"port":45678,"expires_at":1300}]
    finally:
        prepared.close()


def test_all_eligible_route_sockets_are_owned_and_mixed_family_candidates_retained(monkeypatch):
    class PathsNative(Native):
        def request(self, operation, **payload):
            if operation == "prepare":
                value = super().request(operation, **payload)
                self.paths = [{key:value[key] for key in ("id","host","port","certificate")}]
                return value
            if operation == "prepare_path":
                self.calls.append((operation,payload))
                value = {"id":1,"host":payload["address"].rsplit(":",1)[0].strip("[]"),
                         "port":45678+len(self.paths),"certificate":self.owned["certificate"]}
                self.paths.append(value)
                return dict(value)
            if operation == "inspect_paths":
                return [dict(value) for value in self.paths]
            return super().request(operation, **payload)
    native = PathsNative()
    route4 = c.RouteInfo(socket.AF_INET, "wired", None, "93.184.216.34", 2)
    monkeypatch.setattr(c,"map_upnp_ipv6_pinhole",lambda *a,**k: (_ for _ in ()).throw(OSError()))
    prepared = prepare(native, routes=[V6,route4], multiple=True)
    try:
        fields = prepared.document_fields()
        assert {row["host"] for row in fields["candidates"]} == {V6.local_address,route4.local_address}
        assert {row["port"] for row in fields["candidates"]} == {45678,45679}
        assert len(prepared._sockets) == 2
        native.paths[1]["port"] += 1
        with pytest.raises(ValidationError, match="ownership"):
            prepared.document_fields()
    finally:
        prepared.close()


def test_failed_additional_bind_preserves_existing_owned_candidate(monkeypatch):
    class UnavailableNative(Native):
        def request(self, operation, **payload):
            if operation == "prepare_path":
                raise ValidationError("unavailable")
            return super().request(operation, **payload)
    monkeypatch.setattr(c,"map_upnp_ipv6_pinhole",lambda *a,**k: (_ for _ in ()).throw(OSError()))
    native = UnavailableNative()
    prepared = prepare(native, routes=[V6,V4], multiple=True)
    try:
        assert len(prepared.document_fields()["candidates"]) == 1
    finally:
        prepared.close()
