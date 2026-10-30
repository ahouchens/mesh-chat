"""Trusted mobile composition selects one owner before service startup."""
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mesh_chat import mobile_bridge, native_webrtc_host
from mesh_chat.errors import ValidationError


@pytest.fixture
def mobile_request(tmp_path, monkeypatch):
    mobile_bridge.shutdown()
    monkeypatch.setattr(sys, "platform", "android")
    monkeypatch.setattr(Path, "home", classmethod(lambda _: tmp_path))

    def unexpected(*_):
        pytest.fail("An empty profile must not allocate a native peer")

    native = SimpleNamespace(**{name: unexpected for name in native_webrtc_host.HOST_METHODS})
    monkeypatch.setattr(native_webrtc_host, "android_host", lambda: native)
    yield json.dumps({"profile_dir": str(tmp_path / "files" / "profile"),
                      "vault_key": base64.b64encode(b"b" * 32).decode(),
                      "platform": "android"})
    assert json.loads(mobile_bridge.shutdown())["ok"]


@pytest.mark.parametrize("policy", ["legacy", "shared-native"])
def test_mobile_constructor_selects_one_owner_and_rejects_live_switch(mobile_request, policy):
    result = json.loads(mobile_bridge.initialize(mobile_request, connection_policy=policy))
    assert result["ok"]
    service = mobile_bridge._service
    owner = service._connection_runtime
    assert service._connection_policy == policy
    assert (owner is not None) == (policy == "shared-native")
    assert service._background_reconnect_supervisor is None
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy=policy))["ok"]
    other = "legacy" if policy == "shared-native" else "shared-native"
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy=other)) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is service
    assert service._connection_runtime is owner
    if owner is not None:
        assert owner._thread.is_alive()
        assert owner._failure is None


def test_mobile_default_remains_legacy(mobile_request):
    assert json.loads(mobile_bridge.initialize(mobile_request))["ok"]
    assert mobile_bridge._service._connection_policy == "legacy"
    assert mobile_bridge._service._connection_runtime is None


@pytest.mark.parametrize("field", ["connection_policy", "native_webrtc_host"])
def test_mobile_json_cannot_select_private_composition(mobile_request, field):
    request = json.loads(mobile_request)
    request[field] = "shared-native"
    assert json.loads(mobile_bridge.initialize(json.dumps(request))) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is None


def test_invalid_private_policy_fails_before_opening_vault(mobile_request, monkeypatch):
    monkeypatch.setattr(mobile_bridge, "VaultStore", lambda *_a, **_k: pytest.fail("Opened vault"))
    assert json.loads(mobile_bridge.initialize(mobile_request, connection_policy="unknown")) == {
        "ok": False, "error": {"code": "invalid_request"}}
    assert mobile_bridge._service is None


@pytest.mark.parametrize("policy", ["legacy", "shared-native"])
def test_profile_failure_closes_unpublished_service(mobile_request, monkeypatch, policy):
    constructed = []

    def fail_profile(service, _name):
        constructed.append(service)
        raise ValidationError("Profile creation failed")

    monkeypatch.setattr(mobile_bridge.MeshChatService, "create_profile", fail_profile)
    request = json.loads(mobile_request)
    request["display_name"] = "Synthetic profile"
    try:
        assert json.loads(mobile_bridge.initialize(json.dumps(request), connection_policy=policy)) == {
            "ok": False, "error": {"code": "invalid_request"}}
        service, = constructed
        assert service._shutdown.is_set()
        assert service._store_closed
        if service._connection_runtime is not None:
            assert not service._connection_runtime._thread.is_alive()
        assert mobile_bridge._service is None
        assert mobile_bridge._native_channel is None
    finally:
        for service in constructed:
            service.close()
