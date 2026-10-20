from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import RNS

from .errors import IdentityMismatch, InvitationExpired, ValidationError
from .invitations import _b64decode, _b64encode, canonical_bytes

CALL_VERSION = 1
MAX_SDP_BYTES = 32 * 1024
MAX_SDP_LINES = 512
MAX_CANDIDATE_BYTES = 2 * 1024
MAX_CALL_SECONDS = 10 * 60
CALL_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
FINGERPRINT = re.compile(r"^sha-256 (?:[0-9A-F]{2}:){31}[0-9A-F]{2}$")
MEDIA = {"audio", "video"}
ROLES = {"caller", "callee"}
RENEGOTIATE_ROLES = {"offer", "answer"}
HANGUP_REASONS = {"completed", "declined", "busy", "failed", "cancelled"}

CALL_STATES = {
    "idle", "dialing", "ringing", "connecting", "in_call",
    "ended", "declined", "busy", "no_answer", "failed",
}


@dataclass(frozen=True, slots=True)
class VerifiedCallInvite:
    call_id: str
    media: str
    caller_destination: str
    callee_destination: str
    sdp: str
    dtls_fingerprint: str
    created_at: int
    expires_at: int
    signer_public_key: bytes
    serialized: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedCallAnswer:
    call_id: str
    invite_digest: str
    media: str
    caller_destination: str
    callee_destination: str
    sdp: str
    dtls_fingerprint: str
    created_at: int
    expires_at: int
    signer_public_key: bytes
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedCallCandidate:
    call_id: str
    role: str
    candidate: str
    created_at: int
    expires_at: int
    signer_destination: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedCallHangup:
    call_id: str
    reason: str
    created_at: int
    expires_at: int
    signer_destination: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedCallRenegotiate:
    call_id: str
    role: str
    generation: int
    sdp: str
    dtls_fingerprint: str
    created_at: int
    expires_at: int
    signer_destination: str
    serialized: str


def create_call_invite(
    identity: RNS.Identity,
    *,
    call_id: str,
    callee_destination: str,
    media: str,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    caller_destination = _destination_for(identity)
    _call_id(call_id)
    _media(media)
    _destination(callee_destination)
    sdp = _sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    unsigned = {
        "v": CALL_VERSION,
        "type": "call_invite",
        "call_id": call_id,
        "media": media,
        "caller_destination": caller_destination,
        "callee_destination": callee_destination.lower(),
        "sdp": sdp,
        "dtls_fingerprint": fingerprint,
        "created_at": created,
        "expires_at": expiry,
        "signer_public_key": _b64encode(identity.get_public_key()),
    }
    return _sign(identity, unsigned)


def verify_call_invite(
    raw: str,
    *,
    expected_callee_destination: str | None = None,
    now: int | None = None,
) -> VerifiedCallInvite:
    value = _document(raw, "call_invite")
    _call_id(value["call_id"])
    media = _media(value["media"])
    caller = _destination(value["caller_destination"])
    callee = _destination(value["callee_destination"])
    if expected_callee_destination is not None and callee != expected_callee_destination.lower():
        raise IdentityMismatch("Call invitation is addressed to a different destination")
    sdp = _sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    _expiry_value(value, now)
    public_key = _verify_signature(value, raw)
    if _destination_for_public_key(public_key) != caller:
        raise IdentityMismatch("Call invitation signer is not the caller")
    return VerifiedCallInvite(
        call_id=value["call_id"],
        media=media,
        caller_destination=caller,
        callee_destination=callee,
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_public_key=public_key,
        serialized=raw,
    )


def create_call_answer(
    identity: RNS.Identity,
    invite: VerifiedCallInvite,
    *,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    if expiry > invite.expires_at:
        expiry = invite.expires_at
    sdp = _sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    if _destination_for(identity) != invite.callee_destination:
        raise IdentityMismatch("Only the invited callee can answer this call")
    unsigned = {
        "v": CALL_VERSION,
        "type": "call_answer",
        "call_id": invite.call_id,
        "invite_digest": invite.digest,
        "media": invite.media,
        "caller_destination": invite.caller_destination,
        "callee_destination": invite.callee_destination,
        "sdp": sdp,
        "dtls_fingerprint": fingerprint,
        "created_at": created,
        "expires_at": expiry,
        "signer_public_key": _b64encode(identity.get_public_key()),
    }
    return _sign(identity, unsigned)


def verify_call_answer(
    raw: str, invite: VerifiedCallInvite, *, now: int | None = None
) -> VerifiedCallAnswer:
    value = _document(raw, "call_answer")
    if value["call_id"] != invite.call_id:
        raise IdentityMismatch("Call answer does not match the invitation")
    if value["invite_digest"] != invite.digest:
        raise IdentityMismatch("Call answer does not bind the invitation digest")
    if value["media"] != invite.media:
        raise IdentityMismatch("Call answer changed the media type")
    caller = _destination(value["caller_destination"])
    callee = _destination(value["callee_destination"])
    if caller != invite.caller_destination or callee != invite.callee_destination:
        raise IdentityMismatch("Call answer changed the participants")
    sdp = _sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    _expiry_value(value, now)
    public_key = _verify_signature(value, raw)
    if _destination_for_public_key(public_key) != callee:
        raise IdentityMismatch("Call answer signer is not the callee")
    return VerifiedCallAnswer(
        call_id=value["call_id"],
        invite_digest=value["invite_digest"],
        media=invite.media,
        caller_destination=caller,
        callee_destination=callee,
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_public_key=public_key,
        serialized=raw,
    )


def create_call_candidate(
    identity: RNS.Identity,
    *,
    call_id: str,
    role: str,
    candidate: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    _call_id(call_id)
    if role not in ROLES:
        raise ValidationError("Call candidate role is invalid")
    if not isinstance(candidate, str) or not candidate or len(candidate.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ValidationError("Call candidate is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValidationError("Call candidate is invalid")
    unsigned = {
        "v": CALL_VERSION,
        "type": "call_candidate",
        "call_id": call_id,
        "role": role,
        "candidate": candidate,
        "created_at": created,
        "expires_at": expiry,
        "signer_destination": _destination_for(identity),
        "signer_public_key": _b64encode(identity.get_public_key()),
    }
    return _sign(identity, unsigned)


def verify_call_candidate(
    raw: str,
    *,
    call_id: str,
    expected_signer_destination: str | None = None,
    now: int | None = None,
) -> VerifiedCallCandidate:
    value = _document(raw, "call_candidate")
    _call_id(call_id)
    if value["call_id"] != call_id:
        raise IdentityMismatch("Call candidate is for a different call")
    role = value["role"]
    if role not in ROLES:
        raise ValidationError("Call candidate role is invalid")
    candidate = value["candidate"]
    if not isinstance(candidate, str) or not candidate or len(candidate.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ValidationError("Call candidate is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValidationError("Call candidate is invalid")
    _expiry_value(value, now)
    public_key = _verify_signature(value, raw)
    signer = _destination_for_public_key(public_key)
    expected = value["signer_destination"]
    if not isinstance(expected, str) or signer != expected.lower():
        raise IdentityMismatch("Call candidate signer destination is invalid")
    if expected_signer_destination is not None and signer != expected_signer_destination.lower():
        raise IdentityMismatch("Call candidate signer is not the expected participant")
    return VerifiedCallCandidate(
        call_id=call_id,
        role=role,
        candidate=candidate,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def create_call_hangup(
    identity: RNS.Identity,
    *,
    call_id: str,
    reason: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    _call_id(call_id)
    if reason not in HANGUP_REASONS:
        raise ValidationError("Call hangup reason is invalid")
    unsigned = {
        "v": CALL_VERSION,
        "type": "call_hangup",
        "call_id": call_id,
        "reason": reason,
        "created_at": created,
        "expires_at": expiry,
        "signer_destination": _destination_for(identity),
        "signer_public_key": _b64encode(identity.get_public_key()),
    }
    return _sign(identity, unsigned)


def verify_call_hangup(
    raw: str,
    *,
    call_id: str,
    expected_signer_destination: str | None = None,
    now: int | None = None,
) -> VerifiedCallHangup:
    value = _document(raw, "call_hangup")
    _call_id(call_id)
    if value["call_id"] != call_id:
        raise IdentityMismatch("Call hangup is for a different call")
    reason = value["reason"]
    if reason not in HANGUP_REASONS:
        raise ValidationError("Call hangup reason is invalid")
    _expiry_value(value, now)
    public_key = _verify_signature(value, raw)
    signer = _destination_for_public_key(public_key)
    expected = value["signer_destination"]
    if not isinstance(expected, str) or signer != expected.lower():
        raise IdentityMismatch("Call hangup signer destination is invalid")
    if expected_signer_destination is not None and signer != expected_signer_destination.lower():
        raise IdentityMismatch("Call hangup signer is not the expected participant")
    return VerifiedCallHangup(
        call_id=call_id,
        reason=reason,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def create_call_renegotiate(
    identity: RNS.Identity,
    *,
    call_id: str,
    role: str,
    generation: int,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _expiry(expires_at, created)
    _call_id(call_id)
    if role not in RENEGOTIATE_ROLES:
        raise ValidationError("Call renegotiation role is invalid")
    if isinstance(generation, bool) or not isinstance(generation, int) or not 1 <= generation <= 10000:
        raise ValidationError("Call renegotiation generation is invalid")
    sdp = _sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    unsigned = {
        "v": CALL_VERSION,
        "type": "call_renegotiate",
        "call_id": call_id,
        "role": role,
        "generation": generation,
        "sdp": sdp,
        "dtls_fingerprint": fingerprint,
        "created_at": created,
        "expires_at": expiry,
        "signer_destination": _destination_for(identity),
        "signer_public_key": _b64encode(identity.get_public_key()),
    }
    return _sign(identity, unsigned)


def verify_call_renegotiate(
    raw: str,
    *,
    call_id: str,
    expected_signer_destination: str | None = None,
    now: int | None = None,
) -> VerifiedCallRenegotiate:
    value = _document(raw, "call_renegotiate")
    _call_id(call_id)
    if value["call_id"] != call_id:
        raise IdentityMismatch("Call renegotiation is for a different call")
    role = value["role"]
    if role not in RENEGOTIATE_ROLES:
        raise ValidationError("Call renegotiation role is invalid")
    generation = value["generation"]
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= 10000
    ):
        raise ValidationError("Call renegotiation generation is invalid")
    sdp = _sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Call SDP does not contain the DTLS fingerprint")
    _expiry_value(value, now)
    public_key = _verify_signature(value, raw)
    signer = _destination_for_public_key(public_key)
    expected = value["signer_destination"]
    if not isinstance(expected, str) or signer != expected.lower():
        raise IdentityMismatch("Call renegotiation signer destination is invalid")
    if expected_signer_destination is not None and signer != expected_signer_destination.lower():
        raise IdentityMismatch("Call renegotiation signer is not the expected participant")
    return VerifiedCallRenegotiate(
        call_id=call_id,
        role=role,
        generation=generation,
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def next_call_state(state: str, event: str) -> str:
    """Return the next call state or raise for an invalid transition."""
    if state not in CALL_STATES:
        raise ValidationError("Call state is invalid")
    transitions = {
        ("idle", "dial"): "dialing",
        ("dialing", "ring"): "ringing",
        ("dialing", "answer"): "connecting",
        ("dialing", "decline"): "declined",
        ("dialing", "busy"): "busy",
        ("dialing", "timeout"): "no_answer",
        ("ringing", "accept"): "connecting",
        ("ringing", "decline"): "declined",
        ("ringing", "timeout"): "no_answer",
        ("connecting", "connect"): "in_call",
        ("in_call", "end"): "ended",
        ("dialing", "cancel"): "ended",
        ("ringing", "cancel"): "ended",
        ("connecting", "cancel"): "ended",
    }
    if event == "fail" and state not in {"ended", "declined", "busy", "no_answer", "failed"}:
        return "failed"
    if event == "end" and state in {"dialing", "ringing", "connecting"}:
        return "ended"
    try:
        return transitions[(state, event)]
    except KeyError as exc:
        raise ValidationError("Call transition is invalid") from exc


def _sign(identity: RNS.Identity, unsigned: dict[str, Any]) -> str:
    signed = {
        **unsigned,
        "signature": _b64encode(identity.sign(canonical_bytes(unsigned))),
    }
    return canonical_bytes(signed).decode("utf-8")


def _document(raw: str, kind: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > MAX_SDP_BYTES + 4096:
        raise ValidationError("Call document is invalid")
    try:
        import json

        value = json.loads(raw)
    except Exception as exc:
        raise ValidationError("Call document is invalid") from exc
    if not isinstance(value, dict) or value.get("v") != CALL_VERSION or value.get("type") != kind:
        raise ValidationError("Call document fields are invalid")
    if set(value) != _keys(kind):
        raise ValidationError("Call document fields are invalid")
    if canonical_bytes(value).decode("utf-8") != raw:
        raise ValidationError("Call document is not canonical")
    return value


def _keys(kind: str) -> set[str]:
    common = {"v", "type", "call_id", "created_at", "expires_at", "signer_public_key", "signature"}
    if kind == "call_invite":
        return common | {"media", "caller_destination", "callee_destination", "sdp", "dtls_fingerprint"}
    if kind == "call_answer":
        return common | {
            "invite_digest", "media", "caller_destination", "callee_destination",
            "sdp", "dtls_fingerprint",
        }
    if kind == "call_candidate":
        return {"v", "type", "call_id", "role", "candidate", "created_at", "expires_at",
                "signer_destination", "signer_public_key", "signature"}
    if kind == "call_hangup":
        return {"v", "type", "call_id", "reason", "created_at", "expires_at",
                "signer_destination", "signer_public_key", "signature"}
    if kind == "call_renegotiate":
        return {
            "v", "type", "call_id", "role", "generation", "sdp", "dtls_fingerprint",
            "created_at", "expires_at", "signer_destination", "signer_public_key", "signature",
        }
    raise ValidationError("Call document type is invalid")


def _verify_signature(value: dict[str, Any], raw: str) -> bytes:
    public_key = _b64decode(value["signer_public_key"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Call signer key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Call signer key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(_b64decode(value["signature"]), canonical_bytes(unsigned)):
        raise IdentityMismatch("Call signature is invalid")
    return public_key


def _expiry_value(value: dict[str, Any], now: int | None) -> None:
    created = value.get("created_at")
    expires = value.get("expires_at")
    if not isinstance(created, int) or isinstance(created, bool):
        raise ValidationError("Call timestamp is invalid")
    if not isinstance(expires, int) or isinstance(expires, bool):
        raise ValidationError("Call expiry is invalid")
    current = _now(now)
    if created > current + 86400 or expires <= current:
        raise InvitationExpired("Call document has expired")
    if expires > created + MAX_CALL_SECONDS:
        raise ValidationError("Call document expiry is too long")


def _now(now: int | None) -> int:
    if now is None:
        return int(time.time())
    if isinstance(now, bool) or not isinstance(now, int):
        raise ValidationError("Call timestamp is invalid")
    return now


def _expiry(expires_at: int | None, created: int) -> int:
    if expires_at is None:
        return created + MAX_CALL_SECONDS
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ValidationError("Call expiry is invalid")
    if not created < expires_at <= created + MAX_CALL_SECONDS:
        raise ValidationError("Call expiry is invalid")
    return expires_at


def _call_id(value: Any) -> str:
    if not isinstance(value, str) or not CALL_ID.fullmatch(value):
        raise ValidationError("Call ID is invalid")
    return value


def _media(value: Any) -> str:
    if value not in MEDIA:
        raise ValidationError("Call media type is invalid")
    return str(value)


def _destination(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value.lower()):
        raise ValidationError("Call destination is invalid")
    return value.lower()


def _sdp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("Call SDP is invalid")
    if len(value.encode("utf-8")) > MAX_SDP_BYTES or not value.startswith("v=0"):
        raise ValidationError("Call SDP is invalid")
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ValidationError("Call SDP contains control characters")
    lines = value.replace("\r\n", "\n").split("\n")
    if len(lines) > MAX_SDP_LINES:
        raise ValidationError("Call SDP has too many lines")
    media = [line for line in lines if line.startswith("m=")]
    if not media or any(
        not (line.startswith("m=audio ") or line.startswith("m=video "))
        for line in media
    ):
        raise ValidationError("Call SDP must describe audio or video")
    fingerprints = [line for line in lines if line.startswith("a=fingerprint:")]
    if len(fingerprints) != 1:
        raise ValidationError("Call SDP must contain exactly one DTLS fingerprint")
    return value


def _fingerprint(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("Call fingerprint is invalid")
    parts = value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "sha-256":
        raise ValidationError("Call fingerprint is invalid")
    normalized = "sha-256 " + parts[1].upper()
    if not FINGERPRINT.fullmatch(normalized):
        raise ValidationError("Call fingerprint is invalid")
    return normalized


def _destination_for(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _destination_for_public_key(public_key: bytes) -> str:
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Call signer key is invalid")
    return _destination_for(identity)
