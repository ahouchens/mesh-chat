"""A failed role cannot become a pass when cleanup loses child custody."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

import packaged_call_controller as controller
from packaged_call_exchange import pair_id


class PackagedCallControllerTest(unittest.TestCase):
    def test_role_admits_exact_push_or_dispatch_source(self):
        fields = {"repository": "example/mesh", "repository_id": 1,
                  "run_id": 2, "run_attempt": 1, "source_commit": "a" * 40,
                  "source_tree": "b" * 40}
        environment = {"GITHUB_REPOSITORY": fields["repository"],
                       "GITHUB_REPOSITORY_ID": str(fields["repository_id"]),
                       "GITHUB_RUN_ID": str(fields["run_id"]),
                       "GITHUB_RUN_ATTEMPT": str(fields["run_attempt"]),
                       "GITHUB_SHA": fields["source_commit"],
                       "GITHUB_JOB": "call_gui", "GITHUB_ACTIONS": "true",
                       "GITHUB_TOKEN": "test-token", "ACTIONS_RUNTIME_TOKEN": "test-runtime"}
        with tempfile.TemporaryDirectory() as temporary:
            environment["RUNNER_TEMP"] = temporary
            with (patch.dict(os.environ, environment, clear=True),
                  patch.object(controller.sys, "platform", "win32"),
                  patch.object(controller.subprocess, "check_output", return_value=fields["source_tree"]),
                  patch.object(controller.media, "source_identity", return_value=(
                      fields["source_commit"], fields["source_tree"]))):
                for event in ("push", "workflow_dispatch"):
                    with self.subTest(event=event):
                        os.environ["GITHUB_EVENT_NAME"] = event
                        self.assertEqual(controller.admitted("gui", fields["source_commit"])[0]["source_tree"],
                                         fields["source_tree"])
                os.environ["GITHUB_EVENT_NAME"] = "pull_request"
                with self.assertRaisesRegex(ValueError, "call_runner_admission"):
                    controller.admitted("gui", fields["source_commit"])

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
