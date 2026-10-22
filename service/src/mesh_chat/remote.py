from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import random
import socket
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import canonical_bytes, verify_invitation
from .workspace_protocol import (
    MAX_AUTHORITY_BOOTSTRAP_BYTES,
    find_device,
    verify_workspace_invitation,
)

REMOTE_PROFILE_VERSION = 1
REMOTE_ENVELOPE_VERSION = 2
MAX_REMOTE_PROFILES = 4
MAX_REMOTE_ENDPOINTS = 2
MAX_REMOTE_PROFILE_BYTES = 4 * 1024
MAX_REMOTE_PERSONAL_BYTES = 32 * 1024
MAX_REMOTE_WORKSPACE_BYTES = MAX_AUTHORITY_BOOTSTRAP_BYTES * 2 + MAX_REMOTE_PROFILE_BYTES + 4096
MAX_PROFILE_LIFETIME_SECONDS = 90 * 24 * 60 * 60
MAX_RETRY_SECONDS = 5 * 60
REMOTE_CAPABILITIES = {"reticulum_tcp", "lxmf_propagation"}
REMOTE_ORIGINS = {"manual", "personal_invitation", "workspace_invitation", "workspace_access"}
REMOTE_SCOPE_KINDS = {"manual", "pending_invitation", "contact", "workspace"}
_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
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
    if _b64encode(decoded) != value:
        raise ValidationError(f"{label} is not canonical")
    if len(decoded) > maximum:
        raise ValidationError(f"{label} is too large")
    return decoded


def _normalized_label(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Remote profile label is missing")
    label = " ".join(value.strip().split())
    if not 1 <= len(label) <= 64 or any(ord(character) < 32 for character in label):
        raise ValidationError("Remote profile label is invalid")
    return label


def _host(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 253:
        raise ValidationError("Remote endpoint host is invalid")
    if any(marker in value for marker in ("://", "/", "\\", "@", "\x00", "%")):
        raise ValidationError("Remote endpoint host is invalid")
    stripped = value.rstrip(".")
    try:
        return ipaddress.ip_address(stripped).compressed
    except ValueError:
        labels = stripped.split(".")
        if (
            not labels
            or any(
                not 1 <= len(item) <= 63
                or not item[0].isalnum()
                or not item[-1].isalnum()
                or any(not (character.isalnum() or character == "-") for character in item)
                for item in labels
            )
        ):
            raise ValidationError("Remote endpoint host is invalid")
        hostname = stripped.lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".home", ".lan")):
            raise ValidationError("Imported remote profiles cannot target local hostnames")
        return hostname


def address_is_public(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # is_global rejects private, loopback, link-local, multicast, unspecified,
    # documentation, benchmarking and IANA-reserved ranges on supported Python.
    return bool(address.is_global and not address.is_multicast)


def validate_endpoint(value: Any, *, allow_private: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"host", "port"}:
        raise ValidationError("Remote endpoint fields are invalid")
    host = _host(value["host"])
    port = value["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValidationError("Remote endpoint port is invalid")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not allow_private and not address_is_public(host):
        raise ValidationError("Imported remote profiles require public endpoints")
    return {"host": host, "port": port}


def resolve_public_endpoint(endpoint: dict[str, Any], *, allow_private: bool = False) -> list[str]:
    """Resolve once, rejecting the hostname if any selected result is unsafe.

    Callers put one of the returned numeric addresses in Reticulum's interface
    configuration. Reticulum therefore cannot perform a second, unvalidated DNS
    lookup between consent and connection (DNS rebinding).
    """

    checked = validate_endpoint(endpoint, allow_private=allow_private)
    try:
        answers = socket.getaddrinfo(
            checked["host"], checked["port"], type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ValidationError("Remote endpoint could not be resolved") from exc
    addresses: list[str] = []
    for answer in answers:
        candidate = ipaddress.ip_address(answer[4][0]).compressed
        if not allow_private and not address_is_public(candidate):
            raise ValidationError("Remote endpoint DNS includes a non-public address")
        if candidate not in addresses:
            addresses.append(candidate)
    if not addresses:
        raise ValidationError("Remote endpoint did not resolve")
    return addresses[:8]


def _propagation_destination(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.lower():
        raise ValidationError("Propagation-node destination is invalid")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValidationError("Propagation-node destination is invalid") from exc
    if len(raw) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
        raise ValidationError("Propagation-node destination is invalid")
    return value


def _profile_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def create_profile_document(
    label: str,
    endpoints: list[dict[str, Any]],
    *,
    propagation_node: str | None = None,
    now: int | None = None,
    expires_at: int | None = None,
    allow_private: bool = False,
) -> dict[str, Any]:
    created = int(time.time()) if now is None else int(now)
    expiry = created + MAX_PROFILE_LIFETIME_SECONDS if expires_at is None else expires_at
    unsigned = {
        "v": REMOTE_PROFILE_VERSION,
        "label": _normalized_label(label),
        "endpoints": [
            validate_endpoint(item, allow_private=allow_private) for item in endpoints
        ],
        "propagation_node": _propagation_destination(propagation_node),
        "created_at": created,
        "expires_at": expiry,
        "capabilities": [
            "reticulum_tcp",
            *(["lxmf_propagation"] if propagation_node is not None else []),
        ],
    }
    document = {"id": _profile_digest(unsigned), **unsigned}
    return validate_profile_document(document, now=created, allow_private=allow_private)


def validate_profile_document(
    value: Any,
    *,
    now: int | None = None,
    allow_private: bool = False,
) -> dict[str, Any]:
    expected = {
        "v", "id", "label", "endpoints", "propagation_node",
        "created_at", "expires_at", "capabilities",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Remote profile fields are invalid")
    if len(canonical_bytes(value)) > MAX_REMOTE_PROFILE_BYTES:
        raise ValidationError("Remote profile is too large")
    if value["v"] != REMOTE_PROFILE_VERSION:
        raise ValidationError("Remote profile version is unsupported")
    endpoints = value["endpoints"]
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= MAX_REMOTE_ENDPOINTS:
        raise ValidationError("Remote profile must contain one or two endpoints")
    checked_endpoints: list[dict[str, Any]] = []
    for endpoint in endpoints:
        checked = validate_endpoint(endpoint, allow_private=allow_private)
        if checked in checked_endpoints:
            raise ValidationError("Remote profile endpoints must be distinct")
        checked_endpoints.append(checked)
    capabilities = value["capabilities"]
    if (
        not isinstance(capabilities, list)
        or not 1 <= len(capabilities) <= 2
        or any(item not in REMOTE_CAPABILITIES for item in capabilities)
        or len(set(capabilities)) != len(capabilities)
        or capabilities[0] != "reticulum_tcp"
    ):
        raise ValidationError("Remote profile capabilities are invalid")
    propagation = _propagation_destination(value["propagation_node"])
    if (propagation is not None) != ("lxmf_propagation" in capabilities):
        raise ValidationError("Remote profile propagation capability is inconsistent")
    created = value["created_at"]
    expiry = value["expires_at"]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expiry)):
        raise ValidationError("Remote profile dates are invalid")
    current = int(time.time()) if now is None else int(now)
    if created > current + 24 * 60 * 60 or expiry <= created or expiry - created > MAX_PROFILE_LIFETIME_SECONDS:
        raise ValidationError("Remote profile dates are invalid")
    if expiry < current:
        raise InvitationExpired("Remote connection profile has expired")
    unsigned = {
        "v": REMOTE_PROFILE_VERSION,
        "label": _normalized_label(value["label"]),
        "endpoints": checked_endpoints,
        "propagation_node": propagation,
        "created_at": created,
        "expires_at": expiry,
        "capabilities": list(capabilities),
    }
    profile_id = _profile_digest(unsigned)
    if value["id"] != profile_id:
        raise ValidationError("Remote profile ID does not match its canonical content")
    return {"id": profile_id, **unsigned}


def _identity_from_public_key(public_key: bytes) -> RNS.Identity:
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Invitation signer identity is invalid")
    return identity


def _destination(identity: RNS.Identity) -> bytes:
    return RNS.Destination.hash(identity, "lxmf", "delivery")


def _create_envelope(
    identity: RNS.Identity,
    purpose: Literal["personal", "workspace"],
    inner: str,
    profile: dict[str, Any],
    *,
    inner_expires_at: int,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else int(now)
    checked_profile = validate_profile_document(profile, now=current)
    expires = min(inner_expires_at, checked_profile["expires_at"])
    unsigned = {
        "v": REMOTE_ENVELOPE_VERSION,
        "type": "remote_invitation",
        "purpose": purpose,
        "inner": inner,
        "inner_digest": hashlib.sha256(inner.encode("utf-8")).hexdigest(),
        "profile": checked_profile,
        "created_at": current,
        "expires_at": expires,
        "signer_destination": _destination(identity).hex(),
    }
    return canonical_bytes(
        {**unsigned, "signature": _b64encode(identity.sign(canonical_bytes(unsigned)))}
    ).decode("utf-8")


def create_remote_personal_invitation(
    identity: RNS.Identity, inner: str, profile: dict[str, Any], *, now: int | None = None
) -> str:
    invitation = verify_invitation(inner, now=now)
    if invitation.destination_hash != _destination(identity):
        raise IdentityMismatch("Remote invitation signer does not match personal invitation")
    return _create_envelope(
        identity, "personal", invitation.serialized, profile,
        inner_expires_at=invitation.expires_at, now=now,
    )


def create_remote_workspace_invitation(
    identity: RNS.Identity, inner: str, profile: dict[str, Any], *, now: int | None = None
) -> str:
    invitation = verify_workspace_invitation(inner, now=now)
    if invitation.offered_manifest.authority_destination != _destination(identity):
        raise IdentityMismatch("Remote invitation signer is not the workspace authority")
    return _create_envelope(
        identity, "workspace", invitation.serialized, profile,
        inner_expires_at=invitation.expires_at, now=now,
    )


def remote_invitation_formats(serialized: str, purpose: Literal["personal", "workspace"]) -> dict[str, Any]:
    maximum = MAX_REMOTE_PERSONAL_BYTES if purpose == "personal" else MAX_REMOTE_WORKSPACE_BYTES
    if len(serialized.encode("utf-8")) > maximum:
        raise ValidationError("Remote invitation is too large")
    token = _b64encode(serialized.encode("utf-8"))
    if purpose == "personal":
        return {"link": f"meshchat://invite/{token}", "text": f"MESHCHAT2:{token}", "file": serialized}
    return {"link": f"meshchat://workspace/{token}", "text": f"MESHWORKSPACE2:{token}", "value": serialized}


def _extract_envelope(raw: str, purpose: Literal["personal", "workspace"]) -> str | None:
    if not isinstance(raw, str):
        raise ValidationError("Remote invitation is invalid")
    value = raw.translate(_INVISIBLE).strip()
    maximum = MAX_REMOTE_PERSONAL_BYTES if purpose == "personal" else MAX_REMOTE_WORKSPACE_BYTES
    if not value or len(value.encode("utf-8")) > maximum * 2:
        raise ValidationError("Remote invitation is empty or too large")
    compact = "".join(value.split())
    lower = compact.lower()
    text_prefix = "meshchat2:" if purpose == "personal" else "meshworkspace2:"
    link_host = "invite" if purpose == "personal" else "workspace"
    if lower.startswith(text_prefix):
        return _b64decode(compact[len(text_prefix):], "Remote invitation token", maximum=maximum).decode("utf-8")
    if lower.startswith(f"meshchat://{link_host}/"):
        parsed = urlsplit(compact)
        if parsed.scheme != "meshchat" or parsed.netloc != link_host or parsed.query or parsed.fragment or not parsed.path.startswith("/") or "/" in parsed.path[1:]:
            raise ValidationError("Remote invitation link is invalid")
        decoded = _b64decode(parsed.path[1:], "Remote invitation token", maximum=maximum).decode("utf-8")
        try:
            candidate = json.loads(decoded)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(candidate, dict) and candidate.get("v") == 2 else None
    if value.startswith("{"):
        try:
            candidate = json.loads(value)
        except json.JSONDecodeError:
            return None
        return value if isinstance(candidate, dict) and candidate.get("v") == 2 else None
    return None


@dataclass(frozen=True, slots=True)
class VerifiedRemoteInvitation:
    purpose: Literal["personal", "workspace"]
    inner: str
    profile: dict[str, Any]
    created_at: int
    expires_at: int


def verify_remote_invitation(
    raw: str, purpose: Literal["personal", "workspace"], *, now: int | None = None
) -> VerifiedRemoteInvitation | None:
    serialized = _extract_envelope(raw, purpose)
    if serialized is None:
        return None
    maximum = MAX_REMOTE_PERSONAL_BYTES if purpose == "personal" else MAX_REMOTE_WORKSPACE_BYTES
    if len(serialized.encode("utf-8")) > maximum:
        raise ValidationError("Remote invitation is too large")
    try:
        value = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValidationError("Remote invitation encoding is invalid") from exc
    expected = {
        "v", "type", "purpose", "inner", "inner_digest", "profile",
        "created_at", "expires_at", "signer_destination", "signature",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError("Remote invitation fields are invalid")
    if value["v"] != REMOTE_ENVELOPE_VERSION or value["type"] != "remote_invitation" or value["purpose"] != purpose:
        raise ValidationError("Remote invitation version or purpose is unsupported")
    current = int(time.time()) if now is None else int(now)
    profile = validate_profile_document(value["profile"], now=current)
    inner = value["inner"]
    if not isinstance(inner, str) or hashlib.sha256(inner.encode("utf-8")).hexdigest() != value["inner_digest"]:
        raise ValidationError("Remote invitation inner digest is invalid")
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
    expires = value["expires_at"]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (created, expires)) or created > current + 24 * 60 * 60 or expires <= created or expires > inner_expiry or expires > profile["expires_at"]:
        raise ValidationError("Remote invitation dates are invalid")
    if expires < current:
        raise InvitationExpired("Remote invitation has expired")
    if value["signer_destination"] != expected_destination.hex():
        raise IdentityMismatch("Remote invitation signer does not match the inner invitation")
    unsigned = {key: value[key] for key in expected if key != "signature"}
    signature = _b64decode(value["signature"], "Remote invitation signature", maximum=1024)
    if not signer_identity.validate(signature, canonical_bytes(unsigned)):
        raise IdentityMismatch("Remote invitation signature is invalid")
    return VerifiedRemoteInvitation(purpose, inner, profile, created, expires)


def new_profile_record(
    profile: dict[str, Any],
    *,
    origin: str,
    scope_kind: str,
    scope_id: str,
    consented_at: int | None = None,
    allow_private: bool = False,
) -> dict[str, Any]:
    now = int(time.time()) if consented_at is None else int(consented_at)
    checked = validate_profile_document(
        profile, now=now, allow_private=allow_private
    )
    if origin not in REMOTE_ORIGINS or scope_kind not in REMOTE_SCOPE_KINDS or not isinstance(scope_id, str) or not 1 <= len(scope_id) <= 128:
        raise ValidationError("Remote profile origin or scope is invalid")
    return {
        "id": checked["id"],
        "profile": checked,
        "origin": origin,
        "consented_at": now,
        "allow_private": bool(allow_private),
        "scopes": [{"kind": scope_kind, "id": scope_id}],
        "propagation_approved_at": None,
        "resolved_endpoints": [],
        "state": "approved",
        "connected_endpoints": 0,
        "path_available": False,
        "ratchet_ready": False,
        "propagation_available": False,
        "retry_count": 0,
        "next_retry_at": float(now),
        "last_attempt_at": None,
        "last_connected_at": None,
        "last_error": None,
        "created_at": float(now),
        "updated_at": float(now),
    }


def add_profile_scope(record: dict[str, Any], kind: str, scope_id: str) -> dict[str, Any]:
    if kind not in REMOTE_SCOPE_KINDS or not isinstance(scope_id, str) or not 1 <= len(scope_id) <= 128:
        raise ValidationError("Remote profile scope is invalid")
    scopes = list(record.get("scopes", []))
    scope = {"kind": kind, "id": scope_id}
    if scope not in scopes:
        if len(scopes) >= 64:
            raise ValidationError("Remote profile has too many scopes")
        scopes.append(scope)
    record["scopes"] = scopes
    record["updated_at"] = time.time()
    return record


def remove_profile_scope(record: dict[str, Any], kind: str, scope_id: str) -> bool:
    record["scopes"] = [
        item for item in record.get("scopes", [])
        if item != {"kind": kind, "id": scope_id}
    ]
    record["updated_at"] = time.time()
    return not record["scopes"] and record.get("propagation_approved_at") is None


def retry_delay(retry_count: int, *, random_value: float | None = None) -> float:
    jitter = random.random() if random_value is None else max(0.0, min(1.0, random_value))
    base = min(MAX_RETRY_SECONDS, 2 ** max(0, min(retry_count, 12)))
    return min(MAX_RETRY_SECONDS, base * (0.75 + 0.5 * jitter))


def sanitized_profile(record: dict[str, Any]) -> dict[str, Any]:
    profile = record["profile"]
    propagation = profile.get("propagation_node")
    return {
        "id": record["id"],
        "label": profile["label"],
        "origin": record.get("origin", "manual"),
        "expires_at": profile["expires_at"],
        "endpoint_count": len(profile["endpoints"]),
        "connected_endpoint_count": int(record.get("connected_endpoints", 0)),
        "state": record.get("state", "approved"),
        "path_available": bool(record.get("path_available", False)),
        "ratchet_ready": bool(record.get("ratchet_ready", False)),
        "offline_delivery_recommended": propagation is not None,
        "offline_delivery_approved": bool(record.get("propagation_approved_at")),
        "offline_delivery_available": bool(record.get("propagation_available", False)),
        "propagation_identifier": (
            f"{propagation[:8]}…{propagation[-4:]}" if propagation else None
        ),
        "scope_count": len(record.get("scopes", [])),
        "retry_count": int(record.get("retry_count", 0)),
        "last_error": record.get("last_error"),
        "last_connected_at": record.get("last_connected_at"),
        "capabilities": list(profile.get("capabilities", [])),
        "allow_private": bool(record.get("allow_private", False)),
    }
