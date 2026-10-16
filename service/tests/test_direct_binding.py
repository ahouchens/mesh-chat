import json
import uuid
from dataclasses import replace

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, create_binding, verify_binding
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.workspace_protocol import _destination_for, _sign


@pytest.fixture
def binding():
    issuer, audience = RNS.Identity(), RNS.Identity()
    authority = BindingAuthority(issuer.get_public_key(), _destination_for(audience), {
        "kind": "invitation", "digest": "ab" * 32, "expires_at": 3000,
    }, 3000, b"c" * 32)
    certificate = b"opaque native certificate bytes; TLS validates DER separately"
    raw = create_binding(issuer, authority, certificate,
                         session_id=str(uuid.uuid4()), challenge=b"c" * 32,
                         generation=1, candidates=[{
                             "host": "8.8.8.8", "port": 12345, "expires_at": 2500,
                         }], issued_at=1000, expires_at=2000)
    return issuer, authority, certificate, raw


def resign(issuer, raw, **fields):
    value = json.loads(raw)
    value.pop("signature")
    return _sign(issuer, {**value, **fields})


def test_binding_rotation_replay_and_conflict(binding):
    issuer, authority, cert, raw = binding
    first = verify_binding(raw, authority, cert, now=1000)
    assert verify_binding(raw, authority, cert, now=1100, previous=first) == first
    conflicting = resign(issuer, raw, session_id=str(uuid.uuid4()))
    with pytest.raises(ValidationError):
        verify_binding(conflicting, authority, cert, now=1100, previous=first)
    second_raw = resign(issuer, conflicting, generation=2)
    second = verify_binding(second_raw, authority, cert, now=1100, previous=first)
    with pytest.raises(ValidationError):
        verify_binding(raw, authority, cert, now=1100, previous=second)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 2), ("type", "workspace_join"), ("generation", True),
    ("generation", 0), ("generation", 2**63), ("issued_at", 1101),
    ("expires_at", 1000), ("expires_at", 3001), ("alpn", "h3"),
    ("challenge", "ab"), ("challenge", "ab" * 32), ("session_id", "bad"), ("unknown", "extra"),
    ("issuer_destination", "00" * 16), ("issuer_public_identity", "00" * 64),
    ("audience_destination", "00" * 16), ("certificate_sha256", "00" * 32),
    ("scope", {"kind": "invitation", "digest": "cd" * 32, "expires_at": 3000}),
    ("candidates", []),
])
def test_even_signed_invalid_fields_are_rejected(binding, field, value):
    issuer, authority, cert, raw = binding
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_binding(resign(issuer, raw, **{field: value}), authority, cert, now=1100)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.1", "100.64.0.1",
                                   "::", "::1", "ff02::1", "fe80::1%eth0", "8.008.8.8"])
def test_unusable_or_non_numeric_candidates_rejected(binding, host):
    issuer, authority, cert, raw = binding
    candidate = {"host": host, "port": 12345, "expires_at": 2500}
    with pytest.raises(ValidationError):
        verify_binding(resign(issuer, raw, candidates=[candidate]), authority, cert, now=1100)


def test_candidate_budgets_and_lease(binding):
    issuer, authority, cert, raw = binding
    candidate = json.loads(raw)["candidates"][0]
    for candidates in ([candidate] * 9, [candidate] * 2,
                       [{**candidate, "port": True}], [{**candidate, "expires_at": 1999}]):
        with pytest.raises(ValidationError):
            verify_binding(resign(issuer, raw, candidates=candidates), authority, cert, now=1100)


def test_untrusted_signer_certificate_expiry_and_local_revocation(binding):
    _, authority, cert, raw = binding
    with pytest.raises(IdentityMismatch):
        verify_binding(resign(RNS.Identity(), raw), authority, cert, now=1100)
    with pytest.raises(IdentityMismatch):
        verify_binding(raw, authority, cert + b"different", now=1100)
    for now in (999, 2000):
        with pytest.raises(ValidationError):
            verify_binding(raw, authority, cert, now=now)
    with pytest.raises(ValidationError):
        verify_binding(raw, replace(authority, expires_at=1099), cert, now=1100)


def test_parser_bounds_before_signature(binding):
    _, authority, cert, raw = binding
    for invalid in (" " + raw, raw[:-1] + ',"v":1}', "[" * 10000,
                    '{"x":' * 9 + "0" + "}" * 9,
                    raw.replace('"v":1', '"v":1.0'), raw.replace('"v":1', '"v":NaN'),
                    "x" * 16385, '"\\ud800"'):
        with pytest.raises(ValidationError):
            verify_binding(invalid, authority, cert, now=1100)


def test_workspace_scope_must_match_exact_local_devices(binding):
    issuer, authority, cert, raw = binding
    scope = {"kind": "workspace", "workspace_id": str(uuid.uuid4()),
             "issuer_device_id": str(uuid.uuid4()), "audience_device_id": str(uuid.uuid4())}
    local = replace(authority, scope=scope)
    scoped = resign(issuer, raw, scope=scope)
    assert verify_binding(scoped, local, cert, now=1100).generation == 1
    changed = {**scope, "audience_device_id": str(uuid.uuid4())}
    with pytest.raises(IdentityMismatch):
        verify_binding(resign(issuer, scoped, scope=changed), local, cert, now=1100)


def test_certificate_rotation_requires_new_signed_binding(binding):
    issuer, authority, cert, raw = binding
    first = verify_binding(raw, authority, cert, now=1100)
    import hashlib
    rotated_cert = b"new native session certificate"
    rotated = resign(issuer, raw, certificate_sha256=hashlib.sha256(rotated_cert).hexdigest(), generation=2)
    assert verify_binding(rotated, authority, rotated_cert, now=1100, previous=first).generation == 2


def test_cross_language_helper_returns_only_verified_public_pins(capsys):
    from tools.direct_binding_proof import authorize
    authorize([b"certificate-a", b"certificate-b"])
    assert capsys.readouterr().out.splitlines() == [
        b"certificate-a".hex(), b"certificate-b".hex(),
    ]
