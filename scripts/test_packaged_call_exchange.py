"""Focused same-run sealing and provenance checks without network access."""

import unittest
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import zipfile

from cryptography.exceptions import InvalidTag

from packaged_call_exchange import (Artifacts, SealedPhase, artifact_name,
                                     canonical, checked_context, pair_id)


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

    def _archive(self, bundle, extra=False):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as zipped:
            zipped.writestr("bundle.json", canonical(bundle))
            if extra: zipped.writestr("foreign.json", b"{}")
        return output.getvalue()

    def _transport(self, bundle, *, extra=False, duplicate=False, bad_digest=False,
                   wrong_source=False):
        archive = self._archive(bundle, extra)
        row = {"name": artifact_name(self.context, "peer", "offer_code"),
               "expired": False, "id": 7, "size_in_bytes": len(archive),
               "digest": "sha256:" + ("0" * 64 if bad_digest else hashlib.sha256(archive).hexdigest()),
               "workflow_run": {"id": self.context["run_id"],
                   "head_sha": "f" * 40 if wrong_source else self.context["source_commit"],
                   "repository_id": self.context["repository_id"]}}
        transport = Artifacts.__new__(Artifacts)
        transport.context, transport.role, transport.clock = self.context, "gui", time.monotonic
        def get(path, deadline, archive=False):
            return self._archive(bundle, extra) if archive else {
                "artifacts": [row, row] if duplicate else [row], "total_count": 2 if duplicate else 1}
        transport.get = get
        return transport

    def test_artifact_wait_rejects_duplicate_digest_zip_and_wrong_source(self):
        bundle = self.peer.seal("offer_code", {"pairing_code": "MESHPAIR2.private-code"})
        deadline = time.monotonic() + 5
        self.assertEqual(self._transport(bundle).wait("peer", "offer_code", deadline), bundle)
        for issue in ("duplicate", "bad_digest", "extra", "wrong_source"):
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                self._transport(bundle, **{issue: True}).wait("peer", "offer_code", deadline)

    def test_artifact_publish_is_exact_source_run_and_once_only(self):
        bundle = self.peer.seal("offer_code", {"pairing_code": "MESHPAIR2.private-code"})
        with tempfile.TemporaryDirectory() as temporary:
            transport = Artifacts.__new__(Artifacts)
            transport.context, transport.role = self.context, "peer"
            transport.directory, transport.node = Path(temporary), "node"
            transport.clock, transport.published = time.monotonic, set()
            def upload(args, **_kwargs):
                self.assertEqual(Path(args[-2]).read_bytes(), canonical(bundle))
                Path(args[-1]).write_text(json.dumps({"passed": True, "id": 9, "size": 100}),
                                          encoding="utf-8")
                return type("Result", (), {"returncode": 0})()
            with patch("packaged_call_exchange.subprocess.run", side_effect=upload):
                transport.publish("offer_code", bundle, time.monotonic() + 5)
                with self.assertRaises(ValueError):
                    transport.publish("offer_code", bundle, time.monotonic() + 5)
                changed = {**bundle, "context": {**self.context, "run_id": 23}}
                with self.assertRaises(ValueError):
                    Artifacts.publish(transport, "offer_code", changed, time.monotonic() + 5)


if __name__ == "__main__":
    unittest.main()
