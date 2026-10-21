from __future__ import annotations

import threading
from types import SimpleNamespace

from mesh_chat.call_settings import CallSettings, DEFAULT_TURN_BROKER_URL
from mesh_chat.service import MeshChatService


def test_update_call_settings_accepts_broker_consent_payload() -> None:
    service = object.__new__(MeshChatService)
    service._call_settings = CallSettings.from_dict(None)
    service._turn_ice_lock = threading.Lock()
    service._turn_ice_cache = None
    service._changed = lambda: None
    service.store = SimpleNamespace(put=lambda *args, **kwargs: None)
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
            "relay_only": False,
        },
    )

    assert result["turn_broker_consent"] is True
    assert result["turn_broker_configured"] is True
