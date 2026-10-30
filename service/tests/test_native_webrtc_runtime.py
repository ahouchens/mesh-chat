from __future__ import annotations

import json
import queue
import threading
import time

import pytest
import RNS

from mesh_chat.errors import NativeUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.webrtc_onboarding import create_onboarding_offer, verify_onboarding_offer, verify_onboarding_answer

FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:" + FINGERPRINT + "\r\n"
ICE = {"iceServers": [], "iceTransportPolicy": "all"}
ONBOARDING_CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
]


class Host:
    def __init__(self):
        self.created = []
        self.closed = []
        self.state = {"ice_connection_state": "connected", "data_channel_state": "open"}
        self.during_create = lambda: None
        self.controls = []

    def sendControl(self, session, label, text):
        self.controls.append((session, label, json.loads(text)))
        return True

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
    service._native_webrtc_descriptions = {}
    service._native_webrtc_peers = {}
    service._native_webrtc_controls = {}
    service._native_webrtc_sessions = {}
    service._webrtc_bridges = {}
    host = Host()
    service._native_webrtc_host = lambda: host
    service.profile = {"id": "profile-1", "contact_id": "contact-1", "active": True, "allow_direct_ip_disclosure": False}
    service._reconnect_profile = lambda profile: service.profile
    service._reconnect_profile_public = lambda profile: {"effective": {"ready": True}}
    service.lifecycle = "caught_up"
    service._workspace_lifecycle_state = lambda: {"state": service.lifecycle}
    service._background_availability_enabled = lambda: True
    service.emit = lambda event: None
    service.webrtc_detach = lambda bridge: service._webrtc_bridges.pop(bridge, None)
    service._contact_by_destination = lambda peer: {"id": "contact-1", "destination_hash": peer}
    return service, host


@pytest.mark.parametrize("lifecycle", ["foreground", "background_available"])
def test_shared_policy_claim_has_one_owner_across_lifecycle(lifecycle):
    service, host = runtime()
    service._connection_policy = "shared-native"
    service.lifecycle = lifecycle
    with pytest.raises(NativeUnavailable):
        service.native_webrtc_offer("renderer-session", ICE, [], "profile-1")
    service.native_webrtc_offer("runtime-session", ICE, [], "profile-1", runtime_owned=True)
    assert [session for session, _ in host.created] == ["runtime-session"]


def test_shared_policy_cannot_bypass_background_execution_denial():
    service, host = runtime()
    service._connection_policy = "shared-native"
    service.lifecycle = "background_available"
    service._background_availability_enabled = lambda: False
    with pytest.raises(NativeUnavailable):
        service.native_webrtc_offer("runtime-session", ICE, [], "profile-1", runtime_owned=True)
    assert host.created == []


def test_native_capabilities_exchange_and_consent_updates_without_a_renderer():
    import base64
    service, host = runtime()
    service.native_webrtc_offer("native-session", ICE, [], "profile-1")
    document = ["signed-v1"]
    stored = []
    service.reconnect_capabilities_get = lambda contact: {"local_capabilities": document[0]}
    service.reconnect_capabilities_store = lambda doc, **binding: stored.append((doc, binding))
    service._handle_native_webrtc_event("channel", "native-session", "meshchat-reconnect:open")
    service._maintain_native_controls()
    assert host.controls[-1][2] == {"type": "connection_capabilities", "document": "signed-v1"}
    text = json.dumps({"type": "connection_capabilities", "document": "peer-signed"})
    service._handle_native_webrtc_event("control", "native-session", "meshchat-reconnect:" + base64.b64encode(text.encode()).decode())
    assert stored == [("peer-signed", {"expected_contact_id": "contact-1", "expected_peer_destination": None})]
    document[0] = "signed-consent-change"
    service._native_control_next = 0
    service._maintain_native_controls()
    assert host.controls[-1][2]["document"] == "signed-consent-change"
    service.native_webrtc_close("native-session")
    count = len(host.controls)
    service._maintain_native_controls()
    assert len(host.controls) == count
    assert not service._native_webrtc_controls


@pytest.mark.parametrize("failure_at", [None, "before_binding", "after_binding"])
def test_native_answer_can_be_bound_signed_and_verified_as_a_complete_exchange(failure_at):
    service, host = runtime()
    service._call_identity = lambda: RNS.Identity()
    offer = create_onboarding_offer(RNS.Identity(), session_id="a" * 32, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    preview = service.verify_webrtc_onboarding_offer(offer)
    native = service.native_webrtc_accept("manual-answer", preview["sdp"], ICE, ONBOARDING_CHANNELS)
    if failure_at == "before_binding":
        service._handle_native_webrtc_event("ice", "manual-answer", "failed")
    service.native_webrtc_bind_onboarding("manual-answer", preview["document"])
    if failure_at == "after_binding":
        service._handle_native_webrtc_event("ice", "manual-answer", "failed")
    complete_sdp = native["sdp"] + "a=end-of-candidates\r\n"
    answer = service.webrtc_onboarding_answer(preview["document"], complete_sdp, native["fingerprint"])
    verified = verify_onboarding_answer(answer["document"], verify_onboarding_offer(offer))
    assert verified.sdp == complete_sdp
    assert verified.session_id == preview["session_id"]
    assert not host.closed


def test_manual_answer_grace_ends_when_the_data_channel_opens(monkeypatch):
    service, host = runtime()
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    service.native_webrtc_accept("manual-answer", SDP, ICE, ONBOARDING_CHANNELS)
    service._handle_native_webrtc_event("ice", "manual-answer", "failed")
    assert not host.closed

    def attach(session_id):
        service._native_webrtc_sessions[session_id] = "bridge"
        return {"bridge_id": "bridge"}

    service.webrtc_attach_native = attach
    service._handle_native_webrtc_event("open", "manual-answer")
    clock[0] += 121
    service._expire_native_answer_exchanges()
    assert not host.closed
    # Once the channel has opened, the 0.9.51 cleanup remains necessary.
    service._handle_native_webrtc_event("ice", "manual-answer", "failed")
    assert host.closed == ["manual-answer"]
    assert not service._native_webrtc_sessions


@pytest.mark.parametrize("ending", ["timeout", "cancel", "ice_closed", "channel_closed"])
def test_manual_answer_grace_is_bounded_and_does_not_hide_closure(monkeypatch, ending):
    service, host = runtime()
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    service.native_webrtc_accept("manual-answer", SDP, ICE, ONBOARDING_CHANNELS)
    service._handle_native_webrtc_event("ice", "manual-answer", "failed")
    assert not host.closed
    if ending == "timeout":
        clock[0] += 119
        service._expire_native_answer_exchanges()
        assert not host.closed
        clock[0] += 2
        service._expire_native_answer_exchanges()
    elif ending == "cancel":
        service.native_webrtc_close("manual-answer")
    elif ending == "ice_closed":
        service._handle_native_webrtc_event("ice", "manual-answer", "closed")
    else:
        service._handle_native_webrtc_event("channel", "manual-answer", "mesh-reticulum:closed")
    assert host.closed == ["manual-answer"]
    assert not service._native_webrtc_live
    assert not service._native_webrtc_descriptions


def test_manual_answer_grace_cannot_outlive_the_signed_offer(monkeypatch):
    service, host = runtime()
    clock = [1000.0]
    now = int(time.time())
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(time, "time", lambda: now)
    offer = create_onboarding_offer(RNS.Identity(), session_id="a" * 32, sdp=SDP,
        dtls_fingerprint=FINGERPRINT, now=now, expires_at=now + 10)
    service.native_webrtc_accept("manual-answer", SDP, ICE, ONBOARDING_CHANNELS)
    service.native_webrtc_bind_onboarding("manual-answer", offer)
    clock[0] += 11
    service._expire_native_answer_exchanges()
    assert host.closed == ["manual-answer"]


def test_native_worker_expires_abandoned_answer_without_renderer_commands():
    service, host = runtime()
    service._native_webrtc_events = queue.Queue()
    service._native_answer_exchange_timeout = 0
    service.native_webrtc_accept("manual-answer", SDP, ICE, ONBOARDING_CHANNELS)
    closed = threading.Event()

    def close(session_id):
        host.closed.append(session_id)
        closed.set()

    host.close = close
    worker = threading.Thread(target=service._native_webrtc_event_loop, daemon=True)
    worker.start()
    try:
        assert closed.wait(2), "The native worker did not expire the abandoned answer"
        assert host.closed == ["manual-answer"]
    finally:
        service._shutdown.set()
        service._native_webrtc_events.put_nowait(None)
        worker.join(2)


@pytest.mark.parametrize("kind", ["offerer", "reconnect_answerer"])
def test_answer_exchange_grace_does_not_delay_other_native_failure_cleanup(kind):
    service, host = runtime()
    if kind == "offerer":
        service.native_webrtc_offer("native-session", ICE, ONBOARDING_CHANNELS)
    else:
        service.native_webrtc_accept("native-session", SDP, ICE, ONBOARDING_CHANNELS, "profile-1")
    service._handle_native_webrtc_event("ice", "native-session", "failed")
    assert host.closed == ["native-session"]


def test_manual_session_binding_uses_verified_signaling_and_survives_dialog_closure():
    from mesh_chat.errors import IdentityMismatch
    service, host = runtime()
    peer = RNS.Identity()
    offer = create_onboarding_offer(peer, session_id="a" * 32, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    service.native_webrtc_accept("manual-session", SDP, ICE, [])
    result = service.native_webrtc_bind_onboarding("manual-session", offer)
    destination = verify_onboarding_offer(offer).signer_destination
    assert result == {"peer_destination": destination}
    service._native_webrtc_sessions["manual-session"] = "bridge"
    service._native_webrtc_controls["manual-session"] = {"profile_id": "profile-1"}
    assert service.native_reconnect_session("profile-1") == "manual-session"
    assert service.native_reconnect_session("another-device") is None
    service._native_onboarding_approval({"id": "contact-1", "destination_hash": destination}, True, "signed-caps")
    assert host.controls[-1] == ("manual-session", "mesh-onboarding", {
        "type": "invitation_approved", "capabilities": "signed-caps"})
    wrong = create_onboarding_offer(peer, session_id="b" * 32, sdp=SDP + "a=ice-ufrag:other\r\n", dtls_fingerprint=FINGERPRINT)
    with pytest.raises(IdentityMismatch):
        service.native_webrtc_bind_onboarding("manual-session", wrong)


def test_reconnect_control_cannot_run_invitation_actions_or_accept_closed_controls():
    import base64
    service, host = runtime()
    service.native_webrtc_offer("native-session", ICE, [], "profile-1")
    stored = []
    service.reconnect_capabilities_store = lambda *args, **kwargs: stored.append(args)
    for session in ["native-session", "closed-session"]:
        text = json.dumps({"type": "invitation_approved", "capabilities": "untrusted"})
        service._handle_native_webrtc_event("control", session, "meshchat-reconnect:" + base64.b64encode(text.encode()).decode())
    assert not stored
    assert not host.controls


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
    service._native_webrtc_live.add("native-session")
    service._native_webrtc_sessions["native-session"] = "bridge"
    service._webrtc_bridges["bridge"] = object()
    assert service.native_webrtc_stats("native-session")["attached"]
    host.state["ice_connection_state"] = state
    assert not service.native_webrtc_stats("native-session")["attached"]
    service._handle_native_webrtc_event("ice", "native-session", state)
    assert not service._native_webrtc_sessions
    assert not service._webrtc_bridges
    assert not service._native_webrtc_live
    assert host.closed == ["native-session"]


def test_channel_closure_detaches_even_if_the_peer_ice_state_is_connected():
    service, host = runtime()
    service._native_webrtc_live.add("native-session")
    service._native_webrtc_sessions["native-session"] = "bridge"
    host.state["data_channel_state"] = "closed"
    assert not service.native_webrtc_stats("native-session")["attached"]
    service._handle_native_webrtc_event("channel", "native-session", "mesh-reticulum:closed")
    assert not service._native_webrtc_sessions
    assert not service._native_webrtc_live
    assert host.closed == ["native-session"]


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
