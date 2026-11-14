"""Public request shapes, role evidence and bounded scenario polling."""

import hashlib
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_pair_flow as flow


PAIR_ID = "a" * 32
DESTINATIONS = {"windows": "1" * 32, "android": "2" * 32}
CALLS = {"turn_configured": False, "turn_username": None, "stun_urls": [],
         "turn_url": None, "turn_broker_url": "https://broker.example.test",
         "signal_mailbox_url": None, "store_call_signaling": False}
OPERATIONS = ["profile.create", "peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel",
              "contact.invitation", "peer.approve", "connection.snapshot", "message.enqueue", "message.query"]


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Exchange:
    def __init__(self, role):
        self.role = role
        self.published = []
        self.received = []

    def publish(self, phase, payload, deadline):
        assert deadline > 0
        self.published.append((phase, payload))

    def receive(self, phase, deadline):
        assert deadline > 0
        self.received.append(phase)
        return {"pairing_code": "sealed-offer-code"} if phase == "offer_code" else {}


class Peer:
    def __init__(self, role, *, pending_offer=False, duplicate_inbound=False):
        self.role = role
        self.other = "android" if role == "windows" else "windows"
        self.created = self.approved = self.accepted = self.sent = False
        self.offer_queries = 0
        self.pending_offer = pending_offer
        self.duplicate_inbound = duplicate_inbound
        self.calls = []

    def snapshot(self):
        own = flow._text(PAIR_ID, self.role)
        other = flow._text(PAIR_ID, self.other)
        contact = {"id": "contact-1", "core_handle": "public-peer-handle",
                   "destination_hash": DESTINATIONS[self.other],
                   "trust": "approved" if self.approved or self.accepted else "pending_request"}
        if not self.created:
            return {"profile": None, "contacts": [], "messages": [], "contact_invitations": []}
        profile = {"display_name": "Independent " + self.role,
                   "destination_hash": DESTINATIONS[self.role]}
        if self.role == "windows":
            contacts = [contact] if len(self.calls) > 11 else []
            invitations = []
        else:
            contacts = [contact] if self.accepted else []
            invitations = [] if self.accepted else [{"id": "invitation-1", "state": "pending"}]
        messages = []
        if self.sent:
            messages = [{"id": "outbound-1", "contact_id": "contact-1", "kind": "chat",
                         "direction": "outbound", "text": own, "state": "delivered"},
                        {"id": "inbound-1", "contact_id": "contact-1", "kind": "chat",
                         "direction": "inbound", "text": other}]
            if self.duplicate_inbound:
                messages.append(dict(messages[1], id="inbound-2"))
        return {"profile": profile, "contacts": contacts, "messages": messages,
                "contact_invitations": invitations}

    def request(self, operation, params=None, key=None):
        self.calls.append((operation, params, key))
        profile = "owner-handle"
        if operation == "runtime.capabilities":
            assert params is None and key is None
            return {"profiles": [profile], "operations": OPERATIONS}
        if operation == "application.snapshot":
            assert params is None
            return self.snapshot()
        if operation == "profile.create":
            assert params == {"display_name": "Independent " + self.role} and len(key) >= 16
            self.created = True
            return {"display_name": params["display_name"]}
        if operation == "profile.query":
            assert params == {"profile": profile}
            return {"profile": profile, "destination": DESTINATIONS[self.role],
                    "connections": ["connection-1"]}
        if operation == "settings.update":
            assert params == {"profile": profile, "settings": flow.ALTERNATE_PATHS}
            return {}
        if operation == "settings.query":
            return {"settings": flow.ALTERNATE_PATHS}
        if operation == "call.settings_query":
            return {"settings": {**CALLS, "turn_broker_consent": True, "relay_only": True}}
        if operation == "call.settings_update":
            assert params["profile"] == profile and params["settings"]["turn_broker_consent"] is True
            assert params["settings"]["relay_only"] is True
            return {}
        if operation == "peer.pairing_begin":
            assert params["profile"] == profile and params["allow_direct_ip_disclosure"] is False
            assert params["role"] == ("offer" if self.role == "windows" else "answer")
            assert ("pairing_code" in params) == (self.role == "android") and len(key) >= 16
            return {"pairing": "pairing-1", "state": "reserved", "pairing_code": None}
        if operation == "peer.pairing_query":
            assert params == {"profile": profile, "pairing": "pairing-1"}
            self.offer_queries += 1
            if self.role == "windows" and not self.approved and (not self.pending_offer or self.offer_queries > 1):
                return {"state": "offer_ready", "pairing_code": "sealed-offer-code"}
            if self.role == "windows" and not self.approved and self.pending_offer and self.offer_queries == 1:
                return {"state": "reserved", "pairing_code": None}
            return {"state": "transferred", "pairing_code": None}
        if operation == "contact.invitation":
            assert params == {"profile": profile, "action": "decide",
                              "invitation": "invitation-1", "accept": True}
            self.accepted = True
            return {"contact_invitation": {"state": "accepted"}}
        if operation == "peer.approve":
            assert params == {"profile": profile, "peer": "public-peer-handle"}
            self.approved = True
            return {"trust": "approved"}
        if operation == "peer.pairing_cancel":
            assert params == {"profile": profile, "pairing": "pairing-1"} and len(key) >= 16
            return {"state": "transferred", "pairing_code": None}
        if operation == "connection.snapshot":
            assert params == {"profile": profile, "connection": "connection-1"}
            return {"observation": {"messaging_ready": True}}
        if operation == "message.enqueue":
            assert params == {"profile": profile, "recipient": "public-peer-handle", "kind": "text",
                              "text": flow._text(PAIR_ID, self.role)} and len(key) >= 16
            self.sent = True
            return {"accepted": True, "message": "message-1"}
        if operation == "message.query":
            assert params == {"profile": profile, "message": "message-1"}
            return {"message": "message-1", "text": flow._text(PAIR_ID, self.role),
                    "recipient": "public-peer-handle", "state": "delivered"}
        raise AssertionError(operation)


def test_both_roles_return_exact_cross_matching_public_evidence():
    results = {}
    for role in ("windows", "android"):
        clock, peer, exchange = Clock(), Peer(role), Exchange(role)
        results[role] = flow.run_role(role, peer, exchange, pair_id=PAIR_ID, deadline=840,
                                      clock=clock.clock, sleep=clock.sleep)
        result = results[role]
        assert result == {"v": 1, "role": role, "pair_id": PAIR_ID,
            "self_destination_sha256": hashlib.sha256(DESTINATIONS[role].encode()).hexdigest(),
            "peer_destination_sha256": hashlib.sha256(DESTINATIONS[peer.other].encode()).hexdigest(),
            "explicit_decision": "request_approved" if role == "windows" else "invitation_accepted",
            "contact_count": 1, "contact_trust": "approved", "messaging_ready": True,
            "pairing_transferred": True, "cancel_preserved_transferred": True,
            "outbound_text_sha256": flow._digest(flow._text(PAIR_ID, role)),
            "outbound_message_count": 1, "outbound_delivered": True,
            "inbound_text_sha256": flow._digest(flow._text(PAIR_ID, peer.other)),
            "inbound_message_count": 1, "public_request_count": len(peer.calls)}
        assert result["public_request_count"] <= 96
        assert all(op != "native.command" for op, _, _ in peer.calls)
        assert all(payload == {} for phase, payload in exchange.published if phase != "offer_code")
        assert exchange.published[0] == (("offer_code", {"pairing_code": "sealed-offer-code"})
                                          if role == "windows" else ("invitation_accepted", {}))
    assert results["windows"]["outbound_text_sha256"] == results["android"]["inbound_text_sha256"]
    assert results["android"]["outbound_text_sha256"] == results["windows"]["inbound_text_sha256"]


def test_offer_code_polling_waits_at_least_five_seconds():
    clock = Clock()
    result = flow.run_role("windows", Peer("windows", pending_offer=True), Exchange("windows"),
                           pair_id=PAIR_ID, deadline=840, clock=clock.clock, sleep=clock.sleep)
    assert result["public_request_count"] > 0
    assert clock.sleeps == [5]


def test_request_budget_refuses_call_before_adapter_send():
    clock, peer = Clock(), Peer("android")
    scenario = flow.Flow("android", peer, Exchange("android"), PAIR_ID, 840, clock.clock, clock.sleep)
    scenario.requests = 96
    with pytest.raises(ValueError, match="public_pair_request_budget"):
        scenario.request("runtime.capabilities")
    assert peer.calls == []


def test_poll_attempt_cap_and_five_second_spacing():
    clock = Clock()
    scenario = flow.Flow("android", Peer("android"), Exchange("android"), PAIR_ID,
                         840, clock.clock, clock.sleep)
    probes = []
    with pytest.raises(TimeoutError, match="public_pair_missing"):
        scenario.wait("missing", 3, lambda: probes.append(clock.clock()) or None)
    assert probes == [0, 5, 10] and clock.sleeps == [5, 5]


@pytest.mark.parametrize("completed_at,accepted", [(90, False), (89.999, True)])
def test_observation_must_complete_inside_phase_deadline(completed_at, accepted):
    clock = Clock()
    scenario = flow.Flow("android", Peer("android"), Exchange("android"), PAIR_ID,
                         840, clock.clock, clock.sleep)
    def observe():
        clock.now = completed_at
        return {"ready": True}
    if accepted:
        assert scenario.wait("boundary", 1, observe) == {"ready": True}
    else:
        with pytest.raises(TimeoutError, match="public_pair_boundary"):
            scenario.wait("boundary", 1, observe)


@pytest.mark.parametrize("method", ["publish", "receive"])
@pytest.mark.parametrize("offset,accepted", [(0, False), (-0.001, True)])
def test_setup_exchange_must_complete_inside_its_phase_deadline(method, offset, accepted):
    clock = Clock()
    class AdvancingExchange(Exchange):
        def publish(self, phase, payload, deadline):
            clock.now = deadline + offset
        def receive(self, phase, deadline):
            clock.now = deadline + offset
            return {}
    scenario = flow.Flow("android", Peer("android"), AdvancingExchange("android"), PAIR_ID,
                         840, clock.clock, clock.sleep)
    action = (lambda: scenario.publish("ready", {})) if method == "publish" else (lambda: scenario.receive("ready"))
    if accepted:
        assert action() == ({} if method == "receive" else None)
    else:
        with pytest.raises(TimeoutError, match="public_pair_setup_deadline"):
            action()


def test_finish_reserve_blocks_new_public_request():
    clock, peer = Clock(), Peer("android")
    scenario = flow.Flow("android", peer, Exchange("android"), PAIR_ID, 840,
                         clock.clock, clock.sleep)
    clock.now = 780
    with pytest.raises(TimeoutError, match="public_pair_deadline"):
        scenario.request("runtime.capabilities")
    assert peer.calls == [] and scenario.requests == 0


def test_setup_control_rejects_unexpected_payload():
    clock = Clock()
    class UnsealedProduct(Exchange):
        def receive(self, phase, deadline):
            return {"text": "product-content"}
    scenario = flow.Flow("android", Peer("android"), UnsealedProduct("android"), PAIR_ID,
                         840, clock.clock, clock.sleep)
    with pytest.raises(ValueError, match="public_pair_setup"):
        scenario.receive("ready")


def test_inbound_duplicate_is_rejected():
    clock = Clock()
    with pytest.raises(ValueError, match="public_pair_duplicate_inbound"):
        flow.run_role("android", Peer("android", duplicate_inbound=True), Exchange("android"),
                      pair_id=PAIR_ID, deadline=840, clock=clock.clock, sleep=clock.sleep)


@pytest.mark.parametrize("bad_pair", ["A" * 32, "short", "g" * 32])
def test_pair_id_is_exact_lowercase_hex(bad_pair):
    clock, peer = Clock(), Peer("windows")
    with pytest.raises(ValueError, match="public_pair_arguments"):
        flow.run_role("windows", peer, Exchange("windows"), pair_id=bad_pair,
                      deadline=840, clock=clock.clock, sleep=clock.sleep)
    assert peer.calls == []
