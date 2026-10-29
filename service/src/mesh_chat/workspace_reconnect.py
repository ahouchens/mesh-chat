from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes
from .reconnect import verify_connection_capabilities

WORKSPACE_RECONNECT_VERSION = 1
WORKSPACE_RECONNECT_PREFIX = "MESHWSR1:"
WORKSPACE_RECONNECT_TYPE = "workspace_reconnect_capability"
MAX_WORKSPACE_RECONNECT_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceReconnectCapability:
    workspace_id: str
    manifest_digest: str
    capability: str
    signer_destination: str
    issued_at: int
    expires_at: int
    serialized: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_WORKSPACE_RECONNECT_BYTES:
        raise ValidationError(f"{label} is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError(f"{label} is invalid") from exc


def _workspace_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Workspace reconnect workspace ID is invalid")
    try:
        checked = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Workspace reconnect workspace ID is invalid") from exc
    if str(checked) != value:
        raise ValidationError("Workspace reconnect workspace ID is invalid")
    return value


def _digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError("Workspace reconnect manifest digest is invalid")
    return value


def create_workspace_reconnect_capability(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    manifest_digest: str,
    capability: str,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked = verify_connection_capabilities(capability, now=current)
    if checked.persistent and checked.version != 3:
        raise ValidationError("Workspace reconnect requires bounded v1 capabilities")
    unsigned = {
        "v": WORKSPACE_RECONNECT_VERSION,
        "type": WORKSPACE_RECONNECT_TYPE,
        "workspace_id": _workspace_id(workspace_id),
        "manifest_digest": _digest(manifest_digest),
        "capability": checked.serialized,
        "issued_at": current,
        "expires_at": checked.expires_at,
        "signer_public_key": _b64(identity.get_public_key()),
    }
    value = {
        **unsigned,
        "signature": _b64(identity.sign(canonical_bytes(unsigned))),
    }
    raw = WORKSPACE_RECONNECT_PREFIX + _b64(canonical_bytes(value))
    if len(raw.encode("utf-8")) > MAX_WORKSPACE_RECONNECT_BYTES:
        raise ValidationError("Workspace reconnect capability is too large")
    return raw


def verify_workspace_reconnect_capability(
    raw: Any, *, now: int | None = None
) -> VerifiedWorkspaceReconnectCapability:
    current = int(time.time()) if now is None else int(now)
    if (
        not isinstance(raw, str)
        or not raw.startswith(WORKSPACE_RECONNECT_PREFIX)
        or len(raw.encode("utf-8")) > MAX_WORKSPACE_RECONNECT_BYTES
    ):
        raise ValidationError("Workspace reconnect capability is invalid")
    try:
        value = json.loads(
            _unb64(
                raw[len(WORKSPACE_RECONNECT_PREFIX) :],
                "Workspace reconnect capability",
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Workspace reconnect capability is invalid") from exc
    expected = {
        "v",
        "type",
        "workspace_id",
        "manifest_digest",
        "capability",
        "issued_at",
        "expires_at",
        "signer_public_key",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Workspace reconnect fields are invalid")
    if (
        value["v"] != WORKSPACE_RECONNECT_VERSION
        or value["type"] != WORKSPACE_RECONNECT_TYPE
    ):
        raise ValidationError("Workspace reconnect version is unsupported")
    workspace_id = _workspace_id(value["workspace_id"])
    manifest_digest = _digest(value["manifest_digest"])
    capability = verify_connection_capabilities(value["capability"], now=current)
    if capability.persistent and capability.version != 3:
        raise ValidationError("Workspace reconnect requires bounded v1 capabilities")
    issued_at = value["issued_at"]
    expires_at = value["expires_at"]
    if (
        isinstance(issued_at, bool)
        or isinstance(expires_at, bool)
        or not isinstance(issued_at, int)
        or not isinstance(expires_at, int)
        or issued_at > current + 300
        or (expires_at <= issued_at and not capability.persistent)
        or expires_at != capability.expires_at
    ):
        raise ValidationError("Workspace reconnect dates are invalid")
    if not capability.persistent and expires_at < current:
        raise InvitationExpired("Workspace reconnect capability has expired")
    public_key = _unb64(value["signer_public_key"], "Workspace reconnect public key")
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Workspace reconnect public key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Workspace reconnect public key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(
        _unb64(value["signature"], "Workspace reconnect signature"),
        canonical_bytes(unsigned),
    ):
        raise IdentityMismatch("Workspace reconnect signature is invalid")
    signer = RNS.Destination.hash(identity, "lxmf", "delivery").hex()
    if capability.signer_destination != signer:
        raise IdentityMismatch("Workspace reconnect capability signer is invalid")
    return VerifiedWorkspaceReconnectCapability(
        workspace_id=workspace_id,
        manifest_digest=manifest_digest,
        capability=capability.serialized,
        signer_destination=signer,
        issued_at=issued_at,
        expires_at=expires_at,
        serialized=raw,
    )
