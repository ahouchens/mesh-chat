"""Workspace listing and join approval through the private facade."""

import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest
import RNS

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.session import Grant

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workspace_service import _deliver, _flush, _op, _service  # noqa: E402

from test_core_messages import request  # noqa: E402


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"


@pytest.fixture
def admin_pair(tmp_path):
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Alex")
    owner._shutdown.clear()  # the harness stops background loops; the facade needs the grant path open
    joiner, joiner_network = _service(tmp_path / "joiner", RNS.Identity(), "Blair")
    workspace = owner.create_workspace(_op(71000), "Core", "")
    invitation = owner.create_workspace_invitation_command(workspace["id"], _op(71001))
    joiner.submit_workspace_join(invitation["text"], _op(71002))
    pending = _flush(joiner, joiner_network)[0]
    _deliver(owner, pending, source_profile=joiner._require_profile(),
             recipient_profile=owner._require_profile())
    yield owner, joiner, workspace
    owner.close()
    joiner.close()


def open_client(service, permissions=("observe", "read", "approve"), caller="alex"):
    grants = [Grant(caller, frozenset(permissions), ("local",))]
    session = bind_service_session(service, lambda: grants[0])
    capabilities = session.request(request("runtime.capabilities"))
    assert capabilities["ok"], capabilities
    return session, capabilities["result"]["profiles"][0]


def approve(session, profile, workspace, join_request, key="k" * 32):
    return session.request({"api_version": 1, "request_id": "request:1",
                            "operation": "workspace.join_approve",
                            "params": {"profile": profile, "workspace": workspace,
                                       "request": join_request},
                            "idempotency_key": key})


def test_owner_lists_workspaces_requests_and_approves_a_join(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    listing = session.request(request("workspace.query", profile=profile))
    assert listing["ok"], listing
    assert len(listing["result"]["workspaces"]) == 1
    workspace = listing["result"]["workspaces"][0]
    assert workspace["name"] == "Core" and workspace["role"] == "owner"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-list-result-v1.schema.json").read_text())
    ).validate(listing)

    pending = session.request(request("workspace.join_requests", profile=profile,
                                      workspace=workspace["workspace"]))
    assert pending["ok"], pending
    assert [item["display_name"] for item in pending["result"]["requests"]] == ["Blair"]
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-requests-result-v1.schema.json").read_text())
    ).validate(pending)

    join_request = pending["result"]["requests"][0]["request"]
    approved = approve(session, profile, workspace["workspace"], join_request)
    assert approved["ok"], approved
    assert approved["result"]["state"] in {"active", "joining"}
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-approve-result-v1.schema.json").read_text())
    ).validate(approved)
    members = session.request(request("workspace.members", profile=profile,
                                      workspace=workspace["workspace"]))
    assert members["ok"], members
    assert [(item["display_name"], item["role"]) for item in members["result"]["members"]] == [
        ("Alex", "owner"), ("Blair", "member")]
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-members-result-v1.schema.json").read_text())
    ).validate(members)

    blair = next(item for item in members["result"]["members"]
                 if item["display_name"] == "Blair")
    change = session.request({
        "api_version": 1, "request_id": "request:1", "operation": "workspace.member_role",
        "params": {"profile": profile, "workspace": workspace["workspace"],
                   "member": blair["member"], "role": "admin"},
        "idempotency_key": "r" * 32,
    })
    assert change["ok"], change
    assert change["result"]["role"] == "admin"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-member-role-result-v1.schema.json").read_text())
    ).validate(change)
    assert session.request({
        "api_version": 1, "request_id": "request:2", "operation": "workspace.member_role",
        "params": {"profile": profile, "workspace": workspace["workspace"],
                   "member": blair["member"], "role": "admin"},
        "idempotency_key": "r" * 32,
    })["result"] == change["result"]
    refreshed = session.request(request("workspace.members", profile=profile,
                                        workspace=workspace["workspace"]))
    assert next(item for item in refreshed["result"]["members"]
                if item["member"] == blair["member"])["role"] == "admin"
    refused = session.request({
        "api_version": 1, "request_id": "request:3", "operation": "workspace.member_role",
        "params": {"profile": profile, "workspace": workspace["workspace"],
                   "member": blair["member"], "role": "owner"},
        "idempotency_key": "o" * 32,
    })
    assert refused["error"]["code"] == "invalid_request"
    again = approve(session, profile, workspace["workspace"], join_request)
    assert again == approved
    remaining = session.request(request("workspace.join_requests", profile=profile,
                                        workspace=workspace["workspace"]))
    assert remaining["result"]["requests"] == []


def test_workspace_administration_requires_the_approve_grant_and_scope(admin_pair):
    owner, _, _ = admin_pair
    reader, profile = open_client(owner, permissions=("observe", "read"))
    assert reader.request(request("workspace.query", profile=profile))["ok"]
    assert reader.request(request("workspace.join_requests", profile=profile,
                                  workspace="w" * 64))["error"]["code"] == "forbidden"
    alex, alex_profile = open_client(owner, caller="alex")
    _, blair_profile = open_client(owner, caller="blair")
    assert alex.request(request("workspace.query", profile=blair_profile)
                        )["error"]["code"] == "forbidden"
