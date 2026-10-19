from __future__ import annotations

from mesh_chat import i2p_router


def test_binary_path_honors_explicit_environment(tmp_path, monkeypatch) -> None:
    binary = tmp_path / "i2pd.exe"
    binary.write_bytes(b"stub")
    monkeypatch.setenv("MESH_CHAT_I2PD_PATH", str(binary))
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: True))
    manager = i2p_router.I2PRouterManager(tmp_path)
    assert manager.binary_path() == binary


def test_missing_router_is_reported_without_starting_a_process(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: True))
    monkeypatch.delenv("MESH_CHAT_I2PD_PATH", raising=False)
    monkeypatch.setattr(i2p_router.I2PRouterManager, "binary_path", lambda self: None)
    monkeypatch.setattr(i2p_router.I2PRouterManager, "sam_available", staticmethod(lambda: False))
    manager = i2p_router.I2PRouterManager(tmp_path)
    status = manager.start()
    assert status["state"] == "failed"
    assert status["reason"] == "router_missing"
    assert status["managed"] is False


def test_external_sam_is_not_managed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: True))
    monkeypatch.setattr(i2p_router.I2PRouterManager, "sam_available", staticmethod(lambda: True))
    manager = i2p_router.I2PRouterManager(tmp_path)
    status = manager.start()
    assert status["state"] == "external"
    assert status["available"] is True
    assert status["managed"] is False


def test_non_windows_platform_is_unsupported(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: False))
    manager = i2p_router.I2PRouterManager(tmp_path)
    status = manager.start()
    assert status["state"] == "failed"
    assert status["reason"] == "unsupported_platform"
