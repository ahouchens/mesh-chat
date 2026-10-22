from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import RNS

from .call_settings import validate_broker_url
from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes
from .webrtc_signaling import (
    _b64decode,
    _b64encode,
    _destination_for_public_key,
    _document,
    _now,
    _sign,
)

CAPABILITIES_VERSION = 1
MAX_CAPABILITY_SECONDS = 7 * 24 * 60 * 60
DEVICE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")
DESTINATION = re.compile(r"^[0-9a-f]{32}$")
PAIR_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,160}$")
TRANSPORTS = {"webrtc", "direct_tcp", "access_point", "i2p"}
RELAY_SCOPES = {"contact", "session", "workspace"}


@dataclass(frozen=True, slots=True)
class VerifiedConnectionCapabilities:
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
    now: int | None = None,
) -> str:
    created = _now(now)
    expiry = _capability_expiry(expires_at, created)
    _destination(peer_destination)
    _device_id(device_id)
    normalized = _transports(transports)
    if relay_consent_scope not in RELAY_SCOPES:
        raise ValidationError("Relay consent scope is invalid")
    if not isinstance(auto_reconnect, bool) or not isinstance(allow_direct_ip_disclosure, bool):
        raise ValidationError("Connection consent must be boolean")
    mailbox = _mailbox(mailbox_url, mailbox_pair_token, mailbox_expires_at, created)
    document: dict[str, Any] = {
        "v": CAPABILITIES_VERSION,
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
    return _sign(identity, document)


def verify_connection_capabilities(
    raw: str,
    *,
    expected_signer: str | None = None,
    now: int | None = None,
) -> VerifiedConnectionCapabilities:
    value = _document(raw, "connection_capabilities")
    peer = _destination(value["peer_destination"])
    device = _device_id(value["device_id"])
    transports = _transports(value["transports"])
    _capability_expiry_value(value, now)
    auto = value["auto_reconnect"]
    disclose = value["allow_direct_ip_disclosure"]
    if not isinstance(auto, bool) or not isinstance(disclose, bool):
        raise ValidationError("Connection consent must be boolean")
    scope = value["relay_consent_scope"]
    if scope not in RELAY_SCOPES:
        raise ValidationError("Relay consent scope is invalid")
    mailbox = value.get("mailbox")
    mailbox_url = mailbox_token = None
    mailbox_expiry = None
    if mailbox is not None:
        if not isinstance(mailbox, dict):
            raise ValidationError("Mailbox capability is invalid")
        mailbox_url = str(validate_broker_url(mailbox.get("url")))
        mailbox_token = _pair_token(mailbox.get("pair_token"))
        mailbox_expiry = _mailbox_expiry(mailbox.get("expires_at"), value["issued_at"])
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
    if not isinstance(expiry, int) or isinstance(expiry, bool):
        raise ValidationError("Capability expiry is invalid")
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
        if item not in TRANSPORTS or item in seen:
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
) -> dict[str, Any] | None:
    if url is None and token is None and expires_at is None:
        return None
    if url is None or token is None or expires_at is None:
        raise ValidationError("Mailbox capability requires URL, token, and expiry")
    return {
        "url": validate_broker_url(url),
        "pair_token": _pair_token(token),
        "expires_at": _mailbox_expiry(expires_at, now),
    }


def _mailbox_expiry(value: Any, now: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError("Mailbox expiry is invalid")
    if value <= now or value - now > 30 * 24 * 60 * 60:
        raise ValidationError("Mailbox expiry is invalid")
    return value
