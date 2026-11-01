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


def test_channels_can_be_listed_and_a_public_channel_created(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    listed = session.request(request("workspace.channels", profile=profile,
                                     workspace=workspace))
    assert listed["ok"], listed
    assert listed["result"]["channels"]
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channels-result-v1.schema.json").read_text())
    ).validate(listed)

    create = {"api_version": 1, "request_id": "request:1",
              "operation": "workspace.channel_create",
              "params": {"profile": profile, "workspace": workspace, "name": "Core Chat"},
              "idempotency_key": "c" * 32}
    created = session.request(create)
    assert created["ok"], created
    assert created["result"]["name"] == "Core Chat"
    assert created["result"]["visibility"] == "public"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channel-create-result-v1.schema.json").read_text())
    ).validate(created)
    assert session.request(create)["result"] == created["result"]
    refreshed = session.request(request("workspace.channels", profile=profile,
                                        workspace=workspace))
    assert created["result"]["channel"] in [item["channel"]
                                            for item in refreshed["result"]["channels"]]
    empty = dict(create)
    empty["params"] = {"profile": profile, "workspace": workspace, "name": ""}
    assert session.request(empty)["error"]["code"] == "invalid_request"


def test_private_channels_support_membership_and_edits(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    pending = session.request(request("workspace.join_requests", profile=profile,
                                      workspace=workspace))["result"]["requests"][0]
    assert session.request({
        "api_version": 1, "request_id": "request:1", "operation": "workspace.join_approve",
        "params": {"profile": profile, "workspace": workspace, "request": pending["request"]},
        "idempotency_key": "a" * 32,
    })["ok"]
    members = session.request(request("workspace.members", profile=profile,
                                      workspace=workspace))
    by_name = {item["display_name"]: item["member"] for item in members["result"]["members"]}

    create = {"api_version": 1, "request_id": "request:2",
              "operation": "workspace.channel_create",
              "params": {"profile": profile, "workspace": workspace, "name": "Secret",
                         "visibility": "private", "members": [by_name["Blair"]]},
              "idempotency_key": "p" * 32}
    created = session.request(create)
    assert created["ok"], created
    assert created["result"]["visibility"] == "private"
    channel = created["result"]["channel"]

    listed = session.request(request("workspace.channel_members", profile=profile,
                                     workspace=workspace, channel=channel))
    assert listed["ok"], listed
    assert len(listed["result"]["members"]) == 2
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channel-members-result-v1.schema.json").read_text())
    ).validate(listed)

    updated = session.request({
        "api_version": 1, "request_id": "request:3", "operation": "workspace.channel_update",
        "params": {"profile": profile, "workspace": workspace, "channel": channel,
                   "name": "Renamed", "topic": "Ops"},
        "idempotency_key": "e" * 32,
    })
    assert updated["ok"], updated
    assert updated["result"]["name"] == "Renamed" and updated["result"]["topic"] == "Ops"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channel-update-result-v1.schema.json").read_text())
    ).validate(updated)

    roster = session.request({
        "api_version": 1, "request_id": "request:4",
        "operation": "workspace.channel_members_update",
        "params": {"profile": profile, "workspace": workspace, "channel": channel,
                   "members": [by_name["Alex"]]},
        "idempotency_key": "m" * 32,
    })
    assert roster["ok"], roster
    assert roster["result"]["members"] == [by_name["Alex"]]
    public_channel = next(item for item in session.request(
        request("workspace.channels", profile=profile, workspace=workspace)
    )["result"]["channels"] if item["visibility"] == "public")["channel"]
    assert session.request(request("workspace.channel_members", profile=profile,
                                   workspace=workspace, channel=public_channel)
                           )["error"]["code"] == "invalid_request"


def test_channels_can_be_archived_and_replays_are_stable(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    create = {"api_version": 1, "request_id": "request:1",
              "operation": "workspace.channel_create",
              "params": {"profile": profile, "workspace": workspace, "name": "Archive Me"},
              "idempotency_key": "a" * 32}
    channel = session.request(create)["result"]["channel"]
    archive = {"api_version": 1, "request_id": "request:2",
               "operation": "workspace.channel_archive",
               "params": {"profile": profile, "workspace": workspace, "channel": channel},
               "idempotency_key": "r" * 32}
    archived = session.request(archive)
    assert archived["ok"], archived
    assert archived["result"]["state"] == "archived"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channel-archive-result-v1.schema.json").read_text())
    ).validate(archived)
    assert session.request(archive)["result"] == archived["result"]
    listed = session.request(request("workspace.channels", profile=profile,
                                     workspace=workspace))
    assert next(item for item in listed["result"]["channels"]
                if item["channel"] == channel)["state"] == "archived"


def test_device_links_can_be_created_and_previewed(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner, permissions=("observe", "read", "approve", "pair"))
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    create = {"api_version": 1, "request_id": "request:1",
              "operation": "workspace.device_link_create",
              "params": {"profile": profile, "workspace": workspace},
              "idempotency_key": "l" * 32}
    created = session.request(create)
    assert created["ok"], created
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-device-link-create-result-v1.schema.json").read_text())
    ).validate(created)
    document = created["result"]["document"]
    assert created["result"]["link"].startswith("meshchat://workspace-device/")
    assert session.request(create)["result"] == created["result"]
    preview = session.request(request("workspace.device_link_preview", profile=profile,
                                      document=document))
    assert preview["ok"], preview
    assert preview["result"]["name"] == "Core"
    assert preview["result"]["member_display_name"] == "Alex"
    assert preview["result"]["device_count"] == 1
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-device-link-preview-result-v1.schema.json").read_text())
    ).validate(preview)
    assert session.request(request("workspace.device_link_preview", profile=profile,
                                   document="not-a-link"))["error"]["code"] == "invalid_request"
