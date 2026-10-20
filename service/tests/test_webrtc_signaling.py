from __future__ import annotations

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, InvitationExpired, ValidationError
from mesh_chat.webrtc_signaling import (
    create_call_answer,
    create_call_candidate,
    create_call_hangup,
    create_call_invite,
    create_call_renegotiate,
    next_call_state,
    verify_call_answer,
    verify_call_candidate,
    verify_call_hangup,
    verify_call_invite,
    verify_call_renegotiate,
)

NOW = 1_800_000_000
CALL_ID = "call_0123456789abcdef"
FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "\r\n".join(
    [
        "v=0",
        "o=- 4611731400430051336 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=fingerprint:" + FINGERPRINT,
        "m=audio 9 UDP/TLS/RTP/SAVPF 111",
        "a=mid:0",
    ]
) + "\r\n"


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _invite(caller: RNS.Identity, callee: RNS.Identity, **kwargs):
    return create_call_invite(
        caller,
        call_id=CALL_ID,
        callee_destination=_destination(callee),
        media="audio",
        sdp=kwargs.pop("sdp", SDP),
        dtls_fingerprint=kwargs.pop("fingerprint", FINGERPRINT),
        expires_at=kwargs.pop("expires_at", NOW + 300),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def test_invite_round_trip_binds_caller_and_callee() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    raw = _invite(caller, callee)

    verified = verify_call_invite(raw, expected_callee_destination=_destination(callee), now=NOW)

    assert verified.call_id == CALL_ID
    assert verified.media == "audio"
    assert verified.caller_destination == _destination(caller)
    assert verified.callee_destination == _destination(callee)
    assert verified.sdp == SDP
    assert verified.dtls_fingerprint == FINGERPRINT
    assert len(verified.digest) == 64


def test_invite_rejects_a_different_callee() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    other = RNS.Identity()
    raw = _invite(caller, callee)

    with pytest.raises(IdentityMismatch):
        verify_call_invite(raw, expected_callee_destination=_destination(other), now=NOW)


def test_fingerprint_prefix_is_case_insensitive() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    raw = _invite(caller, callee, fingerprint="SHA-256 " + FINGERPRINT.removeprefix("sha-256 "))

    verified = verify_call_invite(raw, now=NOW)
    assert verified.dtls_fingerprint == FINGERPRINT


def test_invite_rejects_tampered_sdp() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    raw = _invite(caller, callee)

    with pytest.raises((IdentityMismatch, ValidationError)):
        verify_call_invite(raw.replace("a=mid:0", "a=mid:1"), now=NOW)


def test_invite_rejects_missing_fingerprint() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    bad_sdp = SDP.replace("a=fingerprint:" + FINGERPRINT, "a=fingerprint:sha-256 " + ":".join(["CD"] * 32))

    with pytest.raises(ValidationError):
        _invite(caller, callee, sdp=bad_sdp)


def test_invite_rejects_expired_document() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    raw = _invite(caller, callee, expires_at=NOW + 60)

    with pytest.raises(InvitationExpired):
        verify_call_invite(raw, now=NOW + 61)


def test_answer_binds_the_invite_digest_and_callee() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    invite = verify_call_invite(_invite(caller, callee), now=NOW)
    raw = create_call_answer(
        callee,
        invite,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        expires_at=NOW + 240,
        now=NOW + 1,
    )

    verified = verify_call_answer(raw, invite, now=NOW + 2)
    assert verified.call_id == CALL_ID
    assert verified.invite_digest == invite.digest
    assert verified.caller_destination == _destination(caller)
    assert verified.callee_destination == _destination(callee)


def test_only_the_invited_callee_can_answer() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    invite = verify_call_invite(_invite(caller, callee), now=NOW)

    with pytest.raises(IdentityMismatch):
        create_call_answer(
            caller, invite, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW + 1
        )


def test_answer_rejects_a_different_invite() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    first = verify_call_invite(_invite(caller, callee), now=NOW)
    other_invite = _invite(caller, callee, now=NOW + 1)
    second = verify_call_invite(other_invite, now=NOW + 1)
    raw = create_call_answer(
        callee, first, sdp=SDP, dtls_fingerprint=FINGERPRINT, now=NOW + 1
    )

    with pytest.raises(IdentityMismatch):
        verify_call_answer(raw, second, now=NOW + 1)


def test_candidate_and_hangup_are_scoped_to_the_call() -> None:
    caller = RNS.Identity()
    candidate = create_call_candidate(
        caller, call_id=CALL_ID, role="caller", candidate="candidate:1 1 UDP 1 192.0.2.1 5000 typ host",
        now=NOW,
    )
    verified = verify_call_candidate(
        candidate, call_id=CALL_ID, expected_signer_destination=_destination(caller), now=NOW
    )
    assert verified.call_id == CALL_ID
    assert verified.role == "caller"

    hangup = create_call_hangup(caller, call_id=CALL_ID, reason="completed", now=NOW)
    ended = verify_call_hangup(
        hangup, call_id=CALL_ID, expected_signer_destination=_destination(caller), now=NOW
    )
    assert ended.reason == "completed"

    with pytest.raises(IdentityMismatch):
        verify_call_candidate(candidate, call_id="other_0123456789abcdef", now=NOW)
    with pytest.raises(IdentityMismatch):
        verify_call_hangup(hangup, call_id="other_0123456789abcdef", now=NOW)


def test_candidate_rejects_a_foreign_signer() -> None:
    caller = RNS.Identity()
    other = RNS.Identity()
    candidate = create_call_candidate(
        caller, call_id=CALL_ID, role="caller", candidate="candidate:1 1 UDP 1 192.0.2.1 5000 typ host",
        now=NOW,
    )

    with pytest.raises(IdentityMismatch):
        verify_call_candidate(
            candidate, call_id=CALL_ID, expected_signer_destination=_destination(other), now=NOW
        )


def test_call_state_machine() -> None:
    assert next_call_state("idle", "dial") == "dialing"
    assert next_call_state("dialing", "ring") == "ringing"
    assert next_call_state("ringing", "accept") == "connecting"
    assert next_call_state("connecting", "connect") == "in_call"
    assert next_call_state("in_call", "end") == "ended"
    assert next_call_state("ringing", "decline") == "declined"
    assert next_call_state("dialing", "busy") == "busy"
    assert next_call_state("dialing", "timeout") == "no_answer"
    assert next_call_state("in_call", "fail") == "failed"

    with pytest.raises(ValidationError):
        next_call_state("ended", "accept")
    with pytest.raises(ValidationError):
        next_call_state("unknown", "dial")


def test_renegotiate_binds_call_role_and_generation() -> None:
    caller = RNS.Identity()
    raw = create_call_renegotiate(
        caller,
        call_id=CALL_ID,
        role="offer",
        generation=2,
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
        now=NOW,
    )

    verified = verify_call_renegotiate(
        raw,
        call_id=CALL_ID,
        expected_signer_destination=_destination(caller),
        now=NOW,
    )
    assert verified.role == "offer"
    assert verified.generation == 2
    assert verified.dtls_fingerprint == FINGERPRINT

    with pytest.raises(IdentityMismatch):
        verify_call_renegotiate(raw, call_id="other_0123456789abcdef", now=NOW)


@pytest.mark.parametrize(
    "bad_sdp",
    [
        "v=0\r\na=fingerprint:" + FINGERPRINT,
        "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:"
        + FINGERPRINT,
        SDP + "a=fingerprint:" + FINGERPRINT + "\r\n",
        SDP.replace("\r\n", "\x00\r\n"),
        "v=0\r\n" + "\r\n".join(["a=x"] * 513) + "\r\na=fingerprint:" + FINGERPRINT,
    ],
)
def test_invite_rejects_malformed_sdp(bad_sdp: str) -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    with pytest.raises(ValidationError):
        _invite(caller, callee, sdp=bad_sdp)


def test_candidate_rejects_control_characters() -> None:
    caller = RNS.Identity()
    with pytest.raises(ValidationError):
        create_call_candidate(
            caller,
            call_id=CALL_ID,
            role="caller",
            candidate="candidate:1 1 UDP 1 192.0.2.1 5000 typ host\x00",
            now=NOW,
        )
