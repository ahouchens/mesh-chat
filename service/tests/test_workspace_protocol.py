from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import TYPE_FIELD as LEGACY_TYPE_FIELD, build_fields
from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.models import MessageKind, WorkspacePostingPolicy, WorkspaceRole
from mesh_chat.network import ReticulumNetwork, validate_unknown_source_signature
from mesh_chat.workspace_protocol import (
    MAX_CHANNEL_FETCH_CONTROLS,
    MAX_CHANNEL_SUMMARY_ENTRIES,
    MAX_CHANNEL_SUMMARY_PAGES,
    MAX_HISTORY_RESPONSE_BYTES,
    MAX_WORKSPACE_DOCUMENT_BYTES,
    WorkspaceManifestMemberInput,
    create_workspace_device_card,
    create_workspace_display_name_request,
    create_workspace_display_name_decision,
    create_workspace_channel_record,
    create_workspace_channel_fetch,
    create_workspace_channel_manifest,
    create_workspace_channel_recovery,
    create_workspace_channel_summary,
    create_workspace_channel_transfer,
    create_workspace_channel_transfer_offer,
    create_workspace_event,
    create_workspace_event_checkpoint,
    create_workspace_history_request,
    create_workspace_history_response,
    create_workspace_mutation_event,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_join,
    create_workspace_manifest,
    derive_workspace_id,
    verify_workspace_channel_record,
    verify_workspace_channel_fetch,
    verify_workspace_channel_manifest,
    verify_workspace_channel_manifest_transition,
    verify_workspace_channel_recovery,
    verify_workspace_channel_record_transition,
    verify_workspace_channel_summary,
    verify_workspace_channel_transfer,
    verify_workspace_channel_transfer_offer,
    verify_workspace_event,
    verify_workspace_event_checkpoint,
    verify_workspace_history_request,
    verify_workspace_history_response,
    verify_workspace_display_name_request,
    verify_workspace_display_name_decision,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_join,
    verify_workspace_manifest_transition,
    workspace_direct_conversation_id,
    workspace_invitation_formats,
)
from mesh_chat.workspace_wire import (
    WORKSPACE_CUSTOM_TYPE,
    build_workspace_fields,
    parse_workspace_payload,
)


NOW = 1_800_000_000


def _id() -> str:
    return str(uuid.uuid4())


def _workspace() -> tuple[RNS.Identity, object, object, object]:
    owner = RNS.Identity()
    created = create_workspace_genesis(
        owner,
        "Lakewatcher Operations",
        "Private field coordination",
        "Alex",
        now=NOW,
        nonce=b"w" * 32,
        owner_member_id=_id(),
        authority_device_id=_id(),
    )
    genesis = verify_workspace_genesis(created.serialized, now=NOW)
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name=genesis.name,
        description=genesis.description,
        authority_device_id=genesis.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            )
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, genesis, now=NOW)
    return owner, created, genesis, manifest


def _history_documents() -> tuple[object, object, object, object, str, object, str]:
    owner, created, genesis, manifest = _workspace()
    channel_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="history",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW,
    )
    channel = verify_workspace_channel_record(channel_raw, manifest=manifest, now=NOW)
    event_raw = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="retained before catch-up",
        created_at=NOW,
    )
    event = verify_workspace_event(event_raw, manifest=manifest, channel=channel, now=NOW)
    request_raw = create_workspace_history_request(
        owner,
        workspace_id=genesis.workspace_id,
        request_id=_id(),
        requester_member_id=genesis.owner_member_id,
        requester_device_id=genesis.authority_device_id,
        manifest_digest=manifest.digest,
        scope={
            "kind": "public",
            "conversation_id": channel.channel_id,
            "channel_digest": channel.digest,
            "participant_member_ids": [],
        },
        streams=[{
            "author_device_id": genesis.authority_device_id,
            "known_high_water": 0,
            "retained_floor": 1,
            "head_digest": None,
            "seen_ranges": [],
            "gaps": [],
            "request_ranges": [[1, 10]],
        }],
        event_limit=8,
        byte_limit=MAX_HISTORY_RESPONSE_BYTES,
        nonce=b"h" * 32,
        replay_key=_id(),
        created_at=NOW,
        expires_at=NOW + 600,
    )
    request = verify_workspace_history_request(request_raw, manifest=manifest, now=NOW)
    return owner, genesis, manifest, channel, event_raw, request, channel_raw


def test_history_checkpoint_request_and_response_are_canonical_and_bound() -> None:
    owner, genesis, manifest, channel, event_raw, request, channel_raw = _history_documents()
    event = verify_workspace_event(event_raw, manifest=manifest, channel=channel, now=NOW)
    checkpoint_raw = create_workspace_event_checkpoint(
        owner,
        workspace_id=genesis.workspace_id,
        checkpoint_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        manifest_digest=manifest.digest,
        streams=[{
            "conversation_id": channel.channel_id,
            "channel_digest": channel.digest,
            "high_water": 1,
            "head_digest": event.digest,
        }],
        created_at=NOW,
    )
    checkpoint = verify_workspace_event_checkpoint(checkpoint_raw, manifest=manifest, now=NOW)
    assert checkpoint.streams[0]["head_digest"] == event.digest
    response_raw = create_workspace_history_response(
        owner,
        request=request,
        response_id=_id(),
        responder_member_id=genesis.owner_member_id,
        responder_device_id=genesis.authority_device_id,
        page_index=0,
        previous_response_digest=None,
        controls=[("workspace_channel_record", channel_raw)],
        checkpoints=[checkpoint_raw],
        events=[event_raw],
        complete=True,
        created_at=NOW,
    )
    response = verify_workspace_history_response(
        response_raw, manifest=manifest, request=request, now=NOW
    )
    assert response.events == (event_raw,)
    assert response.controls == (("workspace_channel_record", channel_raw),)
    assert response.complete is True


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id", "request_id", "request_digest", "requester_member_id",
        "requester_device_id", "request_nonce", "request_replay_key", "scope",
        "event_limit", "byte_limit", "expires_at",
    ],
)
def test_history_response_rejects_tampered_request_binding(field: str) -> None:
    owner, genesis, manifest, _channel, event_raw, request, _channel_raw = _history_documents()
    raw = create_workspace_history_response(
        owner,
        request=request,
        response_id=_id(),
        responder_member_id=genesis.owner_member_id,
        responder_device_id=genesis.authority_device_id,
        page_index=0,
        previous_response_digest=None,
        events=[event_raw],
        complete=True,
        created_at=NOW,
    )
    value = json.loads(raw)
    if field in {"event_limit", "byte_limit", "expires_at"}:
        value[field] += 1
    elif field == "scope":
        value[field] = {**value[field], "conversation_id": _id()}
    elif field == "request_nonce":
        value[field] = value[field][::-1]
    elif field in {"request_digest"}:
        value[field] = "0" * 64
    else:
        value[field] = _id()
    tampered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_workspace_history_response(tampered, manifest=manifest, request=request, now=NOW)


def test_history_response_rejects_event_outside_requested_range_and_oversize() -> None:
    owner, genesis, manifest, channel, _event_raw, request, _channel_raw = _history_documents()
    outside = create_workspace_event(
        owner,
        workspace_id=manifest.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=11,
        previous_event_digest="1" * 64,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="outside",
        created_at=NOW,
    )
    raw = create_workspace_history_response(
        owner,
        request=request,
        response_id=_id(),
        responder_member_id=genesis.owner_member_id,
        responder_device_id=genesis.authority_device_id,
        page_index=0,
        previous_response_digest=None,
        events=[outside],
        complete=True,
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="requested range"):
        verify_workspace_history_response(raw, manifest=manifest, request=request, now=NOW)
    with pytest.raises(ValidationError, match="count limit"):
        create_workspace_history_response(
            owner,
            request=request,
            response_id=_id(),
            responder_member_id=genesis.owner_member_id,
            responder_device_id=genesis.authority_device_id,
            page_index=0,
            previous_response_digest=None,
            events=[outside] * 9,
            created_at=NOW,
        )


@pytest.mark.parametrize(
    ("initial_retention", "retention_days"),
    [(90, 30), (30, 90), (90, 365), (90, None)],
)
def test_manifest_allows_one_owner_signed_retention_transition(
    initial_retention: int, retention_days: int | None
) -> None:
    owner, _created, _genesis, manifest = _workspace()
    if initial_retention != 90:
        initial_raw = create_workspace_manifest(
            owner,
            workspace_id=manifest.workspace_id,
            epoch=manifest.epoch + 1,
            previous_manifest_hash=manifest.digest,
            name=manifest.name,
            description=manifest.description,
            authority_device_id=manifest.authority_device_id,
            retention_days=initial_retention,
            members=[
                WorkspaceManifestMemberInput(
                    member.member_id,
                    member.display_name,
                    member.role,
                    [device.serialized for device in member.devices],
                    member.status,
                )
                for member in manifest.members
            ],
            now=NOW + 1,
        )
        manifest = verify_workspace_manifest_transition(
            initial_raw, manifest, now=NOW + 1
        )
    raw = create_workspace_manifest(
        owner,
        workspace_id=manifest.workspace_id,
        epoch=manifest.epoch + 1,
        previous_manifest_hash=manifest.digest,
        name=manifest.name,
        description=manifest.description,
        authority_device_id=manifest.authority_device_id,
        retention_days=retention_days,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                member.role,
                [device.serialized for device in member.devices],
                member.status,
            )
            for member in manifest.members
        ],
        now=NOW + 2,
    )
    updated = verify_workspace_manifest_transition(raw, manifest, now=NOW + 2)
    assert updated.retention_days == retention_days


def test_manifest_rejects_non_authority_retention_transition() -> None:
    _owner, _created, _genesis, manifest = _workspace()
    attacker = RNS.Identity()
    with pytest.raises(IdentityMismatch):
        create_workspace_manifest(
            attacker,
            workspace_id=manifest.workspace_id,
            epoch=manifest.epoch + 1,
            previous_manifest_hash=manifest.digest,
            name=manifest.name,
            description=manifest.description,
            authority_device_id=manifest.authority_device_id,
            retention_days=30,
            members=[
                WorkspaceManifestMemberInput(
                    member.member_id,
                    member.display_name,
                    member.role,
                    [device.serialized for device in member.devices],
                    member.status,
                )
                for member in manifest.members
            ],
            now=NOW + 1,
        )


def test_thread_root_is_signed_without_changing_ordinary_event_bytes() -> None:
    owner, created, genesis, manifest = _workspace()
    channel_raw = create_workspace_channel_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="general",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        member_ids=[genesis.owner_member_id],
        now=NOW,
    )
    channel = verify_workspace_channel_manifest(
        channel_raw, manifest=manifest, now=NOW
    )
    event_id = _id()
    ordinary = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=event_id,
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="ordinary bytes stay stable",
        audience_member_ids=channel.member_ids,
        created_at=NOW + 1,
    )
    explicit_null = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=event_id,
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="ordinary bytes stay stable",
        thread_root=None,
        audience_member_ids=channel.member_ids,
        created_at=NOW + 1,
    )
    assert ordinary == explicit_null
    assert json.loads(ordinary)["thread_root"] is None
    verified_root = verify_workspace_event(
        ordinary, manifest=manifest, channel=channel, now=NOW + 1
    )
    assert verified_root.thread_root is None

    reply = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=2,
        previous_event_digest=verified_root.digest,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="one level only",
        thread_root=event_id,
        audience_member_ids=channel.member_ids,
        created_at=NOW + 2,
    )
    verified_reply = verify_workspace_event(
        reply, manifest=manifest, channel=channel, now=NOW + 2
    )
    assert verified_reply.thread_root == event_id
    tampered = json.loads(reply)
    tampered["thread_root"] = _id()
    with pytest.raises(IdentityMismatch, match="signature"):
        verify_workspace_event(
            json.dumps(tampered, separators=(",", ":"), sort_keys=True),
            manifest=manifest,
            channel=channel,
            now=NOW + 2,
        )


def test_workspace_bootstrap_join_channel_and_event_round_trip() -> None:
    owner, created, genesis, initial = _workspace()
    invitee = RNS.Identity()
    invitation_raw = create_workspace_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=initial.serialized,
        nonce=b"i" * 32,
        now=NOW,
    )
    invitation = verify_workspace_invitation(invitation_raw, now=NOW)
    assert invitation.preview()["member_count"] == 1
    assert verify_workspace_invitation(
        workspace_invitation_formats(invitation_raw, now=NOW)["link"], now=NOW
    ).serialized == invitation.serialized

    join_raw = create_workspace_join(
        invitee,
        invitation,
        "Bailey",
        member_id=_id(),
        device_id=_id(),
        now=NOW + 1,
    )
    join = verify_workspace_join(join_raw, invitation=invitation, now=NOW + 1)
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                member.role,
                [device.serialized for device in member.devices],
            )
            for member in initial.members
        ]
        + [
            WorkspaceManifestMemberInput(
                join.member_id,
                join.device.display_name,
                WorkspaceRole.MEMBER,
                [join.device.serialized],
            )
        ],
        now=NOW + 2,
    )
    combined_close = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                member.role,
                [device.serialized for device in member.devices],
            )
            for member in initial.members
        ]
        + [
            WorkspaceManifestMemberInput(
                join.member_id,
                join.device.display_name,
                WorkspaceRole.MEMBER,
                [join.device.serialized],
            )
        ],
        status="closed",
        now=NOW + 2,
    )
    with pytest.raises(ValidationError, match="closure cannot change membership"):
        verify_workspace_manifest_transition(combined_close, initial, now=NOW + 2)
    manifest = verify_workspace_manifest_transition(
        manifest_raw, initial, now=NOW + 2
    )
    # Protocol v1 already allowed a later owner-authorized checkpoint in a
    # fresh invitation. Pin it to genesis without narrowing that valid wire
    # behavior to epoch one.
    later_invitation = create_workspace_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest.serialized,
        nonce=b"l" * 32,
        now=NOW + 2,
    )
    assert verify_workspace_invitation(
        later_invitation, now=NOW + 2
    ).offered_manifest.epoch == 2
    channel_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=initial.digest,
        name="general",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW,
    )
    channel = verify_workspace_channel_record(
        channel_raw, manifest=initial, now=NOW
    )
    event_raw = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="Water level is stable.",
        created_at=NOW + 3,
    )
    event = verify_workspace_event(
        event_raw, manifest=manifest, channel=channel, now=NOW + 3
    )
    assert event.text == "Water level is stable."
    assert len(manifest.members) == 2


def test_workspace_mutation_events_bind_target_revision_and_payload() -> None:
    owner, _created, genesis, manifest = _workspace()
    channel = verify_workspace_channel_record(
        create_workspace_channel_record(
            owner,
            workspace_id=genesis.workspace_id,
            channel_id=_id(),
            manifest_digest=manifest.digest,
            name="general",
            topic="",
            manager_member_id=genesis.owner_member_id,
            manager_device_id=genesis.authority_device_id,
            now=NOW,
        ),
        manifest=manifest,
        now=NOW,
    )
    target = _id()
    previous: str | None = None
    for sequence, event_type, kwargs in (
        (1, "edit", {"text": "Corrected field note"}),
        (2, "delete", {}),
        (3, "reaction", {"emoji": "👍", "active": True}),
    ):
        raw = create_workspace_mutation_event(
            owner,
            workspace_id=genesis.workspace_id,
            conversation_id=channel.channel_id,
            event_id=_id(),
            event_type=event_type,
            author_member_id=genesis.owner_member_id,
            author_device_id=genesis.authority_device_id,
            sequence=sequence,
            previous_event_digest=previous,
            manifest_digest=manifest.digest,
            channel_digest=channel.digest,
            target_event_id=target,
            base_revision=sequence - 1,
            revision=sequence,
            created_at=NOW,
            **kwargs,
        )
        event = verify_workspace_event(
            raw, manifest=manifest, channel=channel, now=NOW
        )
        assert event.event_type == event_type
        assert event.target_event_id == target
        assert event.base_revision == sequence - 1
        assert event.revision == sequence
        previous = event.digest

    with pytest.raises(ValidationError, match="revision"):
        create_workspace_mutation_event(
            owner,
            workspace_id=genesis.workspace_id,
            conversation_id=channel.channel_id,
            event_id=_id(),
            event_type="edit",
            author_member_id=genesis.owner_member_id,
            author_device_id=genesis.authority_device_id,
            sequence=4,
            previous_event_digest=previous,
            manifest_digest=manifest.digest,
            channel_digest=channel.digest,
            target_event_id=target,
            base_revision=1,
            revision=3,
            text="Skipped base",
        )


def test_workspace_mentions_are_canonical_structured_and_audience_bound() -> None:
    owner, created, genesis, initial = _workspace()
    member_identity = RNS.Identity()
    member_id = _id()
    member_device_id = _id()
    member_card = create_workspace_device_card(
        member_identity,
        workspace_id=genesis.workspace_id,
        member_id=member_id,
        device_id=member_device_id,
        display_name="Bailey",
        now=NOW,
    )
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            ),
            WorkspaceManifestMemberInput(
                member_id,
                "Bailey",
                WorkspaceRole.MEMBER,
                [member_card],
            ),
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, initial, now=NOW)
    channel_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="general",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW,
    )
    channel = verify_workspace_channel_record(
        channel_raw, manifest=manifest, now=NOW
    )
    mentioned = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="@Bailey inspect the north gauge",
        mention_member_ids=[member_id],
        created_at=NOW + 1,
    )
    assert json.loads(mentioned)["mentions"] == [member_id]
    verified = verify_workspace_event(
        mentioned, manifest=manifest, channel=channel, now=NOW + 1
    )
    assert verified.mentions == (member_id,)

    edited = create_workspace_mutation_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        event_type="edit",
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=2,
        previous_event_digest=verified.digest,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        target_event_id=verified.event_id,
        base_revision=0,
        revision=1,
        text="@Bailey inspect the south gauge",
        mention_member_ids=[member_id],
        created_at=NOW + 2,
    )
    assert verify_workspace_event(
        edited, manifest=manifest, channel=channel, now=NOW + 2
    ).mentions == (member_id,)
    with pytest.raises(ValidationError, match="mentions"):
        create_workspace_mutation_event(
            owner,
            workspace_id=genesis.workspace_id,
            conversation_id=channel.channel_id,
            event_id=_id(),
            event_type="delete",
            author_member_id=genesis.owner_member_id,
            author_device_id=genesis.authority_device_id,
            sequence=3,
            previous_event_digest=verified.digest,
            manifest_digest=manifest.digest,
            channel_digest=channel.digest,
            target_event_id=verified.event_id,
            base_revision=0,
            revision=1,
            mention_member_ids=[member_id],
            created_at=NOW + 3,
        )

    raw_text_only = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=3,
        previous_event_digest=verified.digest,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="@Bailey is ordinary text without picker metadata",
        created_at=NOW + 3,
    )
    assert verify_workspace_event(
        raw_text_only, manifest=manifest, channel=channel, now=NOW + 3
    ).mentions == ()

    unauthorized = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=4,
        previous_event_digest=verified.digest,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="Invisible mention",
        mention_member_ids=[_id()],
        created_at=NOW + 4,
    )
    with pytest.raises(IdentityMismatch, match="mention audience"):
        verify_workspace_event(
            unauthorized, manifest=manifest, channel=channel, now=NOW + 4
        )

    private_raw = create_workspace_channel_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="owner-only",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        member_ids=[genesis.owner_member_id],
        now=NOW,
    )
    private = verify_workspace_channel_manifest(
        private_raw, manifest=manifest, now=NOW
    )
    leaked = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=private.channel_id,
        event_id=_id(),
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=private.digest,
        text="Private metadata must stay private",
        audience_member_ids=private.member_ids,
        mention_member_ids=[member_id],
        created_at=NOW + 1,
    )
    with pytest.raises(IdentityMismatch, match="mention audience"):
        verify_workspace_event(
            leaked, manifest=manifest, channel=private, now=NOW + 1
        )


def test_workspace_documents_fail_closed_on_tampering_expiry_and_wrong_signer() -> None:
    owner, _created, genesis, manifest = _workspace()
    raw = create_workspace_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest.serialized,
        lifetime_seconds=10,
        now=NOW,
    )
    with pytest.raises(InvitationExpired):
        verify_workspace_invitation(raw, now=NOW + 11)

    with pytest.raises(ValidationError, match="not canonical"):
        verify_workspace_invitation(raw.replace(',"', ', "', 1), now=NOW)

    tampered = json.loads(raw)
    tampered["expires_at"] += 100
    with pytest.raises(IdentityMismatch):
        verify_workspace_invitation(
            json.dumps(tampered, separators=(",", ":"), sort_keys=True), now=NOW
        )


def test_eight_member_manifest_metadata_and_display_name_transitions_fit_wire() -> None:
    owner, _created, genesis, manifest = _workspace()
    admitted: list[tuple[RNS.Identity, str, str]] = []
    for index in range(7):
        identity = RNS.Identity()
        member_id = _id()
        device_id = _id()
        card = create_workspace_device_card(
            identity,
            workspace_id=genesis.workspace_id,
            member_id=member_id,
            device_id=device_id,
            display_name=f"Member {index + 1}",
            now=NOW + index + 1,
        )
        raw = create_workspace_manifest(
            owner,
            workspace_id=genesis.workspace_id,
            epoch=manifest.epoch + 1,
            previous_manifest_hash=manifest.digest,
            name=manifest.name,
            description=manifest.description,
            authority_device_id=manifest.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    member.member_id,
                    member.display_name,
                    member.role,
                    [device.serialized for device in member.devices],
                    member.status,
                )
                for member in manifest.members
            ]
            + [
                WorkspaceManifestMemberInput(
                    member_id,
                    f"Member {index + 1}",
                    WorkspaceRole.MEMBER,
                    [card],
                )
            ],
            now=NOW + index + 1,
        )
        manifest = verify_workspace_manifest_transition(
            raw, manifest, now=NOW + index + 1
        )
        admitted.append((identity, member_id, device_id))
    assert len(manifest.members) == 8
    assert len(manifest.serialized.encode("utf-8")) <= MAX_WORKSPACE_DOCUMENT_BYTES
    assert build_workspace_fields(
        kind="workspace_manifest_root",
        logical_id=_id(),
        workspace_id=genesis.workspace_id,
        expires_at=int(time.time()) + 60,
        document=manifest.serialized,
    )

    metadata_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=manifest.epoch + 1,
        previous_manifest_hash=manifest.digest,
        name="Eight-person field coordination",
        description="Metadata changes are authority-signed and catch up by epoch.",
        authority_device_id=manifest.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                member.role,
                [device.serialized for device in member.devices],
                member.status,
            )
            for member in manifest.members
        ],
        now=NOW + 8,
    )
    metadata = verify_workspace_manifest_transition(
        metadata_raw, manifest, now=NOW + 8
    )
    assert metadata.name == "Eight-person field coordination"

    identity, member_id, device_id = admitted[0]
    request_raw = create_workspace_display_name_request(
        identity,
        manifest=metadata,
        member_id=member_id,
        device_id=device_id,
        display_name="River lead",
        now=NOW + 9,
    )
    request = verify_workspace_display_name_request(
        request_raw, manifest=metadata, now=NOW + 9
    )
    decision_raw = create_workspace_display_name_decision(
        owner,
        manifest=metadata,
        request=request,
        approved=False,
        now=NOW + 9,
    )
    assert not verify_workspace_display_name_decision(
        decision_raw, manifest=metadata, request=request, now=NOW + 9
    ).approved
    renamed_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=metadata.epoch + 1,
        previous_manifest_hash=metadata.digest,
        name=metadata.name,
        description=metadata.description,
        authority_device_id=metadata.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                request.display_name
                if member.member_id == request.member_id
                else member.display_name,
                member.role,
                [request.replacement_device.serialized]
                if member.member_id == request.member_id
                else [device.serialized for device in member.devices],
                member.status,
            )
            for member in metadata.members
        ],
        now=NOW + 10,
    )
    renamed = verify_workspace_manifest_transition(
        renamed_raw, metadata, now=NOW + 10
    )
    assert next(
        member for member in renamed.members if member.member_id == member_id
    ).display_name == "River lead"

    tampered = json.loads(request_raw)
    tampered["display_name"] = "Mallory"
    with pytest.raises(ValidationError):
        verify_workspace_display_name_request(
            json.dumps(tampered, separators=(",", ":"), sort_keys=True),
            manifest=metadata,
            now=NOW + 9,
        )


def test_workspace_genesis_pins_the_initial_manifest_authority() -> None:
    _owner, _created, genesis, manifest = _workspace()
    attacker = RNS.Identity()
    attacker_member_id = _id()
    attacker_device_id = _id()
    attacker_card = create_workspace_device_card(
        attacker,
        workspace_id=genesis.workspace_id,
        member_id=attacker_member_id,
        device_id=attacker_device_id,
        display_name="Mallory",
        now=NOW,
    )
    forged = create_workspace_manifest(
        attacker,
        workspace_id=genesis.workspace_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name=genesis.name,
        description=genesis.description,
        authority_device_id=attacker_device_id,
        members=[
            WorkspaceManifestMemberInput(
                attacker_member_id,
                "Mallory",
                WorkspaceRole.OWNER,
                [attacker_card],
            )
        ],
        now=NOW,
    )
    with pytest.raises(IdentityMismatch):
        verify_workspace_manifest_transition(forged, genesis, now=NOW)
    with pytest.raises(IdentityMismatch):
        create_workspace_invitation(
            attacker,
            genesis=genesis.serialized,
            manifest=forged,
            now=NOW,
        )

    with pytest.raises(IdentityMismatch):
        create_workspace_invitation(
            RNS.Identity(),
            genesis=genesis.serialized,
            manifest=manifest.serialized,
            now=NOW,
        )


def test_workspace_id_and_wire_profile_are_isolated_from_legacy_chat() -> None:
    identity = RNS.Identity()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    assert derive_workspace_id(destination, b"n" * 32) == derive_workspace_id(
        destination, b"n" * 32
    )
    fields = build_workspace_fields(
        kind="workspace_event",
        logical_id=_id(),
        workspace_id=_id(),
        expires_at=int(time.time()) + 60,
        document=json.dumps({"type": "workspace_event"}),
    )
    native = LXMF.LXMessage(
        None,
        None,
        content="",
        fields=fields,
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=os.urandom(16),
        source_hash=os.urandom(16),
    )
    assert parse_workspace_payload(native).kind == "workspace_event"
    assert fields[LEGACY_TYPE_FIELD] == WORKSPACE_CUSTOM_TYPE

    legacy = build_fields(
        kind=MessageKind.CHAT,
        logical_id=_id(),
        conversation=_id(),
        expires_at=int(time.time()) + 60,
    )
    assert legacy[LEGACY_TYPE_FIELD] == b"mesh-chat"
    with pytest.raises(ValidationError):
        parse_workspace_payload(
            LXMF.LXMessage(
                None,
                None,
                content="hello",
                fields=legacy,
                desired_method=LXMF.LXMessage.DIRECT,
                destination_hash=os.urandom(16),
                source_hash=os.urandom(16),
            )
        )


def test_workspace_v1_canonical_serialization_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "workspace_v1.json").read_text(
            encoding="utf-8"
        )
    )
    owner = RNS.Identity.from_bytes(bytes(range(64)))
    joiner = RNS.Identity.from_bytes(bytes(range(64, 128)))
    assert owner is not None and joiner is not None
    created = create_workspace_genesis(
        owner,
        "Fixture Workspace",
        "Canonical v1 fixture",
        "Owner",
        now=NOW,
        nonce=b"w" * 32,
        owner_member_id="11111111-1111-4111-8111-111111111111",
        authority_device_id="22222222-2222-4222-8222-222222222222",
    )
    genesis = verify_workspace_genesis(created.serialized, now=NOW)
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name=genesis.name,
        description=genesis.description,
        authority_device_id=genesis.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                "Owner",
                WorkspaceRole.OWNER,
                [created.device_card],
            )
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, genesis, now=NOW)
    invitation_raw = create_workspace_invitation(
        owner,
        genesis=created.serialized,
        manifest=manifest_raw,
        now=NOW,
        lifetime_seconds=7 * 24 * 60 * 60,
        nonce=b"i" * 32,
    )
    invitation = verify_workspace_invitation(invitation_raw, now=NOW)
    join_raw = create_workspace_join(
        joiner,
        invitation,
        "Member",
        member_id="44444444-4444-4444-8444-444444444444",
        device_id="55555555-5555-4555-8555-555555555555",
        now=NOW + 1,
    )
    channel_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id="33333333-3333-4333-8333-333333333333",
        manifest_digest=manifest.digest,
        name="general",
        topic="",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW,
    )
    channel = verify_workspace_channel_record(channel_raw, manifest=manifest, now=NOW)
    event_raw = create_workspace_event(
        owner,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id="66666666-6666-4666-8666-666666666666",
        author_member_id=genesis.owner_member_id,
        author_device_id=genesis.authority_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="Fixture message",
        created_at=NOW + 2,
    )
    documents = {
        "device_card": created.device_card,
        "genesis": created.serialized,
        "manifest": manifest_raw,
        "invitation": invitation_raw,
        "join": join_raw,
        "channel": channel_raw,
        "event": event_raw,
    }
    assert genesis.workspace_id == fixture["workspace_id"]
    for name, raw in documents.items():
        expected = fixture["documents"][name]
        assert len(raw.encode("utf-8")) == expected["bytes"]
        assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == expected["sha256"]


def test_unknown_source_admission_is_limited_to_a_verified_workspace_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time", lambda: float(NOW))
    owner, _created, genesis, manifest = _workspace()
    joiner = RNS.Identity()
    invitation = create_workspace_invitation(
        owner,
        genesis=genesis.serialized,
        manifest=manifest.serialized,
        now=NOW,
    )
    join = create_workspace_join(
        joiner,
        invitation,
        "Bailey",
        member_id=_id(),
        device_id=_id(),
        now=NOW + 1,
    )
    local_destination = os.urandom(LXMF.LXMessage.DESTINATION_LENGTH)
    source = RNS.Destination.hash(joiner, "lxmf", "delivery")

    def message(kind: str, document: str, workspace_id: str = genesis.workspace_id):
        fields = build_workspace_fields(
            kind=kind,
            logical_id=_id(),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=document,
        )
        packed_payload = b"workspace-unknown-source-fixture"
        hashed_part = local_destination + source + packed_payload
        message_hash = RNS.Identity.full_hash(hashed_part)
        signature = joiner.sign(hashed_part + message_hash)
        return SimpleNamespace(
            content="",
            fields=fields,
            get_fields=lambda: fields,
            destination_hash=local_destination,
            source_hash=source,
            signature_validated=False,
            packed=local_destination + source + signature + packed_payload,
            hash=message_hash,
        )

    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.delivery_destination = SimpleNamespace(hash=local_destination)
    remembered: list[bytes] = []
    received: list[object] = []
    network.remember_contact = lambda _public, destination: remembered.append(destination)
    network._inbound_callback = received.append
    network._defer_callback = (
        lambda callback, *args, **_kwargs: (callback(*args), True)[1]
    )

    accepted = message("workspace_join", join)
    checked_wire = parse_workspace_payload(accepted)
    checked_join = verify_workspace_join(checked_wire.document)
    assert checked_join.workspace_id == checked_wire.workspace_id
    assert checked_join.device.destination_hash == accepted.source_hash
    assert validate_unknown_source_signature(
        accepted, checked_join.device.public_identity
    )
    network._on_inbound(accepted)
    assert accepted.signature_validated is True
    assert remembered == []
    assert received == [accepted]

    remembered.clear()
    received.clear()
    rejected_kind = message("workspace_event", json.dumps({"type": "workspace_event"}))
    network._on_inbound(rejected_kind)
    assert remembered == []
    assert received == []

    rejected_scope = message("workspace_join", join, workspace_id=_id())
    network._on_inbound(rejected_scope)
    assert remembered == []
    assert received == []


def test_public_channel_control_chain_transfer_recovery_and_bounded_sync() -> None:
    owner, created, genesis, initial = _workspace()
    successor = RNS.Identity()
    successor_member_id = _id()
    successor_device_id = _id()
    successor_card = create_workspace_device_card(
        successor,
        workspace_id=genesis.workspace_id,
        member_id=successor_member_id,
        device_id=successor_device_id,
        display_name="Bailey",
        now=NOW,
    )
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            ),
            WorkspaceManifestMemberInput(
                successor_member_id,
                "Bailey",
                WorkspaceRole.MEMBER,
                [successor_card],
            ),
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, initial, now=NOW)
    channel_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="field-notes",
        topic="Daily observations",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW,
    )
    channel = verify_workspace_channel_record(channel_raw, manifest=manifest, now=NOW)
    rename_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=channel.channel_id,
        manifest_digest=manifest.digest,
        name="Field Notes",
        topic="Daily observations and photos",
        manager_member_id=channel.manager_member_id,
        manager_device_id=channel.manager_device_id,
        version=2,
        previous_hash=channel.digest,
        now=NOW + 1,
    )
    renamed = verify_workspace_channel_record_transition(
        rename_raw, channel, manifest=manifest, now=NOW + 1
    )
    offer_raw = create_workspace_channel_transfer_offer(
        owner,
        channel=renamed,
        manifest=manifest,
        successor_member_id=successor_member_id,
        successor_device_id=successor_device_id,
        now=NOW + 2,
    )
    offer = verify_workspace_channel_transfer_offer(
        offer_raw, channel=renamed, manifest=manifest, now=NOW + 2
    )
    transfer_raw = create_workspace_channel_transfer(
        successor, offer=offer, now=NOW + 3
    )
    transferred = verify_workspace_channel_transfer(
        transfer_raw, channel=renamed, manifest=manifest, now=NOW + 3
    )
    assert transferred.manager_member_id == successor_member_id
    recovered_raw = create_workspace_channel_recovery(
        owner,
        channel=transferred,
        manifest=manifest,
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW + 4,
    )
    recovered = verify_workspace_channel_recovery(
        recovered_raw, channel=transferred, manifest=manifest, now=NOW + 4
    )
    assert recovered.manager_member_id == genesis.owner_member_id
    archive_raw = create_workspace_channel_record(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=channel.channel_id,
        manifest_digest=manifest.digest,
        name=recovered.name,
        topic=recovered.topic,
        manager_member_id=recovered.manager_member_id,
        manager_device_id=recovered.manager_device_id,
        version=recovered.version + 1,
        previous_hash=recovered.digest,
        archived=True,
        now=NOW + 5,
    )
    archived = verify_workspace_channel_record_transition(
        archive_raw, recovered, manifest=manifest, now=NOW + 5
    )
    assert archived.archived is True
    with pytest.raises(ValidationError, match="terminal"):
        verify_workspace_channel_record_transition(
            archive_raw, archived, manifest=manifest, now=NOW + 5
        )

    session_id = _id()
    summary_raw = create_workspace_channel_summary(
        successor,
        manifest=manifest,
        member_id=successor_member_id,
        device_id=successor_device_id,
        session_id=session_id,
        entries=[(archived.channel_id, archived.version, archived.digest)],
        now=NOW + 5,
    )
    summary = verify_workspace_channel_summary(
        summary_raw, manifest=manifest, now=NOW + 5
    )
    assert summary.entries == ((archived.channel_id, archived.version, archived.digest),)
    assert (summary.page_index, summary.page_count) == (0, 1)
    fetch_raw = create_workspace_channel_fetch(
        successor,
        manifest=manifest,
        member_id=successor_member_id,
        device_id=successor_device_id,
        session_id=session_id,
        requests=[(archived.channel_id, 2, renamed.digest)],
        max_controls=3,
        now=NOW + 5,
    )
    fetch = verify_workspace_channel_fetch(fetch_raw, manifest=manifest, now=NOW + 5)
    assert fetch.requests == ((archived.channel_id, 2, renamed.digest),)
    assert fetch.max_controls == 3

    forged_summary = json.loads(summary_raw)
    forged_summary["entries"][0]["version"] += 1
    with pytest.raises(IdentityMismatch, match="signature"):
        verify_workspace_channel_summary(
            json.dumps(forged_summary, separators=(",", ":"), sort_keys=True),
            manifest=manifest,
            now=NOW + 5,
        )
    too_many = [(_id(), 1, archived.digest) for _ in range(MAX_CHANNEL_SUMMARY_ENTRIES + 1)]
    with pytest.raises(ValidationError, match="too large"):
        create_workspace_channel_summary(
            successor,
            manifest=manifest,
            member_id=successor_member_id,
            device_id=successor_device_id,
            session_id=session_id,
            entries=too_many,
            now=NOW + 5,
        )
    with pytest.raises(ValidationError, match="limit"):
        create_workspace_channel_fetch(
            successor,
            manifest=manifest,
            member_id=successor_member_id,
            device_id=successor_device_id,
            session_id=session_id,
            requests=[(archived.channel_id, 0, None)],
            max_controls=MAX_CHANNEL_FETCH_CONTROLS + 1,
            now=NOW + 5,
        )
    with pytest.raises(ValidationError, match="page"):
        create_workspace_channel_summary(
            successor,
            manifest=manifest,
            member_id=successor_member_id,
            device_id=successor_device_id,
            session_id=session_id,
            entries=[],
            page_index=0,
            page_count=MAX_CHANNEL_SUMMARY_PAGES + 1,
            now=NOW + 5,
        )


def test_workspace_direct_event_binds_exact_two_member_audience_without_channel() -> None:
    owner, created, genesis, initial = _workspace()
    member_identity = RNS.Identity()
    member_id = _id()
    member_device_id = _id()
    member_card = create_workspace_device_card(
        member_identity,
        workspace_id=genesis.workspace_id,
        member_id=member_id,
        device_id=member_device_id,
        display_name="Bailey",
        now=NOW,
    )
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            ),
            WorkspaceManifestMemberInput(
                member_id,
                "Bailey",
                WorkspaceRole.MEMBER,
                [member_card],
            ),
        ],
        now=NOW,
    )
    admitted = verify_workspace_manifest_transition(
        manifest_raw, initial, now=NOW
    )
    policy_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=3,
        previous_manifest_hash=admitted.digest,
        name=admitted.name,
        description=admitted.description,
        authority_device_id=admitted.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                item.member_id,
                item.display_name,
                item.role,
                [device.serialized for device in item.devices],
                status=item.status,
            )
            for item in admitted.members
        ],
        posting=WorkspacePostingPolicy.OWNER_AND_ADMINS,
        now=NOW + 1,
    )
    manifest = verify_workspace_manifest_transition(
        policy_raw, admitted, now=NOW + 1
    )
    participants = tuple(sorted([genesis.owner_member_id, member_id]))
    conversation_id = workspace_direct_conversation_id(
        genesis.workspace_id, participants
    )
    assert conversation_id == workspace_direct_conversation_id(
        genesis.workspace_id, reversed(participants)
    )
    event_raw = create_workspace_event(
        member_identity,
        workspace_id=genesis.workspace_id,
        conversation_id=conversation_id,
        event_id=_id(),
        author_member_id=member_id,
        author_device_id=member_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=None,
        text="Private workspace hello",
        audience_member_ids=participants,
        created_at=NOW + 1,
    )
    raw_value = json.loads(event_raw)
    assert raw_value["channel_digest"] is None
    assert raw_value["audience_member_ids"] == list(participants)
    verified = verify_workspace_event(
        event_raw,
        manifest=manifest,
        channel=None,
        direct_member_ids=participants,
        now=NOW + 1,
    )
    assert verified.conversation_id == conversation_id
    assert verified.audience_member_ids == participants

    wrong_conversation = create_workspace_event(
        member_identity,
        workspace_id=genesis.workspace_id,
        conversation_id=_id(),
        event_id=_id(),
        author_member_id=member_id,
        author_device_id=member_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=None,
        text="Wrong conversation",
        audience_member_ids=participants,
        created_at=NOW + 1,
    )
    with pytest.raises(ValidationError, match="identifier"):
        verify_workspace_event(
            wrong_conversation,
            manifest=manifest,
            channel=None,
            direct_member_ids=participants,
            now=NOW + 1,
        )

    wrong_audience = create_workspace_event(
        member_identity,
        workspace_id=genesis.workspace_id,
        conversation_id=conversation_id,
        event_id=_id(),
        author_member_id=member_id,
        author_device_id=member_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=None,
        text="Wrong audience",
        audience_member_ids=[member_id],
        created_at=NOW + 1,
    )
    with pytest.raises(IdentityMismatch, match="audience"):
        verify_workspace_event(
            wrong_audience,
            manifest=manifest,
            channel=None,
            direct_member_ids=participants,
            now=NOW + 1,
        )

    with pytest.raises(ValidationError, match="participants"):
        verify_workspace_event(
            event_raw,
            manifest=manifest,
            channel=None,
            direct_member_ids=None,
            now=NOW + 1,
        )


def test_private_channel_chain_binds_roster_audience_transfer_and_recovery() -> None:
    owner, created, genesis, initial = _workspace()
    member_identity = RNS.Identity()
    member_id = _id()
    member_device_id = _id()
    member_card = create_workspace_device_card(
        member_identity,
        workspace_id=genesis.workspace_id,
        member_id=member_id,
        device_id=member_device_id,
        display_name="Bailey",
        now=NOW,
    )
    manifest_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=initial.digest,
        name=initial.name,
        description=initial.description,
        authority_device_id=initial.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                genesis.owner_member_id,
                genesis.owner_device.display_name,
                WorkspaceRole.OWNER,
                [created.device_card],
            ),
            WorkspaceManifestMemberInput(
                member_id,
                "Bailey",
                WorkspaceRole.MEMBER,
                [member_card],
            ),
        ],
        now=NOW,
    )
    manifest = verify_workspace_manifest_transition(manifest_raw, initial, now=NOW)
    channel_raw = create_workspace_channel_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="incident-room",
        topic="Need to know",
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        member_ids=[genesis.owner_member_id, member_id],
        now=NOW,
    )
    channel = verify_workspace_channel_manifest(
        channel_raw, manifest=manifest, now=NOW
    )
    assert channel.member_ids == tuple(sorted([genesis.owner_member_id, member_id]))

    event_raw = create_workspace_event(
        member_identity,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=member_id,
        author_device_id=member_device_id,
        sequence=1,
        previous_event_digest=None,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="scoped",
        audience_member_ids=channel.member_ids,
        created_at=NOW + 1,
    )
    assert verify_workspace_event(
        event_raw, manifest=manifest, channel=channel, now=NOW + 1
    ).audience_member_ids == channel.member_ids
    wrong_audience = json.loads(event_raw)
    wrong_audience["audience_member_ids"] = [member_id]
    wrong_audience.pop("signature")
    wrong_audience_raw = create_workspace_event(
        member_identity,
        workspace_id=genesis.workspace_id,
        conversation_id=channel.channel_id,
        event_id=_id(),
        author_member_id=member_id,
        author_device_id=member_device_id,
        sequence=2,
        previous_event_digest=hashlib.sha256(event_raw.encode()).hexdigest(),
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text="wrong audience",
        audience_member_ids=[member_id],
        created_at=NOW + 2,
    )
    with pytest.raises(IdentityMismatch, match="audience"):
        verify_workspace_event(
            wrong_audience_raw, manifest=manifest, channel=channel, now=NOW + 2
        )

    offer_raw = create_workspace_channel_transfer_offer(
        owner,
        channel=channel,
        manifest=manifest,
        successor_member_id=member_id,
        successor_device_id=member_device_id,
        now=NOW + 2,
    )
    offer = verify_workspace_channel_transfer_offer(
        offer_raw, channel=channel, manifest=manifest, now=NOW + 2
    )
    renamed_raw = create_workspace_channel_manifest(
        owner,
        workspace_id=channel.workspace_id,
        channel_id=channel.channel_id,
        manifest_digest=manifest.digest,
        name="incident-response",
        topic=channel.topic,
        manager_member_id=channel.manager_member_id,
        manager_device_id=channel.manager_device_id,
        member_ids=channel.member_ids,
        version=2,
        previous_hash=channel.digest,
        now=NOW + 3,
    )
    renamed = verify_workspace_channel_manifest_transition(
        renamed_raw, channel, manifest=manifest, now=NOW + 3
    )
    with pytest.raises(ValidationError, match="stale"):
        verify_workspace_channel_transfer_offer(
            offer_raw, channel=renamed, manifest=manifest, now=NOW + 3
        )
    transfer_raw = create_workspace_channel_transfer(
        member_identity, offer=offer, now=NOW + 3
    )
    transferred = verify_workspace_channel_transfer(
        transfer_raw, channel=channel, manifest=manifest, now=NOW + 3
    )
    assert transferred.member_ids == channel.member_ids

    member_only_raw = create_workspace_channel_manifest(
        member_identity,
        workspace_id=genesis.workspace_id,
        channel_id=_id(),
        manifest_digest=manifest.digest,
        name="member-only",
        topic="",
        manager_member_id=member_id,
        manager_device_id=member_device_id,
        member_ids=[member_id],
        now=NOW,
    )
    member_only = verify_workspace_channel_manifest(
        member_only_raw, manifest=manifest, now=NOW
    )
    forbidden_recovery = create_workspace_channel_recovery(
        owner,
        channel=member_only,
        manifest=manifest,
        manager_member_id=genesis.owner_member_id,
        manager_device_id=genesis.authority_device_id,
        now=NOW + 1,
    )
    with pytest.raises(IdentityMismatch, match="authority"):
        verify_workspace_channel_recovery(
            forbidden_recovery,
            channel=member_only,
            manifest=manifest,
            now=NOW + 1,
        )

    with pytest.raises(ValidationError, match="one to eight"):
        create_workspace_channel_manifest(
            owner,
            workspace_id=genesis.workspace_id,
            channel_id=_id(),
            manifest_digest=manifest.digest,
            name="too-many",
            topic="",
            manager_member_id=genesis.owner_member_id,
            manager_device_id=genesis.authority_device_id,
            member_ids=[genesis.owner_member_id, *[_id() for _ in range(8)]],
            now=NOW,
        )
