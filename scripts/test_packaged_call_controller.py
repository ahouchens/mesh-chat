"""A failed role cannot become a pass when cleanup loses child custody."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import packaged_call_controller as controller
from packaged_call_exchange import pair_id


class PackagedCallControllerTest(unittest.TestCase):
    def test_failed_flow_retains_negative_driver_cleanup(self):
        fields = {"repository": "example/mesh", "repository_id": 1,
                  "run_id": 2, "run_attempt": 1, "source_commit": "a" * 40,
                  "source_tree": "b" * 40}
        context = {**fields, "pair_id": pair_id(fields)}
        class BrokenGui:
            preflight = {"passed": True}
            candidate = dict.fromkeys(("delivery_report_sha256", "release_manifest_sha256",
                "installer_sha256", "application_sha256", "sidecar_sha256"), "c" * 64)
            cleanup = {"driver_reader_retired": False}
            def __init__(self, *args): pass
            def open(self): return self
            def close(self): return False
        class Exchange:
            def __init__(self, *args): pass
            def connect(self, *args): pass
            def close(self): pass
        class Flow:
            def __init__(self, *args): pass
            def run(self, *_args): raise RuntimeError("deliberate_flow_failure")
        with tempfile.TemporaryDirectory() as temporary:
            with (patch.object(controller, "admitted", return_value=(context, Path(temporary))),
                  patch.object(controller, "InstalledGui", BrokenGui),
                  patch.object(controller, "Exchange", Exchange),
                  patch.object(controller, "Flow", Flow),
                  patch.object(controller.media, "source_identity", return_value=(
                      fields["source_commit"], fields["source_tree"]))):
                result = controller.run("gui", fields["source_commit"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_phase"], "public_gui_call_flow")
        self.assertFalse(result["cleanup"]["gui_retired"])
        self.assertFalse(result["cleanup"]["driver_reader_retired"])
        self.assertTrue(result["cleanup"]["temporary_removed"])


if __name__ == "__main__":
    unittest.main()
