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
    if (type(reply) is not dict or set(reply) != {"id", "ok", "result"}
            or reply["id"] != request["id"] or reply["ok"] is not True
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
    reader.start()
    return process, reader, ports, observed, overflow


def run_phases(sock, nonce, deadline):
    auth = exchange(sock, {"id": "auth", "action": "authenticate", "nonce": nonce}, deadline)
    if auth != {"authenticated": True}:
        raise ValueError("authentication_reply")
    step = 0

    def request(operation, params=None, key=None):
        nonlocal step
        step += 1
        payload = {"id": f"phase:{step}", "action": "request", "step": step,
                   "operation": operation, "params": params or {}}
        if key is not None:
            payload["idempotency_key"] = key
        return exchange(sock, payload, deadline)

    capabilities = request("runtime.capabilities")
    handles = capabilities.get("profiles")
    if ("native.command" in capabilities.get("operations", []) or type(handles) is not list
            or len(handles) != 1 or type(handles[0]) is not str or not handles[0]):
        raise ValueError("fresh_public_capabilities")
    snapshot = request("application.snapshot")
    if (snapshot.get("profile") is not None or snapshot.get("contacts") != []
            or snapshot.get("messages") != []):
        raise ValueError("fresh_public_snapshot")
    request("profile.create", {"display_name": "Independent Android"}, "public-session-" + uuid4().hex)
    profiles = request("runtime.capabilities").get("profiles")
    if profiles != handles:
        raise ValueError("owner_handle_changed")
    profile = request("profile.query", {"profile": handles[0]})
    if type(profile.get("destination")) is not str or not profile["destination"]:
        raise ValueError("public_profile_query")
    after = request("application.snapshot")
    if after.get("profile") is None:
        raise ValueError("public_snapshot_after_create")
    step += 1
    finish = exchange(sock, {"id": "finish", "action": "finish", "step": step}, deadline)
    if finish != {"completed": True, "requests": step - 1}:
        raise ValueError("public_session_finish")
    return step - 1


def run(expected_source, serial):
    started = time.monotonic()
    phase = "distribution"
    process = reader = forward = None
    observed = []
    overflow = None
    owned = False
    result = {"v": 1, "passed": False, "scope": SCOPE, "checks": [], "run_id": uuid4().hex}
    try:
        identity, artifacts = verified_distribution(expected_source)
        result.update(identity, artifacts=artifacts)
        phase = "emulator_admission"
        admit_emulator(serial)
        result["emulator_serial"] = serial
        phase = "install"
        for package in (APP, APP + ".test"):
            subprocess.run(["adb", "-s", serial, "uninstall", package], capture_output=True, timeout=30)
        for name in ("consumer.apk", "consumer-test.apk"):
            if not adb(serial, "install", "-r", str(ROOT / "dist/android-independent-consumer" / name), timeout=120).endswith("Success"):
                raise RuntimeError("install_failed")
            owned = True
        if adb(serial, "shell", "pm", "clear", APP) != "Success":
            raise RuntimeError("clear_failed")
        result["checks"].append(CHECKS[0])
        phase = "instrumentation"
        nonce = os.urandom(32).hex()
        deadline = time.monotonic() + SESSION_SECONDS
        process, reader, ports, observed, overflow = instrument(serial, nonce)
        try:
            port = ports.get(timeout=min(90, remaining(deadline)))
        except queue.Empty:
            raise TimeoutError("port_deadline") from None
        if port == "overflow" or overflow.is_set():
            raise ValueError("instrumentation_output_overflow")
        if port == "eof":
            raise RuntimeError("instrumentation_exited_before_session")
        if process.poll() is not None:
            raise RuntimeError("instrumentation_exited_before_session")
        result["checks"].append(CHECKS[1])
        phase = "forward"
        forward = adb(serial, "forward", "tcp:0", f"tcp:{port}")
        if re.fullmatch(r"[0-9]{1,5}", forward) is None or not 1024 <= int(forward) <= 65535:
            raise ValueError("adb_forward")
        phase = "public_phases"
        with socket.create_connection(("127.0.0.1", int(forward)), timeout=min(30, remaining(deadline))) as sock:
            result["requests"] = run_phases(sock, nonce, deadline)
        result["checks"].extend(CHECKS[2:5])
        phase = "shutdown"
        if process.wait(timeout=min(90, remaining(deadline))) != 0:
            raise RuntimeError("instrumentation_failure")
        reader.join(timeout=5)
        if reader.is_alive():
            raise RuntimeError("instrumentation_output_incomplete")
        if overflow.is_set():
            raise ValueError("instrumentation_output_overflow")
        output = b"".join(observed)
        if b"OK (1 test)" not in output or b"FAILURES!!!" in output:
            raise RuntimeError("instrumentation_result")
        if verified_distribution(expected_source) != (identity, artifacts):
            raise RuntimeError("distribution_changed_during_session")
        remaining(deadline)
        result["checks"].append(CHECKS[5])
        result["passed"] = True
    except Exception as error:
        result.update(phase=phase, failure_type=type(error).__name__)
    finally:
        cleanup = True
        actions = []
        if forward is not None:
            actions.append(lambda: adb(serial, "forward", "--remove", f"tcp:{forward}"))
        if process is not None and process.poll() is None:
            actions.append(lambda: process.kill())
            actions.append(lambda: process.wait(timeout=10))
        if reader is not None:
            actions.append(lambda: reader.join(timeout=5))
        if owned:
            actions.extend((lambda: adb(serial, "shell", "am", "force-stop", APP),
                            lambda: adb(serial, "shell", "am", "force-stop", APP + ".test")))
        for action in actions:
            try:
                action()
            except Exception:
                cleanup = False
        if reader is not None and reader.is_alive():
            cleanup = False
        result["cleanup"] = cleanup
        result["duration_seconds"] = time.monotonic() - started
        result["passed"] = result["passed"] and cleanup and result["checks"] == list(CHECKS)
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
