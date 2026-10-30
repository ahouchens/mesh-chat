"""Isolated contact control with explicit buffered or native test transports.

The native scenario also exercises JNI DataChannels. Neither scenario qualifies
user approval, main-service ownership transfer or application receipts.
"""
import base64
from collections import deque
import json
import threading
import time
from uuid import uuid4

import LXMF
import RNS

from mesh_chat.app_protocol import parse_payload
from mesh_chat.contact_bootstrap import ContactBootstrapEngine
from mesh_chat.errors import ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.network import validate_unknown_source_signature


class BufferedContactPackets:
    def __init__(self):
        self.packets = [[], []]

    def send(self, side, packets):
        self.packets[1 - side].extend(packets)

    def receive(self, side):
        packets, self.packets[side] = self.packets[side], []
        return packets


class NativeContactPackets:
    """Instrumentation-only callback capture; packets must cross the real host."""
    def __init__(self, host):
        self.host = host
        self.sessions = ["contact-native-" + uuid4().hex for _ in range(2)]
        self._packets = [deque(), deque()]
        self._lock = threading.Lock()
        self._failure = None
        self._previous = None
        self._closed = False

    def _invoke(self, operation, *arguments):
        result = json.loads(str(getattr(self.host, operation)(*arguments)))
        assert result.get("ok") is True, "Native contact transport operation failed: " + operation
        return result.get("result", result)

    def __enter__(self):
        from mesh_chat import mobile_bridge
        assert mobile_bridge._service is None, "Native contact fixture requires an isolated test process"
        self._previous = mobile_bridge.native_webrtc_event
        mobile_bridge.native_webrtc_event = self._event
        try:
            ice = json.dumps({"iceServers": [], "iceTransportPolicy": "all"})
            channels = json.dumps([{"label": "mesh-reticulum", "binary": True, "ordered": True}])
            offer = self._invoke("createOffer", self.sessions[0], ice, channels)
            answer = self._invoke("acceptOffer", self.sessions[1], offer["sdp"], ice, channels)
            self._invoke("applyAnswer", self.sessions[0], answer["sdp"])
            deadline = time.monotonic() + 30
            while not all(self._invoke("stats", session).get("data_channel_state") == "open"
                          for session in self.sessions):
                assert time.monotonic() < deadline, "Native contact channels did not open"
                time.sleep(.02)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _event(self, event, session, data=""):
        event, session, data = str(event), str(session), str(data)
        if session not in self.sessions:
            return self._previous(event, session, data)
        with self._lock:
            if self._closed:
                return
            try:
                assert event != "overflow", "Native callback overflow"
                if event != "message":
                    return
                assert 1 <= len(data) <= 688, "Native packet encoding exceeded its bound"
                packet = base64.b64decode(data, validate=True)
                queue = self._packets[self.sessions.index(session)]
                assert 1 <= len(packet) <= 516 and len(queue) < 128, "Native packet budget exhausted"
                queue.append(packet)
            except Exception:
                self._failure = "Native contact packet callback failed"

    def receive(self, side):
        with self._lock:
            assert self._failure is None, self._failure
            queue = self._packets[side]
            return [queue.popleft() for _ in range(min(32, len(queue)))]

    def send(self, side, packets):
        for packet in packets:
            with self._lock:
                assert self._failure is None, self._failure
            assert self.host.send(self.sessions[side], packet), "Native contact packet send failed"

    def verify_traffic(self):
        with self._lock:
            assert self._failure is None, self._failure
        assert all(self._invoke("stats", session).get("received_packets", 0) > 0
                   for session in self.sessions), "Native contact traffic was not bidirectional"

    def __exit__(self, *_):
        from mesh_chat import mobile_bridge
        with self._lock:
            self._closed = True
        failures = []
        try:
            for session in self.sessions:
                try:
                    self.host.close(session)
                    assert json.loads(str(self.host.stats(session))).get("ok") is not True
                except Exception:
                    failures.append(session)
        finally:
            mobile_bridge.native_webrtc_event = self._previous
        assert not failures, "Native contact transport retirement failed"


def run_native(directory):
    from java import jclass
    with NativeContactPackets(jclass("com.meshchat.runtime.NativeWebRtcHost")) as link:
        result = run(directory, link=link)
        link.verify_traffic()
        return result


def run(directory, factory=None, link=None):
    if factory is None:
        from mesh_chat.direct_bootstrap_mobile import AndroidBootstrapProcess
        factory = AndroidBootstrapProcess
    link = link or BufferedContactPackets()
    local, remote = RNS.Identity(), RNS.Identity()
    engine = ContactBootstrapEngine(local.get_private_key(), remote.get_public_key(),
                                    int(time.time()) + 120, directory=directory)
    worker = None
    try:
        main_reticulum = RNS.Reticulum.get_instance()
        worker = factory()
        # This must succeed with RNS already running in the calling interpreter.
        worker.request("initialize_contact", private_identity=remote.get_private_key().hex(),
                       peer_identity=local.get_public_key().hex(), expires_at=int(time.time()) + 120)
        worker.request("activate")
        engine.activate()
        observed, ready = [], [False, False]

        def exchange():
            result = engine.exchange(link.receive(0))
            ready[0] = result["recipient_ready"]
            observed.extend((0, event) for event in result["events"])
            link.send(0, result["packets"])
            result = worker.request("exchange", packets=[packet.hex() for packet in link.receive(1)])
            link.send(1, [bytes.fromhex(packet) for packet in result["packets"]])
            ready[1] = result["recipient_ready"]
            observed.extend((1, event) for event in result["events"])
            time.sleep(.02)

        def until(predicate):
            deadline = time.monotonic() + 30
            while not predicate() and time.monotonic() < deadline:
                exchange()
            assert predicate(), "Contact bootstrap exchange did not complete"

        until(lambda: all(ready))
        invitation = create_invitation(remote, "Synthetic contact bootstrap")["file"]
        request_id, accept_id = str(uuid4()), str(uuid4())
        worker.request("send", kind="contact_request", logical_id=request_id,
                       document=invitation, expires_at=int(time.time()) + 45)
        until(lambda: any(index == 0 and event["kind"] == "inbound" for index, event in observed))
        engine.send(kind="contact_accept", logical_id=accept_id, document="", expires_at=int(time.time()) + 45)
        until(lambda: any(index == 1 and event["kind"] == "inbound" for index, event in observed))
        for index, identity, kind, logical_id in ((0, remote, "contact_request", request_id),
                                                (1, local, "contact_accept", accept_id)):
            messages = [event for receiver, event in observed if receiver == index and event["kind"] == "inbound"]
            assert len(messages) == 1
            packed = messages[0]["packed"]
            if index == 1:
                packed = base64.b64decode(packed, validate=True)
            message = LXMF.LXMessage.unpack_from_bytes(packed)
            assert validate_unknown_source_signature(message, identity.get_public_key())
            message.signature_validated = True
            payload = parse_payload(message)
            assert (payload.kind.value, payload.logical_id) == (kind, logical_id)
            if index == 0:
                assert payload.invitation == invitation
        try:
            worker.request("send", kind="chat", logical_id=str(uuid4()), document="forbidden",
                           expires_at=int(time.time()) + 30)
        except ValidationError:
            pass
        else:
            raise AssertionError("Contact interpreter admitted ordinary chat")
        try:
            worker.request("exchange", packets=[])
        except ValidationError:
            pass
        else:
            raise AssertionError("Failed interpreter remained available")
        assert RNS.Reticulum.get_instance() is main_reticulum
        assert engine.exchange([])["recipient_ready"]
        return True
    finally:
        if worker is not None:
            worker.close()
        engine.close()
