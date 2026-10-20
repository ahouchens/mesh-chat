from __future__ import annotations

import pytest

from mesh_chat.call_settings import CallSettings
from mesh_chat.errors import ValidationError


def test_defaults_use_google_stun_but_no_turn() -> None:
    settings = CallSettings.from_dict(None)
    assert settings.public() == {
        "stun_urls": ["stun:stun.l.google.com:19302"],
        "turn_url": None,
        "turn_username": None,
        "turn_configured": False,
        "turn_broker_url": None,
        "turn_broker_configured": False,
        "turn_broker_default_url": None,
        "relay_only": False,
    }
    assert settings.ice_servers() == [{"urls": ["stun:stun.l.google.com:19302"]}]


def test_user_can_replace_or_clear_the_default_stun_server() -> None:
    cleared = CallSettings.from_dict({"stun_urls": [], "relay_only": False})
    assert cleared.ice_servers() == []
    custom = CallSettings.from_dict(
        {"stun_urls": ["stun:stun.example.org:3478"], "relay_only": False}
    )
    assert custom.ice_servers() == [{"urls": ["stun:stun.example.org:3478"]}]


def test_stun_and_turn_are_normalized_and_secretly_scoped() -> None:
    settings = CallSettings.from_dict(
        {
            "stun_urls": ["stun:stun.example.org:3478"],
            "turn_url": "turns:turn.example.org:5349",
            "turn_username": "mesh",
            "turn_credential": "short-lived-secret",
            "relay_only": True,
        }
    )
    assert settings.public() == {
        "stun_urls": ["stun:stun.example.org:3478"],
        "turn_url": "turns:turn.example.org:5349",
        "turn_username": "mesh",
        "turn_configured": True,
        "turn_broker_url": None,
        "turn_broker_configured": False,
        "turn_broker_default_url": None,
        "relay_only": True,
    }
    assert "credential" not in settings.public()
    assert settings.rtc_configuration() == {
        "iceServers": [
            {"urls": ["stun:stun.example.org:3478"]},
            {
                "urls": ["turns:turn.example.org:5349"],
                "username": "mesh",
                "credential": "short-lived-secret",
            },
        ],
        "iceTransportPolicy": "relay",
    }


def test_turn_tcp_443_url_is_supported() -> None:
    settings = CallSettings.from_dict(
        {
            "stun_urls": [],
            "turn_url": "turn:relay.example.org:443?transport=tcp",
            "turn_username": "mesh",
            "turn_credential": "secret",
        }
    )
    assert settings.ice_servers() == [
        {
            "urls": ["turn:relay.example.org:443?transport=tcp"],
            "username": "mesh",
            "credential": "secret",
        }
    ]


def test_cloudflare_broker_url_is_stored_and_exposed_without_secrets() -> None:
    settings = CallSettings.from_dict(
        {
            "stun_urls": [],
            "turn_broker_url": "https://turn.example.workers.dev/credentials",
            "relay_only": True,
        }
    )
    assert settings.turn_broker_url == "https://turn.example.workers.dev/credentials"
    assert settings.public()["turn_broker_configured"] is True
    assert "turn_credential" not in settings.public()
    assert settings.rtc_configuration()["iceTransportPolicy"] == "relay"


@pytest.mark.parametrize(
    "value",
    [
        {"turn_broker_url": "http://turn.example.workers.dev/credentials"},
        {"turn_broker_url": "https://user:pass@turn.example/credentials"},
        {"turn_broker_url": "https://turn.example/credentials#fragment"},
        {"turn_broker_url": "not-a-url"},
    ],
)
def test_invalid_turn_broker_urls_fail_closed(value: dict) -> None:
    with pytest.raises(ValidationError):
        CallSettings.from_dict(value)


@pytest.mark.parametrize(
    "value",
    [
        {"stun_urls": ["http://stun.example.org"]},
        {"stun_urls": ["stun:bad host"]},
        {"stun_urls": ["stun:example.org/path"]},
        {"stun_urls": ["stun:example.org?transport=tcp"]},
        {"stun_urls": ["stun:example.org"] * 9},
        {"turn_url": "turn:example.org", "turn_username": "user"},
        {"turn_url": "turn:example.org", "turn_username": "user", "turn_credential": ""},
        {"relay_only": True},
    ],
)
def test_invalid_call_settings_fail_closed(value: dict) -> None:
    with pytest.raises(ValidationError):
        CallSettings.from_dict(value)


def test_turn_credentials_require_turn() -> None:
    with pytest.raises(ValidationError):
        CallSettings.from_dict({"turn_username": "user", "turn_credential": "secret"})
