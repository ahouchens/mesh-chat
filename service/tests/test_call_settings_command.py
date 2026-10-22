from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from mesh_chat.call_settings import CallSettings, DEFAULT_TURN_BROKER_URL
from mesh_chat.service import MeshChatService


def test_update_call_settings_accepts_broker_consent_payload() -> None:
    service = object.__new__(MeshChatService)
    service._call_settings = CallSettings.from_dict(None)
    service._turn_ice_lock = threading.Lock()
    service._turn_ice_cache = None
    service._changed = lambda: None
    service.store = SimpleNamespace(put=lambda *args, **kwargs: None)
    service.calls = SimpleNamespace(set_persist=lambda *_args, **_kwargs: None)
    service._call_identity = lambda: None

    result = service._execute(
        "update_call_settings",
        {
            "stun_urls": ["stun:stun.l.google.com:19302"],
            "turn_url": None,
            "turn_username": None,
            "turn_credential": None,
            "turn_broker_url": DEFAULT_TURN_BROKER_URL,
            "turn_broker_consent": True,
            "signal_mailbox_url": "https://signal.example.workers.dev",
            "relay_only": False,
        },
    )

    assert result["turn_broker_consent"] is True
    assert result["turn_broker_configured"] is True
    assert result["signal_mailbox_url"] == "https://signal.example.workers.dev"

    enabled = service._execute(
        "update_call_settings",
        {
            "stun_urls": result["stun_urls"],
            "turn_url": result["turn_url"],
            "turn_username": result["turn_username"],
            "turn_credential": None,
            "turn_broker_url": result["turn_broker_url"],
            "turn_broker_consent": True,
            "signal_mailbox_url": result["signal_mailbox_url"],
            "relay_only": False,
        },
    )
    assert enabled["signal_mailbox_url"] == "https://signal.example.workers.dev"


def test_signal_commands_require_configured_mailbox(monkeypatch) -> None:
    service = object.__new__(MeshChatService)
    service._call_settings = CallSettings.from_dict(
        {
            "stun_urls": ["stun:example.org"],
            "signal_mailbox_url": "https://signal.example.workers.dev",
            "relay_only": False,
        }
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "mesh_chat.service.publish_signal",
        lambda base, document, role, **kwargs: calls.append(("publish", base, role)) or {"ok": True},
    )
    monkeypatch.setattr(
        "mesh_chat.service.fetch_signal",
        lambda base, session, role, **kwargs: calls.append(("fetch", base, role)) or {"ok": True},
    )

    document = json.dumps({"session_id": "a" * 24})
    assert service._execute("signal_publish", {"document": document, "role": "offer"}) == {"ok": True}
    assert service._execute("signal_fetch", {"session_id": "a" * 24, "role": "answer"}) == {"ok": True}
    assert calls == [
        ("publish", "https://signal.example.workers.dev", "offer"),
        ("fetch", "https://signal.example.workers.dev", "answer"),
    ]


def test_update_call_settings_applies_call_record_storage() -> None:
    service = object.__new__(MeshChatService)
    service._call_settings = CallSettings.from_dict(None)
    service._turn_ice_lock = threading.Lock()
    service._turn_ice_cache = None
    service._changed = lambda: None
    service.store = SimpleNamespace(put=lambda *args, **kwargs: None)
    service.calls = SimpleNamespace(set_persist=Mock())

    result = service._execute(
        "update_call_settings",
        {
            "stun_urls": ["stun:stun.example.org"],
            "relay_only": False,
            "store_call_signaling": False,
        },
    )

    assert result["store_call_signaling"] is False
    service.calls.set_persist.assert_called_once_with(False)


def test_update_call_settings_keeps_storage_choice_when_omitted() -> None:
    service = object.__new__(MeshChatService)
    service._call_settings = CallSettings.from_dict(
        {"stun_urls": [], "relay_only": False, "store_call_signaling": False}
    )
    service._turn_ice_lock = threading.Lock()
    service._turn_ice_cache = None
    service._changed = lambda: None
    service.store = SimpleNamespace(put=lambda *args, **kwargs: None)
    service.calls = SimpleNamespace(set_persist=Mock())

    result = service._execute(
        "update_call_settings",
        {"stun_urls": [], "relay_only": False},
    )

    assert result["store_call_signaling"] is False
    service.calls.set_persist.assert_called_once_with(False)
