"""Actual encrypted Core/lifecycle; OS key and auth boundary are explicit doubles."""
import base64
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import NativeUnavailable
from mesh_chat.mobile_profile_host import NativeMobileProfileHost, native_key
from mesh_chat.vault import VaultStore
from test_pairing_runtime import native_pairing


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


@pytest.mark.parametrize("value", [None, "bad", "A" * 65, base64.b64encode(b"short").decode()])
def test_native_key_decoder_never_accepts_partial_unbounded_or_non_native_key(value):
    with pytest.raises(NativeUnavailable):
        native_key(value)
