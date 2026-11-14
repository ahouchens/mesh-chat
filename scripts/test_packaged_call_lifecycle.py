"""Actual Windows children: stalled stdin, job descendants, partial startup."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from packaged_call_gui_session import GuiControl
from packaged_call_io import BoundedWriter
from packaged_call_peer import BrowserProcess
from packaged_call_windows_job import WindowsJob


def bounded_line(process, seconds=3):
    result = []
    reader = threading.Thread(target=lambda: result.append(process.stdout.readline()), daemon=True)
    reader.start()
    reader.join(seconds)
    if reader.is_alive():
        process.kill()
        process.wait(timeout=5)
        reader.join(5)
        raise TimeoutError("child_stdout_stalled")
    return result[0]


@unittest.skipUnless(sys.platform == "win32", "Windows child and Job Object checks")
class PackagedCallLifecycleTest(unittest.TestCase):
    def test_stalled_reader_cannot_extend_write_deadline(self):
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW)
        def terminate():
            if child.poll() is None: child.kill()
            child.wait(timeout=5)
            return child.poll() is not None
        writer = BoundedWriter(child.stdin, terminate)
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                writer.write(b"x" * (256 * 1024), time.monotonic() + 0.5)
            self.assertLess(time.monotonic() - started, 8)
            self.assertTrue(writer.retired)
            self.assertIsNotNone(child.poll())
        finally:
            terminate()
            child.stdin.close()

    def test_job_owns_spawned_descendant_before_start(self):
        code = ("import subprocess,sys,time;"
                "sys.stdin.buffer.readline();"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                "print(child.pid,flush=True);time.sleep(60)")
        parent = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=subprocess.CREATE_NO_WINDOW)
        job = WindowsJob()
        try:
            job.assign(parent)
            BoundedWriter(parent.stdin, job.terminate).write(b"start\n", time.monotonic() + 3)
            child_pid = int(bounded_line(parent).strip())
            self.assertGreater(child_pid, 0)
            self.assertGreaterEqual(job.active(), 2)
            zero, forced = job.close()
            self.assertTrue(zero)
            self.assertTrue(forced)
            parent.wait(timeout=5)
            self.assertIsNotNone(parent.poll())
        finally:
            if job.handle is not None: job.close()
            if parent.poll() is None: parent.kill(); parent.wait(timeout=5)
            parent.stdin.close()
            parent.stdout.close()

    def test_browser_request_stalled_reader_retires_owned_job(self):
        with tempfile.TemporaryDirectory(prefix="mesh-call-test-") as temporary:
            edge = Path(temporary) / "msedge.exe"
            edge.write_bytes(b"test-placeholder")
            browser = BrowserProcess(Path(sys.executable), edge, Path(temporary))
            browser.directory = Path(tempfile.mkdtemp(prefix="mesh-call-edge-", dir=temporary))
            browser.process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW)
            browser.job = WindowsJob()
            browser.job.assign(browser.process)
            browser.reader = threading.Thread(target=browser._read, daemon=True)
            browser.reader.start()
            browser.writer = BoundedWriter(browser.process.stdin, browser._terminate_job)
            browser.deadline = time.monotonic() + 0.5
            started = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    browser.request("answer", offer="x" * 200000, ice={})
                self.assertLess(time.monotonic() - started, 8)
                self.assertTrue(browser.writer.retired)
            finally:
                self.assertFalse(browser.close())
            self.assertTrue(browser.cleanup["reader_retired"])
            self.assertTrue(browser.cleanup["job_zero_and_released"])
            self.assertTrue(browser.cleanup["edge_profile_removed"])

    def test_job_allows_graceful_tree_exit(self):
        code = ("import subprocess,sys;sys.stdin.buffer.readline();"
                "child=subprocess.Popen([sys.executable,'-c','pass']);"
                "child.wait();print('done',flush=True)")
        parent = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=subprocess.CREATE_NO_WINDOW)
        job = WindowsJob()
        try:
            job.assign(parent)
            BoundedWriter(parent.stdin, job.terminate).write(b"start\n", time.monotonic() + 3)
            self.assertEqual(bounded_line(parent).strip(), b"done")
            parent.wait(timeout=5)
            zero, forced = job.close()
            self.assertTrue(zero)
            self.assertFalse(forced)
        finally:
            if job.handle is not None: job.close()
            if parent.poll() is None: parent.kill(); parent.wait(timeout=5)
            parent.stdin.close()
            parent.stdout.close()

    def test_partial_gui_and_browser_start_retain_cleanup_handles(self):
        gui = GuiControl(Path(sys.executable), 12345, "a" * 40, time.monotonic() + 10)
        with self.assertRaises(Exception): gui.open()
        self.assertFalse(gui.close())
        self.assertTrue(gui.cleanup["reader_retired"])
        self.assertTrue(gui.cleanup["process_retired"])
        with tempfile.TemporaryDirectory(prefix="mesh-call-test-") as temporary:
            edge = Path(temporary) / "msedge.exe"
            edge.write_bytes(b"test-placeholder")
            browser = BrowserProcess(Path(sys.executable), edge, Path(temporary))
            with self.assertRaises(Exception): browser.open(time.monotonic() + 10)
            self.assertFalse(browser.close())
            self.assertTrue(browser.cleanup["reader_retired"])
            self.assertTrue(browser.cleanup["job_zero_and_released"])
            self.assertTrue(browser.cleanup["edge_profile_removed"])


if __name__ == "__main__":
    unittest.main()
