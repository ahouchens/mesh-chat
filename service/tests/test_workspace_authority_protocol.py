from __future__ import annotations

import json
import uuid

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.models import WorkspaceRole
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_authority_acceptance,
    create_workspace_authority_manifest,
    create_workspace_authority_offer,
    create_workspace_channel_record,
    create_workspace_channel_recovery,
    create_workspace_device_card,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_manifest,
    verify_workspace_authority_acceptance,
    verify_workspace_authority_manifest_transition,
    verify_workspace_authority_offer,
    verify_workspace_channel_record,
    verify_workspace_channel_recovery,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_manifest,
    verify_workspace_manifest_transition,
)


NOW = 1_800_000_000


def _id() -> str:
    return str(uuid.uuid4())


def _seeded_workspace() -> dict[str, object]:
    old_authority = RNS.Identity()
    owner_successor = RNS.Identity()
    member_successor = RNS.Identity()
    created = create_workspace_genesis(
        old_authority,
        "Authority lab",
        "Bounded continuity fixture",
        "Alex",
        now=NOW,
        nonce=b"a" * 32,
        owner_member_id=_id(),
        authority_device_id=_id(),
    )
    genesis = verify_workspace_genesis(created.serialized, now=NOW)
    owner_successor_device_id = _id()
    owner_successor_card = create_workspace_device_card(
        owner_successor,
        workspace_id=genesis.workspace_id,
        member_id=genesis.owner_member_id,
        device_id=owner_successor_device_id,
        display_name="Alex",
        now=NOW,
    )
    member_id = _id()
    member_device_id = _id()
    member_card = create_workspace_device_card(
        member_successor,
        workspace_id=genesis.workspace_id,
        member_id=member_id,
        device_id=member_device_id,
        display_name="Bailey",
        now=NOW,
    )
    # Increment 14 enrollment remains absent. This deliberately seeded
    # multi-device manifest is the bounded Increment 13 rotation fixture.
    manifest = verify_workspace_manifest(
        create_workspace_manifest(
            old_authority,
            workspace_id=genesis.workspace_id,
            epoch=2,
            previous_manifest_hash="0" * 64,
            name=genesis.name,
            description=genesis.description,
            authority_device_id=genesis.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    "Alex",
                    WorkspaceRole.OWNER,
                    [created.device_card, owner_successor_card],
                ),
                WorkspaceManifestMemberInput(
                    member_id,
                    "Bailey",
                    WorkspaceRole.MEMBER,
                    [member_card],
                ),
            ],
            now=NOW,
        ),
        now=NOW,
    )
    general = verify_workspace_channel_record(
        create_workspace_channel_record(
            old_authority,
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
    return locals()


def test_same_owner_rotation_is_countersigned_and_changes_only_authority() -> None:
    fixture = _seeded_workspace()
    manifest = fixture["manifest"]
    offer = verify_workspace_authority_offer(
        create_workspace_authority_offer(
            fixture["old_authority"],
            manifest=manifest,
            transition_kind="same_owner_rotation",
            successor_member_id=fixture["genesis"].owner_member_id,
            successor_device_id=fixture["owner_successor_device_id"],
            now=NOW,
        ),
        manifest=manifest,
        now=NOW,
    )
    with pytest.raises(IdentityMismatch):
        create_workspace_authority_acceptance(
            fixture["member_successor"], offer=offer, now=NOW
        )
    acceptance = verify_workspace_authority_acceptance(
        create_workspace_authority_acceptance(
            fixture["owner_successor"], offer=offer, now=NOW
        ),
        manifest=manifest,
        now=NOW,
    )
    final = verify_workspace_authority_manifest_transition(
        create_workspace_authority_manifest(
            fixture["old_authority"], previous=manifest, acceptance=acceptance, now=NOW
        ),
        manifest,
        acceptance=acceptance,
        now=NOW,
    )
    assert final.authority_device_id == fixture["owner_successor_device_id"]
    assert [(member.member_id, member.role, member.status) for member in final.members] == [
        (member.member_id, member.role, member.status) for member in manifest.members
    ]
    assert [device.serialized for member in final.members for device in member.devices] == [
        device.serialized for member in manifest.members for device in member.devices
    ]
    with pytest.raises((IdentityMismatch, ValidationError)):
        create_workspace_manifest(
            fixture["old_authority"],
            workspace_id=final.workspace_id,
            epoch=final.epoch + 1,
            previous_manifest_hash=final.digest,
            name=final.name,
            description=final.description,
            authority_device_id=final.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    member.member_id,
                    member.display_name,
                    member.role,
                    [device.serialized for device in member.devices],
                    member.status,
                )
                for member in final.members
            ],
            now=NOW,
        )


def test_ownership_transfer_recovers_general_and_bootstraps_from_genesis() -> None:
    fixture = _seeded_workspace()
    manifest = fixture["manifest"]
    general = fixture["general"]
    offer = verify_workspace_authority_offer(
        create_workspace_authority_offer(
            fixture["old_authority"],
            manifest=manifest,
            transition_kind="ownership_transfer",
            successor_member_id=fixture["member_id"],
            successor_device_id=fixture["member_device_id"],
            outgoing_owner_role="admin",
            general_channel=general,
            now=NOW,
        ),
        manifest=manifest,
        general_channel=general,
        now=NOW,
    )
    acceptance = verify_workspace_authority_acceptance(
        create_workspace_authority_acceptance(
            fixture["member_successor"], offer=offer, now=NOW
        ),
        manifest=manifest,
        general_channel=general,
        now=NOW,
    )
    recovery_raw = create_workspace_channel_recovery(
        fixture["old_authority"],
        channel=general,
        manifest=manifest,
        manager_member_id=offer.successor_member_id,
        manager_device_id=offer.successor_device_id,
        now=NOW,
    )
    recovery = verify_workspace_channel_recovery(
        recovery_raw, channel=general, manifest=manifest, now=NOW
    )
    final = verify_workspace_authority_manifest_transition(
        create_workspace_authority_manifest(
            fixture["old_authority"], previous=manifest, acceptance=acceptance, now=NOW
        ),
        manifest,
        acceptance=acceptance,
        general_channel=general,
        general_result=recovery,
        now=NOW,
    )
    roles = {member.member_id: member.role for member in final.members}
    assert roles[fixture["genesis"].owner_member_id] == WorkspaceRole.ADMIN
    assert roles[fixture["member_id"]] == WorkspaceRole.OWNER
    assert recovery.manager_device_id == fixture["member_device_id"]

    step = {
        "base_manifest": manifest.serialized,
        "offer": offer.serialized,
        "acceptance": acceptance.serialized,
        "final_manifest": final.serialized,
        "general_result": recovery_raw,
    }
    invitation = create_workspace_invitation(
        fixture["member_successor"],
        genesis=fixture["genesis"].serialized,
        manifest=final.serialized,
        authority_chain=[step],
        now=NOW,
    )
    verified = verify_workspace_invitation(invitation, now=NOW)
    assert verified.offered_manifest.digest == final.digest
    assert len(verified.authority_chain) == 1

    truncated = json.loads(invitation)
    truncated["authority_chain"] = []
    unsigned = {key: value for key, value in truncated.items() if key != "signature"}
    truncated["signature"] = __import__("base64").urlsafe_b64encode(
        fixture["member_successor"].sign(
            json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        )
    ).decode().rstrip("=")
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_workspace_invitation(
            json.dumps(truncated, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            now=NOW,
        )


def test_expired_or_substituted_authority_controls_fail_closed() -> None:
    fixture = _seeded_workspace()
    manifest = fixture["manifest"]
    offer_raw = create_workspace_authority_offer(
        fixture["old_authority"],
        manifest=manifest,
        transition_kind="same_owner_rotation",
        successor_member_id=fixture["genesis"].owner_member_id,
        successor_device_id=fixture["owner_successor_device_id"],
        lifetime_seconds=1,
        now=NOW,
    )
    with pytest.raises(InvitationExpired):
        verify_workspace_authority_offer(offer_raw, manifest=manifest, now=NOW + 2)
    offer = verify_workspace_authority_offer(
        offer_raw, manifest=manifest, now=NOW, allow_expired=True
    )
    acceptance_raw = create_workspace_authority_acceptance(
        fixture["owner_successor"], offer=offer, now=NOW
    )
    substituted = json.loads(acceptance_raw)
    substituted["successor_member_id"] = fixture["member_id"]
    with pytest.raises(ValidationError, match="not canonical|substituted|signature"):
        verify_workspace_authority_acceptance(
            json.dumps(substituted), manifest=manifest, now=NOW
        )
