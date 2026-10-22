from __future__ import annotations

import json
import uuid

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.models import WorkspaceRole
from mesh_chat.workspace_admission import (
    create_admission_acceptance,
    create_admission_grant,
    verify_admission_acceptance,
    verify_admission_grant,
)
from mesh_chat.workspace_delegation import (
    create_delegated_manifest,
    verify_delegated_manifest,
)
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_device_card,
    create_workspace_genesis,
    create_workspace_manifest,
    verify_workspace_genesis,
    verify_workspace_manifest_transition,
)

NOW = 1_800_000_000


def _id() -> str:
    return str(uuid.uuid4())


def _inputs(manifest):
    return [
        WorkspaceManifestMemberInput(
            member.member_id,
            member.display_name,
            member.role,
            [device.serialized for device in member.devices],
        )
        for member in manifest.members
    ]


def _base() -> tuple:
    owner = RNS.Identity()
    admin = RNS.Identity()
    owner_member_id = _id()
    authority_device_id = _id()
    created = create_workspace_genesis(
        owner,
        "Lakewatcher",
        "Admission test",
        "Alex",
        now=NOW,
        nonce=b"a" * 32,
        owner_member_id=owner_member_id,
        authority_device_id=authority_device_id,
    )
    genesis = verify_workspace_genesis(created.serialized, now=NOW)
    first = create_workspace_manifest(
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
    base = verify_workspace_manifest_transition(first, genesis, now=NOW)
    admin_member_id = _id()
    admin_device_id = _id()
    admin_card = create_workspace_device_card(
        admin,
        workspace_id=genesis.workspace_id,
        member_id=admin_member_id,
        device_id=admin_device_id,
        display_name="Ada Admin",
        now=NOW,
    )
    second = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=2,
        previous_manifest_hash=base.digest,
        name=base.name,
        description=base.description,
        authority_device_id=base.authority_device_id,
        members=[
            *_inputs(base),
            WorkspaceManifestMemberInput(
                admin_member_id,
                "Ada Admin",
                WorkspaceRole.MEMBER,
                [admin_card],
            ),
        ],
        now=NOW + 1,
    )
    base = verify_workspace_manifest_transition(second, base, now=NOW + 1)
    promote = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=3,
        previous_manifest_hash=base.digest,
        name=base.name,
        description=base.description,
        authority_device_id=base.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                WorkspaceRole.ADMIN if member.member_id == admin_member_id else member.role,
                [device.serialized for device in member.devices],
            )
            for member in base.members
        ],
        now=NOW + 2,
    )
    base = verify_workspace_manifest_transition(promote, base, now=NOW + 2)
    return owner, admin, base, admin_member_id, admin_device_id, admin_card


def test_admission_grant_and_acceptance_round_trip_and_tamper():
    owner, admin, base, admin_member_id, admin_device_id, admin_card = _base()
    grant = create_admission_grant(
        owner,
        workspace_id=base.workspace_id,
        start_manifest_hash=base.digest,
        admin_member_id=admin_member_id,
        admin_device_id=admin_device_id,
        admin_device_card=admin_card,
        now=NOW + 2,
    )
    checked = verify_admission_grant(grant, now=NOW + 2)
    assert checked.workspace_id == base.workspace_id
    assert checked.admin_destination == RNS.Destination.hash(admin, "lxmf", "delivery").hex()
    acceptance = create_admission_acceptance(admin, grant=grant, now=NOW + 3)
    accepted = verify_admission_acceptance(acceptance, grant, now=NOW + 3)
    assert accepted.grant_digest == checked.digest

    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_admission_grant(grant[:-2] + "AA", now=NOW + 2)
    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_admission_acceptance(acceptance[:-2] + "AA", grant, now=NOW + 3)
    with pytest.raises(InvitationExpired):
        verify_admission_grant(grant, now=NOW + 2 + 7 * 24 * 60 * 60 + 1)


def test_delegated_manifest_full_snapshot_and_use_chain():
    owner, admin, base, admin_member_id, admin_device_id, admin_card = _base()
    grant = create_admission_grant(
        owner,
        workspace_id=base.workspace_id,
        start_manifest_hash=base.digest,
        admin_member_id=admin_member_id,
        admin_device_id=admin_device_id,
        admin_device_card=admin_card,
        now=NOW + 2,
    )
    acceptance = create_admission_acceptance(admin, grant=grant, now=NOW + 3)
    first_identity = RNS.Identity()
    first_id = _id()
    first_card = create_workspace_device_card(
        first_identity,
        workspace_id=base.workspace_id,
        member_id=first_id,
        device_id=_id(),
        display_name="Casey",
        now=NOW + 4,
    )
    raw = create_delegated_manifest(
        admin,
        previous=base,
        grant=grant,
        acceptance=acceptance,
        new_member=WorkspaceManifestMemberInput(
            first_id, "Casey", WorkspaceRole.MEMBER, [first_card]
        ),
        now=NOW + 5,
    )
    first = verify_delegated_manifest(raw, previous=base, now=NOW + 5)
    assert first.delegation_grant_use == 1
    assert any(member.member_id == first_id for member in first.members)

    second_identity = RNS.Identity()
    second_id = _id()
    second_card = create_workspace_device_card(
        second_identity,
        workspace_id=base.workspace_id,
        member_id=second_id,
        device_id=_id(),
        display_name="Drew",
        now=NOW + 6,
    )
    second_raw = create_delegated_manifest(
        admin,
        previous=first,
        grant=grant,
        acceptance=acceptance,
        new_member=WorkspaceManifestMemberInput(
            second_id, "Drew", WorkspaceRole.MEMBER, [second_card]
        ),
        now=NOW + 7,
    )
    second = verify_delegated_manifest(second_raw, previous=first, now=NOW + 7)
    assert second.delegation_grant_use == 2
    assert any(member.member_id == second_id for member in second.members)

    tampered = json.loads(second_raw)
    tampered["name"] = "Changed"
    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_delegated_manifest(json.dumps(tampered), previous=first, now=NOW + 7)
