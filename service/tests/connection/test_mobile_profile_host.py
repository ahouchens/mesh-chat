"""Actual encrypted Core/lifecycle; OS key and auth boundary are explicit doubles."""
import base64
import hashlib
import hmac
import json
import os
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import NativeUnavailable
from mesh_chat.mobile_profile_host import NativeMobileProfileHost, native_key
from mesh_chat.vault import VaultStore
from test_pairing_runtime import native_pairing
from test_mobile_bootstrap import mobile_request
from mesh_chat import mobile_bridge
from mesh_chat.service import MeshChatService


@pytest.fixture
def platform_host(native_pairing, tmp_path):
    create, _ = native_pairing
    root = tmp_path / "mesh-chat" / "profile-v1"
    active, _, _, _, _, key = create(root)
    loads, proof, published, events, clock = [], set(), [], [], [100.0]
    def fresh():
        loads.append(True)
        return base64.b64encode(key).decode()
    def consume(challenge, caller, slot):
        if challenge not in proof or caller != "app.owner" or slot != "primary":
            return False
        proof.remove(challenge)
        return True
    provider = SimpleNamespace(profileDirectory=lambda: str(root), ownerCaller=lambda: "app.owner",
                               profileKey=fresh, consumeAuthorization=consume)
    meta_key = os.urandom(32)
    meta_root = tmp_path / "mesh-chat" / "host-v1"
    meta = VaultStore(meta_root, meta_key, allow_unprotected_for_tests=True)
    def build(active_service, store=meta):
        return NativeMobileProfileHost(provider, store, active=active_service,
            open_profile=lambda directory, raw_key: create(directory, raw_key)[0],
            publish=published.append, emit=events.append, now=lambda: clock[0])
    host = build(active)
    def request(operation, params=None, key=None, caller="app.owner", scope="owner", target=host):
        frame = {"api_version": 1, "request_id": "mobile:test", "operation": operation, "params": params or {}}
        if key is not None:
            frame["idempotency_key"] = key
        return decode_frame(target.exchange(caller, encode_frame(frame), scope))
    yield SimpleNamespace(host=host, provider=provider, active=active, meta=meta, loads=loads, proof=proof,
                          published=published, events=events, clock=clock, build=build, request=request,
                          meta_root=meta_root, meta_key=meta_key)
    host.close()


def negotiate(r):
    response = r.request("runtime.capabilities")
    assert response["ok"], response
    return response["result"]["profiles"][0]


def credential(r):
    challenge = r.host.begin_authentication(r.host.context()["profile"])["challenge"]
    r.proof.add(challenge)
    return r.host.complete_authentication(challenge)["credential_handle"]


def test_actual_runtime_catalog_survives_profile_close_and_unlock_reads_original_key_provider_afresh(platform_host):
    r = platform_host
    profile = negotiate(r)
    assert "profile.catalog" in r.request("runtime.capabilities")["result"]["operations"]
    assert r.loads == []
    r.host.lock()
    assert r.active._store_closed and r.active._identity is None
    assert r.host.context()["state"] == "locked" and r.meta._key is not None
    assert r.request("profile.catalog")["ok"]
    assert r.request("profile.query", {"profile": profile})["error"]["code"] == "locked"
    token = credential(r)
    unlocked = r.request("profile.unlock", {"profile": profile, "credential_handle": token}, str(uuid4()))
    assert unlocked["ok"], unlocked
    assert r.loads == [True] and r.published[-1] is r.host.core.lifecycle.active
    assert r.request("runtime.capabilities")["result"]["profiles"] == [profile]
    assert all("vault_key" not in str(event) and "primary" not in str(event) for event in r.events)
    assert {event["state"] for event in r.events} >= {"unlocked", "locked"}


def test_registered_cold_runtime_reopens_catalog_without_opening_a_profile_or_loading_profile_key(platform_host):
    r = platform_host
    original_context = r.host.context()
    r.host.close()
    reopened_meta = VaultStore(r.meta_root, r.meta_key, allow_unprotected_for_tests=True)
    reopened = r.build(None, reopened_meta)
    try:
        assert r.loads == [] and reopened.core.lifecycle.active is None
        assert reopened.context()["state"] == "locked"
        assert reopened.context()["profile"] == original_context["profile"]
        assert reopened.context()["host_generation"] != original_context["host_generation"]
        reply = r.request("runtime.capabilities", target=reopened)
        assert reply["ok"] and "profile.unlock" in reply["result"]["operations"]
    finally:
        reopened.close()


@pytest.mark.parametrize("fault", ["unverified", "expired", "changed_revision", "cancelled", "wrong_profile"])
def test_native_authentication_proof_is_required_current_bounded_and_bound_to_authorized_profile(platform_host, fault):
    r = platform_host
    profile = negotiate(r)
    r.host.lock()
    if fault == "wrong_profile":
        with pytest.raises(ApiFailure):
            r.host.begin_authentication("another-profile")
        return
    challenge = r.host.begin_authentication(profile)["challenge"]
    r.proof.add(challenge)
    if fault == "unverified": r.proof.clear()
    elif fault == "expired": r.clock[0] += 61
    elif fault == "changed_revision": r.host.lock()
    else: r.host.cancel_authentication(challenge)
    with pytest.raises(ApiFailure):
        r.host.complete_authentication(challenge)
    assert not r.loads


def test_credential_proof_and_public_token_are_each_single_use_and_cannot_cross_binder_callers(platform_host):
    r = platform_host
    profile = negotiate(r)
    r.host.lock()
    challenge = r.host.begin_authentication(profile)["challenge"]
    r.proof.add(challenge)
    token = r.host.complete_authentication(challenge)["credential_handle"]
    with pytest.raises(ApiFailure):
        r.host.complete_authentication(challenge)
    assert r.request("runtime.capabilities", caller="other.app")["error"]["code"] == "forbidden"
    assert r.request("runtime.capabilities", caller="other.app", scope="consumer")["ok"]
    assert r.request("profile.unlock", {"profile": profile, "credential_handle": token}, str(uuid4()),
                     caller="other.app", scope="consumer")["error"]["code"] == "forbidden"
    assert not r.loads


def test_provider_recreation_keeps_slot_binding_but_invalidates_unfinished_native_auth(platform_host):
    r = platform_host
    challenge = r.host.begin_authentication(r.host.context()["profile"])["challenge"]
    r.host.rebind(r.provider)
    with pytest.raises(ApiFailure):
        r.host.complete_authentication(challenge)
    with pytest.raises(NativeUnavailable):
        r.host.rebind(SimpleNamespace(profileDirectory=lambda: str(r.host.directory), ownerCaller=lambda: "different.app"))


def test_lifecycle_change_during_native_credential_issue_cannot_return_token_for_new_revision(platform_host, monkeypatch):
    r = platform_host
    r.host.lock()
    challenge = r.host.begin_authentication(r.host.context()["profile"])["challenge"]
    r.proof.add(challenge)
    original = r.host.core.issue_unlock_credential
    def changed(*args, **kwargs):
        token = original(*args, **kwargs)
        r.host.lock()
        return token
    monkeypatch.setattr(r.host.core, "issue_unlock_credential", changed)
    with pytest.raises(ApiFailure, match="resync_required"):
        r.host.complete_authentication(challenge)
    assert not r.loads


def test_native_lock_retains_one_admitted_key_and_reports_pending_until_actual_worker_drain(platform_host):
    r = platform_host
    released = Event()
    r.active._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
    try:
        with pytest.raises(ApiFailure):
            r.host.lock()
        admitted = r.host._native_lock_key
        assert admitted is not None and r.active.store._key is not None
        with pytest.raises(ApiFailure):
            r.host.lock()
        assert r.host._native_lock_key == admitted
        released.set()
        r.active._close_finalizer.join(3)
        assert r.host.lock()["state"] == "locked"
        assert r.host._native_lock_key is None and r.active.store._key is None
    finally:
        released.set()


@pytest.mark.parametrize("value", [None, "bad", "A" * 65, base64.b64encode(b"short").decode()])
def test_native_key_decoder_never_accepts_partial_unbounded_or_non_native_key(value):
    with pytest.raises(NativeUnavailable):
        native_key(value)


@pytest.fixture
def installed_mobile_host(mobile_request, tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    root = tmp_path / "files" / "mesh-chat" / "profile-v1"
    key = b"b" * 32
    loads, proof = [], set()
    def fresh():
        loads.append(True)
        return base64.b64encode(key).decode()
    def consume(challenge, caller, slot):
        if challenge not in proof or caller != "app.owner" or slot != "primary":
            return False
        proof.remove(challenge)
        return True
    provider = SimpleNamespace(profileDirectory=lambda: str(root), ownerCaller=lambda: "app.owner", profileKey=fresh,
        catalogKey=lambda: base64.b64encode(hmac.new(key, b"mesh-chat:profile-host-catalog:v1", hashlib.sha256).digest()).decode(),
        consumeAuthorization=consume)
    assert json.loads(mobile_bridge.initialize_native_host(provider, "Synthetic"))["ok"]
    def request(operation, params=None, operation_key=None, caller="app.owner", scope="owner"):
        value = {"api_version": 1, "request_id": "native:test", "operation": operation, "params": params or {}}
        if operation_key is not None:
            value["idempotency_key"] = operation_key
        raw = mobile_bridge.core_exchange(caller, base64.b64encode(encode_frame(value)).decode(), scope)
        return decode_frame(base64.b64decode(raw))
    capabilities = request("runtime.capabilities")
    assert capabilities["ok"], capabilities
    return SimpleNamespace(provider=provider, loads=loads, proof=proof, root=root, request=request,
                           profile=capabilities["result"]["profiles"][0], legacy_request=mobile_request)


def test_actual_mobile_binder_route_uses_runtime_core_while_locked_and_reopens_only_after_native_auth(installed_mobile_host):
    r = installed_mobile_host
    original, emitter = mobile_bridge._service, mobile_bridge._service.emit
    identity = original._identity.hash.hex()
    assert "profile.catalog" in r.request("runtime.capabilities")["result"]["operations"]
    assert json.loads(mobile_bridge.lock_profile_host())["result"]["state"] == "locked"
    assert original._store_closed and original.store._key is None
    assert mobile_bridge._service is None and mobile_bridge._profile_host is not None
    assert r.request("profile.catalog")["ok"]
    assert not json.loads(mobile_bridge.initialize_native(r.legacy_request))["ok"]
    challenge = json.loads(mobile_bridge.begin_profile_unlock_auth(r.profile))["result"]["challenge"]
    r.proof.add(challenge)
    token = json.loads(mobile_bridge.complete_profile_unlock_auth(challenge))["result"]["credential_handle"]
    unlocked = r.request("profile.unlock", {"profile": r.profile, "credential_handle": token}, str(uuid4()))
    assert unlocked["ok"], unlocked
    assert r.loads == [True, True]
    assert mobile_bridge._service is not original and mobile_bridge._service._identity.hash.hex() == identity
    assert mobile_bridge._service._connection_policy == "shared-native"
    assert r.request("runtime.capabilities")["result"]["profiles"] == [r.profile]
    mobile_bridge.drain_events()
    emitter({"type": "event", "event": "old-service-private"})
    assert json.loads(mobile_bridge.drain_events())["result"] == []


def test_actual_mobile_cold_catalog_init_stays_locked_without_profile_key_read_or_initializer_fallback(installed_mobile_host):
    r = installed_mobile_host
    original_generation = mobile_bridge._profile_host.context()["host_generation"]
    assert json.loads(mobile_bridge.shutdown())["ok"]
    assert mobile_bridge._profile_host is None
    reopened = json.loads(mobile_bridge.initialize_native_host(r.provider))
    assert reopened == {"ok": False, "error": {"code": "locked"}}
    assert mobile_bridge._service is None and r.loads == [True]
    assert mobile_bridge._profile_host.context()["host_generation"] != original_generation
    assert r.request("runtime.capabilities")["ok"]
    assert r.request("profile.catalog")["ok"]


def test_actual_mobile_native_auth_cannot_be_borrowed_by_other_binder_caller_or_renderer_command(installed_mobile_host):
    r = installed_mobile_host
    assert r.request("runtime.capabilities", caller="different.app")["error"]["code"] == "forbidden"
    assert json.loads(mobile_bridge.begin_profile_unlock_auth("another-profile"))["error"]["code"] == "forbidden"
    response = json.loads(mobile_bridge.command(json.dumps({"command": "begin_profile_unlock_auth", "payload": {"profile": r.profile}})))
    assert not response["ok"]
    from mesh_chat.core_api.native_commands import NATIVE_COMMANDS
    assert "begin_profile_unlock_auth" not in NATIVE_COMMANDS


def test_actual_mobile_failed_open_retains_unpublished_native_response_channel_until_host_shutdown_can_drain(installed_mobile_host, monkeypatch):
    from mesh_chat.service import NativeStartupIncomplete
    r = installed_mobile_host
    assert json.loads(mobile_bridge.lock_profile_host())["ok"]
    original = mobile_bridge.MeshChatService
    released, opened = Event(), []
    def incomplete(*args, **kwargs):
        service = original(*args, **kwargs)
        opened.append(service)
        service._pending_contact_carriers = {"pending": SimpleNamespace(close=lambda: None, wait=released.wait)}
        raise NativeStartupIncomplete(service)
    monkeypatch.setattr(mobile_bridge, "MeshChatService", incomplete)
    challenge = json.loads(mobile_bridge.begin_profile_unlock_auth(r.profile))["result"]["challenge"]
    r.proof.add(challenge)
    token = json.loads(mobile_bridge.complete_profile_unlock_auth(challenge))["result"]["credential_handle"]
    try:
        assert not r.request("profile.unlock", {"profile": r.profile, "credential_handle": token}, str(uuid4()))["ok"]
        retiring, = opened
        assert mobile_bridge._service is None and mobile_bridge._retiring_service is retiring
        assert mobile_bridge._retiring_channel is retiring._mobile_channel
        assert retiring.store._key is not None and not json.loads(mobile_bridge.shutdown())["ok"]
        released.set()
        retiring._close_finalizer.join(3)
        assert json.loads(mobile_bridge.shutdown())["ok"]
        assert retiring.store._key is None and mobile_bridge._retiring_service is None
        assert mobile_bridge._profile_host is None
    finally:
        released.set()
