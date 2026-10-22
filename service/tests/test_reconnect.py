from __future__ import annotations

import json

import RNS
import pytest

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import canonical_bytes
from mesh_chat.reconnect import (
    ReconnectReplayCache,
    create_connection_capabilities,
    preferred_initiator,
    verify_connection_capabilities,
)

NOW = 1_800_000_000


def destination(identity: RNS.Identity) -> str:
    return RNS.Destination(
        identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        "meshchat",
        "reconnect-test",
    ).hash.hex()


def test_capabilities_round_trip_and_consent() -> None:
    owner = RNS.Identity()
    peer = RNS.Identity()
    raw = create_connection_capabilities(
        owner,
        peer_destination=destination(peer),
        device_id="device:test-1",
        transports=["webrtc", "direct_tcp"],
        auto_reconnect=True,
        allow_direct_ip_disclosure=True,
        relay_consent_scope="contact",
        mailbox_url="https://signal.example.workers.dev",
        mailbox_pair_token="a" * 32,
        mailbox_expires_at=NOW + 3600,
        expires_at=NOW + 7200,
        now=NOW,
    )

    value = verify_connection_capabilities(raw, now=NOW)
    assert value.transports == ("webrtc", "direct_tcp")
    assert value.auto_reconnect is True
    assert value.mailbox_url == "https://signal.example.workers.dev"
    assert value.mailbox_pair_token == "a" * 32
    assert value.signer_destination
    assert verify_connection_capabilities(raw, expected_signer=value.signer_destination, now=NOW).peer_destination == value.peer_destination


def test_capabilities_reject_tampering_and_wrong_signer() -> None:
    owner = RNS.Identity()
    peer = RNS.Identity()
    raw = create_connection_capabilities(
        owner,
        peer_destination=destination(peer),
        device_id="device:test-1",
        transports=["webrtc"],
        now=NOW,
    )
    tampered = json.loads(raw)
    tampered["auto_reconnect"] = True
    with pytest.raises(IdentityMismatch):
        verify_connection_capabilities(canonical_bytes(tampered).decode("utf-8"), now=NOW)
    with pytest.raises(IdentityMismatch):
        verify_connection_capabilities(raw, expected_signer=destination(peer), now=NOW)


def test_capabilities_reject_invalid_mailbox_and_expiry() -> None:
    owner = RNS.Identity()
    with pytest.raises(ValidationError):
        create_connection_capabilities(
            owner,
            peer_destination=destination(RNS.Identity()),
            device_id="device:test-1",
            transports=["webrtc"],
            mailbox_url="http://insecure.example",
            mailbox_pair_token="a" * 32,
            mailbox_expires_at=NOW + 60,
            now=NOW,
        )
    raw = create_connection_capabilities(
        owner,
        peer_destination=destination(RNS.Identity()),
        device_id="device:test-1",
        transports=["webrtc"],
        now=NOW,
    )
    with pytest.raises(ValidationError):
        verify_connection_capabilities(raw, now=NOW + 8 * 24 * 60 * 60)


def test_glare_preference_and_replay_cache() -> None:
    assert preferred_initiator("device:a", "device:b") is True
    assert preferred_initiator("device:b", "device:a") is False
    assert preferred_initiator("device:a", "device:a") is False

    cache = ReconnectReplayCache()
    assert cache.accept("attempt-1", now=NOW, ttl=60) is True
    assert cache.accept("attempt-1", now=NOW + 1, ttl=60) is False
    assert cache.accept("attempt-2", now=NOW + 61, ttl=60) is True
    cache.purge(NOW + 122)
    assert cache.accept("attempt-2", now=NOW + 123, ttl=60) is True
