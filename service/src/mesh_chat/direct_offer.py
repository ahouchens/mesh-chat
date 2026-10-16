"""Pure initial direct Offer codec; no import command, sockets or admission.

The protected caller obtains authority from a separately verified invitation.
An Offer has no audience: only a later audience-bound response can select a peer.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import RNS

from .direct_binding import (
    ALPN, MAX_BYTES, AcceptedBinding, _hex, _parse, _scope, _verify_transport_fields,
)
from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import _destination_for, _identity_from_public_key, _sign, _verify_signature


@dataclass(frozen=True)
class OfferAuthority:
    issuer_public_identity: bytes
    scope: dict[str, Any]
    expires_at: int
    challenge: bytes


def verify_offer(raw: str, authority: OfferAuthority, certificate_der: bytes,
                 *, now: int, previous: AcceptedBinding | None = None) -> AcceptedBinding:
    """Validate only against independently verified invitation/negotiation state.

    Returned generation/digest are evidence, not durable acceptance or a path.
    A caller previewing the first Offer may learn its challenge, but must not
    derive issuer authority or invitation scope from this document.
    """
    value = _parse(raw)
    if set(value) != {"v", "type", "scope", "issuer_public_identity", "issuer_destination",
                      "certificate_sha256", "alpn", "session_id", "challenge", "generation",
                      "candidates", "issued_at", "expires_at", "signature"}:
        raise ValidationError("Direct Offer fields are invalid")
    if type(value["v"]) is not int or value["v"] != 1 or value["type"] != "direct_offer":
        raise ValidationError("Direct Offer version or purpose is invalid")
    _scope(value["scope"])
    _scope(authority.scope)
    if (authority.scope["kind"] != "invitation"
            or canonical_bytes(value["scope"]) != canonical_bytes(authority.scope)):
        raise IdentityMismatch("Direct Offer does not match the invitation")
    identity = _identity_from_public_key(authority.issuer_public_identity)
    if (_hex(value["issuer_public_identity"], 64) != authority.issuer_public_identity
            or _hex(value["issuer_destination"], 16) != _destination_for(identity)):
        raise IdentityMismatch("Direct Offer signer does not match invitation authority")
    _verify_transport_fields(value, authority, certificate_der, now=now)
    _verify_signature(identity, value, "Direct Offer")
    accepted = AcceptedBinding(value["generation"], hashlib.sha256(raw.encode("utf-8")).hexdigest())
    if previous is not None and (accepted.generation < previous.generation
            or (accepted.generation == previous.generation and accepted.digest != previous.digest)):
        raise ValidationError("Direct Offer generation is stale or conflicting")
    return accepted


def create_offer(identity: RNS.Identity, authority: OfferAuthority, certificate_der: bytes,
                 *, session_id: str, generation: int, candidates: list[dict[str, Any]],
                 issued_at: int, expires_at: int) -> str:
    if identity.get_public_key() != authority.issuer_public_identity:
        raise IdentityMismatch("Direct Offer signer does not match invitation authority")
    raw = _sign(identity, {
        "v": 1, "type": "direct_offer", "scope": authority.scope,
        "issuer_public_identity": identity.get_public_key().hex(),
        "issuer_destination": _destination_for(identity).hex(),
        "certificate_sha256": hashlib.sha256(certificate_der).hexdigest(), "alpn": ALPN,
        "session_id": session_id, "challenge": authority.challenge.hex(), "generation": generation,
        "candidates": candidates, "issued_at": issued_at, "expires_at": expires_at,
    }, maximum=MAX_BYTES)
    verify_offer(raw, authority, certificate_der, now=issued_at)
    return raw
