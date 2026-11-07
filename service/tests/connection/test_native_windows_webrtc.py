"""Native Windows WebRTC host conformance over real aiortc data channels."""

import base64
import json
import queue
import time

import pytest

aiortc = pytest.importorskip("aiortc")

from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost


ICE = {"iceServers": [], "iceTransportPolicy": "all"}
CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
]


def wait_for(events, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in list(events.queue):
            if predicate(event):
                return event
        time.sleep(0.02)
    raise AssertionError(f"event not observed: {list(events.queue)}")


def host():
    events = queue.Queue()
    return WindowsNativeWebRTCHost(lambda *event: events.put(event)), events


def establish():
    left, left_events = host()
    right, right_events = host()
    try:
        offer = json.loads(left.createOffer("left", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        answer = json.loads(right.acceptOffer(
            "right", offer["sdp"], json.dumps(ICE), json.dumps(CHANNELS)))
        assert answer["ok"], answer
        assert json.loads(left.applyAnswer("left", answer["sdp"]))["ok"]
        wait_for(left_events, lambda event: event == ("open", "left", "mesh-reticulum"))
        wait_for(right_events, lambda event: event == ("open", "right", "mesh-reticulum"))
        return (left, left_events), (right, right_events)
    except Exception:
        left.shutdown()
        right.shutdown()
        raise


def test_native_host_exchanges_binary_packets_and_controls():
    (left, left_events), (right, right_events) = establish()
    try:
        packet = bytes(range(256)) * 4 + b"x" * 40
        assert left.send("left", packet)
        assert right.send("right", b"reply")
        assert right.sendControl("right", "mesh-onboarding", "control text")
        wait_for(left_events, lambda event: event[0] == "message"
                 and base64.b64decode(event[2]) == b"reply")
        wait_for(left_events, lambda event: event[0] == "control"
                 and event[2].startswith("mesh-onboarding:")
                 and base64.b64decode(event[2].split(":", 1)[1]) == b"control text")
        wait_for(right_events, lambda event: event[0] == "message"
                 and base64.b64decode(event[2]) == packet)
        stats = json.loads(left.stats("left"))
        assert stats["ok"] and stats["result"]["data_channel_state"] == "open"
        assert stats["result"]["received_packets"] == 1
        assert json.loads(right.stats("right"))["result"]["received_controls"] == 0
    finally:
        left.shutdown()
        right.shutdown()


def test_close_is_exact_and_reports_closed_once():
    (left, left_events), (right, _right_events) = establish()
    try:
        left.close("left")
        wait_for(left_events, lambda event: event == ("closed", "left", ""))
        assert json.loads(left.stats("left"))["error"] == "native_webrtc_session_missing"
        deadline = time.monotonic() + 5
        while right.send("right", b"after close") is not False:
            assert time.monotonic() < deadline, "remote session never observed closure"
            time.sleep(0.02)
    finally:
        left.shutdown()
        right.shutdown()


def test_missing_packet_channel_and_oversized_frames_fail_before_allocation():
    host_instance, _ = host()
    try:
        missing = json.loads(host_instance.createOffer(
            "missing", json.dumps(ICE), json.dumps([{"label": "mesh-onboarding"}])))
        assert missing == {"ok": False, "error": "native_webrtc_missing_data_channel"}
        assert host_instance.send("missing", b"x") is False
        assert host_instance.sendControl("missing", "mesh-onboarding", "x" * 65_537) is False
        assert host_instance.send("missing", b"x" * 1065) is False
    finally:
        host_instance.shutdown()


def test_session_capacity_is_bounded():
    host_instance, _ = host()
    try:
        for index in range(16):
            result = json.loads(host_instance.createOffer(
                f"session-{index}", json.dumps(ICE), json.dumps(CHANNELS)))
            if not result["ok"]:
                pytest.fail(result)
        refused = json.loads(host_instance.createOffer(
            "session-overflow", json.dumps(ICE), json.dumps(CHANNELS)))
        assert refused["error"] == "native_webrtc_session_limit"
    finally:
        host_instance.shutdown()


@pytest.mark.parametrize("phase", ["offer-created", "accepted", "answer-applied"])
def test_cancellation_at_each_handshake_phase_retires_exactly_that_session(phase):
    left, left_events = host()
    right, right_events = host()
    try:
        offer = json.loads(left.createOffer("left", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        if phase in {"accepted", "answer-applied"}:
            answer = json.loads(right.acceptOffer(
                "right", offer["sdp"], json.dumps(ICE), json.dumps(CHANNELS)))
            assert answer["ok"], answer
        if phase == "answer-applied":
            assert json.loads(left.applyAnswer("left", answer["sdp"]))["ok"]

        left.close("left")
        if phase != "offer-created":
            right.close("right")
        for instance, session in ((left, "left"), (right, "right")):
            if phase == "offer-created" and instance is right:
                continue
            assert json.loads(instance.stats(session))["error"] == "native_webrtc_session_missing"

        replacement = json.loads(left.createOffer(
            "replacement", json.dumps(ICE), json.dumps(CHANNELS)))
        assert replacement["ok"], replacement
        left.close("replacement")
        assert json.loads(left.stats("replacement"))["error"] == "native_webrtc_session_missing"
    finally:
        left.shutdown()
        right.shutdown()


def test_shutdown_retires_live_sessions_and_refuses_further_work():
    host_instance, events = host()
    for index in range(3):
        created = json.loads(host_instance.createOffer(
            f"live-{index}", json.dumps(ICE), json.dumps(CHANNELS)))
        assert created["ok"], created
    host_instance.shutdown()
    for index in range(3):
        assert json.loads(host_instance.stats(f"live-{index}"))["error"] == (
            "native_webrtc_session_missing")
    assert host_instance.send("live-0", b"after shutdown") is False
    assert host_instance.sendControl("live-0", "mesh-onboarding", "after shutdown") is False
    host_instance.shutdown()


def test_relay_only_offer_has_no_direct_candidates_without_turn():
    host_instance, events = host()
    ice = json.dumps({"iceServers": [], "iceTransportPolicy": "relay"})
    try:
        created = json.loads(host_instance.createOffer("relay", ice, json.dumps(CHANNELS)))
        assert created["ok"], created
        candidates = [
            line for line in created["sdp"].splitlines()
            if line.startswith("a=candidate:")
        ]
        assert all(" typ relay" in line for line in candidates), candidates
    finally:
        host_instance.shutdown()


def test_relay_only_answer_filters_direct_candidates():
    left, left_events = host()
    right, right_events = host()
    ice = json.dumps({"iceServers": [], "iceTransportPolicy": "relay"})
    try:
        offer = json.loads(left.createOffer("offer", json.dumps(ICE), json.dumps(CHANNELS)))
        assert offer["ok"], offer
        answer = json.loads(right.acceptOffer(
            "answer", offer["sdp"], ice, json.dumps(CHANNELS)))
        assert answer["ok"], answer
        candidates = [
            line for line in answer["sdp"].splitlines()
            if line.startswith("a=candidate:")
        ]
        assert all(" typ relay" in line for line in candidates), candidates
    finally:
        left.shutdown()
        right.shutdown()
