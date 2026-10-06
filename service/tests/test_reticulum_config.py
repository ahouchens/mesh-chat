from __future__ import annotations

from mesh_chat.reticulum_config import (
    SIGNED_TCP_ROUTE_GRAVITY,
    NetworkSettings,
    write_config,
)


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
