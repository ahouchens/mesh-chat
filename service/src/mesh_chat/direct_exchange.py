"""Pure signed Answer/Ready chaining. No persistence, timers or network effects.

All authorities and previous replay records are protected caller inputs. A valid
chain neither starts a monotonic attempt window nor proves the native engine
still owns the Answer's socket. Acceptance must recheck both before activation.
"""
from __future__ import annotations

import hashlib

from .direct_binding import MAX_BYTES, AcceptedBinding, _hex, _parse, verify_binding
from .direct_offer import verify_offer
from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import _identity_from_public_key, _sign, _verify_signature


def _digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _create(identity, kind, binding_raw, parent_raw, parent_type):
    binding, parent = _parse(binding_raw), _parse(parent_raw)
    if binding.get("issuer_public_identity") != identity.get_public_key().hex():
        raise IdentityMismatch("Direct response signer does not own its binding")
    if binding.get("type") != "direct_binding" or parent.get("type") != parent_type:
        raise ValidationError("Direct response document purpose is invalid")
    if (type(binding.get("v")) is not int or binding["v"] not in (1, 2)
            or type(parent.get("v")) is not int or binding["v"] != parent["v"]):
        raise ValidationError("Direct response versions must match")
    return _sign(identity, {"v": binding["v"], "type": kind, "parent_digest": _digest(parent_raw),
                           "binding": binding}, maximum=MAX_BYTES)


def create_answer(identity, binding_raw, offer_raw):
    """Wrap signed public binding material; receivers still verify the full chain."""
    return _create(identity, "direct_answer", binding_raw, offer_raw, "direct_offer")


def create_ready(identity, binding_raw, answer_raw):
    return _create(identity, "direct_ready", binding_raw, answer_raw, "direct_answer")


def _verify(raw, kind, parent_raw, authority, certificate_der, now, previous):
    value = _parse(raw)
    if (set(value) != {"v", "type", "parent_digest", "binding", "signature"}
            or type(value["v"]) is not int or value["v"] not in (1, 2) or value["type"] != kind
            or not isinstance(value["binding"], dict)):
        raise ValidationError("Direct response fields are invalid")
    if value["v"] != value["binding"].get("v") or value["v"] != _parse(parent_raw).get("v"):
        raise ValidationError("Direct response versions must match")
    if _hex(value["parent_digest"], 32).hex() != _digest(parent_raw):
        raise IdentityMismatch("Direct response references a different document")
    binding_raw = canonical_bytes(value["binding"]).decode("utf-8")
    accepted = verify_binding(binding_raw, authority, certificate_der, now=now)
    _verify_signature(_identity_from_public_key(authority.issuer_public_identity), value, "Direct response")
    result = AcceptedBinding(accepted.generation, _digest(raw))
    if previous is not None and (result.generation < previous.generation
            or (result.generation == previous.generation and result.digest != previous.digest)):
        raise ValidationError("Direct response generation is stale or conflicting")
    return result, value["binding"]


def _same_scope_and_window(binding, parent):
    if (canonical_bytes(binding["scope"]) != canonical_bytes(parent["scope"])
            or binding["challenge"] != parent["challenge"]
            or binding["issued_at"] < parent["issued_at"]
            or binding["expires_at"] > parent["expires_at"]):
        raise IdentityMismatch("Direct response scope, challenge or validity differs from its parent")


def verify_answer(raw, authority, certificate_der, *, offer_raw, offer_authority,
                  offer_certificate_der, now, previous=None):
    verify_offer(offer_raw, offer_authority, offer_certificate_der, now=now)
    offer = _parse(offer_raw)
    accepted, binding = _verify(raw, "direct_answer", offer_raw, authority, certificate_der, now, previous)
    _same_scope_and_window(binding, offer)
    if (binding["audience_destination"] != offer["issuer_destination"]
            or binding["issuer_destination"] == offer["issuer_destination"]):
        raise IdentityMismatch("Direct Answer does not address the invitation authority")
    return accepted


def verify_ready(raw, authority, certificate_der, *, answer_raw, answer_authority,
                 answer_certificate_der, offer_raw, offer_authority,
                 offer_certificate_der, now, previous=None):
    verify_answer(answer_raw, answer_authority, answer_certificate_der, offer_raw=offer_raw,
                  offer_authority=offer_authority, offer_certificate_der=offer_certificate_der, now=now)
    answer, offer = _parse(answer_raw)["binding"], _parse(offer_raw)
    accepted, binding = _verify(raw, "direct_ready", answer_raw, authority, certificate_der, now, previous)
    _same_scope_and_window(binding, answer)
    if (binding["issuer_public_identity"] != offer["issuer_public_identity"]
            or binding["audience_destination"] != answer["issuer_destination"]
            or binding["generation"] <= offer["generation"]):
        raise IdentityMismatch("Direct Ready does not bind the selected peer and fresh owner generation")
    return accepted
