"""Workspace invitation preview and join through the private facade."""

import json
import os
from pathlib import Path
import uuid

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant
from test_core_messages import request


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"


def service_at(tmp_path, monkeypatch, name, folder):
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore

    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    directory = tmp_path / folder
    store = VaultStore(directory, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, directory, lambda _: None)
    service.create_profile(name)
    return service


@pytest.fixture
def workspaces(tmp_path, monkeypatch):
    owner = service_at(tmp_path, monkeypatch, "Alex", "owner")
    joiner = service_at(tmp_path, monkeypatch, "Blair", "joiner")
    workspace = owner.create_workspace(str(uuid.uuid4()), "Core Workspace", "")
    invitation = owner.create_workspace_invitation_command(workspace["id"], str(uuid.uuid4()))
    yield owner, joiner, workspace, invitation["value"]
    owner.close()
    joiner.close()


def open_client(service, permissions=("observe", "read", "pair"), caller="blair"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    return session, capabilities["result"]["profiles"][0]


def join_request(profile, document, key):
    return {"api_version": 1, "request_id": "request:1", "operation": "workspace.join",
            "params": {"profile": profile, "document": document}, "idempotency_key": key}


def test_preview_and_join_a_workspace_invitation(workspaces):
    _, joiner, _, document = workspaces
    session, profile = open_client(joiner)
    preview = session.request(request("workspace.invitation_preview", profile=profile,
                                      document=document))
    assert preview["ok"], preview
    assert preview["result"]["name"] == "Core Workspace"
    assert preview["result"]["member_count"] == 1
    assert preview["result"]["requires_i2p_consent"] is False
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-preview-result-v1.schema.json").read_text())
    ).validate(preview)

    key = "k" * 16
    joined = session.request(join_request(profile, document, key))
    assert joined["ok"], joined
    assert joined["result"]["name"] == "Core Workspace"
    assert joined["result"]["state"] in {"joining", "active", "pending", "left"}
    assert session.request(join_request(profile, document, key)) == joined
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-join-result-v1.schema.json").read_text())
    ).validate(joined)


def test_preview_and_join_require_their_grants_and_caller_scope(workspaces):
    _, joiner, _, document = workspaces
    reader, profile = open_client(joiner, permissions=("observe", "read"))
    assert reader.request(join_request(profile, document, "k" * 16))["error"]["code"] == "forbidden"
    assert reader.request(request("workspace.invitation_preview", profile=profile,
                                  document=document))["ok"]
    observer, _ = open_client(joiner, permissions=("observe",), caller="alex")
    _, foreign = open_client(joiner)
    assert observer.request(request("workspace.invitation_preview", profile=foreign,
                                    document=document))["error"]["code"] == "forbidden"


def test_invalid_workspace_material_is_refused(workspaces):
    _, joiner, _, _ = workspaces
    session, profile = open_client(joiner)
    assert session.request(request("workspace.invitation_preview", profile=profile,
                                   document="not-an-invitation"))["error"]["code"] == "invalid_request"
    assert session.request(join_request(profile, "not-an-invitation", "k" * 16))["error"]["code"] == "invalid_request"
