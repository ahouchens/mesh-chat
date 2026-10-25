from __future__ import annotations

import json
import threading

import pytest
import RNS

from mesh_chat.errors import NativeUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.webrtc_onboarding import create_onboarding_offer, verify_onboarding_offer

FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:" + FINGERPRINT + "\r\n"
ICE = {"iceServers": [], "iceTransportPolicy": "all"}


class Host:
    def __init__(self):
        self.created = []
        self.closed = []
        self.state = {"ice_connection_state": "connected", "data_channel_state": "open"}
        self.during_create = lambda: None

    def createOffer(self, session, ice, channels):
        self.created.append((session, json.loads(ice)))
        self.during_create()
        # Deliberately use the old metadata format: service signing must use
        # the canonical fingerprint extracted from the actual SDP.
        return json.dumps({"ok": True, "sdp": SDP, "fingerprint": FINGERPRINT.removeprefix("sha-256 ")})

    def acceptOffer(self, session, offer, ice, channels):
        return self.createOffer(session, ice, channels)

    def close(self, session):
        self.closed.append(session)

    def stats(self, session):
        return json.dumps({"ok": True, "result": self.state})


def runtime():
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._dispatch_lock = threading.RLock()
    service._native_webrtc_lock = threading.RLock()
    service._native_webrtc_live = set()
    service._native_webrtc_creating = set()
    service._native_webrtc_profile_sessions = {}
    service._native_webrtc_sessions = {}
    service._webrtc_bridges = {}
    host = Host()
    service._native_webrtc_host = lambda: host
    service.profile = {"id": "profile-1", "active": True, "allow_direct_ip_disclosure": False}
    service._reconnect_profile = lambda profile: service.profile
    service._reconnect_profile_public = lambda profile: {"effective": {"ready": True}}
    service.lifecycle = "caught_up"
    service._workspace_lifecycle_state = lambda: {"state": service.lifecycle}
    service._background_availability_enabled = lambda: True
    service.emit = lambda event: None
    service.webrtc_detach = lambda bridge: service._webrtc_bridges.pop(bridge, None)
    return service, host


@pytest.mark.parametrize("answer", [False, True])
def test_native_fingerprint_can_sign_a_document_verified_by_the_real_parser(answer):
    service, _ = runtime()
    if answer:
        result = service.native_webrtc_accept("native-session", SDP, ICE, [])
    else:
        result = service.native_webrtc_offer("native-session", ICE, [])
    assert result["fingerprint"] == FINGERPRINT
    document = create_onboarding_offer(RNS.Identity(), session_id="a" * 32,
                                      sdp=result["sdp"], dtls_fingerprint=result["fingerprint"])
    assert verify_onboarding_offer(document).dtls_fingerprint == FINGERPRINT


@pytest.mark.parametrize("state", ["failed", "closed"])
def test_native_stats_and_events_stop_claiming_a_failed_bridge_is_attached(state):
    service, host = runtime()
    service._native_webrtc_sessions["native-session"] = "bridge"
    service._webrtc_bridges["bridge"] = object()
    assert service.native_webrtc_stats("native-session")["attached"]
    host.state["ice_connection_state"] = state
    assert not service.native_webrtc_stats("native-session")["attached"]
    service._handle_native_webrtc_event("ice", "native-session", state)
    assert not service._native_webrtc_sessions
    assert not service._webrtc_bridges


def test_channel_closure_detaches_even_if_the_peer_ice_state_is_connected():
    service, host = runtime()
    service._native_webrtc_sessions["native-session"] = "bridge"
    host.state["data_channel_state"] = "closed"
    assert not service.native_webrtc_stats("native-session")["attached"]
    service._handle_native_webrtc_event("channel", "native-session", "mesh-reticulum:closed")
    assert not service._native_webrtc_sessions


def test_profile_reservation_prevents_overlapping_native_creation_and_is_released():
    service, host = runtime()
    service.native_webrtc_offer("first-session", ICE, [], "profile-1")
    with pytest.raises(NativeUnavailable, match="already has a peer"):
        service.native_webrtc_accept("second-session", SDP, ICE, [], "profile-1")
    assert len(host.created) == 1
    assert host.created[0][1]["iceTransportPolicy"] == "relay"
    service.native_webrtc_close("first-session")
    service.native_webrtc_accept("second-session", SDP, ICE, [], "profile-1")
    assert service.native_reconnect_session("profile-1") == "second-session"


@pytest.mark.parametrize("lifecycle,background", [("caught_up", True), ("background_available", False)])
def test_creation_cannot_cross_the_foreground_background_ownership_boundary(lifecycle, background):
    service, host = runtime()
    service.lifecycle = lifecycle
    with pytest.raises(NativeUnavailable, match="ownership changed"):
        service.native_webrtc_offer("native-session", ICE, [], "profile-1", background=background)
    assert not host.created


def test_close_during_native_creation_retires_the_late_result_and_releases_reservation():
    service, host = runtime()
    entered, release = threading.Event(), threading.Event()
    failures = []
    def wait():
        entered.set()
        assert release.wait(2)
    host.during_create = wait
    def create():
        try:
            service.native_webrtc_offer("native-session", ICE, [], "profile-1")
        except NativeUnavailable as error:
            failures.append(str(error))
    worker = threading.Thread(target=create, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        service.close_native_reconnect_session("profile-1")
        with pytest.raises(NativeUnavailable, match="already has a peer"):
            service.native_webrtc_accept("second-session", SDP, ICE, [], "profile-1")
    finally:
        release.set()
        worker.join(2)
    assert failures == ["Native WebRTC creation was cancelled"]
    assert host.closed.count("native-session") == 2
    assert not service._native_webrtc_live
    assert service.native_reconnect_session("profile-1") is None


def test_a_late_open_callback_cannot_resurrect_a_closed_session():
    service, host = runtime()
    attached = []
    service.webrtc_attach_native = lambda session: attached.append(session)
    service.native_webrtc_offer("native-session", ICE, [])
    service.native_webrtc_close("native-session")
    service._handle_native_webrtc_event("open", "native-session", "mesh-reticulum")
    assert not attached
