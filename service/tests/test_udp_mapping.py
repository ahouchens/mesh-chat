import socket
import struct

import pytest

from mesh_chat import connectivity as c


ROUTE = c.RouteInfo(socket.AF_INET, "Wi-Fi", "192.168.1.1", "192.168.1.20", 1)
PUBLIC = "93.184.216.34"


@pytest.mark.parametrize("protocol,opcode", [("tcp", 2), ("udp", 1)])
def test_nat_pmp_create_renew_remove_preserves_protocol(monkeypatch, protocol, opcode):
    requests = []
    def exchange(_gateway, payload, _size, *args, **kwargs):
        requests.append(payload)
        if payload == b"\x00\x00":
            return struct.pack("!BBHII", 0, 128, 0, 10, int.from_bytes(socket.inet_aton(PUBLIC), "big"))
        assert payload[1] == opcode
        return struct.pack("!BBHIHHI", 0, 128 + opcode, 0, 10, 45678, 55000, 600)
    monkeypatch.setattr(c, "_retry_gateway_exchange", exchange)
    monkeypatch.setattr(c, "_gateway_exchange", exchange)
    monkeypatch.setattr(c, "_local_address_for", lambda *_: ROUTE.local_address)
    mapped = c.map_nat_pmp(45678, routes=[ROUTE], protocol=protocol)
    assert mapped.protocol == protocol and mapped.record()["protocol"] == protocol
    renewed = c.renew_port_mapping(mapped.record())
    assert renewed.protocol == protocol
    c.remove_port_mapping(renewed.record())
    assert requests[-1] == struct.pack("!BBHHHI", 0, opcode, 0, 45678, 55000, 0)


@pytest.mark.parametrize("protocol,number", [("tcp", 6), ("udp", 17)])
def test_pcp_create_renew_remove_preserves_protocol_and_nonce(monkeypatch, protocol, number):
    requests = []
    def exchange(_gateway, payload, _size, *args, **kwargs):
        requests.append(payload)
        assert payload[36] == number
        response = bytearray(payload)
        response[:24] = struct.pack("!BBBBII", 2, 0x81, 0, 0, 600, 10) + b"\0" * 12
        response[42:44] = struct.pack("!H", 55000)
        response[44:60] = b"\0" * 10 + b"\xff\xff" + socket.inet_aton(PUBLIC)
        return bytes(response)
    monkeypatch.setattr(c, "_retry_gateway_exchange", exchange)
    monkeypatch.setattr(c, "_gateway_exchange", exchange)
    monkeypatch.setattr(c, "_local_address_for", lambda *_: ROUTE.local_address)
    mapped = c.map_pcp(45678, routes=[ROUTE], protocol=protocol)
    renewed = c.renew_port_mapping(mapped.record())
    assert mapped.protocol == renewed.protocol == protocol
    c.remove_port_mapping(renewed.record())
    assert requests[-1][4:8] == b"\0" * 4
    assert requests[0][24:36] == requests[1][24:36] == requests[2][24:36]


@pytest.mark.parametrize("igd_version", [1, 2])
def test_upnp_udp_create_renew_remove_uses_udp(monkeypatch, igd_version):
    actions = []
    monkeypatch.setattr(c, "_upnp_external", lambda *_: (
        ROUTE.local_address, f"urn:schemas-upnp-org:service:WANIPConnection:{igd_version}",
        "http://192.168.1.1/control", PUBLIC))
    def soap(_url, _service, action, arguments, **kwargs):
        actions.append((action, arguments))
        if action == "AddAnyPortMapping":
            return b"<r><NewReservedPort>55000</NewReservedPort></r>"
        if action == "GetStatusInfo":
            return b"<r><NewUptime>100</NewUptime></r>"
        if action == "GetExternalIPAddress":
            return f"<r><NewExternalIPAddress>{PUBLIC}</NewExternalIPAddress></r>".encode()
        return b"<r/>"
    monkeypatch.setattr(c, "_soap", soap)
    mapped = c.map_upnp(45678, routes=[], protocol="udp")
    renewed = c.renew_port_mapping(mapped.record())
    c.remove_port_mapping(renewed.record())
    mapping_calls = [arguments for action, arguments in actions
                     if action in {"AddAnyPortMapping", "AddPortMapping", "DeletePortMapping"}]
    assert len(mapping_calls) == 3
    assert all(arguments["NewProtocol"] == "UDP" for arguments in mapping_calls)
    assert renewed.protocol == "udp"
    with pytest.raises(ValueError, match="legacy TCP"):
        renewed.endpoint()


def test_udp_ipv6_pinhole_keeps_protocol(monkeypatch):
    actions = []
    monkeypatch.setattr(c, "_upnp_locations_by_route", lambda *_: [(ROUTE.local_address, "router")])
    monkeypatch.setattr(c, "_upnp_services", lambda *a, **kw: {c.UPNP_IPV6_FIREWALL_SERVICE: "control"})
    def soap(_url, _service, action, arguments, **kwargs):
        actions.append((action, arguments))
        if action == "GetFirewallStatus":
            return b"<r><FirewallEnabled>1</FirewallEnabled><InboundPinholeAllowed>1</InboundPinholeAllowed></r>"
        return b"<r><UniqueID>42</UniqueID></r>"
    monkeypatch.setattr(c, "_soap", soap)
    mapped = c.map_upnp_ipv6_pinhole("2001:4860::20", 45678, routes=[], protocol="udp")
    renewed = c.renew_port_mapping(mapped.record())
    c.remove_port_mapping(renewed.record())
    assert actions[1][1]["Protocol"] == "17"
    assert renewed.protocol == "udp"
    assert actions[-1][1] == {"UniqueID": "42"}


@pytest.mark.parametrize("method", ["pcp", "nat_pmp"])
@pytest.mark.parametrize("fault", ["wrong_protocol", "wrong_version", "zero_lease"])
def test_renewal_rejects_mismatched_or_dead_mapping(monkeypatch, method, fault):
    nonce = b"n" * 12
    record = c.MappingResult(method, PUBLIC, 55000, ROUTE.local_address, 45678, 600,
        {"gateway": ROUTE.gateway, "nonce": nonce.hex(), "epoch": 10}, "udp").record()
    def exchange(_gateway, payload, _size, **kwargs):
        if payload == b"\0\0":
            return struct.pack("!BBHII", 0, 128, 0, 10, int.from_bytes(socket.inet_aton(PUBLIC), "big"))
        lease = 0 if fault == "zero_lease" else 600
        if method == "nat_pmp":
            return struct.pack("!BBHIHHI", 1 if fault == "wrong_version" else 0,
                130 if fault == "wrong_protocol" else 129, 0, 10, 45678, 55000, lease)
        return (struct.pack("!BBBBII", 1 if fault == "wrong_version" else 2, 0x81, 0, 0, lease, 10)
            + b"\0" * 12 + nonce + struct.pack("!B3sHH", 6 if fault == "wrong_protocol" else 17,
                b"\0" * 3, 45678, 55000) + b"\0" * 10 + b"\xff\xff" + socket.inet_aton(PUBLIC))
    monkeypatch.setattr(c, "_retry_gateway_exchange", exchange)
    monkeypatch.setattr(c, "_local_address_for", lambda *_: ROUTE.local_address)
    with pytest.raises(c.ConnectivityError, match="router_state_changed"):
        c.renew_port_mapping(record)


def test_legacy_records_default_to_tcp_and_unknown_protocol_has_no_network_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(c, "_gateway_exchange", lambda *args, **kwargs: calls.append(args))
    record = c.MappingResult("nat_pmp", PUBLIC, 55000, ROUTE.local_address, 45678, 600,
                             {"gateway": ROUTE.gateway}).record()
    del record["protocol"]
    c.remove_port_mapping(record)
    assert calls[0][1][1] == 2
    c.remove_port_mapping({**record, "protocol": "unknown"})
    assert len(calls) == 1
    with pytest.raises(ValueError):
        c.create_port_mapping(45678, protocol="UDP")


def test_udp_fallback_keeps_protocol(monkeypatch):
    seen = []
    def unavailable(*args, **kwargs):
        seen.append(kwargs["protocol"])
        raise c.ConnectivityError("pcp", "pcp_no_response")
    def mapped(*args, **kwargs):
        seen.append(kwargs["protocol"])
        return c.MappingResult("nat_pmp", PUBLIC, 55000, ROUTE.local_address, 45678, 600, {}, "udp")
    monkeypatch.setattr(c, "map_pcp", unavailable)
    monkeypatch.setattr(c, "map_upnp", unavailable)
    monkeypatch.setattr(c, "map_nat_pmp", mapped)
    assert c.create_port_mapping(45678, protocol="udp").protocol == "udp"
    assert seen == ["udp", "udp", "udp"]
