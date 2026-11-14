"""Focused same-run sealing and provenance checks without network access."""

import unittest

from cryptography.exceptions import InvalidTag

from packaged_call_exchange import (SealedPhase, artifact_name, checked_context,
                                     pair_id)


def context():
    fields = {"repository": "example/mesh", "repository_id": 11, "run_id": 22,
              "run_attempt": 1, "source_commit": "a" * 40, "source_tree": "b" * 40}
    return {**fields, "pair_id": pair_id(fields)}


class PackagedCallExchangeTest(unittest.TestCase):
    def setUp(self):
        self.context = context()
        self.now = 2_000_000_000
        self.peer = SealedPhase(self.context, "peer", clock=lambda: self.now)
        self.gui = SealedPhase(self.context, "gui", clock=lambda: self.now)
        self.peer.bind(self.gui.manifest())
        self.gui.bind(self.peer.manifest())

    def tearDown(self):
        self.peer.close()
        self.gui.close()

    def test_exact_pairing_code_roundtrip_and_replay_refusal(self):
        code = "MESHPAIR2.private-code"
        bundle = self.peer.seal("offer_code", {"pairing_code": code})
        self.assertEqual(self.gui.open("offer_code", bundle), {"pairing_code": code})
        with self.assertRaises(ValueError):
            self.gui.open("offer_code", bundle)
        with self.assertRaises(ValueError):
            self.peer.seal("offer_code", {"pairing_code": code})

    def test_ciphertext_and_run_identity_fail_closed(self):
        bundle = self.peer.seal("approved", {})
        changed = {**bundle, "ciphertext": bundle["ciphertext"][:-1] +
                   ("A" if bundle["ciphertext"][-1] != "A" else "B")}
        with self.assertRaises((ValueError, InvalidTag)):
            self.gui.open("approved", changed)
        altered = dict(self.context, run_attempt=2)
        with self.assertRaises(ValueError):
            checked_context(altered)
        with self.assertRaises(ValueError):
            artifact_name(self.context, "gui", "offer_code")


if __name__ == "__main__":
    unittest.main()
