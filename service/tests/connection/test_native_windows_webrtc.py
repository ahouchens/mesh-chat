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
        assert right.send("right", b"after close") is False
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
