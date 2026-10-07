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
from mesh_chat.models import MessageKind, WorkspaceRole
from mesh_chat.network import ReticulumNetwork, validate_unknown_source_signature
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_channel_record,
    create_workspace_event,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_join,
    create_workspace_manifest,
    derive_workspace_id,
    verify_workspace_channel_record,
    verify_workspace_event,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_join,
    verify_workspace_manifest_transition,
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
    manifest = verify_workspace_manifest_transition(
        manifest_raw, initial, now=NOW + 2
    )
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
