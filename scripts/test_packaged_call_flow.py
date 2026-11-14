"""Receipt identity and public connection-scope regression checks."""

import time
import unittest

from packaged_call_flow import ALTERNATE_PATHS, CALL_KEYS, Flow, text_for


class PublicPeer:
    def __init__(self, messages, observations=None):
        self.messages = messages
        self.observations = observations or {}

    def request(self, operation, params=None, key=None):
        if operation == "application.snapshot": return {"messages": self.messages}
        if operation == "profile.query": return {"connections": list(self.observations)}
        if operation == "connection.snapshot": return {"observation": self.observations[params["connection"]]}
        raise AssertionError(operation)


class PackagedCallFlowTest(unittest.TestCase):
    def flow(self, messages, observations=None):
        work = Flow("peer", PublicPeer(messages, observations), None,
                    "c" * 32, time.monotonic() + 60)
        work.profile = "profile"
        work.contact = {"id": "approved-contact"}
        return work

    def test_inbound_receipt_requires_one_approved_contact(self):
        row = {"kind": "chat", "direction": "inbound", "text": "unique",
               "contact_id": "approved-contact"}
        self.assertEqual(self.flow([row]).peer_inbound("unique"), row)
        with self.assertRaises(ValueError):
            self.flow([row, row]).peer_inbound("unique")
        with self.assertRaises(ValueError):
            self.flow([{**row, "contact_id": "foreign"}]).peer_inbound("unique")

    def test_public_readiness_rejects_ambiguous_ready_connections(self):
        ready = {"messaging_ready": True, "carrier": "open", "runtime_epoch": "one", "sequence": 5}
        self.assertIsNone(self.flow([], {"first": ready, "second": ready}).connection())
        self.assertEqual(self.flow([], {"first": ready}).connection(), ready)

    def test_alternate_path_setting_requires_positive_readback(self):
        required = {"profile.create", "peer.pairing_begin", "peer.pairing_query",
                    "peer.approve", "application.snapshot", "call.ice_servers",
                    "call.media_query", "call.control", "message.enqueue", "message.query"}
        class ProfilePeer:
            def __init__(self, network):
                self.network = network
                self.call_queries = 0
            def request(self, operation, params=None, key=None):
                if operation == "runtime.capabilities":
                    return {"profiles": ["profile"], "operations": list(required)}
                if operation == "application.snapshot":
                    return {"profile": None, "contacts": [], "messages": []}
                if operation == "profile.create": return {}
                if operation == "profile.query": return {"destination": "a" * 32}
                if operation == "settings.update":
                    self.assert_settings(params["settings"])
                    return {}
                if operation == "settings.query": return {"settings": self.network}
                if operation == "call.settings_query":
                    self.call_queries += 1
                    return {"settings": {**dict.fromkeys(CALL_KEYS, None),
                        "turn_broker_consent": self.call_queries > 1, "relay_only": self.call_queries > 1}}
                if operation == "call.settings_update": return {}
                raise AssertionError(operation)
            def assert_settings(self, value):
                if value != ALTERNATE_PATHS: raise AssertionError("wrong settings mutation")
        denied = ProfilePeer({**ALTERNATE_PATHS, "lan_fallback": True})
        with self.assertRaises(ValueError):
            Flow("peer", denied, None, "c" * 32, time.monotonic() + 60).peer_profile()
        self.assertEqual(denied.call_queries, 0)
        allowed = ProfilePeer(dict(ALTERNATE_PATHS))
        work = Flow("peer", allowed, None, "c" * 32, time.monotonic() + 60)
        work.peer_profile()
        self.assertTrue(work.checks["fresh_peer_and_relay_consent"])

    def test_onboarding_dismissal_handles_auto_close_and_retained_dialog(self):
        class GuiPeer:
            def __init__(self, titles):
                self.titles = iter(titles)
                self.current = None
                self.closed = False
                self.actions = []
            def request(self, action, **params):
                if action == "observe":
                    self.current = None if self.closed else next(self.titles, self.current)
                    return {"dialogTitle": self.current}
                self.actions.append(action)
                if action == "close_onboarding": self.closed = True
                return {}
        for titles, expected in (([None], []),
                                 (["Connect with WebRTC"] * 50 + [None], ["close_onboarding"])):
            peer = GuiPeer(titles)
            work = Flow("gui", peer, None, "c" * 32, time.monotonic() + 60)
            work.clock = lambda: 0
            def fast_wait(name, probe, seconds=None, interval=0.1):
                if name == "onboarding_auto_dismissed" and expected: raise TimeoutError("call_" + name)
                value = probe()
                if value is None: raise AssertionError(name)
                return value
            work.wait = fast_wait
            work.dismiss_onboarding()
            self.assertEqual(peer.actions, expected)
        foreign = GuiPeer(["Different dialog"])
        work = Flow("gui", foreign, None, "c" * 32, time.monotonic() + 60)
        work.wait = lambda name, probe, seconds=None, interval=0.1: (_ for _ in ()).throw(TimeoutError("call_" + name))
        with self.assertRaises(ValueError): work.dismiss_onboarding()

    def test_staged_peer_receipts_real_media_gate_and_hangup(self):
        pair = "c" * 32
        class StagePeer:
            ended = False
            sent = {}
            def request(self, operation, params=None, key=None):
                if operation == "profile.query": return {"connections": ["owned"]}
                if operation == "connection.snapshot": return {"observation": {
                    "messaging_ready": True, "carrier": "open", "runtime_epoch": "one", "sequence": 5}}
                if operation == "application.snapshot": return {"calls": [] if self.ended else [{
                    "id": "call-1", "core_handle": "call-handle", "direction": "inbound",
                    "state": "ringing"}],
                    "messages": [{"kind": "chat", "direction": "inbound",
                        "text": text_for(pair, "gui", stage), "contact_id": "approved-contact"}
                        for stage in ("before", "after")]}
                if operation == "message.enqueue":
                    identifier = "message-" + params["text"].split(":")[-1]
                    self.sent[identifier] = params
                    return {"message": identifier, "accepted": True}
                if operation == "message.query":
                    sent = self.sent[params["message"]]
                    return {"message": params["message"], "text": sent["text"],
                            "recipient": sent["recipient"], "state": "delivered"}
                if operation == "call.media_query": return {"media": {"remote_sdp": "signed-offer",
                    "id": "call-1", "state": "ended" if self.ended else "ringing"}}
                if operation == "call.ice_servers": return {"ice": {"iceServers": [], "iceTransportPolicy": "all"}}
                if operation == "call.control":
                    if params["action"] != "answer" or params["call_id"] != "call-1": raise AssertionError()
                    return {"result": {"state": "connecting"}}
                raise AssertionError(operation)
        class StageExchange:
            sent = []
            def __init__(self, peer): self.peer = peer
            def publish(self, phase, payload, deadline):
                if payload != {}: raise AssertionError()
                self.sent.append(phase)
            def receive(self, phase, deadline):
                if phase == "call_hungup": self.peer.ended = True
                return {}
        class Browser:
            closed = False
            def request(self, action, **params):
                if action == "answer":
                    if params["offer"] != "signed-offer": raise AssertionError()
                    return {"sdp": "real-answer", "fingerprint": "sha-256 AA:BB"}
                if action == "observe": return {"connected": True, "selectedPair": True,
                    "captured": True, "remoteAudio": True,
                    "outboundPackets": 5, "inboundPackets": 7}
                raise AssertionError(action)
            def close(self): self.closed = True; return True
        peer = StagePeer()
        exchange = StageExchange(peer)
        browser = Browser()
        work = Flow("peer", peer, exchange, pair, time.monotonic() + 120)
        work.profile = "profile"
        work.contact = {"id": "approved-contact", "core_handle": "peer-handle"}
        work.ready()
        work.before()
        work.call(browser)
        work.after()
        self.assertEqual(exchange.sent, ["ready", "precall_peer_sent", "call_active",
                                         "during_peer_sent", "postcall_peer_sent", "done"])
        self.assertTrue(browser.closed)
        self.assertTrue(work.checks["two_way_before"])
        self.assertTrue(work.checks["two_way_after"])
        self.assertTrue(work.checks["public_same_runtime_epoch"])
        self.assertEqual(work.checks["real_media_packets"]["inboundPackets"], 7)


if __name__ == "__main__":
    unittest.main()
