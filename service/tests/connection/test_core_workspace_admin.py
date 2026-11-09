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
from test_workspace_service import (_deliver, _deliver_all, _flush, _joined_pair,  # noqa: E402
                                   _op, _service)

from test_core_messages import host, request  # noqa: E402, F401


CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "core-api"


@pytest.fixture
def admin_pair(tmp_path):
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Alex")
    owner._shutdown.clear()  # the harness stops background loops; the facade needs the grant path open
    joiner, joiner_network = _service(tmp_path / "joiner", RNS.Identity(), "Blair")
    joiner._shutdown.clear()
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
                   "name": "Renamed", "topic": "Ops",
                   "posting": "owner_and_admins"},
        "idempotency_key": "e" * 32,
    })
    assert updated["ok"], updated
    assert updated["result"]["name"] == "Renamed" and updated["result"]["topic"] == "Ops"
    assert updated["result"]["posting"] == "owner_and_admins"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-channel-update-result-v1.schema.json").read_text())
    ).validate(updated)
    cleared = session.request({
        "api_version": 1, "request_id": "request:3b", "operation": "workspace.channel_update",
        "params": {"profile": profile, "workspace": workspace, "channel": channel,
                   "name": "Renamed", "topic": "Ops", "posting": "inherit"},
        "idempotency_key": "i" * 32,
    })
    assert cleared["ok"], cleared
    assert cleared["result"]["posting"] is None

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


def test_a_new_device_can_submit_a_device_link_and_wait_for_approval(admin_pair, tmp_path):
    owner, _, _ = admin_pair
    owner_session, owner_profile = open_client(
        owner, permissions=("observe", "read", "approve", "pair"))
    workspace = owner_session.request(request("workspace.query", profile=owner_profile)
                                      )["result"]["workspaces"][0]["workspace"]
    created = owner_session.request({
        "api_version": 1, "request_id": "request:1",
        "operation": "workspace.device_link_create",
        "params": {"profile": owner_profile, "workspace": workspace},
        "idempotency_key": "l" * 32,
    })
    assert created["ok"], created
    new_device, _ = _service(tmp_path / "newdevice", RNS.Identity(), "Blair")
    new_device._shutdown.clear()
    try:
        new_session, new_profile = open_client(
            new_device, permissions=("observe", "read", "approve", "pair"), caller="blair")
        submit = {"api_version": 1, "request_id": "request:2",
                  "operation": "workspace.device_link_submit",
                  "params": {"profile": new_profile, "document": created["result"]["document"]},
                  "idempotency_key": "s" * 32}
        submitted = new_session.request(submit)
        assert submitted["ok"], submitted
        assert submitted["result"]["state"] == "linking"
        assert submitted["result"]["name"] == "Core"
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-device-link-submit-result-v1.schema.json").read_text())
        ).validate(submitted)
        assert new_session.request(submit)["result"] == submitted["result"]
        invalid = dict(submit)
        invalid["params"] = {"profile": new_profile, "document": "not-a-link"}
        assert new_session.request(invalid)["error"]["code"] == "idempotency_conflict"
    finally:
        new_device.close()


def test_pending_device_links_can_be_listed_and_approved(tmp_path):
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Alex")
    owner._shutdown.clear()
    linked, linked_network = _service(tmp_path / "linked", RNS.Identity(), "Alex")
    linked._shutdown.clear()
    try:
        owner.create_workspace(_op(72000), "Core", "")
        owner_session, owner_profile = open_client(
            owner, permissions=("observe", "read", "approve", "pair"))
        workspace = owner_session.request(request("workspace.query", profile=owner_profile)
                                          )["result"]["workspaces"][0]["workspace"]
        created = owner_session.request({
            "api_version": 1, "request_id": "request:1",
            "operation": "workspace.device_link_create",
            "params": {"profile": owner_profile, "workspace": workspace},
            "idempotency_key": "l" * 32,
        })
        linked_session, linked_profile = open_client(
            linked, permissions=("observe", "read", "approve", "pair"), caller="alex-linked")
        submitted = linked_session.request({
            "api_version": 1, "request_id": "request:2",
            "operation": "workspace.device_link_submit",
            "params": {"profile": linked_profile, "document": created["result"]["document"]},
            "idempotency_key": "s" * 32,
        })
        assert submitted["ok"], submitted
        _deliver_all(owner, _flush(linked, linked_network),
                     source_profile=linked._require_profile(),
                     recipient_profile=owner._require_profile())
        listing = owner_session.request(request("workspace.device_links",
                                                profile=owner_profile, workspace=workspace))
        assert listing["ok"], listing
        assert len(listing["result"]["links"]) == 1
        request_handle = listing["result"]["links"][0]["request"]
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-device-links-result-v1.schema.json").read_text())
        ).validate(listing)
        approve = {"api_version": 1, "request_id": "request:3",
                   "operation": "workspace.device_link_approve",
                   "params": {"profile": owner_profile, "workspace": workspace,
                              "request": request_handle},
                   "idempotency_key": "d" * 32}
        decided = owner_session.request(approve)
        assert decided["ok"], decided
        assert decided["result"]["state"] == "approved"
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-device-link-decision-result-v1.schema.json").read_text())
        ).validate(decided)
        assert owner_session.request(approve)["result"] == decided["result"]
        _deliver_all(linked, _flush(owner, owner_network),
                     source_profile=owner._require_profile(),
                     recipient_profile=linked._require_profile())
        linked_workspace = linked_session.request(request("workspace.query",
                                                          profile=linked_profile))
        assert linked_workspace["result"]["workspaces"][0]["state"] == "active"
        devices = owner_session.request(request("workspace.devices",
                                                profile=owner_profile, workspace=workspace))
        assert devices["ok"], devices
        assert len(devices["result"]["devices"]) == 2
        assert sum(item["current"] for item in devices["result"]["devices"]) == 1
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-devices-result-v1.schema.json").read_text())
        ).validate(devices)
        target_device = next(item["device"] for item in devices["result"]["devices"]
                             if not item["current"])
        removed = owner_session.request({
            "api_version": 1, "request_id": "request:4",
            "operation": "workspace.device_remove",
            "params": {"profile": owner_profile, "workspace": workspace,
                       "device": target_device},
            "idempotency_key": "x" * 32,
        })
        assert removed["ok"], removed
        assert removed["result"]["state"] == "removed"
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-device-remove-result-v1.schema.json").read_text())
        ).validate(removed)
        replay = owner_session.request({
            "api_version": 1, "request_id": "request:4",
            "operation": "workspace.device_remove",
            "params": {"profile": owner_profile, "workspace": workspace,
                       "device": target_device},
            "idempotency_key": "x" * 32,
        })
        assert replay["ok"] and replay["result"]["state"] == "removed", replay
        _deliver_all(linked, _flush(owner, owner_network),
                     source_profile=owner._require_profile(),
                     recipient_profile=linked._require_profile())
        assert linked_session.request(request("workspace.query", profile=linked_profile)
                                      )["result"]["workspaces"][0]["state"] == "device_removed"
        assert owner_session.request(request("workspace.device_links",
                                             profile=owner_profile, workspace=workspace)
                                     )["result"]["links"] == []
    finally:
        owner.close()
        linked.close()


def test_channel_transfers_can_be_offered_and_accepted(tmp_path):
    (owner, owner_network, owner_profile, member, member_network, member_profile,
     workspace, *_rest) = _joined_pair(tmp_path, base=73000)
    owner._shutdown.clear()
    member._shutdown.clear()
    try:
        owner_session, owner_handle = open_client(owner)
        member_session, member_handle = open_client(member, caller="bailey")
        owner_workspace = owner_session.request(request("workspace.query", profile=owner_handle)
                                                )["result"]["workspaces"][0]["workspace"]
        created = owner_session.request({
            "api_version": 1, "request_id": "request:1",
            "operation": "workspace.channel_create",
            "params": {"profile": owner_handle, "workspace": owner_workspace,
                       "name": "Transfers"},
            "idempotency_key": "c" * 32,
        })
        assert created["ok"], created
        owner_channel = created["result"]["channel"]
        for item in _flush(owner, owner_network):
            _deliver(member, item, source_profile=owner_profile,
                     recipient_profile=member_profile)
        members = owner_session.request(request("workspace.members", profile=owner_handle,
                                                workspace=owner_workspace))
        target = next(item["member"] for item in members["result"]["members"]
                      if item["display_name"] == "Bailey")
        offer = owner_session.request({
            "api_version": 1, "request_id": "request:2",
            "operation": "workspace.channel_transfer_offer",
            "params": {"profile": owner_handle, "workspace": owner_workspace,
                       "channel": owner_channel, "member": target},
            "idempotency_key": "o" * 32,
        })
        assert offer["ok"], offer
        assert offer["result"]["state"] == "offered"
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-channel-transfer-offer-result-v1.schema.json").read_text())
        ).validate(offer)
        for item in _flush(owner, owner_network):
            _deliver(member, item, source_profile=owner_profile,
                     recipient_profile=member_profile)
        member_workspace = member_session.request(request("workspace.query", profile=member_handle)
                                                  )["result"]["workspaces"][0]["workspace"]
        member_channels = member_session.request(request("workspace.channels", profile=member_handle,
                                                          workspace=member_workspace))
        member_channel = next(item["channel"] for item in member_channels["result"]["channels"]
                              if item["name"] == "Transfers")
        accept = {"api_version": 1, "request_id": "request:3",
                  "operation": "workspace.channel_transfer_accept",
                  "params": {"profile": member_handle, "workspace": member_workspace,
                             "channel": member_channel},
                  "idempotency_key": "a" * 32}
        accepted = member_session.request(accept)
        assert accepted["ok"], accepted
        assert accepted["result"]["state"] == "accepted"
        Draft202012Validator(
            json.loads((CONTRACTS / "workspace-channel-transfer-accept-result-v1.schema.json").read_text())
        ).validate(accepted)
        assert member_session.request(accept)["result"] == accepted["result"]
        for item in _flush(member, member_network):
            _deliver(owner, item, source_profile=member_profile,
                     recipient_profile=owner_profile)
    finally:
        owner.close()
        member.close()


def test_workspace_owners_can_update_workspace_policies(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    update = {"api_version": 1, "request_id": "request:1",
              "operation": "workspace.policy_update",
              "params": {"profile": profile, "workspace": workspace,
                         "channel_creation": "owner_and_admins",
                         "posting": "owner_and_admins",
                         "invitation_requests": "owner_only"},
              "idempotency_key": "y" * 32}
    applied = session.request(update)
    assert applied["ok"], applied
    assert applied["result"]["channel_creation"] == "owner_and_admins"
    assert applied["result"]["posting"] == "owner_and_admins"
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-policy-update-result-v1.schema.json").read_text())
    ).validate(applied)
    assert session.request(update)["result"] == applied["result"]


def test_new_administration_handles_are_caller_scoped(admin_pair):
    owner, _, _ = admin_pair
    first, first_profile = open_client(owner, permissions=("observe", "read", "approve", "pair"))
    second, second_profile = open_client(
        owner, permissions=("observe", "read", "approve", "pair"), caller="mallory")
    first_workspace = first.request(request("workspace.query", profile=first_profile)
                                    )["result"]["workspaces"][0]["workspace"]
    second_workspace = second.request(request("workspace.query", profile=second_profile)
                                      )["result"]["workspaces"][0]["workspace"]
    assert first_workspace != second_workspace
    assert second.request(request("workspace.channels", profile=second_profile,
                                  workspace=first_workspace)
                          )["error"]["code"] == "forbidden"
    created = first.request({
        "api_version": 1, "request_id": "request:1",
        "operation": "workspace.channel_create",
        "params": {"profile": first_profile, "workspace": first_workspace, "name": "Scoped"},
        "idempotency_key": "s" * 32,
    })
    assert created["ok"], created
    channel = created["result"]["channel"]
    assert second.request({
        "api_version": 1, "request_id": "request:2",
        "operation": "workspace.channel_update",
        "params": {"profile": second_profile, "workspace": second_workspace,
                   "channel": channel, "name": "Stolen", "topic": ""},
        "idempotency_key": "t" * 32,
    })["error"]["code"] == "forbidden"
    members = first.request(request("workspace.members", profile=first_profile,
                                    workspace=first_workspace))
    member = members["result"]["members"][0]["member"]
    assert second.request({
        "api_version": 1, "request_id": "request:3",
        "operation": "workspace.member_role",
        "params": {"profile": second_profile, "workspace": second_workspace,
                   "member": member, "role": "admin"},
        "idempotency_key": "u" * 32,
    })["error"]["code"] == "forbidden"


def test_reusing_one_caller_key_across_operations_fails_closed(admin_pair):
    owner, _, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    key = "z" * 32
    created = session.request({
        "api_version": 1, "request_id": "request:1",
        "operation": "workspace.channel_create",
        "params": {"profile": profile, "workspace": workspace, "name": "Collision"},
        "idempotency_key": key,
    })
    assert created["ok"], created
    collided = session.request({
        "api_version": 1, "request_id": "request:2",
        "operation": "workspace.channel_update",
        "params": {"profile": profile, "workspace": workspace,
                   "channel": created["result"]["channel"],
                   "name": "Replayed", "topic": ""},
        "idempotency_key": key,
    })
    assert collided["error"]["code"] == "idempotency_conflict", collided
    channels = session.request(request("workspace.channels", profile=profile,
                                       workspace=workspace))["result"]["channels"]
    names = [item["name"] for item in channels]
    assert "Collision" in names and "Replayed" not in names


def test_owner_creates_a_signed_workspace_invitation_through_the_facade(admin_pair):
    owner, joiner, _ = admin_pair
    session, profile = open_client(owner)
    workspace = session.request(request("workspace.query", profile=profile)
                                )["result"]["workspaces"][0]["workspace"]
    key = "i" * 32
    created = session.request({
        "api_version": 1, "request_id": "request:1",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace},
        "idempotency_key": key,
    })
    assert created["ok"], created
    Draft202012Validator(
        json.loads((CONTRACTS / "workspace-invitation-create-result-v1.schema.json").read_text())
    ).validate(created)
    document = created["result"]["document"]
    assert joiner.preview_workspace_invitation(document)["name"] == "Core"
    assert created["result"]["link"].startswith("meshchat://workspace/")
    replay = session.request({
        "api_version": 1, "request_id": "request:2",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace},
        "idempotency_key": key,
    })
    assert replay["result"] == created["result"]

    native = session.request({
        "api_version": 1, "request_id": "request:3",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace,
                   "connection_mode": "webrtc"},
        "idempotency_key": "w" * 32,
    })
    assert native["ok"], native
    assert native["result"]["connection_mode"] == "webrtc"
    assert joiner.preview_workspace_invitation(native["result"]["document"])["name"] == "Core"

    email = session.request({
        "api_version": 1, "request_id": "request:7",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace,
                   "connection_mode": "email"},
        "idempotency_key": "e" * 32,
    })
    assert email["ok"] and email["result"]["connection_mode"] == "email", email

    relay = "a" * 52 + ".b32.i2p"
    i2p = session.request({
        "api_version": 1, "request_id": "request:7",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace,
                   "connection_mode": "i2p", "i2p_access_point": relay,
                   "i2p_label": "Community relay"},
        "idempotency_key": "r" * 32,
    })
    assert i2p["ok"], i2p
    assert i2p["result"]["connection_mode"] == "i2p"
    assert i2p["result"]["i2p_access_point"] == relay

    participant = session.request({
        "api_version": 1, "request_id": "request:7",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace,
                   "connection_mode": "participant"},
        "idempotency_key": "p" * 32,
    })
    assert participant["error"]["code"] == "unavailable", participant

    consumer, _ = open_client(owner, permissions=("observe", "read"))
    denied = consumer.request({
        "api_version": 1, "request_id": "request:7",
        "operation": "workspace.invitation_create",
        "params": {"profile": profile, "workspace": workspace},
        "idempotency_key": "j" * 32,
    })
    assert denied["error"]["code"] == "forbidden", denied


@pytest.fixture
def awaiting_pair(tmp_path):
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Alex")
    owner._shutdown.clear()
    joiner, joiner_network = _service(tmp_path / "joiner", RNS.Identity(), "Blair")
    joiner._shutdown.clear()
    workspace = owner.create_workspace(_op(72000), "Facade pairing", "")
    yield owner, owner_network, joiner, joiner_network, workspace
    owner.close()
    joiner.close()


def test_workspace_invite_join_and_approval_through_the_facade(awaiting_pair):
    owner, owner_network, joiner, joiner_network, workspace = awaiting_pair
    owner_session, owner_profile = open_client(owner)
    joiner_session, joiner_profile = open_client(
        joiner, permissions=("observe", "read", "pair"))
    workspace_handle = owner_session.request(
        request("workspace.query", profile=owner_profile)
    )["result"]["workspaces"][0]["workspace"]
    invited = owner_session.request({
        "api_version": 1, "request_id": "request:1",
        "operation": "workspace.invitation_create",
        "params": {"profile": owner_profile, "workspace": workspace_handle},
        "idempotency_key": "i" * 32,
    })
    assert invited["ok"], invited
    joined = joiner_session.request({
        "api_version": 1, "request_id": "request:2",
        "operation": "workspace.join",
        "params": {"profile": joiner_profile, "document": invited["result"]["document"]},
        "idempotency_key": "j" * 32,
    })
    assert joined["ok"], joined
    assert joined["result"]["state"] == "joining"
    _deliver_all(owner, _flush(joiner, joiner_network),
                 source_profile=joiner._require_profile(),
                 recipient_profile=owner._require_profile())
    pending = owner_session.request(request("workspace.join_requests",
                                             profile=owner_profile,
                                             workspace=workspace_handle))
    assert pending["ok"] and len(pending["result"]["requests"]) == 1, pending
    approved = approve(owner_session, owner_profile, workspace_handle,
                       pending["result"]["requests"][0]["request"], key="a" * 32)
    assert approved["ok"], approved
    members = owner_session.request(request("workspace.members", profile=owner_profile,
                                            workspace=workspace_handle))
    assert [(item["display_name"], item["role"]) for item in members["result"]["members"]] == [
        ("Alex", "owner"), ("Blair", "member")]


def component_request(session, operation, key=None, **params):
    value = request(operation, **params)
    if key is not None:
        value["idempotency_key"] = key
    # Exercise the public JSON boundary before production parsing/execution.
    return session.request(json.loads(json.dumps(value)))


def test_new_component_mutations_execute_and_replay_through_the_real_vault(host):
    service = host()
    session, profile = open_client(service, permissions=("observe", "read", "send", "approve"))
    created = component_request(session, "workspace.create", "create-workspace-key",
                                profile=profile, name="Component", description="")
    assert created["ok"], created
    listing = component_request(session, "workspace.query", profile=profile)
    workspace = listing["result"]["workspaces"][0]["workspace"]
    channel_id = service.store.list("workspace_channel")[0]["id"]
    channel = component_request(session, "workspace.channels", profile=profile,
                                 workspace=workspace)["result"]["channels"][0]["channel"]
    mutations = [
        ("workspace.metadata_update", {"workspace": workspace, "name": "Renamed", "description": "Core"}),
        ("workspace.retention_update", {"workspace": workspace, "retention_days": 30}),
        ("workspace.read_hint_sync", {"workspace": workspace, "enabled": False}),
        ("workspace.draft_set", {"workspace": workspace, "conversation": channel_id, "text": "draft"}),
        ("workspace.channel_state", {"workspace": workspace, "channel": channel,
                                      "action": "mute", "muted": True}),
        ("runtime.mutate", {"action": "notification_previews", "hidden": True}),
        ("workspace.timeline_mutation", {"workspace": workspace, "action": "channel_message",
            "conversation": channel_id, "text": "Hello Core", "event_id": _op(73000)}),
        ("workspace.timeline_mutation", {"workspace": workspace, "action": "notification_preference",
            "conversation": None, "mode": "mentions"}),
    ]
    replies = []
    for index, (operation, params) in enumerate(mutations):
        key = f"component-mutation-{index:04}"
        reply = component_request(session, operation, key, profile=profile, **params)
        assert reply["ok"], (operation, reply)
        assert component_request(session, operation, key, profile=profile, **params) == reply
        replies.append(reply)
    assert service.store.list("workspace")[0]["name"] == "Renamed"
    assert service.store.list("workspace_draft")[0]["text"] == "draft"
    assert service.notification_state()["hide_previews"] is True
    messages = component_request(session, "workspace.timeline_query", profile=profile,
                                  workspace=workspace, view="channel_messages", channel=channel_id)
    assert messages["ok"], messages
    assert "Hello Core" in json.dumps(messages)
    service.close()
    reopened = host()
    again, same_profile = open_client(reopened, permissions=("observe", "read", "send", "approve"))
    assert same_profile == profile
    for index, (operation, params) in enumerate(mutations):
        assert component_request(again, operation, f"component-mutation-{index:04}",
                                 profile=profile, **params) == replies[index]
    changed = component_request(again, "workspace.metadata_update", "component-mutation-0000",
                                 profile=profile, workspace=workspace,
                                 name="Different", description="Core")
    assert changed["error"]["code"] == "idempotency_conflict", changed
    assert reopened.store.list("workspace")[0]["name"] == "Renamed"
    cleared = component_request(again, "workspace.draft_set", "clear-workspace-draft",
                                 profile=profile, workspace=workspace,
                                 conversation=channel_id, text="")
    assert cleared["ok"], cleared
    assert reopened.store.list("workspace_draft") == []


