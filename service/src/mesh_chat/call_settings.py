from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .errors import ValidationError
from .deployment_defaults import SIGNAL_MAILBOX_URL as PACKAGED_SIGNAL_MAILBOX_URL

MAX_SERVERS = 8
DEFAULT_STUN_URLS = ("stun:stun.l.google.com:19302",)
DEFAULT_TURN_BROKER_URL = os.environ.get(
    "MESH_CHAT_DEFAULT_TURN_BROKER",
    "https://staether.webtechalex.workers.dev/credentials",
).strip() or None
DEFAULT_SIGNAL_MAILBOX_URL = os.environ.get("MESH_CHAT_DEFAULT_SIGNAL_MAILBOX", PACKAGED_SIGNAL_MAILBOX_URL or "").strip() or None
URL = re.compile(
    r"^(stun|stuns|turn|turns):([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?(?:\?transport=(tcp|udp))?$",
    re.IGNORECASE,
)
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
USERNAME = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")


@dataclass(slots=True)
class CallSettings:
    stun_urls: list[str] = field(default_factory=lambda: list(DEFAULT_STUN_URLS))
    turn_url: str | None = None
    turn_username: str | None = None
    turn_credential: str | None = None
    turn_broker_url: str | None = field(default_factory=lambda: DEFAULT_TURN_BROKER_URL)
    turn_broker_consent: bool = False
    signal_mailbox_url: str | None = field(default_factory=lambda: _default_signal_mailbox())
    relay_only: bool = False
    # Sealed call records (negotiated SDP and ICE candidates) are stored in the
    # vault by default so an active call survives a service restart. Turning
    # this off keeps them in service memory only; calls still work while the
    # process is alive.
    store_call_signaling: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CallSettings":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError("Call settings must be an object")
        allowed = {
            "stun_urls", "turn_url", "turn_username", "turn_credential",
            "turn_broker_url", "turn_broker_consent", "signal_mailbox_url", "relay_only",
            "store_call_signaling",
        }
        if set(value) - allowed:
            raise ValidationError("Call settings contain unsupported fields")
        stun = value.get("stun_urls", [])
        if not isinstance(stun, list) or len(stun) > MAX_SERVERS:
            raise ValidationError("STUN server list is invalid")
        stun_urls = []
        for item in stun:
            normalized = _url(item, {"stun", "stuns"})
            if normalized not in stun_urls:
                stun_urls.append(normalized)
        turn_url = value.get("turn_url")
        if turn_url is not None:
            turn_url = _url(turn_url, {"turn", "turns"})
        username = value.get("turn_username")
        credential = value.get("turn_credential")
        if (username is None) != (credential is None):
            raise ValidationError("TURN username and credential must be set together")
        if turn_url is None and (username is not None or credential is not None):
            raise ValidationError("TURN credentials require a TURN URL")
        if username is not None and (not isinstance(username, str) or not USERNAME.fullmatch(username)):
            raise ValidationError("TURN username is invalid")
        if credential is not None and (
            not isinstance(credential, str) or not 1 <= len(credential) <= 512
        ):
            raise ValidationError("TURN credential is invalid")
        broker = value.get("turn_broker_url", DEFAULT_TURN_BROKER_URL)
        if broker is not None:
            broker = validate_broker_url(broker)
        broker_consent = value.get("turn_broker_consent", False)
        if not isinstance(broker_consent, bool):
            raise ValidationError("TURN broker consent must be boolean")
        if broker_consent and broker is None:
            raise ValidationError("TURN broker consent requires a broker")
        signal_url = value.get("signal_mailbox_url", DEFAULT_SIGNAL_MAILBOX_URL)
        if signal_url is not None:
            signal_url = validate_mailbox_url(signal_url)
        relay_only = value.get("relay_only", False)
        if not isinstance(relay_only, bool):
            raise ValidationError("Relay-only must be boolean")
        if relay_only and turn_url is None and (broker is None or not broker_consent):
            raise ValidationError("Relay-only requires a consented TURN server")
        store_call_signaling = value.get("store_call_signaling", True)
        if not isinstance(store_call_signaling, bool):
            raise ValidationError("Call signaling storage must be boolean")
        return cls(
            stun_urls=stun_urls,
            turn_url=turn_url,
            turn_username=username,
            turn_credential=credential,
            turn_broker_url=broker,
            turn_broker_consent=broker_consent,
            signal_mailbox_url=signal_url,
            relay_only=relay_only,
            store_call_signaling=store_call_signaling,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stun_urls": list(self.stun_urls),
            "turn_url": self.turn_url,
            "turn_username": self.turn_username,
            "turn_credential": self.turn_credential,
            "turn_broker_url": self.turn_broker_url,
            "turn_broker_consent": self.turn_broker_consent,
            "signal_mailbox_url": self.signal_mailbox_url,
            "relay_only": self.relay_only,
            "store_call_signaling": self.store_call_signaling,
        }

    def public(self) -> dict[str, Any]:
        return {
            "stun_urls": list(self.stun_urls),
            "turn_url": self.turn_url,
            "turn_username": self.turn_username,
            "turn_configured": self.turn_url is not None,
            "turn_broker_url": self.turn_broker_url,
            "turn_broker_configured": self.turn_broker_url is not None,
            "turn_broker_consent": self.turn_broker_consent,
            "turn_broker_default_url": DEFAULT_TURN_BROKER_URL,
            "signal_mailbox_url": self.signal_mailbox_url,
            "signal_mailbox_default_url": _default_signal_mailbox(),
            "relay_only": self.relay_only,
            "store_call_signaling": self.store_call_signaling,
        }

    def ice_servers(self) -> list[dict[str, Any]]:
        servers: list[dict[str, Any]] = []
        if self.stun_urls:
            servers.append({"urls": list(self.stun_urls)})
        if self.turn_url is not None and self.turn_username is not None:
            servers.append(
                {
                    "urls": [self.turn_url],
                    "username": self.turn_username,
                    "credential": self.turn_credential,
                }
            )
        return servers

    def rtc_configuration(self) -> dict[str, Any]:
        return {
            "iceServers": self.ice_servers(),
            "iceTransportPolicy": "relay" if self.relay_only else "all",
        }


def _default_signal_mailbox() -> str | None:
    return validate_mailbox_url(DEFAULT_SIGNAL_MAILBOX_URL) if DEFAULT_SIGNAL_MAILBOX_URL else None


def validate_broker_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("TURN credential broker URL is invalid")
    value = value.strip()
    if not 1 <= len(value) <= 512 or not value.startswith("https://"):
        raise ValidationError("TURN credential broker URL must use HTTPS")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValidationError("TURN credential broker URL is invalid")
    return value


def validate_mailbox_url(value: Any) -> str:
    value = validate_broker_url(value).rstrip("/")
    try:
        parsed = urlsplit(value)
        if parsed.query or parsed.port == 0:
            raise ValueError()
    except ValueError:
        raise ValidationError("Signaling mailbox URL is invalid") from None
    return value


def _url(value: Any, schemes: set[str]) -> str:
    if not isinstance(value, str):
        raise ValidationError("Call server URL is invalid")
    value = value.strip()
    if len(value) > 512:
        raise ValidationError("Call server URL is invalid")
    parsed = URL.fullmatch(value)
    if parsed is None:
        raise ValidationError("Call server URL is invalid")
    scheme = parsed.group(1).lower()
    if scheme not in schemes:
        raise ValidationError("Call server URL scheme is invalid")
    if parsed.group(4) is not None and scheme not in {"turn", "turns"}:
        raise ValidationError("Only TURN URLs may specify a transport")
    if not HOST.fullmatch(parsed.group(2)):
        raise ValidationError("Call server host is invalid")
    port = parsed.group(3)
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValidationError("Call server port is invalid")
    return value
