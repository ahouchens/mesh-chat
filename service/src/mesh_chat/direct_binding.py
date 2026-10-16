"""Phase-1 direct transport binding proof; not registered as an app command.

The caller supplies locally verified authorization, never authority taken from
the incoming document. Verification is pure; acceptance wraps it in a vault
transaction with an authorization reload and durable replay protection. Runtime
activation still requires lifecycle checks. A binding authorizes a transport
key, not workspace admission.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from typing import Any, Callable

import RNS

from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .vault import VaultStore
from .workspace_protocol import (
    _destination_for, _identity_from_public_key, _sign, _validate_uuid,
    _verify_signature,
)

MAX_BYTES = 16 * 1024
ALPN = "mesh-direct-proof/1"
MAX_GENERATION = (1 << 63) - 1


@dataclass(frozen=True)
class BindingAuthority:
    """Snapshot of local authorization; recheck it when committing acceptance."""

    issuer_public_identity: bytes
    audience_destination: bytes
    scope: dict[str, Any]
    expires_at: int
    challenge: bytes


@dataclass(frozen=True)
class AcceptedBinding:
    generation: int
    digest: str


def accept_binding(
    store: VaultStore, raw: str, expected: BindingAuthority, certificate_der: bytes,
    *, load_authority: Callable[[], BindingAuthority], clock: Callable[[], int],
) -> AcceptedBinding:
    """Commit replay protection with current local authorization, without network I/O.

    The protected caller loads authority from vault records in the callback,
    rejecting revoked/removed scopes. It must not reuse a cached snapshot or
    trust document fields. This is durable acceptance, not an activation token:
    a later runtime activation still needs lifecycle/revocation reconciliation.
    Expired records must be retained so rotation cannot reset replay protection.
    """
    def relationship(authority):
        return canonical_bytes({
            "issuer": authority.issuer_public_identity.hex(),
            "audience": authority.audience_destination.hex(),
            "scope": authority.scope,
        }).decode("utf-8")

    expected_relationship = relationship(expected)
    record_id = store.opaque_id("direct-binding", expected_relationship)

    def update(previous):
        current = load_authority()
        if relationship(current) != expected_relationship:
            raise IdentityMismatch("Direct binding authorization changed")
        accepted = verify_binding(
            raw, current, certificate_der, now=clock(),
            previous=AcceptedBinding(**previous) if previous is not None else None,
        )
        return {"generation": accepted.generation, "digest": accepted.digest}

    return AcceptedBinding(**store.update_record("direct_binding", record_id, update))


def _fail(message: str = "Direct binding is invalid") -> None:
    raise ValidationError(message)


def _hex(value: Any, size: int) -> bytes:
    if not isinstance(value, str) or len(value) != size * 2:
        _fail()
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        _fail()
    if decoded.hex() != value:
        _fail()
    return decoded


def _integer(value: Any, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()


def _scope(value: Any) -> None:
    if not isinstance(value, dict):
        _fail()
    if value.get("kind") == "invitation":
        if set(value) != {"kind", "digest", "expires_at"}:
            _fail()
        _hex(value["digest"], 32)
        _integer(value["expires_at"], 1, MAX_GENERATION)
    elif value.get("kind") == "workspace":
        if set(value) != {"kind", "workspace_id", "issuer_device_id", "audience_device_id"}:
            _fail()
        for key in ("workspace_id", "issuer_device_id", "audience_device_id"):
            _validate_uuid(value[key], key)
    else:
        _fail()


def _parse(raw: str) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("Duplicate direct binding field")
            result[key] = value
        return result

    def invalid_number(_value):
        _fail("Non-integer direct binding number")

    if not isinstance(raw, str):
        _fail()
    try:
        if not 0 < len(raw.encode("utf-8")) <= MAX_BYTES:
            _fail()
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_float=invalid_number, parse_constant=invalid_number)
        def depth(item, level=1):
            if level > 8:
                _fail("Direct binding nesting is too deep")
            if isinstance(item, dict):
                for child in item.values():
                    depth(child, level + 1)
            elif isinstance(item, list):
                for child in item:
                    depth(child, level + 1)
        depth(value)
        if not isinstance(value, dict) or canonical_bytes(value).decode("utf-8") != raw:
            _fail("Direct binding encoding is not canonical")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Direct binding encoding is invalid") from exc


def verify_binding(
    raw: str, authority: BindingAuthority, certificate_der: bytes,
    *, now: int, previous: AcceptedBinding | None = None,
) -> AcceptedBinding:
    """Validate against THIS peer's authorization and actual TLS certificate.

    `previous` must be loaded for this exact issuer/audience/scope, including
    expired sessions. Do not reset the generation when a certificate rotates.
    """
    value = _parse(raw)
    if set(value) != {
        "v", "type", "scope", "issuer_public_identity", "issuer_destination",
        "audience_destination", "certificate_sha256", "alpn", "session_id",
        "challenge", "generation", "candidates", "issued_at", "expires_at", "signature",
    }:
        _fail()
    if type(value["v"]) is not int or value["v"] != 1 or value["type"] != "direct_binding":
        _fail()
    _scope(value["scope"])
    _scope(authority.scope)
    # Canonical bytes avoid Python's bool/int equality in nested scopes.
    if canonical_bytes(value["scope"]) != canonical_bytes(authority.scope):
        raise IdentityMismatch("Direct binding scope does not match authorization")
    identity = _identity_from_public_key(authority.issuer_public_identity)
    if (
        _hex(value["issuer_public_identity"], 64) != authority.issuer_public_identity
        or _hex(value["issuer_destination"], 16) != _destination_for(identity)
        or _hex(value["audience_destination"], 16) != authority.audience_destination
    ):
        raise IdentityMismatch("Direct binding peer does not match authorization")
    if not isinstance(certificate_der, bytes) or not 1 <= len(certificate_der) <= MAX_BYTES:
        _fail("Transport certificate size is invalid")
    if _hex(value["certificate_sha256"], 32) != hashlib.sha256(certificate_der).digest():
        raise IdentityMismatch("Direct binding transport certificate does not match")
    if value["alpn"] != ALPN:
        _fail("Direct binding ALPN is incompatible")
    _validate_uuid(value["session_id"], "Direct session ID")
    if _hex(value["challenge"], 32) != authority.challenge:
        raise IdentityMismatch("Direct binding challenge does not match negotiation")
    _integer(value["generation"], 1, MAX_GENERATION)
    _integer(value["issued_at"], 0, MAX_GENERATION)
    _integer(value["expires_at"], 1, MAX_GENERATION)
    issued, expiry = value["issued_at"], value["expires_at"]
    if not issued <= now < expiry <= min(issued + 3600, authority.expires_at):
        _fail("Direct binding validity has expired or is not active")
    if value["scope"]["kind"] == "invitation" and expiry > value["scope"]["expires_at"]:
        _fail("Direct binding exceeds invitation validity")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
        _fail("Direct candidate count is invalid")
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"host", "port", "expires_at"}:
            _fail()
        host = candidate["host"]
        if not isinstance(host, str) or "%" in host:
            _fail()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            _fail("Direct candidate must be a numeric address")
        if str(address) != host or not address.is_global or address.is_multicast:
            _fail("Direct candidate must be a canonical global address")
        _integer(candidate["port"], 1, 65535)
        _integer(candidate["expires_at"], expiry, authority.expires_at)
        endpoint = (host, candidate["port"])
        if endpoint in seen:
            _fail("Duplicate direct candidate")
        seen.add(endpoint)
    _verify_signature(identity, value, "Direct binding")
    accepted = AcceptedBinding(value["generation"], hashlib.sha256(raw.encode("utf-8")).hexdigest())
    if previous is not None and (
        accepted.generation < previous.generation
        or (accepted.generation == previous.generation and accepted.digest != previous.digest)
    ):
        _fail("Direct binding generation is stale or conflicting")
    return accepted


def create_binding(identity: RNS.Identity, authority: BindingAuthority,
                   certificate_der: bytes, *, session_id: str, challenge: bytes,
                   generation: int, candidates: list[dict[str, Any]],
                   issued_at: int, expires_at: int) -> str:
    """Sign public native session material without exporting the RNS private key."""
    if identity.get_public_key() != authority.issuer_public_identity:
        raise IdentityMismatch("Direct binding signer does not match authorization")
    raw = _sign(identity, {
        "v": 1, "type": "direct_binding", "scope": authority.scope,
        "issuer_public_identity": identity.get_public_key().hex(),
        "issuer_destination": _destination_for(identity).hex(),
        "audience_destination": authority.audience_destination.hex(),
        "certificate_sha256": hashlib.sha256(certificate_der).hexdigest(),
        "alpn": ALPN, "session_id": session_id, "challenge": challenge.hex(),
        "generation": generation, "candidates": candidates,
        "issued_at": issued_at, "expires_at": expires_at,
    }, maximum=MAX_BYTES)
    verify_binding(raw, authority, certificate_der, now=issued_at)
    return raw
