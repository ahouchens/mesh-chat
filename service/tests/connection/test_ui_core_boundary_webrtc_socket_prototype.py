"""Offline failure gates for the isolated WebRTC C++ prototype workflow."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "webrtc_socket_prototype.py"
SPEC = importlib.util.spec_from_file_location("webrtc_socket_prototype", SCRIPT)
assert SPEC and SPEC.loader
prototype = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prototype)


def sample_patch(path: str = "p2p/base/turn_port_unittest.cc", add_test: bool = True) -> str:
    line = "+TEST_F(TurnPortSocketTest, CapturesSelectedTcpTuple) {}\n" if add_test else "+// no test\n"
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n@@ -1 +1,2 @@\n context\n{line}")


class PatchInputs(unittest.TestCase):
    def test_missing_patch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(prototype.PrototypeError, "required patch absent"):
                prototype.patch_inventory(Path(directory) / "absent.patch")

    def test_outside_p2p_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "patch.diff"
            candidate.write_text(sample_patch("sdk/android/PeerConnection.java"), encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "outside p2p"):
                prototype.patch_inventory(candidate)

    def test_patch_without_regression_case_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "patch.diff"
            candidate.write_text(sample_patch(add_test=False), encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "at least one TEST"):
                prototype.patch_inventory(candidate)

    def test_valid_patch_yields_exact_case_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "patch.diff"
            candidate.write_text(sample_patch(), encoding="utf-8")
            inventory = prototype.patch_inventory(candidate)
            self.assertEqual(inventory["selectedTests"], ["TurnPortSocketTest.CapturesSelectedTcpTuple"])
            self.assertEqual(inventory["sha256"], prototype.sha256(candidate))

    def test_wrong_deps_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "DEPS"
            candidate.write_text("moving input", encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "SHA256 mismatch"):
                prototype.verify_checkout_file(candidate, prototype.DEPS_SHA256, "DEPS")

    def test_post_apply_inventory_includes_new_untracked_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            p2p = source / "p2p" / "base"
            p2p.mkdir(parents=True)
            existing = p2p / "turn_port.cc"
            added = p2p / "turn_tcp_socket_tuple.h"
            existing.write_text("patched implementation\n", encoding="utf-8")
            added.write_text("new value header\n", encoding="utf-8")
            inventory = prototype.patched_file_inventory(source, [
                "p2p/base/turn_port.cc", "p2p/base/turn_tcp_socket_tuple.h"])
            self.assertEqual([item["relativePath"] for item in inventory], [
                "p2p/base/turn_port.cc", "p2p/base/turn_tcp_socket_tuple.h"])
            self.assertEqual(inventory[1]["sha256"], prototype.sha256(added))

    def test_post_apply_inventory_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(prototype.PrototypeError, "absent after apply"):
                prototype.patched_file_inventory(Path(directory), ["p2p/base/absent.h"])


class ResolvedInputs(unittest.TestCase):
    def test_library_alone_is_not_a_runnable_test_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "p2p").mkdir()
            (source / "BUILD.gn").write_text('group("default") {}\n', encoding="utf-8")
            (source / "p2p" / "BUILD.gn").write_text(
                'rtc_library("rtc_p2p_unittests") {}\n', encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "root runnable"):
                prototype.verify_test_target(source)

    def test_moving_git_revision_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            path.write_text(json.dumps({
                "src": {"url": prototype.SOURCE_REPO, "rev": prototype.SOURCE_REVISION},
                "src/build": {"url": "https://example.org/build.git", "rev": "main"},
            }), encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "unresolved or moving"):
                prototype.verify_resolved_revisions(path)

    def test_wrong_source_revision_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            path.write_text(json.dumps({
                "src": {"url": prototype.SOURCE_REPO, "rev": "0" * 40},
            }), encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "differs"):
                prototype.verify_resolved_revisions(path)

    def test_pinned_revisions_are_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            path.write_text(json.dumps({
                "src": {"url": prototype.SOURCE_REPO, "rev": prototype.SOURCE_REVISION},
                "src/build": {"url": "https://example.org/build.git", "rev": "a" * 40},
            }), encoding="utf-8")
            self.assertEqual(prototype.verify_resolved_revisions(path)["entries"], 2)

    def test_cipd_instance_and_deps_pinned_gcs_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            path.write_text(json.dumps({
                "src": {"url": prototype.SOURCE_REPO, "rev": prototype.SOURCE_REVISION},
                "src/third_party/tool:pkg": {
                    "url": "https://chrome-infra-packages.appspot.com/p/pkg/+/" + "A" * 43,
                    "rev": None,
                },
                "src/third_party/clang": {
                    "url": "gs://chromium-browser-clang/Linux_x64/pinned.tar.xz", "rev": None,
                },
            }), encoding="utf-8")
            kinds = prototype.verify_resolved_revisions(path)["kinds"]
            self.assertEqual(kinds["cipdInstance"], 1)
            self.assertEqual(kinds["gcsDepsPinned"], 1)


class TestReceipts(unittest.TestCase):
    def test_binary_inventory_must_contain_new_test(self) -> None:
        listed = prototype.extract_listed_tests("ExistingSuite.\n  ExistingCase\n")
        with self.assertRaisesRegex(prototype.PrototypeError, "absent from binary"):
            prototype.verify_listed_tests(listed, ["TurnPortSocketTest.CapturesSelectedTcpTuple"])

    def test_xml_requires_executed_passing_selected_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xml"
            path.write_text('<testsuites><testsuite><testcase classname="TurnPortSocketTest" '
                            'name="CapturesSelectedTcpTuple"><skipped/></testcase></testsuite></testsuites>',
                            encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "did not pass"):
                prototype.validate_test_xml(path, ["TurnPortSocketTest.CapturesSelectedTcpTuple"])

    def test_xml_rejects_notrun_or_suppressed_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xml"
            for status, result in (("notrun", "suppressed"), ("run", "suppressed"),
                                   ("notrun", "completed")):
                with self.subTest(status=status, result=result):
                    path.write_text(
                        '<testsuites><testsuite><testcase classname="TurnPortTest" '
                        f'name="TestTurnTcpAllocate" status="{status}" result="{result}"/>'
                        '</testsuite></testsuites>', encoding="utf-8")
                    with self.assertRaisesRegex(prototype.PrototypeError, "did not pass"):
                        prototype.validate_test_xml(path, ["TurnPortTest.TestTurnTcpAllocate"])

    def test_xml_rejects_duplicate_selected_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xml"
            case = ('<testcase classname="TurnPortTest" name="TestTurnTcpAllocate" '
                    'status="run" result="completed"/>')
            path.write_text(f"<testsuites><testsuite>{case}{case}</testsuite></testsuites>",
                            encoding="utf-8")
            with self.assertRaisesRegex(prototype.PrototypeError, "duplicated selected cases"):
                prototype.validate_test_xml(path, ["TurnPortTest.TestTurnTcpAllocate"])

    def test_xml_accepts_one_realistic_completed_gtest_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.xml"
            path.write_text(
                '<testsuites tests="1" failures="0" disabled="0" errors="0" time="0.002">'
                '<testsuite name="TurnPortTest" tests="1" failures="0" disabled="0" '
                'errors="0" time="0.002">'
                '<testcase name="TestTurnTcpAllocate" status="run" result="completed" '
                'time="0.002" classname="TurnPortTest"/>'
                '</testsuite></testsuites>', encoding="utf-8")
            result = prototype.validate_test_xml(path, ["TurnPortTest.TestTurnTcpAllocate"])
            self.assertEqual(result["allCaseCount"], 1)
            self.assertEqual(result["sha256"], prototype.sha256(path))

    def test_preflight_failure_still_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            patch_path = repo / prototype.PATCH_RELATIVE
            patch_path.parent.mkdir(parents=True)
            patch_path.write_text(sample_patch(), encoding="utf-8")
            evidence = root / "evidence"
            with patch.object(prototype.sys, "platform", "linux"), patch.object(
                    prototype, "disk_snapshot", return_value={"freeBytes": 1}):
                with self.assertRaisesRegex(prototype.PrototypeError, "initial free disk"):
                    prototype.run_prototype(repo, root / "work", evidence)
            result = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(result["nativeAcceptanceClaim"])
            self.assertIn("failed or blocked", result["status"])
            self.assertEqual(result["patch"]["selectedTests"], ["TurnPortSocketTest.CapturesSelectedTcpTuple"])


if __name__ == "__main__":
    unittest.main()
