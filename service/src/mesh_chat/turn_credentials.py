from __future__ import annotations

import json
import ssl
import urllib.request
from typing import Any

try:
    import certifi
except ImportError:  # Older mobile builds may not bundle CA data yet.
    certifi = None

from .call_settings import _url, validate_broker_url
from .errors import NetworkUnavailable
from ._qualification_failure_observer import note

MAX_RESPONSE_BYTES = 64 * 1024
MAX_ICE_SERVERS = 8
MAX_URLS_PER_SERVER = 8
DEFAULT_TTL_SECONDS = 3600


def fetch_ice_servers(broker_url: str, *, timeout: float = 8.0) -> list[dict[str, Any]]:
    try:
        broker_url = validate_broker_url(broker_url)
    except Exception as error:
        note("caught", error, "broker_url")
        raise
    separator = "&" if "?" in broker_url else "?"
    try:
        request = urllib.request.Request(
            f"{broker_url}{separator}ttl={DEFAULT_TTL_SECONDS}",
            headers={
                "Accept": "application/json",
                "User-Agent": "mesh-chat-turn-broker/1",
            },
        )
    except Exception as error:
        note("caught", error, "broker_request")
        raise
    stage = "tls_context"
    try:
        context = (
            ssl.create_default_context(cafile=certifi.where())
            if certifi is not None
            else ssl.create_default_context()
        )
        stage = "broker_open"
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            try:
                stage = "broker_status"
                if response.status != 200:
                    raise NetworkUnavailable("TURN credential broker rejected the request")
                stage = "broker_read"
                body = response.read(MAX_RESPONSE_BYTES + 1)
            except Exception as error:
                note("caught", error, stage)
                raise
            finally:
                stage = "broker_open"  # A distinct context-exit failure replaces the body error.
    except NetworkUnavailable as error:
        note("caught", error, stage)
        raise
    except Exception as exc:
        note("caught", exc, stage)
        raise NetworkUnavailable("TURN credentials are unavailable") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        error = NetworkUnavailable("TURN credential broker returned too much data")
        note("caught", error, "broker_size")
        raise error
    try:
        payload = json.loads(body)
    except Exception as exc:
        note("caught", exc, "broker_json")
        raise NetworkUnavailable("TURN credential broker returned invalid JSON") from exc
    try:
        return validate_ice_servers(payload)
    except Exception as error:
        note("caught", error, "broker_validate")
        raise


def validate_ice_servers(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise NetworkUnavailable("TURN credential broker returned an invalid response")
    servers = payload.get("iceServers")
    if not isinstance(servers, list) or not 1 <= len(servers) <= MAX_ICE_SERVERS:
        raise NetworkUnavailable("TURN credential broker returned no usable ICE servers")
    result: list[dict[str, Any]] = []
    has_turn = False
    for item in servers:
        if not isinstance(item, dict) or set(item) - {"urls", "username", "credential"}:
            raise NetworkUnavailable("TURN credential broker returned an invalid server")
        urls = item.get("urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_URLS_PER_SERVER:
            raise NetworkUnavailable("TURN credential broker returned an invalid URL list")
        normalized = []
        for value in urls:
            try:
                normalized.append(_url(value, {"stun", "stuns", "turn", "turns"}))
            except Exception as exc:
                raise NetworkUnavailable("TURN credential broker returned an invalid URL") from exc
        if any(value.lower().startswith(("turn:", "turns:")) for value in normalized):
            has_turn = True
        entry: dict[str, Any] = {"urls": normalized}
        if item.get("username") is not None:
            entry["username"] = item["username"]
        if item.get("credential") is not None:
            entry["credential"] = item["credential"]
        result.append(entry)
    if not has_turn:
        raise NetworkUnavailable("TURN credential broker returned no TURN server")
    return result
