from __future__ import annotations

import json
import time

import pytest
import RNS

from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_device_card,
    create_workspace_manifest,
)
from mesh_chat.workspace_wire import WorkspaceWirePayload, parse_workspace_payload
from test_workspace_service import _deliver, _flush, _native, _op, _service


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("reordered", [False, True])
def test_join_after_workspace_update_receives_general(tmp_path, repair, reordered):
    owner, owner_net = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    joiner, joiner_net = _service(tmp_path / "joiner", RNS.Identity(), "Joiner")
    try:
        workspace = owner.create_workspace(_op(98000), "Team", "")
        for index in range(4):
            owner.update_workspace_metadata(
                workspace["id"], "Team", f"Updated {index}", _op(98100 + index)
            )
        invitation = owner.create_workspace_invitation_command(workspace["id"], _op(98002))
        joiner.submit_workspace_join(invitation["text"], _op(98003))

        def forward(sender, network, recipient, *, drop_history=False):
            outgoing = _flush(sender, network)
            if reordered:
                outgoing.reverse()
            for sent in outgoing:
                wire = parse_workspace_payload(
                    _native(sent, source=b"\x00" * 16, destination=b"\x01" * 16)
                )
                if (
                    drop_history and wire.kind == "workspace_manifest_root"
                    and json.loads(wire.document)["epoch"] < 5
                ):
                    continue
                _deliver(
                    recipient, sent, source_profile=sender._require_profile(),
                    recipient_profile=recipient._require_profile(),
                )

        forward(joiner, joiner_net, owner)
        request = owner.workspace_snapshot()["workspace_join_requests"][0]
        owner.approve_workspace_join(workspace["id"], request["id"], _op(98004))
        forward(owner, owner_net, joiner, drop_history=repair)
        if repair:
            assert joiner.workspace_snapshot()["workspace_channels"] == []
            joiner.sync_workspace_channels(workspace["id"], _op(98005))
            for _ in range(4):
                forward(joiner, joiner_net, owner)
                forward(owner, owner_net, joiner)
        snapshot = joiner.workspace_snapshot()
        assert snapshot["workspaces"][0]["state"] == "active"
        assert snapshot["workspaces"][0]["epoch"] == 6
        assert snapshot["workspaces"][0]["description"] == "Updated 3"
        assert len(snapshot["workspaces"][0]["members"]) == 2
        assert [channel["name"] for channel in snapshot["workspace_channels"]] == ["general"]
        assert snapshot["workspaces"][0]["general_channel_id"] == workspace["general_channel_id"]
        assert joiner.store.list("workspace_pending_control") == []
    finally:
        owner.close()
        joiner.close()


@pytest.mark.parametrize("offered_epoch", [2, 4])
def test_historical_manifest_rejects_untrusted_authority(tmp_path, offered_epoch):
    owner, _ = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    joiner, _ = _service(tmp_path / "joiner", RNS.Identity(), "Joiner")
    try:
        workspace = owner.create_workspace(_op(98200), "Team", "")
        for epoch in range(1, offered_epoch):
            owner.update_workspace_metadata(
                workspace["id"], "Team", str(epoch), _op(98200 + epoch)
            )
        invitation = owner.create_workspace_invitation_command(workspace["id"], _op(98210))
        joiner.submit_workspace_join(invitation["text"], _op(98211))
        before = joiner._require_workspace(workspace["id"])
        attacker = RNS.Identity()
        member_id, device_id = _op(98212), _op(98213)
        card = create_workspace_device_card(
            attacker, workspace_id=workspace["id"], member_id=member_id,
            device_id=device_id, display_name="Attacker",
        )
        forged = create_workspace_manifest(
            attacker, workspace_id=workspace["id"], epoch=1,
            previous_manifest_hash=before["genesis_digest"], name="Team", description="",
            authority_device_id=device_id,
            members=[WorkspaceManifestMemberInput(member_id, "Attacker", "owner", [card])],
        )
        wire = WorkspaceWirePayload(
            kind="workspace_manifest_root", logical_id=_op(98214),
            workspace_id=workspace["id"], expires_at=int(time.time()) + 60,
            document=forged,
        )
        assert not joiner._receive_workspace_manifest(wire)
        assert joiner._workspace_manifest_at_epoch(workspace["id"], 1) is None
        assert joiner._require_workspace(workspace["id"]) == before

        # The genuine old record is useful even before approval, but must not
        # activate the workspace or replace the invitation's current checkpoint.
        initial = owner._workspace_manifest_at_epoch(workspace["id"], 1)
        valid = WorkspaceWirePayload(
            kind=wire.kind, logical_id=_op(98215), workspace_id=workspace["id"],
            expires_at=wire.expires_at, document=initial.serialized,
        )
        assert joiner._receive_workspace_manifest(valid)
        after = joiner._require_workspace(workspace["id"])
        assert after["state"] == "joining"
        assert after["manifest_hash"] == before["manifest_hash"]
        assert after["epoch"] == offered_epoch
    finally:
        owner.close()
        joiner.close()
