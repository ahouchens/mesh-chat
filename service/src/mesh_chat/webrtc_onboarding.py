from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import RNS

from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .webrtc_signaling import (
    MAX_SDP_BYTES,
    MAX_SDP_LINES,
    _b64decode,
    _b64encode,
    _call_id,
    _destination_for_public_key,
    _expiry,
    _expiry_value,
    _fingerprint,
    _now,
    _sign,
    _document,
)

ONBOARDING_VERSION = 1


@dataclass(frozen=True, slots=True)
class VerifiedOnboardingOffer:
    session_id: str
    sdp: str
    dtls_fingerprint: str
    created_at: int
    expires_at: int
    signer_destination: str
    serialized: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedOnboardingAnswer:
    session_id: str
    offer_digest: str
    sdp: str
    dtls_fingerprint: str
    created_at: int
    expires_at: int
    signer_destination: str
    serialized: str


def create_onboarding_offer(
    identity: RNS.Identity,
    *,
    session_id: str,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    _call_id(session_id)
    sdp = _onboarding_sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Onboarding SDP does not contain the DTLS fingerprint")
    return _sign(
        identity,
        {
            "v": ONBOARDING_VERSION,
            "type": "webrtc_onboarding_offer",
            "session_id": session_id,
            "sdp": sdp,
            "dtls_fingerprint": fingerprint,
            "created_at": created,
            "expires_at": expiry,
            "signer_public_key": _b64encode(identity.get_public_key()),
        },
    )


def verify_onboarding_offer(
    raw: str,
    *,
    now: int | None = None,
) -> VerifiedOnboardingOffer:
    value = _document(raw, "webrtc_onboarding_offer")
    _call_id(value["session_id"])
    sdp = _onboarding_sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Onboarding SDP does not contain the DTLS fingerprint")
    _expiry_value(value, now)
    public_key = _verify_onboarding_signature(value, raw)
    signer = _destination_for_public_key(public_key)
    return VerifiedOnboardingOffer(
        session_id=value["session_id"],
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def create_onboarding_answer(
    identity: RNS.Identity,
    offer: VerifiedOnboardingOffer,
    *,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    if expiry > offer.expires_at:
        expiry = offer.expires_at
    sdp = _onboarding_sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Onboarding SDP does not contain the DTLS fingerprint")
    return _sign(
        identity,
        {
            "v": ONBOARDING_VERSION,
            "type": "webrtc_onboarding_answer",
            "session_id": offer.session_id,
            "offer_digest": offer.digest,
            "sdp": sdp,
            "dtls_fingerprint": fingerprint,
            "created_at": created,
            "expires_at": expiry,
            "signer_public_key": _b64encode(identity.get_public_key()),
        },
    )


def verify_onboarding_answer(
    raw: str,
    offer: VerifiedOnboardingOffer,
    *,
    now: int | None = None,
) -> VerifiedOnboardingAnswer:
    value = _document(raw, "webrtc_onboarding_answer")
    if value["session_id"] != offer.session_id:
        raise IdentityMismatch("Onboarding answer is for a different session")
    if value["offer_digest"] != offer.digest:
        raise IdentityMismatch("Onboarding answer does not bind the offer digest")
    sdp = _onboarding_sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Onboarding SDP does not contain the DTLS fingerprint")
    _expiry_value(value, now)
    public_key = _verify_onboarding_signature(value, raw)
    signer = _destination_for_public_key(public_key)
    return VerifiedOnboardingAnswer(
        session_id=value["session_id"],
        offer_digest=value["offer_digest"],
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def _onboarding_sdp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("Onboarding SDP is invalid")
    if len(value.encode("utf-8")) > MAX_SDP_BYTES or not value.startswith("v=0"):
        raise ValidationError("Onboarding SDP is invalid")
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ValidationError("Onboarding SDP contains control characters")
    lines = value.replace("\r\n", "\n").split("\n")
    if len(lines) > MAX_SDP_LINES:
        raise ValidationError("Onboarding SDP has too many lines")
    media = [line for line in lines if line.startswith("m=")]
    if not any(
        line.startswith("m=application ") and "webrtc-datachannel" in line
        for line in media
    ):
        raise ValidationError("Onboarding SDP must describe a WebRTC DataChannel")
    fingerprints = [line for line in lines if line.startswith("a=fingerprint:")]
    if len(fingerprints) != 1:
        raise ValidationError("Onboarding SDP must contain exactly one DTLS fingerprint")
    return value


def _verify_onboarding_signature(value: dict[str, Any], raw: str) -> bytes:
    public_key = _b64decode(value["signer_public_key"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Onboarding signer key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Onboarding signer key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(_b64decode(value["signature"]), canonical_bytes(unsigned)):
        raise IdentityMismatch("Onboarding signature is invalid")
    return public_key


