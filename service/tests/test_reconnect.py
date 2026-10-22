from __future__ import annotations

import json

import RNS
import pytest

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import canonical_bytes
from mesh_chat.reconnect import (
    ReconnectReplayCache,
    create_connection_capabilities,
    create_reconnect_answer,
    create_reconnect_offer,
    create_reconnect_request,
    preferred_initiator,
    verify_connection_capabilities,
    verify_reconnect_answer,
    verify_reconnect_offer,
    verify_reconnect_request,
)

NOW = 1_800_000_000
FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "\r\n".join(
    [
        "v=0",
        "o=- 1 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=fingerprint:" + FINGERPRINT,
        "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
        "a=mid:0",
        "a=sctp-port:5000",
    ]
) + "\r\n"


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


def test_reconnect_request_offer_answer_binding() -> None:
    owner = RNS.Identity()
    peer = RNS.Identity()
    owner_destination = destination(owner)
    peer_destination = destination(peer)
    request_raw = create_reconnect_request(
        owner,
        to_destination=peer_destination,
        device_id="device:test-owner",
        attempt_id="attempt-0123456789",
        nonce="nonce-0123456789",
        expires_at=NOW + 300,
        now=NOW,
    )
    request = verify_reconnect_request(request_raw, now=NOW)
    assert request.to_destination == peer_destination
    assert request.signer_destination

    offer_raw = create_reconnect_offer(
        peer,
        request,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        expires_at=NOW + 240,
        now=NOW,
    )
    offer = verify_reconnect_offer(offer_raw, now=NOW)
    assert offer.attempt_id == request.attempt_id
    assert offer.to_destination == request.from_destination

    answer_raw = create_reconnect_answer(
        owner,
        offer,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        expires_at=NOW + 180,
        now=NOW,
    )
    answer = verify_reconnect_answer(answer_raw, offer, now=NOW)
    assert answer.offer_digest == offer.digest
    assert answer.session_id == offer.session_id


def test_reconnect_answer_rejects_other_offer() -> None:
    owner = RNS.Identity()
    peer = RNS.Identity()
    request_raw = create_reconnect_request(
        owner,
        to_destination=destination(peer),
        device_id="device:test-owner",
        attempt_id="attempt-0123456789",
        nonce="nonce-0123456789",
        now=NOW,
    )
    request = verify_reconnect_request(request_raw, now=NOW)
    offer = verify_reconnect_offer(
        create_reconnect_offer(peer, request, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW),
        now=NOW,
    )
    answer_raw = create_reconnect_answer(owner, offer, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW)
    other = RNS.Identity()
    other_offer = verify_reconnect_offer(
        create_reconnect_offer(other, request, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW),
        now=NOW,
    )
    with pytest.raises(IdentityMismatch):
        verify_reconnect_answer(answer_raw, other_offer, now=NOW)


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
