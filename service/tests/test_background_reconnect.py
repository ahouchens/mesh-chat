from __future__ import annotations

from typing import Any

from mesh_chat.background_reconnect import BackgroundReconnectSupervisor


class Service:
    def __init__(self, preferred: bool) -> None:
        self.preferred = preferred
        self.published: list[tuple[str, str, str]] = []
        self.calls: list[str] = []

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

    def native_webrtc_offer(self, session_id: str, ice: Any, channels: Any) -> dict[str, Any]:
        self.calls.append("native_offer")
        return {"ok": True, "sdp": "native-offer-sdp", "fingerprint": "sha-256 AA"}

    def native_webrtc_accept(
        self, session_id: str, offer_sdp: str, ice: Any, channels: Any
    ) -> dict[str, Any]:
        self.calls.append("native_accept")
        return {"ok": True, "sdp": "native-answer-sdp", "fingerprint": "sha-256 BB"}

    def native_webrtc_apply_answer(self, session_id: str, answer_sdp: str) -> dict[str, Any]:
        self.calls.append("native_apply")
        return {"ok": True}

    def native_webrtc_stats(self, session_id: str) -> dict[str, Any]:
        return {"attached": True, "session_id": session_id}

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
