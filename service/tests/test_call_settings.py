from __future__ import annotations

import pytest

from mesh_chat.call_settings import CallSettings
from mesh_chat.errors import ValidationError


def test_defaults_are_empty_and_not_relay_only() -> None:
    settings = CallSettings.from_dict(None)
    assert settings.public() == {
        "stun_urls": [],
        "turn_configured": False,
        "relay_only": False,
    }
    assert settings.ice_servers() == []


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
        "turn_configured": True,
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


@pytest.mark.parametrize(
    "value",
    [
        {"stun_urls": ["http://stun.example.org"]},
        {"stun_urls": ["stun:bad host"]},
        {"stun_urls": ["stun:example.org/path"]},
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
