"""Prepared parent mutations: real vaults, signed manifests/capabilities, no transport qualification."""

from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, IdentityMismatch, ValidationError
from mesh_chat.reconnect import verify_connection_capabilities
from mesh_chat.remote import create_profile_document
from mesh_chat.workspace_reconnect import create_workspace_reconnect_capability

from test_workspace_service import _joined_pair, _service


@pytest.fixture
def prepared_pair(tmp_path):
    owner, network, _, member, _, _, workspace, _, _ = _joined_pair(tmp_path, base=87000)
    owner._shutdown.clear()
    member._shutdown.clear()
    yield owner, network, member, owner._require_workspace(workspace["id"])
    owner.close()
    member.close()


def peer_for(service, workspace):
    manifest = service._workspace_current_manifest(workspace)
    member = next(member for member in manifest.members if member.member_id != workspace["local_member_id"])
    device = member.devices[0]
    identifier = service._workspace_reconnect_peer_id(workspace["id"], member.member_id, device.device_id)
    return identifier, member, device


def rows(store):
    return store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()


def forbid_writes(monkeypatch, store):
    def fail(*args, **kwargs):
        pytest.fail("Preparation must not write the vault")
    for method in ("put", "put_many", "put_and_delete", "commit_operation"):
        monkeypatch.setattr(store, method, fail)


def prepare_consent(service, workspace):
    peer, member, device = peer_for(service, workspace)
    records = {}
    profile = service._prepare_reconnect_profile_for_contact(peer, device.device_id, records=records)
    profile.update(scope_kind="workspace", workspace_id=workspace["id"],
        workspace_name=workspace["name"], peer_member_id=member.member_id,
        peer_display_name=member.display_name, auto_reconnect=True,
        allow_direct_ip_disclosure=False, relay_consent_scope="workspace")
    contact = service._workspace_reconnect_contact(peer)
    service._prepare_reconnect_local_capabilities(profile, contact, rotate=True, records=records)
    wrapper = create_workspace_reconnect_capability(service._call_identity(), workspace_id=workspace["id"],
        manifest_digest=workspace["manifest_hash"], capability=profile["local_capabilities"])
    delivery = service._workspace_delivery_record(workspace_id=workspace["id"], recipient_member_id=member.member_id,
        recipient_device=device, kind="workspace_reconnect_capability", document=wrapper, priority=0)
    writes = [(kind, identifier, value) for (kind, identifier), value in records.items()]
    writes += [("workspace_delivery", delivery["id"], delivery), *service._due_records(add=[delivery])]
    return profile, writes, delivery


def test_workspace_consent_preparation_does_not_persist_device_profile_or_send(prepared_pair, monkeypatch):
    owner, network, _, workspace = prepared_pair
    before = rows(owner.store)
    sent = deepcopy(network.sent)
    forbid_writes(monkeypatch, owner.store)
    profile, writes, _ = prepare_consent(owner, workspace)
    checked = verify_connection_capabilities(profile["local_capabilities"])
    assert checked.device_id == profile["local_device_id"]
    assert checked.auto_reconnect and not checked.allow_direct_ip_disclosure
    assert checked.relay_consent_scope == "workspace"
    assert ("reconnect_device", "local") in {(kind, identifier) for kind, identifier, _ in writes}
    assert rows(owner.store) == before and network.sent == sent


def test_parent_commit_rolls_back_device_consent_outbox_due_and_receipt_together(prepared_pair, monkeypatch):
    owner, network, _, workspace = prepared_pair
    before = rows(owner.store)
    profile, writes, _ = prepare_consent(owner, workspace)
    operation = str(uuid4())
    original = owner.store._write_records_locked

    def fail_after_writes(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("failed before SQLite commit")

    sent = deepcopy(network.sent)
    monkeypatch.setattr(owner.store, "_write_records_locked", fail_after_writes)
    with pytest.raises(OSError):
        owner.store.commit_operation(operation, "a" * 64, {"profile": profile["id"]}, writes)
    assert rows(owner.store) == before and network.sent == sent
    monkeypatch.setattr(owner.store, "_write_records_locked", original)
    assert owner.store.commit_operation(operation, "a" * 64, {"profile": profile["id"]}, writes) == {"profile": profile["id"]}
    assert owner.store.get("reconnect_device", "local")["device_id"] == profile["local_device_id"]
    assert owner.store.get("reconnect_profile", profile["id"])["auto_reconnect"] is True


def test_parent_replay_after_reopen_reuses_exact_signed_capability_and_outbox(prepared_pair, tmp_path):
    owner, _, _, workspace = prepared_pair
    profile, writes, delivery = prepare_consent(owner, workspace)
    operation, digest = str(uuid4()), "b" * 64
    outcome = {"profile": profile["id"]}
    owner.store.commit_operation(operation, digest, outcome, writes)
    identity, key = owner._identity, owner.store._key
    owner.close()
    reopened, _ = _service(tmp_path / "owner", identity, "Alex", vault_key=key)
    reopened._shutdown.clear()
    try:
        before = rows(reopened.store)
        assert reopened.store.operation_result(operation, digest) == outcome
        assert reopened.store.commit_operation(operation, digest, outcome, writes) == outcome
        stored = reopened.store.get("reconnect_profile", profile["id"])
        assert stored["local_capabilities"] == profile["local_capabilities"]
        assert reopened.store.get("workspace_delivery", delivery["id"]) == delivery
        assert rows(reopened.store) == before
        with pytest.raises(ValidationError, match="already used with different input"):
            reopened.store.commit_operation(operation, "c" * 64, outcome, writes)
    finally:
        reopened.close()


def test_shared_prepared_write_set_reserves_one_device_and_preserves_exact_remote_devices(prepared_pair):
    owner, _, _, _ = prepared_pair
    contact_id = "prepared-contact"
    identity = RNS.Identity()
    owner.store.put("contact", contact_id, {"id": contact_id, "trust": "approved",
        "destination_hash": RNS.Destination.hash(identity, "lxmf", "delivery").hex()})
    records = {}
    first = owner._prepare_reconnect_profile_for_contact(contact_id, "device-one", records=records)
    second = owner._prepare_reconnect_profile_for_contact(contact_id, "device-two", records=records)
    assert first["id"] != second["id"]
    assert first["local_device_id"] == second["local_device_id"] == records["reconnect_device", "local"]["device_id"]
    assert first["remote_device_id"] == "device-one" and second["remote_device_id"] == "device-two"
    assert owner.store.get("reconnect_device", "local") is None
    assert owner.store.get("reconnect_profile", first["id"]) is None


def test_pending_profiles_count_toward_existing_capacity_bound(prepared_pair):
    owner, _, _, _ = prepared_pair
    owner.store.put("contact", "capacity-peer", {"id": "capacity-peer", "trust": "approved",
        "destination_hash": "ab" * 16})
    records = {("reconnect_profile", f"other-{index}"): {"id": f"other-{index}", "contact_id": f"other-{index}"}
               for index in range(63)}
    owner._prepare_reconnect_profile_for_contact("capacity-peer", "one", records=records)
    before = deepcopy(records)
    with pytest.raises(ValidationError, match="Too many"):
        owner._prepare_reconnect_profile_for_contact("capacity-peer", "two", records=records)
    assert records == before


def test_preference_migration_is_staged_and_preserves_explicit_opt_out(prepared_pair, monkeypatch):
    owner, _, _, _ = prepared_pair
    owner.store.put("contact", "legacy-peer", {"id": "legacy-peer", "trust": "approved", "destination_hash": "ab" * 16})
    legacy = owner._new_profile("legacy-peer", None)
    legacy.pop("auto_reconnect_preference")
    legacy.update(auto_reconnect=False, last_attempt_at=1)
    owner.store.put("reconnect_profile", legacy["id"], legacy)
    before = rows(owner.store)
    forbid_writes(monkeypatch, owner.store)
    records = {}
    prepared = owner._prepare_reconnect_profile_for_contact("legacy-peer", records=records)
    assert prepared["auto_reconnect"] is False and prepared["auto_reconnect_preference"] == "legacy_disabled"
    assert rows(owner.store) == before


@pytest.mark.parametrize("change", ["workspace_left", "wrong_device", "changed_identity"])
def test_reconnect_preparation_rechecks_current_scope_and_peer_binding(prepared_pair, change):
    owner, _, _, workspace = prepared_pair
    peer, _, device = peer_for(owner, workspace)
    records = {}
    profile = owner._prepare_reconnect_profile_for_contact(peer, device.device_id, records=records)
    contact = owner._workspace_reconnect_contact(peer)
    if change == "workspace_left":
        changed = dict(owner._require_workspace(workspace["id"]))
        changed["state"] = "left"
        owner.store.put("workspace", owner._workspace_record_id(workspace["id"]), changed)
    elif change == "wrong_device":
        profile["remote_device_id"] = "another-device"
    else:
        contact["destination_hash"] = "ff" * 16
    before = rows(owner.store)
    with pytest.raises((ContactNotApproved, IdentityMismatch)):
        owner._prepare_reconnect_local_capabilities(profile, contact, rotate=True, records=records)
    assert rows(owner.store) == before


def test_blocked_personal_contact_cannot_stage_new_profile(prepared_pair):
    owner, _, _, _ = prepared_pair
    owner.store.put("contact", "blocked", {"id": "blocked", "trust": "blocked", "destination_hash": "ab" * 16})
    records = {}
    with pytest.raises(ContactNotApproved):
        owner._prepare_reconnect_profile_for_contact("blocked", records=records)
    assert records == {}


def test_remote_approval_and_parent_state_can_commit_or_roll_back_together(prepared_pair, monkeypatch):
    _, _, member, workspace = prepared_pair
    document = create_profile_document("Workspace relay", [{"host": "relay.example.net", "port": 4242}])
    before = rows(member.store)
    operation, digest = str(uuid4()), hashlib.sha256(b"explicit workspace consent").hexdigest()
    with monkeypatch.context() as guard:
        forbid_writes(guard, member.store)
        guard.setattr("mesh_chat.remote_service.resolve_public_endpoint", lambda *_a, **_k: pytest.fail("No DNS before commit"))
        record, writes = member._prepare_remote_approval(document, origin="workspace_access", scope_kind="workspace",
            scope_id=workspace["id"], operation_id=operation)
    assert rows(member.store) == before
    parent = {"id": "recommendation", "workspace_id": workspace["id"], "state": "applied"}
    writes += [("workspace_access_recommendation", parent["id"], parent)]
    original = member.store._write_records_locked

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected combined commit failure")

    monkeypatch.setattr(member.store, "_write_records_locked", fail)
    with pytest.raises(OSError):
        member.store.commit_operation(operation, digest, {"id": record["id"]}, writes)
    assert rows(member.store) == before
    monkeypatch.setattr(member.store, "_write_records_locked", original)
    member.store.commit_operation(operation, digest, {"id": record["id"]}, writes)
    assert member.store.get("remote_profile", record["id"])["scopes"] == [{"kind": "workspace", "id": workspace["id"]}]
    assert member.store.get("workspace_access_recommendation", parent["id"]) == parent
    assert member.store.get("remote_runtime_intent", "transport") is not None


def test_prepared_remote_approval_cannot_bypass_private_endpoint_consent(prepared_pair):
    _, _, member, workspace = prepared_pair
    document = create_profile_document("Private relay", [{"host": "127.0.0.1", "port": 4242}], allow_private=True)
    before = rows(member.store)
    with pytest.raises(ValidationError):
        member._prepare_remote_approval(document, origin="workspace_access", scope_kind="workspace", scope_id=workspace["id"])
    assert rows(member.store) == before
