from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import RNS

from .call_settings import validate_broker_url
from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .webrtc_onboarding import _onboarding_sdp
from .webrtc_signaling import (
    _b64decode,
    _b64encode,
    _call_id,
    _destination_for_public_key,
    _document,
    _fingerprint,
    _now,
    _sign,
)

CAPABILITIES_VERSION = 1
DURABLE_CAPABILITIES_VERSION = 2
CAPABILITY_LIFETIME = "until_revoked"
MAX_CAPABILITY_BYTES = 16 * 1024
MAX_CLOCK_SKEW_SECONDS = 300
MAX_CAPABILITY_SECONDS = 7 * 24 * 60 * 60
MAX_RECONNECT_SECONDS = 60 * 60
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
DEVICE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")
DESTINATION = re.compile(r"^[0-9a-f]{32}$")
PAIR_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,160}$")
TRANSPORTS = {"webrtc", "direct_tcp", "access_point", "i2p"}
RELAY_SCOPES = {"contact", "session", "workspace"}


@dataclass(frozen=True, slots=True)
class VerifiedConnectionCapabilities:
    version: int
    persistent: bool
    peer_destination: str
    device_id: str
    transports: tuple[str, ...]
    mailbox_url: str | None
    mailbox_pair_token: str | None
    mailbox_expires_at: int | None
    auto_reconnect: bool
    allow_direct_ip_disclosure: bool
    relay_consent_scope: str
    issued_at: int
    expires_at: int
    signer_destination: str
    serialized: str


def create_connection_capabilities(
    identity: RNS.Identity,
    *,
    peer_destination: str,
    device_id: str,
    transports: list[str],
    auto_reconnect: bool = False,
    allow_direct_ip_disclosure: bool = False,
    relay_consent_scope: str = "contact",
    mailbox_url: str | None = None,
    mailbox_pair_token: str | None = None,
    mailbox_expires_at: int | None = None,
    expires_at: int | None = None,
    persistent: bool = False,
    now: int | None = None,
) -> str:
    created = _now(now)
    if not isinstance(persistent, bool):
        raise ValidationError("Capability lifetime is invalid")
    if persistent and expires_at is not None and (type(expires_at) is not int or expires_at != 0):
        raise ValidationError("Durable capability expiry must be zero")
    expiry = 0 if persistent else _capability_expiry(expires_at, created)
    _destination(peer_destination)
    _device_id(device_id)
    normalized = _transports(transports)
    if not isinstance(relay_consent_scope, str) or relay_consent_scope not in RELAY_SCOPES:
        raise ValidationError("Relay consent scope is invalid")
    if persistent and relay_consent_scope == "workspace":
        raise ValidationError("Durable capabilities are only for personal contacts")
    if not isinstance(auto_reconnect, bool) or not isinstance(allow_direct_ip_disclosure, bool):
        raise ValidationError("Connection consent must be boolean")
    mailbox = _mailbox(mailbox_url, mailbox_pair_token, mailbox_expires_at, created, persistent=persistent)
    document: dict[str, Any] = {
        "v": DURABLE_CAPABILITIES_VERSION if persistent else CAPABILITIES_VERSION,
        "type": "connection_capabilities",
        "peer_destination": peer_destination,
        "device_id": device_id,
        "transports": normalized,
        "auto_reconnect": auto_reconnect,
        "allow_direct_ip_disclosure": allow_direct_ip_disclosure,
        "relay_consent_scope": relay_consent_scope,
        "issued_at": created,
        "expires_at": expiry,
        "signer_public_key": _b64encode(identity.get_public_key()),
        "mailbox": mailbox,
    }
    if persistent:
        document["lifetime"] = CAPABILITY_LIFETIME
    return _sign(identity, document)


def verify_connection_capabilities(
    raw: str,
    *,
    expected_signer: str | None = None,
    now: int | None = None,
) -> VerifiedConnectionCapabilities:
    value = _capability_document(raw)
    persistent = value["v"] == DURABLE_CAPABILITIES_VERSION
    peer = _destination(value["peer_destination"])
    device = _device_id(value["device_id"])
    transports = _transports(value["transports"])
    _capability_expiry_value(value, now)
    auto = value["auto_reconnect"]
    disclose = value["allow_direct_ip_disclosure"]
    if not isinstance(auto, bool) or not isinstance(disclose, bool):
        raise ValidationError("Connection consent must be boolean")
    scope = value["relay_consent_scope"]
    if not isinstance(scope, str) or scope not in RELAY_SCOPES:
        raise ValidationError("Relay consent scope is invalid")
    if persistent and scope == "workspace":
        raise ValidationError("Durable capabilities are only for personal contacts")
    mailbox = value.get("mailbox")
    mailbox_url = mailbox_token = None
    mailbox_expiry = None
    if mailbox is not None:
        if not isinstance(mailbox, dict) or set(mailbox) != {"url", "pair_token", "expires_at"}:
            raise ValidationError("Mailbox capability is invalid")
        mailbox_url = validate_broker_url(mailbox.get("url"))
        if mailbox_url is None:
            raise ValidationError("Mailbox capability is invalid")
        mailbox_token = _pair_token(mailbox.get("pair_token"))
        mailbox_expiry = _mailbox_expiry(mailbox.get("expires_at"), value["issued_at"], persistent=persistent)
    public_key = _b64decode(value["signer_public_key"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Capabilities signer key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Capabilities signer key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(_b64decode(value["signature"]), canonical_bytes(unsigned)):
        raise IdentityMismatch("Capabilities signature is invalid")
    signer = _destination_for_public_key(public_key)
    if expected_signer is not None and signer != expected_signer:
        raise IdentityMismatch("Capabilities signer is not the expected contact")
    return VerifiedConnectionCapabilities(
        version=value["v"],
        persistent=persistent,
        peer_destination=peer,
        device_id=device,
        transports=transports,
        mailbox_url=mailbox_url,
        mailbox_pair_token=mailbox_token,
        mailbox_expires_at=mailbox_expiry,
        auto_reconnect=auto,
        allow_direct_ip_disclosure=disclose,
        relay_consent_scope=scope,
        issued_at=value["issued_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def _capability_document(raw: str) -> dict[str, Any]:
    """Version only pair authorization; other signaling remains strictly v1."""
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > MAX_CAPABILITY_BYTES:
        raise ValidationError("Connection capability is invalid")
    try:
        value = json.loads(raw)
    except Exception as exc:
        raise ValidationError("Connection capability is invalid") from exc
    if (not isinstance(value, dict) or type(value.get("v")) is not int
        or value["v"] not in {CAPABILITIES_VERSION, DURABLE_CAPABILITIES_VERSION}
        or value.get("type") != "connection_capabilities"):
        raise ValidationError("Connection capability version is unsupported")
    expected = {
        "v", "type", "peer_destination", "device_id", "transports",
        "auto_reconnect", "allow_direct_ip_disclosure", "relay_consent_scope",
        "mailbox", "issued_at", "expires_at", "signer_public_key", "signature",
    }
    if value["v"] == DURABLE_CAPABILITIES_VERSION:
        expected.add("lifetime")
        if value.get("lifetime") != CAPABILITY_LIFETIME:
            raise ValidationError("Capability lifetime is invalid")
    if set(value) != expected or canonical_bytes(value).decode("utf-8") != raw:
        raise ValidationError("Connection capability fields are invalid")
    return value


class ReconnectReplayCache:
    """Bounded, restart-persistable replay cache for reconnect attempts."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def accept(self, key: str, *, now: int, ttl: int = 600) -> bool:
        if not isinstance(key, str) or not key or len(key) > 200:
            raise ValidationError("Reconnect attempt ID is invalid")
        self.purge(now)
        if key in self._seen:
            return False
        self._seen[key] = now + ttl
        return True

    def purge(self, now: int) -> None:
        self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > now}


def preferred_initiator(local_device: str, remote_device: str) -> bool:
    """Return True when this device should create the first offer."""
    local = _device_id(local_device)
    remote = _device_id(remote_device)
    return local < remote


@dataclass(frozen=True, slots=True)
class VerifiedReconnectRequest:
    attempt_id: str
    from_destination: str
    to_destination: str
    device_id: str
    nonce: str
    issued_at: int
    expires_at: int
    signer_destination: str
    serialized: str


@dataclass(frozen=True, slots=True)
class VerifiedReconnectOffer:
    attempt_id: str
    session_id: str
    from_destination: str
    to_destination: str
    sdp: str
    dtls_fingerprint: str
    nonce: str
    issued_at: int
    expires_at: int
    signer_destination: str
    serialized: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedReconnectAnswer:
    attempt_id: str
    session_id: str
    offer_digest: str
    from_destination: str
    to_destination: str
    sdp: str
    dtls_fingerprint: str
    nonce: str
    issued_at: int
    expires_at: int
    signer_destination: str
    serialized: str


def create_reconnect_request(
    identity: RNS.Identity,
    *,
    to_destination: str,
    device_id: str,
    attempt_id: str,
    nonce: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _reconnect_expiry(expires_at, created)
    from_destination = _destination_for_public_key(identity.get_public_key())
    return _sign(
        identity,
        {
            "v": CAPABILITIES_VERSION,
            "type": "webrtc_reconnect_request",
            "from": from_destination,
            "to": _destination(to_destination),
            "device_id": _device_id(device_id),
            "attempt_id": _token(attempt_id, "attempt"),
            "nonce": _token(nonce, "nonce"),
            "issued_at": created,
            "expires_at": expiry,
            "signer_public_key": _b64encode(identity.get_public_key()),
        },
    )


def verify_reconnect_request(
    raw: str,
    *,
    expected_signer: str | None = None,
    now: int | None = None,
) -> VerifiedReconnectRequest:
    value = _document(raw, "webrtc_reconnect_request")
    _reconnect_expiry_value(value, now)
    signer = _verify_reconnect_signature(value, raw)
    if signer != value["from"]:
        raise IdentityMismatch("Reconnect request signer does not match sender")
    if expected_signer is not None and signer != expected_signer:
        raise IdentityMismatch("Reconnect request signer is not the expected contact")
    return VerifiedReconnectRequest(
        attempt_id=value["attempt_id"],
        from_destination=value["from"],
        to_destination=_destination(value["to"]),
        device_id=_device_id(value["device_id"]),
        nonce=value["nonce"],
        issued_at=value["issued_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def create_reconnect_offer(
    identity: RNS.Identity,
    request: VerifiedReconnectRequest,
    *,
    sdp: str,
    dtls_fingerprint: str,
    session_id: str | None = None,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = min(_reconnect_expiry(expires_at, created), request.expires_at)
    sdp = _onboarding_sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Reconnect SDP does not contain the DTLS fingerprint")
    session = session_id or hashlib.sha256(
        f"{request.attempt_id}:{request.nonce}:{created}".encode("utf-8")
    ).hexdigest()[:24]
    return _sign(
        identity,
        {
            "v": CAPABILITIES_VERSION,
            "type": "webrtc_reconnect_offer",
            "from": _destination_for_public_key(identity.get_public_key()),
            "to": request.from_destination,
            "attempt_id": request.attempt_id,
            "session_id": _call_id(session),
            "sdp": sdp,
            "dtls_fingerprint": fingerprint,
            "nonce": request.nonce,
            "issued_at": created,
            "expires_at": expiry,
            "signer_public_key": _b64encode(identity.get_public_key()),
        },
    )


def verify_reconnect_offer(
    raw: str,
    *,
    expected_signer: str | None = None,
    now: int | None = None,
) -> VerifiedReconnectOffer:
    value = _document(raw, "webrtc_reconnect_offer")
    _reconnect_expiry_value(value, now)
    sdp = _onboarding_sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Reconnect SDP does not contain the DTLS fingerprint")
    signer = _verify_reconnect_signature(value, raw)
    if signer != value["from"]:
        raise IdentityMismatch("Reconnect offer signer does not match sender")
    if expected_signer is not None and signer != expected_signer:
        raise IdentityMismatch("Reconnect offer signer is not the expected contact")
    return VerifiedReconnectOffer(
        attempt_id=value["attempt_id"],
        session_id=_call_id(value["session_id"]),
        from_destination=value["from"],
        to_destination=_destination(value["to"]),
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        nonce=value["nonce"],
        issued_at=value["issued_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def create_reconnect_answer(
    identity: RNS.Identity,
    offer: VerifiedReconnectOffer,
    *,
    sdp: str,
    dtls_fingerprint: str,
    expires_at: int | None = None,
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = min(_reconnect_expiry(expires_at, created), offer.expires_at)
    sdp = _onboarding_sdp(sdp)
    fingerprint = _fingerprint(dtls_fingerprint)
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Reconnect SDP does not contain the DTLS fingerprint")
    return _sign(
        identity,
        {
            "v": CAPABILITIES_VERSION,
            "type": "webrtc_reconnect_answer",
            "from": _destination_for_public_key(identity.get_public_key()),
            "to": offer.from_destination,
            "attempt_id": offer.attempt_id,
            "session_id": offer.session_id,
            "offer_digest": offer.digest,
            "sdp": sdp,
            "dtls_fingerprint": fingerprint,
            "nonce": offer.nonce,
            "issued_at": created,
            "expires_at": expiry,
            "signer_public_key": _b64encode(identity.get_public_key()),
        },
    )


def verify_reconnect_answer(
    raw: str,
    offer: VerifiedReconnectOffer,
    *,
    expected_signer: str | None = None,
    now: int | None = None,
) -> VerifiedReconnectAnswer:
    value = _document(raw, "webrtc_reconnect_answer")
    if value["attempt_id"] != offer.attempt_id:
        raise IdentityMismatch("Reconnect answer is for a different attempt")
    if value["session_id"] != offer.session_id:
        raise IdentityMismatch("Reconnect answer is for a different session")
    if value["offer_digest"] != offer.digest:
        raise IdentityMismatch("Reconnect answer does not bind the offer digest")
    _reconnect_expiry_value(value, now)
    sdp = _onboarding_sdp(value["sdp"])
    fingerprint = _fingerprint(value["dtls_fingerprint"])
    if sdp.lower().find(fingerprint.lower()) < 0:
        raise ValidationError("Reconnect SDP does not contain the DTLS fingerprint")
    signer = _verify_reconnect_signature(value, raw)
    if signer != value["from"]:
        raise IdentityMismatch("Reconnect answer signer does not match sender")
    if expected_signer is not None and signer != expected_signer:
        raise IdentityMismatch("Reconnect answer signer is not the expected contact")
    return VerifiedReconnectAnswer(
        attempt_id=value["attempt_id"],
        session_id=value["session_id"],
        offer_digest=value["offer_digest"],
        from_destination=value["from"],
        to_destination=_destination(value["to"]),
        sdp=sdp,
        dtls_fingerprint=fingerprint,
        nonce=value["nonce"],
        issued_at=value["issued_at"],
        expires_at=value["expires_at"],
        signer_destination=signer,
        serialized=raw,
    )


def _reconnect_expiry(value: int | None, now: int) -> int:
    if value is None:
        return now + MAX_RECONNECT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("Reconnect expiry is invalid")
    if not now < value <= now + MAX_RECONNECT_SECONDS:
        raise ValidationError("Reconnect expiry is invalid")
    return value


def _reconnect_expiry_value(value: dict[str, Any], now: int | None) -> None:
    created = value.get("issued_at")
    expiry = value.get("expires_at")
    if not isinstance(created, int) or isinstance(created, bool):
        raise ValidationError("Reconnect issue time is invalid")
    if not isinstance(expiry, int) or isinstance(expiry, bool):
        raise ValidationError("Reconnect expiry is invalid")
    if expiry <= created or expiry - created > MAX_RECONNECT_SECONDS:
        raise ValidationError("Reconnect expiry is invalid")
    if _now(now) >= expiry:
        raise ValidationError("Reconnect document has expired")


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValidationError(f"Reconnect {label} is invalid")
    return value


def _verify_reconnect_signature(value: dict[str, Any], raw: str) -> str:
    public_key = _b64decode(value["signer_public_key"])
    if len(public_key) != RNS.Identity.KEYSIZE // 8:
        raise ValidationError("Reconnect signer key is invalid")
    identity = RNS.Identity(create_keys=False)
    if not identity.load_public_key(public_key):
        raise ValidationError("Reconnect signer key is invalid")
    unsigned = {key: value[key] for key in value if key != "signature"}
    if not identity.validate(_b64decode(value["signature"]), canonical_bytes(unsigned)):
        raise IdentityMismatch("Reconnect signature is invalid")
    return _destination_for_public_key(public_key)


def _capability_expiry(value: int | None, now: int) -> int:
    if value is None:
        return now + MAX_CAPABILITY_SECONDS
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("Capability expiry is invalid")
    if not now < value <= now + MAX_CAPABILITY_SECONDS:
        raise ValidationError("Capability expiry is invalid")
    return value


def _capability_expiry_value(value: dict[str, Any], now: int | None) -> None:
    current = _now(now)
    created = value.get("issued_at")
    expiry = value.get("expires_at")
    if not isinstance(created, int) or isinstance(created, bool):
        raise ValidationError("Capability issue time is invalid")
    if created < 0 or created > current + MAX_CLOCK_SKEW_SECONDS:
        raise ValidationError("Capability issue time is invalid")
    if not isinstance(expiry, int) or isinstance(expiry, bool):
        raise ValidationError("Capability expiry is invalid")
    if value["v"] == DURABLE_CAPABILITIES_VERSION:
        if expiry != 0:
            raise ValidationError("Durable capability expiry must be zero")
        return
    if expiry <= created or expiry - created > MAX_CAPABILITY_SECONDS:
        raise ValidationError("Capability expiry is invalid")
    if current >= expiry:
        raise ValidationError("Capability has expired")


def _destination(value: Any) -> str:
    if not isinstance(value, str) or not DESTINATION.fullmatch(value.lower()):
        raise ValidationError("Peer destination is invalid")
    return value.lower()


def _device_id(value: Any) -> str:
    if not isinstance(value, str) or not DEVICE_ID.fullmatch(value):
        raise ValidationError("Device ID is invalid")
    return value


def _transports(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValidationError("Transport list is invalid")
    seen: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in TRANSPORTS or item in seen:
            raise ValidationError("Transport list is invalid")
        seen.append(item)
    return tuple(seen)


def _pair_token(value: Any) -> str:
    if not isinstance(value, str) or not PAIR_TOKEN.fullmatch(value):
        raise ValidationError("Mailbox pairing token is invalid")
    return value


def _mailbox(
    url: str | None,
    token: str | None,
    expires_at: int | None,
    now: int,
    *,
    persistent: bool = False,
) -> dict[str, Any] | None:
    if url is None and token is None and expires_at is None:
        return None
    if url is None or token is None or expires_at is None:
        raise ValidationError("Mailbox capability requires URL, token, and expiry")
    return {
        "url": validate_broker_url(url),
        "pair_token": _pair_token(token),
        "expires_at": _mailbox_expiry(expires_at, now, persistent=persistent),
    }


def _mailbox_expiry(value: Any, now: int, *, persistent: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError("Mailbox expiry is invalid")
    if persistent:
        if value != 0:
            raise ValidationError("Durable mailbox authorization expiry must be zero")
        return value
    if value <= now or value - now > 30 * 24 * 60 * 60:
        raise ValidationError("Mailbox expiry is invalid")
    return value
