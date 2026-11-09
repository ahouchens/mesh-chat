"""Keyed local tombstones and signed artifacts through the actual facade."""

import uuid

import pytest

from mesh_chat.remote import create_profile_document, new_profile_record
from test_core_messages import host
from test_core_workspace_admin import component_request, open_client


def setup_recommendation(service):
    service.create_workspace(str(uuid.uuid4()), "Artifacts", "")
    profile = create_profile_document("Relay", [{"host": "93.184.216.34", "port": 4242}])
    record = new_profile_record(profile, origin="manual", scope_kind="manual", scope_id=profile["id"])
    service.store.put("remote_profile", profile["id"], record)
    client, handle = open_client(service, permissions=("observe", "read", "send", "approve"))
    workspace = component_request(client, "workspace.query", profile=handle)["result"]["workspaces"][0]["workspace"]
    return client, {"profile": handle, "workspace": workspace, "action": "create",
                     "remote_profile_id": profile["id"], "lifetime_days": 7}


def test_signed_recommendation_reuses_exact_artifact_and_rechecks_authority(host, monkeypatch):
    service = host()
    client, params = setup_recommendation(service)
    created = component_request(client, "workspace.access_recommendation", "signed-artifact-key", **params)
    assert created["ok"], created

    def forbidden(*_, **__):
        raise AssertionError("A replay must not mint another signed artifact")

    monkeypatch.setattr("mesh_chat.workspace_service.build_workspace_access_recommendation", forbidden)
    assert component_request(client, "workspace.access_recommendation", "signed-artifact-key", **params) == created
    changed = component_request(client, "workspace.access_recommendation", "signed-artifact-key",
                                 **{**params, "lifetime_days": 6})
    assert changed["error"]["code"] == "idempotency_conflict", changed
    workspace = service.store.list("workspace")[0]
    workspace["local_role"] = "member"
    service.store.put("workspace", service._workspace_record_id(workspace["id"]), workspace)
    assert component_request(client, "workspace.access_recommendation", "signed-artifact-key", **params)["error"]["code"] == "forbidden"


def test_signed_artifact_receipt_rolls_back_and_survives_reopen(host, monkeypatch):
    service = host()
    client, params = setup_recommendation(service)
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected artifact receipt failure")

    before = len(service.store.list("workspace_operation"))
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    assert component_request(client, "workspace.access_recommendation", "artifact-reopen-key", **params)["error"]["code"] == "unavailable"
    assert len(service.store.list("workspace_operation")) == before
    monkeypatch.setattr(service.store, "_write_records_locked", original)
    created = component_request(client, "workspace.access_recommendation", "artifact-reopen-key", **params)
    assert created["ok"], created
    service.close()
    reopened = host()
    again, _ = open_client(reopened, permissions=("observe", "read", "send", "approve"))
    assert component_request(again, "workspace.access_recommendation", "artifact-reopen-key", **params) == created


@pytest.mark.parametrize("fail_commit", [False, True])
def test_prompt_dismissal_is_atomic_and_conflicts_on_changed_target(host, monkeypatch, fail_commit):
    service = host()
    client, profile = open_client(service, permissions=("observe", "read", "send"))
    for identifier in ("a" * 64, "b" * 64):
        service.store.put("workspace_contact_invite", identifier, {"id": identifier, "state": "pending"})
    params = {"profile": profile, "action": "prompt_dismiss", "prompt_id": "a" * 64}
    original = service.store._write_records_locked
    if fail_commit:
        def fail(*args):
            original(*args)
            raise OSError("injected prompt commit failure")
        monkeypatch.setattr(service.store, "_write_records_locked", fail)
        assert component_request(client, "workspace.connection", "dismiss-prompt-key", **params)["error"]["code"] == "unavailable"
        assert service.store.get("workspace_contact_invite", "a" * 64)["state"] == "pending"
        assert service.store.list("workspace_operation") == []
        monkeypatch.setattr(service.store, "_write_records_locked", original)
    dismissed = component_request(client, "workspace.connection", "dismiss-prompt-key", **params)
    assert dismissed["ok"], dismissed
    assert component_request(client, "workspace.connection", "dismiss-prompt-key", **params) == dismissed
    changed = component_request(client, "workspace.connection", "dismiss-prompt-key",
                                 **{**params, "prompt_id": "b" * 64})
    assert changed["error"]["code"] == "idempotency_conflict", changed
    assert service.store.get("workspace_contact_invite", "b" * 64)["state"] == "pending"
