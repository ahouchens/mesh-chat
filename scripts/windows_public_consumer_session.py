"""One installed Windows application-owned host and public TypeScript SDK session.

The smoke command proves only fresh public profile creation and clean host exit.
Controllers may use WindowsPublicConsumerSession.open/request/finish, then inspect
its owned workspace and explicitly remove it with cleanup_workspace(). No private
Core pipe, native command, pairing orchestrator, or peer acceptance lives here.
"""

import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

import check_independent_core_consumers as bootstrap
from native_windows_evidence import artifact_binding, require_unchanged
from stage_core_sdk import tools
from stage_independent_core_consumers import ROOT, cleanup, digest, install_typescript, outside_directory


REPORT = ROOT / "dist/reports/windows-public-consumer-session.json"
SCOPE = ("Installed Windows ordinary application-owned host and public TypeScript SDK; "
         "fresh profile and positive host exit only; no pairing, peer receipts, Android, impairment or SC21 acceptance")
CHECKS = ("exact_source_installed_sdk", "fresh_public_snapshot", "public_profile_creation",
          "same_session_profile_query", "positive_host_exit", "protected_profile")
PUBLIC_OPERATIONS = frozenset({"runtime.capabilities", "profile.create", "profile.query", "application.snapshot",
    "peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel", "peer.approve", "contact.invitation",
    "settings.query", "settings.update", "call.settings_query", "call.settings_update",
    "connection.snapshot", "connection.start", "connection.stop", "message.enqueue", "message.query",
    "message.list", "message.received", "events.poll", "events.ack"})
MAX_FRAME = 256 * 1024
MAX_STDERR = 8192
SESSION_SECONDS = 840


class PublicCoreError(ValueError):
    def __init__(self, code):
        super().__init__("public_core_error")
        self.code = code


def remaining(deadline, limit=None):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("public_session_deadline")
    return min(seconds, limit) if limit is not None else seconds


def frame(value):
    data = (json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if not 2 <= len(data) <= MAX_FRAME:
        raise ValueError("public_frame_budget")
    return data


def reply(value, request_id):
    if type(value) is not dict or value.get("id") != request_id:
        raise ValueError("public_reply")
    if (set(value) == {"id", "ok", "error"} and value["ok"] is False
            and type(value["error"]) is dict and set(value["error"]) == {"code"}
            and type(value["error"]["code"]) is str
            and re.fullmatch(r"[a-z_]{1,64}", value["error"]["code"])):
        raise PublicCoreError(value["error"]["code"])
    if set(value) != {"id", "ok", "result"} or value["ok"] is not True or type(value["result"]) is not dict:
        raise ValueError("public_reply")
    return value["result"]


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("public_reply")
        value[key] = item
    return value


def verified_inputs(expected_source, bootstrap_report):
    binary, binding = artifact_binding(expected_source)
    if not bootstrap_report.is_file() or not 0 < bootstrap_report.stat().st_size <= 128 * 1024:
        raise ValueError("bootstrap_report")
    report_hash = digest(bootstrap_report)
    prior = bootstrap.verify_report(json.loads(bootstrap_report.read_text(encoding="utf-8")),
                                    binding["source_commit"], binding["source_tree"])
    if any(prior[key] != binding[key] for key in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")):
        raise ValueError("runtime_binding")
    sdk = bootstrap_report.parent / prior["sdk_artifact"]
    if (not sdk.is_file() or not 0 < sdk.stat().st_size <= 2 * 1024 * 1024
            or digest(sdk) != prior["sdk_sha256"]):
        raise ValueError("sdk_binding")
    return binary, binding, sdk, report_hash


class WindowsPublicConsumerSession:
    """Retain exact owned files on failure; only an explicit cleanup removes them."""

    def __init__(self, expected_source, *, bootstrap_report=None, temporary_root=None):
        self.expected_source = expected_source
        self.bootstrap_report = Path(bootstrap_report or ROOT / "dist/reports/windows-independent-bootstrap.json")
        self.temporary_root = Path(temporary_root or os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
        self.phase = "source_artifact_binding"
        self.binary = self.binding = self.sdk = self.report_hash = None
        self.node = self.directory = self.runtime = self.data = self.installed = None
        self.sdk_hash = None
        self.process = self.stdout_reader = self.stderr_reader = None
        self.responses = queue.Queue(maxsize=2)
        self.request_lock = threading.Lock()
        self.output_failure = threading.Event()
        self.stderr_bytes = 0
        self.deadline = None
        self.sequence = 0
        self.faulted = False
        self.retired = False
        self.workspace_cleaned = False
        self.opened = False

    def __enter__(self):
        return self.open()

    def __exit__(self, kind, _error, _traceback):
        try:
            if not self.retired:
                self.finish()
        except Exception:
            if kind is None:
                raise

    def _read_stdout(self):
        try:
            while line := self.process.stdout.readline(MAX_FRAME + 1):
                if self.output_failure.is_set():
                    continue
                if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                    self.output_failure.set()
                    continue
                try: self.responses.put_nowait(line)
                except queue.Full: self.output_failure.set()
        except Exception:
            self.output_failure.set()
        finally:
            self.process.stdout.close()
            try: self.responses.put_nowait(None)
            except queue.Full: pass

    def _read_stderr(self):
        try:
            while data := self.process.stderr.read(MAX_STDERR + 1):
                self.stderr_bytes += len(data)
                if self.stderr_bytes > MAX_STDERR:
                    self.output_failure.set()
        except Exception:
            self.output_failure.set()
        finally:
            self.process.stderr.close()

    def open(self):
        if self.opened:
            raise ValueError("session_already_opened")
        self.opened = True
        self.binary, self.binding, self.sdk, self.report_hash = verified_inputs(
            self.expected_source, self.bootstrap_report)
        self.sdk_hash = digest(self.sdk)
        self.node, npm = tools()
        self.phase = "outside_checkout_installation"
        self.directory = outside_directory(self.temporary_root)
        self.installed = install_typescript(self.directory, self.sdk, self.node, npm)
        self.runtime = self.directory / self.binary.name
        shutil.copy2(self.binary, self.runtime)
        if (digest(self.runtime) != self.binding["sidecar_sha256"] or digest(self.sdk) != self.sdk_hash
                or any(digest(self.directory / name) != value for name, value in self.installed["application_files"].items())):
            raise ValueError("installed_inputs_changed")
        require_unchanged(self.binary, self.binding)
        self.data = self.directory / "app-data"
        self.phase = "public_session_start"
        self.deadline = time.monotonic() + SESSION_SECONDS
        self.process = subprocess.Popen([self.node, "consumer.mjs", "--runtime", str(self.runtime),
            "--data-directory", str(self.data)], cwd=self.directory,
            env=bootstrap.application_environment(os.environ), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.stdout_reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        try:
            self.stdout_reader.start()
            self.stderr_reader.start()
        except Exception:
            self._kill()
            raise
        self.phase = "public_requests"
        return self

    def _kill(self):
        if self.process is not None and self.process.poll() is None:
            try: self.process.kill()
            finally: self.process.wait(timeout=10)

    def _close_stdin(self):
        done = threading.Event()
        errors = []
        def close():
            try: self.process.stdin.close()
            except Exception as error: errors.append(error)
            finally: done.set()
        worker = threading.Thread(target=close, daemon=True)
        worker.start()
        if not done.wait(remaining(self.deadline, 30)):
            raise TimeoutError("public_close_deadline")
        if errors:
            raise RuntimeError("public_close_failed") from None

    def _write(self, data):
        remaining(self.deadline)
        done = threading.Event()
        errors = []
        def write():
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except Exception as error:
                errors.append(error)
            finally: done.set()
        worker = threading.Thread(target=write, daemon=True)
        worker.start()
        if not done.wait(remaining(self.deadline, 30)):
            raise TimeoutError("public_write_deadline")
        worker.join(timeout=1)
        if errors:
            raise RuntimeError("public_write_failed") from None

    def request(self, operation, params=None, key=None):
        if (self.process is None or self.retired or self.faulted or type(operation) is not str
                or operation not in PUBLIC_OPERATIONS or type(params) not in {dict, type(None)}
                or (key is not None and (type(key) is not str
                    or re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", key) is None))):
            raise ValueError("public_request")
        if not self.request_lock.acquire(blocking=False):
            raise ValueError("concurrent_public_request")
        try:
            self.sequence += 1
            request_id = f"win:{self.sequence}"
            command = {"id": request_id, "operation": operation, "params": params if params is not None else {}}
            if key is not None:
                command["idempotency_key"] = key
            self._write(frame(command))
            try: line = self.responses.get(timeout=remaining(self.deadline, 30))
            except queue.Empty: raise TimeoutError("public_reply_deadline") from None
            if (line is None or self.output_failure.is_set() or len(line) > MAX_FRAME
                    or not line.endswith(b"\n")):
                raise ValueError("public_output")
            return reply(json.loads(line.decode("utf-8"), object_pairs_hook=unique_object), request_id)
        except PublicCoreError:
            raise
        except Exception:
            self.faulted = True
            raise
        finally:
            self.request_lock.release()

    def finish(self):
        if self.process is None or self.retired:
            raise ValueError("public_session_closed")
        self.phase = "retirement"
        try:
            if self.faulted:
                raise RuntimeError("public_session_faulted")
            self._close_stdin()
            if self.process.wait(timeout=remaining(self.deadline, 30)) != 0:
                raise RuntimeError("consumer_exit")
            self.stdout_reader.join(timeout=5)
            self.stderr_reader.join(timeout=5)
            pending = []
            while not self.responses.empty():
                pending.append(self.responses.get_nowait())
            if (self.stdout_reader.is_alive() or self.stderr_reader.is_alive()
                    or self.output_failure.is_set() or self.stderr_bytes
                    or any(item is not None for item in pending)):
                raise RuntimeError("consumer_output_incomplete")
            require_unchanged(self.binary, self.binding)
            if (digest(self.runtime) != self.binding["sidecar_sha256"] or digest(self.sdk) != self.sdk_hash
                    or digest(self.bootstrap_report) != self.report_hash
                    or any(digest(self.directory / name) != value for name, value in self.installed["application_files"].items())):
                raise ValueError("installed_inputs_changed")
            remaining(self.deadline)
            self.retired = True
            return True
        except Exception:
            self._kill()
            raise

    def close(self):
        """Close stdin and require the same positive host retirement as finish()."""
        return self.finish()

    def cleanup_workspace(self):
        if not self.retired:
            raise ValueError("retirement_unconfirmed")
        if not self.workspace_cleaned:
            cleanup(self.directory, self.temporary_root)
            self.workspace_cleaned = True


def smoke_profile(peer):
    capabilities = peer.request("runtime.capabilities")
    handles = capabilities.get("profiles")
    if (type(handles) is not list or len(handles) != 1 or type(handles[0]) is not str
            or not handles[0] or "profile.create" not in capabilities.get("operations", [])
            or "native.command" in capabilities.get("operations", [])):
        raise ValueError("public_capabilities")
    empty = peer.request("application.snapshot")
    if empty.get("profile") is not None or empty.get("contacts") != [] or empty.get("messages") != []:
        raise ValueError("fresh_snapshot")
    peer.request("profile.create", {"display_name": "Independent Windows"}, str(uuid4()))
    after = peer.request("runtime.capabilities")
    if after.get("profiles") != handles:
        raise ValueError("owner_handle_changed")
    profile = peer.request("profile.query", {"profile": handles[0]})
    if type(profile.get("destination")) is not str or not profile["destination"]:
        raise ValueError("public_profile_query")
    snapshot = peer.request("application.snapshot")
    if (type(snapshot.get("profile")) is not dict
            or snapshot["profile"].get("display_name") != "Independent Windows"
            or snapshot.get("contacts") != [] or snapshot.get("messages") != []):
        raise ValueError("public_profile_snapshot")
    return handles[0]


def run(expected_source, bootstrap_report=None, temporary_root=None):
    started = time.monotonic()
    peer = WindowsPublicConsumerSession(expected_source, bootstrap_report=bootstrap_report,
                                        temporary_root=temporary_root)
    result = {"v": 1, "passed": False, "scope": SCOPE, "checks": [], "run_id": uuid4().hex}
    try:
        peer.open()
        result["checks"].append(CHECKS[0])
        smoke_profile(peer)
        result["checks"].extend(CHECKS[1:4])
        peer.finish()
        result["checks"].append(CHECKS[4])
        bootstrap.protected_profile(peer.data)
        result["checks"].append(CHECKS[5])
        result.update(peer.binding, sdk_sha256=peer.sdk_hash,
                      bootstrap_report_sha256=peer.report_hash, application=peer.installed,
                      passed=True)
        peer.cleanup_workspace()
    except Exception as error:
        result.update(phase=peer.phase, failure_type=type(error).__name__)
        if peer.process is not None and peer.process.poll() is None and not peer.retired:
            try: peer.finish()
            except Exception: pass
    result["duration_seconds"] = time.monotonic() - started
    result["retired"] = peer.retired
    result["workspace_cleanup"] = peer.workspace_cleaned
    result["passed"] = result["passed"] and peer.retired and peer.workspace_cleaned and result["checks"] == list(CHECKS)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--bootstrap-report", type=Path)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    result = run(args.expected_source, args.bootstrap_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "phase": result.get("phase"), "retired": result["retired"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
