"""Real mobile Vault/Core; native key, RTC and confirmation are explicit doubles."""
import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat import mobile_bridge, native_webrtc_host
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.service import MeshChatService
from test_mobile_bootstrap import mobile_request


@pytest.fixture
def ordinary(mobile_request, tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    native_webrtc_host.android_host().resourceAccounting = lambda: json.dumps(
        {"ok": True, "result": {"complete": True, "reserved_count": 0}})
    loads, proof = [], set()
    root = tmp_path / "files" / "mesh-core-runtime" / "profile-v1"
    def profile_key():
        loads.append(True)
        return base64.b64encode(b"p" * 32).decode()
    def consume(challenge, caller, slot):
        if caller != "independent.app" or slot != "primary" or challenge not in proof:
            return False
        proof.remove(challenge)
        return True
    provider = SimpleNamespace(profileDirectory=lambda: str(root), ownerCaller=lambda: "independent.app",
        profileKey=profile_key, catalogKey=lambda: base64.b64encode(b"m" * 32).decode(),
        consumeAuthorization=consume)
    assert json.loads(mobile_bridge.initialize_app_owned_host(provider))["ok"]
    def request(operation, params=None, key=None, caller="independent.app", scope="owner"):
        value = {"api_version": 1, "request_id": "ordinary:mobile", "operation": operation,
            "params": params or {}}
        if key is not None: value["idempotency_key"] = key
        reply = mobile_bridge.core_exchange(caller, base64.b64encode(encode_frame(value)).decode(), scope)
        return decode_frame(base64.b64decode(reply))
    yield SimpleNamespace(provider=provider, loads=loads, proof=proof, request=request, root=root,
        profile=request("runtime.capabilities")["result"]["profiles"][0])


def test_normal_mobile_host_is_empty_and_public_core_has_no_private_native_port(ordinary):
    r = ordinary
    service = mobile_bridge._service
    assert service._identity is None and service.store.list("contact") == []
    assert not service.settings.nearby_discovery and not service.settings.lan_fallback
    assert service._direct_native is None and mobile_bridge._native_channel is None
    capabilities = r.request("runtime.capabilities")["result"]
    assert "profile.create" in capabilities["operations"]
    assert "native.command" not in capabilities["operations"]
    assert not r.request("native.command", {"command": "create_profile", "payload": {}})["ok"]
    assert service._identity is None
    assert r.request("profile.create", {"display_name": "Independent"}, str(uuid4()))["ok"]
    assert service._identity is not None and service.store.list("contact") == []
    assert json.loads(mobile_bridge.direct_exchange('{"responses":[]}'))["result"] == []


def test_registered_cold_start_stays_locked_without_reading_profile_key_or_rust_pump(ordinary):
    r = ordinary
    assert r.request("profile.create", {"display_name": "Independent"}, str(uuid4()))["ok"]
    identity = mobile_bridge._service._identity.hash.hex()
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert json.loads(mobile_bridge.initialize_app_owned_host(r.provider)) == {
        "ok": False, "error": {"code": "locked"}}
    assert r.loads == [True] and mobile_bridge._service is None
    assert r.request("runtime.capabilities")["ok"]
    challenge = json.loads(mobile_bridge.begin_profile_unlock_auth(r.profile))["result"]["challenge"]
    r.proof.add(challenge)
    token = json.loads(mobile_bridge.complete_profile_unlock_auth(challenge))["result"]["credential_handle"]
    assert r.request("profile.unlock", {"profile": r.profile, "credential_handle": token}, str(uuid4()))["ok"]
    assert r.loads == [True, True] and mobile_bridge._service._identity.hash.hex() == identity


def test_owner_uid_cannot_be_borrowed_or_switched_to_original_mesh_host(ordinary):
    r = ordinary
    assert r.request("runtime.capabilities", caller="other.app")["error"]["code"] == "forbidden"
    assert not json.loads(mobile_bridge.initialize_native_host(r.provider))["ok"]
    assert mobile_bridge._profile_host.public_only
    external = r.request("runtime.capabilities", caller="signed.consumer", scope="consumer")
    assert external["ok"] and "profile.create" not in external["result"]["operations"]
    assert "native.command" not in external["result"]["operations"]


def test_reopening_waits_for_actual_prior_native_allocation_ack(ordinary):
    r = ordinary
    assert json.loads(mobile_bridge.lock_profile_host())["ok"]
    native_webrtc_host.android_host().resourceAccounting = lambda: json.dumps(
        {"ok": True, "result": {"complete": True, "reserved_count": 1}})
    challenge = json.loads(mobile_bridge.begin_profile_unlock_auth(r.profile))["result"]["challenge"]
    r.proof.add(challenge)
    token = json.loads(mobile_bridge.complete_profile_unlock_auth(challenge))["result"]["credential_handle"]
    assert not r.request("profile.unlock", {"profile": r.profile, "credential_handle": token}, str(uuid4()))["ok"]
    assert mobile_bridge._service is None and mobile_bridge._opening_channel is None


def test_startup_publication_cannot_expose_the_legacy_native_port(ordinary, monkeypatch):
    from mesh_chat import mobile_profile_host
    r = ordinary
    assert json.loads(mobile_bridge.shutdown())["ok"]
    monkeypatch.setattr(r.provider, "profileDirectory",
        lambda: str(r.root.parent.parent / "second" / "mesh-core-runtime" / "profile-v1"))
    constructor = mobile_profile_host.NativeMobileProfileHost
    observed = []
    def inspect_publication(*args, **kwargs):
        assert mobile_bridge._service is not None and mobile_bridge._profile_host is None
        observed.append(r.request("runtime.capabilities"))
        return constructor(*args, **kwargs)
    monkeypatch.setattr(mobile_profile_host, "NativeMobileProfileHost", inspect_publication)
    assert json.loads(mobile_bridge.initialize_app_owned_host(r.provider))["ok"]
    assert len(observed) == 1 and observed[0]["error"]["code"] == "unavailable"
    assert "native.command" not in r.request("runtime.capabilities")["result"]["operations"]


def test_failed_install_retains_metadata_key_until_close_ack(ordinary, mobile_request, monkeypatch):
    from mesh_chat import mobile_profile_host
    r = ordinary
    assert json.loads(mobile_bridge.shutdown())["ok"]
    monkeypatch.setattr(r.provider, "profileDirectory",
        lambda: str(r.root.parent.parent / "second" / "mesh-core-runtime" / "profile-v1"))
    stores, release = [], []
    vault = mobile_bridge.VaultStore
    def catalog(*args, **kwargs):
        store = vault(*args, **kwargs)
        if store.profile_dir.name != "host-v1":
            return store
        close = store.close
        def blocked_close():
            if not release:
                raise OSError("metadata cleanup pending")
            close()
        store.close = blocked_close
        stores.append(store)
        return store
    def failed_install(*args, **kwargs):
        assert mobile_bridge._service is not None
        raise OSError("host installation failed")
    monkeypatch.setattr(mobile_bridge, "VaultStore", catalog)
    monkeypatch.setattr(mobile_profile_host, "NativeMobileProfileHost", failed_install)
    try:
        assert not json.loads(mobile_bridge.initialize_app_owned_host(r.provider))["ok"]
        assert len(stores) == 1 and mobile_bridge._retiring_catalog is stores[0]
        assert stores[0]._key is not None
        assert mobile_bridge._service is None and mobile_bridge._retiring_service is None
        assert not json.loads(mobile_bridge.initialize_native(mobile_request))["ok"]
        assert not json.loads(mobile_bridge.shutdown())["ok"]
        assert mobile_bridge._retiring_catalog is stores[0] and stores[0]._key is not None
        assert not json.loads(mobile_bridge.initialize_app_owned_host(r.provider))["ok"]
        assert len(stores) == 1
    finally:
        release.append(True)
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert stores[0]._key is None and mobile_bridge._retiring_catalog is None
