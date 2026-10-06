from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

import LXMF

from .emoji_validation import LEGACY_REACTION_EMOJIS, is_valid_reaction_emoji
from .errors import ValidationError
from .models import MessageKind

PAYLOAD_VERSION = 1
CUSTOM_TYPE = b"mesh-chat"
MAX_TEXT_BYTES = 16 * 1024
DELIVERY_WINDOW_SECONDS = 7 * 24 * 60 * 60

# LXMF explicitly reserves 0xFB and 0xFD for custom type and metadata. The
# metadata map uses compact integer keys to avoid colliding with LXMF fields.
TYPE_FIELD = LXMF.FIELD_CUSTOM_TYPE
META_FIELD = LXMF.FIELD_CUSTOM_META
M_VERSION = 1
M_KIND = 2
M_LOGICAL_ID = 3
M_CONVERSATION_ID = 4
M_EXPIRES_AT = 5
M_RECEIPT_FOR = 6
M_INVITATION = 7
M_GROUP_ID = 8
M_GROUP_EPOCH = 9
M_GROUP_MANIFEST_HASH = 10
M_SENDER_SEQUENCE = 11
M_GROUP_DOCUMENT = 12
M_GROUP_MESSAGE_ID = 13
M_REACTION_FOR = 14
M_REACTION_EMOJI = 15
M_REACTION_ACTIVE = 16
M_REACTION_REVISION = 17

# Kept as a compatibility/export name for the original quick-reaction set.
# Validation is intentionally broader; see is_valid_reaction_emoji().
ALLOWED_REACTION_EMOJIS = LEGACY_REACTION_EMOJIS
REACTION_KINDS = frozenset({MessageKind.REACTION, MessageKind.GROUP_REACTION})

GROUP_KINDS = frozenset(
    {
        MessageKind.GROUP_INVITE,
        MessageKind.GROUP_ACCEPT,
        MessageKind.GROUP_MANIFEST,
        MessageKind.GROUP_CHAT,
        MessageKind.GROUP_REACTION,
        MessageKind.GROUP_RECEIPT,
        MessageKind.GROUP_LEAVE_REQUEST,
    }
)
GROUP_CONTROL_KINDS = frozenset(
    {
        MessageKind.GROUP_INVITE,
        MessageKind.GROUP_ACCEPT,
        MessageKind.GROUP_MANIFEST,
        MessageKind.GROUP_LEAVE_REQUEST,
    }
)
MAX_GROUP_DOCUMENT_BYTES = 16 * 1024
MAX_GROUP_EPOCH = (1 << 63) - 1
MAX_SENDER_SEQUENCE = (1 << 63) - 1
MAX_REACTION_REVISION = (1 << 63) - 1


def _uuid_bytes(value: str, label: str) -> bytes:
    try:
        return uuid.UUID(value).bytes
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{label} is invalid") from exc


def _uuid_text(value: Any, label: str) -> str:
    if not isinstance(value, bytes) or len(value) != 16:
        raise ValidationError(f"{label} is invalid")
    return str(uuid.UUID(bytes=value))


def conversation_id(first_destination: bytes, second_destination: bytes) -> str:
    pair = b"".join(sorted((first_destination, second_destination)))
    digest = hashlib.sha256(b"mesh-chat:conversation:v1:" + pair).digest()[:16]
    return str(uuid.UUID(bytes=digest))


@dataclass(frozen=True, slots=True)
class AppPayload:
    kind: MessageKind
    logical_id: str
    conversation_id: str
    expires_at: int
    text: str
    receipt_for: str | None = None
    invitation: str | None = None
    group_id: str | None = None
    group_epoch: int | None = None
    group_manifest_hash: str | None = None
    sender_sequence: int | None = None
    group_document: str | None = None
    group_message_id: str | None = None
    reaction_for: str | None = None
    reaction_emoji: str | None = None
    reaction_active: bool | None = None
    reaction_revision: int | None = None


def build_fields(
    *,
    kind: MessageKind,
    logical_id: str,
    conversation: str,
    expires_at: int,
    receipt_for: str | None = None,
    invitation: str | None = None,
    group_id: str | None = None,
    group_epoch: int | None = None,
    group_manifest_hash: str | None = None,
    sender_sequence: int | None = None,
    group_document: str | None = None,
    group_message_id: str | None = None,
    reaction_for: str | None = None,
    reaction_emoji: str | None = None,
    reaction_active: bool | None = None,
    reaction_revision: int | None = None,
) -> dict[int, Any]:
    metadata: dict[int, Any] = {
        M_VERSION: PAYLOAD_VERSION,
        M_KIND: kind.value,
        M_LOGICAL_ID: _uuid_bytes(logical_id, "Logical message ID"),
        M_CONVERSATION_ID: _uuid_bytes(conversation, "Conversation ID"),
        M_EXPIRES_AT: int(expires_at),
    }
    if receipt_for is not None:
        metadata[M_RECEIPT_FOR] = _uuid_bytes(receipt_for, "Receipt reference")
    if invitation is not None:
        if not isinstance(invitation, str) or len(invitation.encode("utf-8")) > 16 * 1024:
            raise ValidationError("Contact request invitation is invalid")
        metadata[M_INVITATION] = invitation
    group_values = (
        group_id,
        group_epoch,
        group_manifest_hash,
        sender_sequence,
        group_document,
        group_message_id,
    )
    if kind not in GROUP_KINDS and any(value is not None for value in group_values):
        raise ValidationError("Group metadata is not valid for this message kind")
    if kind in GROUP_KINDS:
        if group_id is None:
            raise ValidationError("Group ID is required")
        metadata[M_GROUP_ID] = _uuid_bytes(group_id, "Group ID")
        if (
            isinstance(group_epoch, bool)
            or not isinstance(group_epoch, int)
            or not 1 <= group_epoch <= MAX_GROUP_EPOCH
        ):
            raise ValidationError("Group epoch is invalid")
        metadata[M_GROUP_EPOCH] = group_epoch
        try:
            manifest_digest = bytes.fromhex(group_manifest_hash or "")
        except (TypeError, ValueError) as exc:
            raise ValidationError("Group manifest hash is invalid") from exc
        if len(manifest_digest) != 32:
            raise ValidationError("Group manifest hash is invalid")
        metadata[M_GROUP_MANIFEST_HASH] = manifest_digest
        if kind == MessageKind.GROUP_CHAT:
            if (
                isinstance(sender_sequence, bool)
                or not isinstance(sender_sequence, int)
                or not 0 <= sender_sequence <= MAX_SENDER_SEQUENCE
            ):
                raise ValidationError("Group sender sequence is invalid")
            metadata[M_SENDER_SEQUENCE] = sender_sequence
        elif sender_sequence is not None:
            raise ValidationError("Group sender sequence is not valid for this message kind")
        if kind in GROUP_CONTROL_KINDS:
            if (
                not isinstance(group_document, str)
                or not group_document
                or len(group_document.encode("utf-8")) > MAX_GROUP_DOCUMENT_BYTES
            ):
                raise ValidationError("Group control document is invalid")
            metadata[M_GROUP_DOCUMENT] = group_document
        elif group_document is not None:
            raise ValidationError("Group control document is not valid for this message kind")
        if kind in {
            MessageKind.GROUP_CHAT,
            MessageKind.GROUP_REACTION,
            MessageKind.GROUP_RECEIPT,
        }:
            if group_message_id is None:
                raise ValidationError("Group message ID is required")
            metadata[M_GROUP_MESSAGE_ID] = _uuid_bytes(
                group_message_id, "Group message ID"
            )
        elif group_message_id is not None:
            metadata[M_GROUP_MESSAGE_ID] = _uuid_bytes(
                group_message_id, "Group message ID"
            )
    reaction_values = (
        reaction_for,
        reaction_emoji,
        reaction_active,
        reaction_revision,
    )
    if kind not in REACTION_KINDS and any(value is not None for value in reaction_values):
        raise ValidationError("Reaction metadata is not valid for this message kind")
    if kind in REACTION_KINDS:
        if reaction_for is None:
            raise ValidationError("Reaction target is required")
        metadata[M_REACTION_FOR] = _uuid_bytes(reaction_for, "Reaction target")
        if not is_valid_reaction_emoji(reaction_emoji):
            raise ValidationError("Reaction emoji is invalid")
        metadata[M_REACTION_EMOJI] = reaction_emoji
        if not isinstance(reaction_active, bool):
            raise ValidationError("Reaction active state is invalid")
        metadata[M_REACTION_ACTIVE] = reaction_active
        if (
            isinstance(reaction_revision, bool)
            or not isinstance(reaction_revision, int)
            or not 1 <= reaction_revision <= MAX_REACTION_REVISION
        ):
            raise ValidationError("Reaction revision is invalid")
        metadata[M_REACTION_REVISION] = reaction_revision
    return {TYPE_FIELD: CUSTOM_TYPE, META_FIELD: metadata}


def parse_payload(message: LXMF.LXMessage, *, now: int | None = None) -> AppPayload:
    fields = message.get_fields()
    if not isinstance(fields, dict) or fields.get(TYPE_FIELD) != CUSTOM_TYPE:
        raise ValidationError("Message is not a Mesh Chat payload")
    metadata = fields.get(META_FIELD)
    if not isinstance(metadata, dict):
        raise ValidationError("Message metadata is invalid")
    allowed = {
        M_VERSION,
        M_KIND,
        M_LOGICAL_ID,
        M_CONVERSATION_ID,
        M_EXPIRES_AT,
        M_RECEIPT_FOR,
        M_INVITATION,
        M_GROUP_ID,
        M_GROUP_EPOCH,
        M_GROUP_MANIFEST_HASH,
        M_SENDER_SEQUENCE,
        M_GROUP_DOCUMENT,
        M_GROUP_MESSAGE_ID,
        M_REACTION_FOR,
        M_REACTION_EMOJI,
        M_REACTION_ACTIVE,
        M_REACTION_REVISION,
    }
    if set(metadata) - allowed or metadata.get(M_VERSION) != PAYLOAD_VERSION:
        raise ValidationError("Message metadata version is unsupported")
    try:
        kind = MessageKind(metadata[M_KIND])
    except (KeyError, ValueError) as exc:
        raise ValidationError("Message kind is invalid") from exc
    logical_id = _uuid_text(metadata.get(M_LOGICAL_ID), "Logical message ID")
    conv_id = _uuid_text(metadata.get(M_CONVERSATION_ID), "Conversation ID")
    expires_at = metadata.get(M_EXPIRES_AT)
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ValidationError("Message expiry is invalid")
    current = int(time.time()) if now is None else now
    if expires_at < current - 24 * 60 * 60:
        raise ValidationError("Message has expired")
    if expires_at > current + DELIVERY_WINDOW_SECONDS + 24 * 60 * 60:
        raise ValidationError("Message expiry exceeds the supported window")
    receipt_for = None
    if M_RECEIPT_FOR in metadata:
        receipt_for = _uuid_text(metadata[M_RECEIPT_FOR], "Receipt reference")
    invitation = metadata.get(M_INVITATION)
    if invitation is not None and (
        not isinstance(invitation, str) or len(invitation.encode("utf-8")) > 16 * 1024
    ):
        raise ValidationError("Contact request invitation is invalid")

    group_id = None
    group_epoch = None
    group_manifest_hash = None
    sender_sequence = None
    group_document = None
    group_message_id = None
    reaction_for = None
    reaction_emoji = None
    reaction_active = None
    reaction_revision = None
    group_metadata_fields = {
        M_GROUP_ID,
        M_GROUP_EPOCH,
        M_GROUP_MANIFEST_HASH,
        M_SENDER_SEQUENCE,
        M_GROUP_DOCUMENT,
        M_GROUP_MESSAGE_ID,
    }
    present_group_fields = set(metadata) & group_metadata_fields
    if kind not in GROUP_KINDS and present_group_fields:
        raise ValidationError("Group metadata is not valid for this message kind")
    if kind in GROUP_KINDS:
        group_id = _uuid_text(metadata.get(M_GROUP_ID), "Group ID")
        group_epoch = metadata.get(M_GROUP_EPOCH)
        if (
            isinstance(group_epoch, bool)
            or not isinstance(group_epoch, int)
            or not 1 <= group_epoch <= MAX_GROUP_EPOCH
        ):
            raise ValidationError("Group epoch is invalid")
        manifest_digest = metadata.get(M_GROUP_MANIFEST_HASH)
        if not isinstance(manifest_digest, bytes) or len(manifest_digest) != 32:
            raise ValidationError("Group manifest hash is invalid")
        group_manifest_hash = manifest_digest.hex()
        if kind == MessageKind.GROUP_CHAT:
            sender_sequence = metadata.get(M_SENDER_SEQUENCE)
            if (
                isinstance(sender_sequence, bool)
                or not isinstance(sender_sequence, int)
                or not 0 <= sender_sequence <= MAX_SENDER_SEQUENCE
            ):
                raise ValidationError("Group sender sequence is invalid")
        elif M_SENDER_SEQUENCE in metadata:
            raise ValidationError("Group sender sequence is not valid for this message kind")
        if kind in GROUP_CONTROL_KINDS:
            group_document = metadata.get(M_GROUP_DOCUMENT)
            if (
                not isinstance(group_document, str)
                or not group_document
                or len(group_document.encode("utf-8")) > MAX_GROUP_DOCUMENT_BYTES
            ):
                raise ValidationError("Group control document is invalid")
        elif M_GROUP_DOCUMENT in metadata:
            raise ValidationError("Group control document is not valid for this message kind")
        if kind in {
            MessageKind.GROUP_CHAT,
            MessageKind.GROUP_REACTION,
            MessageKind.GROUP_RECEIPT,
        }:
            group_message_id = _uuid_text(
                metadata.get(M_GROUP_MESSAGE_ID), "Group message ID"
            )
        elif M_GROUP_MESSAGE_ID in metadata:
            group_message_id = _uuid_text(
                metadata[M_GROUP_MESSAGE_ID], "Group message ID"
            )

    reaction_metadata_fields = {
        M_REACTION_FOR,
        M_REACTION_EMOJI,
        M_REACTION_ACTIVE,
        M_REACTION_REVISION,
    }
    present_reaction_fields = set(metadata) & reaction_metadata_fields
    if kind not in REACTION_KINDS and present_reaction_fields:
        raise ValidationError("Reaction metadata is not valid for this message kind")
    if kind in REACTION_KINDS:
        reaction_for = _uuid_text(metadata.get(M_REACTION_FOR), "Reaction target")
        reaction_emoji = metadata.get(M_REACTION_EMOJI)
        if not is_valid_reaction_emoji(reaction_emoji):
            raise ValidationError("Reaction emoji is invalid")
        reaction_active = metadata.get(M_REACTION_ACTIVE)
        if not isinstance(reaction_active, bool):
            raise ValidationError("Reaction active state is invalid")
        reaction_revision = metadata.get(M_REACTION_REVISION)
        if (
            isinstance(reaction_revision, bool)
            or not isinstance(reaction_revision, int)
            or not 1 <= reaction_revision <= MAX_REACTION_REVISION
        ):
            raise ValidationError("Reaction revision is invalid")

    text = message.content_as_string()
    if text is None or len(message.content) > MAX_TEXT_BYTES:
        raise ValidationError("Message text is invalid or too large")
    if kind == MessageKind.CHAT and not text.strip():
        raise ValidationError("Chat message is empty")
    if kind in {MessageKind.RECEIPT, MessageKind.GROUP_RECEIPT} and (
        text or receipt_for is None
    ):
        raise ValidationError("Receipt payload is invalid")
    if kind == MessageKind.CONTACT_REQUEST and invitation is None:
        raise ValidationError("Contact request lacks a signed invitation")
    if kind not in {MessageKind.CHAT, MessageKind.CONTACT_REQUEST} and invitation is not None:
        raise ValidationError("Invitation is not valid for this message kind")
    if kind == MessageKind.GROUP_CHAT and not text.strip():
        raise ValidationError("Group chat message is empty")
    if kind in REACTION_KINDS and text:
        raise ValidationError("Reaction message content must be empty")
    if kind in REACTION_KINDS and receipt_for is not None:
        raise ValidationError("Receipt reference is not valid for a reaction")
    if kind in GROUP_CONTROL_KINDS and text:
        raise ValidationError("Group control message content must be empty")
    if kind in GROUP_KINDS and kind != MessageKind.GROUP_RECEIPT and receipt_for is not None:
        raise ValidationError("Receipt reference is not valid for this message kind")
    return AppPayload(
        kind=kind,
        logical_id=logical_id,
        conversation_id=conv_id,
        expires_at=expires_at,
        text=text,
        receipt_for=receipt_for,
        invitation=invitation,
        group_id=group_id,
        group_epoch=group_epoch,
        group_manifest_hash=group_manifest_hash,
        sender_sequence=sender_sequence,
        group_document=group_document,
        group_message_id=group_message_id,
        reaction_for=reaction_for,
        reaction_emoji=reaction_emoji,
        reaction_active=reaction_active,
        reaction_revision=reaction_revision,
    )
