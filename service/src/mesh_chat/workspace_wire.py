from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import LXMF

from .errors import ValidationError
from .workspace_protocol import (
    MAX_WORKSPACE_DOCUMENT_BYTES,
    MAX_WORKSPACE_EVENT_BYTES,
    WORKSPACE_PROTOCOL_VERSION,
)


WORKSPACE_CUSTOM_TYPE = b"mesh-chat-workspace"
TYPE_FIELD = LXMF.FIELD_CUSTOM_TYPE
META_FIELD = LXMF.FIELD_CUSTOM_META
W_VERSION = 1
W_KIND = 2
W_LOGICAL_ID = 3
W_WORKSPACE_ID = 4
W_EXPIRES_AT = 5
W_DOCUMENT = 6

WORKSPACE_WIRE_KINDS = frozenset(
    {
        "workspace_join",
        "workspace_manifest_root",
        "workspace_channel_record",
        "workspace_event",
        "workspace_leave_request",
    }
)
WORKSPACE_CONTROL_KINDS = WORKSPACE_WIRE_KINDS - {"workspace_event"}
DELIVERY_WINDOW_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class WorkspaceWirePayload:
    kind: str
    logical_id: str
    workspace_id: str
    expires_at: int
    document: str


def _uuid_bytes(value: str, label: str) -> bytes:
    try:
        checked = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if str(checked) != value:
        raise ValidationError(f"{label} is not canonical")
    return checked.bytes


def _uuid_text(value: Any, label: str) -> str:
    if not isinstance(value, bytes) or len(value) != 16:
        raise ValidationError(f"{label} is invalid")
    return str(uuid.UUID(bytes=value))


def is_workspace_payload(message: LXMF.LXMessage) -> bool:
    fields = message.get_fields()
    return isinstance(fields, dict) and fields.get(TYPE_FIELD) == WORKSPACE_CUSTOM_TYPE


def build_workspace_fields(
    *,
    kind: str,
    logical_id: str,
    workspace_id: str,
    expires_at: int,
    document: str,
) -> dict[int, Any]:
    if kind not in WORKSPACE_WIRE_KINDS:
        raise ValidationError("Workspace payload kind is invalid")
    maximum = (
        MAX_WORKSPACE_EVENT_BYTES
        if kind == "workspace_event"
        else MAX_WORKSPACE_DOCUMENT_BYTES
    )
    if (
        not isinstance(document, str)
        or not document
        or len(document.encode("utf-8")) > maximum
    ):
        raise ValidationError("Workspace payload document is invalid")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ValidationError("Workspace payload expiry is invalid")
    return {
        TYPE_FIELD: WORKSPACE_CUSTOM_TYPE,
        META_FIELD: {
            W_VERSION: WORKSPACE_PROTOCOL_VERSION,
            W_KIND: kind,
            W_LOGICAL_ID: _uuid_bytes(logical_id, "Workspace logical ID"),
            W_WORKSPACE_ID: _uuid_bytes(workspace_id, "Workspace ID"),
            W_EXPIRES_AT: expires_at,
            W_DOCUMENT: document,
        },
    }


def parse_workspace_payload(
    message: LXMF.LXMessage, *, now: int | None = None
) -> WorkspaceWirePayload:
    fields = message.get_fields()
    if not isinstance(fields, dict) or fields.get(TYPE_FIELD) != WORKSPACE_CUSTOM_TYPE:
        raise ValidationError("Message is not a workspace payload")
    metadata = fields.get(META_FIELD)
    if not isinstance(metadata, dict) or set(metadata) != {
        W_VERSION,
        W_KIND,
        W_LOGICAL_ID,
        W_WORKSPACE_ID,
        W_EXPIRES_AT,
        W_DOCUMENT,
    }:
        raise ValidationError("Workspace payload metadata is invalid")
    if metadata[W_VERSION] != WORKSPACE_PROTOCOL_VERSION:
        raise ValidationError("Workspace payload version is unsupported")
    kind = metadata[W_KIND]
    if kind not in WORKSPACE_WIRE_KINDS:
        raise ValidationError("Workspace payload kind is invalid")
    expires_at = metadata[W_EXPIRES_AT]
    current = int(time.time()) if now is None else int(now)
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at < current - 24 * 60 * 60
        or expires_at > current + DELIVERY_WINDOW_SECONDS + 24 * 60 * 60
    ):
        raise ValidationError("Workspace payload expiry is invalid")
    document = metadata[W_DOCUMENT]
    maximum = (
        MAX_WORKSPACE_EVENT_BYTES
        if kind == "workspace_event"
        else MAX_WORKSPACE_DOCUMENT_BYTES
    )
    if (
        not isinstance(document, str)
        or not document
        or len(document.encode("utf-8")) > maximum
    ):
        raise ValidationError("Workspace payload document is invalid")
    if message.content:
        raise ValidationError("Workspace payload content must be empty")
    return WorkspaceWirePayload(
        kind=kind,
        logical_id=_uuid_text(metadata[W_LOGICAL_ID], "Workspace logical ID"),
        workspace_id=_uuid_text(metadata[W_WORKSPACE_ID], "Workspace ID"),
        expires_at=expires_at,
        document=document,
    )

