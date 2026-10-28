from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, ValidationError, WorkspaceAlreadyKnown
from mesh_chat.models import Contact, TrustState
from test_workspace_service import _deliver_all, _flush, _joined_pair, _op, _service


@pytest.fixture
def pair(tmp_path):
    values = _joined_pair(tmp_path, base=98000)
    yield values
    values[0].close()
    values[3].close()


def exchange(sender, network, recipient):
    _deliver_all(recipient, _flush(sender, network), source_profile=sender._require_profile(),
                 recipient_profile=recipient._require_profile())


@pytest.mark.parametrize("deliver_removal", [True, False])
def test_removed_person_rejoins_with_fresh_membership_and_keeps_local_history(pair, deliver_removal, tmp_path):
    owner, onet, _, member, mnet, _, workspace, key, identity = pair
    wid = workspace["id"]
    old = member._require_workspace(wid)
    general = old["general_channel_id"]
    private = owner.create_workspace_channel(wid, "Private", "", _op(98010), visibility="private",
                                             member_ids=[workspace["local_member_id"], old["local_member_id"]])
    exchange(owner, onet, member)
    direct = member.open_workspace_direct(wid, workspace["local_member_id"], _op(98011))
    direct_root = member.send_workspace_direct_message(wid, direct["id"], "Old private note", _op(98012), _op(98013))
    member.send_workspace_message(wid, general, "Before removal", _op(98014), _op(98015))
    private_root = member.send_workspace_message(wid, private["id"], "Old channel note", _op(98016), _op(98017))
    for offset, root in enumerate((direct_root, private_root)):
        conversation = direct["id"] if offset == 0 else private["id"]
        member.send_workspace_thread_reply(wid, conversation, root["id"], "Saved reply",
                                           _op(98040 + offset * 2), _op(98041 + offset * 2))
    # Leave these old-membership messages queued: rejoin must not revive them.
    old_pending = [row["id"] for row in member.store.list("workspace_delivery") if row.get("kind") == "workspace_event"]
    owner.remove_workspace_member(wid, old["local_member_id"], _op(98018))
    if deliver_removal:
        exchange(owner, onet, member)
        assert member._require_workspace(wid)["state"] == "removed"
    gap_message = owner.send_workspace_message(wid, general, "During removal", _op(98060), _op(98061))
    fresh = owner.create_workspace_invitation_command(wid, _op(98019))["text"]
    saved_events = member.store.list("workspace_event")
    preview = member.preview_workspace_invitation(fresh)
    assert preview["can_rejoin"] is True
    joined = member.submit_workspace_join(fresh, _op(98020))
    assert joined["state"] == "joining"
    assert joined["local_member_id"] != old["local_member_id"]
    assert joined["local_device_id"] != old["local_device_id"]
    assert member.store.list("workspace_event") == saved_events
    assert all(member.store.get("workspace_delivery", item)["state"] == "cancelled" for item in old_pending)
    with pytest.raises(ContactNotApproved):
        member.send_workspace_message(wid, general, "Not approved", _op(98021), _op(98022))
    # Retrying the same invitation must keep the new request/member/device.
    assert member.preview_workspace_invitation(fresh)["can_resume_join"] is True
    for operation in (_op(98020), _op(98023)):
        assert member.submit_workspace_join(fresh, operation)["local_member_id"] == joined["local_member_id"]
    exchange(member, mnet, owner)
    pending = [item for item in owner.workspace_snapshot()["workspace_join_requests"] if item["state"] == "pending"]
    assert len(pending) == 1
    owner.approve_workspace_join(wid, pending[0]["id"], _op(98024))
    exchange(owner, onet, member)
    assert member._require_workspace(wid)["state"] == "active"
    assert member._require_workspace(wid)["local_role"] == "member"
    memberships = owner._workspace_current_manifest(owner._require_workspace(wid)).members
    assert next(m for m in memberships if m.member_id == old["local_member_id"]).status == "removed"
    assert next(m for m in memberships if m.member_id == joined["local_member_id"]).status == "active"
    for channel, text in [(general, "Before removal"), (private["id"], "Old channel note"), (direct["id"], "Old private note")]:
        assert text in [m["text"] for m in member.list_workspace_messages(wid, channel)["messages"]]
    snapshot = member.workspace_snapshot()
    assert next(d for d in snapshot["workspace_directs"] if d["id"] == direct["id"])["state"] == "read_only"
    assert next(c for c in snapshot["workspace_channels"] if c["id"] == private["id"])["state"] == "removed"
    for offset, root in enumerate((direct_root, private_root)):
        thread = member.list_workspace_thread_messages(wid, root["id"])
        assert "Saved reply" in [message["text"] for message in thread["replies"]]
        conversation = direct["id"] if offset == 0 else private["id"]
        with pytest.raises((ContactNotApproved, ValidationError)):
            member.send_workspace_thread_reply(wid, conversation, root["id"], "No restored access",
                                               _op(98050 + offset * 2), _op(98051 + offset * 2))
    # Even if a gap event is retained locally, neither membership entitles this
    # person to read it: the old one was removed and the new one did not exist.
    gap_event = owner.store.get("workspace_event", owner._workspace_event_record_id(gap_message["id"]))
    member.store.put("workspace_event", member._workspace_event_record_id(gap_message["id"]), gap_event)
    assert not member._workspace_message_is_visible(member._require_workspace(wid), gap_message)
    for message in member.list_workspace_messages(wid, general)["messages"]:
        if message["text"] == "Before removal":
            assert message["delivery_summary"]["devices_pending"] == 0
    with pytest.raises((ContactNotApproved, ValidationError)):
        member.send_workspace_direct_message(wid, direct["id"], "Old direct", _op(98025), _op(98026))
    with pytest.raises((ContactNotApproved, ValidationError)):
        member.send_workspace_message(wid, private["id"], "No private access", _op(98027), _op(98028))
    new_message = member.send_workspace_message(wid, general, "Rejoined", _op(98029), _op(98030))
    exchange(member, mnet, owner)
    assert new_message["id"] in [m["id"] for m in owner.list_workspace_messages(wid, general)["messages"]]
    member.close()
    restarted, _ = _service(tmp_path / "member", identity, "Bailey", vault_key=key)
    try:
        assert restarted._require_workspace(wid)["state"] == "active"
        assert "Before removal" in [m["text"] for m in restarted.list_workspace_messages(wid, general)["messages"]]
    finally:
        restarted.close()


def test_rejoin_requires_fresh_invitation_proving_removal_and_keeps_workspace_limit(pair, monkeypatch):
    owner, onet, _, member, mnet, _, workspace, *_ = pair
    wid = workspace["id"]
    old_invite = owner.create_workspace_invitation_command(wid, _op(98100))["text"]
    original = member._require_workspace(wid)
    assert member.preview_workspace_invitation(old_invite)["can_rejoin"] is False
    owner.remove_workspace_member(wid, original["local_member_id"], _op(98101))
    exchange(owner, onet, member)
    with pytest.raises(WorkspaceAlreadyKnown):
        member.submit_workspace_join(old_invite, _op(98102))
    fresh = owner.create_workspace_invitation_command(wid, _op(98103))["text"]
    monkeypatch.setattr("mesh_chat.workspace_service.MAX_WORKSPACES", 1)
    joined = member.submit_workspace_join(fresh, _op(98104))
    assert joined["state"] == "joining"
    assert len(member.store.list("workspace")) == 1
    # Another invitation cannot replace a pending request.
    other = owner.create_workspace_invitation_command(wid, _op(98105))["text"]
    with pytest.raises(WorkspaceAlreadyKnown):
        member.submit_workspace_join(other, _op(98106))


@pytest.mark.parametrize("invalid", ["identity", "closed", "forked", "genesis", "newer_local_epoch"])
def test_rejoin_does_not_override_identity_or_terminal_workspace_state(pair, monkeypatch, invalid):
    owner, onet, _, member, _, _, workspace, *_ = pair
    wid = workspace["id"]
    original = member._require_workspace(wid)
    owner.remove_workspace_member(wid, original["local_member_id"], _op(98200))
    exchange(owner, onet, member)
    fresh = owner.create_workspace_invitation_command(wid, _op(98201))["text"]
    stored = member._require_workspace(wid)
    if invalid == "identity":
        monkeypatch.setattr(member, "_identity", RNS.Identity())
    elif invalid == "genesis":
        stored["genesis_digest"] = "00" * 32
    elif invalid == "newer_local_epoch":
        stored["epoch"] += 1
    else:
        stored["state"] = invalid
    member.store.put("workspace", member._workspace_record_id(wid), stored)
    before = member.store.list("workspace")
    assert member.preview_workspace_invitation(fresh)["can_rejoin"] is False
    with pytest.raises(WorkspaceAlreadyKnown):
        member.submit_workspace_join(fresh, _op(98202))
    assert member.store.list("workspace") == before


def test_repeated_removal_and_rejoin_keeps_each_old_membership_revoked(pair):
    owner, onet, _, member, mnet, _, workspace, *_ = pair
    wid = workspace["id"]
    retired = []
    for cycle in range(2):
        base = 98300 + cycle * 10
        retired.append(member._require_workspace(wid)["local_member_id"])
        owner.remove_workspace_member(wid, retired[-1], _op(base))
        exchange(owner, onet, member)
        fresh = owner.create_workspace_invitation_command(wid, _op(base + 1))["text"]
        member.submit_workspace_join(fresh, _op(base + 2))
        exchange(member, mnet, owner)
        pending = next(item for item in owner.workspace_snapshot()["workspace_join_requests"] if item["state"] == "pending")
        owner.approve_workspace_join(wid, pending["id"], _op(base + 3))
        exchange(owner, onet, member)
        assert member._require_workspace(wid)["state"] == "active"
    assert [item["member_id"] for item in member._require_workspace(wid)["local_membership_history"]] == retired
    manifest = owner._workspace_current_manifest(owner._require_workspace(wid))
    assert all(item.status == "removed" for item in manifest.members if item.member_id in retired)
    assert len([item for item in manifest.members if item.status == "active"]) == 2


def test_pending_rejoin_survives_restart_and_retries_without_new_identity(pair, tmp_path):
    owner, onet, _, member, _, _, workspace, key, identity = pair
    wid = workspace["id"]
    owner.remove_workspace_member(wid, member._require_workspace(wid)["local_member_id"], _op(98400))
    exchange(owner, onet, member)
    fresh = owner.create_workspace_invitation_command(wid, _op(98401))["text"]
    joined = member.submit_workspace_join(fresh, _op(98402))
    member.close()
    restarted, _ = _service(tmp_path / "member", identity, "Bailey", vault_key=key)
    try:
        assert restarted.preview_workspace_invitation(fresh)["can_resume_join"] is True
        for operation in (_op(98402), _op(98403)):
            retry = restarted.submit_workspace_join(fresh, operation)
            assert (retry["local_member_id"], retry["local_device_id"]) == (joined["local_member_id"], joined["local_device_id"])
        assert len(restarted._require_workspace(wid)["local_membership_history"]) == 1
    finally:
        restarted.close()


def test_android_reviews_and_submits_fresh_contact_invitation_after_removal(pair, monkeypatch):
    from mesh_chat import mobile_bridge

    owner, onet, owner_profile, member, mnet, member_profile, workspace, *_ = pair
    wid = workspace["id"]
    old_member_id = member._require_workspace(wid)["local_member_id"]
    for service, peer in ((owner, member_profile), (member, owner_profile)):
        service.store.put("contact", "peer", Contact(
            id="peer", display_name=peer["display_name"],
            public_identity=peer["public_identity"], identity_hash=peer["identity_hash"],
            destination_hash=peer["destination_hash"], fingerprint=peer["fingerprint"],
            trust=TrustState.VERIFIED, created_at=1, updated_at=1,
        ).to_dict())
    owner.remove_workspace_member(wid, old_member_id, _op(98500))
    exchange(owner, onet, member)
    sent = owner.invite_contact_to_workspace(wid, "peer")
    member._receive_workspace_contact_invite(member.store.get("contact", "peer"), SimpleNamespace(
        invitation=sent["invitation"]["value"], logical_id=_op(98501), conversation_id=_op(98502),
    ))
    prompt = member.snapshot()["workspace_invitation_prompts"][0]
    monkeypatch.setattr(mobile_bridge, "_service", member)

    def command(name, **payload):
        response = json.loads(mobile_bridge.command(json.dumps({"command": name, "payload": payload})))
        assert response["ok"], response
        return response["result"]

    preview = command("preview_workspace_invitation_prompt", prompt_id=prompt["id"])
    assert preview["can_rejoin"] is True
    joined = command("submit_workspace_invitation_prompt", prompt_id=prompt["id"], operation_id=_op(98503))
    assert joined["state"] == "joining"
    assert joined["local_member_id"] != old_member_id
    exchange(member, mnet, owner)
    pending = next(item for item in owner.workspace_snapshot()["workspace_join_requests"] if item["state"] == "pending")
    owner.approve_workspace_join(wid, pending["id"], _op(98504))
    exchange(owner, onet, member)
    assert member._require_workspace(wid)["state"] == "active"
