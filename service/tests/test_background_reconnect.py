from __future__ import annotations

from typing import Any
import threading

import pytest

from mesh_chat.background_reconnect import BackgroundReconnectSupervisor


class Service:
    def __init__(self, preferred: bool) -> None:
        self.preferred = preferred
        self.published: list[tuple[str, str, str]] = []
        self.calls: list[str] = []
        self._shutdown = threading.Event()
        self.lifecycle = "background_available"
        self.profile = {"id": "profile-1", "contact_id": "contact-1", "active": True,
                        "effective": {"ready": True, "preferred": preferred}}
        self.ice_configs: list[dict] = []
        self.stats = {"attached": True, "ice_connection_state": "connected", "data_channel_state": "open"}

    def reconnect_profiles(self):
        return {"profiles": [self.profile] if self.profile else []}

    def _workspace_lifecycle_state(self):
        return {"state": self.lifecycle}

    def native_reconnect_session(self, profile_id):
        return None

    def reconnect_start(self, contact_id):
        self.profile["active"] = True

    def call_ice_servers(self) -> dict[str, Any]:
        return {"iceServers": [], "iceTransportPolicy": "all"}

    def reconnect_request_create(self, contact_id: str, attempt_id: str) -> dict[str, Any]:
        self.calls.append("request")
        return {"document": "request-document"}

    def reconnect_fetch(self, profile_id: str, role: str) -> dict[str, Any] | None:
        if role == "offer":
            return {"document": "offer-document"}
        if role == "request":
            return {"document": "request-document"}
        if role == "answer":
            return {"document": "answer-document"}
        return None

    def reconnect_publish(self, profile_id: str, document: str, role: str) -> None:
        self.published.append((profile_id, document, role))

    def verify_reconnect_offer(self, document: str, profile_id: str) -> dict[str, Any]:
        return {"sdp": "offer-sdp"}

    def verify_reconnect_request(self, document: str, profile_id: str) -> dict[str, Any]:
        return {"document": document}

    def verify_reconnect_answer(
        self, document: str, offer_document: str, profile_id: str
    ) -> dict[str, Any]:
        return {"sdp": "answer-sdp"}

    def reconnect_answer_create(
        self, contact_id: str, offer_document: str, sdp: str, fingerprint: str
    ) -> dict[str, Any]:
        self.calls.append("answer")
        return {"document": "answer-document"}

    def reconnect_offer_create(
        self, contact_id: str, request_document: str, sdp: str, fingerprint: str
    ) -> dict[str, Any]:
        self.calls.append("offer")
        return {"document": "offer-document"}

    def native_webrtc_offer(self, session_id: str, ice: Any, channels: Any, profile_id=None, *, background=False) -> dict[str, Any]:
        assert profile_id == "profile-1" and background
        self.ice_configs.append(ice)
        self.calls.append("native_offer")
        return {"ok": True, "sdp": "native-offer-sdp", "fingerprint": "sha-256 AA"}

    def native_webrtc_accept(
        self, session_id: str, offer_sdp: str, ice: Any, channels: Any, profile_id=None, *, background=False,
    ) -> dict[str, Any]:
        assert profile_id == "profile-1" and background
        self.ice_configs.append(ice)
        self.calls.append("native_accept")
        return {"ok": True, "sdp": "native-answer-sdp", "fingerprint": "sha-256 BB"}

    def native_webrtc_apply_answer(self, session_id: str, answer_sdp: str) -> dict[str, Any]:
        self.calls.append("native_apply")
        return {"ok": True}

    def native_webrtc_stats(self, session_id: str) -> dict[str, Any]:
        return {**self.stats, "session_id": session_id}

    def native_webrtc_close(self, session_id: str) -> dict[str, Any]:
        self.calls.append(f"close:{session_id}")
        return {"state": "closed"}


def test_preferred_side_requests_then_answers_with_native_transport() -> None:
    service = Service(preferred=True)
    supervisor = BackgroundReconnectSupervisor(service)
    session_id = supervisor._attempt(
        {
            "id": "profile-1",
            "contact_id": "contact-1",
            "effective": {"ready": True, "preferred": True},
        }
    )
    assert session_id.startswith("background-")
    assert service.calls == ["request", "native_accept", "answer"]
    assert service.published == [
        ("profile-1", "request-document", "request"),
        ("profile-1", "answer-document", "answer"),
    ]


def test_non_preferred_side_offers_with_native_transport() -> None:
    service = Service(preferred=False)
    supervisor = BackgroundReconnectSupervisor(service)
    session_id = supervisor._attempt(
        {
            "id": "profile-1",
            "contact_id": "contact-1",
            "effective": {"ready": True, "preferred": False},
        }
    )
    assert session_id.startswith("background-")
    assert service.calls == ["native_offer", "offer", "native_apply"]
    assert service.published == [("profile-1", "offer-document", "offer")]


def test_stop_closes_native_sessions_instead_of_leaking_them() -> None:
    service = Service(preferred=False)
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "background-session-1"
    supervisor._attempt_session_id = "background-session-2"
    supervisor.stop()
    assert "close:background-session-1" in service.calls
    assert "close:background-session-2" in service.calls


@pytest.mark.parametrize("preferred", [False, True])
@pytest.mark.parametrize("disclose", [False, True])
def test_background_ice_obeys_contact_disclosure_consent(preferred, disclose):
    service = Service(preferred)
    service.profile["allow_direct_ip_disclosure"] = disclose
    BackgroundReconnectSupervisor(service)._attempt(service.profile)
    assert service.ice_configs[0]["iceTransportPolicy"] == ("all" if disclose else "relay")


@pytest.mark.parametrize("state", ["foreground", "active", "reconciling", "caught_up"])
def test_foreground_states_yield_without_creating_a_second_peer(state):
    service = Service(False)
    service.lifecycle = state
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "old-session"
    supervisor._tick({})
    assert service.calls == ["close:old-session"]
    assert not supervisor._sessions


@pytest.mark.parametrize("change", ["stopped", "consent_removed", "deleted"])
def test_profile_removal_or_stop_retires_the_existing_peer(change):
    service = Service(False)
    if change == "deleted":
        service.profile = None
    elif change == "stopped":
        service.profile.update(active=False, state="stopped")
    else:
        service.profile["effective"]["ready"] = False
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "old-session"
    supervisor._tick({})
    assert service.calls == ["close:old-session"]
    assert not supervisor._sessions


@pytest.mark.parametrize("stats", [
    {"attached": False}, {"attached": True, "ice_connection_state": "failed"},
    {"attached": True, "ice_connection_state": "closed"},
])
def test_failed_session_is_closed_before_its_replacement(monkeypatch, stats):
    service = Service(False)
    service.stats = stats
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "old-session"
    def attempt(profile):
        assert service.calls == ["close:old-session"]
        return "new-session"
    monkeypatch.setattr(supervisor, "_attempt", attempt)
    supervisor._tick({})
    assert supervisor._sessions == {"profile-1": "new-session"}


def test_disconnected_peer_has_a_bounded_recovery_grace(monkeypatch):
    service = Service(False)
    service.stats["ice_connection_state"] = "disconnected"
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "old-session"
    now = [0.0]
    monkeypatch.setattr("mesh_chat.background_reconnect.time.monotonic", lambda: now[0])
    monkeypatch.setattr(supervisor, "_attempt", lambda profile: "new-session")
    supervisor._tick({})
    now[0] = 9.0
    supervisor._tick({})
    assert not service.calls
    now[0] = 10.0
    supervisor._tick({})
    assert service.calls == ["close:old-session"]


@pytest.mark.parametrize("change", ["stopped", "foreground", "disabled"])
def test_cancel_during_native_creation_closes_late_result_without_publishing(monkeypatch, change):
    service = Service(False)
    supervisor = BackgroundReconnectSupervisor(service)
    def offer(*args, **kwargs):
        if change == "stopped":
            service.profile.update(active=False, state="stopped")
        elif change == "foreground":
            service.lifecycle = "caught_up"
        else:
            supervisor.stop()
        return {"sdp": "late-offer", "fingerprint": "sha-256 AA"}
    monkeypatch.setattr(service, "native_webrtc_offer", offer)
    with pytest.raises(RuntimeError):
        supervisor._attempt(service.profile)
    assert not service.published
    assert any(call.startswith("close:background-") for call in service.calls)
    assert supervisor._attempt_session_id is None


def test_background_reuses_a_healthy_foreground_created_native_peer(monkeypatch):
    service = Service(False)
    monkeypatch.setattr(service, "native_reconnect_session", lambda profile: "foreground-session")
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._tick({})
    assert not service.calls
    assert not supervisor._sessions
