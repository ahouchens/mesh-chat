"""Receipt identity and public connection-scope regression checks."""

import time
import unittest

from packaged_call_flow import Flow


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


if __name__ == "__main__":
    unittest.main()
