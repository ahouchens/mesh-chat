"""Workspace consent parents commit child records and receipts atomically."""

import json
from uuid import uuid4

import pytest
import RNS

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.remote import create_profile_document, new_profile_record
from test_reconnect_prepared_mutations import prepared_pair, rows
from test_workspace_service import _deliver_all, _flush, _service
from test_core_messages import host


def client(service):
    session = bind_service_stream(service, lambda: Grant(
        "consent-parent", frozenset({"observe", "read", "send", "approve"}), ("local",)))

    def exchange(operation, key=None, **params):
        value = {"api_version": 1, "request_id": "consent:1", "operation": operation, "params": params}
        if key is not None:
            value["idempotency_key"] = key
        return json.loads(session.exchange(json.dumps(value).encode() + b"\n"))

    profile = exchange("runtime.capabilities")["result"]["profiles"][0]
    workspace = exchange("workspace.query", profile=profile)["result"]["workspaces"][0]["workspace"]
    return exchange, {"profile": profile, "workspace": workspace}


def recommendation(owner, network, member, workspace):
    profile = create_profile_document("Consent relay", [{"host": "93.184.216.34", "port": 4242}])
    owner.store.put("remote_profile", profile["id"], new_profile_record(
        profile, origin="manual", scope_kind="manual", scope_id=profile["id"]))
    document = owner.create_workspace_access_recommendation(workspace["id"], profile["id"], 7)["text"]
    owner.send_workspace_access_recommendation(workspace["id"], document, str(uuid4()))
    _deliver_all(member, _flush(owner, network), source_profile=owner._require_profile(),
                 recipient_profile=member._require_profile())
    identifier = member.list_workspace_access_recommendations(workspace["id"])["recommendations"][0]["id"]
    return document, identifier, profile["id"]


@pytest.mark.parametrize("by_id", [False, True])
def test_access_parent_atomic_rollback_exact_retry_and_revocation(prepared_pair, monkeypatch, by_id):
    owner, network, member, workspace = prepared_pair
    document, identifier, profile_id = recommendation(owner, network, member, workspace)
    monkeypatch.setattr(member.network, "remote_profile_state",
        lambda *_: {"connected_endpoint_count": 0}, raising=False)
    monkeypatch.setattr(member.network, "apply_remote_profiles", lambda *_: None, raising=False)
    exchange, scope = client(member)
    params = {**scope, "action": "apply_by_id" if by_id else "apply", "consent": True,
              **({"recommendation_id": identifier} if by_id else {"recommendation": document})}
    before = rows(member.store)
    original = member.store._write_records_locked
    reconciles = []
    reconcile = member.reconcile_remote_profiles

    def observed():
        assert member.store.get("remote_profile", profile_id)
        assert len(member.store.list("workspace_operation")) > 0
        reconciles.append(True)
        reconcile()

    monkeypatch.setattr(member, "reconcile_remote_profiles", observed)

    def fail(*args):
        original(*args)
        raise OSError("injected consent parent failure")

    monkeypatch.setattr(member.store, "_write_records_locked", fail)
    reply = exchange("workspace.access_recommendation", "access-parent-key", **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(member.store) == before and reconciles == []
    monkeypatch.setattr(member.store, "_write_records_locked", original)
    reply = exchange("workspace.access_recommendation", "access-parent-key", **params)
    assert reply["ok"], reply
    assert (member.store.get("workspace_access_recommendation", identifier)["state"] == "applied") is by_id
    accepted = rows(member.store)
    assert exchange("workspace.access_recommendation", "access-parent-key", **params)["ok"]
    assert rows(member.store) == accepted and reconciles == [True]
    changed_document = owner.create_workspace_access_recommendation(workspace["id"], profile_id, 6)["text"]
    if not by_id:
        assert exchange("workspace.access_recommendation", "access-parent-key",
                        **{**params, "recommendation": changed_document})["error"]["code"] == "idempotency_conflict"
    changed = exchange("workspace.access_recommendation", "access-parent-key", **{**params, "consent": False})
    assert changed["ok"] is False
    member.remove_remote_profile(profile_id)
    assert exchange("workspace.access_recommendation", "access-parent-key", **params)["error"]["code"] == "forbidden"
    assert member.store.get("remote_profile", profile_id) is None


def test_reconnect_parent_rolls_back_device_capability_outbox_and_receipt(prepared_pair, monkeypatch):
    owner, _, _, _ = prepared_pair
    exchange, scope = client(owner)
    params = {**scope, "action": "reconnect_consent", "auto_reconnect": True,
              "allow_direct_ip_disclosure": False, "relay_consent_scope": "workspace"}
    before = rows(owner.store)
    original = owner.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected reconnect parent failure")

    monkeypatch.setattr(owner.store, "_write_records_locked", fail)
    reply = exchange("workspace.connection", "reconnect-parent-key", **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(owner.store) == before
    monkeypatch.setattr(owner.store, "_write_records_locked", original)
    reply = exchange("workspace.connection", "reconnect-parent-key", **params)
    assert reply["ok"], reply
    accepted = rows(owner.store)
    assert exchange("workspace.connection", "reconnect-parent-key", **params)["ok"]
    assert rows(owner.store) == accepted
    changed = exchange("workspace.connection", "reconnect-parent-key", **{**params, "auto_reconnect": False})
    assert changed["error"]["code"] == "idempotency_conflict", changed
    assert exchange("workspace.connection", "reconnect-newer-key", **{**params, "auto_reconnect": False})["ok"]
    replay = exchange("workspace.connection", "reconnect-parent-key", **params)
    assert replay["ok"] and replay["result"]["result"]["enabled"] is False, replay
    assert exchange("workspace.connection", "reconnect-session-key", **{**params, "relay_consent_scope": "session"})["ok"]
    invalid = exchange("workspace.connection", "reconnect-profile-key", **{**params, "relay_consent_scope": "profile"})
    assert invalid["error"]["code"] == "invalid_request", invalid


def test_access_committed_before_reconcile_failure_and_replays_after_reopen(host, monkeypatch):
    service = host()
    workspace = service.create_workspace(str(uuid4()), "Durable consent", "")
    remote = create_profile_document("Durable relay", [{"host": "93.184.216.34", "port": 4242}])
    service.store.put("remote_profile", remote["id"], new_profile_record(
        remote, origin="manual", scope_kind="manual", scope_id=remote["id"]))
    document = service.create_workspace_access_recommendation(workspace["id"], remote["id"], 7)["text"]
    exchange, scope = client(service)
    params = {**scope, "action": "apply", "recommendation": document, "consent": True}

    def fail():
        raise OSError("injected post-commit runtime failure")

    monkeypatch.setattr(service, "reconcile_remote_profiles", fail)
    first = exchange("workspace.access_recommendation", "durable-access-key", **params)
    assert first["error"]["code"] == "unavailable", first
    assert {"kind": "workspace", "id": workspace["id"]} in service.store.get("remote_profile", remote["id"])["scopes"]
    assert service.store.get("remote_runtime_intent", "transport")
    assert exchange("workspace.access_recommendation", "durable-access-key", **params)["ok"]
    record = service.store.get("remote_profile", remote["id"])
    record.update(connected_endpoints=2, path_available=True, ratchet_ready=True, propagation_available=True)
    service.store.put("remote_profile", record["id"], record)
    service.close()
    reopened = host()
    exchange, scope = client(reopened)
    replay = exchange("workspace.access_recommendation", "durable-access-key", **{**params, **scope})
    assert replay["ok"], replay
    projection = replay["result"]["result"]["profile"]
    assert projection["connected_endpoint_count"] == 0
    assert projection["path_available"] is projection["ratchet_ready"] is projection["offline_delivery_available"] is False
    assert len(reopened.store.list("remote_profile")) == 1


def test_contact_invitation_and_outbox_roll_back_and_replay_after_reopen(host, monkeypatch):
    service = host()
    service.create_workspace(str(uuid4()), "Contact invites", "")
    exchange, scope = client(service)
    params = {**scope, "action": "invite_contact", "contact_id": "internal-peer"}
    before = rows(service.store)
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected invite/outbox commit failure")

    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    reply = exchange("workspace.connection", "contact-invite-stable", **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(service.store) == before and service._direct_retry_snapshot() == []
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    reply = exchange("workspace.connection", "contact-invite-stable", **params)
    assert reply["ok"], reply
    invitation = service.store.list("workspace_invitation")[0]
    message = service.store.list("message")[0]
    assert invitation["delivery_message_id"] == message["id"]
    assert message["id"] in service._direct_retry_snapshot()
    assert exchange("workspace.connection", "contact-invite-stable", **params) == reply
    service.close()
    reopened = host()
    exchange, scope = client(reopened)
    replay = exchange("workspace.connection", "contact-invite-stable", **{**params, **scope})
    assert replay["ok"], replay
    assert len(reopened.store.list("message")) == len(reopened.store.list("workspace_invitation")) == 1
    contact = reopened.store.get("contact", "internal-peer")
    contact["trust"] = "blocked"
    reopened.store.put("contact", contact["id"], contact)
    assert exchange("workspace.connection", "contact-invite-stable", **{**params, **scope})["error"]["code"] == "forbidden"


def test_unchanged_role_commits_key_without_manifest_effect_and_survives_reopen(prepared_pair, monkeypatch):
    owner, _, member, workspace = prepared_pair
    exchange, scope = client(owner)
    members = exchange("workspace.members", **scope)["result"]["members"]
    params = {**scope, "member": next(item["member"] for item in members if item["role"] == "member"), "role": "member"}
    before = rows(owner.store)
    original = owner.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected no-op receipt failure")

    monkeypatch.setattr(owner.store, "_write_records_locked", fail)
    reply = exchange("workspace.member_role", "role-noop-stable-key", **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(owner.store) == before
    monkeypatch.setattr(owner.store, "_write_records_locked", original)
    manifests = owner.store.list("workspace_manifest")
    deliveries = owner.store.list("workspace_delivery")
    reply = exchange("workspace.member_role", "role-noop-stable-key", **params)
    assert reply["ok"], reply
    assert owner.store.list("workspace_manifest") == manifests
    assert owner.store.list("workspace_delivery") == deliveries
    identity, key, root = owner._identity, owner.store._key, owner.profile_dir
    owner.close()
    reopened, _ = _service(root, identity, "Alex", vault_key=key)
    reopened._shutdown.clear()
    try:
        exchange, scope = client(reopened)
        params.update(scope)
        assert exchange("workspace.member_role", "role-noop-stable-key", **params) == reply
        changed = exchange("workspace.member_role", "role-noop-stable-key", **{**params, "role": "admin"})
        assert changed["error"]["code"] == "idempotency_conflict", changed
        assert reopened.store.list("workspace_manifest") == manifests
    finally:
        reopened.close()


@pytest.mark.parametrize("remove_member", [False, True])
def test_contact_invite_preserves_signed_manifest_capacity(host, tmp_path, remove_member):
    owner = host()
    workspace = owner.create_workspace(str(uuid4()), "Full invitation bound", "")
    for index in range(7):
        member, network = _service(tmp_path / f"capacity-member-{index}", RNS.Identity(), f"Member {index}")
        try:
            document = owner.create_workspace_invitation_command(workspace["id"], str(uuid4()))["text"]
            member.submit_workspace_join(document, str(uuid4()))
            _deliver_all(owner, _flush(member, network), source_profile=member._require_profile(),
                recipient_profile=owner._require_profile())
            request = next(item for item in owner.store.list("workspace_join_request") if item["state"] == "pending")
            owner.approve_workspace_join(workspace["id"], request["id"], str(uuid4()))
        finally:
            member.close()
    if remove_member:
        manifest = owner._workspace_current_manifest(owner._require_workspace(workspace["id"]))
        target = next(item for item in manifest.members if item.role.value != "owner")
        owner.remove_workspace_member(workspace["id"], target.member_id, str(uuid4()))
    before = rows(owner.store)
    exchange, scope = client(owner)
    reply = exchange("workspace.connection", "full-contact-invite-key", **scope,
        action="invite_contact", contact_id="internal-peer")
    assert reply["error"]["code"] == "invalid_request", reply
    assert rows(owner.store) == before
