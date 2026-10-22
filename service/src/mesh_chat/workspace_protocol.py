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
MAX_ADMIN_REQUEST_BYTES = 4 * 1024
MAX_ADMIN_DECISION_BYTES = 48 * 1024
MAX_ADMIN_REQUEST_LIFETIME_SECONDS = 7 * 24 * 60 * 60
MAX_ADMIN_REQUEST_NOTE_LENGTH = 250
MAX_AUTHORITY_OFFER_BYTES = 8 * 1024
MAX_AUTHORITY_ACCEPTANCE_BYTES = 16 * 1024
MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS = 7 * 24 * 60 * 60
MAX_AUTHORITY_TRANSITIONS = 8
MAX_AUTHORITY_BOOTSTRAP_BYTES = 256 * 1024
MAX_DEVICE_LINK_BYTES = 320 * 1024
MAX_DEVICE_LINK_LIFETIME_SECONDS = 15 * 60
MAX_DEVICE_BOOTSTRAP_MANIFESTS = 64
# The text field itself is 16 KiB. The canonical event has a separate bounded
# allowance for IDs and the author signature.
MAX_MESSAGE_TEXT_BYTES = 16 * 1024
MAX_MEMBER_HINTS = 2
MAX_ACTIVE_MEMBERS = 8
# Historical manifests prepared the device array with a wider parser bound.
# Linked-device enrollment is deliberately capped at three active devices per
# member while retaining read compatibility with those canonical manifests.
MAX_DEVICES_PER_MEMBER = 8
MAX_LINKED_DEVICES_PER_MEMBER = 3
MAX_ACTIVE_DEVICES = 24
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
    authority_transition_digest: str | None = None
    authority_signer_destination: bytes | None = None
    device_transition_digest: str | None = None
    delegated_signer_destination: bytes | None = None
    delegation_grant_digest: str | None = None
    delegation_grant_use: int | None = None


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDeviceLinkOffer:
    workspace_id: str
    link_id: str
    base_manifest_epoch: int
    base_manifest_digest: str
    member_id: str
    sponsor_device_id: str
    sponsor_destination: bytes
    nonce: bytes
    replay_key: str
    created_at: int
    expires_at: int
    genesis: VerifiedWorkspaceGenesis
    offered_manifest: VerifiedWorkspaceManifest
    authority_chain: tuple[dict[str, str | None], ...]
    bootstrap_manifests: tuple[VerifiedWorkspaceManifest, ...]
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDeviceLinkAcceptance:
    offer: VerifiedWorkspaceDeviceLinkOffer
    device: VerifiedWorkspaceDeviceCard
    replay_key: str
    accepted_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceDeviceRemoval:
    workspace_id: str
    removal_id: str
    base_manifest_epoch: int
    base_manifest_digest: str
    member_id: str
    actor_device_id: str
    target_device_id: str
    replay_key: str
    created_at: int
    expires_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceReadHint:
    workspace_id: str
    manifest_digest: str
    member_id: str
    device_id: str
    conversation_id: str
    through_event_id: str
    event_digest: str
    created_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceAuthorityOffer:
    workspace_id: str
    transition_id: str
    transition_kind: str
    base_manifest_epoch: int
    base_manifest_digest: str
    current_owner_member_id: str
    current_authority_device_id: str
    current_authority_destination: bytes
    successor_member_id: str
    successor_device_id: str
    successor_destination: bytes
    outgoing_owner_role: WorkspaceRole | None
    general_channel_id: str | None
    general_channel_head: str | None
    general_disposition: str
    nonce: bytes
    replay_key: str
    created_at: int
    expires_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceAuthorityAcceptance:
    offer: VerifiedWorkspaceAuthorityOffer
    replay_key: str
    accepted_at: int
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
    authority_chain: tuple[dict[str, str | None], ...]
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


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceAdminRequest:
    workspace_id: str
    request_id: str
    request_kind: str
    base_manifest_epoch: int
    base_manifest_digest: str
    requester_member_id: str
    requester_device_id: str
    target_member_id: str | None
    requested_role: WorkspaceRole | None
    note: str
    replay_key: str
    created_at: int
    expires_at: int
    digest: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceAdminDecision:
    workspace_id: str
    request_id: str
    request_digest: str
    request_kind: str
    base_manifest_epoch: int
    base_manifest_digest: str
    authority_member_id: str
    authority_device_id: str
    outcome: str
    result_kind: str
    result_digest: str | None
    result_document: str | None
    replay_key: str
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
        else MAX_DEVICE_LINK_BYTES
        if document_type in {"workspace_device_link_offer", "workspace_device_link"}
        else MAX_AUTHORITY_BOOTSTRAP_BYTES
        if document_type == "workspace_invite"
        else MAX_AUTHORITY_ACCEPTANCE_BYTES
        if document_type == "workspace_authority_transition"
        else MAX_HISTORY_RESPONSE_BYTES
        if document_type == "workspace_history_response"
        else MAX_ADMIN_DECISION_BYTES
        if document_type == "workspace_admin_request"
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


def workspace_document_digest(raw: str) -> str:
    """Return the canonical SHA-256 digest of one validated JSON document."""

    if not isinstance(raw, str) or not raw:
        raise ValidationError("Workspace document is invalid")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Workspace document encoding is invalid") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise ValidationError("Workspace document encoding is not canonical")
    return _digest(value)


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
    authority_transition_digest: str | None = None,
    device_transition_digest: str | None = None,
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
    device_count = 0
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
        if (
            not isinstance(item.device_cards, Sequence)
            or not 1 <= len(item.device_cards) <= MAX_DEVICES_PER_MEMBER
        ):
            raise ValidationError("Workspace member device count is invalid")
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
            device_count += 1
            if card.display_name != display_name:
                raise ValidationError("Member display name does not match its device card")
            if card.device_id == authority_device_id:
                authority_count += 1
                if role != WorkspaceRole.OWNER:
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
    if device_count > MAX_ACTIVE_DEVICES:
        raise ValidationError("Workspace manifest has too many devices")
    if owner_count != 1 or authority_count != 1:
        raise ValidationError("Workspace must contain one owner authority device")
    transition_digest = (
        None
        if authority_transition_digest is None
        else _validate_digest(authority_transition_digest, "Authority transition digest")
    )
    checked_device_transition = (
        None
        if device_transition_digest is None
        else _validate_digest(device_transition_digest, "Device transition digest")
    )
    if transition_digest is not None and checked_device_transition is not None:
        raise ValidationError("Workspace manifest transition is ambiguous")
    authority_card = next(
        card
        for item in encoded
        for card in item["devices"]
        if card["device_id"] == authority_device_id
    )
    if transition_digest is None and authority_card["destination"] != authority_destination.hex():
        raise IdentityMismatch("Workspace authority is not the owner signer")
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
        "authority_destination": authority_card["destination"],
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
    if transition_digest is not None:
        unsigned["authority_transition_digest"] = transition_digest
        unsigned["authority_signer_destination"] = authority_destination.hex()
    if checked_device_transition is not None:
        unsigned["device_transition_digest"] = checked_device_transition
    return _sign(authority_identity, unsigned)


def verify_workspace_manifest(
    raw: str,
    *,
    expected_workspace_id: str | None = None,
    expected_epoch: int | None = None,
    expected_previous_hash: str | None = None,
    expected_authority_destination: bytes | None = None,
    expected_signing_destination: bytes | None = None,
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
    transition_digest: str | None = None
    authority_signer_destination: bytes | None = None
    device_transition_digest: str | None = None
    if "authority_transition_digest" in value or "authority_signer_destination" in value:
        fields.update({"authority_transition_digest", "authority_signer_destination"})
        transition_digest = _validate_digest(
            value.get("authority_transition_digest"), "Authority transition digest"
        )
        authority_signer_destination = _validate_destination(
            value.get("authority_signer_destination"), "Authority signer destination"
        )
    if "device_transition_digest" in value:
        fields.add("device_transition_digest")
        device_transition_digest = _validate_digest(
            value.get("device_transition_digest"), "Device transition digest"
        )
    if transition_digest is not None and device_transition_digest is not None:
        raise ValidationError("Workspace manifest transition is ambiguous")
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
    signer_identity: RNS.Identity | None = None
    authority_count = 0
    device_count = 0
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
        if (
            not isinstance(raw_devices, list)
            or not 1 <= len(raw_devices) <= MAX_DEVICES_PER_MEMBER
        ):
            raise ValidationError("Workspace member device count is invalid")
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
            device_count += 1
            if card.display_name != display_name:
                raise ValidationError("Member display name does not match its device card")
            if card.device_id == authority_device_id:
                authority_count += 1
                if role != WorkspaceRole.OWNER or card.destination_hash != authority_destination:
                    raise IdentityMismatch("Workspace authority is not the owner signer")
                authority_identity = _identity_from_public_key(card.public_identity)
            if (
                authority_signer_destination is not None
                and card.destination_hash == authority_signer_destination
            ):
                signer_identity = _identity_from_public_key(card.public_identity)
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
    if device_count > MAX_ACTIVE_DEVICES:
        raise ValidationError("Workspace manifest has too many devices")
    if owner_count != 1 or authority_count != 1 or authority_identity is None:
        raise ValidationError("Workspace must contain one owner authority device")
    if transition_digest is None:
        if authority_signer_destination is not None or expected_signing_destination is not None:
            raise ValidationError("Workspace manifest signing boundary is invalid")
        signer_identity = authority_identity
    else:
        if signer_identity is None:
            raise IdentityMismatch("Workspace transition signer is not admitted")
        if (
            expected_signing_destination is not None
            and authority_signer_destination != expected_signing_destination
        ):
            raise IdentityMismatch("Workspace transition signer is unexpected")
    _verify_signature(signer_identity, value, "Workspace manifest")
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
        authority_transition_digest=transition_digest,
        authority_signer_destination=authority_signer_destination,
        device_transition_digest=device_transition_digest,
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
        manifest.authority_transition_digest is not None
        or manifest.authority_signer_destination is not None
        or manifest.device_transition_digest is not None
        or
        manifest.authority_device_id != previous.authority_device_id
        or manifest.created_at < previous.created_at
    ):
        raise ValidationError("Workspace manifest transition is not enabled")
    previous_members = {member.member_id: member for member in previous.members}
    next_members = {member.member_id: member for member in manifest.members}
    if not previous_members.keys() <= next_members.keys():
        raise ValidationError("Workspace manifest cannot remove member history")
    display_name_changes: list[str] = []
    role_changes: list[str] = []
    for member_id, old_member in previous_members.items():
        new_member = next_members[member_id]
        old_devices = tuple(device.serialized for device in old_member.devices)
        new_devices = tuple(device.serialized for device in new_member.devices)
        allowed_statuses = (
            {"active", "left", "removed"}
            if old_member.status == "active" and old_member.role != WorkspaceRole.OWNER
            else {old_member.status}
        )
        if new_member.status not in allowed_statuses:
            raise ValidationError("Workspace member transition is not enabled")
        if new_member.role != old_member.role:
            if (
                old_member.role == WorkspaceRole.OWNER
                or old_member.status != "active"
                or new_member.status != "active"
                or new_member.role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}
            ):
                raise ValidationError("Workspace role transition is not enabled")
            role_changes.append(member_id)
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
    if len(role_changes) > 1:
        raise ValidationError("Workspace role transition is invalid")
    metadata_changed = (
        manifest.name != previous.name or manifest.description != previous.description
    )
    policies_changed = (
        manifest.channel_creation != previous.channel_creation
        or manifest.posting != previous.posting
        or manifest.invitation_requests != previous.invitation_requests
    )
    retention_changed = manifest.retention_days != previous.retention_days
    checkpoints_changed = (
        manifest.removal_checkpoint_digests
        != previous.removal_checkpoint_digests
    )
    removed_member = any(
        previous_members[member_id].status == "active"
        and next_members[member_id].status == "removed"
        for member_id in status_changes
    )
    if checkpoints_changed and not removed_member:
        raise ValidationError("Workspace removal checkpoints changed without a removal")
    if manifest.status == "closed":
        if (
            added
            or status_changes
            or display_name_changes
            or role_changes
            or metadata_changed
            or policies_changed
            or retention_changed
            or checkpoints_changed
        ):
            raise ValidationError(
                "Workspace closure cannot change membership or metadata"
            )
    elif sum(
        (
            bool(added),
            bool(status_changes),
            bool(display_name_changes),
            bool(role_changes),
            metadata_changed,
            policies_changed,
            retention_changed,
        )
    ) != 1:
        # Publish exactly one semantic change per epoch so concurrent owner
        # operations have a deterministic predecessor and replay boundary.
        raise ValidationError("Workspace manifest transition is not enabled")
    return manifest


_AUTHORITY_TRANSITION_KINDS = {"same_owner_rotation", "ownership_transfer"}
_AUTHORITY_GENERAL_DISPOSITIONS = {"unchanged", "recover"}


def _authority_owner(manifest: VerifiedWorkspaceManifest) -> VerifiedWorkspaceMember:
    owners = [
        member
        for member in manifest.members
        if member.status == "active" and member.role == WorkspaceRole.OWNER
    ]
    if len(owners) != 1:
        raise ValidationError("Workspace owner state is invalid")
    return owners[0]


def create_workspace_authority_offer(
    authority_identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    transition_kind: str,
    successor_member_id: str,
    successor_device_id: str,
    general_channel: VerifiedWorkspaceChannel | None = None,
    outgoing_owner_role: WorkspaceRole | str | None = None,
    general_disposition: str | None = None,
    transition_id: str | None = None,
    nonce: bytes | None = None,
    replay_key: str | None = None,
    lifetime_seconds: int = MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS,
    now: int | None = None,
) -> str:
    """Create the current authority's inert, exact-successor offer."""

    if manifest.status != "active" or transition_kind not in _AUTHORITY_TRANSITION_KINDS:
        raise ValidationError("Workspace authority transition kind is invalid")
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace authority transition lifetime is invalid")
    owner = _authority_owner(manifest)
    authority = find_device(manifest, manifest.authority_device_id)
    successor = find_device(
        manifest, _validate_uuid(successor_device_id, "Successor device ID")
    )
    successor_member_id = _validate_uuid(successor_member_id, "Successor member ID")
    if (
        authority is None
        or authority[0].member_id != owner.member_id
        or _destination_for(authority_identity) != authority[1].destination_hash
        or successor is None
        or successor[0].member_id != successor_member_id
        or successor[0].status != "active"
        or successor[1].device_id == authority[1].device_id
    ):
        raise IdentityMismatch("Workspace authority transition participant is invalid")
    role: WorkspaceRole | None
    channel_id: str | None
    channel_head: str | None
    if transition_kind == "same_owner_rotation":
        if successor_member_id != owner.member_id:
            raise ValidationError("Same-owner rotation requires another owner device")
        if outgoing_owner_role is not None or general_channel is not None:
            raise ValidationError("Same-owner rotation cannot change ownership or channels")
        role = None
        channel_id = None
        channel_head = None
        disposition = general_disposition or "unchanged"
        if disposition != "unchanged":
            raise ValidationError("Same-owner rotation must leave #general unchanged")
    else:
        if successor_member_id == owner.member_id:
            raise ValidationError("Ownership transfer requires a nonowner successor")
        role = _coerce_role(outgoing_owner_role)
        if role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
            raise ValidationError("Outgoing owner role is invalid")
        if (
            general_channel is None
            or general_channel.workspace_id != manifest.workspace_id
            or general_channel.visibility != "public"
            or channel_name_key(general_channel.name) != "general"
            or general_channel.archived
        ):
            raise ValidationError("Ownership transfer requires the exact active #general head")
        channel_id = general_channel.channel_id
        channel_head = general_channel.digest
        disposition = general_disposition or "recover"
        if disposition != "recover":
            raise ValidationError("Ownership transfer must explicitly recover #general")
    checked_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(checked_nonce, bytes) or len(checked_nonce) != NONCE_BYTES:
        raise ValidationError("Workspace authority transition nonce is invalid")
    current = int(time.time()) if now is None else int(now)
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_authority_transition",
        "phase": "offer",
        "workspace_id": manifest.workspace_id,
        "transition_id": _validate_uuid(transition_id or str(uuid.uuid4()), "Transition ID"),
        "transition_kind": transition_kind,
        "base_manifest_epoch": manifest.epoch,
        "base_manifest_digest": manifest.digest,
        "current_owner_member_id": owner.member_id,
        "current_authority_device_id": authority[1].device_id,
        "current_authority_destination": authority[1].destination_hash.hex(),
        "successor_member_id": successor_member_id,
        "successor_device_id": successor[1].device_id,
        "successor_destination": successor[1].destination_hash.hex(),
        "outgoing_owner_role": None if role is None else role.value,
        "general_channel_id": channel_id,
        "general_channel_head": channel_head,
        "general_disposition": disposition,
        "nonce": _b64encode(checked_nonce),
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "created_at": current,
        "expires_at": current + lifetime_seconds,
    }
    return _sign(authority_identity, unsigned, maximum=MAX_AUTHORITY_OFFER_BYTES)


def verify_workspace_authority_offer(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    general_channel: VerifiedWorkspaceChannel | None = None,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceAuthorityOffer:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_AUTHORITY_OFFER_BYTES:
        raise ValidationError("Workspace authority offer is too large")
    value = _load_document(raw, "workspace_authority_transition")
    _require_fields(
        value,
        {
            "v", "type", "phase", "workspace_id", "transition_id",
            "transition_kind", "base_manifest_epoch", "base_manifest_digest",
            "current_owner_member_id", "current_authority_device_id",
            "current_authority_destination", "successor_member_id",
            "successor_device_id", "successor_destination", "outgoing_owner_role",
            "general_channel_id", "general_channel_head", "general_disposition",
            "nonce", "replay_key", "created_at", "expires_at", "signature",
        },
    )
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or value["phase"] != "offer"
        or value["workspace_id"] != manifest.workspace_id
        or value["base_manifest_epoch"] != manifest.epoch
        or value["base_manifest_digest"] != manifest.digest
        or manifest.status != "active"
    ):
        raise ValidationError("Workspace authority offer base state is stale")
    kind = value["transition_kind"]
    if kind not in _AUTHORITY_TRANSITION_KINDS:
        raise ValidationError("Workspace authority transition kind is invalid")
    owner = _authority_owner(manifest)
    owner_id = _validate_uuid(value["current_owner_member_id"], "Current owner member ID")
    authority_device_id = _validate_uuid(
        value["current_authority_device_id"], "Current authority device ID"
    )
    authority_destination = _validate_destination(
        value["current_authority_destination"], "Current authority destination"
    )
    successor_member_id = _validate_uuid(value["successor_member_id"], "Successor member ID")
    successor_device_id = _validate_uuid(value["successor_device_id"], "Successor device ID")
    successor_destination = _validate_destination(
        value["successor_destination"], "Successor destination"
    )
    authority = find_device(manifest, authority_device_id)
    successor = find_device(manifest, successor_device_id)
    if (
        owner_id != owner.member_id
        or authority_device_id != manifest.authority_device_id
        or authority is None
        or authority[0].member_id != owner_id
        or authority[1].destination_hash != authority_destination
        or successor is None
        or successor[0].member_id != successor_member_id
        or successor[0].status != "active"
        or successor[1].destination_hash != successor_destination
        or successor_device_id == authority_device_id
    ):
        raise IdentityMismatch("Workspace authority offer participant is invalid")
    _verify_signature(
        _identity_from_public_key(authority[1].public_identity),
        value,
        "Workspace authority offer",
    )
    role: WorkspaceRole | None = None
    channel_id: str | None = None
    channel_head: str | None = None
    disposition = value["general_disposition"]
    if kind == "same_owner_rotation":
        if (
            successor_member_id != owner_id
            or value["outgoing_owner_role"] is not None
            or value["general_channel_id"] is not None
            or value["general_channel_head"] is not None
            or disposition != "unchanged"
        ):
            raise ValidationError("Same-owner authority rotation is invalid")
    else:
        if successor_member_id == owner_id:
            raise ValidationError("Ownership transfer successor is invalid")
        role = _coerce_role(value["outgoing_owner_role"])
        if role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
            raise ValidationError("Outgoing owner role is invalid")
        channel_id = _validate_uuid(value["general_channel_id"], "#general channel ID")
        channel_head = _validate_digest(value["general_channel_head"], "#general head")
        if disposition != "recover":
            raise ValidationError("Ownership transfer #general disposition is invalid")
        if general_channel is not None and (
            general_channel.workspace_id != manifest.workspace_id
            or general_channel.channel_id != channel_id
            or general_channel.digest != channel_head
            or general_channel.visibility != "public"
            or channel_name_key(general_channel.name) != "general"
            or general_channel.archived
        ):
            raise ValidationError("Ownership transfer #general head is stale")
    current = int(time.time()) if now is None else int(now)
    created = _validate_timestamp(value["created_at"], now=current)
    expires = value["expires_at"]
    if (
        isinstance(expires, bool)
        or not isinstance(expires, int)
        or expires <= created
        or expires > created + MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS
        or (not allow_expired and expires < current)
    ):
        raise InvitationExpired("Workspace authority offer has expired")
    return VerifiedWorkspaceAuthorityOffer(
        workspace_id=manifest.workspace_id,
        transition_id=_validate_uuid(value["transition_id"], "Transition ID"),
        transition_kind=kind,
        base_manifest_epoch=manifest.epoch,
        base_manifest_digest=manifest.digest,
        current_owner_member_id=owner_id,
        current_authority_device_id=authority_device_id,
        current_authority_destination=authority_destination,
        successor_member_id=successor_member_id,
        successor_device_id=successor_device_id,
        successor_destination=successor_destination,
        outgoing_owner_role=role,
        general_channel_id=channel_id,
        general_channel_head=channel_head,
        general_disposition=disposition,
        nonce=_b64decode(value["nonce"], "Authority transition nonce", expected_length=NONCE_BYTES),
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        created_at=created,
        expires_at=expires,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_authority_acceptance(
    successor_identity: RNS.Identity,
    *,
    offer: VerifiedWorkspaceAuthorityOffer,
    replay_key: str | None = None,
    now: int | None = None,
) -> str:
    if _destination_for(successor_identity) != offer.successor_destination:
        raise IdentityMismatch("Only the named successor can accept authority")
    accepted_at = int(time.time()) if now is None else int(now)
    if accepted_at < offer.created_at or accepted_at > offer.expires_at:
        raise InvitationExpired("Workspace authority offer has expired")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_authority_transition",
        "phase": "acceptance",
        "workspace_id": offer.workspace_id,
        "transition_id": offer.transition_id,
        "transition_kind": offer.transition_kind,
        "base_manifest_epoch": offer.base_manifest_epoch,
        "base_manifest_digest": offer.base_manifest_digest,
        "offer_digest": offer.digest,
        "offer": json.loads(offer.serialized),
        "current_owner_member_id": offer.current_owner_member_id,
        "current_authority_device_id": offer.current_authority_device_id,
        "successor_member_id": offer.successor_member_id,
        "successor_device_id": offer.successor_device_id,
        "general_channel_id": offer.general_channel_id,
        "general_channel_head": offer.general_channel_head,
        "general_disposition": offer.general_disposition,
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "accepted_at": accepted_at,
    }
    return _sign(successor_identity, unsigned, maximum=MAX_AUTHORITY_ACCEPTANCE_BYTES)


def verify_workspace_authority_acceptance(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    general_channel: VerifiedWorkspaceChannel | None = None,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceAuthorityAcceptance:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_AUTHORITY_ACCEPTANCE_BYTES:
        raise ValidationError("Workspace authority acceptance is too large")
    value = _load_document(raw, "workspace_authority_transition")
    _require_fields(
        value,
        {
            "v", "type", "phase", "workspace_id", "transition_id",
            "transition_kind", "base_manifest_epoch", "base_manifest_digest",
            "offer_digest", "offer", "current_owner_member_id",
            "current_authority_device_id", "successor_member_id",
            "successor_device_id", "general_channel_id", "general_channel_head",
            "general_disposition", "replay_key", "accepted_at", "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["phase"] != "acceptance" or not isinstance(value["offer"], dict):
        raise ValidationError("Workspace authority acceptance is invalid")
    offer = verify_workspace_authority_offer(
        _canonical(value["offer"]),
        manifest=manifest,
        general_channel=general_channel,
        now=now,
        allow_expired=allow_expired,
    )
    repeated = {
        "workspace_id": offer.workspace_id,
        "transition_id": offer.transition_id,
        "transition_kind": offer.transition_kind,
        "base_manifest_epoch": offer.base_manifest_epoch,
        "base_manifest_digest": offer.base_manifest_digest,
        "offer_digest": offer.digest,
        "current_owner_member_id": offer.current_owner_member_id,
        "current_authority_device_id": offer.current_authority_device_id,
        "successor_member_id": offer.successor_member_id,
        "successor_device_id": offer.successor_device_id,
        "general_channel_id": offer.general_channel_id,
        "general_channel_head": offer.general_channel_head,
        "general_disposition": offer.general_disposition,
    }
    if any(value[key] != expected for key, expected in repeated.items()):
        raise ValidationError("Workspace authority acceptance substituted its offer")
    successor = find_device(manifest, offer.successor_device_id)
    if successor is None or successor[0].member_id != offer.successor_member_id:
        raise IdentityMismatch("Workspace authority successor is unavailable")
    _verify_signature(
        _identity_from_public_key(successor[1].public_identity),
        value,
        "Workspace authority acceptance",
    )
    current = int(time.time()) if now is None else int(now)
    accepted = _validate_timestamp(value["accepted_at"], now=current)
    if accepted < offer.created_at or accepted > offer.expires_at:
        raise InvitationExpired("Workspace authority acceptance is outside the offer lifetime")
    return VerifiedWorkspaceAuthorityAcceptance(
        offer=offer,
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        accepted_at=accepted,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def _authority_transition_member_inputs(
    previous: VerifiedWorkspaceManifest,
    offer: VerifiedWorkspaceAuthorityOffer,
) -> list[WorkspaceManifestMemberInput]:
    result: list[WorkspaceManifestMemberInput] = []
    for member in previous.members:
        role: WorkspaceRole | str = member.role
        if offer.transition_kind == "ownership_transfer":
            if member.member_id == offer.current_owner_member_id:
                role = offer.outgoing_owner_role or WorkspaceRole.MEMBER
            elif member.member_id == offer.successor_member_id:
                role = WorkspaceRole.OWNER
        result.append(
            WorkspaceManifestMemberInput(
                member_id=member.member_id,
                display_name=member.display_name,
                role=role,
                status=member.status,
                device_cards=[device.serialized for device in member.devices],
            )
        )
    return result


def create_workspace_authority_manifest(
    authority_identity: RNS.Identity,
    *,
    previous: VerifiedWorkspaceManifest,
    acceptance: VerifiedWorkspaceAuthorityAcceptance,
    now: int | None = None,
) -> str:
    offer = acceptance.offer
    if offer.base_manifest_digest != previous.digest or offer.base_manifest_epoch != previous.epoch:
        raise ValidationError("Workspace authority transition is stale")
    if _destination_for(authority_identity) != previous.authority_destination:
        raise IdentityMismatch("Only the current authority can finalize the transition")
    created = int(time.time()) if now is None else int(now)
    if created < acceptance.accepted_at or created > offer.expires_at:
        raise InvitationExpired("Workspace authority transition cannot be finalized")
    return create_workspace_manifest(
        authority_identity,
        workspace_id=previous.workspace_id,
        epoch=previous.epoch + 1,
        previous_manifest_hash=previous.digest,
        name=previous.name,
        description=previous.description,
        authority_device_id=offer.successor_device_id,
        members=_authority_transition_member_inputs(previous, offer),
        status=previous.status,
        retention_days=previous.retention_days,
        channel_creation=previous.channel_creation,
        posting=previous.posting,
        invitation_requests=previous.invitation_requests,
        removal_checkpoint_digests=previous.removal_checkpoint_digests,
        authority_transition_digest=acceptance.digest,
        now=created,
    )


def verify_workspace_authority_manifest_transition(
    raw: str,
    previous: VerifiedWorkspaceManifest,
    *,
    acceptance: str | VerifiedWorkspaceAuthorityAcceptance,
    general_channel: VerifiedWorkspaceChannel | None = None,
    general_result: str | VerifiedWorkspaceChannel | None = None,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceManifest:
    checked_acceptance = (
        acceptance
        if isinstance(acceptance, VerifiedWorkspaceAuthorityAcceptance)
        else verify_workspace_authority_acceptance(
            acceptance,
            manifest=previous,
            general_channel=general_channel,
            now=now,
            allow_expired=allow_expired,
        )
    )
    offer = checked_acceptance.offer
    if offer.base_manifest_digest != previous.digest or offer.base_manifest_epoch != previous.epoch:
        raise ValidationError("Workspace authority transition is stale")
    manifest = verify_workspace_manifest(
        raw,
        expected_workspace_id=previous.workspace_id,
        expected_epoch=previous.epoch + 1,
        expected_previous_hash=previous.digest,
        expected_signing_destination=previous.authority_destination,
        now=now,
    )
    if (
        manifest.authority_transition_digest != checked_acceptance.digest
        or manifest.authority_signer_destination != previous.authority_destination
        or manifest.device_transition_digest is not None
        or manifest.authority_device_id != offer.successor_device_id
        or manifest.authority_destination != offer.successor_destination
        or manifest.created_at < checked_acceptance.accepted_at
        or manifest.created_at > offer.expires_at
        or manifest.status != previous.status
        or manifest.name != previous.name
        or manifest.description != previous.description
        or manifest.retention_days != previous.retention_days
        or manifest.channel_creation != previous.channel_creation
        or manifest.posting != previous.posting
        or manifest.invitation_requests != previous.invitation_requests
        or manifest.removal_checkpoint_digests != previous.removal_checkpoint_digests
    ):
        raise ValidationError("Workspace authority manifest is not bound to its acceptance")
    before = {member.member_id: member for member in previous.members}
    after = {member.member_id: member for member in manifest.members}
    if before.keys() != after.keys():
        raise ValidationError("Workspace authority transition changed membership")
    for member_id, old in before.items():
        new = after[member_id]
        if (
            old.status != new.status
            or old.display_name != new.display_name
            or tuple(card.serialized for card in old.devices)
            != tuple(card.serialized for card in new.devices)
        ):
            raise ValidationError("Workspace authority transition changed a device or member")
        expected_role = old.role
        if offer.transition_kind == "ownership_transfer":
            if member_id == offer.current_owner_member_id:
                expected_role = offer.outgoing_owner_role or WorkspaceRole.MEMBER
            elif member_id == offer.successor_member_id:
                expected_role = WorkspaceRole.OWNER
        if new.role != expected_role:
            raise ValidationError("Workspace authority transition changed the wrong role")
    if offer.transition_kind == "same_owner_rotation":
        if general_result is not None:
            raise ValidationError("Same-owner rotation changed #general")
    else:
        if general_channel is None or general_result is None:
            raise ValidationError("Ownership transfer requires atomic #general recovery")
        recovered = (
            general_result
            if isinstance(general_result, VerifiedWorkspaceChannel)
            else verify_workspace_channel_recovery(
                general_result,
                channel=general_channel,
                manifest=previous,
                now=now,
            )
        )
        if (
            recovered.previous_hash != offer.general_channel_head
            or recovered.channel_id != offer.general_channel_id
            or recovered.manager_member_id != offer.successor_member_id
            or recovered.manager_device_id != offer.successor_device_id
        ):
            raise ValidationError("Ownership transfer #general recovery is invalid")
    return manifest


def _encoded_authority_chain(
    authority_chain: Sequence[dict[str, str | None]],
) -> list[dict[str, Any]]:
    if not isinstance(authority_chain, Sequence) or isinstance(authority_chain, (str, bytes)):
        raise ValidationError("Workspace authority chain is invalid")
    if len(authority_chain) > MAX_AUTHORITY_TRANSITIONS:
        raise ValidationError("Workspace authority chain limit is reached")
    encoded: list[dict[str, Any]] = []
    expected = {"base_manifest", "offer", "acceptance", "final_manifest", "general_result"}
    for step in authority_chain:
        if not isinstance(step, dict) or set(step) != expected:
            raise ValidationError("Workspace authority certificate step is invalid")
        item: dict[str, Any] = {}
        for key in ("base_manifest", "offer", "acceptance", "final_manifest"):
            raw = step[key]
            if not isinstance(raw, str):
                raise ValidationError("Workspace authority certificate document is invalid")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValidationError("Workspace authority certificate document is invalid") from exc
            if not isinstance(parsed, dict) or raw != _canonical(parsed):
                raise ValidationError("Workspace authority certificate document is not canonical")
            item[key] = parsed
        general = step["general_result"]
        if general is None:
            item["general_result"] = None
        else:
            if not isinstance(general, str):
                raise ValidationError("Workspace authority #general result is invalid")
            try:
                parsed_general = json.loads(general)
            except json.JSONDecodeError as exc:
                raise ValidationError("Workspace authority #general result is invalid") from exc
            if not isinstance(parsed_general, dict) or general != _canonical(parsed_general):
                raise ValidationError("Workspace authority #general result is not canonical")
            item["general_result"] = parsed_general
        encoded.append(item)
    return encoded


def verify_workspace_authority_chain(
    genesis: VerifiedWorkspaceGenesis,
    authority_chain: Sequence[dict[str, Any]],
    offered_manifest: str,
    *,
    now: int | None = None,
) -> tuple[VerifiedWorkspaceManifest, tuple[dict[str, str | None], ...]]:
    """Verify a bounded genesis-to-current authority certificate chain."""

    if not isinstance(authority_chain, Sequence) or isinstance(authority_chain, (str, bytes)):
        raise ValidationError("Workspace authority chain is invalid")
    if len(authority_chain) > MAX_AUTHORITY_TRANSITIONS:
        raise ValidationError("Workspace authority chain limit is reached")
    current_authority = genesis.owner_device.destination_hash
    current_manifest: VerifiedWorkspaceManifest | None = None
    decoded: list[dict[str, str | None]] = []
    seen_transitions: set[str] = set()
    seen_results: set[str] = set()
    expected = {"base_manifest", "offer", "acceptance", "final_manifest", "general_result"}
    for step in authority_chain:
        if not isinstance(step, dict) or set(step) != expected:
            raise ValidationError("Workspace authority certificate step is invalid")
        if any(not isinstance(step[key], dict) for key in ("base_manifest", "offer", "acceptance", "final_manifest")):
            raise ValidationError("Workspace authority certificate document is invalid")
        base_raw = _canonical(step["base_manifest"])
        base = verify_workspace_manifest(
            base_raw,
            expected_workspace_id=genesis.workspace_id,
            expected_authority_destination=current_authority,
            now=now,
        )
        if current_manifest is not None:
            if base.digest == current_manifest.digest:
                base = current_manifest
            elif (
                base.epoch <= current_manifest.epoch
                or base.created_at < current_manifest.created_at
                or base.authority_device_id != current_manifest.authority_device_id
            ):
                raise ValidationError("Workspace authority chain is reordered or stale")
        else:
            if base.authority_transition_digest is not None:
                raise ValidationError("Authority certificate must start at an ordinary checkpoint")
            if base.created_at < genesis.created_at:
                raise ValidationError("Workspace authority chain predates genesis")
        offer_raw = _canonical(step["offer"])
        offer = verify_workspace_authority_offer(
            offer_raw, manifest=base, now=now, allow_expired=True
        )
        if offer.transition_id in seen_transitions:
            raise ValidationError("Workspace authority chain duplicates a transition")
        acceptance_raw = _canonical(step["acceptance"])
        acceptance = verify_workspace_authority_acceptance(
            acceptance_raw, manifest=base, now=now, allow_expired=True
        )
        general_raw: str | None = None
        general_before: VerifiedWorkspaceChannel | None = None
        general_result: VerifiedWorkspaceChannel | None = None
        if offer.transition_kind == "ownership_transfer":
            raw_general = step["general_result"]
            if not isinstance(raw_general, dict):
                raise ValidationError("Ownership certificate is missing #general recovery")
            general_raw = _canonical(raw_general)
            # The canonical recovery verifier also needs the exact predecessor
            # channel body. It is intentionally not reconstructed from names or
            # local presentation state, so invitation steps carry a recovery
            # whose predecessor fields are checked below and whose authority
            # signature is checked directly here.
            recovery_value = _load_document(general_raw, "workspace_channel_recovery")
            _require_fields(
                recovery_value,
                {
                    "v", "type", "workspace_id", "channel_id", "channel_head",
                    "manifest_digest", "manager_member_id", "manager_device_id",
                    "created_at", "signature",
                },
            )
            authority = find_device(base, base.authority_device_id)
            if authority is None:
                raise IdentityMismatch("Authority certificate signer is unavailable")
            _verify_signature(
                _identity_from_public_key(authority[1].public_identity),
                recovery_value,
                "Workspace channel recovery",
            )
            if (
                recovery_value["workspace_id"] != base.workspace_id
                or recovery_value["manifest_digest"] != base.digest
                or recovery_value["channel_id"] != offer.general_channel_id
                or recovery_value["channel_head"] != offer.general_channel_head
                or recovery_value["manager_member_id"] != offer.successor_member_id
                or recovery_value["manager_device_id"] != offer.successor_device_id
            ):
                raise ValidationError("Authority certificate #general recovery is substituted")
            general_before = VerifiedWorkspaceChannel(
                workspace_id=base.workspace_id,
                channel_id=offer.general_channel_id or "",
                version=1,
                previous_hash=None,
                manifest_digest=base.digest,
                name="general",
                topic="",
                visibility="public",
                manager_member_id=offer.current_owner_member_id,
                manager_device_id=offer.current_authority_device_id,
                archived=False,
                created_at=0,
                digest=offer.general_channel_head or "",
                serialized="",
            )
            general_result = verify_workspace_channel_recovery(
                general_raw,
                channel=general_before,
                manifest=base,
                now=now,
            )
        elif step["general_result"] is not None:
            raise ValidationError("Same-owner certificate changed #general")
        final_raw = _canonical(step["final_manifest"])
        # Full #general predecessor validation is performed by members that
        # already hold the channel head. A fresh joiner verifies the exact
        # signed head binding above without learning any private channel.
        final = verify_workspace_authority_manifest_transition(
            final_raw,
            base,
            acceptance=acceptance,
            general_channel=general_before,
            general_result=general_result,
            now=now,
            allow_expired=True,
        )
        if final.digest in seen_results:
            raise ValidationError("Workspace authority chain duplicates a result")
        seen_transitions.add(offer.transition_id)
        seen_results.add(final.digest)
        current_authority = final.authority_destination
        current_manifest = final
        decoded.append(
            {
                "base_manifest": base_raw,
                "offer": offer_raw,
                "acceptance": acceptance_raw,
                "final_manifest": final_raw,
                "general_result": general_raw,
            }
        )
    if current_manifest is None:
        offered = _verify_workspace_manifest_checkpoint(offered_manifest, genesis, now=now)
    else:
        offered = verify_workspace_manifest(
            offered_manifest,
            expected_workspace_id=genesis.workspace_id,
            expected_authority_destination=current_authority,
            now=now,
        )
        if offered.authority_transition_digest is not None:
            if offered.digest != current_manifest.digest:
                raise ValidationError("Offered manifest omits an authority certificate")
        elif offered.epoch < current_manifest.epoch or offered.created_at < current_manifest.created_at:
            raise ValidationError("Offered manifest predates the authority chain")
    return offered, tuple(decoded)


def create_workspace_invitation(
    authority_identity: RNS.Identity,
    *,
    genesis: str,
    manifest: str,
    now: int | None = None,
    lifetime_seconds: int = DEFAULT_INVITATION_LIFETIME_SECONDS,
    nonce: bytes | None = None,
    authority_chain: Sequence[dict[str, str | None]] = (),
) -> str:
    current = int(time.time()) if now is None else int(now)
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_INVITATION_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace invitation lifetime is invalid")
    checked_genesis = verify_workspace_genesis(genesis, now=current)
    encoded_chain = _encoded_authority_chain(authority_chain)
    checked_manifest, _ = verify_workspace_authority_chain(
        checked_genesis, encoded_chain, manifest, now=current
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
        "authority_chain": encoded_chain,
        "nonce": _b64encode(invitation_nonce),
        "created_at": current,
        "expires_at": current + lifetime_seconds,
        "use_limit": 1,
    }
    return _sign(authority_identity, unsigned, maximum=MAX_AUTHORITY_BOOTSTRAP_BYTES)


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
    if (
        not isinstance(value["authority_chain"], list)
        or len(value["authority_chain"]) > MAX_AUTHORITY_TRANSITIONS
    ):
        raise ValidationError("Workspace authority chain is invalid")
    if not isinstance(value["genesis"], dict) or not isinstance(
        value["offered_manifest"], dict
    ):
        raise ValidationError("Workspace invitation controls are invalid")
    current = int(time.time()) if now is None else int(now)
    genesis = verify_workspace_genesis(_canonical(value["genesis"]), now=current)
    manifest, authority_chain = verify_workspace_authority_chain(
        genesis,
        value["authority_chain"],
        _canonical(value["offered_manifest"]),
        now=current,
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
        authority_chain=authority_chain,
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
    if not value or len(value.encode("utf-8")) > MAX_AUTHORITY_BOOTSTRAP_BYTES * 2:
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


def _validate_workspace_device_bootstrap_manifests(
    genesis: VerifiedWorkspaceGenesis,
    offered_manifest: VerifiedWorkspaceManifest,
    manifests: Sequence[VerifiedWorkspaceManifest],
) -> None:
    """Validate the bounded historical checkpoints endorsed by final admission.

    These checkpoints do not authorize the fresh device by themselves.  They
    become usable only after the current authority signs the device-transition
    manifest that binds the exact offer containing them.
    """

    previous_epoch = 0
    seen_digests: set[str] = set()
    initial: VerifiedWorkspaceManifest | None = None
    for manifest in manifests:
        if (
            manifest.workspace_id != genesis.workspace_id
            or manifest.epoch <= previous_epoch
            or manifest.epoch >= offered_manifest.epoch
            or manifest.digest in seen_digests
        ):
            raise ValidationError("Workspace device bootstrap manifest set is invalid")
        previous_epoch = manifest.epoch
        seen_digests.add(manifest.digest)
        if manifest.epoch == 1:
            initial = manifest
    if offered_manifest.epoch == 1:
        if manifests:
            raise ValidationError("Workspace device bootstrap manifest set is invalid")
        return
    if initial is None:
        raise ValidationError("Workspace device bootstrap is missing the initial manifest")
    verify_workspace_manifest_transition(initial.serialized, genesis)


def create_workspace_device_link_offer(
    sponsor_identity: RNS.Identity,
    *,
    genesis: str,
    manifest: str,
    member_id: str,
    sponsor_device_id: str,
    authority_chain: Sequence[dict[str, str | None]] = (),
    bootstrap_manifests: Sequence[str] = (),
    now: int | None = None,
    lifetime_seconds: int = MAX_DEVICE_LINK_LIFETIME_SECONDS,
    link_id: str | None = None,
    nonce: bytes | None = None,
    replay_key: str | None = None,
) -> str:
    """Create a short-lived sponsor proof for one fresh desktop identity."""

    current = int(time.time()) if now is None else int(now)
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_DEVICE_LINK_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace device-link lifetime is invalid")
    checked_genesis = verify_workspace_genesis(genesis, now=current)
    encoded_chain = _encoded_authority_chain(authority_chain)
    checked_manifest, _ = verify_workspace_authority_chain(
        checked_genesis, encoded_chain, manifest, now=current
    )
    if not isinstance(bootstrap_manifests, Sequence) or isinstance(
        bootstrap_manifests, (str, bytes)
    ):
        raise ValidationError("Workspace device bootstrap manifests are invalid")
    if len(bootstrap_manifests) > MAX_DEVICE_BOOTSTRAP_MANIFESTS:
        raise ValidationError("Workspace device bootstrap manifest limit is reached")
    encoded_bootstrap: list[dict[str, Any]] = []
    checked_bootstrap: list[VerifiedWorkspaceManifest] = []
    for raw_bootstrap in bootstrap_manifests:
        if not isinstance(raw_bootstrap, str):
            raise ValidationError("Workspace device bootstrap manifest is invalid")
        checked = verify_workspace_manifest(
            raw_bootstrap,
            expected_workspace_id=checked_genesis.workspace_id,
            now=current,
        )
        encoded_bootstrap.append(json.loads(checked.serialized))
        checked_bootstrap.append(checked)
    _validate_workspace_device_bootstrap_manifests(
        checked_genesis, checked_manifest, checked_bootstrap
    )
    checked_member_id = _validate_uuid(member_id, "Member ID")
    checked_sponsor_id = _validate_uuid(sponsor_device_id, "Sponsor device ID")
    member = find_member(checked_manifest, checked_member_id)
    sponsor = find_device(checked_manifest, checked_sponsor_id)
    if (
        checked_manifest.status != "active"
        or member is None
        or member.status != "active"
        or sponsor is None
        or sponsor[0].member_id != checked_member_id
        or sponsor[1].destination_hash != _destination_for(sponsor_identity)
    ):
        raise IdentityMismatch("Workspace device-link sponsor is not an active member device")
    if len(member.devices) >= MAX_LINKED_DEVICES_PER_MEMBER:
        raise ValidationError("Workspace member already has three linked devices")
    link_nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if not isinstance(link_nonce, bytes) or len(link_nonce) != NONCE_BYTES:
        raise ValidationError("Workspace device-link nonce is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_device_link_offer",
        "workspace_id": checked_manifest.workspace_id,
        "link_id": _validate_uuid(link_id or str(uuid.uuid4()), "Device-link ID"),
        "base_manifest_epoch": checked_manifest.epoch,
        "base_manifest_digest": checked_manifest.digest,
        "member_id": checked_member_id,
        "sponsor_device_id": checked_sponsor_id,
        "sponsor_destination": sponsor[1].destination_hash.hex(),
        "genesis": json.loads(checked_genesis.serialized),
        "offered_manifest": json.loads(checked_manifest.serialized),
        "authority_chain": encoded_chain,
        "bootstrap_manifests": encoded_bootstrap,
        "nonce": _b64encode(link_nonce),
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "created_at": current,
        "expires_at": current + lifetime_seconds,
        "use_limit": 1,
    }
    return _sign(sponsor_identity, unsigned, maximum=MAX_DEVICE_LINK_BYTES)


def verify_workspace_device_link_offer(
    raw: str,
    *,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceDeviceLinkOffer:
    serialized = extract_workspace_device_link(raw)
    value = _load_document(serialized, "workspace_device_link_offer")
    _require_fields(
        value,
        {
            "v", "type", "workspace_id", "link_id", "base_manifest_epoch",
            "base_manifest_digest", "member_id", "sponsor_device_id",
            "sponsor_destination", "genesis", "offered_manifest",
            "authority_chain", "bootstrap_manifests", "nonce", "replay_key", "created_at",
            "expires_at", "use_limit", "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or value["use_limit"] != 1:
        raise ValidationError("Workspace device-link version or use limit is invalid")
    if not isinstance(value["genesis"], dict) or not isinstance(
        value["offered_manifest"], dict
    ) or not isinstance(value["authority_chain"], list) or not isinstance(
        value["bootstrap_manifests"], list
    ):
        raise ValidationError("Workspace device-link bootstrap is invalid")
    current = int(time.time()) if now is None else int(now)
    genesis = verify_workspace_genesis(_canonical(value["genesis"]), now=current)
    manifest, authority_chain = verify_workspace_authority_chain(
        genesis,
        value["authority_chain"],
        _canonical(value["offered_manifest"]),
        now=current,
    )
    if len(value["bootstrap_manifests"]) > MAX_DEVICE_BOOTSTRAP_MANIFESTS:
        raise ValidationError("Workspace device bootstrap manifest limit is reached")
    bootstrap_manifests: list[VerifiedWorkspaceManifest] = []
    for item in value["bootstrap_manifests"]:
        if not isinstance(item, dict):
            raise ValidationError("Workspace device bootstrap manifest is invalid")
        bootstrap_manifests.append(
            verify_workspace_manifest(
                _canonical(item),
                expected_workspace_id=genesis.workspace_id,
                now=current,
            )
        )
    _validate_workspace_device_bootstrap_manifests(
        genesis, manifest, bootstrap_manifests
    )
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    link_id = _validate_uuid(value["link_id"], "Device-link ID")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    sponsor_device_id = _validate_uuid(value["sponsor_device_id"], "Sponsor device ID")
    base_digest = _validate_digest(value["base_manifest_digest"], "Base manifest digest")
    base_epoch = value["base_manifest_epoch"]
    if (
        workspace_id != genesis.workspace_id
        or workspace_id != manifest.workspace_id
        or isinstance(base_epoch, bool)
        or not isinstance(base_epoch, int)
        or base_epoch != manifest.epoch
        or base_digest != manifest.digest
    ):
        raise ValidationError("Workspace device-link bootstrap does not match")
    member = find_member(manifest, member_id)
    sponsor = find_device(manifest, sponsor_device_id)
    sponsor_destination = _validate_destination(
        value["sponsor_destination"], "Sponsor destination"
    )
    if (
        manifest.status != "active"
        or member is None
        or member.status != "active"
        or sponsor is None
        or sponsor[0].member_id != member_id
        or sponsor[1].destination_hash != sponsor_destination
        or len(member.devices) >= MAX_LINKED_DEVICES_PER_MEMBER
    ):
        raise IdentityMismatch("Workspace device-link sponsor is not an active member device")
    _verify_signature(
        _identity_from_public_key(sponsor[1].public_identity),
        value,
        "Workspace device-link offer",
    )
    created_at = _validate_timestamp(value["created_at"], now=current)
    expires_at = value["expires_at"]
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at < created_at
        or expires_at - created_at > MAX_DEVICE_LINK_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace device-link dates are invalid")
    if expires_at < current and not allow_expired:
        raise InvitationExpired("Workspace device link has expired")
    return VerifiedWorkspaceDeviceLinkOffer(
        workspace_id=workspace_id,
        link_id=link_id,
        base_manifest_epoch=base_epoch,
        base_manifest_digest=base_digest,
        member_id=member_id,
        sponsor_device_id=sponsor_device_id,
        sponsor_destination=sponsor_destination,
        nonce=_b64decode(value["nonce"], "Device-link nonce", expected_length=NONCE_BYTES),
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        created_at=created_at,
        expires_at=expires_at,
        genesis=genesis,
        offered_manifest=manifest,
        authority_chain=authority_chain,
        bootstrap_manifests=tuple(bootstrap_manifests),
        digest=_digest(value),
        serialized=_canonical(value),
    )


def workspace_device_link_formats(raw: str, *, now: int | None = None) -> dict[str, Any]:
    offer = verify_workspace_device_link_offer(raw, now=now)
    token = _b64encode(offer.serialized.encode("utf-8"))
    return {
        "link": f"meshchat://workspace-device/{token}",
        "text": f"MESHWORKSPACEDEVICE1:{token}",
        "value": offer.serialized,
        "expires_at": offer.expires_at,
    }


def extract_workspace_device_link(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValidationError("Workspace device link is invalid")
    value = raw.translate(_INVISIBLE).strip()
    if not value or len(value.encode("utf-8")) > MAX_DEVICE_LINK_BYTES * 2:
        raise ValidationError("Workspace device link is empty or too large")
    lower = value.lower()
    if lower.startswith("meshchat://workspace-device/"):
        compact = "".join(value.split())
        parsed = urlsplit(compact)
        if (
            parsed.scheme != "meshchat"
            or parsed.netloc != "workspace-device"
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
        ):
            raise ValidationError("Workspace device-link URL is invalid")
        return _b64decode(parsed.path[1:], "Workspace device-link token").decode("utf-8")
    if lower.startswith("meshworkspacedevice1:"):
        token = "".join(value.split())[len("MESHWORKSPACEDEVICE1:") :]
        return _b64decode(token, "Workspace device-link token").decode("utf-8")
    return value


def create_workspace_device_link_acceptance(
    new_identity: RNS.Identity,
    offer: str | VerifiedWorkspaceDeviceLinkOffer,
    *,
    device_id: str | None = None,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
    replay_key: str | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked = (
        offer
        if isinstance(offer, VerifiedWorkspaceDeviceLinkOffer)
        else verify_workspace_device_link_offer(offer, now=current)
    )
    member = find_member(checked.offered_manifest, checked.member_id)
    if member is None or member.status != "active":
        raise ValidationError("Workspace device-link member is unavailable")
    card = create_workspace_device_card(
        new_identity,
        workspace_id=checked.workspace_id,
        member_id=checked.member_id,
        device_id=device_id or str(uuid.uuid4()),
        display_name=member.display_name,
        hints=hints,
        now=current,
    )
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_device_link",
        "workspace_id": checked.workspace_id,
        "link_id": checked.link_id,
        "offer_digest": checked.digest,
        "offer": json.loads(checked.serialized),
        "device_card": json.loads(card),
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "accepted_at": current,
    }
    return _sign(new_identity, unsigned, maximum=MAX_DEVICE_LINK_BYTES)


def verify_workspace_device_link_acceptance(
    raw: str,
    *,
    offer: str | VerifiedWorkspaceDeviceLinkOffer | None = None,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceDeviceLinkAcceptance:
    value = _load_document(raw, "workspace_device_link")
    _require_fields(
        value,
        {
            "v", "type", "workspace_id", "link_id", "offer_digest", "offer",
            "device_card", "replay_key", "accepted_at", "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION or not isinstance(
        value["offer"], dict
    ) or not isinstance(value["device_card"], dict):
        raise ValidationError("Workspace device-link acceptance is invalid")
    current = int(time.time()) if now is None else int(now)
    embedded = verify_workspace_device_link_offer(
        _canonical(value["offer"]), now=current, allow_expired=allow_expired
    )
    expected = (
        offer
        if isinstance(offer, VerifiedWorkspaceDeviceLinkOffer)
        else verify_workspace_device_link_offer(
            offer, now=current, allow_expired=allow_expired
        )
        if isinstance(offer, str)
        else embedded
    )
    if embedded.serialized != expected.serialized:
        raise ValidationError("Workspace device-link acceptance uses another offer")
    if (
        value["workspace_id"] != embedded.workspace_id
        or value["link_id"] != embedded.link_id
        or value["offer_digest"] != embedded.digest
    ):
        raise ValidationError("Workspace device-link acceptance does not match its offer")
    card = verify_workspace_device_card(
        _canonical(value["device_card"]),
        expected_workspace_id=embedded.workspace_id,
        expected_member_id=embedded.member_id,
        now=current,
    )
    if find_device(embedded.offered_manifest, card.device_id) is not None:
        raise ValidationError("Workspace device is already admitted")
    _verify_signature(
        _identity_from_public_key(card.public_identity),
        value,
        "Workspace device-link acceptance",
    )
    accepted_at = _validate_timestamp(value["accepted_at"], now=current)
    if accepted_at < embedded.created_at or accepted_at > embedded.expires_at:
        raise InvitationExpired("Workspace device-link acceptance is outside its validity window")
    return VerifiedWorkspaceDeviceLinkAcceptance(
        offer=embedded,
        device=card,
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        accepted_at=accepted_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_device_removal(
    actor_identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    actor_device_id: str,
    target_device_id: str,
    now: int | None = None,
    lifetime_seconds: int = MAX_DEVICE_LINK_LIFETIME_SECONDS,
    removal_id: str | None = None,
    replay_key: str | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_DEVICE_LINK_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace device-removal lifetime is invalid")
    checked_member_id = _validate_uuid(member_id, "Member ID")
    checked_actor_id = _validate_uuid(actor_device_id, "Actor device ID")
    checked_target_id = _validate_uuid(target_device_id, "Target device ID")
    member = find_member(manifest, checked_member_id)
    actor = find_device(manifest, checked_actor_id)
    target = find_device(manifest, checked_target_id)
    if (
        manifest.status != "active"
        or member is None
        or member.status != "active"
        or actor is None
        or target is None
        or actor[0].member_id != checked_member_id
        or target[0].member_id != checked_member_id
        or actor[1].destination_hash != _destination_for(actor_identity)
    ):
        raise IdentityMismatch("Workspace device removal is not authorized")
    if checked_actor_id == checked_target_id:
        raise ValidationError("A device cannot remove itself")
    if checked_target_id == manifest.authority_device_id:
        raise ValidationError("Rotate workspace authority before removing that device")
    if len(member.devices) <= 1:
        raise ValidationError("A member must retain one admitted device")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_device_removal",
        "workspace_id": manifest.workspace_id,
        "removal_id": _validate_uuid(removal_id or str(uuid.uuid4()), "Device-removal ID"),
        "base_manifest_epoch": manifest.epoch,
        "base_manifest_digest": manifest.digest,
        "member_id": checked_member_id,
        "actor_device_id": checked_actor_id,
        "target_device_id": checked_target_id,
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "created_at": current,
        "expires_at": current + lifetime_seconds,
    }
    return _sign(actor_identity, unsigned)


def verify_workspace_device_removal(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceDeviceRemoval:
    value = _load_document(raw, "workspace_device_removal")
    _require_fields(
        value,
        {
            "v", "type", "workspace_id", "removal_id", "base_manifest_epoch",
            "base_manifest_digest", "member_id", "actor_device_id",
            "target_device_id", "replay_key", "created_at", "expires_at",
            "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace device-removal version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    removal_id = _validate_uuid(value["removal_id"], "Device-removal ID")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    actor_device_id = _validate_uuid(value["actor_device_id"], "Actor device ID")
    target_device_id = _validate_uuid(value["target_device_id"], "Target device ID")
    base_epoch = value["base_manifest_epoch"]
    base_digest = _validate_digest(value["base_manifest_digest"], "Base manifest digest")
    if (
        workspace_id != manifest.workspace_id
        or isinstance(base_epoch, bool)
        or not isinstance(base_epoch, int)
        or base_epoch != manifest.epoch
        or base_digest != manifest.digest
        or manifest.status != "active"
    ):
        raise ValidationError("Workspace device removal is stale")
    member = find_member(manifest, member_id)
    actor = find_device(manifest, actor_device_id)
    target = find_device(manifest, target_device_id)
    if (
        member is None
        or member.status != "active"
        or actor is None
        or target is None
        or actor[0].member_id != member_id
        or target[0].member_id != member_id
    ):
        raise IdentityMismatch("Workspace device removal is not authorized")
    if actor_device_id == target_device_id:
        raise ValidationError("A device cannot remove itself")
    if target_device_id == manifest.authority_device_id:
        raise ValidationError("Rotate workspace authority before removing that device")
    if len(member.devices) <= 1:
        raise ValidationError("A member must retain one admitted device")
    _verify_signature(
        _identity_from_public_key(actor[1].public_identity),
        value,
        "Workspace device removal",
    )
    current = int(time.time()) if now is None else int(now)
    created_at = _validate_timestamp(value["created_at"], now=current)
    expires_at = value["expires_at"]
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at < created_at
        or expires_at - created_at > MAX_DEVICE_LINK_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace device-removal dates are invalid")
    if expires_at < current and not allow_expired:
        raise InvitationExpired("Workspace device removal has expired")
    return VerifiedWorkspaceDeviceRemoval(
        workspace_id=workspace_id,
        removal_id=removal_id,
        base_manifest_epoch=base_epoch,
        base_manifest_digest=base_digest,
        member_id=member_id,
        actor_device_id=actor_device_id,
        target_device_id=target_device_id,
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        created_at=created_at,
        expires_at=expires_at,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def verify_workspace_device_manifest_transition(
    raw: str,
    previous: VerifiedWorkspaceManifest,
    *,
    transition: str | VerifiedWorkspaceDeviceLinkAcceptance | VerifiedWorkspaceDeviceRemoval,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceManifest:
    """Verify the one-card delta authorized by a countersigned transition."""

    if isinstance(transition, VerifiedWorkspaceDeviceLinkAcceptance):
        checked: VerifiedWorkspaceDeviceLinkAcceptance | VerifiedWorkspaceDeviceRemoval = transition
    elif isinstance(transition, VerifiedWorkspaceDeviceRemoval):
        checked = transition
    elif isinstance(transition, str):
        try:
            transition_value = json.loads(transition)
        except json.JSONDecodeError as exc:
            raise ValidationError("Workspace device transition is invalid") from exc
        if not isinstance(transition_value, dict):
            raise ValidationError("Workspace device transition is invalid")
        if transition_value.get("type") == "workspace_device_link":
            checked = verify_workspace_device_link_acceptance(
                transition, now=now, allow_expired=allow_expired
            )
        elif transition_value.get("type") == "workspace_device_removal":
            checked = verify_workspace_device_removal(
                transition, manifest=previous, now=now, allow_expired=allow_expired
            )
        else:
            raise ValidationError("Workspace device transition is invalid")
    else:
        raise ValidationError("Workspace device transition is invalid")
    base_epoch = (
        checked.offer.base_manifest_epoch
        if isinstance(checked, VerifiedWorkspaceDeviceLinkAcceptance)
        else checked.base_manifest_epoch
    )
    base_digest = (
        checked.offer.base_manifest_digest
        if isinstance(checked, VerifiedWorkspaceDeviceLinkAcceptance)
        else checked.base_manifest_digest
    )
    if base_epoch != previous.epoch or base_digest != previous.digest:
        raise ValidationError("Workspace device transition is stale")
    manifest = verify_workspace_manifest(
        raw,
        expected_workspace_id=previous.workspace_id,
        expected_epoch=previous.epoch + 1,
        expected_previous_hash=previous.digest,
        expected_authority_destination=previous.authority_destination,
        now=now,
    )
    if (
        manifest.device_transition_digest != checked.digest
        or manifest.authority_transition_digest is not None
        or manifest.authority_signer_destination is not None
        or manifest.authority_device_id != previous.authority_device_id
        or manifest.authority_destination != previous.authority_destination
        or manifest.status != previous.status
        or manifest.name != previous.name
        or manifest.description != previous.description
        or manifest.retention_days != previous.retention_days
        or manifest.channel_creation != previous.channel_creation
        or manifest.posting != previous.posting
        or manifest.invitation_requests != previous.invitation_requests
        or manifest.removal_checkpoint_digests != previous.removal_checkpoint_digests
        or manifest.created_at < previous.created_at
    ):
        raise ValidationError("Workspace device manifest is not bound to its transition")
    before = {member.member_id: member for member in previous.members}
    after = {member.member_id: member for member in manifest.members}
    if before.keys() != after.keys():
        raise ValidationError("Workspace device transition changed membership")
    target_member_id = (
        checked.offer.member_id
        if isinstance(checked, VerifiedWorkspaceDeviceLinkAcceptance)
        else checked.member_id
    )
    for member_id, old_member in before.items():
        new_member = after[member_id]
        if (
            new_member.display_name != old_member.display_name
            or new_member.role != old_member.role
            or new_member.status != old_member.status
        ):
            raise ValidationError("Workspace device transition changed a member")
        old_cards = [device.serialized for device in old_member.devices]
        new_cards = [device.serialized for device in new_member.devices]
        if member_id != target_member_id:
            if new_cards != old_cards:
                raise ValidationError("Workspace device transition changed another member")
            continue
        if isinstance(checked, VerifiedWorkspaceDeviceLinkAcceptance):
            expected_cards = [*old_cards, checked.device.serialized]
            if len(new_cards) > MAX_LINKED_DEVICES_PER_MEMBER:
                raise ValidationError("Workspace member has too many linked devices")
        else:
            expected_cards = [
                device.serialized
                for device in old_member.devices
                if device.device_id != checked.target_device_id
            ]
            if not expected_cards:
                raise ValidationError("Workspace member must retain one device")
        if new_cards != expected_cards:
            raise ValidationError("Workspace device manifest has the wrong device delta")
    if sum(len(member.devices) for member in manifest.members) > MAX_ACTIVE_DEVICES:
        raise ValidationError("Workspace manifest has too many active devices")
    return manifest


def create_workspace_read_hint(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    member_id: str,
    device_id: str,
    conversation_id: str,
    through_event_id: str,
    event_digest: str,
    now: int | None = None,
) -> str:
    member = find_member(manifest, _validate_uuid(member_id, "Member ID"))
    device = find_device(manifest, _validate_uuid(device_id, "Device ID"))
    if (
        manifest.status != "active"
        or member is None
        or member.status != "active"
        or device is None
        or device[0].member_id != member.member_id
        or device[1].destination_hash != _destination_for(identity)
    ):
        raise IdentityMismatch("Workspace read-hint signer is not admitted")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_read_hint",
        "workspace_id": manifest.workspace_id,
        "manifest_digest": manifest.digest,
        "member_id": member.member_id,
        "device_id": device[1].device_id,
        "conversation_id": _validate_uuid(conversation_id, "Conversation ID"),
        "through_event_id": _validate_uuid(through_event_id, "Event ID"),
        "event_digest": _validate_digest(event_digest, "Event digest"),
        "created_at": int(time.time()) if now is None else int(now),
    }
    return _sign(identity, unsigned)


def verify_workspace_read_hint(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
) -> VerifiedWorkspaceReadHint:
    value = _load_document(raw, "workspace_read_hint")
    _require_fields(
        value,
        {
            "v", "type", "workspace_id", "manifest_digest", "member_id",
            "device_id", "conversation_id", "through_event_id", "event_digest",
            "created_at", "signature",
        },
    )
    if value["v"] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace read-hint version is unsupported")
    workspace_id = _validate_uuid(value["workspace_id"], "Workspace ID")
    manifest_digest = _validate_digest(value["manifest_digest"], "Manifest digest")
    member_id = _validate_uuid(value["member_id"], "Member ID")
    device_id = _validate_uuid(value["device_id"], "Device ID")
    if workspace_id != manifest.workspace_id or manifest_digest != manifest.digest:
        raise ValidationError("Workspace read hint references another manifest")
    member = find_member(manifest, member_id)
    device = find_device(manifest, device_id)
    if (
        manifest.status != "active"
        or member is None
        or member.status != "active"
        or device is None
        or device[0].member_id != member_id
    ):
        raise IdentityMismatch("Workspace read-hint signer is not admitted")
    _verify_signature(
        _identity_from_public_key(device[1].public_identity),
        value,
        "Workspace read hint",
    )
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceReadHint(
        workspace_id=workspace_id,
        manifest_digest=manifest_digest,
        member_id=member_id,
        device_id=device_id,
        conversation_id=_validate_uuid(value["conversation_id"], "Conversation ID"),
        through_event_id=_validate_uuid(value["through_event_id"], "Event ID"),
        event_digest=_validate_digest(value["event_digest"], "Event digest"),
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )


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
    # Invitation verification permits bounded clock skew. A freshly received
    # invitation may therefore start after our wall clock; preserve its causal
    # ordering without relaxing the verifier's timestamp or expiry checks.
    joined_at = max(current, invite.created_at)
    card = create_workspace_device_card(
        identity,
        workspace_id=invite.workspace_id,
        member_id=new_member_id,
        device_id=new_device_id,
        display_name=display_name,
        hints=hints,
        now=joined_at,
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
        "created_at": joined_at,
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
        and found[0].role not in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}
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


_ADMIN_REQUEST_KINDS = frozenset({"invitation", "member_removal", "role_change"})
_ADMIN_DECISION_OUTCOMES = frozenset({"approved", "declined"})
_ADMIN_RESULT_KINDS = frozenset({"invitation", "manifest", "no_change"})


def _admin_requester_authorized(
    manifest: VerifiedWorkspaceManifest,
    member: VerifiedWorkspaceMember,
    request_kind: str,
) -> bool:
    if member.status != "active" or manifest.status != "active":
        return False
    if request_kind == "invitation":
        return (
            member.role == WorkspaceRole.OWNER
            or manifest.invitation_requests
            == WorkspaceInvitationPolicy.ALL_MEMBERS_REQUEST
            or (
                manifest.invitation_requests
                == WorkspaceInvitationPolicy.OWNER_AND_ADMINS
                and member.role == WorkspaceRole.ADMIN
            )
        )
    return member.role in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}


def create_workspace_admin_request(
    identity: RNS.Identity,
    *,
    manifest: VerifiedWorkspaceManifest,
    request_id: str,
    request_kind: str,
    requester_member_id: str,
    requester_device_id: str,
    target_member_id: str | None = None,
    requested_role: WorkspaceRole | str | None = None,
    note: str = "",
    replay_key: str | None = None,
    created_at: int | None = None,
    expires_at: int | None = None,
) -> str:
    """Create the canonical request phase of ``workspace_admin_request``."""

    if request_kind not in _ADMIN_REQUEST_KINDS:
        raise ValidationError("Workspace administrative request kind is invalid")
    found = find_device(manifest, requester_device_id)
    if (
        found is None
        or found[0].member_id != requester_member_id
        or not _admin_requester_authorized(manifest, found[0], request_kind)
    ):
        raise IdentityMismatch("Workspace administrative requester is not authorized")
    if _destination_for(identity) != found[1].destination_hash:
        raise IdentityMismatch("Workspace administrative request signer is invalid")
    checked_target: str | None = None
    checked_role: str | None = None
    if request_kind == "invitation":
        if target_member_id is not None or requested_role is not None:
            raise ValidationError("Invitation requests cannot target a member or role")
    else:
        checked_target = _validate_uuid(target_member_id, "Target member ID")
        target = find_member(manifest, checked_target)
        if target is None or target.status != "active" or target.role == WorkspaceRole.OWNER:
            raise ValidationError("Workspace administrative request target is invalid")
        if request_kind == "role_change":
            role = _coerce_role(requested_role)
            if role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
                raise ValidationError("Requested workspace role is invalid")
            if target.role == role:
                raise ValidationError("Workspace role-change request is a no-op")
            checked_role = role.value
        elif requested_role is not None:
            raise ValidationError("Member-removal requests cannot include a role")
    created = int(time.time()) if created_at is None else int(created_at)
    expires = (
        created + MAX_ADMIN_REQUEST_LIFETIME_SECONDS
        if expires_at is None
        else int(expires_at)
    )
    if expires < created or expires > created + MAX_ADMIN_REQUEST_LIFETIME_SECONDS:
        raise ValidationError("Workspace administrative request expiry is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_admin_request",
        "phase": "request",
        "workspace_id": manifest.workspace_id,
        "request_id": _validate_uuid(request_id, "Administrative request ID"),
        "request_kind": request_kind,
        "base_manifest_epoch": manifest.epoch,
        "base_manifest_digest": manifest.digest,
        "requester_member_id": _validate_uuid(requester_member_id, "Requester member ID"),
        "requester_device_id": _validate_uuid(requester_device_id, "Requester device ID"),
        "target_member_id": checked_target,
        "requested_role": checked_role,
        "note": _normalize_text(
            note,
            "Administrative request note",
            MAX_ADMIN_REQUEST_NOTE_LENGTH,
            allow_empty=True,
        ),
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "created_at": created,
        "expires_at": expires,
    }
    return _sign(identity, unsigned, maximum=MAX_ADMIN_REQUEST_BYTES)


def verify_workspace_admin_request(
    raw: str,
    *,
    manifest: VerifiedWorkspaceManifest,
    now: int | None = None,
    allow_expired: bool = False,
) -> VerifiedWorkspaceAdminRequest:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ADMIN_REQUEST_BYTES:
        raise ValidationError("Workspace administrative request is too large")
    value = _load_document(raw, "workspace_admin_request")
    _require_fields(
        value,
        {
            "v", "type", "phase", "workspace_id", "request_id",
            "request_kind", "base_manifest_epoch", "base_manifest_digest",
            "requester_member_id", "requester_device_id", "target_member_id",
            "requested_role", "note", "replay_key", "created_at", "expires_at",
            "signature",
        },
    )
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or value["phase"] != "request"
        or value["workspace_id"] != manifest.workspace_id
        or value["base_manifest_epoch"] != manifest.epoch
        or value["base_manifest_digest"] != manifest.digest
    ):
        raise ValidationError("Workspace administrative request controls do not match")
    request_kind = value["request_kind"]
    if request_kind not in _ADMIN_REQUEST_KINDS:
        raise ValidationError("Workspace administrative request kind is invalid")
    requester_member_id = _validate_uuid(value["requester_member_id"], "Requester member ID")
    requester_device_id = _validate_uuid(value["requester_device_id"], "Requester device ID")
    found = find_device(manifest, requester_device_id)
    if (
        found is None
        or found[0].member_id != requester_member_id
        or not _admin_requester_authorized(manifest, found[0], request_kind)
    ):
        raise IdentityMismatch("Workspace administrative requester is not authorized")
    _verify_signature(
        _identity_from_public_key(found[1].public_identity),
        value,
        "Workspace administrative request",
    )
    target_member_id: str | None = None
    requested_role: WorkspaceRole | None = None
    if request_kind == "invitation":
        if value["target_member_id"] is not None or value["requested_role"] is not None:
            raise ValidationError("Invitation requests cannot target a member or role")
    else:
        target_member_id = _validate_uuid(value["target_member_id"], "Target member ID")
        target = find_member(manifest, target_member_id)
        if target is None or target.status != "active" or target.role == WorkspaceRole.OWNER:
            raise ValidationError("Workspace administrative request target is invalid")
        if request_kind == "role_change":
            requested_role = _coerce_role(value["requested_role"])
            if requested_role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
                raise ValidationError("Requested workspace role is invalid")
            if target.role == requested_role:
                raise ValidationError("Workspace role-change request is a no-op")
        elif value["requested_role"] is not None:
            raise ValidationError("Member-removal requests cannot include a role")
    current = int(time.time()) if now is None else int(now)
    created = _validate_timestamp(value["created_at"], now=current)
    expires = value["expires_at"]
    if (
        isinstance(expires, bool)
        or not isinstance(expires, int)
        or expires < created
        or expires > created + MAX_ADMIN_REQUEST_LIFETIME_SECONDS
    ):
        raise ValidationError("Workspace administrative request expiry is invalid")
    if not allow_expired and expires < current:
        raise InvitationExpired("Workspace administrative request has expired")
    return VerifiedWorkspaceAdminRequest(
        workspace_id=manifest.workspace_id,
        request_id=_validate_uuid(value["request_id"], "Administrative request ID"),
        request_kind=request_kind,
        base_manifest_epoch=manifest.epoch,
        base_manifest_digest=manifest.digest,
        requester_member_id=requester_member_id,
        requester_device_id=requester_device_id,
        target_member_id=target_member_id,
        requested_role=requested_role,
        note=_normalize_text(
            value["note"],
            "Administrative request note",
            MAX_ADMIN_REQUEST_NOTE_LENGTH,
            allow_empty=True,
        ),
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        created_at=created,
        expires_at=expires,
        digest=_digest(value),
        serialized=_canonical(value),
    )


def create_workspace_admin_decision(
    authority_identity: RNS.Identity,
    *,
    authority_manifest: VerifiedWorkspaceManifest,
    request: VerifiedWorkspaceAdminRequest,
    outcome: str,
    result_kind: str = "no_change",
    result_document: str | None = None,
    replay_key: str | None = None,
    created_at: int | None = None,
) -> str:
    if outcome not in _ADMIN_DECISION_OUTCOMES:
        raise ValidationError("Workspace administrative decision outcome is invalid")
    authority = find_device(authority_manifest, authority_manifest.authority_device_id)
    if (
        authority is None
        or authority[0].role != WorkspaceRole.OWNER
        or authority[0].status != "active"
        or _destination_for(authority_identity) != authority[1].destination_hash
        or request.workspace_id != authority_manifest.workspace_id
    ):
        raise IdentityMismatch("Workspace administrative decision signer is invalid")
    if result_kind not in _ADMIN_RESULT_KINDS:
        raise ValidationError("Workspace administrative decision result is invalid")
    expected_kind = "invitation" if request.request_kind == "invitation" else "manifest"
    if outcome == "declined":
        if result_kind != "no_change" or result_document is not None:
            raise ValidationError("Declined administrative decisions cannot carry a result")
        result_digest = None
    else:
        if result_kind != expected_kind or not isinstance(result_document, str):
            raise ValidationError("Approved administrative decision result is invalid")
        result_digest = workspace_document_digest(result_document)
        try:
            result_value = json.loads(result_document)
        except json.JSONDecodeError as exc:
            raise ValidationError("Administrative decision result is invalid") from exc
        expected_type = (
            "workspace_invite"
            if result_kind == "invitation"
            else "workspace_manifest_root"
        )
        if result_value.get("type") != expected_type:
            raise ValidationError("Administrative decision result type is invalid")
    unsigned = {
        "v": WORKSPACE_PROTOCOL_VERSION,
        "type": "workspace_admin_request",
        "phase": "decision",
        "workspace_id": request.workspace_id,
        "request_id": request.request_id,
        "request_digest": request.digest,
        "request_kind": request.request_kind,
        "base_manifest_epoch": request.base_manifest_epoch,
        "base_manifest_digest": request.base_manifest_digest,
        "authority_member_id": authority[0].member_id,
        "authority_device_id": authority[1].device_id,
        "outcome": outcome,
        "result_kind": result_kind,
        "result_digest": result_digest,
        "result_document": result_document,
        "replay_key": _validate_uuid(replay_key or str(uuid.uuid4()), "Replay key"),
        "created_at": int(time.time()) if created_at is None else int(created_at),
    }
    return _sign(authority_identity, unsigned, maximum=MAX_ADMIN_DECISION_BYTES)


def verify_workspace_admin_decision(
    raw: str,
    *,
    authority_manifest: VerifiedWorkspaceManifest,
    request: VerifiedWorkspaceAdminRequest,
    now: int | None = None,
) -> VerifiedWorkspaceAdminDecision:
    value = _load_document(raw, "workspace_admin_request")
    _require_fields(
        value,
        {
            "v", "type", "phase", "workspace_id", "request_id",
            "request_digest", "request_kind", "base_manifest_epoch",
            "base_manifest_digest", "authority_member_id", "authority_device_id",
            "outcome", "result_kind", "result_digest", "result_document",
            "replay_key", "created_at", "signature",
        },
    )
    if (
        value["v"] != WORKSPACE_PROTOCOL_VERSION
        or value["phase"] != "decision"
        or value["workspace_id"] != request.workspace_id
        or value["workspace_id"] != authority_manifest.workspace_id
        or value["request_id"] != request.request_id
        or value["request_digest"] != request.digest
        or value["request_kind"] != request.request_kind
        or value["base_manifest_epoch"] != request.base_manifest_epoch
        or value["base_manifest_digest"] != request.base_manifest_digest
    ):
        raise ValidationError("Workspace administrative decision is not bound to its request")
    authority_member_id = _validate_uuid(value["authority_member_id"], "Authority member ID")
    authority_device_id = _validate_uuid(value["authority_device_id"], "Authority device ID")
    authority = find_device(authority_manifest, authority_device_id)
    if (
        authority is None
        or authority_device_id != authority_manifest.authority_device_id
        or authority[0].member_id != authority_member_id
        or authority[0].role != WorkspaceRole.OWNER
        or authority[0].status != "active"
    ):
        raise IdentityMismatch("Workspace administrative decision authority is invalid")
    _verify_signature(
        _identity_from_public_key(authority[1].public_identity),
        value,
        "Workspace administrative decision",
    )
    outcome = value["outcome"]
    result_kind = value["result_kind"]
    result_document = value["result_document"]
    if outcome not in _ADMIN_DECISION_OUTCOMES or result_kind not in _ADMIN_RESULT_KINDS:
        raise ValidationError("Workspace administrative decision result is invalid")
    expected_kind = "invitation" if request.request_kind == "invitation" else "manifest"
    result_digest: str | None = None
    if outcome == "declined":
        if result_kind != "no_change" or value["result_digest"] is not None or result_document is not None:
            raise ValidationError("Declined administrative decision changed workspace state")
    else:
        if result_kind != expected_kind or not isinstance(result_document, str):
            raise ValidationError("Approved administrative decision result is invalid")
        result_digest = _validate_digest(value["result_digest"], "Administrative result digest")
        if workspace_document_digest(result_document) != result_digest:
            raise ValidationError("Administrative decision result digest is invalid")
        result_value = json.loads(result_document)
        expected_type = "workspace_invite" if result_kind == "invitation" else "workspace_manifest_root"
        if result_value.get("type") != expected_type:
            raise ValidationError("Administrative decision result type is invalid")
    current = int(time.time()) if now is None else int(now)
    return VerifiedWorkspaceAdminDecision(
        workspace_id=request.workspace_id,
        request_id=request.request_id,
        request_digest=request.digest,
        request_kind=request.request_kind,
        base_manifest_epoch=request.base_manifest_epoch,
        base_manifest_digest=request.base_manifest_digest,
        authority_member_id=authority_member_id,
        authority_device_id=authority_device_id,
        outcome=outcome,
        result_kind=result_kind,
        result_digest=result_digest,
        result_document=result_document,
        replay_key=_validate_uuid(value["replay_key"], "Replay key"),
        created_at=_validate_timestamp(value["created_at"], now=current),
        digest=_digest(value),
        serialized=_canonical(value),
    )
