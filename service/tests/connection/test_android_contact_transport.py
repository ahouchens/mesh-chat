"""Harness negative controls; these tests do not provide JNI qualification."""
import base64
import json
from pathlib import Path
import runpy

import pytest

from mesh_chat import mobile_bridge


FIXTURE = Path(__file__).resolve().parents[3] / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/assets/contact_bootstrap_fixture.py"


class Host:
    def __init__(self, failure=None):
        self.failure = failure
        self.sessions = []
        self.closed = []
        self.received = {}

    def createOffer(self, session, *_):
        self.sessions.append(session)
        return json.dumps({"ok": self.failure != "offer", "sdp": "synthetic"})

    def acceptOffer(self, session, *_):
        self.sessions.append(session)
        return json.dumps({"ok": self.failure != "accept", "sdp": "synthetic"})

    def applyAnswer(self, *_):
        return json.dumps({"ok": self.failure != "answer"})

    def stats(self, session):
        return json.dumps({"ok": session not in self.closed, "result": {
            "data_channel_state": "open", "received_packets": self.received.get(session, 0)}})

    def send(self, session, packet):
        if self.failure == "send":
            return False
        other = self.sessions[1 - self.sessions.index(session)]
        self.received[other] = self.received.get(other, 0) + 1
        mobile_bridge.native_webrtc_event("message", other, base64.b64encode(packet).decode())
        return True

    def close(self, session):
        self.closed.append(session)


@pytest.fixture
def packet_link(monkeypatch):
    monkeypatch.setattr(mobile_bridge, "_service", None)
    return runpy.run_path(str(FIXTURE))["NativeContactPackets"]


def test_packet_exchange_uses_host_send_and_received_callbacks(packet_link):
    previous = mobile_bridge.native_webrtc_event
    host = Host()
    with packet_link(host) as link:
        link.send(0, [b"request"])
        link.send(1, [b"accept"])
        assert link.receive(1) == [b"request"]
        assert link.receive(0) == [b"accept"]
        assert link.receive(0) == []
        link.verify_traffic()
    assert set(host.closed) == set(host.sessions)
    assert mobile_bridge.native_webrtc_event is previous


@pytest.mark.parametrize("failure", ["offer", "accept", "answer", "send"])
def test_native_failure_cannot_fall_back_to_python_packet_routing(packet_link, failure):
    previous = mobile_bridge.native_webrtc_event
    host = Host(failure)
    with pytest.raises(AssertionError):
        with packet_link(host) as link:
            link.send(0, [b"request"])
    assert len(set(host.closed)) == 2
    assert mobile_bridge.native_webrtc_event is previous


@pytest.mark.parametrize("fault", ["invalid", "empty", "oversized", "overflow", "native_overflow"])
def test_callback_failure_is_bounded_and_fails_qualification(packet_link, fault):
    with packet_link(Host()) as link:
        encoded = "invalid!" if fault == "invalid" else base64.b64encode(
            b"" if fault == "empty" else b"x" * (517 if fault == "oversized" else 1)).decode()
        for _ in range(129 if fault == "overflow" else 1):
            mobile_bridge.native_webrtc_event("overflow" if fault == "native_overflow" else "message",
                                             link.sessions[0], encoded)
        with pytest.raises(AssertionError):
            link.receive(0)


def test_empty_transport_cannot_claim_contact_traffic(packet_link):
    with packet_link(Host()) as link:
        with pytest.raises(AssertionError):
            link.verify_traffic()


def test_failed_retirement_still_closes_both_sides_and_restores_callback(packet_link):
    previous = mobile_bridge.native_webrtc_event
    host = Host()
    attempted = []
    def close(session):
        attempted.append(session)
        raise RuntimeError("synthetic disposal failure")
    host.close = close
    with pytest.raises(AssertionError, match="retirement"):
        with packet_link(host):
            pass
    assert attempted == host.sessions
    assert mobile_bridge.native_webrtc_event is previous


def test_fixture_cannot_intercept_a_running_application(packet_link, monkeypatch):
    monkeypatch.setattr(mobile_bridge, "_service", object())
    previous = mobile_bridge.native_webrtc_event
    host = Host()
    with pytest.raises(AssertionError):
        with packet_link(host):
            pytest.fail("Intercepted an active application")
    assert not host.sessions
    assert mobile_bridge.native_webrtc_event is previous
