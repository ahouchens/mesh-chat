"""Pure Windows release custody and continuity gates; never launch an installer."""

import unittest
from unittest.mock import patch
from pathlib import Path

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


if __name__ == "__main__": unittest.main()
