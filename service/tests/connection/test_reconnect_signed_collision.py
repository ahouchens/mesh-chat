"""Two-actor SC02 component trace: real signatures, simulated mailbox/native ports."""

from threading import Event
from time import time

import RNS

from mesh_chat.connection.adapters.reconnect import NativePort, ReconnectExecutor, SignalingPort
from mesh_chat.connection.model import (
    Authority, Bridge, ConnectionKey, ConnectionState, Desired, Failed, Phase, Tick, Work,
)
from mesh_chat.connection.reducer import transition
from mesh_chat.errors import IdentityMismatch
from mesh_chat.reconnect import (
    create_reconnect_answer, create_reconnect_offer, create_reconnect_request,
    verify_reconnect_answer, verify_reconnect_offer, verify_reconnect_request,
)
from mesh_chat.webrtc_signaling import _destination_for


FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "v=0\r\na=fingerprint:" + FINGERPRINT + "\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"


class Actor:
    def __init__(self, identity, peer, preferred, mailbox, clock):
        self.identity = identity
        self.local = _destination_for(identity)
        self.peer = _destination_for(peer)
        self.mailbox = mailbox
        self.clock = clock
        self.published = []
        self.native_calls = []
        self.profile = {"id": "shared-profile", "contact_id": "approved-peer", "active": True,
                        "effective": {"ready": True, "preferred": preferred}}
        self.key = ConnectionKey("personal", "shared-profile", self.local, self.peer)
        self.state = ConnectionState(self.key, "epoch", Authority(1, True, True, preferred), Desired.ENABLED)

        def request(_contact, attempt):
            document = create_reconnect_request(identity, to_destination=self.peer,
                device_id="device:test-1", attempt_id=attempt, nonce="nonce-reconnect-test-1")
            verified = verify_reconnect_request(document)
            return {"document": document, "attempt_id": verified.attempt_id,
                    "expires_at": verified.expires_at}

        def checked_request(document, _profile):
            value = verify_reconnect_request(document, expected_signer=self.peer)
            if value.to_destination != self.local:
                raise IdentityMismatch("Request targets another device")
            return {"attempt_id": value.attempt_id}

        def offer(_contact, document, sdp, fingerprint):
            request_value = verify_reconnect_request(document, expected_signer=self.peer)
            signed = create_reconnect_offer(identity, request_value, sdp=sdp,
                                            dtls_fingerprint=fingerprint)
            value = verify_reconnect_offer(signed)
            return {"document": signed, "attempt_id": value.attempt_id, "sdp": value.sdp}

        def checked_offer(document, _profile):
            value = verify_reconnect_offer(document, expected_signer=self.peer)
            if value.to_destination != self.local:
                raise IdentityMismatch("Offer targets another device")
            return {"attempt_id": value.attempt_id, "sdp": value.sdp}

        def answer(_contact, document, sdp, fingerprint):
            offer_value = verify_reconnect_offer(document, expected_signer=self.peer)
            signed = create_reconnect_answer(identity, offer_value, sdp=sdp,
                                             dtls_fingerprint=fingerprint)
            return {"document": signed}

        def checked_answer(document, offer_document, _profile):
            offer_value = verify_reconnect_offer(offer_document)
            value = verify_reconnect_answer(document, offer_value, expected_signer=self.peer)
            if value.to_destination != self.local:
                raise IdentityMismatch("Answer targets another device")
            return {"sdp": value.sdp}

        def publish(_profile, document, role):
            self.published.append(role)
            mailbox[role] = document

        def fetch(_profile, role):
            return {"document": mailbox.get(role)}

        def native_call(role, *_args):
            self.native_calls.append(role)
            return {"sdp": SDP, "fingerprint": FINGERPRINT}

        signaling = SignalingPort(request, offer, answer, checked_request,
                                  checked_offer, checked_answer, publish, fetch)
        native = NativePort(lambda *args: native_call("offer", *args),
                            lambda *args: native_call("accept", *args),
                            lambda *_: self.native_calls.append("apply"),
                            lambda _: {"data_channel_state": "open", "ice_connection_state": "connected"},
                            lambda _: self.native_calls.append("attach"),
                            lambda _: self.native_calls.append("close"))
        self.executor = ReconnectExecutor(signaling, native, profile=lambda _: self.profile,
            ice=lambda: {"iceServers": []}, path=lambda _: {"has_path": True, "ready": True},
            current=lambda _: True, now=lambda: clock[0], wall_time=time)
        self.result = transition(self.state, Tick(clock[0]))

    def work(self):
        if not self.result.effects:
            self.clock[0] += 6
            self.result = transition(self.result.state, Tick(self.clock[0]))
        assert len(self.result.effects) == 1
        work = self.result.effects[0]
        assert isinstance(work, Work)
        return work

    def step(self):
        event = self.executor.execute(self.work(), Event())
        assert not isinstance(event, Failed), event
        self.result = transition(self.result.state, event)
        return event

    def until(self, phase):
        for _ in range(15):
            if self.work().phase is phase:
                return
            self.step()
        raise AssertionError(f"did not reach {phase}")

    def until_ready(self):
        for _ in range(15):
            if self.result.state.carrier and self.result.state.carrier.bridge is Bridge.READY:
                return
            self.step()
        raise AssertionError("carrier did not reach ready")


def test_simultaneous_start_ignores_mismatched_signed_offer_and_duplicate_request():
    mailbox, clock = {}, [0.0]
    first_identity, second_identity = RNS.Identity(), RNS.Identity()
    first = Actor(first_identity, second_identity, True, mailbox, clock)
    second = Actor(second_identity, first_identity, False, mailbox, clock)
    assert first.work().phase is second.work().phase is Phase.DISCOVER

    first.until(Phase.WAIT_OFFER)
    second.until(Phase.WAIT_REQUEST)
    second.until(Phase.WAIT_ANSWER)
    matching_offer = mailbox["offer"]
    unrelated_request = create_reconnect_request(first_identity, to_destination=second.local,
        device_id="device:test-1", attempt_id="different-attempt-1234567890",
        nonce="nonce-reconnect-test-2")
    mailbox["offer"] = create_reconnect_offer(second_identity,
        verify_reconnect_request(unrelated_request), sdp=SDP, dtls_fingerprint=FINGERPRINT)

    first.until(Phase.WAIT_OFFER)
    rejected = first.step()
    assert rejected.pending and first.result.state.carrier is None
    assert "accept" not in first.native_calls
    mailbox["offer"] = matching_offer

    first.until(Phase.CHECKING)
    assert first.published == ["request", "answer"]
    second.until_ready()
    first.until_ready()
    assert second.published == ["offer"]
    assert first.native_calls.count("accept") == second.native_calls.count("offer") == 1
    assert first.native_calls.count("attach") == second.native_calls.count("attach") == 1
    assert first.result.state.carrier.resource != second.result.state.carrier.resource

    # A new local negotiation seeing the already-completed signed request must
    # wait, without making another native offer or publishing another document.
    second.result = transition(second.state, Tick(clock[0]))
    second.until(Phase.WAIT_REQUEST)
    replay = second.step()
    assert replay.pending
    assert second.published == ["offer"] and second.native_calls.count("offer") == 1
