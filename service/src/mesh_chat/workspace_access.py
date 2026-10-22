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
from .remote import validate_profile_document

WORKSPACE_ACCESS_VERSION = 1
WORKSPACE_ACCESS_PREFIX = "MESHACCESS1:"
WORKSPACE_ACCESS_TYPE = "workspace_access_recommendation"
WORKSPACE_ACCESS_DEFAULT_LIFETIME = 7 * 24 * 60 * 60
WORKSPACE_ACCESS_MAX_LIFETIME = 30 * 24 * 60 * 60
MAX_WORKSPACE_ACCESS_BYTES = 32 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceAccess:
    workspace_id: str
    manifest_digest: str
    profile: dict[str, Any]
    created_at: int
    expires_at: int
    authority_destination: str
    serialized: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValidationError(f"{label} is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError(f"{label} is invalid") from exc


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _workspace_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Workspace access workspace ID is invalid")
    try:
        checked = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Workspace access workspace ID is invalid") from exc
    if str(checked) != value:
        raise ValidationError("Workspace access workspace ID is invalid")
    return value


def _digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError("Workspace access manifest digest is invalid")
    return value


def create_workspace_access_recommendation(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    manifest_digest: str,
    profile: dict[str, Any],
    now: int | None = None,
    lifetime_seconds: int = WORKSPACE_ACCESS_DEFAULT_LIFETIME,
) -> str:
    current = int(time.time()) if now is None else int(now)
    workspace_id = _workspace_id(workspace_id)
    manifest_digest = _digest(manifest_digest)
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= WORKSPACE_ACCESS_MAX_LIFETIME
    ):
        raise ValidationError("Workspace access lifetime is invalid")
    checked_profile = validate_profile_document(profile, now=current)
    expires_at = min(current + lifetime_seconds, int(checked_profile["expires_at"]))
    unsigned = {
        "v": WORKSPACE_ACCESS_VERSION,
        "type": WORKSPACE_ACCESS_TYPE,
        "workspace_id": workspace_id,
        "manifest_digest": manifest_digest,
        "profile": checked_profile,
        "created_at": current,
        "expires_at": expires_at,
        "signer_public_key": _b64(identity.get_public_key()),
    }
    value = {
        **unsigned,
        "signature": _b64(identity.sign(canonical_bytes(unsigned))),
    }
    encoded = _b64(canonical_bytes(value))
    serialized = WORKSPACE_ACCESS_PREFIX + encoded
    if len(serialized.encode("utf-8")) > MAX_WORKSPACE_ACCESS_BYTES:
        raise ValidationError("Workspace access recommendation is too large")
    return serialized


def verify_workspace_access_recommendation(
    raw: Any, *, now: int | None = None
) -> VerifiedWorkspaceAccess:
    current = int(time.time()) if now is None else int(now)
    if (
        not isinstance(raw, str)
        or not raw.startswith(WORKSPACE_ACCESS_PREFIX)
        or len(raw.encode("utf-8")) > MAX_WORKSPACE_ACCESS_BYTES
    ):
        raise ValidationError("Workspace access recommendation is invalid")
    try:
        decoded = _unb64(
            raw[len(WORKSPACE_ACCESS_PREFIX) :],
            "Workspace access recommendation",
        ).decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Workspace access recommendation is invalid") from exc
    expected = {
        "v",
        "type",
        "workspace_id",
        "manifest_digest",
        "profile",
        "created_at",
        "expires_at",
        "signer_public_key",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Workspace access recommendation fields are invalid")
    if value["v"] != WORKSPACE_ACCESS_VERSION or value["type"] != WORKSPACE_ACCESS_TYPE:
        raise ValidationError("Workspace access recommendation version is unsupported")
    workspace_id = _workspace_id(value["workspace_id"])
    manifest_digest = _digest(value["manifest_digest"])
    if not isinstance(value["profile"], dict):
        raise ValidationError("Workspace access profile is invalid")
    profile = validate_profile_document(value["profile"], now=current)
    created_at = value["created_at"]
    expires_at = value["expires_at"]
    if (
        isinstance(created_at, bool)
        or isinstance(expires_at, bool)
        or not isinstance(created_at, int)
        or not isinstance(expires_at, int)
        or created_at > current + 300
        or expires_at <= created_at
        or expires_at - created_at > WORKSPACE_ACCESS_MAX_LIFETIME
        or expires_at > int(profile["expires_at"])
    ):
        raise ValidationError("Workspace access recommendation dates are invalid")
    if expires_at < current:
        raise InvitationExpired("Workspace access recommendation has expired")
    public_key = _unb64(value["signer_public_key"], "Workspace access public key")
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Workspace access public key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Workspace access public key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(
        _unb64(value["signature"], "Workspace access signature"),
        canonical_bytes(unsigned),
    ):
        raise IdentityMismatch("Workspace access signature is invalid")
    return VerifiedWorkspaceAccess(
        workspace_id=workspace_id,
        manifest_digest=manifest_digest,
        profile=profile,
        created_at=created_at,
        expires_at=expires_at,
        authority_destination=_destination(identity),
        serialized=raw,
    )
