from __future__ import annotations

import json
import time
from typing import Any, Sequence

import RNS

from .errors import IdentityMismatch, ValidationError
from .models import WorkspaceRole
from .workspace_admission import VerifiedAdmissionGrant, verify_admission_acceptance, verify_admission_grant
from .workspace_protocol import (
    WorkspaceManifestMemberInput,
    VerifiedWorkspaceManifest,
    VerifiedWorkspaceMember,
    _canonical,
    _digest,
    _sign,
    _validate_digest,
    _validate_timestamp,
    _validate_uuid,
    _verify_signature,
    verify_workspace_device_card,
)

DELEGATED_MANIFEST_VERSION = 2
DELEGATED_MANIFEST_TYPE = "workspace_manifest_delegated"


def _grant_use(previous: VerifiedWorkspaceManifest, grant: VerifiedAdmissionGrant) -> int:
    if grant.start_manifest_hash == previous.digest:
        if previous.delegation_grant_digest is not None:
            raise ValidationError("Admission grant start manifest is invalid")
        return 1
    if previous.delegation_grant_digest != grant.digest:
        raise ValidationError("Admission grant chain is invalid")
    if previous.delegation_grant_use is None:
        raise ValidationError("Admission grant chain is invalid")
    return previous.delegation_grant_use + 1


def _members_for_create(
    previous: VerifiedWorkspaceManifest, new_member: WorkspaceManifestMemberInput, now: int
) -> list[dict[str, Any]]:
    members = [
        {
            "member_id": member.member_id,
            "display_name": member.display_name,
            "role": member.role.value,
            "status": member.status,
            "devices": [json.loads(device.serialized) for device in member.devices],
        }
        for member in previous.members
    ]
    if any(item["member_id"] == new_member.member_id for item in members):
        raise ValidationError("Delegated admission member already exists")
    if new_member.role.value == "owner":
        raise ValidationError("Delegated admission cannot add an owner")
    if new_member.role.value != "member":
        raise ValidationError("Delegated admission must add a member")
    if new_member.status != "active" or not new_member.device_cards:
        raise ValidationError("Delegated admission member is invalid")
    devices = []
    for raw in new_member.device_cards:
        card = verify_workspace_device_card(
            raw,
            expected_workspace_id=previous.workspace_id,
            expected_member_id=new_member.member_id,
            now=now,
        )
        if card.display_name != new_member.display_name:
            raise ValidationError("Delegated admission display name is invalid")
        devices.append(json.loads(card.serialized))
    members.append(
        {
            "member_id": new_member.member_id,
            "display_name": new_member.display_name,
            "role": new_member.role.value,
            "status": "active",
            "devices": devices,
        }
    )
    members.sort(key=lambda item: item["member_id"])
    return members


def create_delegated_manifest(
    identity: RNS.Identity,
    *,
    previous: VerifiedWorkspaceManifest,
    grant: str,
    acceptance: str,
    new_member: WorkspaceManifestMemberInput,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked_grant = verify_admission_grant(grant, now=current)
    verify_admission_acceptance(acceptance, grant, now=current)
    if checked_grant.workspace_id != previous.workspace_id:
        raise ValidationError("Admission grant workspace is invalid")
    if _destination(identity) != checked_grant.admin_destination:
        raise IdentityMismatch("Delegated manifest signer is not the grant admin")
    use = _grant_use(previous, checked_grant)
    if use > checked_grant.max_admissions:
        raise ValidationError("Admission grant is exhausted")
    admin = next(
        (
            member
            for member in previous.members
            if member.member_id == checked_grant.admin_member_id
            and member.role.value == "admin"
            and member.status == "active"
            and any(
                device.device_id == checked_grant.admin_device_id
                for device in member.devices
            )
        ),
        None,
    )
    if admin is None:
        raise ValidationError("Admission grant admin is not active")
    unsigned = {
        "v": DELEGATED_MANIFEST_VERSION,
        "type": DELEGATED_MANIFEST_TYPE,
        "workspace_id": previous.workspace_id,
        "epoch": previous.epoch + 1,
        "previous_manifest_hash": previous.digest,
        "name": previous.name,
        "description": previous.description,
        "authority_device_id": previous.authority_device_id,
        "authority_destination": previous.authority_destination.hex(),
        "status": "active",
        "retention_days": previous.retention_days,
        "policies": {
            "channel_creation": previous.channel_creation.value,
            "posting": previous.posting.value,
            "invitation_requests": previous.invitation_requests.value,
        },
        "members": _members_for_create(previous, new_member, current),
        "created_at": current,
        "grant": grant,
        "grant_acceptance": acceptance,
        "grant_use": use,
        "delegated_signer_destination": checked_grant.admin_destination,
    }
    return _sign(identity, unsigned)


def verify_delegated_manifest(
    raw: str,
    *,
    previous: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceManifest:
    current = int(time.time()) if now is None else int(now)
    value = json.loads(raw)
    fields = {
        "v", "type", "workspace_id", "epoch", "previous_manifest_hash", "name",
        "description", "authority_device_id", "authority_destination", "status",
        "retention_days", "policies", "members", "created_at", "grant",
        "grant_acceptance", "grant_use", "delegated_signer_destination",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError("Delegated manifest fields are invalid")
    if value["v"] != DELEGATED_MANIFEST_VERSION or value["type"] != DELEGATED_MANIFEST_TYPE:
        raise ValidationError("Delegated manifest version is unsupported")
    if value["workspace_id"] != previous.workspace_id:
        raise ValidationError("Delegated manifest workspace is invalid")
    if value["previous_manifest_hash"] != previous.digest:
        raise ValidationError("Delegated manifest does not extend the expected state")
    if value["epoch"] != previous.epoch + 1:
        raise ValidationError("Delegated manifest epoch is invalid")
    if value["authority_device_id"] != previous.authority_device_id:
        raise ValidationError("Delegated manifest authority device changed")
    if value["authority_destination"] != previous.authority_destination.hex():
        raise ValidationError("Delegated manifest authority changed")
    if value["status"] != "active":
        raise ValidationError("Delegated manifest cannot close the workspace")
    if (
        value["name"] != previous.name
        or value["description"] != previous.description
        or value["retention_days"] != previous.retention_days
        or value["policies"]
        != {
            "channel_creation": previous.channel_creation.value,
            "posting": previous.posting.value,
            "invitation_requests": previous.invitation_requests.value,
        }
    ):
        raise ValidationError("Delegated manifest changed non-admission state")
    grant = verify_admission_grant(value["grant"], now=current)
    verify_admission_acceptance(value["grant_acceptance"], value["grant"], now=current)
    if grant.workspace_id != previous.workspace_id:
        raise ValidationError("Delegated manifest grant workspace is invalid")
    if value["delegated_signer_destination"] != grant.admin_destination:
        raise ValidationError("Delegated manifest signer is invalid")
    use = value["grant_use"]
    if isinstance(use, bool) or not isinstance(use, int):
        raise ValidationError("Delegated manifest grant use is invalid")
    expected_use = _grant_use(previous, grant)
    if use != expected_use or use > grant.max_admissions:
        raise ValidationError("Delegated manifest grant use is invalid")
    members = _parse_members(value["members"], previous, current)
    created_at = _validate_timestamp(value["created_at"], now=current)
    admin = next(
        (
            member
            for member in members
            if member.member_id == grant.admin_member_id
            and member.role.value == "admin"
            and member.status == "active"
            and any(device.device_id == grant.admin_device_id for device in member.devices)
        ),
        None,
    )
    if admin is None:
        raise ValidationError("Delegated manifest grant admin is not active")
    signer = next(
        device
        for member in members
        for device in member.devices
        if device.destination_hash.hex() == grant.admin_destination
    )
    signer_identity = RNS.Identity(create_keys=False)
    if not signer_identity.load_public_key(signer.public_identity):
        raise IdentityMismatch("Delegated manifest signer key is invalid")
    _verify_signature(signer_identity, value, "Delegated workspace manifest")
    _verify_admission_only(previous, members)
    return VerifiedWorkspaceManifest(
        workspace_id=previous.workspace_id,
        epoch=value["epoch"],
        previous_manifest_hash=previous.digest,
        name=value["name"],
        description=value["description"],
        authority_device_id=previous.authority_device_id,
        authority_destination=previous.authority_destination,
        status="active",
        retention_days=previous.retention_days,
        channel_creation=previous.channel_creation,
        posting=previous.posting,
        invitation_requests=previous.invitation_requests,
        members=tuple(members),
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
        removal_checkpoint_digests=previous.removal_checkpoint_digests,
        delegated_signer_destination=signer.destination_hash,
        delegation_grant_digest=grant.digest,
        delegation_grant_use=use,
    )


def _parse_members(
    raw: Any, previous: VerifiedWorkspaceManifest, now: int
) -> list[VerifiedWorkspaceMember]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        raise ValidationError("Delegated manifest member count is invalid")
    members = []
    owner = 0
    authority = 0
    device_ids = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "member_id", "display_name", "role", "status", "devices",
        }:
            raise ValidationError("Delegated manifest member is invalid")
        member_id = _validate_uuid(item["member_id"], "Member ID")
        role = item["role"]
        if role not in {"owner", "admin", "member"}:
            raise ValidationError("Delegated manifest role is invalid")
        if item["status"] not in {"active", "removed", "left"}:
            raise ValidationError("Delegated manifest status is invalid")
        if role == "owner":
            owner += 1
            if item["status"] != "active":
                raise ValidationError("Delegated manifest owner is not active")
        devices = []
        if not isinstance(item["devices"], list) or not 1 <= len(item["devices"]) <= 3:
            raise ValidationError("Delegated manifest device count is invalid")
        for raw_card in item["devices"]:
            card = verify_workspace_device_card(
                _canonical(raw_card),
                expected_workspace_id=previous.workspace_id,
                expected_member_id=member_id,
                now=now,
            )
            if card.device_id in device_ids:
                raise ValidationError("Delegated manifest has a duplicate device")
            device_ids.add(card.device_id)
            if card.device_id == previous.authority_device_id:
                authority += 1
                if role != "owner":
                    raise ValidationError("Delegated manifest authority is not the owner")
            devices.append(card)
        members.append(
            VerifiedWorkspaceMember(
                member_id=member_id,
                display_name=item["display_name"],
                role=WorkspaceRole(role),
                status=item["status"],
                devices=tuple(devices),
            )
        )
    if owner != 1 or authority != 1:
        raise ValidationError("Delegated manifest must retain one owner authority")
    if [member.member_id for member in members] != sorted(
        member.member_id for member in members
    ):
        raise ValidationError("Delegated manifest members are not canonical")
    return members


def _verify_admission_only(
    previous: VerifiedWorkspaceManifest, members: list[VerifiedWorkspaceMember]
) -> None:
    old = {member.member_id: member for member in previous.members}
    new = {member.member_id: member for member in members}
    if set(old) - set(new):
        raise ValidationError("Delegated admission cannot remove members")
    added = set(new) - set(old)
    if len(added) != 1:
        raise ValidationError("Delegated manifest must add exactly one member")
    for member_id, before in old.items():
        after = new[member_id]
        if (
            before.display_name != after.display_name
            or before.role != after.role
            or before.status != after.status
            or [device.serialized for device in before.devices]
            != [device.serialized for device in after.devices]
        ):
            raise ValidationError("Delegated admission changed an existing member")
    added_member = new[next(iter(added))]
    if added_member.status != "active" or added_member.role.value != "member":
        raise ValidationError("Delegated admission member is invalid")


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()
