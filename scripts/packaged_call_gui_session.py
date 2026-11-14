"""Own one exact-source NSIS GUI, seven-check preflight, and UI input session."""

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

import packaged_media_preflight as media
from packaged_call_io import BoundedWriter
import run_packaged_media_preflight as installer


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/packaged_call_gui.mjs"
MAX_FRAME = 16 * 1024


class GuiControl:
    def __init__(self, node, port, source, deadline):
        self.node, self.port, self.source = node, port, source
        self.deadline = deadline
        self.responses = queue.Queue(maxsize=2)
        self.sequence = 0
        self.process = self.reader = self.writer = None
        self.cleanup = {}

    def open(self):
        self.process = subprocess.Popen([str(self.node), str(DRIVER), str(self.port), self.source],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, bufsize=0,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.writer = BoundedWriter(self.process.stdin, self._terminate)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            try: line = self.responses.get(timeout=self._remaining(25))
            except queue.Empty: raise TimeoutError("gui_ready_deadline") from None
            if line != b'{"ready":true}\n':
                raise ValueError("gui_not_ready")
        except Exception:
            self._terminate()
            raise
        return self

    def _remaining(self, maximum):
        value = min(maximum, self.deadline - time.monotonic())
        if value <= 0: raise TimeoutError("gui_deadline")
        return value

    def _read(self):
        try:
            while line := self.process.stdout.readline(MAX_FRAME + 1):
                if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                    self.responses.put_nowait(None)
                    return
                self.responses.put(line, timeout=1)
        except Exception:
            try: self.responses.put_nowait(None)
            except queue.Full: pass

    def _terminate(self):
        if self.process is None: return True
        try:
            if self.process.poll() is None: self.process.kill()
            self.process.wait(timeout=5)
            if self.reader is not None: self.reader.join(timeout=2)
            return self.process.poll() is not None and (self.reader is None or not self.reader.is_alive())
        except Exception:
            return False

    def request(self, action, **params):
        self.sequence += 1
        request_id = self.sequence
        data = (json.dumps({"id": request_id, "action": action, **params},
                           separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        if not 2 <= len(data) <= MAX_FRAME:
            raise ValueError("gui_frame_limit")
        deadline = min(self.deadline, time.monotonic() + 25)
        self.writer.write(data, deadline)
        try: line = self.responses.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            self._terminate()
            raise TimeoutError("gui_reply_deadline") from None
        if line is None: raise ValueError("gui_reply_invalid")
        value = json.loads(line.decode("utf-8"))
        if type(value) is not dict or value.get("id") != request_id or value.get("ok") is not True:
            raise ValueError("gui_action_failed")
        return value.get("value")

    def close(self):
        if self.process is None:
            self.cleanup = {"writer_retired": True, "reader_retired": True,
                            "process_retired": True, "stdin_closed": True}
            return False
        if self.writer is not None and self.writer.faulted:
            self._terminate()
        closed = threading.Event()
        errors = []
        def close_input():
            try: self.process.stdin.close()
            except Exception as error: errors.append(error)
            finally: closed.set()
        thread = threading.Thread(target=close_input, daemon=True)
        thread.start()
        if not closed.wait(5): self._terminate()
        thread.join(timeout=2)
        try:
            code = self.process.wait(timeout=self._remaining(10))
        except (subprocess.TimeoutExpired, TimeoutError):
            self._terminate()
            code = self.process.poll()
        if self.reader is not None: self.reader.join(timeout=2)
        self.cleanup = {"writer_retired": self.writer is None or self.writer.retired,
                        "reader_retired": self.reader is None or not self.reader.is_alive(),
                        "process_retired": self.process.poll() is not None,
                        "stdin_closed": closed.is_set() and not errors and not thread.is_alive()}
        return code == 0 and all(self.cleanup.values())


class InstalledGui:
    def __init__(self, source, tree, run_id, run_attempt, node, deadline):
        self.source, self.tree = source, tree
        self.run_id, self.run_attempt, self.node = run_id, run_attempt, node
        self.deadline = deadline
        self.installed = self.candidate = self.preflight = None
        self.app = self.policy = self.control = None
        self.port = None
        self.cleanup = {}

    def open(self):
        if sys.platform != "win32" or media.source_identity(self.source, self.tree) != (self.source, self.tree):
            raise ValueError("gui_source_invalid")
        parent = installer.fresh_runner_temp()
        self.candidate = installer.source_bound_candidate(installer.DELIVERY, self.source, self.tree)
        installer.fresh_user_app_data()
        self.installed = Path(tempfile.mkdtemp(prefix="mesh-call-install-", dir=parent))
        code, retired = installer.install(self.candidate["installer_path"], self.installed)
        if code != 0 or not retired:
            raise ValueError("gui_install_failed")
        app = self.installed / "mesh-chat.exe"
        if not installer.installed_artifacts_match(installer.installed_artifacts(self.installed, self.candidate)):
            raise ValueError("gui_installed_bytes_invalid")
        report_path = ROOT / "dist/reports/packaged-call-capture-preflight.json"
        args = argparse.Namespace(run_id=self.run_id, run_attempt=self.run_attempt,
                                  node=self.node, preflight_output=report_path)
        result = {}
        passed, sha = installer.run_preflight(app, self.candidate, args, result)
        self.preflight = {"passed": passed, "sha256": sha, "app_retired": result.get("app_retired"),
                          "preflight_child_retired": result.get("preflight_child_retired")}
        if not passed or not result.get("app_retired") or not result.get("preflight_child_retired"):
            raise ValueError("gui_capture_preflight_failed")
        record = json.loads(report_path.read_text(encoding="utf-8"))
        checks = record.get("checks")
        if not isinstance(checks, dict) or set(checks) != {"appMounted", "tauriBridge", "mediaApi",
                "peerApi", "buildCommitMatches", "captured", "stopped"} or not all(checks.values()):
            raise ValueError("gui_capture_checks_failed")
        self.port = media.reserve_port()
        flags = (f"--remote-debugging-port={self.port} --use-fake-device-for-media-stream "
                 "--use-fake-ui-for-media-stream")
        environment = os.environ.copy()
        if media.token_elevated():
            self.policy = media.ScopedBrowserPolicy(flags)
            self.policy.install()
        else:
            environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = flags
        self.app = subprocess.Popen([str(app)], cwd=self.installed, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        self.control = GuiControl(self.node, self.port, self.source, self.deadline)
        self.control.open()
        return self

    def request(self, action, **params):
        if self.control is None: raise ValueError("gui_not_open")
        return self.control.request(action, **params)

    def close(self):
        success = True
        if self.control is not None:
            try: self.cleanup["driver_retired"] = self.control.close()
            except Exception: self.cleanup["driver_retired"] = False
            self.cleanup.update({"driver_" + key: value for key, value in self.control.cleanup.items()})
            success &= self.cleanup["driver_retired"]
        try: self.cleanup["app_retired"] = media.retire(self.app, self.port)
        except Exception: self.cleanup["app_retired"] = False
        success &= self.cleanup["app_retired"]
        if self.policy is not None:
            try: self.cleanup["browser_policy_retired"] = self.policy.remove()
            except Exception: self.cleanup["browser_policy_retired"] = False
            success &= self.cleanup["browser_policy_retired"]
        if self.installed is not None and self.candidate is not None:
            try:
                after = installer.installed_artifacts(self.installed, self.candidate)
                self.cleanup["installed_bytes_unchanged"] = installer.installed_artifacts_match(after)
                self.cleanup["source_unchanged"] = media.source_identity(self.source, self.tree) == (self.source, self.tree)
            except Exception:
                self.cleanup["installed_bytes_unchanged"] = False
                self.cleanup["source_unchanged"] = False
            success &= self.cleanup["installed_bytes_unchanged"] and self.cleanup["source_unchanged"]
        return bool(success)
