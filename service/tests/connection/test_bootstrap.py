from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from mesh_chat.errors import NativeUnavailable
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def host():
    def unexpected(*_):
        pytest.fail("An empty profile cannot allocate a native peer")
    return SimpleNamespace(**{name: unexpected for name in (
        "createOffer", "acceptOffer", "applyAnswer", "send", "sendControl", "stats", "close")})


@pytest.mark.parametrize("binding", ["explicit", "explicit_inventory", "android_default"])
def test_shared_constructor_binds_private_host(tmp_path, monkeypatch, binding):
    from mesh_chat import native_webrtc_host
    native = host()
    if binding == "explicit_inventory":
        native.inventory = lambda: {"v": 1, "adapter_epoch": "a" * 32, "resources": []}
        native.activate = lambda _: pytest.fail("An empty inventory cannot activate a carrier")
        native.shutdown = lambda: pytest.fail("An empty valid inventory must not quarantine its host")
    loaded = []
    def load_android():
        loaded.append(True)
        return native
    monkeypatch.setattr(native_webrtc_host, "android_host", load_android)
    store = VaultStore(tmp_path, b"b" * 32, allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
    service = None
    try:
        service = MeshChatService(store, tmp_path, lambda _: None,
                                  connection_policy="shared-native",
                                  native_webrtc_host=native if binding.startswith("explicit") else None)
        assert service._native_webrtc_host() is native
        assert loaded == ([] if binding.startswith("explicit") else [True])
        assert (service._carrier_journal is not None) == (binding == "explicit_inventory")
        owner = service._connection_runtime
        deadline = monotonic() + 1
        while monotonic() < deadline:
            assert owner._failure is None
            sleep(0.02)
        assert owner.snapshots() == {}
        assert owner.runner.idle
        assert service._background_reconnect_supervisor is None
    finally:
        if service is not None:
            service.close()
        store.close()


@pytest.mark.parametrize("missing", ["createOffer", "acceptOffer", "applyAnswer", "send", "sendControl", "stats", "close"])
def test_missing_host_capability_fails_before_service_initialization(missing):
    native = host()
    delattr(native, missing)
    with pytest.raises(NativeUnavailable, match="capabilities"):
        MeshChatService(None, None, None, connection_policy="shared-native", native_webrtc_host=native)


def test_inventory_capability_requires_a_private_quarantine_mechanism():
    native = host()
    native.inventory = lambda: {}
    with pytest.raises(NativeUnavailable, match="quarantine"):
        MeshChatService(None, None, None, connection_policy="shared-native", native_webrtc_host=native)
