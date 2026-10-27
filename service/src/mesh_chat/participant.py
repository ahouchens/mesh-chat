from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes, readable_fingerprint, verify_invitation
from .remote import validate_endpoint
from .workspace_protocol import (
    MAX_AUTHORITY_BOOTSTRAP_BYTES,
    find_device,
    verify_workspace_invitation,
)

PARTICIPANT_ACCESS_VERSION = 1
PARTICIPANT_ENVELOPE_VERSION = 3
EMAIL_INVITATION_VERSION = 4
CONNECTION_RESPONSE_VERSION = 1
ROUTE_UPDATE_VERSION = 1
MAX_PARTICIPANT_ENDPOINTS = 3
MAX_PARTICIPANT_PERSONAL_BYTES = 32 * 1024
MAX_PARTICIPANT_WORKSPACE_BYTES = (
    MAX_AUTHORITY_BOOTSTRAP_BYTES * 2 + 8 * 1024
)
MAX_PARTICIPANT_LIFETIME_SECONDS = 24 * 60 * 60
MAX_CONNECTION_DOCUMENT_BYTES = 40 * 1024
MAX_ROUTE_UPDATE_BYTES = 24 * 1024
REPLY_CHALLENGE_BYTES = 32
PARTICIPANT_PATHS = {
    "public_ipv4", "public_ipv6", "upnp", "nat_pmp", "pcp", "manual"
}
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")
ACCESS_MODES = {"participant_direct", "participant_callback"}


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
    mode: Literal["participant_direct", "participant_callback"] = "participant_direct",
) -> dict[str, Any]:
    created = int(time.time()) if now is None else int(now)
    expiry = (
        created + MAX_PARTICIPANT_LIFETIME_SECONDS
        if expires_at is None
        else int(expires_at)
    )
    unsigned = {
        "v": PARTICIPANT_ACCESS_VERSION,
        "mode": mode,
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
    if value["v"] != PARTICIPANT_ACCESS_VERSION or value["mode"] not in ACCESS_MODES:
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
        "mode": value["mode"],
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
        "mode": checked["mode"],
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
    if checked["mode"] != "participant_direct":
        raise ValidationError("Participant invitation access mode is invalid")
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


def _bounded_json(value: str, label: str, *, maximum: int) -> dict[str, Any]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ValidationError(f"{label} is too large")
    try:
        document = json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError(f"{label} encoding is invalid") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"{label} fields are invalid")

    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 6 or nodes > 192:
            raise ValidationError(f"{label} nesting is invalid")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValidationError(f"{label} fields are invalid")
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(document, 0)
    return document


def _invitation_signer(
    inner: str, purpose: Literal["personal", "workspace"], current: int
) -> tuple[RNS.Identity, int, bytes, str]:
    if purpose == "personal":
        verified = verify_invitation(inner, now=current)
        return (
            _identity_from_public_key(verified.public_identity),
            verified.expires_at,
            verified.destination_hash,
            verified.serialized,
        )
    verified_workspace = verify_workspace_invitation(inner, now=current)
    authority = find_device(
        verified_workspace.offered_manifest,
        verified_workspace.offered_manifest.authority_device_id,
    )
    if authority is None:
        raise ValidationError("Workspace authority identity is unavailable")
    return (
        _identity_from_public_key(authority[1].public_identity),
        verified_workspace.expires_at,
        authority[1].destination_hash,
        verified_workspace.serialized,
    )


def _extract_versioned_document(
    raw: str,
    *,
    text_prefix: str,
    link_host: str,
    version: int,
    maximum: int,
) -> str | None:
    if not isinstance(raw, str):
        raise ValidationError("Signed connection document is invalid")
    value = raw.translate(_INVISIBLE).strip()
    if not value or len(value.encode("utf-8")) > maximum * 2:
        raise ValidationError("Signed connection document is empty or too large")

    def matching_version(serialized: str) -> str | None:
        # This helper also probes ordinary workspace invitations. Their signed
        # manifests/device cards can legitimately exceed an email envelope's
        # depth and node limits. Apply those limits only after selecting this
        # format; the other format's verifier still validates its own bounds.
        if len(serialized.encode("utf-8")) > maximum:
            raise ValidationError("Signed connection document is too large")
        try:
            candidate = json.loads(serialized)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValidationError("Signed connection document encoding is invalid") from exc
        if not isinstance(candidate, dict):
            raise ValidationError("Signed connection document fields are invalid")
        if candidate.get("v") != version:
            return None
        _bounded_json(serialized, "Signed connection document", maximum=maximum)
        return serialized

    compact = "".join(value.split())
    lower = compact.lower()
    if lower.startswith(text_prefix.lower()):
        return _b64decode(
            compact[len(text_prefix) :], "Signed connection token", maximum=maximum
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
            raise ValidationError("Signed connection link is invalid")
        decoded = _b64decode(
            parsed.path[1:], "Signed connection token", maximum=maximum
        ).decode("utf-8")
        return matching_version(decoded)
    if value.startswith("{"):
        return matching_version(value)
    return None


@dataclass(frozen=True, slots=True)
class VerifiedEmailInvitation:
    purpose: Literal["personal", "workspace"]
    inner: str
    inviter_access: dict[str, Any] | None
    reply_challenge: str
    signer_destination: bytes
    created_at: int
    expires_at: int
    serialized: str
    digest: str


def create_email_invitation(
    identity: RNS.Identity,
    purpose: Literal["personal", "workspace"],
    inner: str,
    inviter_access: dict[str, Any] | None = None,
    *,
    now: int | None = None,
    reply_challenge: bytes | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    _signer, inner_expiry, expected_destination, canonical_inner = _invitation_signer(
        inner, purpose, current
    )
    if expected_destination != _destination(identity):
        raise IdentityMismatch("Email invitation signer does not match its inner invitation")
    checked_access = None
    if inviter_access is not None:
        checked_access = validate_access_document(inviter_access, now=current)
        if checked_access["mode"] != "participant_direct":
            raise ValidationError("Email invitation access mode is invalid")
        if checked_access["operator_destination"] != expected_destination.hex():
            raise IdentityMismatch("Email invitation access owner is invalid")
    challenge = reply_challenge or secrets.token_bytes(REPLY_CHALLENGE_BYTES)
    if not isinstance(challenge, bytes) or len(challenge) != REPLY_CHALLENGE_BYTES:
        raise ValidationError("Email invitation reply challenge is invalid")
    expiry = min(
        inner_expiry,
        checked_access["expires_at"] if checked_access is not None else inner_expiry,
    )
    unsigned = {
        "v": EMAIL_INVITATION_VERSION,
        "type": "email_invitation",
        "purpose": purpose,
        "inner": canonical_inner,
        "inner_digest": hashlib.sha256(canonical_inner.encode("utf-8")).hexdigest(),
        "inviter_access": checked_access,
        "reply_challenge": _b64encode(challenge),
        "created_at": current,
        "expires_at": expiry,
        "signer_destination": expected_destination.hex(),
    }
    return canonical_bytes(
        {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def email_invitation_formats(
    serialized: str, purpose: Literal["personal", "workspace"]
) -> dict[str, str]:
    maximum = (
        MAX_PARTICIPANT_PERSONAL_BYTES
        if purpose == "personal"
        else MAX_PARTICIPANT_WORKSPACE_BYTES
    )
    if len(serialized.encode("utf-8")) > maximum:
        raise ValidationError("Email-ready invitation is too large")
    token = _b64encode(serialized.encode("utf-8"))
    if purpose == "personal":
        return {
            "link": f"meshchat://invite/{token}",
            "text": f"MESHCHAT4:{token}",
            "file": serialized,
        }
    return {
        "link": f"meshchat://workspace/{token}",
        "text": f"MESHWORKSPACE4:{token}",
        "value": serialized,
    }


def verify_email_invitation(
    raw: str,
    purpose: Literal["personal", "workspace"],
    *,
    now: int | None = None,
) -> VerifiedEmailInvitation | None:
    maximum = (
        MAX_PARTICIPANT_PERSONAL_BYTES
        if purpose == "personal"
        else MAX_PARTICIPANT_WORKSPACE_BYTES
    )
    serialized = _extract_versioned_document(
        raw,
        text_prefix="MESHCHAT4:" if purpose == "personal" else "MESHWORKSPACE4:",
        link_host="invite" if purpose == "personal" else "workspace",
        version=EMAIL_INVITATION_VERSION,
        maximum=maximum,
    )
    if serialized is None:
        return None
    value = _bounded_json(serialized, "Email-ready invitation", maximum=maximum)
    expected = {
        "v", "type", "purpose", "inner", "inner_digest", "inviter_access",
        "reply_challenge", "created_at", "expires_at", "signer_destination",
        "signature",
    }
    if set(value) != expected:
        raise ValidationError("Email-ready invitation fields are invalid")
    if (
        value["v"] != EMAIL_INVITATION_VERSION
        or value["type"] != "email_invitation"
        or value["purpose"] != purpose
    ):
        raise ValidationError("Email-ready invitation version or purpose is unsupported")
    current = int(time.time()) if now is None else int(now)
    signer, inner_expiry, expected_destination, canonical_inner = _invitation_signer(
        value["inner"], purpose, current
    )
    if (
        value["inner"] != canonical_inner
        or value["inner_digest"]
        != hashlib.sha256(canonical_inner.encode("utf-8")).hexdigest()
    ):
        raise ValidationError("Email-ready invitation inner digest is invalid")
    challenge = _b64decode(
        value["reply_challenge"], "Email invitation reply challenge", maximum=64
    )
    if len(challenge) != REPLY_CHALLENGE_BYTES:
        raise ValidationError("Email invitation reply challenge is invalid")
    access = value["inviter_access"]
    if access is not None:
        access = validate_access_document(access, now=current)
        if access["mode"] != "participant_direct":
            raise ValidationError("Email invitation access mode is invalid")
        if access["operator_destination"] != expected_destination.hex():
            raise IdentityMismatch("Email invitation access owner is invalid")
    created = value["created_at"]
    expiry = value["expires_at"]
    if (
        any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expiry))
        or created > current + 24 * 60 * 60
        or expiry <= created
        or expiry > inner_expiry
        or (access is not None and expiry > access["expires_at"])
    ):
        raise ValidationError("Email-ready invitation dates are invalid")
    if expiry < current:
        raise InvitationExpired("Email-ready invitation has expired")
    if value["signer_destination"] != expected_destination.hex():
        raise IdentityMismatch("Email invitation signer does not match its inner invitation")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    signature = _b64decode(value["signature"], "Email invitation signature", maximum=1024)
    if not signer.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Email invitation signature is invalid")
    canonical = canonical_bytes(value).decode("utf-8")
    return VerifiedEmailInvitation(
        purpose,
        canonical_inner,
        access,
        value["reply_challenge"],
        expected_destination,
        created,
        expiry,
        canonical,
        hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class VerifiedConnectionResponse:
    purpose: Literal["personal", "workspace"]
    invitation_digest: str
    reply_challenge: str
    signer_destination: bytes
    responder_public_identity: bytes
    responder_destination: bytes
    access: dict[str, Any]
    created_at: int
    expires_at: int
    serialized: str

    def preview(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "invitation_digest": self.invitation_digest,
            "responder_destination": self.responder_destination.hex(),
            "responder_fingerprint": readable_fingerprint(
                self.responder_public_identity
            ),
            "endpoint_count": len(self.access["endpoints"]),
            "expires_at": self.expires_at,
        }


def create_connection_response(
    responder: RNS.Identity,
    invitation_raw: str,
    purpose: Literal["personal", "workspace"],
    access: dict[str, Any],
    *,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    invitation = verify_email_invitation(invitation_raw, purpose, now=current)
    if invitation is None:
        raise ValidationError("Connection response requires a v4 invitation")
    checked_access = validate_access_document(access, now=current)
    responder_destination = _destination(responder)
    if (
        checked_access["mode"] != "participant_callback"
        or checked_access["operator_destination"] != responder_destination.hex()
    ):
        raise IdentityMismatch("Connection response access owner is invalid")
    expiry = min(invitation.expires_at, checked_access["expires_at"])
    unsigned = {
        "v": CONNECTION_RESPONSE_VERSION,
        "type": "connection_response",
        "purpose": purpose,
        "invitation_digest": invitation.digest,
        "reply_challenge": invitation.reply_challenge,
        "signer_destination": invitation.signer_destination.hex(),
        "responder_public_identity": _b64encode(responder.get_public_key()),
        "responder_destination": responder_destination.hex(),
        "access": checked_access,
        "created_at": current,
        "expires_at": expiry,
    }
    return canonical_bytes(
        {**unsigned, "signature": _b64encode(responder.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def connection_response_formats(serialized: str) -> dict[str, str]:
    if len(serialized.encode("utf-8")) > MAX_CONNECTION_DOCUMENT_BYTES:
        raise ValidationError("Connection response is too large")
    token = _b64encode(serialized.encode("utf-8"))
    return {
        "link": f"meshchat://connect/{token}",
        "text": f"MESHCONNECT1:{token}",
        "file": serialized,
    }


def verify_connection_response(
    raw: str,
    *,
    invitation: VerifiedEmailInvitation | None = None,
    now: int | None = None,
) -> VerifiedConnectionResponse:
    serialized = _extract_versioned_document(
        raw,
        text_prefix="MESHCONNECT1:",
        link_host="connect",
        version=CONNECTION_RESPONSE_VERSION,
        maximum=MAX_CONNECTION_DOCUMENT_BYTES,
    )
    if serialized is None:
        raise ValidationError("Connection response format is unsupported")
    value = _bounded_json(
        serialized, "Connection response", maximum=MAX_CONNECTION_DOCUMENT_BYTES
    )
    expected = {
        "v", "type", "purpose", "invitation_digest", "reply_challenge",
        "signer_destination", "responder_public_identity", "responder_destination",
        "access", "created_at", "expires_at", "signature",
    }
    if set(value) != expected:
        raise ValidationError("Connection response fields are invalid")
    if (
        value["v"] != CONNECTION_RESPONSE_VERSION
        or value["type"] != "connection_response"
        or value["purpose"] not in {"personal", "workspace"}
    ):
        raise ValidationError("Connection response version or purpose is unsupported")
    digest = value["invitation_digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValidationError("Connection response invitation digest is invalid")
    challenge = _b64decode(
        value["reply_challenge"], "Connection response challenge", maximum=64
    )
    if len(challenge) != REPLY_CHALLENGE_BYTES:
        raise ValidationError("Connection response challenge is invalid")
    public_key = _b64decode(
        value["responder_public_identity"],
        "Connection response identity",
        maximum=RNS.Identity.KEYSIZE // 8,
    )
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Connection response identity is invalid")
    responder = _identity_from_public_key(public_key)
    responder_destination = _destination(responder)
    if value["responder_destination"] != responder_destination.hex():
        raise IdentityMismatch("Connection response destination is invalid")
    try:
        signer_destination = bytes.fromhex(value["signer_destination"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("Connection response inviter identity is invalid") from exc
    if len(signer_destination) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
        raise ValidationError("Connection response inviter identity is invalid")
    access = validate_access_document(value["access"], now=now)
    if (
        access["mode"] != "participant_callback"
        or access["operator_destination"] != responder_destination.hex()
    ):
        raise IdentityMismatch("Connection response access owner is invalid")
    current = int(time.time()) if now is None else int(now)
    created = value["created_at"]
    expiry = value["expires_at"]
    if (
        any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expiry))
        or created > current + 24 * 60 * 60
        or expiry <= created
        or expiry > access["expires_at"]
        or expiry - created > MAX_PARTICIPANT_LIFETIME_SECONDS
    ):
        raise ValidationError("Connection response dates are invalid")
    if expiry < current:
        raise InvitationExpired("Connection response has expired")
    if invitation is not None and (
        value["purpose"] != invitation.purpose
        or digest != invitation.digest
        or value["reply_challenge"] != invitation.reply_challenge
        or signer_destination != invitation.signer_destination
        or expiry > invitation.expires_at
    ):
        raise IdentityMismatch("Connection response does not match the invitation")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    signature = _b64decode(value["signature"], "Connection response signature", maximum=1024)
    if not responder.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Connection response signature is invalid")
    canonical = canonical_bytes(value).decode("utf-8")
    return VerifiedConnectionResponse(
        value["purpose"], digest, value["reply_challenge"], signer_destination,
        public_key, responder_destination, access, created, expiry, canonical,
    )


@dataclass(frozen=True, slots=True)
class VerifiedRouteUpdate:
    scope_kind: Literal["contact", "workspace_device"]
    scope_id: str
    audience_destination: bytes
    issuer_public_identity: bytes
    issuer_destination: bytes
    generation: int
    access: dict[str, Any]
    created_at: int
    expires_at: int
    serialized: str

    def preview(self) -> dict[str, Any]:
        return {
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
            "issuer_destination": self.issuer_destination.hex(),
            "issuer_fingerprint": readable_fingerprint(self.issuer_public_identity),
            "generation": self.generation,
            "endpoint_count": len(self.access["endpoints"]),
            "expires_at": self.expires_at,
        }


def create_route_update(
    issuer: RNS.Identity,
    *,
    scope_kind: Literal["contact", "workspace_device"],
    scope_id: str,
    audience_destination: bytes,
    generation: int,
    access: dict[str, Any],
    now: int | None = None,
) -> str:
    if scope_kind not in {"contact", "workspace_device"}:
        raise ValidationError("Route update scope is invalid")
    if not isinstance(scope_id, str) or not 1 <= len(scope_id) <= 128:
        raise ValidationError("Route update scope is invalid")
    if (
        not isinstance(audience_destination, bytes)
        or len(audience_destination) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= 2**63 - 1
    ):
        raise ValidationError("Route update binding is invalid")
    current = int(time.time()) if now is None else int(now)
    checked_access = validate_access_document(access, now=current)
    issuer_destination = _destination(issuer)
    if (
        checked_access["mode"] != "participant_callback"
        or checked_access["operator_destination"] != issuer_destination.hex()
    ):
        raise IdentityMismatch("Route update access owner is invalid")
    unsigned = {
        "v": ROUTE_UPDATE_VERSION,
        "type": "route_update",
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "audience_destination": audience_destination.hex(),
        "issuer_public_identity": _b64encode(issuer.get_public_key()),
        "issuer_destination": issuer_destination.hex(),
        "generation": generation,
        "access": checked_access,
        "created_at": current,
        "expires_at": checked_access["expires_at"],
    }
    return canonical_bytes(
        {**unsigned, "signature": _b64encode(issuer.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def route_update_formats(serialized: str) -> dict[str, str]:
    if len(serialized.encode("utf-8")) > MAX_ROUTE_UPDATE_BYTES:
        raise ValidationError("Route update is too large")
    token = _b64encode(serialized.encode("utf-8"))
    return {
        "link": f"meshchat://route/{token}",
        "text": f"MESHROUTE1:{token}",
        "file": serialized,
    }


def verify_route_update(raw: str, *, now: int | None = None) -> VerifiedRouteUpdate:
    serialized = _extract_versioned_document(
        raw,
        text_prefix="MESHROUTE1:",
        link_host="route",
        version=ROUTE_UPDATE_VERSION,
        maximum=MAX_ROUTE_UPDATE_BYTES,
    )
    if serialized is None:
        raise ValidationError("Route update format is unsupported")
    value = _bounded_json(serialized, "Route update", maximum=MAX_ROUTE_UPDATE_BYTES)
    expected = {
        "v", "type", "scope_kind", "scope_id", "audience_destination",
        "issuer_public_identity", "issuer_destination", "generation", "access",
        "created_at", "expires_at", "signature",
    }
    if set(value) != expected:
        raise ValidationError("Route update fields are invalid")
    if (
        value["v"] != ROUTE_UPDATE_VERSION
        or value["type"] != "route_update"
        or value["scope_kind"] not in {"contact", "workspace_device"}
        or not isinstance(value["scope_id"], str)
        or not 1 <= len(value["scope_id"]) <= 128
    ):
        raise ValidationError("Route update version or scope is unsupported")
    public_key = _b64decode(
        value["issuer_public_identity"], "Route update identity",
        maximum=RNS.Identity.KEYSIZE // 8,
    )
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Route update identity is invalid")
    issuer = _identity_from_public_key(public_key)
    issuer_destination = _destination(issuer)
    if value["issuer_destination"] != issuer_destination.hex():
        raise IdentityMismatch("Route update issuer destination is invalid")
    try:
        audience = bytes.fromhex(value["audience_destination"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("Route update audience is invalid") from exc
    generation = value["generation"]
    if (
        len(audience) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= 2**63 - 1
    ):
        raise ValidationError("Route update binding is invalid")
    access = validate_access_document(value["access"], now=now)
    if (
        access["mode"] != "participant_callback"
        or access["operator_destination"] != issuer_destination.hex()
    ):
        raise IdentityMismatch("Route update access owner is invalid")
    current = int(time.time()) if now is None else int(now)
    created = value["created_at"]
    expiry = value["expires_at"]
    if (
        any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expiry))
        or created > current + 24 * 60 * 60
        or expiry <= created
        or expiry != access["expires_at"]
        or expiry - created > MAX_PARTICIPANT_LIFETIME_SECONDS
    ):
        raise ValidationError("Route update dates are invalid")
    if expiry < current:
        raise InvitationExpired("Route update has expired")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    signature = _b64decode(value["signature"], "Route update signature", maximum=1024)
    if not issuer.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Route update signature is invalid")
    return VerifiedRouteUpdate(
        value["scope_kind"], value["scope_id"], audience, public_key,
        issuer_destination, generation, access, created, expiry,
        canonical_bytes(value).decode("utf-8"),
    )
