from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes, verify_invitation
from .remote import validate_endpoint
from .workspace_protocol import (
    MAX_AUTHORITY_BOOTSTRAP_BYTES,
    find_device,
    verify_workspace_invitation,
)

PARTICIPANT_ACCESS_VERSION = 1
PARTICIPANT_ENVELOPE_VERSION = 3
MAX_PARTICIPANT_ENDPOINTS = 3
MAX_PARTICIPANT_PERSONAL_BYTES = 32 * 1024
MAX_PARTICIPANT_WORKSPACE_BYTES = (
    MAX_AUTHORITY_BOOTSTRAP_BYTES * 2 + 8 * 1024
)
MAX_PARTICIPANT_LIFETIME_SECONDS = 24 * 60 * 60
PARTICIPANT_PATHS = {
    "public_ipv4", "public_ipv6", "upnp", "nat_pmp", "pcp", "manual"
}
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: Any, label: str, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise ValidationError(f"{label} is invalid")
    if any(character not in _TOKEN_CHARS for character in value):
        raise ValidationError(f"{label} is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValidationError(f"{label} is invalid") from exc
    if _b64encode(decoded) != value or len(decoded) > maximum:
        raise ValidationError(f"{label} is invalid")
    return decoded


def _destination(identity: RNS.Identity) -> bytes:
    return RNS.Destination.hash(identity, "lxmf", "delivery")


def _identity_from_public_key(public_key: bytes) -> RNS.Identity:
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Invitation signer identity is invalid")
    return identity


def create_access_document(
    identity: RNS.Identity,
    endpoints: list[dict[str, Any]],
    *,
    network_name: str,
    passphrase: str,
    now: int | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    created = int(time.time()) if now is None else int(now)
    expiry = (
        created + MAX_PARTICIPANT_LIFETIME_SECONDS
        if expires_at is None
        else int(expires_at)
    )
    unsigned = {
        "v": PARTICIPANT_ACCESS_VERSION,
        "mode": "participant_direct",
        "operator_destination": _destination(identity).hex(),
        "endpoints": endpoints,
        "network_name": network_name,
        "passphrase": passphrase,
        "created_at": created,
        "expires_at": expiry,
    }
    return validate_access_document(
        {"id": hashlib.sha256(canonical_bytes(unsigned)).hexdigest(), **unsigned},
        now=created,
    )


def validate_access_document(
    value: Any, *, now: int | None = None
) -> dict[str, Any]:
    expected = {
        "v",
        "id",
        "mode",
        "operator_destination",
        "endpoints",
        "network_name",
        "passphrase",
        "created_at",
        "expires_at",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Participant connection fields are invalid")
    if value["v"] != PARTICIPANT_ACCESS_VERSION or value["mode"] != "participant_direct":
        raise ValidationError("Participant connection version is unsupported")
    try:
        operator = bytes.fromhex(value["operator_destination"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("Participant operator identity is invalid") from exc
    if len(operator) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
        raise ValidationError("Participant operator identity is invalid")
    endpoints = value["endpoints"]
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= MAX_PARTICIPANT_ENDPOINTS:
        raise ValidationError("Participant connection endpoints are invalid")
    checked_endpoints: list[dict[str, Any]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict) or set(endpoint) != {"host", "port", "path"}:
            raise ValidationError("Participant connection endpoint is invalid")
        checked = validate_endpoint(
            {"host": endpoint["host"], "port": endpoint["port"]}
        )
        path = endpoint["path"]
        if path not in PARTICIPANT_PATHS:
            raise ValidationError("Participant connection path is invalid")
        normalized = {**checked, "path": path}
        if normalized in checked_endpoints:
            raise ValidationError("Participant connection endpoints must be distinct")
        checked_endpoints.append(normalized)
    network_name = value["network_name"]
    passphrase = value["passphrase"]
    if not isinstance(network_name, str) or not TOKEN.fullmatch(network_name):
        raise ValidationError("Participant connection network name is invalid")
    if not isinstance(passphrase, str) or not TOKEN.fullmatch(passphrase):
        raise ValidationError("Participant connection credential is invalid")
    created = value["created_at"]
    expiry = value["expires_at"]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expiry)):
        raise ValidationError("Participant connection dates are invalid")
    current = int(time.time()) if now is None else int(now)
    if (
        created > current + 24 * 60 * 60
        or expiry <= created
        or expiry - created > MAX_PARTICIPANT_LIFETIME_SECONDS
    ):
        raise ValidationError("Participant connection dates are invalid")
    if expiry < current:
        raise InvitationExpired("Participant-hosted invitation has expired")
    unsigned = {
        "v": PARTICIPANT_ACCESS_VERSION,
        "mode": "participant_direct",
        "operator_destination": operator.hex(),
        "endpoints": checked_endpoints,
        "network_name": network_name,
        "passphrase": passphrase,
        "created_at": created,
        "expires_at": expiry,
    }
    access_id = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    if value["id"] != access_id:
        raise ValidationError("Participant connection ID is invalid")
    return {"id": access_id, **unsigned}


def preview_participant_access(value: dict[str, Any]) -> dict[str, Any]:
    checked = validate_access_document(value)
    return {
        "id": checked["id"],
        "mode": "participant_direct",
        "operator": "inviter",
        "endpoint_count": len(checked["endpoints"]),
        "expires_at": checked["expires_at"],
        "privacy_disclosure": (
            "The connection goes directly to the person who sent this invitation. "
            "No community or third-party transport node is added."
        ),
    }


def _create_envelope(
    identity: RNS.Identity,
    purpose: Literal["personal", "workspace"],
    inner: str,
    access: dict[str, Any],
    *,
    inner_expires_at: int,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked = validate_access_document(access, now=current)
    if checked["operator_destination"] != _destination(identity).hex():
        raise IdentityMismatch("Participant connection operator does not match invitation signer")
    expiry = min(inner_expires_at, checked["expires_at"])
    unsigned = {
        "v": PARTICIPANT_ENVELOPE_VERSION,
        "type": "participant_invitation",
        "purpose": purpose,
        "inner": inner,
        "inner_digest": hashlib.sha256(inner.encode("utf-8")).hexdigest(),
        "access": checked,
        "created_at": current,
        "expires_at": expiry,
        "signer_destination": _destination(identity).hex(),
    }
    return canonical_bytes(
        {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def create_participant_personal_invitation(
    identity: RNS.Identity,
    inner: str,
    access: dict[str, Any],
    *,
    now: int | None = None,
) -> str:
    invitation = verify_invitation(inner, now=now)
    if invitation.destination_hash != _destination(identity):
        raise IdentityMismatch("Participant invitation signer does not match personal invitation")
    return _create_envelope(
        identity,
        "personal",
        invitation.serialized,
        access,
        inner_expires_at=invitation.expires_at,
        now=now,
    )


def create_participant_workspace_invitation(
    identity: RNS.Identity,
    inner: str,
    access: dict[str, Any],
    *,
    now: int | None = None,
) -> str:
    invitation = verify_workspace_invitation(inner, now=now)
    if invitation.offered_manifest.authority_destination != _destination(identity):
        raise IdentityMismatch("Participant invitation signer is not the workspace authority")
    return _create_envelope(
        identity,
        "workspace",
        invitation.serialized,
        access,
        inner_expires_at=invitation.expires_at,
        now=now,
    )


def participant_invitation_formats(
    serialized: str, purpose: Literal["personal", "workspace"]
) -> dict[str, Any]:
    maximum = (
        MAX_PARTICIPANT_PERSONAL_BYTES
        if purpose == "personal"
        else MAX_PARTICIPANT_WORKSPACE_BYTES
    )
    if len(serialized.encode("utf-8")) > maximum:
        raise ValidationError("Participant-hosted invitation is too large")
    token = _b64encode(serialized.encode("utf-8"))
    if purpose == "personal":
        return {
            "link": f"meshchat://invite/{token}",
            "text": f"MESHCHAT3:{token}",
            "file": serialized,
        }
    return {
        "link": f"meshchat://workspace/{token}",
        "text": f"MESHWORKSPACE3:{token}",
        "value": serialized,
    }


def _extract_envelope(
    raw: str, purpose: Literal["personal", "workspace"]
) -> str | None:
    if not isinstance(raw, str):
        raise ValidationError("Participant-hosted invitation is invalid")
    value = raw.translate(_INVISIBLE).strip()
    maximum = (
        MAX_PARTICIPANT_PERSONAL_BYTES
        if purpose == "personal"
        else MAX_PARTICIPANT_WORKSPACE_BYTES
    )
    if not value or len(value.encode("utf-8")) > maximum * 2:
        raise ValidationError("Participant-hosted invitation is empty or too large")
    compact = "".join(value.split())
    lower = compact.lower()
    text_prefix = "meshchat3:" if purpose == "personal" else "meshworkspace3:"
    link_host = "invite" if purpose == "personal" else "workspace"
    if lower.startswith(text_prefix):
        return _b64decode(
            compact[len(text_prefix) :],
            "Participant invitation token",
            maximum=maximum,
        ).decode("utf-8")
    if lower.startswith(f"meshchat://{link_host}/"):
        parsed = urlsplit(compact)
        if (
            parsed.scheme != "meshchat"
            or parsed.netloc != link_host
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or "/" in parsed.path[1:]
        ):
            raise ValidationError("Participant invitation link is invalid")
        decoded = _b64decode(
            parsed.path[1:], "Participant invitation token", maximum=maximum
        ).decode("utf-8")
        try:
            candidate = json.loads(decoded)
        except json.JSONDecodeError:
            return None
        return (
            decoded
            if isinstance(candidate, dict)
            and candidate.get("v") == PARTICIPANT_ENVELOPE_VERSION
            else None
        )
    if value.startswith("{"):
        try:
            candidate = json.loads(value)
        except json.JSONDecodeError:
            return None
        return (
            value
            if isinstance(candidate, dict)
            and candidate.get("v") == PARTICIPANT_ENVELOPE_VERSION
            else None
        )
    return None


@dataclass(frozen=True, slots=True)
class VerifiedParticipantInvitation:
    purpose: Literal["personal", "workspace"]
    inner: str
    access: dict[str, Any]
    created_at: int
    expires_at: int


def verify_participant_invitation(
    raw: str,
    purpose: Literal["personal", "workspace"],
    *,
    now: int | None = None,
) -> VerifiedParticipantInvitation | None:
    serialized = _extract_envelope(raw, purpose)
    if serialized is None:
        return None
    try:
        value = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValidationError("Participant invitation encoding is invalid") from exc
    expected = {
        "v",
        "type",
        "purpose",
        "inner",
        "inner_digest",
        "access",
        "created_at",
        "expires_at",
        "signer_destination",
        "signature",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Participant invitation fields are invalid")
    if (
        value["v"] != PARTICIPANT_ENVELOPE_VERSION
        or value["type"] != "participant_invitation"
        or value["purpose"] != purpose
    ):
        raise ValidationError("Participant invitation version or purpose is unsupported")
    current = int(time.time()) if now is None else int(now)
    access = validate_access_document(value["access"], now=current)
    inner = value["inner"]
    if (
        not isinstance(inner, str)
        or hashlib.sha256(inner.encode("utf-8")).hexdigest()
        != value["inner_digest"]
    ):
        raise ValidationError("Participant invitation inner digest is invalid")
    if purpose == "personal":
        verified_inner = verify_invitation(inner, now=current)
        signer_identity = _identity_from_public_key(verified_inner.public_identity)
        inner_expiry = verified_inner.expires_at
        expected_destination = verified_inner.destination_hash
    else:
        verified_workspace = verify_workspace_invitation(inner, now=current)
        authority = find_device(
            verified_workspace.offered_manifest,
            verified_workspace.offered_manifest.authority_device_id,
        )
        if authority is None:
            raise ValidationError("Workspace authority identity is unavailable")
        signer_identity = _identity_from_public_key(authority[1].public_identity)
        inner_expiry = verified_workspace.expires_at
        expected_destination = authority[1].destination_hash
    created = value["created_at"]
    expiry = value["expires_at"]
    if (
        any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in (created, expiry)
        )
        or created > current + 24 * 60 * 60
        or expiry <= created
        or expiry > inner_expiry
        or expiry > access["expires_at"]
    ):
        raise ValidationError("Participant invitation dates are invalid")
    if expiry < current:
        raise InvitationExpired("Participant-hosted invitation has expired")
    if (
        value["signer_destination"] != expected_destination.hex()
        or access["operator_destination"] != expected_destination.hex()
    ):
        raise IdentityMismatch("Participant invitation signer does not match its operator")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    signature = _b64decode(
        value["signature"], "Participant invitation signature", maximum=1024
    )
    if not signer_identity.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Participant invitation signature is invalid")
    return VerifiedParticipantInvitation(purpose, inner, access, created, expiry)
