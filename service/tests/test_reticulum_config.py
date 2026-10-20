from __future__ import annotations

import pytest

from mesh_chat.errors import ValidationError
from mesh_chat.reticulum_config import (
    REMOTE_TCP_ROUTE_GRAVITY,
    SIGNED_TCP_ROUTE_GRAVITY,
    NetworkSettings,
    write_config,
)

B32 = "a" * 52 + ".b32.i2p"


def test_profile_is_isolated_and_no_external_interfaces_are_bundled(tmp_path) -> None:
    path = write_config(tmp_path, NetworkSettings())
    text = path.read_text(encoding="utf-8")
    assert "share_instance = No" in text
    assert "discover_interfaces = No" in text
    assert "enable_transport = No" in text
    assert "AutoInterface" in text
    assert "I2P" not in text
    assert "public" not in text.lower()


def test_transport_and_propagation_controls_are_independent(tmp_path) -> None:
    settings = NetworkSettings(help_route=True, store_for_offline=False)
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")
    assert "enable_transport = Yes" in text
    assert settings.store_for_offline is False


def test_lan_fallback_listener_binds_wildcard_without_advertising_a_secret(tmp_path) -> None:
    settings = NetworkSettings(lan_fallback=True, lan_listener_port=43123)
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")

    assert "[[Mesh Chat LAN fallback]]" in text
    assert "type = TCPServerInterface" in text
    assert "listen_ip = 0.0.0.0" in text
    assert "listen_port = 43123" in text
    assert "ingress_control = Yes" in text
    assert "passphrase" not in text
    assert "network_name" not in text


def test_only_signed_hint_clients_get_preferred_route_gravity(tmp_path) -> None:
    settings = NetworkSettings(
        nearby_discovery=True,
        lan_fallback=True,
        lan_listener_port=43123,
        tcp_clients=[{"type": "tcp", "host": "192.168.4.24", "port": 43124}],
        tcp_listener={"host": "192.168.4.25", "port": 43125},
    )
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")
    peer_section = text.split("[[Private TCP peer 1]]", 1)[1].split(
        "[[Mesh Chat LAN fallback]]", 1
    )[0]
    listener_section = text.split("[[Mesh Chat LAN fallback]]", 1)[1]
    private_listener_section = text.split("[[Private TCP listener]]", 1)[1]

    assert f"gravity = {SIGNED_TCP_ROUTE_GRAVITY}" in peer_section
    assert "gravity =" not in listener_section
    assert "gravity =" not in private_listener_section


def test_legacy_settings_enable_lan_fallback_without_inventing_a_port() -> None:
    settings = NetworkSettings.from_dict({"nearby_discovery": True})

    assert settings.lan_fallback is True
    assert settings.lan_listener_port is None


def test_shared_remote_access_does_not_receive_signed_direct_route_gravity(tmp_path) -> None:
    settings = NetworkSettings(
        remote_tcp_clients=[{
            "profile_id": "ab" * 32,
            "endpoint_index": 0,
            "host": "93.184.216.34",
            "port": 4242,
        }]
    )
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")
    remote = text.split("[[Remote access abababababab 1]]", 1)[1]
    assert f"gravity = {REMOTE_TCP_ROUTE_GRAVITY}" in remote
    assert f"gravity = {SIGNED_TCP_ROUTE_GRAVITY}" not in remote
    assert "relay" not in remote.lower()


def test_i2p_peer_block_is_written_only_when_enabled(tmp_path) -> None:
    settings = NetworkSettings(i2p_enabled=True, i2p_peers=[B32])
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")

    assert "[[I2P]]" in text
    assert "type = I2PInterface" in text
    assert "connectable = No" in text
    assert f"peers = {B32}" in text
    assert "enable_transport = No" in text


def test_i2p_connectable_access_point_needs_no_peer_address(tmp_path) -> None:
    settings = NetworkSettings(i2p_enabled=True, i2p_connectable=True)
    text = write_config(tmp_path, settings).read_text(encoding="utf-8")

    assert "[[I2P]]" in text
    assert "connectable = Yes" in text
    assert "peers =" not in text


def test_i2p_settings_round_trip_and_normalize_addresses() -> None:
    settings = NetworkSettings.from_dict({
        "i2p_enabled": True,
        "i2p_connectable": False,
        "i2p_managed": False,
        "i2p_peers": [" " + B32.upper() + " ", B32],
    })

    assert settings.i2p_peers == [B32]
    assert settings.i2p_managed is False
    assert settings.to_dict()["i2p_peers"] == [B32]
    assert settings.to_dict()["i2p_managed"] is False


@pytest.mark.parametrize("peers", [["not-a-b32"], ["a" * 52], ["a" * 53 + ".b32.i2p"]])
def test_i2p_rejects_invalid_access_point_addresses(peers) -> None:
    with pytest.raises(ValidationError):
        NetworkSettings.from_dict({"i2p_enabled": True, "i2p_peers": peers})


def test_i2p_requires_a_peer_or_connectable_mode_when_enabled() -> None:
    with pytest.raises(ValidationError):
        NetworkSettings.from_dict({"i2p_enabled": True})


def test_i2p_accepts_a_disabled_empty_configuration() -> None:
    settings = NetworkSettings.from_dict({"i2p_enabled": False})
    assert settings.i2p_enabled is False
    assert settings.i2p_peers == []
