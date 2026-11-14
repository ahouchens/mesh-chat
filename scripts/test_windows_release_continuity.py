"""Pure Windows release custody and continuity gates; never launch an installer."""

import unittest
from unittest.mock import patch
from pathlib import Path
from argparse import Namespace
import json
import subprocess

import run_windows_release_continuity as continuity
import windows_release_app_custody as custody


class FakeProcess:
    pid = 401
    def __init__(self): self.running = True
    def poll(self): return None if self.running else 0
    def wait(self, timeout): self.running = False; return 0
    def kill(self): self.running = False


class FakeJob:
    def __init__(self, events, *, forced=False):
        self.events, self.forced, self.handle = events, forced, 99
    def assign(self, process): self.events.append("assign")
    def wait_zero(self, seconds=5): return not self.forced
    def close(self): self.events.append("close"); return True, self.forced


class RaisingCloseJob(FakeJob):
    def close(self): self.events.append("close_raises"); raise OSError("job_query_failed")


class FakeApi:
    def __init__(self, events, *, escaped=False):
        self.events, self.escaped = events, escaped
        self.closed = []
    def resume_initial_thread(self, pid): self.events.append("resume")
    def process_rows(self):
        return [(402, 401, "mesh-chat-service.exe")] if self.escaped else []
    def hold_job_member(self, pid, job): self.events.append("hold"); return 402
    def exited(self, handle): return True
    def close_handle(self, handle): self.closed.append(handle)


class CustodyTests(unittest.TestCase):
    def test_sidecar_descendants_include_workers_and_exclude_unrelated_processes(self):
        rows = [(11, 10, "other.exe"), (12, 11, "mesh-chat-service.exe"),
                (13, 99, "mesh-chat-service.exe")]
        self.assertEqual(custody.descendant_sidecars(rows, 10), {12})

    def test_assigns_job_before_resuming_app(self):
        events = []
        process = FakeProcess()
        app = custody.OwnedApp.launch("app", "dir", {}, 1000,
            popen=lambda *args, **kwargs: process,
            job_factory=lambda: FakeJob(events),
            api_factory=lambda: FakeApi(events))
        self.assertEqual(events, ["assign", "resume"])
        self.assertTrue(app.process.running)

    def test_positive_retirement_requires_sidecar_exit_and_job_zero(self):
        events = []
        process = FakeProcess()
        api = FakeApi(events)
        app = custody.OwnedApp(process, FakeJob(events), api, 1000)
        app.sidecars = [402]
        with patch.object(custody.media, "request_app_window_close", return_value=True), \
             patch.object(custody.media, "cdp_closed", return_value=True):
            self.assertTrue(app.retire())
        self.assertEqual(api.closed, [402])

    def test_forced_close_or_escaped_sidecar_fails(self):
        for forced, escaped in ((True, False), (False, True)):
            with self.subTest(forced=forced, escaped=escaped):
                events = []
                app = custody.OwnedApp(FakeProcess(), FakeJob(events, forced=forced),
                                       FakeApi(events, escaped=escaped), 1000)
                app.sidecars = [402]
                with patch.object(custody.media, "request_app_window_close", return_value=True), \
                     patch.object(custody.media, "cdp_closed", return_value=True):
                    if escaped:
                        with patch.object(custody.time, "monotonic", side_effect=[0, 11]):
                            self.assertFalse(app.retire())
                    else:
                        self.assertFalse(app.retire())

    def test_observation_error_still_closes_kill_on_close_job(self):
        events = []
        app = custody.OwnedApp(FakeProcess(), FakeJob(events), FakeApi(events), 1000)
        with patch.object(custody.media, "request_app_window_close", side_effect=OSError):
            with self.assertRaises(OSError): app.retire()
        self.assertIn("close", events)

    def test_installer_job_is_assigned_before_resume_and_must_exit_cleanly(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                events = []
                process = FakeProcess()
                code, clean = custody.install_with_job("installer /S /D=C:\\test", Path("C:/installer.exe"),
                    popen=lambda *args, **kwargs: process,
                    job_factory=lambda: FakeJob(events, forced=forced),
                    api_factory=lambda: FakeApi(events))
                self.assertEqual(code, 0)
                self.assertEqual(clean, not forced)
                self.assertEqual(events[:2], ["assign", "resume"])
                self.assertEqual(events[-1], "close")

    def test_app_launch_failure_kills_and_waits_when_job_close_raises(self):
        events = []
        class TrackedProcess(FakeProcess):
            def kill(self): events.append("kill"); super().kill()
            def wait(self, timeout): events.append("wait"); return super().wait(timeout)
        class RaisingApi(FakeApi):
            def resume_initial_thread(self, pid): raise ValueError("resume_failed")
        with self.assertRaisesRegex(ValueError, "resume_failed") as caught:
            custody.OwnedApp.launch("app", "dir", {}, 1000,
                popen=lambda *args, **kwargs: TrackedProcess(),
                job_factory=lambda: RaisingCloseJob(events),
                api_factory=lambda: RaisingApi(events))
        self.assertEqual(events, ["assign", "close_raises", "kill", "wait"])
        self.assertEqual(caught.exception.release_cleanup["job_close_failed"], True)
        self.assertEqual(caught.exception.release_cleanup["process_retired"], True)

    def test_installer_primary_timeout_survives_raising_job_close(self):
        events = []
        class TimedOutProcess(FakeProcess):
            def wait(self, timeout):
                events.append("wait")
                if self.running: raise subprocess.TimeoutExpired("installer", timeout)
                return 0
            def kill(self): events.append("kill"); super().kill()
        cleanup = {}
        with self.assertRaises(subprocess.TimeoutExpired):
            custody.install_with_job("installer", Path("C:/installer.exe"),
                popen=lambda *args, **kwargs: TimedOutProcess(),
                job_factory=lambda: RaisingCloseJob(events),
                api_factory=lambda: FakeApi(events), cleanup=cleanup)
        self.assertEqual(events, ["assign", "resume", "wait", "close_raises", "kill", "wait"])
        self.assertEqual(cleanup["job_close_failed"], True)
        self.assertEqual(cleanup["process_retired"], True)


class ContinuityTests(unittest.TestCase):
    def test_hashes_must_cover_each_field_and_equal_reopen(self):
        valid = {field: "a" * 64 for field in
                 ("profile", "workspace", "channel", "message_id", "message_text", "draft_text")}
        self.assertTrue(continuity.check_hashes(*({"hashes": valid} for _ in range(3))))
        changed = {**valid, "draft_text": "b" * 64}
        self.assertFalse(continuity.check_hashes({"hashes": valid}, {"hashes": valid}, {"hashes": changed}))
        self.assertFalse(continuity.check_hashes({"hashes": valid}, {"hashes": {}}, {"hashes": valid}))

    def test_ui_config_binds_baseline_and_candidate_to_same_markers(self):
        old = continuity.ui_config("seed", continuity.BASELINE_SOURCE, "123 1")
        new = continuity.ui_config("observe", "b" * 40, "123 1")
        self.assertEqual(old["workspace_name"], new["workspace_name"])
        self.assertEqual(old["message_text"], new["message_text"])
        self.assertEqual(old["draft_text"], new["draft_text"])
        self.assertNotEqual(old["expected_source"], new["expected_source"])

    def test_report_binding_contains_only_pinned_hashes_and_sizes(self):
        candidate = {"source_commit": "a" * 40, "source_tree": "b" * 40,
                     "delivery_report_sha256": "c" * 64, "release_manifest_sha256": "d" * 64,
                     "installer_size": 1, "installer_sha256": "e" * 64,
                     "application_size": 2, "application_sha256": "f" * 64,
                     "sidecar_size": 3, "sidecar_sha256": "0" * 64,
                     "installer_path": Path("secret/location"), "raw_snapshot": "never report"}
        binding = continuity.candidate_binding(candidate)
        self.assertEqual(binding["delivery_report_sha256"], "c" * 64)
        self.assertEqual(binding["sidecar"], {"size_bytes": 3, "sha256": "0" * 64})
        self.assertNotIn("secret/location", json.dumps(binding))
        self.assertNotIn("never report", json.dumps(binding))

    def test_ui_report_is_checked_before_it_can_be_retained(self):
        config = continuity.ui_config("seed", continuity.BASELINE_SOURCE, "123 1")
        hashes = {field: "a" * 64 for field in
                  ("profile", "workspace", "channel", "message_id", "message_text", "draft_text")}
        report = {"v": 1, "passed": True,
                  "evidence_level": "windows_release_ui_seed_readback_contract_only",
                  "source_commit": continuity.BASELINE_SOURCE, "installed_version": continuity.VERSION,
                  "phase": "seed", "hashes": hashes, "native_upgrade_qualified": False,
                  "peer_receipt_qualified": False, "schema_refusal_qualified": False,
                  "physical_device_identity_qualified": False}
        response = lambda value: subprocess.CompletedProcess([], 0, (json.dumps(value) + "\n").encode(), b"")
        with patch.object(continuity.subprocess, "run", return_value=response(report)):
            self.assertEqual(continuity.run_ui(Path("node"), 1000, config), report)
        with patch.object(continuity.subprocess, "run", return_value=response({**report, "raw_snapshot": "secret"})):
            with self.assertRaisesRegex(continuity.ContinuityFailure, "ui_driver_report_invalid"):
                continuity.run_ui(Path("node"), 1000, config)
        with patch.object(continuity.subprocess, "run", return_value=response({**report, "hashes": {"profile": "secret"}})):
            with self.assertRaisesRegex(continuity.ContinuityFailure, "ui_driver_report_invalid"):
                continuity.run_ui(Path("node"), 1000, config)
        failure = {"v": 1, "passed": False,
                   "evidence_level": "windows_release_ui_seed_readback_contract_only",
                   "failure_kind": "ui_source_mismatch",
                   "cleanup_failure_kind": "ui_socket_retirement_failed"}
        with patch.object(continuity.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, (json.dumps(failure) + "\n").encode(), b"")):
            with self.assertRaises(continuity.UiDriverFailure) as caught:
                continuity.run_ui(Path("node"), 1000, config)
        self.assertEqual(caught.exception.code, "ui_source_mismatch")
        self.assertEqual(caught.exception.cleanup_code, "ui_socket_retirement_failed")
        with patch.object(continuity.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, (json.dumps({**failure, "failure_kind": "ui_contract_failed"}) + "\n").encode(), b"")):
            with self.assertRaises(continuity.UiDriverFailure) as caught:
                continuity.run_ui(Path("node"), 1000, config)
        self.assertEqual(caught.exception.code, "ui_contract_failed")
        startup = dict.fromkeys(("bridge_ready", "build_info_seen", "source_matches",
                                 "version_matches", "root_mounted", "title_matches"), True)
        startup["root_mounted"] = False
        with patch.object(continuity.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, (json.dumps({**failure, "failure_kind": "ui_mount_deadline",
                                  "startup_observation": startup}) + "\n").encode(), b"")):
            with self.assertRaises(continuity.UiDriverFailure) as caught:
                continuity.run_ui(Path("node"), 1000, config)
        self.assertEqual(caught.exception.startup, startup)
        for malformed in ({**failure, "failure_kind": "secret path"},
                          {**failure, "failure_kind": []},
                          {**failure, "startup_observation": {**startup, "raw_source": "secret"}},
                          {**failure, "startup_observation": {**startup, "root_mounted": 0}},
                          {**failure, "raw_error": "secret"}):
            with patch.object(continuity.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, (json.dumps(malformed) + "\n").encode(), b"")):
                with self.assertRaisesRegex(continuity.ContinuityFailure, "ui_driver_report_invalid"):
                    continuity.run_ui(Path("node"), 1000, config)

    def test_primary_ui_failure_survives_policy_cleanup_failure(self):
        class FakeOwned:
            def retire(self): return True
        class FakePolicy:
            def __init__(self, flags): pass
            def install(self): pass
            def remove(self): return False
        observation = {}
        config = continuity.ui_config("seed", continuity.BASELINE_SOURCE, "123 1")
        with patch.object(continuity.media, "reserve_port", return_value=1000), \
             patch.object(continuity.media, "token_elevated", return_value=True), \
             patch.object(continuity.media, "ScopedBrowserPolicy", FakePolicy), \
             patch.object(continuity.OwnedApp, "launch", return_value=FakeOwned()), \
             patch.object(continuity, "run_ui", side_effect=continuity.UiDriverFailure(
                 "ui_source_mismatch", "ui_socket_retirement_failed")):
            with self.assertRaisesRegex(continuity.ContinuityFailure, "ui_driver_failed"):
                continuity.launch_and_observe(Path("app.exe"), Path("node"), config, observation)
        self.assertEqual(observation["app_retired"], True)
        self.assertEqual(observation["browser_policy_retired"], False)
        self.assertEqual(observation["ui_failure_kind"], "ui_source_mismatch")
        self.assertEqual(observation["ui_cleanup_failure_kind"], "ui_socket_retirement_failed")
        self.assertNotIn("ui_report", observation)

    def test_changed_reopen_hashes_leave_all_bounded_observations_in_failed_report(self):
        source, tree = "b" * 40, "c" * 40
        candidate = {"source_commit": source, "source_tree": tree,
                     "delivery_report_sha256": "d" * 64, "release_manifest_sha256": "e" * 64,
                     "installer_size": 5, "installer_sha256": "f" * 64,
                     "application_size": 6, "application_sha256": "1" * 64,
                     "sidecar_size": 7, "sidecar_sha256": "2" * 64,
                     "installer_path": Path("candidate.exe")}
        rows = {role: {"size_bytes": 5, "sha256": "a" * 64, "matches_expected": True}
                for role in ("application", "sidecar")}
        reports = []
        def observe(app, node, config, observation):
            character = "b" if len(reports) == 2 else "a"
            value = {"hashes": {field: character * 64 for field in
                                 ("profile", "workspace", "channel", "message_id", "message_text", "draft_text")}}
            observation.update(ui_report=value, app_retired=True, browser_policy_retired=True)
            reports.append(value)
            return value
        args = Namespace(run_id="123", run_attempt=1, candidate_source=source,
                         candidate_tree=tree, baseline_installer=Path("baseline.exe"), node=Path("node"))
        result = {"passed": False}
        with patch.dict(continuity.os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                                               "GITHUB_SHA": source}, clear=True), \
             patch.object(continuity.sys, "platform", "win32"), \
             patch.object(continuity.installer, "fresh_runner_temp", return_value=Path("C:/runner")), \
             patch.object(continuity.installer, "fresh_user_app_data"), \
             patch.object(continuity, "require_fresh_credential_slot"), \
             patch.object(continuity, "require_webview2_ready"), \
             patch.object(continuity, "exact_file", return_value=True), \
             patch.object(continuity.subprocess, "check_output", return_value=continuity.BASELINE_SOURCE), \
             patch.object(continuity.media, "source_identity", return_value=(source, tree)), \
             patch.object(continuity.installer, "source_bound_candidate", return_value=candidate), \
             patch.object(continuity.tempfile, "mkdtemp", return_value="C:/installed"), \
             patch.object(continuity, "install_owned", return_value=(0, True)), \
             patch.object(continuity, "observed_baseline_files", return_value=rows), \
             patch.object(continuity.media, "known_folder", return_value=Path("C:/roaming")), \
             patch.object(continuity, "protected_profile", return_value=True), \
             patch.object(continuity, "launch_and_observe", side_effect=observe), \
             patch.object(continuity.installer, "installed_artifacts", return_value=rows), \
             patch.object(continuity.installer, "installed_artifacts_match", return_value=True):
            with self.assertRaisesRegex(continuity.ContinuityFailure, "ui_continuity_hashes_changed"):
                continuity.execute(args, result)
        self.assertFalse(result["passed"])
        self.assertEqual(set(result["ui_observations"]),
                         {"published_seed", "candidate_observe", "candidate_reopen"})
        self.assertEqual(result["ui_observations"]["candidate_reopen"]["ui_report"], reports[2])
        self.assertEqual(result["candidate_installed_files_after_reopen"], rows)
        self.assertEqual(result["candidate_binding"]["delivery_report_sha256"], "d" * 64)
        self.assertEqual(result["published_expected_files"]["application"]["size_bytes"], 8604672)


if __name__ == "__main__": unittest.main()
