from __future__ import annotations

import json

import pytest

from mesh_chat.errors import NetworkUnavailable
from mesh_chat.turn_credentials import fetch_ice_servers, validate_ice_servers

CLOUDFLARE = {
    "iceServers": [
        {"urls": ["stun:stun.cloudflare.com:3478"]},
        {
            "urls": [
                "turn:turn.cloudflare.com:3478?transport=udp",
                "turn:turn.cloudflare.com:443?transport=udp",
                "turn:turn.cloudflare.com:3478?transport=tcp",
                "turns:turn.cloudflare.com:443?transport=tcp",
            ],
            "username": "user",
            "credential": "secret",
        },
    ]
}


def test_cloudflare_ice_servers_are_validated_and_preserved() -> None:
    servers = validate_ice_servers(CLOUDFLARE)
    assert servers[0]["urls"] == ["stun:stun.cloudflare.com:3478"]
    assert servers[1]["username"] == "user"
    assert "turns:turn.cloudflare.com:443?transport=tcp" in servers[1]["urls"]


def test_broker_response_requires_a_turn_server() -> None:
    with pytest.raises(NetworkUnavailable):
        validate_ice_servers({"iceServers": [{"urls": ["stun:stun.cloudflare.com:3478"]}]})


def test_broker_response_rejects_unknown_url_schemes() -> None:
    with pytest.raises(NetworkUnavailable):
        validate_ice_servers({"iceServers": [{"urls": ["https://example.org"]}]})


def test_fetch_broker_adds_ttl_and_returns_ice_servers(monkeypatch) -> None:
    requested = {}

    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps(CLOUDFLARE).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout, context=None):
        requested["url"] = request.full_url
        requested["timeout"] = timeout
        return Response()

    monkeypatch.setattr("mesh_chat.turn_credentials.urllib.request.urlopen", urlopen)
    servers = fetch_ice_servers("https://turn.example.workers.dev/credentials")
    assert requested["url"].endswith("?ttl=3600")
    assert servers[1]["username"] == "user"
