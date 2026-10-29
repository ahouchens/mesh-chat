from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mesh_chat.call_settings import CallSettings, DEFAULT_TURN_BROKER_URL
from mesh_chat.service import MeshChatService


@pytest.mark.parametrize("role", ["offer", "answer"])
def test_mobile_reports_disabled_mailbox_without_fetching_or_exposing_code(tmp_path, monkeypatch, role):
    import RNS
    from mesh_chat import mobile_bridge
    from test_workspace_service import _service

    service, _ = _service(tmp_path, RNS.Identity(), "Android")
    try:
        service._call_settings = CallSettings(signal_mailbox_url=None)
        monkeypatch.setattr(mobile_bridge, "_service", service)
        fetch = Mock()
        monkeypatch.setattr("mesh_chat.service.fetch_signal", fetch)
        response = json.loads(mobile_bridge.command(json.dumps({
            "command": "signal_fetch", "payload": {"session_id": "MESHPAIR2.private-code", "role": role},
        })))
        assert response == {"ok": False, "error": {"code": "mailbox_not_configured"}}
        fetch.assert_not_called()
        assert service._call_settings.signal_mailbox_url is None
    finally:
        service.close()


def test_mobile_can_enable_default_mailbox_and_retry_same_pairing_code(tmp_path, monkeypatch):
    import RNS
    from mesh_chat import mobile_bridge, signal_mailbox
    from mesh_chat.webrtc_onboarding import create_onboarding_offer
    from test_reconnect_service import SDP, FINGERPRINT
    from test_signal_mailbox import FakeResponse
    from test_workspace_service import _service

    service, _ = _service(tmp_path, RNS.Identity(), "Android")
    try:
        service._call_settings = CallSettings(signal_mailbox_url=None, store_call_signaling=False)
        monkeypatch.setattr(mobile_bridge, "_service", service)
        base = service.call_settings()["signal_mailbox_default_url"]
        code = signal_mailbox.create_pairing(base)
        context = signal_mailbox.parse_pairing(code, base)
        document = create_onboarding_offer(RNS.Identity(), session_id="a" * 32, sdp=SDP, dtls_fingerprint=FINGERPRINT)
        encrypted = signal_mailbox.seal(document, context["secret"], context["session"], "offer")
        opened = Mock(return_value=FakeResponse(encrypted))
        monkeypatch.setattr(signal_mailbox, "_open", opened)

        def command(name, **payload):
            return json.loads(mobile_bridge.command(json.dumps({"command": name, "payload": payload})))

        assert command("signal_fetch", session_id=code, role="offer")["error"]["code"] == "mailbox_not_configured"
        opened.assert_not_called()
        update = command("update_call_settings", **{**service._call_settings.to_dict(), "signal_mailbox_url": base})
        assert update["ok"]
        assert update["result"]["store_call_signaling"] is False
        fetched = command("signal_fetch", session_id=code, role="offer")
        assert fetched["ok"], fetched
        assert fetched["result"]["document"] == document
        assert len(service._signal_contexts()) == 1
        opened.assert_called_once()
    finally:
        service.close()


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

    import RNS
    from mesh_chat.webrtc_onboarding import create_onboarding_offer
    from test_reconnect_service import SDP, FINGERPRINT
    identity = RNS.Identity()
    service._require_profile = lambda: {"destination_hash": RNS.Destination.hash(identity, "lxmf", "delivery").hex()}
    document = create_onboarding_offer(identity, session_id="a" * 24, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    published = service._execute("signal_publish", {"document": document, "role": "offer"})
    assert published["ok"] is True
    assert published["session_id"].startswith("MESHPAIR2.")
    fetched = service._execute("signal_fetch", {"session_id": published["session_id"], "role": "answer"})
    assert fetched["ok"] is True
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
