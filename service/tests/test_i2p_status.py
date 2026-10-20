from __future__ import annotations

from mesh_chat import network
from mesh_chat.reticulum_config import NetworkSettings

B32 = "a" * 52


class I2PInterface:
    def __init__(self, online: bool, b32: str | None) -> None:
        self.name = "I2P"
        self.online = online
        self.receives = True
        self.b32 = b32


class I2PInterfacePeer:
    def __init__(self, online: bool) -> None:
        self.name = "I2P to peer"
        self.online = online
        self.receives = True


def _instance(settings: NetworkSettings) -> network.ReticulumNetwork:
    instance = object.__new__(network.ReticulumNetwork)
    instance.settings = settings
    return instance


def test_i2p_status_is_disabled_without_consent(monkeypatch) -> None:
    monkeypatch.setattr(network.RNS.Transport, "interfaces", [], raising=False)
    status = _instance(NetworkSettings()).i2p_status()
    assert status["state"] == "disabled"
    assert status["online"] is False


def test_i2p_status_reports_not_started_before_interface_attach(monkeypatch) -> None:
    monkeypatch.setattr(network.RNS.Transport, "interfaces", [], raising=False)
    status = _instance(NetworkSettings(i2p_enabled=True, i2p_peers=[B32])).i2p_status()
    assert status["state"] == "not_started"
    assert status["peer_count"] == 1


def test_i2p_status_reports_online_and_only_exposes_own_b32(monkeypatch) -> None:
    interfaces = [I2PInterface(True, B32), I2PInterfacePeer(True)]
    monkeypatch.setattr(network.RNS.Transport, "interfaces", interfaces, raising=False)
    status = _instance(NetworkSettings(
        i2p_enabled=True, i2p_connectable=True, i2p_peers=[B32],
    )).i2p_status()
    assert status["state"] == "online"
    assert status["online_count"] == 2
    assert status["interface_count"] == 2
    assert status["b32"] == B32
    assert status["peer_count"] == 1
    assert status["connectable"] is True


def test_i2p_status_reports_starting_for_an_offline_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        network.RNS.Transport, "interfaces", [I2PInterface(False, None)], raising=False
    )
    status = _instance(NetworkSettings(i2p_enabled=True, i2p_peers=[B32])).i2p_status()
    assert status["state"] == "starting"
    assert status["online"] is False
    assert status["b32"] is None
