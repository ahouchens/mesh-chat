"""A serialized retry cannot outlive signed workspace membership authority."""

import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workspace_service import _deliver_all, _flush, _joined_pair


@pytest.fixture
def removed_member(tmp_path):
    owner, owner_network, owner_profile, member, _, member_profile, workspace, *_ = _joined_pair(
        tmp_path, base=191_000)
    owner._shutdown.clear()
    member._shutdown.clear()
    session = bind_service_stream(member, lambda: Grant(
        "boundary-workspace-member", frozenset({"observe", "read", "send"}), ("local",)))

    def exchange(operation, params=None, key=None):
        value = {"api_version": 1, "request_id": "workspace-retry:1",
                 "operation": operation, "params": params or {}}
        if key is not None:
            value["idempotency_key"] = key
        return json.loads(session.exchange(json.dumps(value).encode("utf-8") + b"\n"))

    profile = exchange("runtime.capabilities")["result"]["profiles"][0]
    handle = exchange("workspace.query", {"profile": profile})["result"]["workspaces"][0]["workspace"]

    def revoke():
        member_id = member._require_workspace(workspace["id"])["local_member_id"]
        owner.remove_workspace_member(workspace["id"], member_id, str(uuid4()))
        _deliver_all(member, _flush(owner, owner_network),
                     source_profile=owner_profile, recipient_profile=member_profile)
        assert member._require_workspace(workspace["id"])["state"] == "removed"

    try:
        yield exchange, revoke, {"profile": profile, "workspace": handle}, workspace["general_channel_id"]
    finally:
        session.close()
        owner.close()
        member.close()


@pytest.mark.parametrize("operation", ["workspace.timeline_mutation", "workspace.read_hint_sync"])
def test_replay_rechecks_signed_membership_before_returning_prior_success(removed_member, operation):
    exchange, revoke, scope, channel = removed_member
    params = ({**scope, "action": "channel_message", "conversation": channel,
               "text": "Authorized before removal", "event_id": str(uuid4()), "mention_member_ids": []}
              if operation == "workspace.timeline_mutation" else {**scope, "enabled": True})
    key = "signed-removal-replay-key-0001"
    accepted = exchange(operation, params, key)
    assert accepted["ok"], accepted
    revoke()
    changed = {**params, "event_id": str(uuid4())} if "event_id" in params else {**params, "enabled": False}
    fresh = exchange(operation, changed, key + "-new")
    assert fresh["error"]["code"] == "forbidden", fresh
    replay = exchange(operation, params, key)
    assert replay["ok"] is False, replay
    assert replay["error"]["code"] == "forbidden"
