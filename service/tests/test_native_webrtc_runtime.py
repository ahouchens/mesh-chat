from __future__ import annotations

import json
import queue
import threading
import time

import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, IdentityMismatch, NativeUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.native_resource_registry import NativeResourceRegistry
from mesh_chat.native_startup_packets import NativeStartupPackets
from mesh_chat.webrtc_onboarding import create_onboarding_answer, create_onboarding_offer, verify_onboarding_offer, verify_onboarding_answer

FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:" + FINGERPRINT + "\r\n"
ICE = {"iceServers": [], "iceTransportPolicy": "all"}
ONBOARDING_CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
]


class Host:
    def __init__(self, resources):
        self.resources = resources
        self.raw_created = []
        self.raw_closed = []
        self.created = []
        self.closed = []
        self.state = {"ice_connection_state": "connected", "data_channel_state": "open"}
        self.during_create = lambda: None
        self.controls = []
        self.answers = []

    def applyAnswer(self, session, answer):
        self.answers.append((self.resources.resolve(session), answer))
        return json.dumps({"ok": True})

    def sendControl(self, session, label, text):
        self.controls.append((self.resources.resolve(session), label, json.loads(text)))
        return True

    def createOffer(self, session, ice, channels):
        self.raw_created.append(session)
        self.created.append((self.resources.resolve(session), json.loads(ice)))
        self.during_create()
        # Deliberately use the old metadata format: service signing must use
        # the canonical fingerprint extracted from the actual SDP.
        return json.dumps({"ok": True, "sdp": SDP, "fingerprint": FINGERPRINT.removeprefix("sha-256 ")})

    def acceptOffer(self, session, offer, ice, channels):
        return self.createOffer(session, ice, channels)

    def close(self, session):
        self.raw_closed.append(session)
        self.closed.append(self.resources.resolve(session))

    def stats(self, session):
        return json.dumps({"ok": True, "result": self.state})


def runtime():
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._dispatch_lock = threading.RLock()
    service._native_webrtc_lock = threading.RLock()
    service._native_resources = NativeResourceRegistry()
    service._native_startup_packets = NativeStartupPackets()
    service._native_webrtc_live = set()
    service._native_webrtc_creating = set()
    service._native_webrtc_profile_sessions = {}
    service._native_webrtc_descriptions = {}
    service._native_webrtc_peers = {}
    service._native_webrtc_controls = {}
    service._native_webrtc_sessions = {}
    service._webrtc_bridges = {}
    host = Host(service._native_resources)
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


def native_event(service, kind, logical, data=""):
    physical = service._native_resources.physical(logical) or logical
    service._handle_native_webrtc_event(kind, physical, data)


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


def test_shared_native_callbacks_observe_but_do_not_attach_or_close():
    service, host = runtime()
    service._connection_policy = "shared-native"
    service.native_webrtc_offer("runtime-session", ICE, [], "profile-1", runtime_owned=True)
    attached = []
    service.webrtc_attach_native = attached.append
    native_event(service, "open", "runtime-session")
    native_event(service, "ice", "runtime-session", "failed")
    native_event(service, "channel", "runtime-session", "mesh-reticulum:closed")
    assert attached == []
    assert host.closed == []
    # Explicit effect cleanup still closes the exact owned resource.
    service.native_webrtc_close("runtime-session")
    assert host.closed == ["runtime-session"]


def test_callback_overflow_quarantines_shared_owner_and_closes_manual_carriers():
    from types import SimpleNamespace
    service, host = runtime()
    service._connection_policy = "shared-native"
    service.native_webrtc_offer("runtime-session", ICE, [], "profile-1", runtime_owned=True)
    service.native_webrtc_offer("manual-session", ICE, [])
    quarantined = []
    service._connection_runtime = SimpleNamespace(quarantine=lambda: quarantined.append(True))
    native_event(service, "overflow", "", "")
    assert quarantined == [True]
    assert host.closed == ["manual-session"]


def test_native_capabilities_exchange_and_consent_updates_without_a_renderer():
    import base64
    service, host = runtime()
    service.native_webrtc_offer("native-session", ICE, [], "profile-1")
    document = ["signed-v1"]
    stored = []
    service.reconnect_capabilities_get = lambda contact: {"local_capabilities": document[0]}
    service.reconnect_capabilities_store = lambda doc, **binding: stored.append((doc, binding))
    native_event(service, "channel", "native-session", "meshchat-reconnect:open")
    service._maintain_native_controls()
    assert host.controls[-1][2] == {"type": "connection_capabilities", "document": "signed-v1"}
    text = json.dumps({"type": "connection_capabilities", "document": "peer-signed"})
    native_event(service, "control", "native-session", "meshchat-reconnect:" + base64.b64encode(text.encode()).decode())
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
        native_event(service, "ice", "manual-answer", "failed")
    service.native_webrtc_bind_onboarding("manual-answer", preview["document"])
    if failure_at == "after_binding":
        native_event(service, "ice", "manual-answer", "failed")
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
    native_event(service, "ice", "manual-answer", "failed")
    assert not host.closed

    def attach(session_id):
        service._native_webrtc_sessions[session_id] = "bridge"
        return {"bridge_id": "bridge"}

    service.webrtc_attach_native = attach
    native_event(service, "open", "manual-answer")
    clock[0] += 121
    service._expire_native_answer_exchanges()
    assert not host.closed
    # Once the channel has opened, the 0.9.51 cleanup remains necessary.
    native_event(service, "ice", "manual-answer", "failed")
    assert host.closed == ["manual-answer"]
    assert not service._native_webrtc_sessions


@pytest.mark.parametrize("ending", ["timeout", "cancel", "ice_closed", "channel_closed"])
def test_manual_answer_grace_is_bounded_and_does_not_hide_closure(monkeypatch, ending):
    service, host = runtime()
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    service.native_webrtc_accept("manual-answer", SDP, ICE, ONBOARDING_CHANNELS)
    native_event(service, "ice", "manual-answer", "failed")
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
        native_event(service, "ice", "manual-answer", "closed")
    else:
        native_event(service, "channel", "manual-answer", "mesh-reticulum:closed")
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
        host.closed.append(service._native_resources.resolve(session_id))
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
    native_event(service, "ice", "native-session", "failed")
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
        native_event(service, "control", session, "meshchat-reconnect:" + base64.b64encode(text.encode()).decode())
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
def test_native_stats_and_events_stop_claiming_a_failed_bridge_is_attached(state, monkeypatch):
    from types import SimpleNamespace
    service, host = runtime()
    service._native_webrtc_live.add("native-session")
    service._native_resources.reserve("native-session")
    service._native_webrtc_sessions["native-session"] = "bridge"
    service.network = object()
    service._webrtc_bridges["bridge"] = SimpleNamespace(online=True)
    monkeypatch.setattr(RNS.Transport, "interfaces", [service._webrtc_bridges["bridge"]])
    assert service.native_webrtc_stats("native-session")["attached"]
    host.state["ice_connection_state"] = state
    assert not service.native_webrtc_stats("native-session")["attached"]
    native_event(service, "ice", "native-session", state)
    assert not service._native_webrtc_sessions
    assert not service._webrtc_bridges
    assert not service._native_webrtc_live
    assert host.closed == ["native-session"]


def test_channel_closure_detaches_even_if_the_peer_ice_state_is_connected():
    service, host = runtime()
    service._native_webrtc_live.add("native-session")
    service._native_resources.reserve("native-session")
    service._native_webrtc_sessions["native-session"] = "bridge"
    host.state["data_channel_state"] = "closed"
    assert not service.native_webrtc_stats("native-session")["attached"]
    native_event(service, "channel", "native-session", "mesh-reticulum:closed")
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
        # Removing live routing cannot release the exact in-flight ID, even
        # when a manual caller does not supply a reconnect profile.
        with pytest.raises(NativeUnavailable, match="already exists"):
            service.native_webrtc_offer("native-session", ICE, [])
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
    native_event(service, "open", "native-session", "mesh-reticulum")
    assert not attached


@pytest.mark.parametrize("kind,data", [("open", "mesh-reticulum"), ("closed", ""),
    ("ice", "failed"), ("channel", "mesh-reticulum:closed"),
    ("message", "cGFja2V0"), ("control", "mesh-onboarding:e30=")])
def test_queued_old_callbacks_cannot_target_reused_public_session_ids(kind, data):
    service, host = runtime()
    service._native_webrtc_events = queue.Queue()
    service.native_webrtc_offer("same-session", ICE, [])
    first = host.raw_created[-1]
    service.native_webrtc_event(kind, first, data)
    service.native_webrtc_close("same-session")
    service.native_webrtc_offer("same-session", ICE, [])
    second = host.raw_created[-1]
    assert first != second
    touched = []
    service.webrtc_attach_native = lambda *args: touched.append(args)
    service.webrtc_packet = lambda *args: touched.append(args)
    service._native_control_receive = lambda *args: touched.append(args)
    service._native_webrtc_sessions["same-session"] = "new-bridge"
    service._handle_native_webrtc_event(*service._native_webrtc_events.get_nowait())
    assert not touched
    assert host.raw_closed == [first]
    assert service._native_resources.physical("same-session") == second
    assert service._native_webrtc_sessions["same-session"] == "new-bridge"
    assert "same-session" in service._native_webrtc_live


def test_late_close_completion_cannot_release_or_detach_replacement():
    service, host = runtime()
    service.native_webrtc_offer("same-session", ICE, [])
    first = host.raw_created[-1]
    def close(physical):
        assert physical == first
        service._handle_native_webrtc_event("closed", physical)
        service.native_webrtc_offer("same-session", ICE, [])
        service._native_webrtc_sessions["same-session"] = "replacement-bridge"
    host.close = close
    service.native_webrtc_close("same-session")
    assert service._native_resources.physical("same-session") == host.raw_created[-1]
    assert "same-session" in service._native_webrtc_live
    assert service._native_webrtc_sessions["same-session"] == "replacement-bridge"


def test_failed_native_close_keeps_exact_handle_for_retry_without_allowing_reuse():
    service, host = runtime()
    service.native_webrtc_offer("same-session", ICE, [])
    first = host.raw_created[-1]
    service._native_webrtc_sessions["same-session"] = "bridge"
    def failed_close(_):
        raise OSError("native close failed")
    host.close = failed_close
    with pytest.raises(OSError):
        service.native_webrtc_close("same-session")
    assert "same-session" not in service._native_webrtc_live
    assert "same-session" not in service._native_webrtc_sessions
    assert service._native_resources.physical("same-session") == first
    with pytest.raises(NativeUnavailable):
        service.native_webrtc_offer("same-session", ICE, [])
    host.close = host.raw_closed.append
    service.native_webrtc_close("same-session")
    assert host.raw_closed == [first]
    assert service._native_resources.physical("same-session") is None


def test_old_bridge_send_cannot_reach_a_reused_public_session(monkeypatch):
    from types import SimpleNamespace
    from mesh_chat import service as service_module
    service, host = runtime()
    senders, sent = [], []
    class Interface:
        HW_MTU = 500
        MODE_POINT_TO_POINT = 1
        def __init__(self, transport, send, **_):
            self.online = True
            senders.append(send)
        def detach(self):
            pass
    monkeypatch.setattr(service_module, "WebRTCInterface", Interface)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    service.network = SimpleNamespace(reticulum=SimpleNamespace(
        _add_interface=lambda interface, **_: RNS.Transport.interfaces.append(interface)), reannounce=lambda: None)
    service._webrtc_announce_later = lambda *_: None
    host.send = lambda physical, data: sent.append((physical, data))
    service.native_webrtc_offer("same-session", ICE, [])
    service.webrtc_attach_native("same-session")
    service.native_webrtc_close("same-session")
    service.native_webrtc_offer("same-session", ICE, [])
    service.webrtc_attach_native("same-session")
    senders[0](b"stale")
    senders[1](b"current")
    assert sent == [(host.raw_created[-1], b"current")]


@pytest.fixture
def startup_bridge(monkeypatch):
    from types import SimpleNamespace
    from mesh_chat import service as service_module
    service, host = runtime()
    received, announcements = [], []
    class Interface:
        HW_MTU = 1064
        MODE_POINT_TO_POINT = 1
        def __init__(self, *_args, **_kwargs):
            self.online = True
        def detach(self):
            self.online = False
        def process_incoming(self, packet):
            if packet == b"bad":
                raise ValueError("Malformed packet")
            received.append(packet)
    monkeypatch.setattr(service_module, "WebRTCInterface", Interface)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    service.network = SimpleNamespace(reticulum=SimpleNamespace(
        _add_interface=lambda interface, **_: RNS.Transport.interfaces.append(interface)),
        reannounce=lambda: announcements.append(tuple(received)))
    service._webrtc_announce_later = lambda *_: None
    service.native_webrtc_offer("early-carrier", ICE, [])
    service._connection_policy = "shared-native"
    service._native_webrtc_profile_sessions["profile-1"] = "early-carrier"
    permitted = [False]
    service._connection_runtime = SimpleNamespace(permits_carrier=lambda *_: permitted[0])
    return service, host, permitted, received, announcements


def test_startup_packets_wait_for_authorized_registered_bridge_before_announce(startup_bridge):
    service, _, permitted, received, announcements = startup_bridge
    native_event(service, "message", "early-carrier", "YmFk")  # bad
    native_event(service, "message", "early-carrier", "AQI=")
    with pytest.raises(ContactNotApproved):
        service.webrtc_attach_native("early-carrier")
    assert not received and not announcements
    permitted[0] = True
    bridge = service.webrtc_attach_native("early-carrier")
    assert received == [b"\x01\x02"]
    assert announcements == [(b"\x01\x02",)]
    assert service.webrtc_attach_native("early-carrier") == bridge
    assert received == [b"\x01\x02"]


def test_unadopted_manual_packets_are_not_retained(startup_bridge):
    service, _, permitted, received, _ = startup_bridge
    service._native_webrtc_profile_sessions.clear()
    native_event(service, "message", "early-carrier", "AQI=")
    service._native_webrtc_profile_sessions["profile-1"] = "early-carrier"
    permitted[0] = True
    service.webrtc_attach_native("early-carrier")
    assert not received


def test_bridge_repair_retains_packets_without_replacing_native_carrier(startup_bridge):
    service, host, permitted, received, _ = startup_bridge
    permitted[0] = True
    first = service.webrtc_attach_native("early-carrier")
    RNS.Transport.interfaces.clear()
    native_event(service, "message", "early-carrier", "AQI=")
    assert not received
    second = service.webrtc_attach_native("early-carrier")
    assert first != second and received == [b"\x01\x02"]
    assert len(host.raw_created) == 1 and not host.raw_closed


def test_close_discards_startup_packets_even_when_native_disposal_fails(startup_bridge):
    service, host, _, received, _ = startup_bridge
    native_event(service, "message", "early-carrier", "AQI=")
    physical = host.raw_created[0]
    def fail_close(_):
        raise RuntimeError("Native disposal pending")
    host.close = fail_close
    with pytest.raises(RuntimeError, match="disposal pending"):
        service.native_webrtc_close("early-carrier")
    service._handle_native_webrtc_event("message", physical, "AQI=")
    assert service._native_startup_packets.take(physical) == ()
    assert not received


def test_reused_logical_carrier_cannot_replay_old_startup_packets(startup_bridge):
    service, host, permitted, received, _ = startup_bridge
    native_event(service, "message", "early-carrier", "AQI=")
    old = host.raw_created[0]
    service.native_webrtc_close("early-carrier")
    service.native_webrtc_offer("early-carrier", ICE, [], "profile-1", runtime_owned=True)
    service._handle_native_webrtc_event("message", old, "AQI=")
    native_event(service, "message", "early-carrier", "AwQ=")
    permitted[0] = True
    service.webrtc_attach_native("early-carrier")
    assert received == [b"\x03\x04"]


@pytest.mark.parametrize("fault", ["missing", "offline", "unregistered", "network_absent", "equal_replacement"])
def test_native_inspection_rejects_stale_bridge_registration(fault, monkeypatch):
    from types import SimpleNamespace
    service, _ = runtime()
    service.native_webrtc_offer("live-carrier", ICE, [])
    service.network = object()
    interface = SimpleNamespace(online=True)
    service._native_webrtc_sessions["live-carrier"] = "bridge"
    service._webrtc_bridges["bridge"] = interface
    monkeypatch.setattr(RNS.Transport, "interfaces", [interface])
    assert service.native_webrtc_stats("live-carrier")["attached"]
    if fault == "missing": service._webrtc_bridges.clear()
    if fault == "offline": interface.online = False
    if fault == "unregistered": RNS.Transport.interfaces.clear()
    if fault == "network_absent": service.network = None
    if fault == "equal_replacement": RNS.Transport.interfaces[:] = [SimpleNamespace(online=True)]
    assert not service.native_webrtc_stats("live-carrier")["attached"]
    received = []
    service.webrtc_packet = lambda *_: received.append(True)
    native_event(service, "message", "live-carrier", "AQI=")
    assert not received


def test_native_bridge_repair_keeps_the_carrier_but_fences_old_interface_sends(monkeypatch):
    from types import SimpleNamespace
    from mesh_chat import service as service_module
    service, host = runtime()
    senders, sent = [], []
    class Interface:
        HW_MTU = 500
        MODE_POINT_TO_POINT = 1
        def __init__(self, transport, send, **_):
            self.online = True
            senders.append(send)
        def detach(self):
            self.online = False
    monkeypatch.setattr(service_module, "WebRTCInterface", Interface)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    service.network = SimpleNamespace(reticulum=SimpleNamespace(
        _add_interface=lambda interface, **_: RNS.Transport.interfaces.append(interface)), reannounce=lambda: None)
    service._webrtc_announce_later = lambda *_: None
    host.send = lambda physical, data: sent.append((physical, data))
    service.native_webrtc_offer("live-carrier", ICE, [])
    first = service.webrtc_attach_native("live-carrier")["bridge_id"]
    RNS.Transport.interfaces.clear()
    assert not service.native_webrtc_stats("live-carrier")["attached"]
    replacement = service.webrtc_attach_native("live-carrier")["bridge_id"]
    assert replacement != first
    assert service.native_webrtc_stats("live-carrier")["attached"]
    senders[0](b"stale-interface")
    senders[1](b"current-interface")
    assert sent == [(host.raw_created[0], b"current-interface")]
    assert len(host.raw_created) == 1 and not host.raw_closed
    # Cleanup may still be pending when the owner revokes its bridge lease.
    permitted = [True]
    service._connection_policy = "shared-native"
    service._native_webrtc_profile_sessions["profile-1"] = "live-carrier"
    service._connection_runtime = SimpleNamespace(permits_carrier=lambda *_: permitted[0])
    received = []
    service.webrtc_packet = lambda *_: received.append(True)
    permitted[0] = False
    senders[1](b"after-stop")
    native_event(service, "message", "live-carrier", "AQI=")
    assert len(sent) == 1 and not received and not host.raw_closed


@pytest.mark.parametrize("operation", ["answer", "inspect"])
def test_late_native_result_cannot_describe_replacement(operation):
    service, host = runtime()
    service.native_webrtc_offer("same-session", ICE, [])
    first = host.raw_created[-1]
    def complete(physical, *_):
        assert physical == first
        service.native_webrtc_close("same-session")
        service.native_webrtc_offer("same-session", ICE, [])
        return json.dumps({"ok": True, "result": host.state})
    host.applyAnswer = complete
    host.stats = complete
    with pytest.raises(NativeUnavailable, match="after its resource was retired"):
        if operation == "answer":
            service.native_webrtc_apply_answer("same-session", SDP)
        else:
            service.native_webrtc_stats("same-session")
    assert "remote_answer" not in service._native_webrtc_descriptions["same-session"]
    assert host.raw_closed == [first]


def adoptable_manual_carrier():
    from types import SimpleNamespace
    service, host = runtime()
    peer = RNS.Identity()
    offer = create_onboarding_offer(peer, session_id="a" * 32, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    service.native_webrtc_accept("manual-carrier", SDP, ICE, ONBOARDING_CHANNELS)
    binding = service.native_webrtc_bind_onboarding("manual-carrier", offer)
    service.profile.update(local_device_id="local", remote_device_id="remote",
                           state="waiting_for_peer", allow_direct_ip_disclosure=True)
    from mesh_chat.native_webrtc_control import bind_control_profile
    service._native_webrtc_controls["manual-carrier"] = {}
    bind_control_profile(service._native_webrtc_controls["manual-carrier"], service.profile)
    contact = {"id": "contact-1", "destination_hash": binding["peer_destination"], "trust": "approved"}
    service.store = SimpleNamespace(get=lambda kind, _id: contact if kind == "contact" else None)
    service._connection_policy = "shared-native"
    return service, host, contact


def test_private_claim_transfers_a_verified_manual_carrier_and_fences_ui_teardown():
    service, host, _ = adoptable_manual_carrier()
    assert service.claim_native_reconnect_carrier("profile-1", "local", "remote") == "manual-carrier"
    assert service._shared_native_session("manual-carrier")
    assert service.claim_native_reconnect_carrier("profile-1", "local", "remote") is None
    service._native_webrtc_sessions["manual-carrier"] = "manual-bridge"
    assert service._execute("native_webrtc_close", {"session_id": "manual-carrier"}) == {"state": "managed"}
    assert service._execute("webrtc_detach", {"bridge_id": "manual-bridge"}) == {"state": "managed"}
    with pytest.raises(NativeUnavailable):
        service._execute("native_webrtc_apply_answer", {"session_id": "manual-carrier", "answer_sdp": SDP})
    assert not host.closed
    # The protected owner's exact effect remains able to retire it.
    service.native_webrtc_close("manual-carrier")
    assert host.closed == ["manual-carrier"]


@pytest.mark.parametrize("command", ["reconnect_request_create", "reconnect_offer_create", "reconnect_answer_create",
    "reconnect_publish", "reconnect_fetch", "reconnect_replay_check", "verify_reconnect_request",
    "verify_reconnect_offer", "verify_reconnect_answer", "webrtc_attach", "webrtc_packet"])
def test_shared_owner_ports_are_fenced_before_persistent_command_cache(command):
    from types import SimpleNamespace
    service, _ = runtime()
    service._connection_policy = "shared-native"
    service.store = SimpleNamespace(command_response=lambda _: pytest.fail("Owner check must precede cached results"))
    with pytest.raises(NativeUnavailable, match="owned by the service"):
        service.dispatch({"v": 1, "id": "previous-process-command", "command": command, "payload": {}})


@pytest.mark.parametrize("command,payload", [("native_webrtc_stats", {"session_id": "manual-carrier"}),
    ("native_webrtc_close", {"session_id": "manual-carrier"})])
def test_shared_transport_observations_never_replay_an_obsolete_persisted_success(command, payload):
    service, _, _ = adoptable_manual_carrier()
    service.claim_native_reconnect_carrier("profile-1", "local", "remote")
    service.store.command_response = lambda _: pytest.fail("Native results cannot come from persistent cache")
    service.store.remember_command = lambda *_: pytest.fail("Native observations cannot be cached as durable outcomes")
    result, stop = service.dispatch({"v": 1, "id": "old-request", "command": command, "payload": payload})
    assert result["ok"] and not stop
    if command == "native_webrtc_close":
        assert result["result"] == {"state": "managed"}
    else:
        assert result["result"]["session_id"] == "manual-carrier"


def test_renderer_cannot_write_shared_runtime_status_or_send_control_on_adopted_carrier():
    service, host, _ = adoptable_manual_carrier()
    service.claim_native_reconnect_carrier("profile-1", "local", "remote")
    with pytest.raises(NativeUnavailable):
        service._execute("reconnect_status", {"state": "online"})
    with pytest.raises(NativeUnavailable):
        service._execute("native_webrtc_control", {"session_id": "manual-carrier",
            "label": "mesh-onboarding", "text": "{}"})
    assert not host.controls
    # Protected signed-capability exchange still uses the private method.
    assert service.native_webrtc_control("manual-carrier", "mesh-onboarding", "{}") == {"accepted": True}


def test_renderer_visibility_reconciliation_cannot_grant_shared_execution_availability():
    service, _ = runtime()
    service._connection_policy = "shared-native"
    service.background_availability_status = lambda: {"state": "suspended"}
    service.mobile_lifecycle_transition = lambda *_: pytest.fail("Renderer cannot assert native lifecycle facts")
    assert service._execute("reconcile_mobile_lifecycle", {}) == {"state": "suspended"}


def test_shared_manual_open_cannot_attach_messaging_before_adoption():
    service, _, _ = adoptable_manual_carrier()
    native_event(service, "open", "manual-carrier", "mesh-reticulum")
    assert not service._native_webrtc_sessions
    with pytest.raises(ContactNotApproved, match="has not been adopted"):
        service.webrtc_attach_native("manual-carrier")


@pytest.mark.parametrize("fault", ["local_device", "remote_device", "stop", "revoked", "expired"])
def test_private_adoption_rechecks_authority_instead_of_trusting_cached_profiles(fault):
    service, host, contact = adoptable_manual_carrier()
    local, remote = "local", "remote"
    if fault == "local_device": local = "other"
    if fault == "remote_device": remote = "other"
    if fault == "stop": service.profile["state"] = "stopped"
    if fault == "revoked": contact["trust"] = "blocked"
    if fault == "expired":
        service._reconnect_profile_public = lambda _: {"effective": {"ready": False, "reasons": ["peer_capabilities_expired"]}}
    with pytest.raises(ContactNotApproved):
        service.claim_native_reconnect_carrier("profile-1", local, remote)
    assert not service._native_webrtc_profile_sessions
    assert not host.closed


@pytest.mark.parametrize("fault", ["peer", "profile", "binding", "sdp", "privacy", "creating", "closed", "local_device", "remote_device", "scope"])
def test_manual_carrier_metadata_alone_is_not_adoption_evidence(fault):
    service, _, _ = adoptable_manual_carrier()
    if fault == "peer": service._native_webrtc_peers["manual-carrier"] = "wrong-peer"
    if fault == "profile": service._native_webrtc_controls["manual-carrier"]["profile_id"] = "other-profile"
    if fault == "binding": service._native_webrtc_descriptions["manual-carrier"].pop("bound_remote_sdp")
    if fault == "sdp": service._native_webrtc_descriptions["manual-carrier"]["remote_offer"] += "a=ice-ufrag:changed\r\n"
    if fault == "privacy": service.profile["allow_direct_ip_disclosure"] = False
    if fault == "creating": service._native_webrtc_creating.add("manual-carrier")
    if fault == "closed": service._native_webrtc_live.clear()
    if fault == "local_device": service.profile["local_device_id"] = "changed"
    if fault == "remote_device": service.profile["remote_device_id"] = "changed"
    if fault == "scope": service.profile["scope_kind"] = "workspace"
    assert not service.native_manual_carrier_authorized("profile-1")
    assert service.claim_native_reconnect_carrier("profile-1", service.profile["local_device_id"], service.profile["remote_device_id"]) is None
    assert not service._native_webrtc_profile_sessions


@pytest.mark.parametrize("bind_first", [False, True])
def test_signed_remote_answer_must_match_the_answer_applied_to_native(bind_first):
    service, host = runtime()
    local, peer = RNS.Identity(), RNS.Identity()
    service.native_webrtc_offer("manual-offerer", ICE, ONBOARDING_CHANNELS)
    offer = create_onboarding_offer(local, session_id="b" * 32, sdp=SDP, dtls_fingerprint=FINGERPRINT)
    answer = create_onboarding_answer(peer, verify_onboarding_offer(offer), sdp=SDP, dtls_fingerprint=FINGERPRINT)
    different = SDP + "a=ice-ufrag:different\r\n"
    if bind_first:
        service.native_webrtc_bind_onboarding("manual-offerer", offer, answer)
        with pytest.raises(IdentityMismatch):
            service.native_webrtc_apply_answer("manual-offerer", different)
        assert not host.answers
    else:
        service.native_webrtc_apply_answer("manual-offerer", different)
        with pytest.raises(IdentityMismatch):
            service.native_webrtc_bind_onboarding("manual-offerer", offer, answer)
        assert "manual-offerer" not in service._native_webrtc_peers


@pytest.mark.parametrize("disabled", [(), ("local",), ("remote",), ("local", "remote")])
def test_production_composition_adopts_manual_carrier_without_mailbox_or_new_peer(disabled):
    from mesh_chat.connection.composition import native_runtime
    service, host, _ = adoptable_manual_carrier()
    public = {**service.profile, "auto_reconnect": True, "peer_auto_reconnect": True,
              "trust": "approved", "effective": {"ready": False, "preferred": True,
              "reasons": ["mailbox_not_configured"]}}
    if disabled:
        public["active"] = service.profile["active"] = False
    for side, field, reason in (("local", "auto_reconnect", "consent_missing"),
                                ("remote", "peer_auto_reconnect", "peer_consent_missing")):
        if side in disabled:
            public[field] = False
            public["effective"]["reasons"].append(reason)
    service.reconnect_profiles = lambda: {"profiles": [public]}
    service._reconnect_profile_public = lambda _: public
    service._identity = object()
    service.call_ice_servers = lambda: pytest.fail("Adoption must not allocate ICE configuration")
    service.reconnect_start = lambda *_args, **_kwargs: pytest.fail("Manual adoption cannot activate automatic reconnect")
    service.reconnect_request_create = lambda *_: pytest.fail("Manual authority cannot negotiate replacement")
    service.reconnect_fetch = lambda *_: pytest.fail("Manual authority cannot fetch signaling")
    service.reconnect_path_status = lambda _: {"has_path": True, "ready": True}
    def attach(session):
        service._native_webrtc_sessions[session] = "bridge"
        return {"bridge_id": "bridge"}
    service.webrtc_attach_native = attach
    owner = service._connection_runtime = native_runtime(service)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            owner.step()
            if owner.snapshots()["profile-1"]["messaging_ready"]:
                break
            threading.Event().wait(0.005)
        assert owner.snapshots()["profile-1"]["messaging_ready"]
        assert owner.owner.snapshots()[0].carrier.resource.resource_id == "manual-carrier"
        assert len(host.created) == 1
        assert service._execute("native_webrtc_close", {"session_id": "manual-carrier"}) == {"state": "managed"}
        assert "manual_carrier_authorized" not in public
        if disabled:
            assert not public["active"]
            assert not owner.owner.snapshots()[0].authority.signaling_available
            # Loss ends this session's authority. It cannot trigger signaling
            # or allocate a replacement even after the retry deadline.
            service.native_webrtc_close("manual-carrier")
            owner.now = lambda: time.monotonic() + 120
            for _ in range(5):
                owner.step()
            assert not owner.snapshots()["profile-1"]["messaging_ready"]
            assert owner.runner.idle
            assert len(host.created) == 1
        owner.fence("contact-1")
        # An attach which passed its earlier executor check cannot use a
        # failed-persistence Stop window to install a bridge afterward.
        with pytest.raises(ContactNotApproved, match="authority|not been adopted"):
            MeshChatService.webrtc_attach_native(service, "manual-carrier")
        owner.step()
        assert not owner.snapshots()["profile-1"]["messaging_ready"]
    finally:
        owner.stop()
        owner.wait()
    assert host.closed == ["manual-carrier"]


@pytest.mark.parametrize("field", ["id", "scope_kind", "local_device_id", "remote_device_id"])
def test_signed_control_cannot_rebind_a_manual_carrier_to_another_scope_or_device(field):
    from mesh_chat.native_webrtc_control import bind_control_profile
    service, _, _ = adoptable_manual_carrier()
    control = service._native_webrtc_controls["manual-carrier"]
    with pytest.raises(IdentityMismatch, match="already bound"):
        bind_control_profile(control, {**service.profile, field: "changed"})
    assert service.native_manual_carrier_authorized("profile-1")


def test_failed_durable_stop_also_retires_manual_carriers_awaiting_adoption():
    from types import SimpleNamespace
    service, host, _ = adoptable_manual_carrier()
    fenced = []
    service._connection_runtime = SimpleNamespace(fence=fenced.append)
    service._reconnect_profiles_raw = lambda: [dict(service.profile)]
    def failed_write(*_):
        raise OSError("vault write failed")
    service.store.put = failed_write
    with pytest.raises(OSError, match="vault write failed"):
        service.reconnect_stop("contact-1")
    assert fenced == ["contact-1"]
    assert host.closed == ["manual-carrier"]
    assert not service._native_webrtc_live
    assert service.profile["active"]  # No claim that Stop was durable.
