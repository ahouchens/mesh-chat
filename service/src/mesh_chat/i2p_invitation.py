from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypedDict

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import _b64decode, _b64encode, canonical_bytes, verify_invitation
from .workspace_protocol import verify_workspace_invitation

PREFIX = "MESHI2P1:"
WORKSPACE_PREFIX = "MESHI2P1W:"
MAX_BYTES = 40 * 1024
B32 = re.compile(r"^[a-z2-7]{52}\.b32\.i2p$", re.IGNORECASE)


class I2PInvitationFormats(TypedDict):
    link: str
    text: str
    file: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class VerifiedI2PInvitation:
    purpose: str
    inner: str
    access_point: dict[str, str]
    created_at: int
    expires_at: int
    signer_public_key: bytes
    serialized: str


def i2p_invitation_formats(serialized: str, purpose: str) -> I2PInvitationFormats:
    token = _b64encode(serialized.encode("utf-8"))
    prefix = WORKSPACE_PREFIX if purpose == "workspace" else PREFIX
    return {
        "link": f"meshchat://i2p/{token}",
        "text": f"{prefix}{token}",
        "file": serialized,
        "expires_at": 0,
    }


def create_i2p_invitation(
    identity: RNS.Identity,
    inner: str,
    purpose: str,
    access_point: str,
    *,
    label: str | None = None,
    expires_at: int,
    now: int | None = None,
) -> str:
    if purpose not in {"personal", "workspace"}:
        raise ValidationError("I2P invitation purpose is invalid")
    if not isinstance(inner, str) or not inner or len(inner.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("I2P invitation inner document is invalid")
    normalized = _normalize_b32(access_point)
    created = int(time.time()) if now is None else int(now)
    expiry = min(int(expires_at), created + 31 * 24 * 60 * 60)
    if expiry <= created:
        raise ValidationError("I2P invitation has expired")
    public_key = identity.get_public_key()
    unsigned: dict[str, Any] = {
        "v": 1,
        "type": "i2p_invitation",
        "purpose": purpose,
        "inner": inner,
        "inner_digest": hashlib.sha256(inner.encode("utf-8")).hexdigest(),
        "access_point": {
            "b32": normalized,
            "label": (label or "").strip()[:64],
            "relay": True,
        },
        "created_at": created,
        "expires_at": expiry,
        "signer_public_key": _b64encode(public_key),
    }
    signed = {
        **unsigned,
        "signature": _b64encode(identity.sign(canonical_bytes(unsigned))),
    }
    serialized = canonical_bytes(signed).decode("utf-8")
    if len(serialized.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("I2P invitation is too large")
    return serialized


def verify_i2p_invitation(
    raw: str, purpose: str, *, now: int | None = None
) -> VerifiedI2PInvitation | None:
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    upper = stripped.upper()
    if upper.startswith(WORKSPACE_PREFIX):
        prefixed = True
        prefix_length = len(WORKSPACE_PREFIX)
    elif upper.startswith(PREFIX):
        prefixed = True
        prefix_length = len(PREFIX)
    else:
        prefixed = False
        prefix_length = 0
    if prefixed:
        compact = "".join(raw.split())
        token = compact[prefix_length:]
        if not token or len(token) > MAX_BYTES:
            raise ValidationError("I2P invitation is invalid")
        try:
            serialized = base64.urlsafe_b64decode(
                token + "=" * (-len(token) % 4)
            ).decode("utf-8")
        except Exception as exc:
            raise ValidationError("I2P invitation is invalid") from exc
    else:
        serialized = stripped
    try:
        value = json.loads(serialized)
    except Exception as exc:
        if prefixed:
            raise ValidationError("I2P invitation is invalid") from exc
        return None
    if not isinstance(value, dict) or value.get("type") != "i2p_invitation":
        if prefixed:
            raise ValidationError("I2P invitation fields are invalid")
        return None
    if not isinstance(value, dict) or serialized != canonical_bytes(value).decode("utf-8"):
        raise ValidationError("I2P invitation is not canonical")
    expected = {
        "v", "type", "purpose", "inner", "inner_digest", "access_point",
        "created_at", "expires_at", "signer_public_key", "signature",
    }
    if set(value) != expected or value["v"] != 1 or value["type"] != "i2p_invitation":
        raise ValidationError("I2P invitation fields are invalid")
    if value["purpose"] != purpose:
        raise ValidationError("I2P invitation purpose does not match")
    current = int(time.time()) if now is None else int(now)
    created_at = _integer(value["created_at"])
    expires_at = _integer(value["expires_at"])
    if created_at > current + 86400 or expires_at <= current:
        raise InvitationExpired("I2P invitation has expired")
    inner = value["inner"]
    if not isinstance(inner, str) or hashlib.sha256(inner.encode("utf-8")).hexdigest() != value["inner_digest"]:
        raise IdentityMismatch("I2P invitation inner digest is invalid")
    access = value["access_point"]
    if not isinstance(access, dict) or set(access) != {"b32", "label", "relay"}:
        raise ValidationError("I2P access point is invalid")
    b32 = _normalize_b32(access["b32"])
    if access["relay"] is not True or not isinstance(access["label"], str) or len(access["label"]) > 64:
        raise ValidationError("I2P access point is invalid")
    public_key = _b64decode(value["signer_public_key"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("I2P signer key is invalid")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("I2P signer key is invalid")
    if not identity.validate(_b64decode(value["signature"]), canonical_bytes(unsigned)):
        raise IdentityMismatch("I2P invitation signature is invalid")
    inner_expiry = _inner_expiry(inner, purpose)
    if expires_at > inner_expiry:
        raise ValidationError("I2P invitation expiry exceeds the inner invitation")
    _require_inner_owner(inner, purpose, public_key)
    return VerifiedI2PInvitation(
        purpose=purpose,
        inner=inner,
        access_point={"b32": b32, "label": access["label"].strip(), "relay": "true"},
        created_at=created_at,
        expires_at=expires_at,
        signer_public_key=public_key,
        serialized=serialized,
    )


def _normalize_b32(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("I2P access point address is invalid")
    normalized = value.strip().lower()
    if not B32.fullmatch(normalized):
        raise ValidationError("I2P access point address is invalid")
    return normalized


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("I2P invitation timestamp is invalid")
    return value


def _inner_expiry(inner: str, purpose: str) -> int:
    if purpose == "personal":
        return int(verify_invitation(inner).expires_at)
    return int(verify_workspace_invitation(inner).expires_at)


def _require_inner_owner(inner: str, purpose: str, public_key: bytes) -> None:
    if purpose == "personal":
        expected = verify_invitation(inner).public_identity
    else:
        expected = verify_workspace_invitation(inner).genesis.owner_device.public_identity
    if expected != public_key:
        raise IdentityMismatch("I2P signer does not match the invitation owner")
