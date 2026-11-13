"""Keyed profile creation on a real empty vault with trusted host authority."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import json
import time
import uuid
import socket

import pytest
import RNS

from mesh_chat.core_api import android_host, host
from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import StorageUnavailable
from mesh_chat.invitations import create_invitation
from mesh_chat.remote import create_profile_document, create_remote_personal_invitation
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@pytest.fixture
def empty_host(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    key = os.urandom(32)
    opened = []

    def open_service():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, lambda _: None)
        opened.append(service)
        return service

    android_host.close_all()
    yield open_service
    android_host.close_all()
    for service in opened:
        service.close()


def exchange(session, operation, params=None, key=None):
    value = {"api_version": 1, "request_id": "bootstrap:1", "operation": operation,
             "params": {} if params is None else params}
    if key is not None:
        value["idempotency_key"] = key
    return decode_frame(session.exchange(encode_frame(value)))


def bootstrap(service, caller="mesh-chat-application"):
    session = host.bind_host_stream(service, caller=caller,
        permissions=host.OWNER_PERMISSIONS | {"profile_owner"}, scope="owner",
        private_profile_bootstrap=True)
    assert exchange(session, "runtime.capabilities")["ok"]
    return session


def create(session, name="Alex", key="profile-creation-key"):
    return exchange(session, "profile.create", {"display_name": name}, key)


def test_profile_create_is_atomic_and_replay_survives_restart(empty_host):
    service = empty_host()
    assert service._identity is None
    session = bootstrap(service)
    reply = create(session)
    assert reply["ok"] and reply["result"] == {"display_name": "Alex"}
    identity = service.store.get("identity", "local")
    assert service.store.get("profile", "local")["display_name"] == "Alex"
    assert service.store.get("settings", "network") is not None
    assert len(service.store.list("workspace_operation")) == 1
    assert create(session) == reply
    assert create(session, "Different")["error"]["code"] == "idempotency_conflict"
    service.close()
    reopened = empty_host()
    assert create(bootstrap(reopened)) == reply
    assert reopened.store.get("identity", "local") == identity
    assert len(reopened.store.list("workspace_operation")) == 1


def test_failed_atomic_profile_write_leaves_no_identity_or_receipt(empty_host, monkeypatch):
    service = empty_host()
    session = bootstrap(service)
    original = service.store._write_records_locked
    network_starts = []
    monkeypatch.setattr(service, "_start_network", lambda *_: network_starts.append(True))

    def fail_after_writes(*args):
        original(*args)
        raise OSError("injected profile transaction failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail_after_writes)
    assert create(session)["error"]["code"] == "unavailable"
    assert service._identity is None
    for kind in ("identity", "profile", "workspace_operation"):
        assert service.store.list(kind) == []
    assert network_starts == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    assert create(session)["ok"]
    assert network_starts == [True]


def test_post_commit_network_failure_does_not_duplicate_profile_creation(empty_host, monkeypatch):
    service = empty_host()
    session = bootstrap(service)

    def fail_network(*_):
        raise StorageUnavailable("injected after profile commit")

    monkeypatch.setattr(service, "_start_network", fail_network)
    assert create(session)["error"]["code"] == "unavailable"
    identity = service.store.get("identity", "local")
    assert identity is not None and service.store.get("profile", "local") is not None
    assert create(session)["ok"]
    service.close()
    reopened = empty_host()
    assert create(bootstrap(reopened))["ok"]
    assert reopened.store.get("identity", "local") == identity


@pytest.mark.parametrize("revocation", ["permission", "scope", "caller", "closed"])
def test_profile_replay_rechecks_bootstrap_authority(empty_host, revocation):
    service = empty_host()
    grants = [Grant("trusted-app", frozenset({"observe", "profile_owner"}), ("local",))]
    session = bind_service_stream(service, lambda: grants[0], private_profile_bootstrap=True)
    assert exchange(session, "runtime.capabilities")["ok"]
    assert create(session)["ok"]
    if revocation == "permission":
        grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    elif revocation == "scope":
        grants[0] = replace(grants[0], profiles=())
    elif revocation == "caller":
        grants[0] = replace(grants[0], caller="other-app")
    else:
        service._shutdown.set()
    assert create(session)["error"]["code"] in {"forbidden", "unauthenticated"}


def test_public_owner_cannot_request_profile_bootstrap(empty_host):
    service = empty_host()
    session = host.bind_host_stream(service, caller="external-owner",
                                    permissions=host.OWNER_PERMISSIONS, scope="owner")
    capabilities = exchange(session, "runtime.capabilities")
    assert "profile.create" not in capabilities["result"]["operations"]
    assert create(session)["error"]["code"] == "unsupported_operation"
    with pytest.raises(ValueError):
        host.host_grant("external-owner", ("profile_owner",), scope="owner")
    with pytest.raises(ValueError):
        host.bind_host_stream(service, caller="external-consumer", permissions=("observe",),
                               private_profile_bootstrap=True)
    assert service.store.get("profile", "local") is None


def test_concurrent_bootstrap_sessions_converge_on_one_identity(empty_host):
    service = empty_host()
    sessions = [bootstrap(service), bootstrap(service)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(create, sessions))
    assert replies[0] == replies[1] and replies[0]["ok"]
    assert len(service.store.list("identity")) == len(service.store.list("workspace_operation")) == 1


def test_android_actual_owner_binding_can_bootstrap_an_existing_empty_service(empty_host):
    service = empty_host()
    caller = "com.meshchat.application"
    capabilities = {"api_version": 1, "request_id": "bootstrap:1",
                    "operation": "runtime.capabilities", "params": {}}
    assert decode_frame(android_host.exchange(service, caller, encode_frame(capabilities), "owner"))["ok"]
    value = {"api_version": 1, "request_id": "bootstrap:2", "operation": "profile.create",
             "params": {"display_name": "Android Alex"}, "idempotency_key": "android-create-key"}
    reply = decode_frame(android_host.exchange(service, caller, encode_frame(value), "owner"))
    assert reply["ok"], reply
    assert decode_frame(android_host.exchange(service, caller, encode_frame(value), "owner")) == reply
    assert service.store.get("profile", "local")["display_name"] == "Android Alex"


def test_verification_only_previews_do_not_create_profile_or_mutate_vault(empty_host, tmp_path, monkeypatch):
    signer_store = VaultStore(tmp_path / "signer", os.urandom(32), allow_unprotected_for_tests=True)
    signer = MeshChatService(signer_store, tmp_path / "signer", lambda _: None)
    signer.create_profile("Blair")
    workspace = signer.create_workspace(str(uuid.uuid4()), "Signed Team", "Preview only")
    invitation = signer.create_workspace_invitation_command(workspace["id"], str(uuid.uuid4()))
    device_link = signer.create_workspace_device_link(workspace["id"], str(uuid.uuid4()))
    personal = create_invitation(RNS.Identity(), "Blair")["file"]
    i2p = signer.invitation(connection_mode="i2p", i2p_access_point="a" * 52 + ".b32.i2p")["file"]
    remote = create_remote_personal_invitation(signer._identity, signer.invitation()["file"],
        create_profile_document("Relay", [{"host": "relay.example", "port": 4242}]))
    signer.close()
    service = empty_host()
    session = bootstrap(service)
    before = service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()

    def forbidden(*_, **__):
        raise AssertionError("Verification-only preview attempted an effect")

    monkeypatch.setattr(service.store, "_write_records_locked", forbidden)
    monkeypatch.setattr(service, "_start_network", forbidden)
    monkeypatch.setattr(service, "approve_participant_access", forbidden)
    monkeypatch.setattr(service, "_approve_remote_document", forbidden)
    monkeypatch.setattr(service, "_adopt_i2p_access_point", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for kind, document, field, expected in [
        ("personal", personal, "display_name", "Blair"),
        ("workspace", invitation["text"], "name", "Signed Team"),
        ("device_link", device_link["text"], "name", "Signed Team"),
    ]:
        reply = exchange(session, "bootstrap.preview", {"kind": kind, "document": document})
        assert reply["ok"], reply
        assert reply["result"]["kind"] == kind
        assert reply["result"]["preview"][field] == expected
        assert "workspace_id" not in reply["result"]["preview"]
    for document, consent in [(i2p, "requires_i2p_consent"), (remote, "requires_network_consent")]:
        reply = exchange(session, "bootstrap.preview", {"kind": "personal", "document": document})
        assert reply["ok"] and reply["result"]["preview"][consent] is True, reply
    assert service._identity is None and service.store.get("profile", "local") is None
    assert service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before


def test_pre_profile_preview_rejects_expired_tampered_and_over_budget_documents(empty_host):
    service = empty_host()
    session = bootstrap(service)
    identity = RNS.Identity()
    expired = create_invitation(identity, "Expired", now=int(time.time()) - 120,
                                lifetime_seconds=60)["file"]
    valid = json.loads(create_invitation(identity, "Blair")["file"])
    valid["display_name"] = "Tampered"
    for document in (expired, json.dumps(valid), "x" * (1048576 + 1)):
        reply = exchange(session, "bootstrap.preview", {"kind": "personal", "document": document})
        assert reply["error"]["code"] == "invalid_request", reply
    public = host.bind_host_stream(service, caller="external-owner",
                                    permissions=host.OWNER_PERMISSIONS, scope="owner")
    assert exchange(public, "runtime.capabilities")["ok"]
    denied = exchange(public, "bootstrap.preview", {"kind": "personal", "document": expired})
    assert denied["error"]["code"] == "unsupported_operation"
