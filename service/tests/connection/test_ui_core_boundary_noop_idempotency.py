"""An accepted keyed no-op still binds its input before a later retry."""

import json
from pathlib import Path
import sys

from mesh_chat.core_api.host import OWNER_PERMISSIONS, bind_host_stream

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workspace_service import _joined_pair


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
