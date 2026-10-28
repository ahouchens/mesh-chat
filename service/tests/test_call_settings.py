from __future__ import annotations

import pytest

from mesh_chat.call_settings import CallSettings, DEFAULT_SIGNAL_MAILBOX_URL, DEFAULT_TURN_BROKER_URL
from mesh_chat.errors import ValidationError


def test_defaults_use_google_stun_but_no_turn() -> None:
    settings = CallSettings.from_dict(None)
    assert settings.public() == {
        "stun_urls": ["stun:stun.l.google.com:19302"],
        "turn_url": None,
        "turn_username": None,
        "turn_configured": False,
        "turn_broker_url": DEFAULT_TURN_BROKER_URL,
        "turn_broker_configured": DEFAULT_TURN_BROKER_URL is not None,
        "turn_broker_consent": False,
        "turn_broker_default_url": DEFAULT_TURN_BROKER_URL,
        "signal_mailbox_url": DEFAULT_SIGNAL_MAILBOX_URL,
        "signal_mailbox_default_url": DEFAULT_SIGNAL_MAILBOX_URL,
        "relay_only": False,
        "store_call_signaling": True,
    }
    assert settings.ice_servers() == [{"urls": ["stun:stun.l.google.com:19302"]}]


def test_user_can_replace_or_clear_the_default_stun_server() -> None:
    cleared = CallSettings.from_dict({"stun_urls": [], "relay_only": False})
    assert cleared.ice_servers() == []
    custom = CallSettings.from_dict(
        {"stun_urls": ["stun:stun.example.org:3478"], "relay_only": False}
    )
    assert custom.ice_servers() == [{"urls": ["stun:stun.example.org:3478"]}]


def test_operator_mailbox_default_preserves_explicit_none_and_custom_endpoints(monkeypatch):
    from mesh_chat import call_settings
    default = "https://signal.example.test"
    monkeypatch.setattr(call_settings, "DEFAULT_SIGNAL_MAILBOX_URL", default)
    assert CallSettings.from_dict(None).signal_mailbox_url == default
    assert CallSettings.from_dict({}).signal_mailbox_url == default
    disabled = CallSettings.from_dict({"signal_mailbox_url": None})
    assert disabled.signal_mailbox_url is None
    assert disabled.public()["signal_mailbox_default_url"] == default
    assert CallSettings.from_dict(disabled.to_dict()).signal_mailbox_url is None
    assert CallSettings.from_dict({"signal_mailbox_url": "https://custom.example.test"}).signal_mailbox_url == "https://custom.example.test"
    assert disabled.turn_broker_consent is False


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
        "turn_broker_url": DEFAULT_TURN_BROKER_URL,
        "turn_broker_configured": DEFAULT_TURN_BROKER_URL is not None,
        "turn_broker_consent": False,
        "turn_broker_default_url": DEFAULT_TURN_BROKER_URL,
        "signal_mailbox_url": DEFAULT_SIGNAL_MAILBOX_URL,
        "signal_mailbox_default_url": DEFAULT_SIGNAL_MAILBOX_URL,
        "relay_only": True,
        "store_call_signaling": True,
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
            "turn_broker_consent": True,
            "relay_only": True,
        }
    )
    assert settings.turn_broker_url == "https://turn.example.workers.dev/credentials"
    assert settings.public()["turn_broker_configured"] is True
    assert settings.public()["turn_broker_consent"] is True
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


def test_call_signaling_storage_defaults_on_and_can_be_disabled() -> None:
    assert CallSettings.from_dict(None).store_call_signaling is True
    disabled = CallSettings.from_dict(
        {
            "stun_urls": [],
            "relay_only": False,
            "store_call_signaling": False,
        }
    )
    assert disabled.store_call_signaling is False
    assert disabled.public()["store_call_signaling"] is False
    with pytest.raises(ValidationError):
        CallSettings.from_dict({"store_call_signaling": "yes"})


def test_turn_credentials_require_turn() -> None:
    with pytest.raises(ValidationError):
        CallSettings.from_dict({"turn_username": "user", "turn_credential": "secret"})


@pytest.mark.parametrize("url", ["https://signal.example.test?room=secret", "https://signal.example.test:0", "https://signal.example.test:invalid"])
def test_mailbox_rejects_query_strings_and_invalid_ports(url):
    with pytest.raises(ValidationError):
        CallSettings.from_dict({"signal_mailbox_url": url})


def test_mailbox_normalizes_trailing_slash():
    assert CallSettings.from_dict({"signal_mailbox_url": "https://signal.example.test/"}).signal_mailbox_url == "https://signal.example.test"


def test_operator_default_is_normalized_for_new_profiles(monkeypatch):
    from mesh_chat import call_settings

    monkeypatch.setattr(call_settings, "DEFAULT_SIGNAL_MAILBOX_URL", "https://signal.example.test/")
    settings = CallSettings.from_dict(None)
    assert settings.signal_mailbox_url == "https://signal.example.test"
    assert settings.public()["signal_mailbox_default_url"] == settings.signal_mailbox_url
