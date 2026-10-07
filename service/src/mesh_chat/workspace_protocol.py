from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes, readable_fingerprint, validate_hints
from .models import (
    WorkspaceChannelCreationPolicy,
    WorkspaceInvitationPolicy,
    WorkspacePostingPolicy,
    WorkspaceRole,
)


WORKSPACE_PROTOCOL_VERSION = 1
MAX_WORKSPACE_DOCUMENT_BYTES = 16 * 1024
MAX_WORKSPACE_EVENT_BYTES = 20 * 1024
MAX_WORKSPACE_NAME_LENGTH = 64
MAX_WORKSPACE_DESCRIPTION_LENGTH = 250
MAX_MEMBER_NAME_LENGTH = 64
MAX_CHANNEL_NAME_LENGTH = 80
MAX_CHANNEL_TOPIC_LENGTH = 250
# The text field itself is 16 KiB. The canonical event has a separate bounded
# allowance for IDs and the author signature.
MAX_MESSAGE_TEXT_BYTES = 16 * 1024
MAX_MEMBER_HINTS = 2
MAX_ACTIVE_MEMBERS = 8
MAX_INVITATION_LIFETIME_SECONDS = 30 * 24 * 60 * 60
DEFAULT_INVITATION_LIFETIME_SECONDS = 7 * 24 * 60 * 60
MAX_EPOCH = (1 << 63) - 1
MAX_SEQUENCE = (1 << 63) - 1
NONCE_BYTES = 32
DIGEST_BYTES = 32
DESTINATION_BYTES = RNS.Reticulum.TRUNCATED_HASHLENGTH // 8
_TOKEN = re.compile(r"[A-Za-z0-9_-]+")
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDeviceCard:
    workspace_id: str
    member_id: str
    device_id: str
    display_name: str
    public_identity: bytes
    identity_hash: bytes
    destination_hash: bytes
    fingerprint: str
    hints: list[dict[str, Any]]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class CreatedWorkspaceGenesis:
    workspace_id: str
    nonce: bytes
    owner_member_id: str
    authority_device_id: str
    device_card: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceGenesis:
    workspace_id: str
    nonce: bytes
    name: str
    description: str
    owner_member_id: str
    authority_device_id: str
    owner_device: VerifiedWorkspaceDeviceCard
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class WorkspaceManifestMemberInput:
    member_id: str
    display_name: str
    role: WorkspaceRole | str
    device_cards: Sequence[str]
    status: str = "active"


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceMember:
    member_id: str
    display_name: str
    role: WorkspaceRole
    status: str
    devices: tuple[VerifiedWorkspaceDeviceCard, ...]


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceManifest:
    workspace_id: str
    epoch: int
    previous_manifest_hash: str
    name: str
    description: str
    authority_device_id: str
    authority_destination: bytes
    status: str
    retention_days: int | None
    channel_creation: WorkspaceChannelCreationPolicy
    posting: WorkspacePostingPolicy
    invitation_requests: WorkspaceInvitationPolicy
    members: tuple[VerifiedWorkspaceMember, ...]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceInvitation:
    workspace_id: str
    genesis_digest: str
    offered_manifest_digest: str
    nonce: bytes
    created_at: int
    expires_at: int
    genesis: VerifiedWorkspaceGenesis
    offered_manifest: VerifiedWorkspaceManifest
    serialized: str

    def preview(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.offered_manifest.name,
            "description": self.offered_manifest.description,
            "owner_fingerprint": self.genesis.owner_device.fingerprint,
            "member_count": len(active_members(self.offered_manifest)),
            "retention_days": self.offered_manifest.retention_days,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceJoin:
    workspace_id: str
    genesis_digest: str
    offered_manifest_digest: str
    invite_nonce: bytes
    member_id: str
    device: VerifiedWorkspaceDeviceCard
    invitation: VerifiedWorkspaceInvitation
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceChannel:
    workspace_id: str
    channel_id: str
    version: int
    previous_hash: str | None
    manifest_digest: str
    name: str
    topic: str
    visibility: str
    manager_member_id: str
    manager_device_id: str
    archived: bool
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceEvent:
    workspace_id: str
    conversation_id: str
    event_id: str
    event_type: str
    author_member_id: str
    author_device_id: str
    author_destination: bytes
    sequence: int
    previous_event_digest: str | None
    manifest_digest: str
    channel_digest: str
    text: str
    thread_root: str | None
    mentions: tuple[str, ...]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceLeaveRequest:
    workspace_id: str
    manifest_digest: str
    member_id: str
    device_id: str
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDisplayNameRequest:
    workspace_id: str
    manifest_digest: str
    member_id: str
    device_id: str
    display_name: str
    replacement_device: VerifiedWorkspaceDeviceCard
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDisplayNameDecision:
    workspace_id: str
    manifest_digest: str
    request_digest: str
    member_id: str
    device_id: str
    approved: bool
    created_at: int
    digest: str
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
    if _b64encode(decoded) != value:
        raise ValidationError(f"{label} is not canonical")
    return decoded


def _canonical(value: dict[str, Any]) -> str:
    return canonical_bytes(value).decode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _load_document(raw: str, document_type: str) -> dict[str, Any]:
    maximum = (
        MAX_WORKSPACE_EVENT_BYTES
        if document_type == "workspace_event"
        else MAX_WORKSPACE_DOCUMENT_BYTES
    )
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8")) > maximum
    ):
        raise ValidationError("Workspace document is empty or too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Workspace document encoding is invalid") from exc
    if not isinstance(value, dict) or value.get("type") != document_type:
        raise ValidationError("Workspace document type is invalid")
    if raw != _canonical(value):
        raise ValidationError("Workspace document encoding is not canonical")
    return value


def _require_fields(value: dict[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise ValidationError("Workspace document fields are invalid")


def _validate_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} is invalid")
    try:
        checked = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if checked != value:
        raise ValidationError(f"{label} is not canonical")
    return checked


def _validate_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != DIGEST_BYTES * 2 or value != value.lower():
        raise ValidationError(f"{label} is invalid")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if len(decoded) != DIGEST_BYTES:
        raise ValidationError(f"{label} is invalid")
    return value


def _validate_destination(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or len(value) != DESTINATION_BYTES * 2 or value != value.lower():
        raise ValidationError(f"{label} is invalid")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if len(decoded) != DESTINATION_BYTES:
        raise ValidationError(f"{label} is invalid")
    return decoded


def _normalize_text(
    value: Any,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} is invalid")
    normalized = unicodedata.normalize("NFC", value)
    checked = " ".join(normalized.strip().split())
    minimum = 0 if allow_empty else 1
    if (
        checked != value
        or not minimum <= len(checked) <= maximum
        or any(ord(char) < 32 for char in checked)
    ):
        raise ValidationError(f"{label} is invalid")
    return checked


def _validate_timestamp(value: Any, *, now: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > now + 24 * 60 * 60
    ):
        raise ValidationError("Workspace document date is invalid")
    return value


def _identity_from_public_key(public_key: bytes) -> RNS.Identity:
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Public identity has an invalid size")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Public identity is invalid")
    return identity


def _destination_for(identity: RNS.Identity) -> bytes:
    return RNS.Destination.hash(identity, "lxmf", "delivery")


def _sign(
    identity: RNS.Identity,
    unsigned: dict[str, Any],
    *,
    maximum: int = MAX_WORKSPACE_DOCUMENT_BYTES,
) -> str:
    signed = {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    serialized = _canonical(signed)
    if len(serialized.encode("utf-8")) > maximum:
        raise ValidationError("Workspace document is too large")
    return serialized


def _verify_signature(identity: RNS.Identity, value: dict[str, Any], label: str) -> None:
    signature = _b64decode(value.get("signature"), f"{label} signature")
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    if not identity.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch(f"{label} signature is invalid")


def derive_workspace_id(creator_destination: bytes, nonce: bytes) -> str:
    if not isinstance(creator_destination, bytes) or len(creator_destination) != DESTINATION_BYTES:
        raise ValidationError("Creator destination is invalid")
    if not isinstance(nonce, bytes) or len(nonce) != NONCE_BYTES:
        raise ValidationError("Workspace nonce is invalid")
    digest = hashlib.sha256(
        b"mesh-chat:workspace:v1:" + creator_destination + nonce
    ).digest()[:16]
    return str(uuid.UUID(bytes=digest))


def active_members(manifest: VerifiedWorkspaceManifest) -> tuple[VerifiedWorkspaceMember, ...]:
    return tuple(member for member in manifest.members if member.status == "active")


def find_member(
    manifest: VerifiedWorkspaceManifest, member_id: str
) -> VerifiedWorkspaceMember | None:
    return next((item for item in manifest.members if item.member_id == member_id), None)


def find_device(
    manifest: VerifiedWorkspaceManifest, device_id: str
) -> tuple[VerifiedWorkspaceMember, VerifiedWorkspaceDeviceCard] | None:
    for member in manifest.members:
        for device in member.devices:
            if device.device_id == device_id:
                return member, device
    return None


def create_workspace_device_card(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    member_id: str,
    device_id: str,
    display_name: str,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> str:
    checked_hints = validate_hints(hints)
    if len(checked_hints) > MAX_MEMBER_HINTS:
        raise ValidationError("Workspace device connection hints are invalid")
    public_key = identity.get_public_key()
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_device_card",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "member_id": _validate_uuid(member_id, "Member ID"),
        "device_id": _validate_uuid(device_id, "Device ID"),
        "display_name": _normalize_text(
            display_name, "Member display name", MAX_MEMBER_NAME_LENGTH
        ),
        "public_identity": _b64encode(public_key),
        "destination": _destination_for(identity).hex(),
        "hints": checked_hints,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_device_card(
    raw: str,
    *,
    expected_workspace_id: str | None = None,
    expected_member_id: str | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceDeviceCard:
    value = _load_document(raw, "workspace_device_card")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "member_id",
            "device_id",
            "display_name",
            "public_identity",
            "destination",
            "hints",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    device_id = _validate_uuid(value["device_id"], "Device ID")
    if expected_workspace_id is not None and workspace_id != _validate_uuid(
        expected_workspace_id, "Workspace ID"
    ):
        raise ValidationError("Device card belongs to another workspace")
    if expected_member_id is not None and member_id != _validate_uuid(
        expected_member_id, "Member ID"
    ):
        raise ValidationError("Device card belongs to another member")
    public_identity = _b64decode(value["public_identity"], "Public identity")
    identity = _identity_from_public_key(public_identity)
    destination = _validate_destination(value["destination"], "Device destination")
    if _destination_for(identity) != destination:
        raise IdentityMismatch("Device destination does not match its public identity")
    checked_hints = validate_hints(value["hints"])
    if len(checked_hints) > MAX_MEMBER_HINTS:
        raise ValidationError("Workspace device connection hints are invalid")
    _verify_signature(identity, value, "Workspace device card")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    return VerifiedWorkspaceDeviceCard(
        workspace_id=workspace_id,
        member_id=member_id,
        device_id=device_id,
        display_name=_normalize_text(
            value["display_name"], "Member display name", MAX_MEMBER_NAME_LENGTH
        ),
        public_identity=public_identity,
        identity_hash=identity.hash,
        destination_hash=destination,
        fingerprint=readable_fingerprint(public_identity),
        hints=checked_hints,
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_genesis(
    identity: RNS.Identity,
    name: str,
    description: str,
    owner_display_name: str,
    *,
    owner_hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
    nonce: bytes | None = None,
    owner_member_id: str | None = None,
    authority_device_id: str | None = None,
) -> CreatedWorkspaceGenesis:
    created_at = int(time.time()) if now is None else int(now)
    creator_destination = _destination_for(identity)
    workspace_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    workspace_id = derive_workspace_id(creator_destination, workspace_nonce)
    member_id = _validate_uuid(
        owner_member_id or str(uuid.uuid4()), "Owner member ID"
    )
    device_id = _validate_uuid(
        authority_device_id or str(uuid.uuid4()), "Authority device ID"
    )
    card = create_workspace_device_card(
        identity,
        workspace_id=workspace_id,
        member_id=member_id,
        device_id=device_id,
        display_name=owner_display_name,
        hints=owner_hints,
        now=created_at,
    )
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_genesis",
        "workspace_id": workspace_id,
        "nonce": _b64encode(workspace_nonce),
        "name": _normalize_text(name, "Workspace name", MAX_WORKSPACE_NAME_LENGTH),
        "description": _normalize_text(
            description,
            "Workspace description",
            MAX_WORKSPACE_DESCRIPTION_LENGTH,
            allow_empty=True,
        ),
        "owner_member_id": member_id,
        "authority_device_id": device_id,
        "owner_device_card": json.loads(card),
        "created_at": created_at,
    }
    return CreatedWorkspaceGenesis(
        workspace_id=workspace_id,
        nonce=workspace_nonce,
        owner_member_id=member_id,
        authority_device_id=device_id,
        device_card=card,
        serialized=_sign(identity, unsigned),
    )


def verify_workspace_genesis(
    raw: str, *, expected_workspace_id: str | None = None, now: int | None = None
) -> VerifiedWorkspaceGenesis:
    value = _load_document(raw, "workspace_genesis")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "nonce",
            "name",
            "description",
            "owner_member_id",
            "authority_device_id",
            "owner_device_card",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    if expected_workspace_id is not None and workspace_id != _validate_uuid(
        expected_workspace_id, "Workspace ID"
    ):
        raise ValidationError("Genesis belongs to another workspace")
    owner_member_id = _validate_uuid(value["owner_member_id"], "Owner member ID")
    authority_device_id = _validate_uuid(
        value["authority_device_id"], "Authority device ID"
    )
    if not isinstance(value["owner_device_card"], dict):
        raise ValidationError("Owner device card is invalid")
    owner = verify_workspace_device_card(
        _canonical(value["owner_device_card"]),
        expected_workspace_id=workspace_id,
        expected_member_id=owner_member_id,
        now=now,
    )
    if owner.device_id != authority_device_id:
        raise IdentityMismatch("Genesis authority device is invalid")
    nonce = _b64decode(value["nonce"], "Workspace nonce", expected_length=NONCE_BYTES)
    if derive_workspace_id(owner.destination_hash, nonce) != workspace_id:
        raise IdentityMismatch("Workspace ID does not match its creator and nonce")
    identity = _identity_from_public_key(owner.public_identity)
    _verify_signature(identity, value, "Workspace genesis")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    if owner.created_at != created_at:
        raise ValidationError("Owner device card date does not match genesis")
    return VerifiedWorkspaceGenesis(
        workspace_id=workspace_id,
        nonce=nonce,
        name=_normalize_text(value["name"], "Workspace name", MAX_WORKSPACE_NAME_LENGTH),
        description=_normalize_text(
            value["description"],
            "Workspace description",
            MAX_WORKSPACE_DESCRIPTION_LENGTH,
            allow_empty=True,
        ),
        owner_member_id=owner_member_id,
        authority_device_id=authority_device_id,
        owner_device=owner,
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def _coerce_role(value: Any) -> WorkspaceRole:
    try:
        return WorkspaceRole(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Workspace member role is invalid") from exc


def _coerce_channel_creation(value: Any) -> WorkspaceChannelCreationPolicy:
    try:
        return WorkspaceChannelCreationPolicy(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Workspace channel-creation policy is invalid") from exc


def _coerce_posting(value: Any) -> WorkspacePostingPolicy:
    try:
        return WorkspacePostingPolicy(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Workspace posting policy is invalid") from exc


def _coerce_invitation_policy(value: Any) -> WorkspaceInvitationPolicy:
    try:
        return WorkspaceInvitationPolicy(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Workspace invitation policy is invalid") from exc


def _validate_retention(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or value not in {30, 90, 365}:
        raise ValidationError("Workspace retention preference is invalid")
    return value


def create_workspace_manifest(
    authority_identity: RNS.Identity,
    *,
    workspace_id: str,
    epoch: int,
    previous_manifest_hash: str,
    name: str,
    description: str,
    authority_device_id: str,
    members: Sequence[WorkspaceManifestMemberInput],
    status: str = "active",
    retention_days: int | None = 90,
    channel_creation: WorkspaceChannelCreationPolicy | str = WorkspaceChannelCreationPolicy.ALL_MEMBERS,
    posting: WorkspacePostingPolicy | str = WorkspacePostingPolicy.ALL_MEMBERS,
    invitation_requests: WorkspaceInvitationPolicy | str = WorkspaceInvitationPolicy.OWNER_ONLY,
    now: int | None = None,
) -> str:
    workspace_id = _validate_uuid(workspace_id, "Workspace ID")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or not 1 <= epoch <= MAX_EPOCH:
        raise ValidationError("Workspace manifest epoch is invalid")
    previous = _validate_digest(previous_manifest_hash, "Previous manifest hash")
    authority_device_id = _validate_uuid(authority_device_id, "Authority device ID")
    if status not in {"active", "closed"}:
        raise ValidationError("Workspace manifest status is invalid")
    if not isinstance(members, Sequence) or not 1 <= len(members) <= MAX_ACTIVE_MEMBERS:
        raise ValidationError("Workspace member count is invalid")
    encoded: list[dict[str, Any]] = []
    seen_members: set[str] = set()
    seen_devices: set[str] = set()
    owner_count = 0
    authority_count = 0
    authority_destination = _destination_for(authority_identity)
    for item in members:
        if not isinstance(item, WorkspaceManifestMemberInput):
            raise ValidationError("Workspace manifest member is invalid")
        member_id = _validate_uuid(item.member_id, "Member ID")
        if member_id in seen_members:
            raise ValidationError("Workspace manifest has a duplicate member")
        seen_members.add(member_id)
        display_name = _normalize_text(
            item.display_name, "Member display name", MAX_MEMBER_NAME_LENGTH
        )
        role = _coerce_role(item.role)
        if item.status not in {"active", "removed", "left"}:
            raise ValidationError("Workspace member status is invalid")
        if role == WorkspaceRole.OWNER:
            owner_count += 1
            if item.status != "active":
                raise ValidationError("Workspace owner must remain active")
        if not isinstance(item.device_cards, Sequence) or len(item.device_cards) != 1:
            raise ValidationError("Workspace members require exactly one device in this increment")
        cards: list[dict[str, Any]] = []
        for raw_card in item.device_cards:
            card = verify_workspace_device_card(
                raw_card,
                expected_workspace_id=workspace_id,
                expected_member_id=member_id,
                now=now,
            )
            if card.device_id in seen_devices:
                raise ValidationError("Workspace manifest has a duplicate device")
            seen_devices.add(card.device_id)
            if card.display_name != display_name:
                raise ValidationError("Member display name does not match its device card")
            if card.device_id == authority_device_id:
                authority_count += 1
                if role != WorkspaceRole.OWNER or card.destination_hash != authority_destination:
                    raise IdentityMismatch("Workspace authority is not the owner signer")
            cards.append(json.loads(card.serialized))
        encoded.append(
            {
                "member_id": member_id,
                "display_name": display_name,
                "role": role.value,
                "status": item.status,
                "devices": cards,
            }
        )
    if owner_count != 1 or authority_count != 1:
        raise ValidationError("Workspace must contain one owner authority device")
    encoded.sort(key=lambda item: item["member_id"])
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_manifest_root",
        "workspace_id": workspace_id,
        "epoch": epoch,
        "previous_manifest_hash": previous,
        "name": _normalize_text(name, "Workspace name", MAX_WORKSPACE_NAME_LENGTH),
        "description": _normalize_text(
            description,
            "Workspace description",
            MAX_WORKSPACE_DESCRIPTION_LENGTH,
            allow_empty=True,
        ),
        "authority_device_id": authority_device_id,
        "authority_destination": authority_destination.hex(),
        "status": status,
        "retention_days": _validate_retention(retention_days),
        "policies": {
            "channel_creation": _coerce_channel_creation(channel_creation).value,
            "posting": _coerce_posting(posting).value,
            "invitation_requests": _coerce_invitation_policy(invitation_requests).value,
        },
        "members": encoded,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(authority_identity, unsigned)


def verify_workspace_manifest(
    raw: str,
    *,
    expected_workspace_id: str | None = None,
    expected_epoch: int | None = None,
    expected_previous_hash: str | None = None,
    expected_authority_destination: bytes | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceManifest:
    value = _load_document(raw, "workspace_manifest_root")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "epoch",
            "previous_manifest_hash",
            "name",
            "description",
            "authority_device_id",
            "authority_destination",
            "status",
            "retention_days",
            "policies",
            "members",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    if expected_workspace_id is not None and workspace_id != _validate_uuid(
        expected_workspace_id, "Workspace ID"
    ):
        raise ValidationError("Manifest belongs to another workspace")
    epoch = value["epoch"]
    if isinstance(epoch, bool) or not isinstance(epoch, int) or not 1 <= epoch <= MAX_EPOCH:
        raise ValidationError("Workspace manifest epoch is invalid")
    if expected_epoch is not None and epoch != expected_epoch:
        raise ValidationError("Workspace manifest epoch is unexpected")
    previous = _validate_digest(value["previous_manifest_hash"], "Previous manifest hash")
    if expected_previous_hash is not None and previous != _validate_digest(
        expected_previous_hash, "Expected previous manifest hash"
    ):
        raise ValidationError("Workspace manifest does not extend the expected state")
    authority_device_id = _validate_uuid(value["authority_device_id"], "Authority device ID")
    authority_destination = _validate_destination(
        value["authority_destination"], "Authority destination"
    )
    if (
        expected_authority_destination is not None
        and authority_destination != expected_authority_destination
    ):
        raise IdentityMismatch("Workspace manifest authority is unexpected")
    if value["status"] not in {"active", "closed"}:
        raise ValidationError("Workspace manifest status is invalid")
    policies = value["policies"]
    if not isinstance(policies, dict) or set(policies) != {
        "channel_creation",
        "posting",
        "invitation_requests",
    }:
        raise ValidationError("Workspace policies are invalid")
    raw_members = value["members"]
    if not isinstance(raw_members, list) or not 1 <= len(raw_members) <= MAX_ACTIVE_MEMBERS:
        raise ValidationError("Workspace member count is invalid")
    members: list[VerifiedWorkspaceMember] = []
    member_ids: list[str] = []
    device_ids: set[str] = set()
    owner_count = 0
    authority_identity: RNS.Identity | None = None
    authority_count = 0
    for item in raw_members:
        if not isinstance(item, dict) or set(item) != {
            "member_id",
            "display_name",
            "role",
            "status",
            "devices",
        }:
            raise ValidationError("Workspace manifest member is invalid")
        member_id = _validate_uuid(item["member_id"], "Member ID")
        member_ids.append(member_id)
        role = _coerce_role(item["role"])
        status = item["status"]
        if status not in {"active", "removed", "left"}:
            raise ValidationError("Workspace member status is invalid")
        if role == WorkspaceRole.OWNER:
            owner_count += 1
            if status != "active":
                raise ValidationError("Workspace owner must remain active")
        raw_devices = item["devices"]
        if not isinstance(raw_devices, list) or len(raw_devices) != 1:
            raise ValidationError("Workspace members require exactly one device in this increment")
        devices: list[VerifiedWorkspaceDeviceCard] = []
        display_name = _normalize_text(
            item["display_name"], "Member display name", MAX_MEMBER_NAME_LENGTH
        )
        for raw_card in raw_devices:
            if not isinstance(raw_card, dict):
                raise ValidationError("Workspace device card is invalid")
            card = verify_workspace_device_card(
                _canonical(raw_card),
                expected_workspace_id=workspace_id,
                expected_member_id=member_id,
                now=now,
            )
            if card.device_id in device_ids:
                raise ValidationError("Workspace manifest has a duplicate device")
            device_ids.add(card.device_id)
            if card.display_name != display_name:
                raise ValidationError("Member display name does not match its device card")
            if card.device_id == authority_device_id:
                authority_count += 1
                if role != WorkspaceRole.OWNER or card.destination_hash != authority_destination:
                    raise IdentityMismatch("Workspace authority is not the owner signer")
                authority_identity = _identity_from_public_key(card.public_identity)
            devices.append(card)
        members.append(
            VerifiedWorkspaceMember(
                member_id=member_id,
                display_name=display_name,
                role=role,
                status=status,
                devices=tuple(devices),
            )
        )
    if member_ids != sorted(member_ids) or len(set(member_ids)) != len(member_ids):
        raise ValidationError("Workspace manifest members are not canonical")
    if owner_count != 1 or authority_count != 1 or authority_identity is None:
        raise ValidationError("Workspace must contain one owner authority device")
    _verify_signature(authority_identity, value, "Workspace manifest")
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    return VerifiedWorkspaceManifest(
        workspace_id=workspace_id,
        epoch=epoch,
        previous_manifest_hash=previous,
        name=_normalize_text(value["name"], "Workspace name", MAX_WORKSPACE_NAME_LENGTH),
        description=_normalize_text(
            value["description"],
            "Workspace description",
            MAX_WORKSPACE_DESCRIPTION_LENGTH,
            allow_empty=True,
        ),
        authority_device_id=authority_device_id,
        authority_destination=authority_destination,
        status=value["status"],
        retention_days=_validate_retention(value["retention_days"]),
        channel_creation=_coerce_channel_creation(policies["channel_creation"]),
        posting=_coerce_posting(policies["posting"]),
        invitation_requests=_coerce_invitation_policy(policies["invitation_requests"]),
        members=tuple(members),
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def _verify_workspace_manifest_checkpoint(
    raw: str,
    genesis: VerifiedWorkspaceGenesis,
    *,
    now: int | None = None,
) -> VerifiedWorkspaceManifest:
    """Verify a checkpoint against its immutable genesis authority."""
    manifest = verify_workspace_manifest(
        raw,
        expected_workspace_id=genesis.workspace_id,
        expected_authority_destination=genesis.owner_device.destination_hash,
        now=now,
    )
    owner = find_member(manifest, genesis.owner_member_id)
    authority = find_device(manifest, genesis.authority_device_id)
    if (
        manifest.authority_device_id != genesis.authority_device_id
        or owner is None
        or owner.role != WorkspaceRole.OWNER
        or authority is None
        or authority[0].member_id != genesis.owner_member_id
        or authority[1].serialized != genesis.owner_device.serialized
        or manifest.created_at < genesis.created_at
    ):
        raise ValidationError("Workspace manifest checkpoint does not match genesis")
    return manifest


def verify_workspace_manifest_transition(
    raw: str,
    previous: VerifiedWorkspaceGenesis | VerifiedWorkspaceManifest,
    *,
    now: int | None = None,
) -> VerifiedWorkspaceManifest:
    if isinstance(previous, VerifiedWorkspaceGenesis):
        manifest = _verify_workspace_manifest_checkpoint(raw, previous, now=now)
        if (
            manifest.epoch != 1
            or manifest.previous_manifest_hash != previous.digest
            or manifest.status != "active"
            or len(manifest.members) != 1
            or manifest.name != previous.name
            or manifest.description != previous.description
        ):
            raise ValidationError("Initial workspace manifest does not match genesis")
        return manifest
    if not isinstance(previous, VerifiedWorkspaceManifest):
        raise ValidationError("Previous workspace state is invalid")
    if previous.status == "closed":
        raise ValidationError("Closed workspaces cannot accept another manifest")
    manifest = verify_workspace_manifest(
        raw,
        expected_workspace_id=previous.workspace_id,
        expected_epoch=previous.epoch + 1,
        expected_previous_hash=previous.digest,
        expected_authority_destination=previous.authority_destination,
        now=now,
    )
    # Authority rotation, linked-device admission, policy changes and retention
    # changes have their own later increments. Increment two additionally
    # permits one workspace metadata update or one member's signed display-name
    # card replacement per epoch.
    if (
        manifest.authority_device_id != previous.authority_device_id
        or manifest.retention_days != previous.retention_days
        or manifest.channel_creation != previous.channel_creation
        or manifest.posting != previous.posting
        or manifest.invitation_requests != previous.invitation_requests
        or manifest.created_at < previous.created_at
    ):
        raise ValidationError("Workspace manifest transition is not enabled")
    previous_members = {member.member_id: member for member in previous.members}
    next_members = {member.member_id: member for member in manifest.members}
    if not previous_members.keys() <= next_members.keys():
        raise ValidationError("Workspace manifest cannot remove member history")
    display_name_changes: list[str] = []
    for member_id, old_member in previous_members.items():
        new_member = next_members[member_id]
        old_devices = tuple(device.serialized for device in old_member.devices)
        new_devices = tuple(device.serialized for device in new_member.devices)
        allowed_statuses = (
            {"active", "left", "removed"}
            if old_member.status == "active" and old_member.role != WorkspaceRole.OWNER
            else {old_member.status}
        )
        if new_member.role != old_member.role or new_member.status not in allowed_statuses:
            raise ValidationError("Workspace member transition is not enabled")
        if new_member.display_name == old_member.display_name:
            if new_devices != old_devices:
                raise ValidationError("Workspace device transition is not enabled")
            continue
        if new_member.status != old_member.status or len(old_member.devices) != 1 or len(new_member.devices) != 1:
            raise ValidationError("Workspace display-name transition is invalid")
        old_device = old_member.devices[0]
        new_device = new_member.devices[0]
        if (
            new_device.workspace_id != old_device.workspace_id
            or new_device.member_id != old_device.member_id
            or new_device.device_id != old_device.device_id
            or new_device.public_identity != old_device.public_identity
            or new_device.destination_hash != old_device.destination_hash
            or new_device.created_at < old_device.created_at
            or new_device.display_name != new_member.display_name
        ):
            raise ValidationError("Workspace display-name device card is invalid")
        display_name_changes.append(member_id)
    added = [
        member for member in manifest.members if member.member_id not in previous_members
    ]
    status_changes = [
        member_id
        for member_id, old_member in previous_members.items()
        if next_members[member_id].status != old_member.status
    ]
    if len(added) > 1 or any(
        member.role != WorkspaceRole.MEMBER or member.status != "active"
        for member in added
    ):
        raise ValidationError("Workspace member admission is invalid")
    if len(status_changes) > 1:
        raise ValidationError("Workspace member transition is invalid")
    if len(display_name_changes) > 1:
        raise ValidationError("Workspace display-name transition is invalid")
    metadata_changed = (
        manifest.name != previous.name or manifest.description != previous.description
    )
    if manifest.status == "closed":
        if added or status_changes or display_name_changes or metadata_changed:
            raise ValidationError(
                "Workspace closure cannot change membership or metadata"
            )
    elif sum(
        (
            bool(added),
            bool(status_changes),
            bool(display_name_changes),
            metadata_changed,
        )
    ) != 1:
        # Publish exactly one semantic change per epoch so concurrent owner
        # operations have a deterministic predecessor and replay boundary.
        raise ValidationError("Workspace manifest transition is not enabled")
    return manifest


def create_workspace_invitation(
    authority_identity: RNS.Identity,
    *,
    genesis: str,
    manifest: str,
    now: int | None = None,
    lifetime_seconds: int = DEFAULT_INVITATION_LIFETIME_SECONDS,
    nonce: bytes | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_INVITATION_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace invitation lifetime is invalid")
    checked_genesis = verify_workspace_genesis(genesis, now=current)
    checked_manifest = _verify_workspace_manifest_checkpoint(
        manifest, checked_genesis, now=current
    )
    if checked_manifest.status != "active":
        raise ValidationError("Closed workspaces cannot create invitations")
    if _destination_for(authority_identity) != checked_manifest.authority_destination:
        raise IdentityMismatch("Invitation signer is not the workspace authority")
    invitation_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if len(invitation_nonce) != NONCE_BYTES:
        raise ValidationError("Workspace invitation nonce is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_invite",
        "workspace_id": checked_genesis.workspace_id,
        "genesis_digest": checked_genesis.digest,
        "offered_manifest_digest": checked_manifest.digest,
        "genesis": json.loads(checked_genesis.serialized),
        "offered_manifest": json.loads(checked_manifest.serialized),
        "authority_chain": [],
        "nonce": _b64encode(invitation_nonce),
        "created_at": current,
        "expires_at": current + lifetime_seconds,
        "use_limit": 1,
    }
    return _sign(authority_identity, unsigned)


def verify_workspace_invitation(
    raw: str, *, now: int | None = None
) -> VerifiedWorkspaceInvitation:
    serialized = extract_workspace_invitation(raw)
    value = _load_document(serialized, "workspace_invite")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "genesis_digest",
            "offered_manifest_digest",
            "genesis",
            "offered_manifest",
            "authority_chain",
            "nonce",
            "created_at",
            "expires_at",
            "use_limit",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["use_limit"] != 1:
        raise ValidationError("Workspace invitation version or use limit is invalid")
    if value["authority_chain"] != []:
        raise ValidationError("Authority transitions are not supported in increment one")
    if not isinstance(value["genesis"], dict) or not isinstance(
        value["offered_manifest"], dict
    ):
        raise ValidationError("Workspace invitation controls are invalid")
    current = int(time.time()) if now is None else int(now)
    genesis = verify_workspace_genesis(_canonical(value["genesis"]), now=current)
    manifest = _verify_workspace_manifest_checkpoint(
        _canonical(value["offered_manifest"]), genesis, now=current
    )
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    if workspace_id != genesis.workspace_id or workspace_id != manifest.workspace_id:
        raise ValidationError("Workspace invitation controls do not match")
    genesis_digest = _validate_digest(value["genesis_digest"], "Genesis digest")
    manifest_digest = _validate_digest(
        value["offered_manifest_digest"], "Offered manifest digest"
    )
    if genesis_digest != genesis.digest or manifest_digest != manifest.digest:
        raise ValidationError("Workspace invitation control digest is invalid")
    if manifest.status != "active":
        raise ValidationError("Workspace invitation is for a closed workspace")
    identity = next(
        _identity_from_public_key(device.public_identity)
        for member in manifest.members
        for device in member.devices
        if device.device_id == manifest.authority_device_id
    )
    _verify_signature(identity, value, "Workspace invitation")
    created_at = _validate_timestamp(value["created_at"], now=current)
    expires_at = value["expires_at"]
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at < created_at
        or expires_at - created_at > MAX_INVITATION_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace invitation dates are invalid")
    if expires_at < current:
        raise InvitationExpired("Workspace invitation has expired")
    return VerifiedWorkspaceInvitation(
        workspace_id=workspace_id,
        genesis_digest=genesis_digest,
        offered_manifest_digest=manifest_digest,
        nonce=_b64decode(value["nonce"], "Invitation nonce", expected_length=NONCE_BYTES),
        created_at=created_at,
        expires_at=expires_at,
        genesis=genesis,
        offered_manifest=manifest,
        serialized=_canonical(value),
    )


def workspace_invitation_formats(
    raw: str, *, now: int | None = None
) -> dict[str, Any]:
    invitation = verify_workspace_invitation(raw, now=now)
    token = _b64encode(invitation.serialized.encode("utf-8"))
    return {
        "link": f"meshchat://workspace/{token}",
        "text": f"MESHWORKSPACE1:{token}",
        "value": invitation.serialized,
        "expires_at": invitation.expires_at,
    }


def extract_workspace_invitation(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValidationError("Workspace invitation is invalid")
    value = raw.translate(_INVISIBLE).strip()
    if not value or len(value.encode("utf-8")) > MAX_WORKSPACE_DOCUMENT_BYTES * 2:
        raise ValidationError("Workspace invitation is empty or too large")
    lower = value.lower()
    if lower.startswith("meshchat://workspace/"):
        compact = "".join(value.split())
        parsed = urlsplit(compact)
        if (
            parsed.scheme != "meshchat"
            or parsed.netloc != "workspace"
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
        ):
            raise ValidationError("Workspace invitation link is invalid")
        return _b64decode(parsed.path[1:], "Workspace invitation token").decode("utf-8")
    if lower.startswith("meshworkspace1:"):
        token = "".join(value.split())[len("MESHWORKSPACE1:") :]
        return _b64decode(token, "Workspace invitation token").decode("utf-8")
    return value


def create_workspace_join(
    identity: RNS.Identity,
    invitation: str | VerifiedWorkspaceInvitation,
    display_name: str,
    *,
    member_id: str | None = None,
    device_id: str | None = None,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    invite = (
        invitation
        if isinstance(invitation, VerifiedWorkspaceInvitation)
        else verify_workspace_invitation(invitation, now=current)
    )
    new_member_id = _validate_uuid(member_id or str(uuid.uuid4()), "Member ID")
    new_device_id = _validate_uuid(device_id or str(uuid.uuid4()), "Device ID")
    card = create_workspace_device_card(
        identity,
        workspace_id=invite.workspace_id,
        member_id=new_member_id,
        device_id=new_device_id,
        display_name=display_name,
        hints=hints,
        now=current,
    )
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_join",
        "workspace_id": invite.workspace_id,
        "genesis_digest": invite.genesis_digest,
        "offered_manifest_digest": invite.offered_manifest_digest,
        "invite_nonce": _b64encode(invite.nonce),
        "member_id": new_member_id,
        "device_card": json.loads(card),
        "invitation": json.loads(invite.serialized),
        "created_at": current,
    }
    return _sign(identity, unsigned)


def verify_workspace_join(
    raw: str,
    *,
    invitation: str | VerifiedWorkspaceInvitation | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceJoin:
    value = _load_document(raw, "workspace_join")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "genesis_digest",
            "offered_manifest_digest",
            "invite_nonce",
            "member_id",
            "device_card",
            "invitation",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    if not isinstance(value["invitation"], dict) or not isinstance(
        value["device_card"], dict
    ):
        raise ValidationError("Workspace join documents are invalid")
    current = int(time.time()) if now is None else int(now)
    embedded = verify_workspace_invitation(_canonical(value["invitation"]), now=current)
    expected = (
        invitation
        if isinstance(invitation, VerifiedWorkspaceInvitation)
        else verify_workspace_invitation(invitation, now=current)
        if isinstance(invitation, str)
        else embedded
    )
    if embedded.serialized != expected.serialized:
        raise ValidationError("Workspace join uses another invitation")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    if (
        workspace_id != embedded.workspace_id
        or value["genesis_digest"] != embedded.genesis_digest
        or value["offered_manifest_digest"] != embedded.offered_manifest_digest
        or _b64decode(value["invite_nonce"], "Invitation nonce", expected_length=NONCE_BYTES)
        != embedded.nonce
    ):
        raise ValidationError("Workspace join does not match its invitation")
    card = verify_workspace_device_card(
        _canonical(value["device_card"]),
        expected_workspace_id=workspace_id,
        expected_member_id=member_id,
        now=current,
    )
    identity = _identity_from_public_key(card.public_identity)
    _verify_signature(identity, value, "Workspace join")
    created_at = _validate_timestamp(value["created_at"], now=current)
    if created_at < embedded.created_at or created_at > embedded.expires_at:
        raise ValidationError("Workspace join date is outside the invitation window")
    return VerifiedWorkspaceJoin(
        workspace_id=workspace_id,
        genesis_digest=embedded.genesis_digest,
        offered_manifest_digest=embedded.offered_manifest_digest,
        invite_nonce=embedded.nonce,
        member_id=member_id,
        device=card,
        invitation=embedded,
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_channel_record(
    manager_identity: RNS.Identity,
    *,
    workspace_id: str,
    channel_id: str,
    manifest_digest: str,
    name: str,
    topic: str,
    manager_member_id: str,
    manager_device_id: str,
    version: int = 1,
    previous_hash: str | None = None,
    visibility: str = "public",
    archived: bool = False,
    now: int | None = None,
) -> str:
    if visibility not in {"public", "private"}:
        raise ValidationError("Workspace channel visibility is invalid")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError("Workspace channel version is invalid")
    if name == "general" and (visibility != "public" or archived):
        raise ValidationError("The general channel must remain public and active")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_record",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "channel_id": _validate_uuid(channel_id, "Channel ID"),
        "version": version,
        "previous_hash": (
            None if previous_hash is None else _validate_digest(previous_hash, "Channel predecessor")
        ),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "name": _normalize_text(name, "Channel name", MAX_CHANNEL_NAME_LENGTH),
        "topic": _normalize_text(
            topic, "Channel topic", MAX_CHANNEL_TOPIC_LENGTH, allow_empty=True
        ),
        "visibility": visibility,
        "manager_member_id": _validate_uuid(manager_member_id, "Manager member ID"),
        "manager_device_id": _validate_uuid(manager_device_id, "Manager device ID"),
        "archived": bool(archived),
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(manager_identity, unsigned)


def verify_workspace_channel_record(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    expected_channel_id: str | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    value = _load_document(raw, "workspace_channel_record")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "channel_id",
            "version",
            "previous_hash",
            "manifest_digest",
            "name",
            "topic",
            "visibility",
            "manager_member_id",
            "manager_device_id",
            "archived",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    channel_id = _validate_uuid(value["channel_id"], "Channel ID")
    if workspace_id != manifest.workspace_id:
        raise ValidationError("Channel belongs to another workspace")
    if expected_channel_id is not None and channel_id != _validate_uuid(
        expected_channel_id, "Channel ID"
    ):
        raise ValidationError("Channel record is unexpected")
    if value["manifest_digest"] != manifest.digest:
        raise ValidationError("Channel record references another manifest")
    manager_member_id = _validate_uuid(value["manager_member_id"], "Manager member ID")
    manager_device_id = _validate_uuid(value["manager_device_id"], "Manager device ID")
    found = find_device(manifest, manager_device_id)
    if found is None or found[0].member_id != manager_member_id or found[0].status != "active":
        raise IdentityMismatch("Channel manager is not an active workspace member")
    identity = _identity_from_public_key(found[1].public_identity)
    _verify_signature(identity, value, "Workspace channel record")
    version = value["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError("Workspace channel version is invalid")
    previous = value["previous_hash"]
    if previous is not None:
        previous = _validate_digest(previous, "Channel predecessor")
    if value["visibility"] not in {"public", "private"} or not isinstance(
        value["archived"], bool
    ):
        raise ValidationError("Workspace channel state is invalid")
    name = _normalize_text(value["name"], "Channel name", MAX_CHANNEL_NAME_LENGTH)
    if name == "general" and (value["visibility"] != "public" or value["archived"]):
        raise ValidationError("The general channel must remain public and active")
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceChannel(
        workspace_id=workspace_id,
        channel_id=channel_id,
        version=version,
        previous_hash=previous,
        manifest_digest=manifest.digest,
        name=name,
        topic=_normalize_text(
            value["topic"], "Channel topic", MAX_CHANNEL_TOPIC_LENGTH, allow_empty=True
        ),
        visibility=value["visibility"],
        manager_member_id=manager_member_id,
        manager_device_id=manager_device_id,
        archived=value["archived"],
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_event(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    conversation_id: str,
    event_id: str,
    author_member_id: str,
    author_device_id: str,
    sequence: int,
    previous_event_digest: str | None,
    manifest_digest: str,
    channel_digest: str,
    text: str,
    created_at: int | None = None,
) -> str:
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
        raise ValidationError("Workspace message is empty or too large")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValidationError("Workspace event sequence is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_event",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "conversation_id": _validate_uuid(conversation_id, "Conversation ID"),
        "event_id": _validate_uuid(event_id, "Event ID"),
        "event_type": "message",
        "author_member_id": _validate_uuid(author_member_id, "Author member ID"),
        "author_device_id": _validate_uuid(author_device_id, "Author device ID"),
        "sequence": sequence,
        "previous_event_digest": (
            None
            if previous_event_digest is None
            else _validate_digest(previous_event_digest, "Previous event digest")
        ),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "channel_digest": _validate_digest(channel_digest, "Channel digest"),
        "payload": {"text": text},
        "thread_root": None,
        "mentions": [],
        "created_at": int(time.time()) if created_at is None else int(created_at),
    }
    return _sign(identity, unsigned, maximum=MAX_WORKSPACE_EVENT_BYTES)


def verify_workspace_event(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    channel: VerifiedWorkspaceChannel,
    now: int | None = None,
) -> VerifiedWorkspaceEvent:
    value = _load_document(raw, "workspace_event")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "conversation_id",
            "event_id",
            "event_type",
            "author_member_id",
            "author_device_id",
            "sequence",
            "previous_event_digest",
            "manifest_digest",
            "channel_digest",
            "payload",
            "thread_root",
            "mentions",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["event_type"] != "message":
        raise ValidationError("Workspace event version or type is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    conversation_id = _validate_uuid(value["conversation_id"], "Conversation ID")
    if workspace_id != manifest.workspace_id or workspace_id != channel.workspace_id:
        raise ValidationError("Workspace event controls do not match")
    if conversation_id != channel.channel_id:
        raise ValidationError("Workspace event belongs to another conversation")
    if value["manifest_digest"] != manifest.digest or value["channel_digest"] != channel.digest:
        raise ValidationError("Workspace event control digest is invalid")
    author_member_id = _validate_uuid(value["author_member_id"], "Author member ID")
    author_device_id = _validate_uuid(value["author_device_id"], "Author device ID")
    found = find_device(manifest, author_device_id)
    if (
        found is None
        or found[0].member_id != author_member_id
        or found[0].status != "active"
        or manifest.status != "active"
    ):
        raise IdentityMismatch("Workspace event author is not active")
    if manifest.posting == WorkspacePostingPolicy.OWNER_AND_ADMINS and found[0].role not in {
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
    }:
        raise IdentityMismatch("Workspace member is not allowed to post")
    identity = _identity_from_public_key(found[1].public_identity)
    _verify_signature(identity, value, "Workspace event")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValidationError("Workspace event sequence is invalid")
    previous = value["previous_event_digest"]
    if previous is not None:
        previous = _validate_digest(previous, "Previous event digest")
    payload = value["payload"]
    if not isinstance(payload, dict) or set(payload) != {"text"}:
        raise ValidationError("Workspace event payload is invalid")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
        raise ValidationError("Workspace message is empty or too large")
    if value["thread_root"] is not None or value["mentions"] != []:
        raise ValidationError("Threads and mentions are not enabled in increment one")
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceEvent(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        event_id=_validate_uuid(value["event_id"], "Event ID"),
        event_type="message",
        author_member_id=author_member_id,
        author_device_id=author_device_id,
        author_destination=found[1].destination_hash,
        sequence=sequence,
        previous_event_digest=previous,
        manifest_digest=manifest.digest,
        channel_digest=channel.digest,
        text=text,
        thread_root=None,
        mentions=(),
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_leave_request(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    now: int | None = None,
) -> str:
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active":
        raise ValidationError("Workspace member cannot leave")
    if found[0].role == WorkspaceRole.OWNER:
        raise ValidationError("Workspace owner cannot leave before transferring ownership")
    if _destination_for(identity) != found[1].destination_hash:
        raise IdentityMismatch("Workspace leave signer is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_leave_request",
        "workspace_id": manifest.workspace_id,
        "manifest_digest": manifest.digest,
        "member_id": member_id,
        "device_id": device_id,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_leave_request(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceLeaveRequest:
    value = _load_document(raw, "workspace_leave_request")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "manifest_digest",
            "member_id",
            "device_id",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    if value["workspace_id"] != manifest.workspace_id or value["manifest_digest"] != manifest.digest:
        raise ValidationError("Workspace leave request is stale")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    device_id = _validate_uuid(value["device_id"], "Device ID")
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active":
        raise IdentityMismatch("Workspace leave signer is not active")
    if found[0].role == WorkspaceRole.OWNER:
        raise ValidationError("Workspace owner cannot leave before transferring ownership")
    _verify_signature(
        _identity_from_public_key(found[1].public_identity), value, "Workspace leave request"
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceLeaveRequest(
        workspace_id=manifest.workspace_id,
        manifest_digest=manifest.digest,
        member_id=member_id,
        device_id=device_id,
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_display_name_request(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    display_name: str,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> str:
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active":
        raise ValidationError("Workspace member cannot change its display name")
    if _destination_for(identity) != found[1].destination_hash:
        raise IdentityMismatch("Workspace display-name signer is invalid")
    created_at = int(time.time()) if now is None else int(now)
    replacement = create_workspace_device_card(
        identity,
        workspace_id=manifest.workspace_id,
        member_id=member_id,
        device_id=device_id,
        display_name=display_name,
        hints=found[1].hints if hints is None else hints,
        now=created_at,
    )
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_display_name_request",
        "workspace_id": manifest.workspace_id,
        "manifest_digest": manifest.digest,
        "member_id": _validate_uuid(member_id, "Member ID"),
        "device_id": _validate_uuid(device_id, "Device ID"),
        "display_name": _normalize_text(
            display_name, "Member display name", MAX_MEMBER_NAME_LENGTH
        ),
        "replacement_device": json.loads(replacement),
        "created_at": created_at,
    }
    return _sign(identity, unsigned)


def verify_workspace_display_name_request(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceDisplayNameRequest:
    value = _load_document(raw, "workspace_display_name_request")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "manifest_digest",
            "member_id",
            "device_id",
            "display_name",
            "replacement_device",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    if value["workspace_id"] != manifest.workspace_id or value["manifest_digest"] != manifest.digest:
        raise ValidationError("Workspace display-name request has an unknown base manifest")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    device_id = _validate_uuid(value["device_id"], "Device ID")
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active":
        raise IdentityMismatch("Workspace display-name signer is not active")
    replacement_value = value["replacement_device"]
    if not isinstance(replacement_value, dict):
        raise ValidationError("Workspace replacement device card is invalid")
    replacement = verify_workspace_device_card(
        _canonical(replacement_value),
        expected_workspace_id=manifest.workspace_id,
        expected_member_id=member_id,
        now=now,
    )
    display_name = _normalize_text(
        value["display_name"], "Member display name", MAX_MEMBER_NAME_LENGTH
    )
    if (
        replacement.device_id != device_id
        or replacement.display_name != display_name
        or replacement.public_identity != found[1].public_identity
        or replacement.destination_hash != found[1].destination_hash
        or replacement.created_at < found[1].created_at
    ):
        raise ValidationError("Workspace replacement device card changed identity")
    _verify_signature(
        _identity_from_public_key(found[1].public_identity),
        value,
        "Workspace display-name request",
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceDisplayNameRequest(
        workspace_id=manifest.workspace_id,
        manifest_digest=manifest.digest,
        member_id=member_id,
        device_id=device_id,
        display_name=display_name,
        replacement_device=replacement,
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_display_name_decision(
    authority_identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    request: VerifiedWorkspaceDisplayNameRequest,
    approved: bool,
    now: int | None = None,
) -> str:
    if (
        request.workspace_id != manifest.workspace_id
        or request.manifest_digest != manifest.digest
    ):
        raise ValidationError("Workspace display-name request base is invalid")
    if _destination_for(authority_identity) != manifest.authority_destination:
        raise IdentityMismatch("Display-name decision signer is not the authority")
    if not isinstance(approved, bool):
        raise ValidationError("Workspace display-name decision is invalid")
    return _sign(
        authority_identity,
        {
            "v": WORKSPACE_PROTOCOL_VERSION,
            "type": "workspace_display_name_decision",
            "workspace_id": manifest.workspace_id,
            "manifest_digest": manifest.digest,
            "request_digest": request.digest,
            "member_id": request.member_id,
            "device_id": request.device_id,
            "approved": approved,
            "created_at": int(time.time()) if now is None else int(now),
        },
    )


def verify_workspace_display_name_decision(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    request: VerifiedWorkspaceDisplayNameRequest,
    now: int | None = None,
) -> VerifiedWorkspaceDisplayNameDecision:
    value = _load_document(raw, "workspace_display_name_decision")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "manifest_digest",
            "request_digest",
            "member_id",
            "device_id",
            "approved",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    if (
        value["workspace_id"] != manifest.workspace_id
        or value["manifest_digest"] != manifest.digest
        or request.workspace_id != manifest.workspace_id
        or request.manifest_digest != manifest.digest
        or value["request_digest"] != request.digest
        or value["member_id"] != request.member_id
        or value["device_id"] != request.device_id
        or not isinstance(value["approved"], bool)
    ):
        raise ValidationError("Workspace display-name decision is invalid")
    authority = find_device(manifest, manifest.authority_device_id)
    if authority is None:
        raise ValidationError("Workspace authority is unavailable")
    _verify_signature(
        _identity_from_public_key(authority[1].public_identity),
        value,
        "Workspace display-name decision",
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceDisplayNameDecision(
        workspace_id=manifest.workspace_id,
        manifest_digest=manifest.digest,
        request_digest=request.digest,
        member_id=request.member_id,
        device_id=request.device_id,
        approved=value["approved"],
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )
