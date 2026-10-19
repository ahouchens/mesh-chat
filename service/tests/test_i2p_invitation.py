from __future__ import annotations

import time

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.i2p_invitation import (
    create_i2p_invitation,
    i2p_invitation_formats,
    verify_i2p_invitation,
)
from mesh_chat.invitations import create_invitation

B32 = "a" * 52 + ".b32.i2p"


def _personal(identity: RNS.Identity, lifetime_seconds: int = 3600) -> str:
    return create_invitation(identity, "Owner", lifetime_seconds=lifetime_seconds)["file"]


def test_i2p_wrapper_binds_the_inner_owner_and_access_point() -> None:
    identity = RNS.Identity()
    now = int(time.time())
    inner = _personal(identity)
    wrapped = create_i2p_invitation(
        identity, inner, "personal", B32, label="Community relay", expires_at=now + 1800, now=now
    )
    verified = verify_i2p_invitation(wrapped, "personal", now=now)
    assert verified is not None
    assert verified.inner == inner
    assert verified.access_point["b32"] == B32
    assert verified.access_point["label"] == "Community relay"
    assert verified.expires_at == now + 1800
    assert i2p_invitation_formats(wrapped, "personal")["text"].startswith("MESHI2P1:")


def test_i2p_wrapper_rejects_a_different_purpose() -> None:
    identity = RNS.Identity()
    now = int(time.time())
    wrapped = create_i2p_invitation(
        identity, _personal(identity), "personal", B32, expires_at=now + 1800, now=now
    )
    with pytest.raises(ValidationError):
        verify_i2p_invitation(wrapped, "workspace", now=now)


def test_i2p_wrapper_rejects_a_tampered_access_point() -> None:
    identity = RNS.Identity()
    now = int(time.time())
    wrapped = create_i2p_invitation(
        identity, _personal(identity), "personal", B32, expires_at=now + 1800, now=now
    )
    tampered = wrapped.replace(B32, "b" * 52 + ".b32.i2p")
    with pytest.raises((ValidationError, IdentityMismatch)):
        verify_i2p_invitation(tampered, "personal", now=now)


def test_i2p_wrapper_rejects_an_expired_descriptor() -> None:
    identity = RNS.Identity()
    now = int(time.time())
    wrapped = create_i2p_invitation(
        identity, _personal(identity), "personal", B32, expires_at=now + 10, now=now
    )
    with pytest.raises(InvitationExpired):
        verify_i2p_invitation(wrapped, "personal", now=now + 60)


def test_i2p_wrapper_rejects_a_foreign_signer() -> None:
    owner = RNS.Identity()
    attacker = RNS.Identity()
    now = int(time.time())
    wrapped = create_i2p_invitation(
        attacker, _personal(owner), "personal", B32, expires_at=now + 1800, now=now
    )
    with pytest.raises(IdentityMismatch):
        verify_i2p_invitation(wrapped, "personal", now=now)

