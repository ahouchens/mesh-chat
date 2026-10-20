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


class _FakeProcess:
    def __init__(self, poll_result=None) -> None:
        self.poll_result = poll_result
        self.terminated = False

    def poll(self):
        return self.poll_result

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self) -> None:
        self.terminated = True


def test_sam_timeout_stops_the_process(tmp_path, monkeypatch) -> None:
    binary = tmp_path / "i2pd.exe"
    binary.write_bytes(b"stub")
    process = _FakeProcess()
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: True))
    monkeypatch.setattr(i2p_router.I2PRouterManager, "binary_path", lambda self: binary)
    monkeypatch.setattr(i2p_router.I2PRouterManager, "sam_available", staticmethod(lambda: False))
    monkeypatch.setattr(i2p_router.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(i2p_router.time, "sleep", lambda _seconds: None)
    manager = i2p_router.I2PRouterManager(tmp_path)
    status = manager.start()
    assert status["state"] == "failed"
    assert status["reason"] == "sam_timeout"
    assert process.terminated is True


def test_router_exit_is_reported_and_cleaned_up(tmp_path, monkeypatch) -> None:
    binary = tmp_path / "i2pd.exe"
    binary.write_bytes(b"stub")
    process = _FakeProcess(poll_result=3)
    monkeypatch.setattr(i2p_router.I2PRouterManager, "supported", staticmethod(lambda: True))
    monkeypatch.setattr(i2p_router.I2PRouterManager, "binary_path", lambda self: binary)
    monkeypatch.setattr(i2p_router.I2PRouterManager, "sam_available", staticmethod(lambda: False))
    monkeypatch.setattr(i2p_router.subprocess, "Popen", lambda *args, **kwargs: process)
    manager = i2p_router.I2PRouterManager(tmp_path)
    status = manager.start()
    assert status["state"] == "failed"
    assert status["reason"] == "router_exited"


def test_stop_terminates_a_managed_process(tmp_path) -> None:
    manager = i2p_router.I2PRouterManager(tmp_path)
    process = _FakeProcess()
    manager._process = process
    manager._started = True
    manager.stop()
    assert process.terminated is True
    assert manager.status()["state"] == "not_started"
