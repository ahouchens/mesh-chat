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
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .emoji_validation import is_valid_reaction_emoji
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
MAX_PUBLIC_CHANNELS = 32
MAX_CHANNEL_SUMMARY_ENTRIES = 32
MAX_CHANNEL_SUMMARY_PAGES = 32
MAX_RETAINED_PUBLIC_CHANNELS = MAX_CHANNEL_SUMMARY_ENTRIES * MAX_CHANNEL_SUMMARY_PAGES
MAX_CHANNEL_FETCH_CONTROLS = 64
MAX_HISTORY_STREAMS = 32
MAX_HISTORY_RANGES = 64
MAX_HISTORY_EVENTS = 32
MAX_HISTORY_CONTROLS = 32
MAX_HISTORY_CHECKPOINTS = 32
MAX_HISTORY_RESPONSE_BYTES = 128 * 1024
MIN_HISTORY_RESPONSE_BYTES = 4 * 1024
MAX_HISTORY_REQUEST_LIFETIME_SECONDS = 15 * 60
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
    removal_checkpoint_digests: tuple[str, ...] = ()


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
    member_ids: tuple[str, ...] = ()
    removal_checkpoint_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceChannelTransferOffer:
    workspace_id: str
    channel_id: str
    channel_head: str
    manifest_digest: str
    manager_member_id: str
    manager_device_id: str
    successor_member_id: str
    successor_device_id: str
    created_at: int
    expires_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceChannelLeaveRequest:
    workspace_id: str
    channel_id: str
    channel_head: str
    manifest_digest: str
    member_id: str
    device_id: str
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceChannelSummary:
    workspace_id: str
    manifest_digest: str
    member_id: str
    device_id: str
    session_id: str
    page_index: int
    page_count: int
    entries: tuple[tuple[str, int, str], ...]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceChannelFetch:
    workspace_id: str
    manifest_digest: str
    member_id: str
    device_id: str
    session_id: str
    requests: tuple[tuple[str, int, str | None], ...]
    max_controls: int
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
    channel_digest: str | None
    text: str | None
    thread_root: str | None
    mentions: tuple[str, ...]
    created_at: int
    digest: str
    serialized: str
    audience_member_ids: tuple[str, ...] = ()
    target_event_id: str | None = None
    base_revision: int | None = None
    revision: int | None = None
    reaction_emoji: str | None = None
    reaction_active: bool | None = None


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceEventCheckpoint:
    workspace_id: str
    checkpoint_id: str
    author_member_id: str
    author_device_id: str
    manifest_digest: str
    streams: tuple[dict[str, Any], ...]
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceHistoryRequest:
    workspace_id: str
    request_id: str
    requester_member_id: str
    requester_device_id: str
    manifest_digest: str
    nonce: bytes
    replay_key: str
    scope: dict[str, Any]
    streams: tuple[dict[str, Any], ...]
    event_limit: int
    byte_limit: int
    continuation: str | None
    created_at: int
    expires_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceHistoryResponse:
    workspace_id: str
    response_id: str
    request_id: str
    request_digest: str
    requester_member_id: str
    requester_device_id: str
    request_nonce: bytes
    request_replay_key: str
    responder_member_id: str
    responder_device_id: str
    scope: dict[str, Any]
    event_limit: int
    byte_limit: int
    expires_at: int
    page_index: int
    previous_response_digest: str | None
    streams: tuple[dict[str, Any], ...]
    controls: tuple[tuple[str, str], ...]
    checkpoints: tuple[str, ...]
    events: tuple[str, ...]
    continuation: str | None
    complete: bool
    document_bytes: int
    created_at: int
    digest: str
    serialized: str


def workspace_direct_conversation_id(
    workspace_id: str, member_ids: Iterable[str]
) -> str:
    """Derive the stable, workspace-scoped identifier for a two-member DM."""

    checked_workspace_id = _validate_uuid(workspace_id, "Workspace ID")
    checked_members = sorted(
        {
            _validate_uuid(member_id, "Workspace direct-message participant ID")
            for member_id in member_ids
        }
    )
    if len(checked_members) != 2:
        raise ValidationError("A workspace direct message requires exactly two members")
    name = "mesh-chat:workspace-direct:v1:" + ":".join(checked_members)
    return str(uuid.uuid5(uuid.UUID(checked_workspace_id), name))


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
        else MAX_HISTORY_RESPONSE_BYTES
        if document_type == "workspace_history_response"
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


def channel_name_key(value: str) -> str:
    """Return the documented presentation-only duplicate comparison key."""
    checked = _normalize_text(value, "Channel name", MAX_CHANNEL_NAME_LENGTH)
    return unicodedata.normalize("NFKC", checked).casefold()


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
    removal_checkpoint_digests: Iterable[str] = (),
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
    checked_checkpoints = sorted({
        _validate_digest(item, "Removal checkpoint digest")
        for item in removal_checkpoint_digests
    })
    if len(checked_checkpoints) > MAX_HISTORY_CHECKPOINTS:
        raise ValidationError("Workspace removal checkpoints are invalid")
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
    if checked_checkpoints:
        unsigned["removal_checkpoint_digests"] = checked_checkpoints
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
    fields = {
            "v", "type", "workspace_id", "epoch", "previous_manifest_hash",
            "name", "description", "authority_device_id", "authority_destination",
            "status", "retention_days", "policies", "members", "created_at", "signature",
        }
    if "removal_checkpoint_digests" in value:
        fields.add("removal_checkpoint_digests")
    _require_fields(
        value,
        fields,
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
    raw_checkpoints = value.get("removal_checkpoint_digests", [])
    if not isinstance(raw_checkpoints, list):
        raise ValidationError("Workspace removal checkpoints are invalid")
    removal_checkpoints = tuple(
        _validate_digest(item, "Removal checkpoint digest")
        for item in raw_checkpoints
    )
    if list(removal_checkpoints) != sorted(removal_checkpoints) or len(set(removal_checkpoints)) != len(removal_checkpoints) or len(removal_checkpoints) > MAX_HISTORY_CHECKPOINTS:
        raise ValidationError("Workspace removal checkpoints are invalid")
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
        removal_checkpoint_digests=removal_checkpoints,
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
    # Authority rotation and linked-device admission have their own later
    # increments. Increment nine permits the exact validated cooperative
    # retention values in addition to the earlier metadata and policy changes.
    if (
        manifest.authority_device_id != previous.authority_device_id
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
    policies_changed = (
        manifest.channel_creation != previous.channel_creation
        or manifest.posting != previous.posting
    )
    retention_changed = manifest.retention_days != previous.retention_days
    if manifest.status == "closed":
        if (
            added
            or status_changes
            or display_name_changes
            or metadata_changed
            or policies_changed
            or retention_changed
        ):
            raise ValidationError(
                "Workspace closure cannot change membership or metadata"
            )
    elif sum(
        (
            bool(added),
            bool(status_changes),
                bool(display_name_changes),
                metadata_changed,
                policies_changed,
                retention_changed,
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


def verify_workspace_channel_record_transition(
    raw: str,
    previous: VerifiedWorkspaceChannel,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    if previous.archived:
        raise ValidationError("Archived workspace channels are terminal")
    channel = verify_workspace_channel_record(
        raw,
        manifest=manifest,
        expected_channel_id=previous.channel_id,
        now=now,
    )
    if (
        channel.workspace_id != previous.workspace_id
        or channel.version != previous.version + 1
        or channel.previous_hash != previous.digest
        or channel.visibility != "public"
        or previous.visibility != "public"
        or channel.manager_member_id != previous.manager_member_id
        or channel.manager_device_id != previous.manager_device_id
    ):
        raise ValidationError("Workspace channel record does not extend the current head")
    if previous.name == "general" and (channel.name != "general" or channel.archived):
        raise ValidationError("The general channel cannot be renamed or archived")
    if channel.created_at < previous.created_at:
        raise ValidationError("Workspace channel record date is invalid")
    return channel


def create_workspace_channel_manifest(
    manager_identity: RNS.Identity,
    *,
    workspace_id: str,
    channel_id: str,
    manifest_digest: str,
    name: str,
    topic: str,
    manager_member_id: str,
    manager_device_id: str,
    member_ids: Iterable[str],
    version: int = 1,
    previous_hash: str | None = None,
    archived: bool = False,
    removal_checkpoint_digests: Iterable[str] = (),
    now: int | None = None,
) -> str:
    """Create a private-channel control.

    Private controls deliberately use a distinct document family so a public
    directory record can never be reinterpreted as a private membership grant.
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError("Workspace channel version is invalid")
    try:
        checked_members = sorted(
            {
                _validate_uuid(value, "Private channel member ID")
                for value in member_ids
            }
        )
    except TypeError as exc:
        raise ValidationError("Private channel roster is invalid") from exc
    if not checked_members or len(checked_members) > MAX_ACTIVE_MEMBERS:
        raise ValidationError("A private channel requires one to eight members")
    checked_manager = _validate_uuid(manager_member_id, "Manager member ID")
    if checked_manager not in checked_members:
        raise ValidationError("Private channel manager must be a channel member")
    if not isinstance(archived, bool):
        raise ValidationError("Workspace channel state is invalid")
    checked_checkpoints = sorted({
        _validate_digest(item, "Removal checkpoint digest")
        for item in removal_checkpoint_digests
    })
    if len(checked_checkpoints) > MAX_HISTORY_CHECKPOINTS:
        raise ValidationError("Private channel removal checkpoints are invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_manifest",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "channel_id": _validate_uuid(channel_id, "Channel ID"),
        "version": version,
        "previous_hash": (
            None
            if previous_hash is None
            else _validate_digest(previous_hash, "Channel predecessor")
        ),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "name": _normalize_text(name, "Channel name", MAX_CHANNEL_NAME_LENGTH),
        "topic": _normalize_text(
            topic, "Channel topic", MAX_CHANNEL_TOPIC_LENGTH, allow_empty=True
        ),
        "manager_member_id": checked_manager,
        "manager_device_id": _validate_uuid(manager_device_id, "Manager device ID"),
        "member_ids": checked_members,
        "archived": archived,
        "created_at": int(time.time()) if now is None else int(now),
    }
    if checked_checkpoints:
        unsigned["removal_checkpoint_digests"] = checked_checkpoints
    return _sign(manager_identity, unsigned)


def verify_workspace_channel_manifest(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    expected_channel_id: str | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    value = _load_document(raw, "workspace_channel_manifest")
    fields = {
            "v", "type", "workspace_id", "channel_id", "version", "previous_hash",
            "manifest_digest", "name", "topic", "manager_member_id",
            "manager_device_id", "member_ids", "archived", "created_at", "signature",
        }
    if "removal_checkpoint_digests" in value:
        fields.add("removal_checkpoint_digests")
    _require_fields(
        value,
        fields,
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
        raise ValidationError("Channel manifest is unexpected")
    if value["manifest_digest"] != manifest.digest:
        raise ValidationError("Channel manifest references another workspace manifest")
    version = value["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError("Workspace channel version is invalid")
    previous = value["previous_hash"]
    if previous is not None:
        previous = _validate_digest(previous, "Channel predecessor")
    raw_members = value["member_ids"]
    if not isinstance(raw_members, list):
        raise ValidationError("Private channel roster is invalid")
    member_ids = tuple(
        _validate_uuid(member_id, "Private channel member ID")
        for member_id in raw_members
    )
    if (
        not member_ids
        or len(member_ids) > MAX_ACTIVE_MEMBERS
        or list(member_ids) != sorted(member_ids)
        or len(set(member_ids)) != len(member_ids)
    ):
        raise ValidationError("Private channel roster is invalid")
    for member_id in member_ids:
        member = find_member(manifest, member_id)
        if member is None or member.status != "active":
            raise IdentityMismatch("Private channel member is not active")
    manager_member_id = _validate_uuid(value["manager_member_id"], "Manager member ID")
    manager_device_id = _validate_uuid(value["manager_device_id"], "Manager device ID")
    manager = find_device(manifest, manager_device_id)
    if (
        manager_member_id not in member_ids
        or manager is None
        or manager[0].member_id != manager_member_id
        or manager[0].status != "active"
    ):
        raise IdentityMismatch("Private channel manager is not an active channel member")
    _verify_signature(
        _identity_from_public_key(manager[1].public_identity),
        value,
        "Workspace private channel manifest",
    )
    if not isinstance(value["archived"], bool):
        raise ValidationError("Workspace channel state is invalid")
    current = int(time.time()) if now is None else int(now)
    raw_checkpoints = value.get("removal_checkpoint_digests", [])
    if not isinstance(raw_checkpoints, list):
        raise ValidationError("Private channel removal checkpoints are invalid")
    removal_checkpoints = tuple(
        _validate_digest(item, "Removal checkpoint digest")
        for item in raw_checkpoints
    )
    if list(removal_checkpoints) != sorted(removal_checkpoints) or len(set(removal_checkpoints)) != len(removal_checkpoints) or len(removal_checkpoints) > MAX_HISTORY_CHECKPOINTS:
        raise ValidationError("Private channel removal checkpoints are invalid")
    return VerifiedWorkspaceChannel(
        workspace_id=workspace_id,
        channel_id=channel_id,
        version=version,
        previous_hash=previous,
        manifest_digest=manifest.digest,
        name=_normalize_text(value["name"], "Channel name", MAX_CHANNEL_NAME_LENGTH),
        topic=_normalize_text(
            value["topic"], "Channel topic", MAX_CHANNEL_TOPIC_LENGTH, allow_empty=True
        ),
        visibility="private",
        manager_member_id=manager_member_id,
        manager_device_id=manager_device_id,
        archived=value["archived"],
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
        member_ids=member_ids,
        removal_checkpoint_digests=removal_checkpoints,
    )


def verify_workspace_channel_manifest_transition(
    raw: str,
    previous: VerifiedWorkspaceChannel,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    if previous.archived:
        raise ValidationError("Archived workspace channels are terminal")
    channel = verify_workspace_channel_manifest(
        raw,
        manifest=manifest,
        expected_channel_id=previous.channel_id,
        now=now,
    )
    if (
        previous.visibility != "private"
        or channel.version != previous.version + 1
        or channel.previous_hash != previous.digest
        or channel.manager_member_id != previous.manager_member_id
        or channel.manager_device_id != previous.manager_device_id
        or channel.created_at < previous.created_at
    ):
        raise ValidationError("Private channel manifest does not extend the current head")
    return channel


def create_workspace_channel_transfer_offer(
    manager_identity: RNS.Identity,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    successor_member_id: str,
    successor_device_id: str,
    lifetime_seconds: int = 7 * 24 * 60 * 60,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    if channel.archived:
        raise ValidationError("Workspace channel cannot transfer management")
    if not 1 <= lifetime_seconds <= 7 * 24 * 60 * 60:
        raise ValidationError("Workspace channel transfer lifetime is invalid")
    successor = find_device(manifest, successor_device_id)
    if (
        successor is None
        or successor[0].member_id != _validate_uuid(successor_member_id, "Successor member ID")
        or successor[0].status != "active"
        or (
            channel.visibility == "private"
            and successor[0].member_id not in channel.member_ids
        )
    ):
        raise ValidationError("Workspace channel successor is not active")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_transfer_offer",
        "workspace_id": channel.workspace_id,
        "channel_id": channel.channel_id,
        "channel_head": channel.digest,
        "manifest_digest": manifest.digest,
        "manager_member_id": channel.manager_member_id,
        "manager_device_id": channel.manager_device_id,
        "successor_member_id": successor[0].member_id,
        "successor_device_id": successor[1].device_id,
        "created_at": current,
        "expires_at": current + lifetime_seconds,
    }
    return _sign(manager_identity, unsigned)


def verify_workspace_channel_transfer_offer(
    raw: str,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannelTransferOffer:
    value = _load_document(raw, "workspace_channel_transfer_offer")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "channel_id",
            "channel_head",
            "manifest_digest",
            "manager_member_id",
            "manager_device_id",
            "successor_member_id",
            "successor_device_id",
            "created_at",
            "expires_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    channel_id = _validate_uuid(value["channel_id"], "Channel ID")
    channel_head = _validate_digest(value["channel_head"], "Channel head")
    manifest_digest = _validate_digest(value["manifest_digest"], "Manifest digest")
    manager_member_id = _validate_uuid(value["manager_member_id"], "Manager member ID")
    manager_device_id = _validate_uuid(value["manager_device_id"], "Manager device ID")
    successor_member_id = _validate_uuid(value["successor_member_id"], "Successor member ID")
    successor_device_id = _validate_uuid(value["successor_device_id"], "Successor device ID")
    if (
        channel.archived
        or workspace_id != channel.workspace_id
        or workspace_id != manifest.workspace_id
        or channel_id != channel.channel_id
        or channel_head != channel.digest
        or manifest_digest != manifest.digest
        or manager_member_id != channel.manager_member_id
        or manager_device_id != channel.manager_device_id
    ):
        raise ValidationError("Workspace channel transfer offer is stale")
    manager = find_device(manifest, manager_device_id)
    successor = find_device(manifest, successor_device_id)
    if (
        manager is None
        or manager[0].member_id != manager_member_id
        or manager[0].status != "active"
        or successor is None
        or successor[0].member_id != successor_member_id
        or successor[0].status != "active"
        or (
            channel.visibility == "private"
            and successor_member_id not in channel.member_ids
        )
    ):
        raise IdentityMismatch("Workspace channel transfer participant is not active")
    _verify_signature(
        _identity_from_public_key(manager[1].public_identity),
        value,
        "Workspace channel transfer offer",
    )
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    expires_at = value["expires_at"]
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at < current
        or expires_at <= created_at
        or expires_at > created_at + 7 * 24 * 60 * 60
    ):
        raise ValidationError("Workspace channel transfer offer expired")
    return VerifiedWorkspaceChannelTransferOffer(
        workspace_id=workspace_id,
        channel_id=channel_id,
        channel_head=channel_head,
        manifest_digest=manifest_digest,
        manager_member_id=manager_member_id,
        manager_device_id=manager_device_id,
        successor_member_id=successor_member_id,
        successor_device_id=successor_device_id,
        created_at=created_at,
        expires_at=expires_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_channel_transfer(
    successor_identity: RNS.Identity,
    *,
    offer: VerifiedWorkspaceChannelTransferOffer,
    now: int | None = None,
) -> str:
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_transfer",
        "offer": json.loads(offer.serialized),
        "accepted_at": int(time.time()) if now is None else int(now),
    }
    return _sign(successor_identity, unsigned)


def verify_workspace_channel_transfer(
    raw: str,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    value = _load_document(raw, "workspace_channel_transfer")
    _require_fields(value, {"v", "type", "offer", "accepted_at", "signature"})
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or not isinstance(value["offer"], dict):
        raise ValidationError("Workspace channel transfer is invalid")
    offer = verify_workspace_channel_transfer_offer(
        _canonical(value["offer"]), channel=channel, manifest=manifest, now=now
    )
    successor = find_device(manifest, offer.successor_device_id)
    if successor is None or successor[0].member_id != offer.successor_member_id:
        raise IdentityMismatch("Workspace channel successor is unavailable")
    _verify_signature(
        _identity_from_public_key(successor[1].public_identity),
        value,
        "Workspace channel transfer",
    )
    current = int(time.time()) if now is None else int(now)
    accepted_at = _validate_timestamp(value["accepted_at"], now=current)
    if accepted_at < offer.created_at or accepted_at > offer.expires_at:
        raise ValidationError("Workspace channel transfer acceptance is invalid")
    return VerifiedWorkspaceChannel(
        workspace_id=channel.workspace_id,
        channel_id=channel.channel_id,
        version=channel.version + 1,
        previous_hash=channel.digest,
        manifest_digest=manifest.digest,
        name=channel.name,
        topic=channel.topic,
        visibility=channel.visibility,
        manager_member_id=offer.successor_member_id,
        manager_device_id=offer.successor_device_id,
        archived=False,
        created_at=accepted_at,
        digest=_digest(value),
        serialized=_canonical(value),
        member_ids=channel.member_ids,
    )


def create_workspace_channel_leave_request(
    identity: RNS.Identity,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    now: int | None = None,
) -> str:
    if channel.visibility != "private" or channel.archived:
        raise ValidationError("Only an active private channel can be left")
    checked_member_id = _validate_uuid(member_id, "Member ID")
    checked_device_id = _validate_uuid(device_id, "Device ID")
    found = find_device(manifest, checked_device_id)
    if (
        checked_member_id == channel.manager_member_id
        or checked_member_id not in channel.member_ids
        or found is None
        or found[0].member_id != checked_member_id
        or found[0].status != "active"
    ):
        raise IdentityMismatch("Private channel member cannot leave at this head")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_leave_request",
        "workspace_id": channel.workspace_id,
        "channel_id": channel.channel_id,
        "channel_head": channel.digest,
        "manifest_digest": manifest.digest,
        "member_id": checked_member_id,
        "device_id": checked_device_id,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_channel_leave_request(
    raw: str,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannelLeaveRequest:
    value = _load_document(raw, "workspace_channel_leave_request")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "channel_id",
            "channel_head",
            "manifest_digest",
            "member_id",
            "device_id",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    device_id = _validate_uuid(value["device_id"], "Device ID")
    if (
        channel.visibility != "private"
        or channel.archived
        or _validate_uuid(value["workspace_id"], "Workspace ID") != channel.workspace_id
        or _validate_uuid(value["channel_id"], "Channel ID") != channel.channel_id
        or _validate_digest(value["channel_head"], "Channel head") != channel.digest
        or _validate_digest(value["manifest_digest"], "Manifest digest")
        != manifest.digest
        or member_id == channel.manager_member_id
        or member_id not in channel.member_ids
    ):
        raise ValidationError("Private channel leave request is stale")
    found = find_device(manifest, device_id)
    if (
        found is None
        or found[0].member_id != member_id
        or found[0].status != "active"
    ):
        raise IdentityMismatch("Private channel leave signer is not active")
    _verify_signature(
        _identity_from_public_key(found[1].public_identity),
        value,
        "Workspace private channel leave request",
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceChannelLeaveRequest(
        workspace_id=channel.workspace_id,
        channel_id=channel.channel_id,
        channel_head=channel.digest,
        manifest_digest=manifest.digest,
        member_id=member_id,
        device_id=device_id,
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_channel_recovery(
    authority_identity: RNS.Identity,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    manager_member_id: str,
    manager_device_id: str,
    now: int | None = None,
) -> str:
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_recovery",
        "workspace_id": channel.workspace_id,
        "channel_id": channel.channel_id,
        "channel_head": channel.digest,
        "manifest_digest": manifest.digest,
        "manager_member_id": _validate_uuid(manager_member_id, "Manager member ID"),
        "manager_device_id": _validate_uuid(manager_device_id, "Manager device ID"),
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(authority_identity, unsigned)


def verify_workspace_channel_recovery(
    raw: str,
    *,
    channel: VerifiedWorkspaceChannel,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannel:
    value = _load_document(raw, "workspace_channel_recovery")
    _require_fields(
        value,
        {
            "v",
            "type",
            "workspace_id",
            "channel_id",
            "channel_head",
            "manifest_digest",
            "manager_member_id",
            "manager_device_id",
            "created_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace document version is unsupported")
    manager_member_id = _validate_uuid(value["manager_member_id"], "Manager member ID")
    manager_device_id = _validate_uuid(value["manager_device_id"], "Manager device ID")
    if (
        channel.archived
        or _validate_uuid(value["workspace_id"], "Workspace ID") != channel.workspace_id
        or _validate_uuid(value["channel_id"], "Channel ID") != channel.channel_id
        or _validate_digest(value["channel_head"], "Channel head") != channel.digest
        or _validate_digest(value["manifest_digest"], "Manifest digest") != manifest.digest
    ):
        raise ValidationError("Workspace channel recovery is stale")
    authority = find_device(manifest, manifest.authority_device_id)
    successor = find_device(manifest, manager_device_id)
    if (
        authority is None
        or authority[0].role != WorkspaceRole.OWNER
        or successor is None
        or successor[0].member_id != manager_member_id
        or successor[0].status != "active"
        or (
            channel.visibility == "private"
            and authority[0].member_id not in channel.member_ids
        )
        or (
            channel.visibility == "private"
            and manager_member_id not in channel.member_ids
        )
    ):
        raise IdentityMismatch("Workspace channel recovery authority is invalid")
    _verify_signature(
        _identity_from_public_key(authority[1].public_identity),
        value,
        "Workspace channel recovery",
    )
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    if created_at < channel.created_at:
        raise ValidationError("Workspace channel recovery date is invalid")
    return VerifiedWorkspaceChannel(
        workspace_id=channel.workspace_id,
        channel_id=channel.channel_id,
        version=channel.version + 1,
        previous_hash=channel.digest,
        manifest_digest=manifest.digest,
        name=channel.name,
        topic=channel.topic,
        visibility=channel.visibility,
        manager_member_id=manager_member_id,
        manager_device_id=manager_device_id,
        archived=False,
        created_at=created_at,
        digest=_digest(value),
        serialized=_canonical(value),
        member_ids=channel.member_ids,
    )


def _workspace_summary_signer(
    manifest: VerifiedWorkspaceManifest, member_id: Any, device_id: Any
) -> tuple[str, str, VerifiedWorkspaceDeviceCard]:
    checked_member_id = _validate_uuid(member_id, "Member ID")
    checked_device_id = _validate_uuid(device_id, "Device ID")
    found = find_device(manifest, checked_device_id)
    if found is None or found[0].member_id != checked_member_id or found[0].status != "active":
        raise IdentityMismatch("Workspace channel sync signer is not active")
    return checked_member_id, checked_device_id, found[1]


def create_workspace_channel_summary(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    session_id: str,
    entries: Sequence[tuple[str, int, str]],
    page_index: int = 0,
    page_count: int = 1,
    now: int | None = None,
) -> str:
    if len(entries) > MAX_CHANNEL_SUMMARY_ENTRIES:
        raise ValidationError("Workspace channel summary is too large")
    encoded = [
        {
            "channel_id": _validate_uuid(channel_id, "Channel ID"),
            "version": version,
            "head_hash": _validate_digest(head_hash, "Channel head"),
        }
        for channel_id, version, head_hash in entries
    ]
    if any(isinstance(item[1], bool) or not isinstance(item[1], int) or item[1] < 1 for item in entries):
        raise ValidationError("Workspace channel summary version is invalid")
    encoded.sort(key=lambda item: item["channel_id"])
    if len({item["channel_id"] for item in encoded}) != len(encoded):
        raise ValidationError("Workspace channel summary has duplicate entries")
    if (
        isinstance(page_index, bool)
        or isinstance(page_count, bool)
        or not isinstance(page_index, int)
        or not isinstance(page_count, int)
        or not 1 <= page_count <= MAX_CHANNEL_SUMMARY_PAGES
        or not 0 <= page_index < page_count
    ):
        raise ValidationError("Workspace channel summary page is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_summary",
        "workspace_id": manifest.workspace_id,
        "manifest_digest": manifest.digest,
        "member_id": _validate_uuid(member_id, "Member ID"),
        "device_id": _validate_uuid(device_id, "Device ID"),
        "session_id": _validate_uuid(session_id, "Session ID"),
        "page_index": page_index,
        "page_count": page_count,
        "entries": encoded,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_channel_summary(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannelSummary:
    value = _load_document(raw, "workspace_channel_summary")
    _require_fields(
        value,
        {"v", "type", "workspace_id", "manifest_digest", "member_id", "device_id", "session_id", "page_index", "page_count", "entries", "created_at", "signature"},
    )
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or _validate_uuid(value["workspace_id"], "Workspace ID") != manifest.workspace_id
        or _validate_digest(value["manifest_digest"], "Manifest digest") != manifest.digest
    ):
        raise ValidationError("Workspace channel summary control is invalid")
    member_id, device_id, device = _workspace_summary_signer(
        manifest, value["member_id"], value["device_id"]
    )
    page_index = value["page_index"]
    page_count = value["page_count"]
    if (
        isinstance(page_index, bool)
        or isinstance(page_count, bool)
        or not isinstance(page_index, int)
        or not isinstance(page_count, int)
        or not 1 <= page_count <= MAX_CHANNEL_SUMMARY_PAGES
        or not 0 <= page_index < page_count
    ):
        raise ValidationError("Workspace channel summary page is invalid")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_CHANNEL_SUMMARY_ENTRIES:
        raise ValidationError("Workspace channel summary is invalid")
    entries: list[tuple[str, int, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict) or set(item) != {"channel_id", "version", "head_hash"}:
            raise ValidationError("Workspace channel summary entry is invalid")
        version = item["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError("Workspace channel summary version is invalid")
        entries.append(
            (
                _validate_uuid(item["channel_id"], "Channel ID"),
                version,
                _validate_digest(item["head_hash"], "Channel head"),
            )
        )
    if entries != sorted(entries) or len({entry[0] for entry in entries}) != len(entries):
        raise ValidationError("Workspace channel summary entries are not canonical")
    _verify_signature(
        _identity_from_public_key(device.public_identity), value, "Workspace channel summary"
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceChannelSummary(
        workspace_id=manifest.workspace_id,
        manifest_digest=manifest.digest,
        member_id=member_id,
        device_id=device_id,
        session_id=_validate_uuid(value["session_id"], "Session ID"),
        page_index=page_index,
        page_count=page_count,
        entries=tuple(entries),
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_channel_fetch(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    session_id: str,
    requests: Sequence[tuple[str, int, str | None]],
    max_controls: int = MAX_CHANNEL_FETCH_CONTROLS,
    now: int | None = None,
) -> str:
    if not requests or len(requests) > MAX_CHANNEL_SUMMARY_ENTRIES:
        raise ValidationError("Workspace channel fetch request count is invalid")
    if isinstance(max_controls, bool) or not 1 <= max_controls <= MAX_CHANNEL_FETCH_CONTROLS:
        raise ValidationError("Workspace channel fetch limit is invalid")
    encoded = [
        {
            "channel_id": _validate_uuid(channel_id, "Channel ID"),
            "known_version": known_version,
            "known_head_hash": None if known_head is None else _validate_digest(known_head, "Known channel head"),
        }
        for channel_id, known_version, known_head in requests
    ]
    if any(isinstance(item[1], bool) or not isinstance(item[1], int) or item[1] < 0 for item in requests):
        raise ValidationError("Workspace channel fetch version is invalid")
    encoded.sort(key=lambda item: item["channel_id"])
    if len({item["channel_id"] for item in encoded}) != len(encoded):
        raise ValidationError("Workspace channel fetch has duplicate entries")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_channel_fetch",
        "workspace_id": manifest.workspace_id,
        "manifest_digest": manifest.digest,
        "member_id": _validate_uuid(member_id, "Member ID"),
        "device_id": _validate_uuid(device_id, "Device ID"),
        "session_id": _validate_uuid(session_id, "Session ID"),
        "requests": encoded,
        "max_controls": max_controls,
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_channel_fetch(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceChannelFetch:
    value = _load_document(raw, "workspace_channel_fetch")
    _require_fields(
        value,
        {"v", "type", "workspace_id", "manifest_digest", "member_id", "device_id", "session_id", "requests", "max_controls", "created_at", "signature"},
    )
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or _validate_uuid(value["workspace_id"], "Workspace ID") != manifest.workspace_id
        or _validate_digest(value["manifest_digest"], "Manifest digest") != manifest.digest
    ):
        raise ValidationError("Workspace channel fetch control is invalid")
    member_id, device_id, device = _workspace_summary_signer(
        manifest, value["member_id"], value["device_id"]
    )
    raw_requests = value["requests"]
    if not isinstance(raw_requests, list) or not 1 <= len(raw_requests) <= MAX_CHANNEL_SUMMARY_ENTRIES:
        raise ValidationError("Workspace channel fetch requests are invalid")
    requests: list[tuple[str, int, str | None]] = []
    for item in raw_requests:
        if not isinstance(item, dict) or set(item) != {"channel_id", "known_version", "known_head_hash"}:
            raise ValidationError("Workspace channel fetch entry is invalid")
        version = item["known_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValidationError("Workspace channel fetch version is invalid")
        known_head = item["known_head_hash"]
        requests.append(
            (
                _validate_uuid(item["channel_id"], "Channel ID"),
                version,
                None if known_head is None else _validate_digest(known_head, "Known channel head"),
            )
        )
    if requests != sorted(requests) or len({request[0] for request in requests}) != len(requests):
        raise ValidationError("Workspace channel fetch requests are not canonical")
    max_controls = value["max_controls"]
    if isinstance(max_controls, bool) or not isinstance(max_controls, int) or not 1 <= max_controls <= MAX_CHANNEL_FETCH_CONTROLS:
        raise ValidationError("Workspace channel fetch limit is invalid")
    _verify_signature(
        _identity_from_public_key(device.public_identity), value, "Workspace channel fetch"
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceChannelFetch(
        workspace_id=manifest.workspace_id,
        manifest_digest=manifest.digest,
        member_id=member_id,
        device_id=device_id,
        session_id=_validate_uuid(value["session_id"], "Session ID"),
        requests=tuple(requests),
        max_controls=max_controls,
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
    channel_digest: str | None,
    text: str,
    thread_root: str | None = None,
    audience_member_ids: Iterable[str] | None = None,
    mention_member_ids: Iterable[str] | None = None,
    created_at: int | None = None,
) -> str:
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
        raise ValidationError("Workspace message is empty or too large")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValidationError("Workspace event sequence is invalid")
    mentions = sorted(
        {
            _validate_uuid(member_id, "Workspace mention member ID")
            for member_id in (mention_member_ids or ())
        }
    )
    if len(mentions) > MAX_ACTIVE_MEMBERS:
        raise ValidationError("Workspace event mentions are invalid")
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
        "channel_digest": (
            None
            if channel_digest is None
            else _validate_digest(channel_digest, "Channel digest")
        ),
        "payload": {"text": text},
        "thread_root": (
            None
            if thread_root is None
            else _validate_uuid(thread_root, "Workspace thread root event ID")
        ),
        "mentions": mentions,
        "created_at": int(time.time()) if created_at is None else int(created_at),
    }
    if audience_member_ids is not None:
        audience = sorted(
            {
                _validate_uuid(member_id, "Workspace event audience member ID")
                for member_id in audience_member_ids
            }
        )
        if not audience or len(audience) > MAX_ACTIVE_MEMBERS:
            raise ValidationError("Workspace event audience is invalid")
        unsigned["audience_member_ids"] = audience
    return _sign(identity, unsigned, maximum=MAX_WORKSPACE_EVENT_BYTES)


def create_workspace_mutation_event(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    conversation_id: str,
    event_id: str,
    event_type: str,
    author_member_id: str,
    author_device_id: str,
    sequence: int,
    previous_event_digest: str | None,
    manifest_digest: str,
    channel_digest: str | None,
    target_event_id: str,
    base_revision: int,
    revision: int,
    text: str | None = None,
    emoji: str | None = None,
    active: bool | None = None,
    thread_root: str | None = None,
    audience_member_ids: Iterable[str] | None = None,
    mention_member_ids: Iterable[str] | None = None,
    created_at: int | None = None,
) -> str:
    """Create an author mutation or member reaction without changing v1 messages."""

    if event_type not in {"edit", "delete", "reaction"}:
        raise ValidationError("Workspace mutation type is invalid")
    if (
        isinstance(base_revision, bool)
        or not isinstance(base_revision, int)
        or base_revision < 0
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision != base_revision + 1
        or revision > MAX_SEQUENCE
    ):
        raise ValidationError("Workspace mutation revision is invalid")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValidationError("Workspace event sequence is invalid")
    if event_type == "edit":
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace message is empty or too large")
        payload: dict[str, Any] = {"text": text}
    elif event_type == "delete":
        if text is not None or emoji is not None or active is not None:
            raise ValidationError("Workspace deletion payload is invalid")
        payload = {}
    else:
        if not is_valid_reaction_emoji(emoji) or not isinstance(active, bool):
            raise ValidationError("Workspace reaction payload is invalid")
        payload = {"emoji": emoji, "active": active}
    mentions = sorted(
        {
            _validate_uuid(member_id, "Workspace mention member ID")
            for member_id in (mention_member_ids or ())
        }
    )
    if len(mentions) > MAX_ACTIVE_MEMBERS or (event_type != "edit" and mentions):
        raise ValidationError("Workspace mutation mentions are invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_event",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "conversation_id": _validate_uuid(conversation_id, "Conversation ID"),
        "event_id": _validate_uuid(event_id, "Event ID"),
        "event_type": event_type,
        "author_member_id": _validate_uuid(author_member_id, "Author member ID"),
        "author_device_id": _validate_uuid(author_device_id, "Author device ID"),
        "sequence": sequence,
        "previous_event_digest": (
            None if previous_event_digest is None
            else _validate_digest(previous_event_digest, "Previous event digest")
        ),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "channel_digest": (
            None if channel_digest is None
            else _validate_digest(channel_digest, "Channel digest")
        ),
        "target_event_id": _validate_uuid(target_event_id, "Target event ID"),
        "base_revision": base_revision,
        "revision": revision,
        "payload": payload,
        "thread_root": (
            None
            if thread_root is None
            else _validate_uuid(thread_root, "Workspace thread root event ID")
        ),
        "mentions": mentions,
        "created_at": int(time.time()) if created_at is None else int(created_at),
    }
    if audience_member_ids is not None:
        audience = sorted(
            {
                _validate_uuid(member_id, "Workspace event audience member ID")
                for member_id in audience_member_ids
            }
        )
        if not audience or len(audience) > MAX_ACTIVE_MEMBERS:
            raise ValidationError("Workspace event audience is invalid")
        unsigned["audience_member_ids"] = audience
    return _sign(identity, unsigned, maximum=MAX_WORKSPACE_EVENT_BYTES)


def verify_workspace_event(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    channel: VerifiedWorkspaceChannel | None,
    direct_member_ids: Iterable[str] | None = None,
    now: int | None = None,
) -> VerifiedWorkspaceEvent:
    value = _load_document(raw, "workspace_event")
    fields = {
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
        }
    event_type = value.get("event_type")
    if event_type in {"edit", "delete", "reaction"}:
        fields.update({"target_event_id", "base_revision", "revision"})
    if "audience_member_ids" in value:
        fields.add("audience_member_ids")
    _require_fields(value, fields)
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or event_type not in {
        "message", "edit", "delete", "reaction"
    }:
        raise ValidationError("Workspace event version or type is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    conversation_id = _validate_uuid(value["conversation_id"], "Conversation ID")
    if workspace_id != manifest.workspace_id:
        raise ValidationError("Workspace event controls do not match")
    if value["manifest_digest"] != manifest.digest:
        raise ValidationError("Workspace event manifest digest is invalid")
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
    raw_audience = value.get("audience_member_ids")
    if channel is None:
        if direct_member_ids is None:
            raise ValidationError("Workspace direct-message participants are missing")
        direct_members = tuple(
            sorted(
                {
                    _validate_uuid(
                        member_id, "Workspace direct-message participant ID"
                    )
                    for member_id in direct_member_ids
                }
            )
        )
        if len(direct_members) != 2:
            raise ValidationError(
                "A workspace direct message requires exactly two members"
            )
        if conversation_id != workspace_direct_conversation_id(
            workspace_id, direct_members
        ):
            raise ValidationError("Workspace direct-message identifier is invalid")
        if value["channel_digest"] is not None:
            raise ValidationError(
                "Workspace direct messages cannot reference a channel control"
            )
        if not isinstance(raw_audience, list):
            raise ValidationError("Workspace direct-message audience is missing")
        audience_member_ids = tuple(
            _validate_uuid(member_id, "Workspace event audience member ID")
            for member_id in raw_audience
        )
        if (
            list(audience_member_ids) != sorted(audience_member_ids)
            or len(set(audience_member_ids)) != len(audience_member_ids)
            or audience_member_ids != direct_members
            or author_member_id not in audience_member_ids
            or any(
                (participant := find_member(manifest, member_id)) is None
                or participant.status != "active"
                for member_id in direct_members
            )
        ):
            raise IdentityMismatch("Workspace direct-message audience is invalid")
        channel_digest = None
    elif channel.visibility == "private":
        if workspace_id != channel.workspace_id:
            raise ValidationError("Workspace event controls do not match")
        if conversation_id != channel.channel_id:
            raise ValidationError("Workspace event belongs to another conversation")
        if value["channel_digest"] != channel.digest:
            raise ValidationError("Workspace event channel digest is invalid")
        if not isinstance(raw_audience, list):
            raise ValidationError("Private workspace event audience is missing")
        audience_member_ids = tuple(
            _validate_uuid(member_id, "Workspace event audience member ID")
            for member_id in raw_audience
        )
        if (
            list(audience_member_ids) != sorted(audience_member_ids)
            or len(set(audience_member_ids)) != len(audience_member_ids)
            or (event_type == "message" and audience_member_ids != channel.member_ids)
            or not audience_member_ids
            or len(audience_member_ids) > MAX_ACTIVE_MEMBERS
            or author_member_id not in audience_member_ids
        ):
            raise IdentityMismatch("Private workspace event audience is invalid")
        channel_digest = channel.digest
    else:
        if workspace_id != channel.workspace_id:
            raise ValidationError("Workspace event controls do not match")
        if conversation_id != channel.channel_id:
            raise ValidationError("Workspace event belongs to another conversation")
        if value["channel_digest"] != channel.digest:
            raise ValidationError("Workspace event channel digest is invalid")
        if raw_audience is not None:
            raise ValidationError("Public workspace events cannot carry a private audience")
        audience_member_ids = ()
        channel_digest = channel.digest
    raw_mentions = value["mentions"]
    if not isinstance(raw_mentions, list):
        raise ValidationError("Workspace event mentions are invalid")
    mentions = tuple(
        _validate_uuid(member_id, "Workspace mention member ID")
        for member_id in raw_mentions
    )
    if (
        list(mentions) != sorted(mentions)
        or len(set(mentions)) != len(mentions)
        or len(mentions) > MAX_ACTIVE_MEMBERS
        or (event_type not in {"message", "edit"} and mentions)
        or any(
            (mentioned := find_member(manifest, member_id)) is None
            or mentioned.status != "active"
            or (audience_member_ids and member_id not in audience_member_ids)
            for member_id in mentions
        )
    ):
        raise IdentityMismatch("Workspace event mention audience is invalid")
    if (
        channel is not None
        and event_type == "message"
        and manifest.posting == WorkspacePostingPolicy.OWNER_AND_ADMINS
        and found[0].role != WorkspaceRole.OWNER
    ):
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
    text: str | None = None
    reaction_emoji: str | None = None
    reaction_active: bool | None = None
    target_event_id: str | None = None
    base_revision: int | None = None
    revision: int | None = None
    if event_type in {"message", "edit"}:
        if not isinstance(payload, dict) or set(payload) != {"text"}:
            raise ValidationError("Workspace event payload is invalid")
        text = payload["text"]
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace message is empty or too large")
    elif event_type == "delete":
        if not isinstance(payload, dict) or payload:
            raise ValidationError("Workspace deletion payload is invalid")
    else:
        if not isinstance(payload, dict) or set(payload) != {"emoji", "active"}:
            raise ValidationError("Workspace reaction payload is invalid")
        reaction_emoji = payload["emoji"]
        reaction_active = payload["active"]
        if not is_valid_reaction_emoji(reaction_emoji) or not isinstance(reaction_active, bool):
            raise ValidationError("Workspace reaction payload is invalid")
    if event_type != "message":
        target_event_id = _validate_uuid(value["target_event_id"], "Target event ID")
        base_revision = value["base_revision"]
        revision = value["revision"]
        if (
            isinstance(base_revision, bool)
            or not isinstance(base_revision, int)
            or base_revision < 0
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision != base_revision + 1
            or revision > MAX_SEQUENCE
        ):
            raise ValidationError("Workspace mutation revision is invalid")
    raw_thread_root = value["thread_root"]
    thread_root = (
        None
        if raw_thread_root is None
        else _validate_uuid(raw_thread_root, "Workspace thread root event ID")
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceEvent(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        event_id=_validate_uuid(value["event_id"], "Event ID"),
        event_type=event_type,
        author_member_id=author_member_id,
        author_device_id=author_device_id,
        author_destination=found[1].destination_hash,
        sequence=sequence,
        previous_event_digest=previous,
        manifest_digest=manifest.digest,
        channel_digest=channel_digest,
        text=text,
        thread_root=thread_root,
        mentions=mentions,
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
        audience_member_ids=audience_member_ids,
        target_event_id=target_event_id,
        base_revision=base_revision,
        revision=revision,
        reaction_emoji=reaction_emoji,
        reaction_active=reaction_active,
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


def _history_ranges(value: Any, label: str) -> list[list[int]]:
    if not isinstance(value, list) or len(value) > MAX_HISTORY_RANGES:
        raise ValidationError(f"{label} are invalid")
    checked: list[list[int]] = []
    previous_end = 0
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(isinstance(part, bool) or not isinstance(part, int) for part in item)
            or item[0] < 1
            or item[1] < item[0]
            or item[1] > MAX_SEQUENCE
            or item[0] <= previous_end
        ):
            raise ValidationError(f"{label} are invalid")
        checked.append([item[0], item[1]])
        previous_end = item[1]
    return checked


def _history_scope(value: Any, *, workspace_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "kind", "conversation_id", "channel_digest", "participant_member_ids"
    }:
        raise ValidationError("Workspace history scope is invalid")
    kind = value["kind"]
    if kind not in {"public", "private", "direct"}:
        raise ValidationError("Workspace history scope is invalid")
    conversation_id = _validate_uuid(value["conversation_id"], "Conversation ID")
    channel_digest = value["channel_digest"]
    participants = value["participant_member_ids"]
    if kind == "direct":
        if channel_digest is not None or not isinstance(participants, list):
            raise ValidationError("Workspace direct history scope is invalid")
        checked_participants = [
            _validate_uuid(item, "Workspace direct-message participant ID")
            for item in participants
        ]
        if (
            len(checked_participants) != 2
            or checked_participants != sorted(checked_participants)
            or len(set(checked_participants)) != 2
            or conversation_id
            != workspace_direct_conversation_id(workspace_id, checked_participants)
        ):
            raise ValidationError("Workspace direct history scope is invalid")
    else:
        if not isinstance(channel_digest, str) or participants != []:
            raise ValidationError("Workspace channel history scope is invalid")
        channel_digest = _validate_digest(channel_digest, "Channel digest")
        checked_participants = []
    return {
        "kind": kind,
        "conversation_id": conversation_id,
        "channel_digest": channel_digest,
        "participant_member_ids": checked_participants,
    }


def _history_streams(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_HISTORY_STREAMS:
        raise ValidationError("Workspace history streams are invalid")
    checked: list[dict[str, Any]] = []
    total_ranges = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "author_device_id", "known_high_water", "retained_floor", "head_digest",
            "seen_ranges", "gaps", "request_ranges",
        }:
            raise ValidationError("Workspace history stream is invalid")
        device_id = _validate_uuid(item["author_device_id"], "Author device ID")
        high_water = item["known_high_water"]
        retained_floor = item["retained_floor"]
        if (
            isinstance(high_water, bool)
            or not isinstance(high_water, int)
            or not 0 <= high_water <= MAX_SEQUENCE
            or isinstance(retained_floor, bool)
            or not isinstance(retained_floor, int)
            or not 1 <= retained_floor <= MAX_SEQUENCE
            or retained_floor > max(1, high_water + 1)
        ):
            raise ValidationError("Workspace history stream coverage is invalid")
        head_digest = item["head_digest"]
        if high_water == 0:
            if head_digest is not None:
                raise ValidationError("Workspace history stream head is invalid")
        else:
            head_digest = _validate_digest(head_digest, "Workspace history head digest")
        seen = _history_ranges(item["seen_ranges"], "Workspace history seen ranges")
        gaps = _history_ranges(item["gaps"], "Workspace history gaps")
        requested = _history_ranges(item["request_ranges"], "Workspace history requested ranges")
        if not requested:
            raise ValidationError("Workspace history requested ranges are empty")
        total_ranges += len(seen) + len(gaps) + len(requested)
        checked.append({
            "author_device_id": device_id,
            "known_high_water": high_water,
            "retained_floor": retained_floor,
            "head_digest": head_digest,
            "seen_ranges": seen,
            "gaps": gaps,
            "request_ranges": requested,
        })
    device_ids = [item["author_device_id"] for item in checked]
    if total_ranges > MAX_HISTORY_RANGES:
        raise ValidationError("Workspace history ranges are too fragmented")
    if device_ids != sorted(device_ids) or len(set(device_ids)) != len(device_ids):
        raise ValidationError("Workspace history streams are not canonical")
    return tuple(checked)


def create_workspace_event_checkpoint(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    checkpoint_id: str,
    author_member_id: str,
    author_device_id: str,
    manifest_digest: str,
    streams: Sequence[dict[str, Any]],
    created_at: int | None = None,
) -> str:
    encoded: list[dict[str, Any]] = []
    if not isinstance(streams, Sequence) or not 1 <= len(streams) <= MAX_HISTORY_STREAMS:
        raise ValidationError("Workspace checkpoint streams are invalid")
    for item in streams:
        if not isinstance(item, dict) or set(item) != {
            "conversation_id", "channel_digest", "high_water", "head_digest"
        }:
            raise ValidationError("Workspace checkpoint stream is invalid")
        high_water = item["high_water"]
        if isinstance(high_water, bool) or not isinstance(high_water, int) or not 1 <= high_water <= MAX_SEQUENCE:
            raise ValidationError("Workspace checkpoint high-water is invalid")
        encoded.append({
            "conversation_id": _validate_uuid(item["conversation_id"], "Conversation ID"),
            "channel_digest": None if item["channel_digest"] is None else _validate_digest(item["channel_digest"], "Channel digest"),
            "high_water": high_water,
            "head_digest": _validate_digest(item["head_digest"], "Workspace checkpoint head digest"),
        })
    encoded.sort(key=lambda item: (item["conversation_id"], item["channel_digest"] or ""))
    if len({(item["conversation_id"], item["channel_digest"]) for item in encoded}) != len(encoded):
        raise ValidationError("Workspace checkpoint streams are duplicated")
    return _sign(identity, {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_event_checkpoint",
        "workspace_id": _validate_uuid(workspace_id, "Workspace ID"),
        "checkpoint_id": _validate_uuid(checkpoint_id, "Checkpoint ID"),
        "author_member_id": _validate_uuid(author_member_id, "Author member ID"),
        "author_device_id": _validate_uuid(author_device_id, "Author device ID"),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "streams": encoded,
        "created_at": int(time.time()) if created_at is None else int(created_at),
    })


def verify_workspace_event_checkpoint(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceEventCheckpoint:
    value = _load_document(raw, "workspace_event_checkpoint")
    _require_fields(value, {
        "v", "type", "workspace_id", "checkpoint_id", "author_member_id",
        "author_device_id", "manifest_digest", "streams", "created_at", "signature",
    })
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["workspace_id"] != manifest.workspace_id or value["manifest_digest"] != manifest.digest:
        raise ValidationError("Workspace checkpoint controls do not match")
    author_member_id = _validate_uuid(value["author_member_id"], "Author member ID")
    author_device_id = _validate_uuid(value["author_device_id"], "Author device ID")
    found = find_device(manifest, author_device_id)
    if found is None or found[0].member_id != author_member_id or found[0].status != "active":
        raise IdentityMismatch("Workspace checkpoint author is not active")
    raw_streams = value["streams"]
    if not isinstance(raw_streams, list) or not 1 <= len(raw_streams) <= MAX_HISTORY_STREAMS:
        raise ValidationError("Workspace checkpoint streams are invalid")
    streams: list[dict[str, Any]] = []
    for item in raw_streams:
        if not isinstance(item, dict) or set(item) != {"conversation_id", "channel_digest", "high_water", "head_digest"}:
            raise ValidationError("Workspace checkpoint stream is invalid")
        high_water = item["high_water"]
        if isinstance(high_water, bool) or not isinstance(high_water, int) or not 1 <= high_water <= MAX_SEQUENCE:
            raise ValidationError("Workspace checkpoint high-water is invalid")
        streams.append({
            "conversation_id": _validate_uuid(item["conversation_id"], "Conversation ID"),
            "channel_digest": None if item["channel_digest"] is None else _validate_digest(item["channel_digest"], "Channel digest"),
            "high_water": high_water,
            "head_digest": _validate_digest(item["head_digest"], "Workspace checkpoint head digest"),
        })
    if streams != sorted(streams, key=lambda item: (item["conversation_id"], item["channel_digest"] or "")) or len({(item["conversation_id"], item["channel_digest"]) for item in streams}) != len(streams):
        raise ValidationError("Workspace checkpoint streams are not canonical")
    _verify_signature(_identity_from_public_key(found[1].public_identity), value, "Workspace event checkpoint")
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceEventCheckpoint(
        workspace_id=manifest.workspace_id,
        checkpoint_id=_validate_uuid(value["checkpoint_id"], "Checkpoint ID"),
        author_member_id=author_member_id,
        author_device_id=author_device_id,
        manifest_digest=manifest.digest,
        streams=tuple(streams),
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_history_request(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    request_id: str,
    requester_member_id: str,
    requester_device_id: str,
    manifest_digest: str,
    scope: dict[str, Any],
    streams: Sequence[dict[str, Any]],
    event_limit: int = MAX_HISTORY_EVENTS,
    byte_limit: int = MAX_HISTORY_RESPONSE_BYTES,
    continuation: str | None = None,
    nonce: bytes | None = None,
    replay_key: str | None = None,
    created_at: int | None = None,
    expires_at: int | None = None,
) -> str:
    created = int(time.time()) if created_at is None else int(created_at)
    expires = created + MAX_HISTORY_REQUEST_LIFETIME_SECONDS if expires_at is None else int(expires_at)
    if expires < created or expires > created + MAX_HISTORY_REQUEST_LIFETIME_SECONDS:
        raise ValidationError("Workspace history request expiry is invalid")
    if isinstance(event_limit, bool) or not isinstance(event_limit, int) or not 1 <= event_limit <= MAX_HISTORY_EVENTS:
        raise ValidationError("Workspace history event limit is invalid")
    if isinstance(byte_limit, bool) or not isinstance(byte_limit, int) or not MIN_HISTORY_RESPONSE_BYTES <= byte_limit <= MAX_HISTORY_RESPONSE_BYTES:
        raise ValidationError("Workspace history byte limit is invalid")
    checked_workspace_id = _validate_uuid(workspace_id, "Workspace ID")
    checked_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(checked_nonce, bytes) or len(checked_nonce) != NONCE_BYTES:
        raise ValidationError("Workspace history nonce is invalid")
    return _sign(identity, {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_history_request",
        "workspace_id": checked_workspace_id,
        "request_id": _validate_uuid(request_id, "Request ID"),
        "requester_member_id": _validate_uuid(requester_member_id, "Requester member ID"),
        "requester_device_id": _validate_uuid(requester_device_id, "Requester device ID"),
        "manifest_digest": _validate_digest(manifest_digest, "Manifest digest"),
        "nonce": _b64encode(checked_nonce),
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "scope": _history_scope(scope, workspace_id=checked_workspace_id),
        "streams": list(_history_streams(list(streams))),
        "event_limit": event_limit,
        "byte_limit": byte_limit,
        "continuation": None if continuation is None else _validate_digest(continuation, "Workspace history continuation"),
        "created_at": created,
        "expires_at": expires,
    })


def verify_workspace_history_request(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceHistoryRequest:
    value = _load_document(raw, "workspace_history_request")
    _require_fields(value, {
        "v", "type", "workspace_id", "request_id", "requester_member_id",
        "requester_device_id", "manifest_digest", "nonce", "replay_key", "scope",
        "streams", "event_limit", "byte_limit", "continuation", "created_at",
        "expires_at", "signature",
    })
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["workspace_id"] != manifest.workspace_id or value["manifest_digest"] != manifest.digest:
        raise ValidationError("Workspace history request controls do not match")
    member_id = _validate_uuid(value["requester_member_id"], "Requester member ID")
    device_id = _validate_uuid(value["requester_device_id"], "Requester device ID")
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active" or manifest.status != "active":
        raise IdentityMismatch("Workspace history requester is not active")
    _verify_signature(_identity_from_public_key(found[1].public_identity), value, "Workspace history request")
    current = int(time.time()) if now is None else int(now)
    created = _validate_timestamp(value["created_at"], now=current)
    expires = value["expires_at"]
    if isinstance(expires, bool) or not isinstance(expires, int) or expires < current or expires < created or expires > created + MAX_HISTORY_REQUEST_LIFETIME_SECONDS:
        raise InvitationExpired("Workspace history request has expired")
    event_limit = value["event_limit"]
    byte_limit = value["byte_limit"]
    if isinstance(event_limit, bool) or not isinstance(event_limit, int) or not 1 <= event_limit <= MAX_HISTORY_EVENTS:
        raise ValidationError("Workspace history event limit is invalid")
    if isinstance(byte_limit, bool) or not isinstance(byte_limit, int) or not MIN_HISTORY_RESPONSE_BYTES <= byte_limit <= MAX_HISTORY_RESPONSE_BYTES:
        raise ValidationError("Workspace history byte limit is invalid")
    continuation = value["continuation"]
    if continuation is not None:
        continuation = _validate_digest(continuation, "Workspace history continuation")
    return VerifiedWorkspaceHistoryRequest(
        workspace_id=manifest.workspace_id,
        request_id=_validate_uuid(value["request_id"], "Request ID"),
        requester_member_id=member_id,
        requester_device_id=device_id,
        manifest_digest=manifest.digest,
        nonce=_b64decode(value["nonce"], "Workspace history nonce", expected_length=NONCE_BYTES),
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        scope=_history_scope(value["scope"], workspace_id=manifest.workspace_id),
        streams=_history_streams(value["streams"]),
        event_limit=event_limit,
        byte_limit=byte_limit,
        continuation=continuation,
        created_at=created,
        expires_at=expires,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def _history_response_streams(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) > MAX_HISTORY_STREAMS:
        raise ValidationError("Workspace history response streams are invalid")
    checked: list[dict[str, Any]] = []
    total_ranges = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "author_device_id", "high_water", "head_digest", "retained_floor",
            "available_ranges", "gaps",
        }:
            raise ValidationError("Workspace history response stream is invalid")
        high_water = item["high_water"]
        retained_floor = item["retained_floor"]
        if (
            isinstance(high_water, bool) or not isinstance(high_water, int)
            or not 0 <= high_water <= MAX_SEQUENCE
            or isinstance(retained_floor, bool) or not isinstance(retained_floor, int)
            or not 1 <= retained_floor <= max(1, high_water + 1)
        ):
            raise ValidationError("Workspace history response coverage is invalid")
        head_digest = item["head_digest"]
        if high_water == 0:
            if head_digest is not None:
                raise ValidationError("Workspace history response head is invalid")
        else:
            head_digest = _validate_digest(head_digest, "Workspace history response head")
        available = _history_ranges(item["available_ranges"], "Workspace history available ranges")
        gaps = _history_ranges(item["gaps"], "Workspace history response gaps")
        total_ranges += len(available) + len(gaps)
        checked.append({
            "author_device_id": _validate_uuid(item["author_device_id"], "Author device ID"),
            "high_water": high_water,
            "head_digest": head_digest,
            "retained_floor": retained_floor,
            "available_ranges": available,
            "gaps": gaps,
        })
    device_ids = [item["author_device_id"] for item in checked]
    if total_ranges > MAX_HISTORY_RANGES or device_ids != sorted(device_ids) or len(set(device_ids)) != len(device_ids):
        raise ValidationError("Workspace history response streams are not canonical")
    return tuple(checked)


def create_workspace_history_response(
    identity: RNS.Identity,
    *,
    request: VerifiedWorkspaceHistoryRequest,
    response_id: str,
    responder_member_id: str,
    responder_device_id: str,
    page_index: int,
    previous_response_digest: str | None,
    streams: Sequence[dict[str, Any]] = (),
    controls: Sequence[tuple[str, str]] = (),
    checkpoints: Sequence[str] = (),
    events: Sequence[str] = (),
    continuation: str | None = None,
    complete: bool = False,
    created_at: int | None = None,
) -> str:
    if isinstance(page_index, bool) or not isinstance(page_index, int) or not 0 <= page_index <= MAX_SEQUENCE:
        raise ValidationError("Workspace history response page is invalid")
    if len(events) > request.event_limit or len(events) > MAX_HISTORY_EVENTS or len(controls) > MAX_HISTORY_CONTROLS or len(checkpoints) > MAX_HISTORY_CHECKPOINTS:
        raise ValidationError("Workspace history response count limit exceeded")
    encoded_controls = [{"kind": kind, "document": document} for kind, document in controls]
    encoded_streams = _history_response_streams(list(streams))
    document_bytes = sum(len(item["document"].encode("utf-8")) for item in encoded_controls) + sum(len(item.encode("utf-8")) for item in checkpoints) + sum(len(item.encode("utf-8")) for item in events)
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_history_response",
        "workspace_id": request.workspace_id,
        "response_id": _validate_uuid(response_id, "Response ID"),
        "request_id": request.request_id,
        "request_digest": request.digest,
        "requester_member_id": request.requester_member_id,
        "requester_device_id": request.requester_device_id,
        "request_nonce": _b64encode(request.nonce),
        "request_replay_key": request.replay_key,
        "responder_member_id": _validate_uuid(responder_member_id, "Responder member ID"),
        "responder_device_id": _validate_uuid(responder_device_id, "Responder device ID"),
        "scope": request.scope,
        "event_limit": request.event_limit,
        "byte_limit": request.byte_limit,
        "expires_at": request.expires_at,
        "page_index": page_index,
        "previous_response_digest": None if previous_response_digest is None else _validate_digest(previous_response_digest, "Previous response digest"),
        "streams": list(encoded_streams),
        "controls": encoded_controls,
        "checkpoints": list(checkpoints),
        "events": list(events),
        "event_count": len(events),
        "document_bytes": document_bytes,
        "continuation": None if continuation is None else _validate_digest(continuation, "Workspace history continuation"),
        "complete": bool(complete),
        "created_at": int(time.time()) if created_at is None else int(created_at),
    }
    serialized = _sign(identity, unsigned, maximum=MAX_HISTORY_RESPONSE_BYTES)
    if len(serialized.encode("utf-8")) > request.byte_limit:
        raise ValidationError("Workspace history response byte limit exceeded")
    return serialized


def verify_workspace_history_response(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    request: VerifiedWorkspaceHistoryRequest,
    now: int | None = None,
) -> VerifiedWorkspaceHistoryResponse:
    if len(raw.encode("utf-8")) > request.byte_limit:
        raise ValidationError("Workspace history response byte limit exceeded")
    value = _load_document(raw, "workspace_history_response")
    _require_fields(value, {
        "v", "type", "workspace_id", "response_id", "request_id", "request_digest",
        "requester_member_id", "requester_device_id", "request_nonce", "request_replay_key",
        "responder_member_id", "responder_device_id", "scope", "event_limit", "byte_limit",
        "expires_at", "page_index", "previous_response_digest", "streams", "controls", "checkpoints",
        "events", "event_count", "document_bytes", "continuation", "complete", "created_at",
        "signature",
    })
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or value["workspace_id"] != request.workspace_id
        or value["workspace_id"] != manifest.workspace_id
        or value["request_id"] != request.request_id
        or value["request_digest"] != request.digest
        or value["requester_member_id"] != request.requester_member_id
        or value["requester_device_id"] != request.requester_device_id
        or value["request_nonce"] != _b64encode(request.nonce)
        or value["request_replay_key"] != request.replay_key
        or value["scope"] != request.scope
        or value["event_limit"] != request.event_limit
        or value["byte_limit"] != request.byte_limit
        or value["expires_at"] != request.expires_at
    ):
        raise ValidationError("Workspace history response is not bound to its request")
    member_id = _validate_uuid(value["responder_member_id"], "Responder member ID")
    device_id = _validate_uuid(value["responder_device_id"], "Responder device ID")
    found = find_device(manifest, device_id)
    if found is None or found[0].member_id != member_id or found[0].status != "active" or manifest.status != "active":
        raise IdentityMismatch("Workspace history responder is not active")
    _verify_signature(_identity_from_public_key(found[1].public_identity), value, "Workspace history response")
    current = int(time.time()) if now is None else int(now)
    created = _validate_timestamp(value["created_at"], now=current)
    if current > request.expires_at or created > request.expires_at:
        raise InvitationExpired("Workspace history response has expired")
    page_index = value["page_index"]
    if isinstance(page_index, bool) or not isinstance(page_index, int) or not 0 <= page_index <= MAX_SEQUENCE:
        raise ValidationError("Workspace history response page is invalid")
    previous = value["previous_response_digest"]
    if previous is not None:
        previous = _validate_digest(previous, "Previous response digest")
    raw_controls = value["controls"]
    raw_checkpoints = value["checkpoints"]
    raw_events = value["events"]
    if (
        not isinstance(raw_controls, list) or len(raw_controls) > MAX_HISTORY_CONTROLS
        or not isinstance(raw_checkpoints, list) or len(raw_checkpoints) > MAX_HISTORY_CHECKPOINTS
        or not isinstance(raw_events, list) or len(raw_events) > request.event_limit or len(raw_events) > MAX_HISTORY_EVENTS
        or value["event_count"] != len(raw_events)
        or not isinstance(value["complete"], bool)
    ):
        raise ValidationError("Workspace history response counts are invalid")
    response_streams = _history_response_streams(value["streams"])
    requested_devices = {item["author_device_id"] for item in request.streams}
    if any(item["author_device_id"] not in requested_devices for item in response_streams):
        raise ValidationError("Workspace history response stream is outside the request")
    controls: list[tuple[str, str]] = []
    allowed_controls = {"workspace_manifest_root", "workspace_channel_record", "workspace_channel_manifest", "workspace_channel_transfer", "workspace_channel_recovery"}
    for item in raw_controls:
        if not isinstance(item, dict) or set(item) != {"kind", "document"} or item["kind"] not in allowed_controls:
            raise ValidationError("Workspace history control is invalid")
        control = _load_document(item["document"], item["kind"])
        if control.get("workspace_id") != request.workspace_id:
            raise ValidationError("Workspace history control belongs to another workspace")
        controls.append((item["kind"], item["document"]))
    checkpoints: list[str] = []
    for item in raw_checkpoints:
        checkpoint = _load_document(item, "workspace_event_checkpoint")
        if checkpoint.get("workspace_id") != request.workspace_id:
            raise ValidationError("Workspace history checkpoint belongs to another workspace")
        checkpoints.append(item)
    events: list[str] = []
    requested_by_device = {stream["author_device_id"]: stream["request_ranges"] for stream in request.streams}
    for item in raw_events:
        event = _load_document(item, "workspace_event")
        if event.get("workspace_id") != request.workspace_id or event.get("conversation_id") != request.scope["conversation_id"]:
            raise ValidationError("Workspace history event is outside the requested scope")
        device_ranges = requested_by_device.get(event.get("author_device_id"))
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or not device_ranges or not any(start <= sequence <= end for start, end in device_ranges):
            raise ValidationError("Workspace history event is outside the requested range")
        events.append(item)
    document_bytes = sum(len(document.encode("utf-8")) for _, document in controls) + sum(len(item.encode("utf-8")) for item in checkpoints) + sum(len(item.encode("utf-8")) for item in events)
    if value["document_bytes"] != document_bytes:
        raise ValidationError("Workspace history response byte count is invalid")
    continuation = value["continuation"]
    if continuation is not None:
        continuation = _validate_digest(continuation, "Workspace history continuation")
    return VerifiedWorkspaceHistoryResponse(
        workspace_id=request.workspace_id,
        response_id=_validate_uuid(value["response_id"], "Response ID"),
        request_id=request.request_id,
        request_digest=request.digest,
        requester_member_id=request.requester_member_id,
        requester_device_id=request.requester_device_id,
        request_nonce=request.nonce,
        request_replay_key=request.replay_key,
        responder_member_id=member_id,
        responder_device_id=device_id,
        scope=request.scope,
        event_limit=request.event_limit,
        byte_limit=request.byte_limit,
        expires_at=request.expires_at,
        page_index=page_index,
        previous_response_digest=previous,
        streams=response_streams,
        controls=tuple(controls),
        checkpoints=tuple(checkpoints),
        events=tuple(events),
        continuation=continuation,
        complete=value["complete"],
        document_bytes=document_bytes,
        created_at=created,
        digest=_digest(value),
        serialized=_canonical(value),
    )
