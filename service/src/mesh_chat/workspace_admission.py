from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import verify_workspace_device_card

GRANT_VERSION = 1
GRANT_TYPE = "workspace_admission_grant"
ACCEPTANCE_TYPE = "workspace_admission_acceptance"
MAX_GRANT_ADMISSIONS = 5
MAX_GRANT_LIFETIME = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class VerifiedAdmissionGrant:
    workspace_id: str
    start_manifest_hash: str
    admin_member_id: str
    admin_device_id: str
    admin_destination: str
    admin_device_card: dict[str, Any]
    max_admissions: int
    issued_at: int
    expires_at: int
    nonce: str
    authority_destination: str
    serialized: str
    digest: str


@dataclass(frozen=True, slots=True)
class VerifiedAdmissionAcceptance:
    workspace_id: str
    grant_digest: str
    admin_destination: str
    accepted_at: int
    serialized: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValidationError(f"{label} is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError(f"{label} is invalid") from exc


def _identity(value: Any) -> RNS.Identity:
    public_key = _unb64(value, "Workspace admission public key")
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Workspace admission public key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Workspace admission public key is invalid")
    return identity


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} is invalid")
    try:
        checked = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if str(checked) != value:
        raise ValidationError(f"{label} is invalid")
    return value


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError(f"{label} is invalid")
    return value


def _sign(identity: RNS.Identity, value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    return canonical_bytes(
        {**unsigned, "signature": _b64(identity.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def _verify(identity: RNS.Identity, value: dict[str, Any]) -> None:
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    if not identity.validate(
        _unb64(value["signature"], "Workspace admission signature"),
        canonical_bytes(unsigned),
    ):
        raise IdentityMismatch("Workspace admission signature is invalid")


def create_admission_grant(
    identity: RNS.Identity,
    *,
    workspace_id: str,
    start_manifest_hash: str,
    admin_member_id: str,
    admin_device_id: str,
    admin_device_card: str,
    max_admissions: int = MAX_GRANT_ADMISSIONS,
    lifetime_seconds: int = MAX_GRANT_LIFETIME,
    nonce: bytes | None = None,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    workspace_id = _uuid(workspace_id, "Workspace ID")
    start_manifest_hash = _digest(start_manifest_hash, "Start manifest hash")
    admin_member_id = _uuid(admin_member_id, "Admin member ID")
    admin_device_id = _uuid(admin_device_id, "Admin device ID")
    if (
        isinstance(max_admissions, bool)
        or not isinstance(max_admissions, int)
        or not 1 <= max_admissions <= MAX_GRANT_ADMISSIONS
    ):
        raise ValidationError("Admission grant count is invalid")
    if (
        isinstance(lifetime_seconds, bool)
        or not isinstance(lifetime_seconds, int)
        or not 1 <= lifetime_seconds <= MAX_GRANT_LIFETIME
    ):
        raise ValidationError("Admission grant lifetime is invalid")
    card = verify_workspace_device_card(
        admin_device_card,
        expected_workspace_id=workspace_id,
        expected_member_id=admin_member_id,
        now=current,
    )
    if card.device_id != admin_device_id:
        raise ValidationError("Admission grant admin device is invalid")
    grant_nonce = nonce if nonce is not None else os.urandom(32)
    if len(grant_nonce) != 32:
        raise ValidationError("Admission grant nonce is invalid")
    return _sign(
        identity,
        {
            "v": GRANT_VERSION,
            "type": GRANT_TYPE,
            "workspace_id": workspace_id,
            "start_manifest_hash": start_manifest_hash,
            "admin_member_id": admin_member_id,
            "admin_device_id": admin_device_id,
            "admin_destination": card.destination_hash.hex(),
            "admin_device_card": card.serialized,
            "max_admissions": max_admissions,
            "issued_at": current,
            "expires_at": current + lifetime_seconds,
            "nonce": grant_nonce.hex(),
            "signer_public_key": _b64(identity.get_public_key()),
        },
    )


def verify_admission_grant(raw: Any, *, now: int | None = None) -> VerifiedAdmissionGrant:
    current = int(time.time()) if now is None else int(now)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16 * 1024:
        raise ValidationError("Admission grant is invalid")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Admission grant is invalid") from exc
    fields = {
        "v", "type", "workspace_id", "start_manifest_hash", "admin_member_id",
        "admin_device_id", "admin_destination", "admin_device_card",
        "max_admissions", "issued_at", "expires_at", "nonce",
        "signer_public_key", "signature",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError("Admission grant fields are invalid")
    if value["v"] != GRANT_VERSION or value["type"] != GRANT_TYPE:
        raise ValidationError("Admission grant version is unsupported")
    workspace_id = _uuid(value["workspace_id"], "Workspace ID")
    start = _digest(value["start_manifest_hash"], "Start manifest hash")
    member_id = _uuid(value["admin_member_id"], "Admin member ID")
    device_id = _uuid(value["admin_device_id"], "Admin device ID")
    card = verify_workspace_device_card(
        value["admin_device_card"],
        expected_workspace_id=workspace_id,
        expected_member_id=member_id,
        now=current,
    )
    if (
        card.device_id != device_id
        or card.destination_hash.hex() != value["admin_destination"]
    ):
        raise ValidationError("Admission grant admin device is invalid")
    max_admissions = value["max_admissions"]
    if (
        isinstance(max_admissions, bool)
        or not isinstance(max_admissions, int)
        or not 1 <= max_admissions <= MAX_GRANT_ADMISSIONS
    ):
        raise ValidationError("Admission grant count is invalid")
    issued = value["issued_at"]
    expires = value["expires_at"]
    if (
        isinstance(issued, bool)
        or isinstance(expires, bool)
        or not isinstance(issued, int)
        or not isinstance(expires, int)
        or issued > current + 300
        or expires <= issued
        or expires - issued > MAX_GRANT_LIFETIME
    ):
        raise ValidationError("Admission grant dates are invalid")
    if expires < current:
        raise InvitationExpired("Admission grant has expired")
    nonce = value["nonce"]
    if (
        not isinstance(nonce, str)
        or len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise ValidationError("Admission grant nonce is invalid")
    identity = _identity(value["signer_public_key"])
    _verify(identity, value)
    return VerifiedAdmissionGrant(
        workspace_id=workspace_id,
        start_manifest_hash=start,
        admin_member_id=member_id,
        admin_device_id=device_id,
        admin_destination=value["admin_destination"],
        admin_device_card=json.loads(card.serialized),
        max_admissions=max_admissions,
        issued_at=issued,
        expires_at=expires,
        nonce=nonce,
        authority_destination=_destination(identity),
        serialized=raw,
        digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def create_admission_acceptance(
    identity: RNS.Identity,
    *,
    grant: str,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked = verify_admission_grant(grant, now=current)
    if checked.admin_destination != _destination(identity):
        raise IdentityMismatch("Admission acceptance signer is not the grant admin")
    return _sign(
        identity,
        {
            "v": GRANT_VERSION,
            "type": ACCEPTANCE_TYPE,
            "workspace_id": checked.workspace_id,
            "grant_digest": checked.digest,
            "admin_destination": checked.admin_destination,
            "accepted_at": current,
            "signer_public_key": _b64(identity.get_public_key()),
        },
    )


def verify_admission_acceptance(
    raw: Any, grant: str, *, now: int | None = None
) -> VerifiedAdmissionAcceptance:
    current = int(time.time()) if now is None else int(now)
    checked = verify_admission_grant(grant, now=current)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 8192:
        raise ValidationError("Admission acceptance is invalid")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Admission acceptance is invalid") from exc
    fields = {
        "v", "type", "workspace_id", "grant_digest", "admin_destination",
        "accepted_at", "signer_public_key", "signature",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError("Admission acceptance fields are invalid")
    if value["v"] != GRANT_VERSION or value["type"] != ACCEPTANCE_TYPE:
        raise ValidationError("Admission acceptance version is unsupported")
    if value["workspace_id"] != checked.workspace_id:
        raise ValidationError("Admission acceptance workspace is invalid")
    if value["grant_digest"] != checked.digest:
        raise ValidationError("Admission acceptance grant is invalid")
    if value["admin_destination"] != checked.admin_destination:
        raise ValidationError("Admission acceptance admin is invalid")
    accepted = value["accepted_at"]
    if (
        isinstance(accepted, bool)
        or not isinstance(accepted, int)
        or accepted > current + 300
        or accepted > checked.expires_at
    ):
        raise ValidationError("Admission acceptance date is invalid")
    identity = _identity(value["signer_public_key"])
    _verify(identity, value)
    if _destination(identity) != checked.admin_destination:
        raise IdentityMismatch("Admission acceptance signer is invalid")
    return VerifiedAdmissionAcceptance(
        workspace_id=checked.workspace_id,
        grant_digest=checked.digest,
        admin_destination=checked.admin_destination,
        accepted_at=accepted,
        serialized=raw,
    )
