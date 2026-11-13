"""An accepted keyed no-op still binds its input before a later retry."""

import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import RNS

from mesh_chat.core_api.host import OWNER_PERMISSIONS, bind_host_stream

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workspace_service import _deliver_all, _flush, _joined_pair, _service


def _open_client(service):
    session = bind_host_stream(service, caller="boundary-noop-owner", scope="owner",
                               permissions=OWNER_PERMISSIONS)

    def exchange(operation, params=None, key=None):
        request = {"api_version": 1, "request_id": "noop:1",
                   "operation": operation, "params": params or {}}
        if key is not None:
            request["idempotency_key"] = key
        return json.loads(session.exchange(json.dumps(request).encode("utf-8") + b"\n"))

    capabilities = exchange("runtime.capabilities")
    assert capabilities["ok"], capabilities
    profile = capabilities["result"]["profiles"][0]
    workspaces = exchange("workspace.query", {"profile": profile})
    assert workspaces["ok"], workspaces
    scope = {"profile": profile, "workspace": workspaces["result"]["workspaces"][0]["workspace"]}
    return session, exchange, scope


def _assert_noop_key_conflict(exchange, operation, first, changed):
    key = "accepted-noop-payload-key-0001"
    accepted = exchange(operation, first, key)
    assert accepted["ok"], accepted
    replay = exchange(operation, first, key)
    assert replay["ok"] and replay["result"] == accepted["result"], replay
    conflict = exchange(operation, changed, key)
    assert conflict["ok"] is False, conflict
    assert conflict["error"]["code"] == "idempotency_conflict", conflict
    fresh = exchange(operation, changed, key + "-new")
    assert fresh["ok"], fresh


def test_member_role_noop_binds_key_before_changed_payload_retry(tmp_path):
    owner, _, _, member, *_ = _joined_pair(tmp_path, base=193_000)
    owner._shutdown.clear()
    session = bind_host_stream(owner, caller="boundary-role-owner", scope="owner",
                               permissions=OWNER_PERMISSIONS)

    def exchange(operation, params=None, key=None):
        request = {"api_version": 1, "request_id": "role-noop:1",
                   "operation": operation, "params": params or {}}
        if key is not None:
            request["idempotency_key"] = key
        return json.loads(session.exchange(json.dumps(request).encode("utf-8") + b"\n"))

    try:
        capabilities = exchange("runtime.capabilities")
        assert capabilities["ok"], capabilities
        profile = capabilities["result"]["profiles"][0]
        workspaces = exchange("workspace.query", {"profile": profile})
        assert workspaces["ok"], workspaces
        scope = {"profile": profile, "workspace": workspaces["result"]["workspaces"][0]["workspace"]}
        members = exchange("workspace.members", scope)
        assert members["ok"], members
        target = next(item for item in members["result"]["members"] if item["role"] == "member")
        params = {**scope, "member": target["member"], "role": "member"}
        key = "member-role-noop-key-0001"
        accepted = exchange("workspace.member_role", params, key)
        assert accepted["ok"], accepted
        changed = exchange("workspace.member_role", {**params, "role": "admin"}, key)
        assert changed["ok"] is False, changed
        assert changed["error"]["code"] == "idempotency_conflict", changed
        fresh = exchange("workspace.member_role", {**params, "role": "admin"}, key + "-new")
        assert fresh["ok"], fresh
    finally:
        session.close()
        owner.close()
        member.close()


def test_current_channel_manager_accept_noop_binds_key_to_selected_channel(tmp_path):
    owner, _ = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    owner._shutdown.clear()
    session = None
    try:
        workspace = owner.create_workspace(str(uuid4()), "No-op channels", "")
        owner.create_workspace_channel(workspace["id"], "Another channel", "", str(uuid4()))
        session, exchange, scope = _open_client(owner)
        listed = exchange("workspace.channels", scope)
        assert listed["ok"], listed
        channels = listed["result"]["channels"]
        assert len(channels) == 2
        _assert_noop_key_conflict(exchange, "workspace.channel_transfer_accept",
                                  {**scope, "channel": channels[0]["channel"]},
                                  {**scope, "channel": channels[1]["channel"]})
    finally:
        if session is not None:
            session.close()
        owner.close()


@pytest.fixture
def settled_devices(tmp_path, request):
    action = request.param
    owner, owner_network = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    owner._shutdown.clear()
    linked_hosts = []
    session = None
    try:
        workspace = owner.create_workspace(str(uuid4()), "No-op devices", "")
        session, exchange, scope = _open_client(owner)
        targets = []
        for index in range(2):
            linked, linked_network = _service(tmp_path / f"linked-{index}", RNS.Identity(), "Linked")
            linked_hosts.append(linked)
            link = owner.create_workspace_device_link(workspace["id"], str(uuid4()))
            linked.submit_workspace_device_link(link["text"], str(uuid4()))
            _deliver_all(owner, _flush(linked, linked_network),
                         source_profile=linked._require_profile(), recipient_profile=owner._require_profile())
            pending = next(item for item in owner.workspace_snapshot()["workspace_device_transitions"]
                           if item["transition_kind"] == "link" and item["state"] == "pending")
            links = exchange("workspace.device_links", scope)
            assert links["ok"] and len(links["result"]["links"]) == 1, links
            handle = links["result"]["links"][0]["request"]
            if action == "device_link_decline":
                owner.decline_workspace_device_link(workspace["id"], pending["id"], str(uuid4()))
            else:
                owner.approve_workspace_device_link(workspace["id"], pending["id"], str(uuid4()))
            if action == "device_remove":
                # Query the genuine active device handle before signed removal.
                listed = exchange("workspace.devices", scope)
                assert listed["ok"], listed
                candidates = [item["device"] for item in listed["result"]["devices"] if not item["current"]]
                assert len(candidates) == 1
                handle = candidates[0]
                removal = owner.request_workspace_device_removal(workspace["id"], pending["device_id"], str(uuid4()))
                owner.approve_workspace_device_removal(workspace["id"], removal["id"], str(uuid4()))
            targets.append(handle)
        yield exchange, scope, action, targets
    finally:
        if session is not None:
            session.close()
        owner.close()
        for linked in linked_hosts:
            linked.close()


@pytest.mark.parametrize("settled_devices", ["device_link_approve", "device_link_decline", "device_remove"], indirect=True)
def test_settled_device_noop_binds_key_to_selected_target(settled_devices):
    exchange, scope, action, targets = settled_devices
    field = "device" if action == "device_remove" else "request"
    _assert_noop_key_conflict(exchange, "workspace." + action,
                              {**scope, field: targets[0]}, {**scope, field: targets[1]})
