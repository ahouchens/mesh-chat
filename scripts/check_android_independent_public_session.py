"""Exercise one installed ordinary Android host through its public SDK session."""

import argparse
import json
import os
from pathlib import Path
import queue
import re
import socket
import struct
import subprocess
import threading
import time
from uuid import uuid4

from android_qualification import source
from verify_android_independent_consumer import (ARTIFACTS, ROOT, digest,
    verify_record, verify_source_inputs)


APP = "com.meshchat.core.independent"
TEST = "com.meshchat.runtime.IndependentPublicSessionTest#publicSessionAcrossMultiplePhases"
RUNNER = APP + ".test/androidx.test.runner.AndroidJUnitRunner"
REPORT = ROOT / "dist/reports/android-independent-public-session.json"
SCOPE = ("Installed ordinary app main process, one Binder CoreClient and multiple public SDK phases; "
         "fresh profile and explicit shutdown only; no peer, message receipt, media or physical acceptance")
CHECKS = ("installed_distribution", "long_lived_instrumentation", "fresh_public_snapshot",
          "public_profile_creation", "same_session_profile_query", "public_shutdown")
PORT = re.compile(rb"INSTRUMENTATION_STATUS: mesh_public_port=([0-9]{1,5})\r?\n")
SERIAL = re.compile(r"emulator-[0-9]{4,6}")
SESSION_SECONDS = 840
PUBLIC_OPERATIONS = frozenset({"runtime.capabilities", "application.snapshot", "profile.create", "profile.query",
    "settings.query", "settings.update", "call.settings_query", "call.settings_update",
    "peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel", "contact.invitation", "peer.approve",
    "connection.snapshot", "connection.start", "message.enqueue", "message.query", "message.received"})


class PublicCoreError(ValueError):
    def __init__(self, code):
        super().__init__("public_core_error")
        self.code = code


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("session_deadline")
    return seconds


def encode_frame(value):
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not 2 <= len(data) <= 65536:
        raise ValueError("frame_budget")
    return struct.pack(">I", len(data)) + data


def read_exact(sock, size, deadline=None):
    chunks = bytearray()
    while len(chunks) < size:
        if deadline is not None:
            sock.settimeout(remaining(deadline))
        part = sock.recv(size - len(chunks))
        if not part:
            raise EOFError("public_session_closed")
        chunks.extend(part)
    return bytes(chunks)


def read_frame(sock, deadline=None):
    size = struct.unpack(">I", read_exact(sock, 4, deadline))[0]
    if not 2 <= size <= 65536:
        raise ValueError("frame_budget")
    return json.loads(read_exact(sock, size, deadline).decode("utf-8"))


def exchange(sock, request, deadline=None):
    if deadline is not None:
        sock.settimeout(remaining(deadline))
    sock.sendall(encode_frame(request))
    reply = read_frame(sock, deadline)
    if type(reply) is not dict or reply.get("id") != request["id"]:
        raise ValueError("public_session_reply")
    if (set(reply) == {"id", "ok", "error"} and reply["ok"] is False
            and type(reply["error"]) is dict and set(reply["error"]) == {"code"}
            and type(reply["error"]["code"]) is str
            and re.fullmatch(r"[a-z_]{1,64}", reply["error"]["code"])):
        raise PublicCoreError(reply["error"]["code"])
    if (set(reply) != {"id", "ok", "result"} or reply["ok"] is not True
            or type(reply["result"]) is not dict):
        raise ValueError("public_session_reply")
    return reply["result"]


def status_port(line):
    match = PORT.fullmatch(line)
    if match is None:
        return None
    port = int(match[1])
    if not 1024 <= port <= 65535:
        raise ValueError("public_session_port")
    return port


def adb(serial, *args, timeout=30):
    return subprocess.check_output(["adb", "-s", serial, *args], text=True, timeout=timeout,
                                   stderr=subprocess.DEVNULL).strip()


def verified_distribution(expected_source):
    if re.fullmatch(r"[a-f0-9]{40}", expected_source) is None:
        raise ValueError("expected_source")
    identity = source()
    if identity["source_commit"] != expected_source:
        raise ValueError("source_commit")
    artifact_hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path)
                       for path in ARTIFACTS}
    record = json.loads((ROOT / "dist/reports/android-independent-distribution.json").read_text(encoding="utf-8"))
    verify_record(record, identity, artifact_hashes)
    verify_source_inputs(record)
    return identity, artifact_hashes


def admit_emulator(serial):
    if SERIAL.fullmatch(serial) is None:
        raise ValueError("emulator_serial")
    if adb(serial, "get-state") != "device" or adb(serial, "shell", "getprop", "ro.kernel.qemu") != "1":
        raise ValueError("emulator_admission")


def instrument(serial, nonce):
    process = subprocess.Popen(["adb", "-s", serial, "shell", "am", "instrument", "-w", "-r",
        "-e", "class", TEST, "-e", "mesh_public_nonce", nonce, RUNNER],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    observed = []
    ports = queue.Queue(maxsize=1)
    overflow = threading.Event()

    def read_output():
        captured = 0
        try:
            while line := process.stdout.readline(8193):
                if overflow.is_set():
                    continue
                if len(line) > 8192 or captured + len(line) > 256000:
                    overflow.set()
                    if ports.empty():
                        ports.put_nowait("overflow")
                    continue
                captured += len(line)
                observed.append(line)
                try:
                    port = status_port(line)
                    if port is not None and ports.empty():
                        ports.put_nowait(port)
                except ValueError:
                    overflow.set()
                    if ports.empty():
                        ports.put_nowait("overflow")
        except Exception:
            overflow.set()
            if ports.empty():
                ports.put_nowait("overflow")
        finally:
            process.stdout.close()
            if ports.empty():
                ports.put_nowait("eof")

    reader = threading.Thread(target=read_output, daemon=True)
    try:
        reader.start()
    except Exception:
        process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        raise
    return process, reader, ports, observed, overflow


class PublicProtocol:
    """One authenticated, numbered public SDK command stream over an existing socket."""

    def __init__(self, sock, nonce, deadline):
        self.sock, self.deadline = sock, deadline
        self.step = 0
        self.created = False
        self.finished = False
        self.failed = False
        auth = exchange(sock, {"id": "auth", "action": "authenticate", "nonce": nonce}, deadline)
        if auth != {"authenticated": True}:
            raise ValueError("authentication_reply")

    def request(self, operation, params=None, key=None):
        if (self.finished or self.failed or type(operation) is not str or operation not in PUBLIC_OPERATIONS
                or type(params) not in {dict, type(None)}
                or self.step >= 127 or (key is not None and
                (type(key) is not str or re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", key) is None))):
            raise ValueError("public_request")
        self.step += 1
        payload = {"id": f"phase:{self.step}", "action": "request", "step": self.step,
                   "operation": operation, "params": params if params is not None else {}}
        if key is not None:
            payload["idempotency_key"] = key
        try:
            result = exchange(self.sock, payload, self.deadline)
        except PublicCoreError:
            raise
        except Exception:
            self.failed = True
            raise
        if operation == "profile.create":
            self.created = True
        return result

    def finish(self):
        if self.finished or self.failed or not self.created or self.step < 4 or self.step >= 128:
            raise ValueError("public_finish")
        try:
            result = exchange(self.sock, {"id": "finish", "action": "finish", "step": self.step + 1}, self.deadline)
        except Exception:
            self.failed = True
            raise
        if result != {"completed": True, "requests": self.step}:
            self.failed = True
            raise ValueError("public_session_finish")
        self.finished = True
        return self.step


def smoke_phases(peer):
    capabilities = peer.request("runtime.capabilities")
    handles = capabilities.get("profiles")
    if ("native.command" in capabilities.get("operations", []) or type(handles) is not list
            or len(handles) != 1 or type(handles[0]) is not str or not handles[0]):
        raise ValueError("fresh_public_capabilities")
    snapshot = peer.request("application.snapshot")
    if (snapshot.get("profile") is not None or snapshot.get("contacts") != []
            or snapshot.get("messages") != []):
        raise ValueError("fresh_public_snapshot")
    peer.request("profile.create", {"display_name": "Independent Android"}, "public-session-" + uuid4().hex)
    profiles = peer.request("runtime.capabilities").get("profiles")
    if profiles != handles:
        raise ValueError("owner_handle_changed")
    profile = peer.request("profile.query", {"profile": handles[0]})
    if type(profile.get("destination")) is not str or not profile["destination"]:
        raise ValueError("public_profile_query")
    after = peer.request("application.snapshot")
    if after.get("profile") is None:
        raise ValueError("public_snapshot_after_create")
    return peer.finish()


def run_phases(sock, nonce, deadline):
    """Exercise the original standalone smoke against an already connected test socket."""
    return smoke_phases(PublicProtocol(sock, nonce, deadline))


class AndroidPublicSession:
    """Own one admitted emulator installation and one public SDK instrumentation lifetime."""

    def __init__(self, expected_source, serial):
        self.expected_source, self.serial = expected_source, serial
        self.phase = "distribution"
        self.identity = self.artifacts = None
        self.opened = self.admitted = False
        self.checks = []
        self.owned = False
        self.process = self.reader = self.forward = self.sock = self.protocol = None
        self.observed = []
        self.overflow = None
        self.deadline = None
        self.confirmed_shutdown = False
        self.cleanup = None

    def __enter__(self):
        return self.open()

    def __exit__(self, _kind, _error, _traceback):
        if not self.close() and _kind is None:
            raise RuntimeError("public_session_cleanup_failed")

    def open(self):
        if self.opened or self.cleanup is not None:
            raise ValueError("session_already_opened")
        self.opened = True
        try:
            self.identity, self.artifacts = verified_distribution(self.expected_source)
            self.phase = "emulator_admission"
            admit_emulator(self.serial)
            self.admitted = True
            self.phase = "install"
            for package in (APP, APP + ".test"):
                subprocess.run(["adb", "-s", self.serial, "uninstall", package], capture_output=True, timeout=30)
            for name in ("consumer.apk", "consumer-test.apk"):
                if not adb(self.serial, "install", "-r", str(ROOT / "dist/android-independent-consumer" / name), timeout=120).endswith("Success"):
                    raise RuntimeError("install_failed")
                self.owned = True
            if adb(self.serial, "shell", "pm", "clear", APP) != "Success":
                raise RuntimeError("clear_failed")
            self.checks.append(CHECKS[0])
            self.phase = "instrumentation"
            nonce = os.urandom(32).hex()
            self.deadline = time.monotonic() + SESSION_SECONDS
            self.process, self.reader, ports, self.observed, self.overflow = instrument(self.serial, nonce)
            try:
                port = ports.get(timeout=min(90, remaining(self.deadline)))
            except queue.Empty:
                raise TimeoutError("port_deadline") from None
            if port == "overflow" or self.overflow.is_set():
                raise ValueError("instrumentation_output_overflow")
            if port == "eof" or self.process.poll() is not None:
                raise RuntimeError("instrumentation_exited_before_session")
            self.checks.append(CHECKS[1])
            self.phase = "forward"
            self.forward = adb(self.serial, "forward", "tcp:0", f"tcp:{port}")
            if re.fullmatch(r"[0-9]{1,5}", self.forward) is None or not 1024 <= int(self.forward) <= 65535:
                raise ValueError("adb_forward")
            self.phase = "public_phases"
            self.sock = socket.create_connection(("127.0.0.1", int(self.forward)),
                                                 timeout=min(30, remaining(self.deadline)))
            self.protocol = PublicProtocol(self.sock, nonce, self.deadline)
            return self
        except Exception:
            self.close()
            raise

    def request(self, operation, params=None, key=None):
        if self.protocol is None or self.confirmed_shutdown or self.cleanup is not None:
            raise ValueError("public_session_closed")
        return self.protocol.request(operation, params, key)

    def finish(self):
        if self.protocol is None or self.confirmed_shutdown or self.cleanup is not None:
            raise ValueError("public_session_closed")
        requests = self.protocol.finish()
        self.phase = "shutdown"
        self.sock.close()
        self.sock = None
        if self.process.wait(timeout=min(90, remaining(self.deadline))) != 0:
            raise RuntimeError("instrumentation_failure")
        self.reader.join(timeout=5)
        if self.reader.is_alive():
            raise RuntimeError("instrumentation_output_incomplete")
        if self.overflow.is_set():
            raise ValueError("instrumentation_output_overflow")
        output = b"".join(self.observed)
        if b"OK (1 test)" not in output or b"FAILURES!!!" in output:
            raise RuntimeError("instrumentation_result")
        if verified_distribution(self.expected_source) != (self.identity, self.artifacts):
            raise RuntimeError("distribution_changed_during_session")
        remaining(self.deadline)
        self.confirmed_shutdown = True
        return requests

    def close(self):
        if self.cleanup is not None:
            return self.cleanup
        cleanup = True
        if self.sock is not None:
            try: self.sock.close()
            except Exception: cleanup = False
            self.sock = None
        actions = []
        if self.forward is not None:
            actions.append(lambda: adb(self.serial, "forward", "--remove", f"tcp:{self.forward}"))
        if self.process is not None:
            try: running = self.process.poll() is None
            except Exception:
                cleanup = False
                running = True
            if running:
                actions.append(lambda: self.process.kill())
                actions.append(lambda: self.process.wait(timeout=10))
        if self.reader is not None:
            actions.append(lambda: self.reader.join(timeout=5))
        if self.owned:
            actions.extend((lambda: adb(self.serial, "shell", "am", "force-stop", APP),
                            lambda: adb(self.serial, "shell", "am", "force-stop", APP + ".test")))
        for action in actions:
            try: action()
            except Exception: cleanup = False
        if self.reader is not None and self.reader.is_alive():
            cleanup = False
        self.cleanup = cleanup
        return cleanup


def run(expected_source, serial):
    started = time.monotonic()
    peer = AndroidPublicSession(expected_source, serial)
    result = {"v": 1, "passed": False, "scope": SCOPE, "checks": [], "run_id": uuid4().hex}
    try:
        peer.open()
        result.update(peer.identity, artifacts=peer.artifacts, emulator_serial=serial)
        result["requests"] = smoke_phases(peer)
        peer.checks.extend(CHECKS[2:])
        result["passed"] = peer.confirmed_shutdown
    except Exception as error:
        if peer.identity is not None:
            result.update(peer.identity, artifacts=peer.artifacts)
        if peer.admitted:
            result["emulator_serial"] = serial
        result.update(phase=peer.phase, failure_type=type(error).__name__)
    finally:
        result["checks"] = list(peer.checks)
        result["cleanup"] = peer.close()
        result["duration_seconds"] = time.monotonic() - started
        result["passed"] = result["passed"] and result["cleanup"] and result["checks"] == list(CHECKS)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--disposable-emulator-serial", required=True)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    result = run(args.expected_source, args.disposable_emulator_serial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "phase": result.get("phase"), "cleanup": result["cleanup"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
