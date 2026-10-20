from __future__ import annotations

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.webrtc_onboarding import (
    create_onboarding_answer,
    create_onboarding_offer,
    verify_onboarding_answer,
    verify_onboarding_offer,
)

NOW = 1_800_000_000
SESSION = "onboarding_0123456789"
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


def test_signed_offer_and_answer_bind_the_session_and_digest() -> None:
    owner = RNS.Identity()
    joiner = RNS.Identity()
    offer_raw = create_onboarding_offer(
        owner,
        session_id=SESSION,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        now=NOW,
    )
    offer = verify_onboarding_offer(offer_raw, now=NOW)
    answer_raw = create_onboarding_answer(
        joiner,
        offer,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        now=NOW + 1,
    )
    answer = verify_onboarding_answer(answer_raw, offer, now=NOW + 2)

    assert offer.session_id == SESSION
    assert answer.offer_digest == offer.digest
    assert answer.session_id == SESSION
    assert answer.signer_destination == RNS.Destination.hash(joiner, "lxmf", "delivery").hex()


def test_answer_rejects_a_different_offer() -> None:
    owner = RNS.Identity()
    joiner = RNS.Identity()
    first = verify_onboarding_offer(
        create_onboarding_offer(owner, session_id=SESSION, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW),
        now=NOW,
    )
    second = verify_onboarding_offer(
        create_onboarding_offer(owner, session_id="onboarding_9876543210", sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW),
        now=NOW,
    )
    answer = create_onboarding_answer(joiner, first, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW + 1)

    with pytest.raises(IdentityMismatch):
        verify_onboarding_answer(answer, second, now=NOW + 2)


def test_tampered_offer_is_rejected() -> None:
    owner = RNS.Identity()
    raw = create_onboarding_offer(owner, session_id=SESSION, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW)
    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_onboarding_offer(raw.replace("webrtc-datachannel", "webrtc-badchannel"), now=NOW)
