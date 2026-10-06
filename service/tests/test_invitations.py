from __future__ import annotations

import json

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import create_invitation, verify_invitation


def test_invitation_round_trip_all_entry_formats() -> None:
    identity = RNS.Identity()
    formats = create_invitation(
        identity,
        "Alex Rivera",
        hints=[{"type": "tcp", "host": "192.0.2.4", "port": 4242}],
        now=1_800_000_000,
    )
    assert formats["expires_at"] == 1_802_592_000
    for raw in (formats["link"], formats["text"], formats["file"]):
        invitation = verify_invitation(raw, now=1_800_000_100)
        assert invitation.display_name == "Alex Rivera"
        assert invitation.public_identity == identity.get_public_key()
        assert invitation.destination_hash == RNS.Destination.hash(
            identity, "lxmf", "delivery"
        )
        assert invitation.hints[0]["port"] == 4242
        assert len(invitation.fingerprint.split()) == 16


def test_invitation_accepts_phone_clipboard_formatting() -> None:
    encoded = create_invitation(RNS.Identity(), "Alex", now=1_800_000_000)["text"]
    prefix, token = encoded.split(":", 1)
    wrapped = f"\ufeff{prefix}: \n{token[:120]}\n{token[120:]}\u200b"
    invitation = verify_invitation(wrapped, now=1_800_000_100)
    assert invitation.display_name == "Alex"


def test_invitation_accepts_one_token_inside_shared_text() -> None:
    link = create_invitation(RNS.Identity(), "Alex", now=1_800_000_000)["link"]
    invitation = verify_invitation(f"Here is my Mesh Chat invite: {link}\n", now=1_800_000_100)
    assert invitation.display_name == "Alex"


def test_rejects_changed_destination_even_with_valid_shape() -> None:
    identity = RNS.Identity()
    encoded = create_invitation(identity, "Alex", now=1_800_000_000)["file"]
    value = json.loads(encoded)
    value["destination"] = "00" * 16
    with pytest.raises(IdentityMismatch):
        verify_invitation(json.dumps(value), now=1_800_000_100)


def test_rejects_tampered_signed_label() -> None:
    identity = RNS.Identity()
    value = json.loads(create_invitation(identity, "Alex", now=1_800_000_000)["file"])
    value["label"] = "Mallory"
    with pytest.raises(IdentityMismatch):
        verify_invitation(json.dumps(value), now=1_800_000_100)


@pytest.mark.parametrize(
    "hint",
    [
        {"type": "http", "host": "example.com", "port": 80},
        {"type": "tcp", "host": "https://example.com", "port": 4242},
        {"type": "tcp", "host": "example.com", "port": 70000},
        {"type": "tcp", "host": "example.com", "port": True},
    ],
)
def test_rejects_unsafe_connection_hints(hint: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        create_invitation(RNS.Identity(), "Alex", hints=[hint])
