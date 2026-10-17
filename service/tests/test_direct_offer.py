import json
import uuid
from dataclasses import replace

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, verify_binding
from mesh_chat.direct_offer import OfferAuthority, create_offer, verify_offer
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.workspace_protocol import _sign


@pytest.fixture
def offer():
    identity = RNS.Identity()
    authority = OfferAuthority(identity.get_public_key(), {
        "kind": "invitation", "digest": "ab" * 32, "expires_at": 3000,
    }, 2000, b"c" * 32)
    cert = b"native public certificate"
    raw = create_offer(identity, authority, cert, session_id=str(uuid.uuid4()), generation=1,
        candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": 2000}],
        issued_at=1000, expires_at=1500)
    return identity, authority, cert, raw


def resign(identity, raw, **changes):
    value = json.loads(raw)
    value.pop("signature")
    return _sign(identity, {**value, **changes})


def test_offer_is_unbound_and_cannot_be_used_as_a_binding(offer):
    _, authority, cert, raw = offer
    assert "audience_destination" not in json.loads(raw)
    assert verify_offer(raw, authority, cert, now=1100).generation == 1
    with pytest.raises(ValidationError):
        verify_binding(raw, BindingAuthority(authority.issuer_public_identity, b"a" * 16,
                       authority.scope, authority.expires_at, authority.challenge), cert, now=1100)


def test_offer_generation_rotation_and_identical_replay(offer):
    identity, authority, cert, raw = offer
    first = verify_offer(raw, authority, cert, now=1100)
    assert verify_offer(raw, authority, cert, now=1100, previous=first) == first
    with pytest.raises(ValidationError):
        verify_offer(resign(identity, raw, session_id=str(uuid.uuid4())), authority, cert,
                     now=1100, previous=first)
    second = verify_offer(resign(identity, raw, generation=2), authority, cert, now=1100, previous=first)
    with pytest.raises(ValidationError):
        verify_offer(raw, authority, cert, now=1100, previous=second)


@pytest.mark.parametrize("changes", [
    {"v": True}, {"v": 3}, {"type": "direct_binding"}, {"audience_destination": "aa" * 16},
    {"generation": True}, {"generation": 0}, {"generation": 2**63},
    {"issued_at": 1200}, {"expires_at": 1100}, {"expires_at": 2001},
    {"alpn": "h3"}, {"session_id": "bad"}, {"challenge": "ab" * 32},
    {"issuer_destination": "ab" * 16}, {"certificate_sha256": "ab" * 32},
    {"candidates": []}, {"candidates": [{"host": "127.0.0.1", "port": 1, "expires_at": 2000}]},
    {"scope": {"kind": "invitation", "digest": "cd" * 32, "expires_at": 3000}},
])
def test_signed_invalid_offers_are_rejected(offer, changes):
    identity, authority, cert, raw = offer
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_offer(resign(identity, raw, **changes), authority, cert, now=1100)


def test_offer_cannot_supply_its_own_authority_or_certificate(offer):
    _, authority, cert, raw = offer
    with pytest.raises(IdentityMismatch):
        verify_offer(raw, replace(authority, issuer_public_identity=RNS.Identity().get_public_key()), cert, now=1100)
    with pytest.raises(IdentityMismatch):
        verify_offer(raw, authority, b"substitute certificate", now=1100)
    with pytest.raises(ValidationError):
        verify_offer(raw, replace(authority, expires_at=1001), cert, now=1100)
    with pytest.raises(IdentityMismatch):
        verify_offer(resign(RNS.Identity(), raw), authority, cert, now=1100)


@pytest.mark.parametrize("transform", [
    lambda raw: " " + raw,
    lambda raw: raw.replace('"v":1', '"v":1,"v":1'),
    lambda raw: raw.replace('"v":1', '"v":1.0'),
    lambda raw: raw + " " * 16384,
    lambda raw: '{"nested":' + '[' * 10 + '0' + ']' * 10 + '}',
])
def test_offer_parser_is_bounded_and_canonical(offer, transform):
    _, authority, cert, raw = offer
    with pytest.raises(ValidationError):
        verify_offer(transform(raw), authority, cert, now=1100)
