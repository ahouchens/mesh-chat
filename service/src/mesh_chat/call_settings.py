from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError

MAX_SERVERS = 8
URL = re.compile(
    r"^(stun|stuns|turn|turns):([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?$",
    re.IGNORECASE,
)
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
USERNAME = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")


@dataclass(slots=True)
class CallSettings:
    stun_urls: list[str] = field(default_factory=list)
    turn_url: str | None = None
    turn_username: str | None = None
    turn_credential: str | None = None
    relay_only: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CallSettings":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError("Call settings must be an object")
        allowed = {"stun_urls", "turn_url", "turn_username", "turn_credential", "relay_only"}
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
        relay_only = value.get("relay_only", False)
        if not isinstance(relay_only, bool):
            raise ValidationError("Relay-only must be boolean")
        if relay_only and turn_url is None:
            raise ValidationError("Relay-only requires a TURN server")
        return cls(stun_urls, turn_url, username, credential, relay_only)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stun_urls": list(self.stun_urls),
            "turn_url": self.turn_url,
            "turn_username": self.turn_username,
            "turn_credential": self.turn_credential,
            "relay_only": self.relay_only,
        }

    def public(self) -> dict[str, Any]:
        return {
            "stun_urls": list(self.stun_urls),
            "turn_configured": self.turn_url is not None,
            "relay_only": self.relay_only,
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


def _url(value: Any, schemes: set[str]) -> str:
    if not isinstance(value, str):
        raise ValidationError("Call server URL is invalid")
    value = value.strip()
    if len(value) > 512:
        raise ValidationError("Call server URL is invalid")
    parsed = URL.fullmatch(value)
    if parsed is None:
        raise ValidationError("Call server URL is invalid")
    if parsed.group(1).lower() not in schemes:
        raise ValidationError("Call server URL scheme is invalid")
    if not HOST.fullmatch(parsed.group(2)):
        raise ValidationError("Call server host is invalid")
    port = parsed.group(3)
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValidationError("Call server port is invalid")
    return value
