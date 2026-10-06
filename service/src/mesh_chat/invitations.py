from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypedDict
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError

INVITATION_VERSION = 1
MAX_INVITATION_BYTES = 16 * 1024
MAX_HINTS = 8
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
TOKEN = re.compile(r"[A-Za-z0-9_-]+")
EMBEDDED_INVITATION = re.compile(
    r"(?:meshchat://invite/|MESHCHAT1:)([A-Za-z0-9_-]+)", re.IGNORECASE
)
INVISIBLE_PASTE_CHARACTERS = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")


class InvitationFormats(TypedDict):
    link: str
    text: str
    file: str
    expires_at: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_INVITATION_BYTES:
        raise ValidationError("Invalid base64 value")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError("Invalid base64 value") from exc


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def readable_fingerprint(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).hexdigest().upper()
    return " ".join(digest[index : index + 4] for index in range(0, len(digest), 4))


def _validate_label(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Invitation label is missing")
    label = " ".join(value.strip().split())
    if not 1 <= len(label) <= 64 or any(ord(char) < 32 for char in label):
        raise ValidationError("Invitation label is invalid")
    return label


def _validate_host(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        raise ValidationError("TCP hint host is invalid")
    if any(marker in value for marker in ("://", "/", "\\", "@", "\x00")):
        raise ValidationError("TCP hint host is invalid")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if not HOSTNAME.fullmatch(value):
            raise ValidationError("TCP hint host is invalid")
        return value.lower()


def validate_hints(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_HINTS:
        raise ValidationError("Invitation connection hints are invalid")
    hints: list[dict[str, Any]] = []
    for hint in value:
        if not isinstance(hint, dict) or set(hint) != {"type", "host", "port"}:
            raise ValidationError("Invitation connection hint is invalid")
        if hint["type"] != "tcp":
            raise ValidationError("Unsupported connection hint")
        port = hint["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValidationError("TCP hint port is invalid")
        hints.append({"type": "tcp", "host": _validate_host(hint["host"]), "port": port})
    return hints


@dataclass(frozen=True, slots=True)
class VerifiedInvitation:
    display_name: str
    public_identity: bytes
    identity_hash: bytes
    destination_hash: bytes
    fingerprint: str
    hints: list[dict[str, Any]]
    created_at: int
    expires_at: int
    serialized: str

    def preview(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "identity_hash": self.identity_hash.hex(),
            "destination_hash": self.destination_hash.hex(),
            "fingerprint": self.fingerprint,
            "hints": self.hints,
            "expires_at": self.expires_at,
        }


def create_invitation(
    identity: RNS.Identity,
    display_name: str,
    *,
    hints: list[dict[str, Any]] | None = None,
    now: int | None = None,
    lifetime_seconds: int = 30 * 24 * 60 * 60,
) -> InvitationFormats:
    label = _validate_label(display_name)
    checked_hints = validate_hints(hints)
    created_at = int(time.time()) if now is None else int(now)
    public_key = identity.get_public_key()
    destination_hash = RNS.Destination.hash(identity, "lxmf", "delivery")
    expires_at = created_at + lifetime_seconds
    unsigned: dict[str, Any] = {
        "v": INVITATION_VERSION,
        "label": label,
        "public_identity": _b64encode(public_key),
        "destination": destination_hash.hex(),
        "created_at": created_at,
        "expires_at": expires_at,
        "hints": checked_hints,
    }
    signed = {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    serialized = canonical_bytes(signed).decode("utf-8")
    token = _b64encode(serialized.encode("utf-8"))
    return {
        "link": f"meshchat://invite/{token}",
        "text": f"MESHCHAT1:{token}",
        "file": serialized,
        "expires_at": expires_at,
    }


def _extract_serialized(raw: str) -> str:
    value = raw.translate(INVISIBLE_PASTE_CHARACTERS).strip()
    if not value or len(value.encode("utf-8")) > MAX_INVITATION_BYTES:
        raise ValidationError("Invitation is empty or too large")
    lower = value.lower()
    if lower.startswith("meshchat://"):
        # Phone clipboards and chat clients can wrap a long token across lines.
        # Whitespace is not part of the URL-safe base64 alphabet, so removing it
        # here is unambiguous and the signature still authenticates the result.
        compact = "".join(value.split())
        parsed = urlsplit(compact)
        if parsed.scheme != "meshchat" or parsed.netloc != "invite":
            raise ValidationError("Invitation link is invalid")
        if parsed.query or parsed.fragment or not parsed.path.startswith("/"):
            raise ValidationError("Invitation link is invalid")
        token = parsed.path[1:]
        if not TOKEN.fullmatch(token):
            raise ValidationError("Invitation link is invalid")
        return _b64decode(token).decode("utf-8")
    if lower.startswith("meshchat1:"):
        token = "".join(value.split())[len("MESHCHAT1:") :]
        if not TOKEN.fullmatch(token):
            raise ValidationError("Invitation text is invalid")
        return _b64decode(token).decode("utf-8")
    embedded = EMBEDDED_INVITATION.findall(value)
    if len(embedded) == 1:
        return _b64decode(embedded[0]).decode("utf-8")
    return value


def verify_invitation(raw: str, *, now: int | None = None) -> VerifiedInvitation:
    try:
        serialized = _extract_serialized(raw)
        if len(serialized.encode("utf-8")) > MAX_INVITATION_BYTES:
            raise ValidationError("Invitation is too large")
        value = json.loads(serialized)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Invitation encoding is invalid") from exc
    expected = {
        "v",
        "label",
        "public_identity",
        "destination",
        "created_at",
        "expires_at",
        "hints",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Invitation fields are invalid")
    if value["v"] != INVITATION_VERSION:
        raise ValidationError("Invitation version is unsupported")
    label = _validate_label(value["label"])
    hints = validate_hints(value["hints"])
    created_at = value["created_at"]
    expires_at = value["expires_at"]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (created_at, expires_at)):
        raise ValidationError("Invitation dates are invalid")
    current = int(time.time()) if now is None else int(now)
    if expires_at < current:
        raise InvitationExpired("Invitation has expired")
    if created_at > current + 24 * 60 * 60 or expires_at <= created_at:
        raise ValidationError("Invitation has an invalid date")
    public_key = _b64decode(value["public_identity"])
    signature = _b64decode(value["signature"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Public identity has an invalid size")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Public identity is invalid")
    derived_destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    try:
        claimed_destination = bytes.fromhex(value["destination"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("Destination is invalid") from exc
    if claimed_destination != derived_destination:
        raise IdentityMismatch("Destination does not match public identity")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    if not identity.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Invitation signature is invalid")
    return VerifiedInvitation(
        display_name=label,
        public_identity=public_key,
        identity_hash=identity.hash,
        destination_hash=derived_destination,
        fingerprint=readable_fingerprint(public_key),
        hints=hints,
        created_at=created_at,
        expires_at=expires_at,
        serialized=canonical_bytes(value).decode("utf-8"),
    )
