from __future__ import annotations

import uuid

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.remote import create_profile_document
from mesh_chat.workspace_access import (
    WORKSPACE_ACCESS_PREFIX,
    create_workspace_access_recommendation,
    verify_workspace_access_recommendation,
)

NOW = 1_800_000_000
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
DIGEST = "ab" * 32


def _profile() -> dict:
    return create_profile_document(
        "Workspace relay", [{"host": "93.184.216.34", "port": 4242}], now=NOW
    )


def test_workspace_access_recommendation_round_trip() -> None:
    identity = RNS.Identity()
    raw = create_workspace_access_recommendation(
        identity,
        workspace_id=WORKSPACE_ID,
        manifest_digest=DIGEST,
        profile=_profile(),
        now=NOW,
    )
    assert raw.startswith(WORKSPACE_ACCESS_PREFIX)
    checked = verify_workspace_access_recommendation(raw, now=NOW)
    assert checked.workspace_id == WORKSPACE_ID
    assert checked.manifest_digest == DIGEST
    assert checked.profile["label"] == "Workspace relay"
    assert checked.expires_at == NOW + 7 * 24 * 60 * 60
    assert checked.authority_destination == RNS.Destination.hash(
        identity, "lxmf", "delivery"
    ).hex()


def test_workspace_access_recommendation_fails_closed() -> None:
    identity = RNS.Identity()
    raw = create_workspace_access_recommendation(
        identity,
        workspace_id=WORKSPACE_ID,
        manifest_digest=DIGEST,
        profile=_profile(),
        now=NOW,
        lifetime_seconds=60,
    )
    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_workspace_access_recommendation(raw[:-2] + "AA", now=NOW)
    with pytest.raises(InvitationExpired):
        verify_workspace_access_recommendation(raw, now=NOW + 61)
    with pytest.raises(ValidationError):
        create_workspace_access_recommendation(
            identity,
            workspace_id="not-a-uuid",
            manifest_digest=DIGEST,
            profile=_profile(),
            now=NOW,
        )
    with pytest.raises(ValidationError):
        create_workspace_access_recommendation(
            identity,
            workspace_id=WORKSPACE_ID,
            manifest_digest="zz" * 32,
            profile=_profile(),
            now=NOW,
        )
    with pytest.raises(ValidationError):
        create_workspace_access_recommendation(
            identity,
            workspace_id=WORKSPACE_ID,
            manifest_digest=DIGEST,
            profile=_profile(),
            now=NOW,
            lifetime_seconds=31 * 24 * 60 * 60,
        )


def test_workspace_access_recommendation_rejects_another_signer() -> None:
    raw = create_workspace_access_recommendation(
        RNS.Identity(),
        workspace_id=WORKSPACE_ID,
        manifest_digest=DIGEST,
        profile=_profile(),
        now=NOW,
    )
    checked = verify_workspace_access_recommendation(raw, now=NOW)
    assert checked.authority_destination != RNS.Destination.hash(
        RNS.Identity(), "lxmf", "delivery"
    ).hex()
    assert uuid.UUID(checked.workspace_id) == uuid.UUID(WORKSPACE_ID)
