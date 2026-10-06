from __future__ import annotations

import socket
import os
from types import SimpleNamespace

import RNS

from mesh_chat.network import (
    LAN_FALLBACK_INTERFACE,
    LAN_FALLBACK_MAX_CLIENTS,
    ReticulumNetwork,
    install_lan_listener_guard,
    lan_ipv4_addresses,
    select_lan_listener_port,
    validate_unknown_source_signature,
)
from mesh_chat.reticulum_config import NetworkSettings


class FakeNetInfo:
    AF_INET = socket.AF_INET

    @staticmethod
    def interfaces() -> list[str]:
        return ["link-one", "link-two", "virtual", "wifi", "loopback"]

    @staticmethod
    def ifaddresses(name: str) -> dict[int, list[dict[str, object]]]:
        values = {
            "link-one": [{"addr": "169.254.10.20", "prefix": 16}],
            "link-two": [{"addr": "169.254.30.40", "prefix": 16}],
            "virtual": [{"addr": "192.168.0.1", "prefix": 20}],
            "wifi": [{"addr": "192.168.4.24", "prefix": 22}],
            "loopback": [{"addr": "127.0.0.1", "prefix": 8}],
        }
        return {socket.AF_INET: values[name]}


def test_lan_addresses_are_concrete_local_addresses_only(monkeypatch) -> None:
    fake_rns = SimpleNamespace(
        Interfaces=SimpleNamespace(netinfo=FakeNetInfo),
    )

    addresses = lan_ipv4_addresses(fake_rns, limit=2)

    assert set(addresses) == {"192.168.0.1", "192.168.4.24"}
    assert "127.0.0.1" not in addresses


def test_listener_port_reuses_an_available_preference_and_avoids_a_collision() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as available:
        available.bind(("127.0.0.1", 0))
        preferred = int(available.getsockname()[1])
    assert select_lan_listener_port(b"identity", preferred) == preferred

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("0.0.0.0", 0))
        blocker.listen()
        blocked = int(blocker.getsockname()[1])
        assert select_lan_listener_port(b"identity", blocked) != blocked


def test_invitation_hints_use_only_a_live_lan_listener(monkeypatch) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.settings = NetworkSettings(
        lan_fallback=True,
        lan_listener_port=43123,
    )
    listener = SimpleNamespace(
        name=LAN_FALLBACK_INTERFACE,
        online=True,
        receives=True,
    )
    monkeypatch.setattr(RNS.Transport, "interfaces", [listener])
    monkeypatch.setattr(
        "mesh_chat.network.lan_ipv4_addresses",
        lambda: ["192.168.4.24", "192.168.0.1"],
    )

    assert network.invitation_hints() == [
        {"type": "tcp", "host": "192.168.4.24", "port": 43123},
        {"type": "tcp", "host": "192.168.0.1", "port": 43123},
    ]

    listener.online = False
    assert network.invitation_hints() == []


def test_contact_path_refresh_targets_only_its_online_signed_tcp_client(monkeypatch) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    destination = os.urandom(16)
    nearby = SimpleNamespace(name="Nearby devices", online=True)
    matching = SimpleNamespace(
        name="Private TCP peer 2",
        online=True,
        target_ip="192.168.4.24",
        target_port=43123,
    )
    unrelated = SimpleNamespace(
        name="Private TCP peer 1",
        online=True,
        target_ip="192.168.4.99",
        target_port=43124,
    )
    listener = SimpleNamespace(
        name=LAN_FALLBACK_INTERFACE,
        online=True,
        target_ip="192.168.4.24",
        target_port=43123,
    )
    requested: list[tuple[bytes, object | None]] = []
    monkeypatch.setattr(
        RNS.Transport,
        "interfaces",
        [nearby, unrelated, matching, listener],
    )
    monkeypatch.setattr(
        RNS.Transport,
        "next_hop_interface",
        lambda _destination: nearby,
    )
    monkeypatch.setattr(
        RNS.Transport,
        "request_path",
        lambda value, on_interface=None: requested.append((value, on_interface)),
    )

    ready = network.prefer_signed_route(
        destination,
        [{"type": "tcp", "host": "192.168.4.24", "port": 43123}],
        timeout=0,
    )

    assert ready is False
    assert requested == [(destination, matching)]


def test_late_async_signed_client_replaces_nearby_route_before_return(
    monkeypatch,
) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    destination = os.urandom(16)
    nearby = SimpleNamespace(name="Nearby devices", online=True)
    matching = SimpleNamespace(
        name="Private TCP peer 1",
        online=False,
        target_ip="192.168.4.24",
        target_port=43123,
    )
    current = [nearby]
    requested: list[tuple[bytes, object | None]] = []
    clock = [0.0]
    monkeypatch.setattr(RNS.Transport, "interfaces", [nearby, matching])
    monkeypatch.setattr(
        RNS.Transport,
        "next_hop_interface",
        lambda _destination: current[0],
    )

    def request_path(value, on_interface=None) -> None:
        requested.append((value, on_interface))
        current[0] = on_interface

    def advance_clock(delay: float) -> None:
        clock[0] += delay
        matching.online = True

    monkeypatch.setattr(RNS.Transport, "request_path", request_path)
    monkeypatch.setattr("mesh_chat.network.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("mesh_chat.network.time.sleep", advance_clock)

    assert network.prefer_signed_route(
        destination,
        [{"type": "tcp", "host": "192.168.4.24", "port": 43123}],
        timeout=0.1,
    ) is True
    assert requested == [(destination, matching)]
    assert current[0] is matching

    monkeypatch.setattr(
        RNS.Transport,
        "next_hop_interface",
        lambda _destination: matching,
    )
    assert network.prefer_signed_route(
        destination,
        [{"type": "tcp", "host": "192.168.4.24", "port": 43123}],
    ) is True
    assert requested == [(destination, matching)]


def test_failed_signed_path_request_falls_back_without_raising(monkeypatch) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    destination = os.urandom(16)
    nearby = SimpleNamespace(name="Nearby devices", online=True)
    matching = SimpleNamespace(
        name="Private TCP peer 1",
        online=True,
        target_ip="192.168.4.24",
        target_port=43123,
    )
    monkeypatch.setattr(RNS.Transport, "interfaces", [nearby, matching])
    monkeypatch.setattr(
        RNS.Transport,
        "next_hop_interface",
        lambda _destination: nearby,
    )

    def fail_request(_value, on_interface=None) -> None:
        assert on_interface is matching
        raise RuntimeError("stale TCP client")

    monkeypatch.setattr(RNS.Transport, "request_path", fail_request)

    assert network.prefer_signed_route(
        destination,
        [{"type": "tcp", "host": "192.168.4.24", "port": 43123}],
        timeout=0,
    ) is False


def test_lan_listener_guard_rejects_off_link_and_excess_connections() -> None:
    class FakeServer:
        def __init__(self) -> None:
            self.name = LAN_FALLBACK_INTERFACE
            self.accepted: list[str] = []

        def incoming_connection(self, handler) -> None:
            self.accepted.append(handler.client_address[0])

    class FakeSocket:
        def __init__(self) -> None:
            self.closed = False

        def shutdown(self, _how: int) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    fake_rns = SimpleNamespace(
        Interfaces=SimpleNamespace(
            netinfo=FakeNetInfo,
            TCPInterface=SimpleNamespace(TCPServerInterface=FakeServer),
        )
    )
    install_lan_listener_guard(fake_rns)
    server = FakeServer()

    allowed = SimpleNamespace(
        client_address=("192.168.4.55", 50000), request=FakeSocket()
    )
    server.incoming_connection(allowed)
    assert server.accepted == ["192.168.4.55"]
    assert allowed.request.closed is False

    off_link = SimpleNamespace(
        client_address=("203.0.113.8", 50001), request=FakeSocket()
    )
    server.incoming_connection(off_link)
    assert off_link.request.closed is True
    assert server.accepted == ["192.168.4.55"]

    server._mesh_chat_active = LAN_FALLBACK_MAX_CLIENTS
    excess = SimpleNamespace(
        client_address=("192.168.4.56", 50002), request=FakeSocket()
    )
    server.incoming_connection(excess)
    assert excess.request.closed is True


def test_unknown_source_signature_is_validated_from_invitation_identity() -> None:
    identity = RNS.Identity()
    source = RNS.Destination.hash(identity, "lxmf", "delivery")
    destination = os.urandom(16)
    packed_payload = b"bounded-contact-request-payload"
    hashed_part = destination + source + packed_payload
    message_hash = RNS.Identity.full_hash(hashed_part)
    signature = identity.sign(hashed_part + message_hash)
    message = SimpleNamespace(
        packed=destination + source + signature + packed_payload,
        destination_hash=destination,
        source_hash=source,
        hash=message_hash,
    )

    assert validate_unknown_source_signature(message, identity.get_public_key()) is True

    tampered = SimpleNamespace(**vars(message))
    tampered.packed = tampered.packed[:-1] + bytes([tampered.packed[-1] ^ 1])
    assert validate_unknown_source_signature(tampered, identity.get_public_key()) is False


def test_wrong_destination_is_rejected_before_unknown_source_bootstrap() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.delivery_destination = SimpleNamespace(hash=b"local-destination")
    received: list[object] = []
    network._inbound_callback = received.append
    message = SimpleNamespace(
        destination_hash=b"different-destination",
        signature_validated=False,
    )

    network._on_inbound(message)

    assert received == []
