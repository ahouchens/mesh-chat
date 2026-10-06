from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes, readable_fingerprint, validate_hints
from .models import GroupPostingPolicy, GroupRole, GroupStatus

GROUP_PROTOCOL_VERSION = 1
MAX_GROUP_MEMBERS = 8
MAX_GROUP_DOCUMENT_BYTES = 16 * 1024
MAX_GROUP_TITLE_LENGTH = 64
MAX_MEMBER_NAME_LENGTH = 64
MAX_MEMBER_HINTS = 2
MAX_INVITATION_LIFETIME_SECONDS = 30 * 24 * 60 * 60
MAX_EPOCH = (1 << 63) - 1
NONCE_BYTES = 32
DIGEST_BYTES = 32
DESTINATION_BYTES = RNS.Reticulum.TRUNCATED_HASHLENGTH // 8
_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class VerifiedGroupMemberCard:
    group_id: str
    display_name: str
    public_identity: bytes
    identity_hash: bytes
    destination_hash: bytes
    fingerprint: str
    hints: list[dict[str, Any]]
    created_at: int
    serialized: str


@dataclass(frozen=True, slots=True)
class CreatedGroupGenesis:
    group_id: str
    nonce: bytes
    member_card: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedGroupGenesis:
    group_id: str
    title: str
    posting_policy: GroupPostingPolicy
    owner: VerifiedGroupMemberCard
    nonce: bytes
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class GroupManifestMemberInput:
    member_card: str
    role: GroupRole | str


@dataclass(frozen=True, slots=True)
class VerifiedGroupMember:
    card: VerifiedGroupMemberCard
    role: GroupRole


@dataclass(frozen=True, slots=True)
class VerifiedGroupManifest:
    group_id: str
    epoch: int
    previous_manifest_hash: str
    title: str
    posting_policy: GroupPostingPolicy
    status: GroupStatus
    owner_destination: bytes
    members: tuple[VerifiedGroupMember, ...]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedGroupInvitation:
    group_id: str
    group_epoch: int
    manifest_hash: str
    owner_public_identity: bytes
    owner_identity_hash: bytes
    owner_destination: bytes
    owner_fingerprint: str
    invitee_destination: bytes
    nonce: bytes
    created_at: int
    expires_at: int
    genesis: VerifiedGroupGenesis
    manifest: VerifiedGroupManifest
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedGroupJoinStatement:
    group_id: str
    group_epoch: int
    manifest_hash: str
    invite_nonce: bytes
    member: VerifiedGroupMemberCard
    created_at: int
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedGroupLeaveRequest:
    group_id: str
    group_epoch: int
    manifest_hash: str
    member: VerifiedGroupMemberCard
    leaver_destination: bytes
    created_at: int
    serialized: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: Any, label: str, *, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str) or not value or not _TOKEN.fullmatch(value):
        raise ValidationError(f"{label} is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise ValidationError(f"{label} is invalid")
    return decoded


def _load_document(raw: str, document_type: str) -> dict[str, Any]:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8")) > MAX_GROUP_DOCUMENT_BYTES
    ):
        raise ValidationError("Group document is empty or too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Group document encoding is invalid") from exc
    if not isinstance(value, dict) or value.get("type") != document_type:
        raise ValidationError("Group document type is invalid")
    return value


def _require_fields(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValidationError("Group document fields are invalid")


def _validate_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} is missing")
    checked = " ".join(value.strip().split())
    if (
        not 1 <= len(checked) <= maximum
        or checked != value
        or any(ord(char) < 32 for char in checked)
    ):
        raise ValidationError(f"{label} is invalid")
    return checked


def _validate_group_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Group ID is invalid")
    try:
        checked = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValidationError("Group ID is invalid") from exc
    if checked != value:
        raise ValidationError("Group ID is not canonical")
    return checked


def _validate_epoch(value: Any, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_EPOCH:
        raise ValidationError("Group epoch is invalid")
    return value


def _validate_hex(value: Any, label: str, length: int) -> bytes:
    if not isinstance(value, str) or len(value) != length * 2 or value != value.lower():
        raise ValidationError(f"{label} is invalid")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if len(decoded) != length:
        raise ValidationError(f"{label} is invalid")
    return decoded


def _validate_timestamp(value: Any, *, now: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > now + 24 * 60 * 60
    ):
        raise ValidationError("Group document date is invalid")
    return value


def _ensure_invitation_current(invite: VerifiedGroupInvitation, *, now: int) -> None:
    if invite.expires_at < now:
        raise InvitationExpired("Group invitation has expired")


def _coerce_policy(value: Any) -> GroupPostingPolicy:
    try:
        return GroupPostingPolicy(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Group posting policy is invalid") from exc


def _coerce_role(value: Any) -> GroupRole:
    try:
        return GroupRole(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Group member role is invalid") from exc


def _coerce_status(value: Any) -> GroupStatus:
    try:
        return GroupStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Group status is invalid") from exc


def _validate_member_hints(value: Any) -> list[dict[str, Any]]:
    hints = validate_hints(value)
    if len(hints) > MAX_MEMBER_HINTS:
        raise ValidationError("Group member connection hints are invalid")
    return hints


def _identity_from_public_key(public_key: bytes) -> RNS.Identity:
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Public identity has an invalid size")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Public identity is invalid")
    return identity


def _destination_for(identity: RNS.Identity) -> bytes:
    return RNS.Destination.hash(identity, "lxmf", "delivery")


def _sign_document(identity: RNS.Identity, unsigned: dict[str, Any]) -> str:
    signed = {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    serialized = canonical_bytes(signed).decode("utf-8")
    if len(serialized.encode("utf-8")) > MAX_GROUP_DOCUMENT_BYTES:
        raise ValidationError("Group document is too large")
    return serialized


def _verify_signature(
    identity: RNS.Identity, value: dict[str, Any], *, label: str
) -> None:
    signature = _b64decode(value["signature"], f"{label} signature")
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    if not identity.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch(f"{label} signature is invalid")


def _canonical_serialized(value: dict[str, Any]) -> str:
    return canonical_bytes(value).decode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def derive_group_id(owner_destination: bytes, nonce: bytes) -> str:
    if not isinstance(owner_destination, bytes) or len(owner_destination) != DESTINATION_BYTES:
        raise ValidationError("Owner destination is invalid")
    if not isinstance(nonce, bytes) or len(nonce) != NONCE_BYTES:
        raise ValidationError("Group nonce is invalid")
    digest = hashlib.sha256(
        b"mesh-chat:group:v1:" + owner_destination + nonce
    ).digest()[:16]
    return str(uuid.UUID(bytes=digest))


def create_member_card(
    identity: RNS.Identity,
    display_name: str,
    *,
    group_id: str,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> str:
    checked_group_id = _validate_group_id(group_id)
    checked_name = _validate_text(display_name, "Member display name", MAX_MEMBER_NAME_LENGTH)
    created_at = int(time.time()) if now is None else int(now)
    public_key = identity.get_public_key()
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_member_card",
        "group_id": checked_group_id,
        "display_name": checked_name,
        "public_identity": _b64encode(public_key),
        "destination": _destination_for(identity).hex(),
        "hints": _validate_member_hints(hints),
        "created_at": created_at,
    }
    return _sign_document(identity, unsigned)


def verify_member_card(
    raw: str,
    *,
    expected_group_id: str | None = None,
    now: int | None = None,
) -> VerifiedGroupMemberCard:
    value = _load_document(raw, "group_member_card")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "display_name",
            "public_identity",
            "destination",
            "hints",
            "created_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    if expected_group_id is not None and group_id != _validate_group_id(expected_group_id):
        raise ValidationError("Member card belongs to another group")
    display_name = _validate_text(
        value["display_name"], "Member display name", MAX_MEMBER_NAME_LENGTH
    )
    public_key = _b64decode(value["public_identity"], "Public identity")
    identity = _identity_from_public_key(public_key)
    destination = _validate_hex(value["destination"], "Member destination", DESTINATION_BYTES)
    if destination != _destination_for(identity):
        raise IdentityMismatch("Member destination does not match public identity")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    hints = _validate_member_hints(value["hints"])
    _verify_signature(identity, value, label="Member card")
    return VerifiedGroupMemberCard(
        group_id=group_id,
        display_name=display_name,
        public_identity=public_key,
        identity_hash=identity.hash,
        destination_hash=destination,
        fingerprint=readable_fingerprint(public_key),
        hints=hints,
        created_at=created_at,
        serialized=_canonical_serialized(value),
    )


def create_group_genesis(
    owner_identity: RNS.Identity,
    title: str,
    owner_display_name: str,
    *,
    posting_policy: GroupPostingPolicy | str = GroupPostingPolicy.MEMBERS,
    owner_hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
    nonce: bytes | None = None,
) -> CreatedGroupGenesis:
    created_at = int(time.time()) if now is None else int(now)
    owner_destination = _destination_for(owner_identity)
    group_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    group_id = derive_group_id(owner_destination, group_nonce)
    member_card = create_member_card(
        owner_identity,
        owner_display_name,
        group_id=group_id,
        hints=owner_hints,
        now=created_at,
    )
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_genesis",
        "group_id": group_id,
        "nonce": _b64encode(group_nonce),
        "title": _validate_text(title, "Group title", MAX_GROUP_TITLE_LENGTH),
        "posting_policy": _coerce_policy(posting_policy).value,
        "owner_card": json.loads(member_card),
        "created_at": created_at,
    }
    return CreatedGroupGenesis(
        group_id=group_id,
        nonce=group_nonce,
        member_card=member_card,
        serialized=_sign_document(owner_identity, unsigned),
    )


def verify_group_genesis(
    raw: str,
    *,
    expected_group_id: str | None = None,
    now: int | None = None,
) -> VerifiedGroupGenesis:
    value = _load_document(raw, "group_genesis")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "nonce",
            "title",
            "posting_policy",
            "owner_card",
            "created_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    if expected_group_id is not None and group_id != _validate_group_id(expected_group_id):
        raise ValidationError("Genesis belongs to another group")
    nonce = _b64decode(value["nonce"], "Group nonce", expected_length=NONCE_BYTES)
    if not isinstance(value["owner_card"], dict):
        raise ValidationError("Owner member card is invalid")
    owner = verify_member_card(
        _canonical_serialized(value["owner_card"]),
        expected_group_id=group_id,
        now=now,
    )
    if derive_group_id(owner.destination_hash, nonce) != group_id:
        raise IdentityMismatch("Group ID does not match its owner and nonce")
    owner_identity = _identity_from_public_key(owner.public_identity)
    _verify_signature(owner_identity, value, label="Group genesis")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    if owner.created_at != created_at:
        raise ValidationError("Owner member card date does not match genesis")
    return VerifiedGroupGenesis(
        group_id=group_id,
        title=_validate_text(value["title"], "Group title", MAX_GROUP_TITLE_LENGTH),
        posting_policy=_coerce_policy(value["posting_policy"]),
        owner=owner,
        nonce=nonce,
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical_serialized(value),
    )


def create_group_manifest(
    owner_identity: RNS.Identity,
    *,
    group_id: str,
    epoch: int,
    previous_manifest_hash: str,
    title: str,
    posting_policy: GroupPostingPolicy | str,
    members: Sequence[GroupManifestMemberInput],
    status: GroupStatus | str = GroupStatus.ACTIVE,
    now: int | None = None,
) -> str:
    checked_group_id = _validate_group_id(group_id)
    checked_epoch = _validate_epoch(epoch)
    previous_digest = _validate_hex(
        previous_manifest_hash, "Previous manifest hash", DIGEST_BYTES
    ).hex()
    if not isinstance(members, Sequence) or not 1 <= len(members) <= MAX_GROUP_MEMBERS:
        raise ValidationError("Group member count is invalid")
    owner_destination = _destination_for(owner_identity)
    encoded_members: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    owner_count = 0
    for member in members:
        if not isinstance(member, GroupManifestMemberInput):
            raise ValidationError("Group manifest member is invalid")
        card = verify_member_card(
            member.member_card, expected_group_id=checked_group_id, now=now
        )
        role = _coerce_role(member.role)
        if card.destination_hash in seen:
            raise ValidationError("Group manifest has a duplicate member")
        seen.add(card.destination_hash)
        if role == GroupRole.OWNER:
            owner_count += 1
            if card.destination_hash != owner_destination:
                raise IdentityMismatch("Group owner role does not match manifest signer")
        encoded_members.append({"card": json.loads(card.serialized), "role": role.value})
    if owner_count != 1 or owner_destination not in seen:
        raise ValidationError("Group manifest must contain exactly one owner")
    encoded_members.sort(key=lambda item: item["card"]["destination"])
    created_at = int(time.time()) if now is None else int(now)
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_manifest",
        "group_id": checked_group_id,
        "epoch": checked_epoch,
        "previous_manifest_hash": previous_digest,
        "title": _validate_text(title, "Group title", MAX_GROUP_TITLE_LENGTH),
        "posting_policy": _coerce_policy(posting_policy).value,
        "status": _coerce_status(status).value,
        "owner_destination": owner_destination.hex(),
        "members": encoded_members,
        "created_at": created_at,
    }
    return _sign_document(owner_identity, unsigned)


def verify_group_manifest(
    raw: str,
    *,
    expected_group_id: str | None = None,
    expected_owner_destination: bytes | None = None,
    expected_previous_hash: str | None = None,
    expected_epoch: int | None = None,
    now: int | None = None,
) -> VerifiedGroupManifest:
    value = _load_document(raw, "group_manifest")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "epoch",
            "previous_manifest_hash",
            "title",
            "posting_policy",
            "status",
            "owner_destination",
            "members",
            "created_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    if expected_group_id is not None and group_id != _validate_group_id(expected_group_id):
        raise ValidationError("Manifest belongs to another group")
    epoch = _validate_epoch(value["epoch"])
    if expected_epoch is not None and epoch != _validate_epoch(expected_epoch):
        raise ValidationError("Group manifest epoch is unexpected")
    previous_hash = _validate_hex(
        value["previous_manifest_hash"], "Previous manifest hash", DIGEST_BYTES
    ).hex()
    if expected_previous_hash is not None:
        expected_hash = _validate_hex(
            expected_previous_hash, "Expected previous manifest hash", DIGEST_BYTES
        ).hex()
        if previous_hash != expected_hash:
            raise ValidationError("Group manifest does not extend the expected state")
    owner_destination = _validate_hex(
        value["owner_destination"], "Owner destination", DESTINATION_BYTES
    )
    if expected_owner_destination is not None and owner_destination != expected_owner_destination:
        raise IdentityMismatch("Group manifest owner is unexpected")
    raw_members = value["members"]
    if not isinstance(raw_members, list) or not 1 <= len(raw_members) <= MAX_GROUP_MEMBERS:
        raise ValidationError("Group member count is invalid")
    members: list[VerifiedGroupMember] = []
    seen: set[bytes] = set()
    owner_identity: RNS.Identity | None = None
    owner_count = 0
    destinations: list[str] = []
    for raw_member in raw_members:
        if not isinstance(raw_member, dict) or set(raw_member) != {"card", "role"}:
            raise ValidationError("Group manifest member is invalid")
        if not isinstance(raw_member["card"], dict):
            raise ValidationError("Group member card is invalid")
        card = verify_member_card(
            _canonical_serialized(raw_member["card"]),
            expected_group_id=group_id,
            now=now,
        )
        role = _coerce_role(raw_member["role"])
        if card.destination_hash in seen:
            raise ValidationError("Group manifest has a duplicate member")
        seen.add(card.destination_hash)
        destinations.append(card.destination_hash.hex())
        if role == GroupRole.OWNER:
            owner_count += 1
            if card.destination_hash != owner_destination:
                raise IdentityMismatch("Group owner role does not match manifest signer")
            owner_identity = _identity_from_public_key(card.public_identity)
        members.append(VerifiedGroupMember(card=card, role=role))
    if destinations != sorted(destinations):
        raise ValidationError("Group manifest members are not canonical")
    if owner_count != 1 or owner_identity is None:
        raise ValidationError("Group manifest must contain exactly one owner")
    _verify_signature(owner_identity, value, label="Group manifest")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    return VerifiedGroupManifest(
        group_id=group_id,
        epoch=epoch,
        previous_manifest_hash=previous_hash,
        title=_validate_text(value["title"], "Group title", MAX_GROUP_TITLE_LENGTH),
        posting_policy=_coerce_policy(value["posting_policy"]),
        status=_coerce_status(value["status"]),
        owner_destination=owner_destination,
        members=tuple(members),
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical_serialized(value),
    )


def manifest_hash(raw: str) -> str:
    value = _load_document(raw, "group_manifest")
    return _digest(value)


def verify_manifest_transition(
    raw: str,
    previous: VerifiedGroupGenesis | VerifiedGroupManifest,
    *,
    now: int | None = None,
) -> VerifiedGroupManifest:
    if isinstance(previous, VerifiedGroupGenesis):
        expected_epoch = 1
        group_id = previous.group_id
        owner_destination = previous.owner.destination_hash
        previous_hash = previous.digest
    elif isinstance(previous, VerifiedGroupManifest):
        if previous.status == GroupStatus.CLOSED:
            raise ValidationError("Closed groups cannot accept another manifest")
        if previous.epoch >= MAX_EPOCH:
            raise ValidationError("Group manifest epoch cannot advance")
        expected_epoch = previous.epoch + 1
        group_id = previous.group_id
        owner_destination = previous.owner_destination
        previous_hash = previous.digest
    else:
        raise ValidationError("Previous group state is invalid")
    return verify_group_manifest(
        raw,
        expected_group_id=group_id,
        expected_owner_destination=owner_destination,
        expected_previous_hash=previous_hash,
        expected_epoch=expected_epoch,
        now=now,
    )


def can_post(manifest: VerifiedGroupManifest, sender_destination: bytes) -> bool:
    if manifest.status == GroupStatus.CLOSED:
        return False
    if not isinstance(sender_destination, bytes) or len(sender_destination) != DESTINATION_BYTES:
        return False
    member = next(
        (
            item
            for item in manifest.members
            if item.card.destination_hash == sender_destination
        ),
        None,
    )
    if member is None:
        return False
    return manifest.posting_policy == GroupPostingPolicy.MEMBERS or member.role in {
        GroupRole.OWNER,
        GroupRole.ADMIN,
    }


def create_group_invitation(
    owner_identity: RNS.Identity,
    *,
    genesis: str,
    manifest: str,
    invitee_destination: bytes,
    now: int | None = None,
    lifetime_seconds: int = 7 * 24 * 60 * 60,
    nonce: bytes | None = None,
) -> str:
    created_at = int(time.time()) if now is None else int(now)
    checked_genesis = verify_group_genesis(genesis, now=created_at)
    owner_destination = _destination_for(owner_identity)
    if checked_genesis.owner.destination_hash != owner_destination:
        raise IdentityMismatch("Group genesis owner does not match invitation signer")
    checked_manifest = verify_group_manifest(
        manifest,
        expected_group_id=checked_genesis.group_id,
        expected_owner_destination=owner_destination,
        now=created_at,
    )
    if checked_manifest.status == GroupStatus.CLOSED:
        raise ValidationError("Closed groups cannot issue invitations")
    if (
        checked_manifest.epoch == 1
        and checked_manifest.previous_manifest_hash != checked_genesis.digest
    ):
        raise ValidationError("Initial group manifest is not anchored to genesis")
    if not isinstance(invitee_destination, bytes) or len(invitee_destination) != DESTINATION_BYTES:
        raise ValidationError("Invitee destination is invalid")
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_INVITATION_LIFETIME_SECONDS
    ):
        raise ValidationError("Group invitation lifetime is invalid")
    invite_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(invite_nonce, bytes) or len(invite_nonce) != NONCE_BYTES:
        raise ValidationError("Group invitation nonce is invalid")
    public_key = owner_identity.get_public_key()
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_invite",
        "group_id": checked_genesis.group_id,
        "group_epoch": checked_manifest.epoch,
        "manifest_hash": checked_manifest.digest,
        "owner_public_identity": _b64encode(public_key),
        "owner_destination": owner_destination.hex(),
        "invitee_destination": invitee_destination.hex(),
        "nonce": _b64encode(invite_nonce),
        "genesis": json.loads(checked_genesis.serialized),
        "manifest": json.loads(checked_manifest.serialized),
        "created_at": created_at,
        "expires_at": created_at + lifetime_seconds,
    }
    return _sign_document(owner_identity, unsigned)


def verify_group_invitation(
    raw: str,
    *,
    expected_group_id: str | None = None,
    expected_owner_destination: bytes | None = None,
    expected_invitee_destination: bytes | None = None,
    now: int | None = None,
) -> VerifiedGroupInvitation:
    value = _load_document(raw, "group_invite")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "group_epoch",
            "manifest_hash",
            "owner_public_identity",
            "owner_destination",
            "invitee_destination",
            "nonce",
            "genesis",
            "manifest",
            "created_at",
            "expires_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    if expected_group_id is not None and group_id != _validate_group_id(expected_group_id):
        raise ValidationError("Invitation belongs to another group")
    epoch = _validate_epoch(value["group_epoch"])
    manifest_digest = _validate_hex(
        value["manifest_hash"], "Group manifest hash", DIGEST_BYTES
    ).hex()
    public_key = _b64decode(value["owner_public_identity"], "Owner public identity")
    identity = _identity_from_public_key(public_key)
    owner_destination = _validate_hex(
        value["owner_destination"], "Owner destination", DESTINATION_BYTES
    )
    if owner_destination != _destination_for(identity):
        raise IdentityMismatch("Invitation owner destination does not match public identity")
    if expected_owner_destination is not None and owner_destination != expected_owner_destination:
        raise IdentityMismatch("Invitation owner is unexpected")
    invitee_destination = _validate_hex(
        value["invitee_destination"], "Invitee destination", DESTINATION_BYTES
    )
    if (
        expected_invitee_destination is not None
        and invitee_destination != expected_invitee_destination
    ):
        raise IdentityMismatch("Invitation is intended for another identity")
    nonce = _b64decode(value["nonce"], "Group invitation nonce", expected_length=NONCE_BYTES)
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    expires_at = value["expires_at"]
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ValidationError("Group invitation dates are invalid")
    if expires_at < current:
        raise InvitationExpired("Group invitation has expired")
    if (
        expires_at <= created_at
        or expires_at - created_at > MAX_INVITATION_LIFETIME_SECONDS
    ):
        raise ValidationError("Group invitation dates are invalid")
    if not isinstance(value["genesis"], dict) or not isinstance(value["manifest"], dict):
        raise ValidationError("Group invitation context is invalid")
    genesis = verify_group_genesis(
        _canonical_serialized(value["genesis"]),
        expected_group_id=group_id,
        now=current,
    )
    if genesis.owner.destination_hash != owner_destination:
        raise IdentityMismatch("Group genesis owner does not match invitation owner")
    manifest = verify_group_manifest(
        _canonical_serialized(value["manifest"]),
        expected_group_id=group_id,
        expected_owner_destination=owner_destination,
        expected_epoch=epoch,
        now=current,
    )
    if manifest.digest != manifest_digest:
        raise ValidationError("Invitation manifest hash does not match its manifest")
    if manifest.status == GroupStatus.CLOSED:
        raise ValidationError("Closed groups cannot issue invitations")
    if manifest.epoch == 1 and manifest.previous_manifest_hash != genesis.digest:
        raise ValidationError("Initial group manifest is not anchored to genesis")
    _verify_signature(identity, value, label="Group invitation")
    return VerifiedGroupInvitation(
        group_id=group_id,
        group_epoch=epoch,
        manifest_hash=manifest_digest,
        owner_public_identity=public_key,
        owner_identity_hash=identity.hash,
        owner_destination=owner_destination,
        owner_fingerprint=readable_fingerprint(public_key),
        invitee_destination=invitee_destination,
        nonce=nonce,
        created_at=created_at,
        expires_at=expires_at,
        genesis=genesis,
        manifest=manifest,
        serialized=_canonical_serialized(value),
    )


def create_group_join_statement(
    invitee_identity: RNS.Identity,
    invitation: str | VerifiedGroupInvitation,
    display_name: str,
    *,
    member_hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    invite = (
        verify_group_invitation(invitation, now=current)
        if isinstance(invitation, str)
        else invitation
    )
    _ensure_invitation_current(invite, now=current)
    invitee_destination = _destination_for(invitee_identity)
    if invite.invitee_destination != invitee_destination:
        raise IdentityMismatch("Invitation is intended for another identity")
    member_card = create_member_card(
        invitee_identity,
        display_name,
        group_id=invite.group_id,
        hints=member_hints,
        now=current,
    )
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_join",
        "group_id": invite.group_id,
        "group_epoch": invite.group_epoch,
        "manifest_hash": invite.manifest_hash,
        "invite_nonce": _b64encode(invite.nonce),
        "member_card": json.loads(member_card),
        "created_at": current,
    }
    return _sign_document(invitee_identity, unsigned)


def verify_group_join_statement(
    raw: str,
    *,
    invitation: str | VerifiedGroupInvitation | None = None,
    now: int | None = None,
) -> VerifiedGroupJoinStatement:
    value = _load_document(raw, "group_join")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "group_epoch",
            "manifest_hash",
            "invite_nonce",
            "member_card",
            "created_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    epoch = _validate_epoch(value["group_epoch"])
    digest = _validate_hex(value["manifest_hash"], "Group manifest hash", DIGEST_BYTES).hex()
    invite_nonce = _b64decode(
        value["invite_nonce"], "Group invitation nonce", expected_length=NONCE_BYTES
    )
    if not isinstance(value["member_card"], dict):
        raise ValidationError("Group member card is invalid")
    member = verify_member_card(
        _canonical_serialized(value["member_card"]),
        expected_group_id=group_id,
        now=now,
    )
    identity = _identity_from_public_key(member.public_identity)
    _verify_signature(identity, value, label="Group join statement")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    if member.created_at != created_at:
        raise ValidationError("Member card date does not match join statement")
    if invitation is not None:
        invite = (
            verify_group_invitation(invitation, now=current)
            if isinstance(invitation, str)
            else invitation
        )
        _ensure_invitation_current(invite, now=current)
        if (
            invite.group_id != group_id
            or invite.group_epoch != epoch
            or invite.manifest_hash != digest
            or invite.nonce != invite_nonce
        ):
            raise ValidationError("Join statement does not match the invitation")
        if invite.invitee_destination != member.destination_hash:
            raise IdentityMismatch("Join statement was signed by another identity")
    return VerifiedGroupJoinStatement(
        group_id=group_id,
        group_epoch=epoch,
        manifest_hash=digest,
        invite_nonce=invite_nonce,
        member=member,
        created_at=created_at,
        serialized=_canonical_serialized(value),
    )


def create_group_leave_request(
    member_identity: RNS.Identity,
    manifest: str | VerifiedGroupManifest,
    *,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked_manifest = (
        verify_group_manifest(manifest, now=current)
        if isinstance(manifest, str)
        else manifest
    )
    if checked_manifest.status == GroupStatus.CLOSED:
        raise ValidationError("Closed groups cannot accept leave requests")
    destination = _destination_for(member_identity)
    membership = next(
        (
            item
            for item in checked_manifest.members
            if item.card.destination_hash == destination
        ),
        None,
    )
    if membership is None:
        raise ValidationError("Leave requester is not a group member")
    if membership.role == GroupRole.OWNER:
        raise ValidationError("Group owner cannot leave without transferring ownership")
    unsigned = {
        "v": GROUP_PROTOCOL_VERSION,
        "type": "group_leave_request",
        "group_id": checked_manifest.group_id,
        "group_epoch": checked_manifest.epoch,
        "manifest_hash": checked_manifest.digest,
        "member_card": json.loads(membership.card.serialized),
        "leaver_destination": destination.hex(),
        "created_at": current,
    }
    return _sign_document(member_identity, unsigned)


def verify_group_leave_request(
    raw: str,
    *,
    manifest: str | VerifiedGroupManifest | None = None,
    now: int | None = None,
) -> VerifiedGroupLeaveRequest:
    value = _load_document(raw, "group_leave_request")
    _require_fields(
        value,
        {
            "v",
            "type",
            "group_id",
            "group_epoch",
            "manifest_hash",
            "member_card",
            "leaver_destination",
            "created_at",
            "signature",
        },
    )
    if value["v"] != GROUP_PROTOCOL_VERSION:
        raise ValidationError("Group document version is unsupported")
    group_id = _validate_group_id(value["group_id"])
    epoch = _validate_epoch(value["group_epoch"])
    digest = _validate_hex(
        value["manifest_hash"], "Group manifest hash", DIGEST_BYTES
    ).hex()
    if not isinstance(value["member_card"], dict):
        raise ValidationError("Group member card is invalid")
    member = verify_member_card(
        _canonical_serialized(value["member_card"]),
        expected_group_id=group_id,
        now=now,
    )
    destination = _validate_hex(
        value["leaver_destination"], "Leaver destination", DESTINATION_BYTES
    )
    if destination != member.destination_hash:
        raise IdentityMismatch("Leave requester does not match its member card")
    identity = _identity_from_public_key(member.public_identity)
    _verify_signature(identity, value, label="Group leave request")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    if manifest is not None:
        checked_manifest = (
            verify_group_manifest(manifest, now=current)
            if isinstance(manifest, str)
            else manifest
        )
        if (
            checked_manifest.group_id != group_id
            or checked_manifest.epoch != epoch
            or checked_manifest.digest != digest
        ):
            raise ValidationError("Leave request does not match the current manifest")
        if checked_manifest.status == GroupStatus.CLOSED:
            raise ValidationError("Closed groups cannot accept leave requests")
        membership = next(
            (
                item
                for item in checked_manifest.members
                if item.card.destination_hash == destination
            ),
            None,
        )
        if membership is None:
            raise ValidationError("Leave requester is not a group member")
        if membership.role == GroupRole.OWNER:
            raise ValidationError(
                "Group owner cannot leave without transferring ownership"
            )
        if membership.card.public_identity != member.public_identity:
            raise IdentityMismatch("Leave requester does not match the manifest member")
    return VerifiedGroupLeaveRequest(
        group_id=group_id,
        group_epoch=epoch,
        manifest_hash=digest,
        member=member,
        leaver_destination=destination,
        created_at=created_at,
        serialized=_canonical_serialized(value),
    )
