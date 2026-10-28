"""Versioned signaling encryption; secrets never go to the mailbox host."""
from __future__ import annotations

import base64
import json
import re
import secrets

from RNS.Cryptography.HKDF import hkdf
from RNS.Cryptography.Token import Token

from .errors import ValidationError
from .invitations import canonical_bytes

MAX_DOCUMENT_BYTES = 48 * 1024
MAX_ENVELOPE_BYTES = 68 * 1024
SESSION = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
ROLES = {"request", "offer", "answer"}


def encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(value: object, *, maximum: int = MAX_ENVELOPE_BYTES) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValidationError("Encrypted signaling encoding is invalid")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if encode(raw) != value:
            raise ValueError()
        return raw
    except Exception:
        raise ValidationError("Encrypted signaling encoding is invalid") from None


def new_secret() -> str:
    return encode(secrets.token_bytes(32))


def validate_secret(value: object) -> str:
    if len(decode(value, maximum=43)) != 32:
        raise ValidationError("Signaling encryption secret is invalid")
    return value  # type: ignore[return-value]


def derive_key(secret: str, session: str, role: str) -> bytes:
    validate_secret(secret)
    if not isinstance(session, str) or not SESSION.fullmatch(session) or not isinstance(role, str) or role not in ROLES:
        raise ValidationError("Signaling context is invalid")
    return hkdf(length=64, derive_from=decode(secret), salt=b"mesh-chat:signal:v2",
                context=canonical_bytes(["mesh-chat:signal:v2", session, role]))


def seal(document: str, secret: str, session: str, role: str) -> bytes:
    if not isinstance(document, str) or not document or len(document.encode()) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Signaling document is invalid or too large")
    ciphertext = Token(derive_key(secret, session, role)).encrypt(document.encode("utf-8"))
    envelope = canonical_bytes({"v": 2, "ciphertext": encode(ciphertext)})
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise ValidationError("Encrypted signaling document is too large")
    return envelope


def unseal(envelope: bytes, secret: str, session: str, role: str) -> str:
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise ValidationError("Encrypted signaling document is too large")
    try:
        value = json.loads(envelope)
        if not isinstance(value, dict) or set(value) != {"v", "ciphertext"} or type(value["v"]) is not int or value["v"] != 2:
            raise ValueError()
        raw = Token(derive_key(secret, session, role)).decrypt(decode(value["ciphertext"]))
        if not raw or len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError()
        return raw.decode("utf-8")
    except Exception:
        raise ValidationError("Encrypted signaling authentication failed") from None
