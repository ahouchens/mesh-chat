from __future__ import annotations

import json
import os
import time
import uuid

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import (
    M_GROUP_DOCUMENT,
    M_GROUP_EPOCH,
    M_GROUP_ID,
    M_GROUP_MANIFEST_HASH,
    M_GROUP_MESSAGE_ID,
    M_KIND,
    M_SENDER_SEQUENCE,
    META_FIELD,
    build_fields,
    parse_payload,
)
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.group_protocol import (
    MAX_GROUP_MEMBERS,
    GroupManifestMemberInput,
    can_post,
    create_group_genesis,
    create_group_invitation,
    create_group_join_statement,
    create_group_leave_request,
    create_group_manifest,
    create_member_card,
    verify_group_genesis,
    verify_group_invitation,
    verify_group_join_statement,
    verify_group_leave_request,
    verify_group_manifest,
    verify_manifest_transition,
)
from mesh_chat.models import GroupPostingPolicy, GroupRole, GroupStatus, MessageKind

NOW = 1_800_000_000


def _destination(identity: RNS.Identity) -> bytes:
    return RNS.Destination.hash(identity, "lxmf", "delivery")


def _group_message(
    *,
    kind: MessageKind,
    fields: dict[int, object],
    text: str,
) -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=text,
        fields=fields,
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=os.urandom(16),
        source_hash=os.urandom(16),
    )


def test_genesis_manifest_invite_and_join_round_trip() -> None:
    owner = RNS.Identity()
    invitee = RNS.Identity()
    genesis_created = create_group_genesis(
        owner,
        "Lakewatcher Operations",
        "Alex",
        posting_policy=GroupPostingPolicy.OWNER_ADMINS,
        now=NOW,
        nonce=b"g" * 32,
    )
    genesis = verify_group_genesis(genesis_created.serialized, now=NOW + 1)
    assert genesis.group_id == genesis_created.group_id
    assert genesis.owner.destination_hash == _destination(owner)
    assert genesis.posting_policy == GroupPostingPolicy.OWNER_ADMINS

    initial_manifest_raw = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        title=genesis.title,
        posting_policy=genesis.posting_policy,
        members=[
            GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER)
        ],
        now=NOW,
    )
    initial_manifest = verify_group_manifest(initial_manifest_raw, now=NOW + 1)
    invite = create_group_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=initial_manifest.serialized,
        invitee_destination=_destination(invitee),
        now=NOW,
        nonce=b"i" * 32,
    )
    checked_invite = verify_group_invitation(
        invite,
        expected_group_id=genesis.group_id,
        expected_owner_destination=_destination(owner),
        expected_invitee_destination=_destination(invitee),
        now=NOW + 1,
    )
    assert checked_invite.genesis.digest == genesis.digest
    assert checked_invite.manifest.digest == initial_manifest.digest
    join = create_group_join_statement(invitee, checked_invite, "Bailey", now=NOW + 1)
    checked_join = verify_group_join_statement(
        join, invitation=invite, now=NOW + 1
    )
    assert checked_join.member.destination_hash == _destination(invitee)
    assert checked_join.invite_nonce == b"i" * 32

    manifest_raw = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=2,
        previous_manifest_hash=initial_manifest.digest,
        title=genesis.title,
        posting_policy=genesis.posting_policy,
        members=[
            GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER),
            GroupManifestMemberInput(checked_join.member.serialized, GroupRole.MEMBER),
        ],
        now=NOW + 2,
    )
    manifest = verify_group_manifest(
        manifest_raw,
        expected_group_id=genesis.group_id,
        expected_owner_destination=_destination(owner),
        expected_previous_hash=initial_manifest.digest,
        expected_epoch=2,
        now=NOW + 3,
    )
    assert len(manifest.members) == 2
    assert manifest.members[0].card.destination_hash < manifest.members[1].card.destination_hash
    assert {member.role for member in manifest.members} == {
        GroupRole.OWNER,
        GroupRole.MEMBER,
    }
    assert can_post(manifest, _destination(owner))
    assert not can_post(manifest, _destination(invitee))

    assert verify_manifest_transition(initial_manifest_raw, genesis, now=NOW + 1).epoch == 1
    assert verify_manifest_transition(manifest_raw, initial_manifest, now=NOW + 3).epoch == 2


def test_manifest_rejects_tampering_and_unexpected_chain_state() -> None:
    owner = RNS.Identity()
    genesis_created = create_group_genesis(owner, "Farm", "Alex", now=NOW, nonce=b"n" * 32)
    genesis = verify_group_genesis(genesis_created.serialized, now=NOW)
    raw = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        title="Farm",
        posting_policy=GroupPostingPolicy.MEMBERS,
        members=[GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER)],
        now=NOW,
    )
    tampered = json.loads(raw)
    tampered["title"] = "Mallory's group"
    with pytest.raises(IdentityMismatch):
        verify_group_manifest(json.dumps(tampered), now=NOW)
    with pytest.raises(ValidationError, match="does not extend"):
        verify_group_manifest(raw, expected_previous_hash="00" * 32, now=NOW)
    with pytest.raises(ValidationError, match="epoch"):
        verify_group_manifest(raw, expected_epoch=2, now=NOW)


def test_manifest_rejects_more_than_mvp_member_cap() -> None:
    owner = RNS.Identity()
    genesis_created = create_group_genesis(owner, "Farm", "Owner", now=NOW)
    genesis = verify_group_genesis(genesis_created.serialized, now=NOW)
    inputs = [GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER)]
    for index in range(MAX_GROUP_MEMBERS):
        identity = RNS.Identity()
        card = create_member_card(
            identity,
            f"Member {index}",
            group_id=genesis.group_id,
            now=NOW,
        )
        inputs.append(GroupManifestMemberInput(card, GroupRole.MEMBER))
    with pytest.raises(ValidationError, match="member count"):
        create_group_manifest(
            owner,
            group_id=genesis.group_id,
            epoch=1,
            previous_manifest_hash=genesis.digest,
            title="Farm",
            posting_policy=GroupPostingPolicy.MEMBERS,
            members=inputs,
            now=NOW,
        )


def test_member_card_carries_at_most_two_signed_route_hints() -> None:
    owner = RNS.Identity()
    created = create_group_genesis(
        owner,
        "Farm",
        "Owner",
        owner_hints=[
            {"type": "tcp", "host": "192.0.2.10", "port": 4242},
            {"type": "tcp", "host": "farm.example", "port": 4243},
        ],
        now=NOW,
    )
    genesis = verify_group_genesis(created.serialized, now=NOW)
    assert genesis.owner.hints[0]["host"] == "192.0.2.10"
    assert genesis.owner.hints[1]["host"] == "farm.example"

    with pytest.raises(ValidationError, match="connection hints"):
        create_member_card(
            owner,
            "Owner",
            group_id=created.group_id,
            hints=[
                {"type": "tcp", "host": f"192.0.2.{index}", "port": 4242}
                for index in range(1, 4)
            ],
            now=NOW,
        )


def test_join_statement_is_bound_to_invitation_identity_and_nonce() -> None:
    owner = RNS.Identity()
    invitee = RNS.Identity()
    other = RNS.Identity()
    genesis = create_group_genesis(owner, "Farm", "Owner", now=NOW)
    checked_genesis = verify_group_genesis(genesis.serialized, now=NOW)
    manifest = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=1,
        previous_manifest_hash=checked_genesis.digest,
        title="Farm",
        posting_policy=GroupPostingPolicy.MEMBERS,
        members=[GroupManifestMemberInput(genesis.member_card, GroupRole.OWNER)],
        now=NOW,
    )
    invite = create_group_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest,
        invitee_destination=_destination(invitee),
        now=NOW,
    )
    with pytest.raises(IdentityMismatch, match="another identity"):
        create_group_join_statement(other, invite, "Mallory", now=NOW + 1)

    join = create_group_join_statement(invitee, invite, "Bailey", now=NOW + 1)
    second_invite = create_group_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest,
        invitee_destination=_destination(invitee),
        now=NOW,
    )
    with pytest.raises(ValidationError, match="does not match"):
        verify_group_join_statement(join, invitation=second_invite, now=NOW + 1)


def test_member_can_request_leave_and_owner_can_close_terminally() -> None:
    owner = RNS.Identity()
    member = RNS.Identity()
    genesis_created = create_group_genesis(owner, "Farm", "Owner", now=NOW)
    genesis = verify_group_genesis(genesis_created.serialized, now=NOW)
    member_card = create_member_card(member, "Bailey", group_id=genesis.group_id, now=NOW)
    active_raw = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        title="Farm",
        posting_policy=GroupPostingPolicy.MEMBERS,
        members=[
            GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER),
            GroupManifestMemberInput(member_card, GroupRole.MEMBER),
        ],
        now=NOW,
    )
    active = verify_manifest_transition(active_raw, genesis, now=NOW)
    leave_raw = create_group_leave_request(member, active, now=NOW + 1)
    leave = verify_group_leave_request(leave_raw, manifest=active, now=NOW + 1)
    assert leave.leaver_destination == _destination(member)
    assert leave.manifest_hash == active.digest
    with pytest.raises(ValidationError, match="owner cannot leave"):
        create_group_leave_request(owner, active, now=NOW + 1)

    closed_raw = create_group_manifest(
        owner,
        group_id=genesis.group_id,
        epoch=2,
        previous_manifest_hash=active.digest,
        title="Farm",
        posting_policy=GroupPostingPolicy.MEMBERS,
        status=GroupStatus.CLOSED,
        members=[
            GroupManifestMemberInput(genesis_created.member_card, GroupRole.OWNER),
            GroupManifestMemberInput(member_card, GroupRole.MEMBER),
        ],
        now=NOW + 2,
    )
    closed = verify_manifest_transition(closed_raw, active, now=NOW + 2)
    assert closed.status == GroupStatus.CLOSED
    assert not can_post(closed, _destination(owner))
    with pytest.raises(ValidationError, match="Closed groups"):
        create_group_invitation(
            owner,
            genesis=genesis.serialized,
            manifest=closed.serialized,
            invitee_destination=_destination(RNS.Identity()),
            now=NOW + 3,
        )
    with pytest.raises(ValidationError, match="Closed groups"):
        verify_manifest_transition(closed_raw, closed, now=NOW + 3)


def test_group_chat_wire_metadata_round_trip_and_dm_shape_is_unchanged() -> None:
    logical_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    group_message_id = str(uuid.uuid4())
    fields = build_fields(
        kind=MessageKind.GROUP_CHAT,
        logical_id=logical_id,
        conversation=conversation_id,
        expires_at=int(time.time()) + 60,
        group_id=group_id,
        group_epoch=3,
        group_manifest_hash="ab" * 32,
        sender_sequence=7,
        group_message_id=group_message_id,
    )
    parsed = parse_payload(
        _group_message(kind=MessageKind.GROUP_CHAT, fields=fields, text="Status update")
    )
    assert parsed.group_id == group_id
    assert parsed.group_epoch == 3
    assert parsed.group_manifest_hash == "ab" * 32
    assert parsed.sender_sequence == 7
    assert parsed.group_message_id == group_message_id
    assert set(fields[META_FIELD]) >= {
        M_GROUP_ID,
        M_GROUP_EPOCH,
        M_GROUP_MANIFEST_HASH,
        M_SENDER_SEQUENCE,
        M_GROUP_MESSAGE_ID,
    }

    dm_fields = build_fields(
        kind=MessageKind.CHAT,
        logical_id=str(uuid.uuid4()),
        conversation=str(uuid.uuid4()),
        expires_at=int(time.time()) + 60,
    )
    assert dm_fields[META_FIELD][M_KIND] == MessageKind.CHAT.value
    assert not set(dm_fields[META_FIELD]) & {
        M_GROUP_ID,
        M_GROUP_EPOCH,
        M_GROUP_MANIFEST_HASH,
        M_SENDER_SEQUENCE,
        M_GROUP_DOCUMENT,
        M_GROUP_MESSAGE_ID,
    }


def test_group_receipt_has_copy_reference_and_common_message_id() -> None:
    group_message_id = str(uuid.uuid4())
    copy_id = str(uuid.uuid4())
    fields = build_fields(
        kind=MessageKind.GROUP_RECEIPT,
        logical_id=str(uuid.uuid4()),
        conversation=str(uuid.uuid4()),
        expires_at=int(time.time()) + 60,
        receipt_for=copy_id,
        group_id=str(uuid.uuid4()),
        group_epoch=1,
        group_manifest_hash="cd" * 32,
        group_message_id=group_message_id,
    )
    parsed = parse_payload(
        _group_message(kind=MessageKind.GROUP_RECEIPT, fields=fields, text="")
    )
    assert parsed.receipt_for == copy_id
    assert parsed.group_message_id == group_message_id


def test_group_wire_rejects_missing_common_id_and_dm_group_metadata() -> None:
    common = {
        "logical_id": str(uuid.uuid4()),
        "conversation": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 60,
    }
    with pytest.raises(ValidationError, match="Group message ID"):
        build_fields(
            kind=MessageKind.GROUP_CHAT,
            group_id=str(uuid.uuid4()),
            group_epoch=1,
            group_manifest_hash="ef" * 32,
            sender_sequence=0,
            **common,
        )
    with pytest.raises(ValidationError, match="Group metadata"):
        build_fields(kind=MessageKind.CHAT, group_id=str(uuid.uuid4()), **common)
