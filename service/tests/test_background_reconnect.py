from __future__ import annotations

from typing import Any
import threading
import time

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
        self.attempt_id = attempt_id
        return {"document": "request-document", "attempt_id": attempt_id, "expires_at": time.time() + 3600}

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
        return {"sdp": "offer-sdp", "attempt_id": self.attempt_id}

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


def test_timeout_reuses_request_so_a_delayed_peer_can_catch_up(monkeypatch):
    service = Service(True)
    supervisor = BackgroundReconnectSupervisor(service)
    fetch = supervisor._fetch
    def timeout(*args):
        raise TimeoutError("Peer is still answering the previous request")
    monkeypatch.setattr(supervisor, "_fetch", timeout)
    with pytest.raises(TimeoutError):
        supervisor._attempt(service.profile)
    delayed_attempt = service.attempt_id
    monkeypatch.setattr(supervisor, "_fetch", fetch)
    monkeypatch.setattr(service, "verify_reconnect_offer", lambda *_: {
        "sdp": "delayed-offer", "attempt_id": delayed_attempt})
    supervisor._attempt(service.profile)
    assert service.calls.count("request") == 1
    assert "native_accept" in service.calls
    assert not supervisor._requests


def test_expired_background_request_is_replaced():
    service = Service(True)
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._requests["profile-1"] = {"document": "expired", "attempt_id": "old", "expires_at": 0}
    supervisor._attempt(service.profile)
    assert service.calls.count("request") == 1
    assert all(document != "expired" for _, document, _ in service.published)


def test_recovery_ignores_request_for_the_connection_that_already_succeeded(monkeypatch):
    service = Service(False)
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._attempt(service.profile)
    fetch = service.reconnect_fetch
    requests = iter(["request-document", "fresh-request-document"])
    offered = []
    create = service.reconnect_offer_create

    def mailbox(profile_id, role):
        if role == "request":
            return {"document": next(requests)}
        return fetch(profile_id, role)

    def offer(contact_id, document, *args):
        offered.append(document)
        return create(contact_id, document, *args)

    monkeypatch.setattr(service, "reconnect_fetch", mailbox)
    monkeypatch.setattr(service, "reconnect_offer_create", offer)
    monkeypatch.setattr(supervisor._stop, "wait", lambda _: None)
    supervisor._attempt(service.profile)
    assert offered == ["fresh-request-document"]


@pytest.mark.parametrize("preferred", [True, False])
def test_slow_native_gathering_does_not_consume_the_next_protocol_wait(monkeypatch, preferred):
    service = Service(preferred)
    supervisor = BackgroundReconnectSupervisor(service)
    now = [0.0]
    monkeypatch.setattr("mesh_chat.background_reconnect.time.monotonic", lambda: now[0])
    monkeypatch.setattr(supervisor._stop, "wait", lambda delay: now.__setitem__(0, now[0] + delay))
    fetch = service.reconnect_fetch

    def delayed_document(profile_id, role):
        ready_at = 75 if role == "answer" else 30
        return fetch(profile_id, role) if now[0] >= ready_at else None

    monkeypatch.setattr(service, "reconnect_fetch", delayed_document)
    method = "native_webrtc_accept" if preferred else "native_webrtc_offer"
    create = getattr(service, method)

    def gather(*args, **kwargs):
        now[0] += 20
        return create(*args, **kwargs)

    monkeypatch.setattr(service, method, gather)
    monkeypatch.setattr(service, "native_webrtc_stats", lambda _: {
        "attached": now[0] >= 80, "ice_connection_state": "connected"})
    assert supervisor._attempt(service.profile).startswith("background-")
    assert now[0] == 80


def test_stop_closes_native_sessions_instead_of_leaking_them() -> None:
    service = Service(preferred=False)
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "background-session-1"
    supervisor._attempt_sessions["profile-2"] = "background-session-2"
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
    assert not service.calls
    assert supervisor._sessions == {"profile-1": "old-session"}


@pytest.mark.parametrize("change", ["stopped", "consent_removed", "deleted"])
def test_profile_removal_or_stop_retires_the_existing_peer(change):
    service = Service(False)
    if change == "deleted":
        service.profile = None
    elif change == "stopped":
        service.profile.update(active=False, state="stopped")
    else:
        service.profile["effective"]["ready"] = False
        service.profile["effective"]["reasons"] = ["consent_missing"]
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "old-session"
    supervisor._tick({})
    assert service.calls == ["close:old-session"]
    assert not supervisor._sessions


@pytest.mark.parametrize("lifecycle", ["background_available", "caught_up"])
def test_mailbox_loss_preserves_an_established_peer_without_new_negotiation(lifecycle):
    service = Service(False)
    service.lifecycle = lifecycle
    service.profile["effective"].update(ready=False, reasons=["mailbox_not_configured"])
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "healthy-peer"
    supervisor._tick({})
    assert not service.calls
    assert supervisor._sessions == {"profile-1": "healthy-peer"}


@pytest.mark.parametrize("reason", ["consent_missing", "peer_consent_missing", "workspace_peer_inactive"])
def test_mailbox_loss_does_not_override_consent_or_workspace_revocation(reason):
    service = Service(False)
    service.profile["effective"].update(ready=False, reasons=["mailbox_not_configured", reason])
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "revoked-peer"
    supervisor._tick({})
    assert service.calls == ["close:revoked-peer"]


def test_mailbox_loss_still_retires_a_failed_transport():
    service = Service(False)
    service.profile["effective"].update(ready=False, reasons=["mailbox_not_configured"])
    service.stats["ice_connection_state"] = "failed"
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "failed-peer"
    supervisor._tick({})
    assert service.calls == ["close:failed-peer"]
    assert not supervisor._workers


def test_failed_health_queries_retry_with_a_bounded_grace_and_reset_on_recovery(monkeypatch):
    service = Service(False)
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-1"] = "healthy-peer"
    now = [0.0]
    monkeypatch.setattr("mesh_chat.background_reconnect.time.monotonic", lambda: now[0])
    supervisor._tick({})
    healthy_stats = service.native_webrtc_stats
    def unavailable(_session):
        raise RuntimeError("temporary native query failure")
    service.native_webrtc_stats = unavailable
    supervisor._tick({})
    now[0] = 9
    supervisor._tick({})
    assert not service.calls
    service.native_webrtc_stats = healthy_stats
    supervisor._tick({})
    service.native_webrtc_stats = unavailable
    supervisor._tick({})
    now[0] = 18
    supervisor._tick({})
    assert not service.calls
    monkeypatch.setattr(supervisor, "_attempt", lambda profile: "replacement")
    now[0] = 19
    supervisor._tick({})
    for worker in list(supervisor._workers.values()):
        worker.join(2)
    assert service.calls == ["close:healthy-peer"]


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
    for worker in list(supervisor._workers.values()):
        worker.join(2)
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
    assert not supervisor._attempt_sessions


def test_background_reuses_a_healthy_foreground_created_native_peer(monkeypatch):
    service = Service(False)
    monkeypatch.setattr(service, "native_reconnect_session", lambda profile: "foreground-session")
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._tick({})
    assert not service.calls
    assert not supervisor._sessions


@pytest.mark.parametrize("preferred", [True, False])
def test_stale_mailbox_reply_is_skipped_without_recreating_the_peer(monkeypatch, preferred):
    from mesh_chat.errors import IdentityMismatch
    monkeypatch.setattr("mesh_chat.background_reconnect.POLL_SECONDS", 0)
    service = Service(preferred)
    supervisor = BackgroundReconnectSupervisor(service)
    role = "offer" if preferred else "answer"
    fetch = service.reconnect_fetch
    received = []
    def documents(profile_id, requested_role):
        if requested_role == role:
            received.append(requested_role)
            return {"document": "stale" if len(received) == 1 else "current"}
        return fetch(profile_id, requested_role)
    service.reconnect_fetch = documents
    if preferred:
        service.verify_reconnect_offer = lambda doc, _: {
            "sdp": "offer-sdp", "attempt_id": "previous" if doc == "stale" else service.attempt_id}
    else:
        def verify(document, *args):
            if document == "stale":
                raise IdentityMismatch("Answer belongs to the previous offer")
            return {"sdp": "answer-sdp"}
        service.verify_reconnect_answer = verify
    supervisor._attempt(service.profile)
    assert len(received) == 2
    assert sum(call in {"native_offer", "native_accept"} for call in service.calls) == 1
    assert not any(call.startswith("close:") for call in service.calls)


def test_offline_contacts_do_not_block_health_checks_or_other_contacts(monkeypatch):
    service = Service(False)
    profiles = [{**service.profile, "id": f"profile-{i}", "contact_id": f"contact-{i}"} for i in range(4)]
    service.reconnect_profiles = lambda: {"profiles": profiles}
    checked = []
    service.native_webrtc_stats = lambda sid: checked.append(sid) or service.stats
    supervisor = BackgroundReconnectSupervisor(service)
    supervisor._sessions["profile-3"] = "healthy"
    entered, release = threading.Event(), threading.Event()
    attempts = []
    def attempt(profile):
        attempts.append(profile["id"])
        entered.set()
        assert release.wait(2)
        raise TimeoutError("offline")
    monkeypatch.setattr(supervisor, "_attempt", attempt)
    try:
        failures = {}
        supervisor._tick(failures)
        assert entered.wait(1)
        supervisor._tick(failures)
        assert checked == ["healthy", "healthy"]
        assert len(supervisor._workers) == 2
        assert "profile-2" not in attempts
    finally:
        release.set()
        for worker in list(supervisor._workers.values()):
            worker.join(2)
    supervisor._tick(failures)
    for worker in list(supervisor._workers.values()):
        worker.join(2)
    assert "profile-2" in attempts
    assert attempts.count("profile-0") == 1


def test_health_tick_does_not_close_a_peer_still_being_negotiated():
    service = Service(False)
    supervisor = BackgroundReconnectSupervisor(service)
    service.native_reconnect_session = lambda _: "pending-peer"
    supervisor._workers["profile-1"] = object()
    supervisor._tick({})
    assert not service.calls


@pytest.mark.parametrize("preferred", [False, True])
def test_stop_retires_a_native_peer_created_after_the_initial_close(monkeypatch, preferred):
    service = Service(preferred)
    supervisor = BackgroundReconnectSupervisor(service)
    live = set()
    def close(session_id):
        live.discard(session_id)
    def create(session_id, *args, **kwargs):
        supervisor.stop()
        # A native creation already in flight can finish after stop's close.
        live.add(session_id)
        return {"sdp": "late-sdp", "fingerprint": "sha-256 AA"}
    monkeypatch.setattr(service, "native_webrtc_close", close)
    monkeypatch.setattr(service, "native_webrtc_offer", create)
    monkeypatch.setattr(service, "native_webrtc_accept", create)
    with pytest.raises(RuntimeError):
        supervisor._attempt(service.profile)
    assert not live
    assert not supervisor._attempt_sessions
