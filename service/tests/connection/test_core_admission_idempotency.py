"""Atomic admission grants and their signed durable outbox through Core."""

import pytest

from test_core_workspace_admin import component_request, open_client
from test_workspace_service import _deliver_all, _flush, _joined_pair, _op, _service


@pytest.fixture
def admission_pair(tmp_path):
    owner, network, owner_profile, member, member_network, member_profile, workspace, _, _ = _joined_pair(
        tmp_path, base=81000)
    admin = member._require_workspace(workspace["id"])
    owner.change_workspace_role(workspace["id"], admin["local_member_id"], "admin", _op(81010))
    _deliver_all(member, _flush(owner, network), source_profile=owner_profile,
                 recipient_profile=member_profile)
    owner._shutdown.clear()
    member._shutdown.clear()
    client, profile = open_client(owner)
    handle = component_request(client, "workspace.query", profile=profile)["result"]["workspaces"][0]["workspace"]
    members = component_request(client, "workspace.members", profile=profile, workspace=handle)["result"]["members"]
    admin_handle = next(item["member"] for item in members if item["role"] == "admin")
    devices = component_request(client, "workspace.devices", profile=profile, workspace=handle)["result"]["devices"]
    device = next(item["device"] for item in devices if item["member"] == admin_handle)
    params = {"profile": profile, "workspace": handle, "admin_member": admin_handle,
              "admin_device": device, "max_admissions": 5, "lifetime_days": 7, "v2_ready": True}
    yield owner, network, owner_profile, member, member_network, member_profile, workspace, client, params
    owner.close()
    member.close()


def test_grant_acceptance_and_revocation_replay_without_duplicate_outbox(admission_pair):
    owner, network, owner_profile, member, _, member_profile, workspace, client, params = admission_pair
    created = component_request(client, "workspace.admission_grant_create", "create-admission-key", **params)
    assert created["ok"], created
    count = len(owner.store.list("workspace_delivery"))
    assert component_request(client, "workspace.admission_grant_create", "create-admission-key", **params) == created
    assert len(owner.store.list("workspace_admission_grant")) == 1
    assert len(owner.store.list("workspace_delivery")) == count
    changed = component_request(client, "workspace.admission_grant_create", "create-admission-key",
                                 **{**params, "max_admissions": 4})
    assert changed["error"]["code"] == "idempotency_conflict", changed
    _deliver_all(member, _flush(owner, network), source_profile=owner_profile,
                 recipient_profile=member_profile)
    admin_client, admin_profile = open_client(member)
    admin_workspace = component_request(admin_client, "workspace.query", profile=admin_profile)["result"]["workspaces"][0]["workspace"]
    grants = component_request(admin_client, "workspace.admission_grant_list", "list-admission-key",
        profile=admin_profile, workspace=admin_workspace)["result"]["grants"]
    accept = {"profile": admin_profile, "workspace": admin_workspace, "grant": grants[0]["admission_grant"]}
    accepted = component_request(admin_client, "workspace.admission_grant_accept", "accept-admission-key", **accept)
    assert accepted["ok"], accepted
    count = len(member.store.list("workspace_delivery"))
    assert component_request(admin_client, "workspace.admission_grant_accept", "accept-admission-key", **accept) == accepted
    assert member.store.list("workspace_admission_grant")[0]["state"] == "accepted"
    assert len(member.store.list("workspace_delivery")) == count
    end = {"profile": params["profile"], "workspace": params["workspace"],
           "grant": created["result"]["grant"]["admission_grant"]}
    ended = component_request(client, "workspace.admission_grant_end", "end-admission-key00", **end)
    assert ended["ok"], ended
    epoch = owner._require_workspace(workspace["id"])["epoch"]
    count = len(owner.store.list("workspace_delivery"))
    assert component_request(client, "workspace.admission_grant_end", "end-admission-key00", **end) == ended
    assert owner._require_workspace(workspace["id"])["epoch"] == epoch
    assert len(owner.store.list("workspace_delivery")) == count


def test_admission_receipt_and_grant_rollback_together(admission_pair, monkeypatch):
    owner, _, _, _, _, _, _, client, params = admission_pair
    before = owner.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    original = owner.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected admission commit failure")

    monkeypatch.setattr(owner.store, "_write_records_locked", fail)
    reply = component_request(client, "workspace.admission_grant_create", "failed-admission-key", **params)
    assert reply["error"]["code"] == "unavailable", reply
    assert owner.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    monkeypatch.setattr(owner.store, "_write_records_locked", original)
    assert component_request(client, "workspace.admission_grant_create", "failed-admission-key", **params)["ok"]


def test_admission_creation_replays_after_vault_reopen(admission_pair, tmp_path):
    owner, _, _, _, _, _, _, client, params = admission_pair
    created = component_request(client, "workspace.admission_grant_create", "restart-admission-key", **params)
    assert created["ok"], created
    identity, vault_key = owner._identity, owner.store._key
    owner.close()
    reopened, _ = _service(tmp_path / "owner", identity, "Alex", vault_key=vault_key)
    reopened._shutdown.clear()
    try:
        again, _ = open_client(reopened)
        assert component_request(again, "workspace.admission_grant_create", "restart-admission-key", **params) == created
        assert len(reopened.store.list("workspace_admission_grant")) == 1
    finally:
        reopened.close()


def test_admission_replay_rechecks_current_owner_authority(admission_pair):
    owner, _, _, _, _, _, workspace, client, params = admission_pair
    assert component_request(client, "workspace.admission_grant_create", "authority-admission-key", **params)["ok"]
    current = owner._require_workspace(workspace["id"])
    current["local_role"] = "member"
    owner.store.put("workspace", owner._workspace_record_id(workspace["id"]), current)
    denied = component_request(client, "workspace.admission_grant_create", "authority-admission-key", **params)
    assert denied["error"]["code"] == "forbidden", denied
    assert len(owner.store.list("workspace_admission_grant")) == 1
