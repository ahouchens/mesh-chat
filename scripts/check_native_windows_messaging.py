"""Windows-only: two packaged service binaries exchange native WebRTC controls.

This is packaged component evidence for the browser-free messaging path. It
does not prove durable Reticulum delivery, GUI coexistence or physical media.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service" / "src"))
from mesh_chat.ipc import encode_frame, read_frame  # noqa: E402

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def descendants(pid: int) -> list[str]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "process snapshot failed")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        children: dict[int, list[tuple[int, str]]] = {}
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                children.setdefault(entry.th32ParentProcessID, []).append(
                    (entry.th32ProcessID, entry.szExeFile))
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        names, pending = [], [pid]
        while pending:
            parent = pending.pop()
            for child, name in children.get(parent, []):
                names.append(name.lower())
                pending.append(child)
        return names
    finally:
        kernel32.CloseHandle(snapshot)


class Sidecar:
    def __init__(self, executable: Path, profile: Path, name: str):
        self.profile = profile
        self.process = subprocess.Popen(
            [str(executable), "--native-webrtc"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.events: list[dict] = []
        self._responses: dict[str, dict] = {}
        self._condition = threading.Condition()
        self._eof = False
        assert self.process.stdin and self.process.stdout and self.process.stderr
        threading.Thread(target=self._read_loop, name="native-sidecar-reader",
                         daemon=True).start()
        self._request("init", "initialize", {
            "profile_dir": str(profile),
            "vault_key": base64.b64encode(os.urandom(32)).decode(),
            "parent_pid": os.getpid(), "display_name": name})

    def _read_loop(self):
        while True:
            try:
                frame = read_frame(self.process.stdout)
            except Exception:
                frame = None
            with self._condition:
                if frame is None:
                    self._eof = True
                    self._condition.notify_all()
                    return
                if frame.get("type") == "event":
                    self.events.append(frame)
                else:
                    self._responses[frame.get("id")] = frame
                self._condition.notify_all()

    def _request(self, identifier, command, payload=None):
        self.process.stdin.write(encode_frame({
            "v": 1, "id": identifier, "command": command, "payload": payload or {}}))
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        with self._condition:
            while identifier not in self._responses:
                if self._eof:
                    error = self.process.stderr.read().decode("utf-8", "replace")[-3000:]
                    raise AssertionError(f"{command} closed the sidecar: {error}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{command} did not reply")
                self._condition.wait(min(0.1, remaining))
            reply = self._responses.pop(identifier)
        if not reply.get("ok"):
            raise AssertionError(f"{command} failed: {reply.get('error')}")
        return reply.get("result")

    def wait_event(self, event, timeout=30.0, predicate=None):
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for item in self.events:
                    if item.get("event") == event and (predicate is None or predicate(item)):
                        return item
                if self._eof:
                    raise AssertionError(f"sidecar closed before {event}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"event {event} was not observed")
                self._condition.wait(min(0.1, remaining))

    def close(self):
        if self.process.poll() is None:
            try:
                self._request("shutdown", "shutdown")
            except Exception:
                pass
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)


ICE = {"iceServers": [], "iceTransportPolicy": "all"}
CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
    {"label": "meshchat-reconnect", "binary": False, "ordered": True},
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--expected-source")
    args = parser.parse_args()
    if os.name != "nt":
        print(json.dumps({"passed": True, "skipped": "requires Windows"}))
        return 0
    candidates = sorted((ROOT / "src-tauri" / "binaries").glob("mesh-chat-service-*.exe"))
    executable = args.sidecar or (candidates[0] if candidates else None)
    if executable is None or not executable.is_file():
        raise SystemExit("packaged sidecar was not built")
    with tempfile.TemporaryDirectory(prefix="mesh-native-messaging-") as directory:
        work = Path(directory)
        left = Sidecar(executable, work / "left", "Left")
        right = Sidecar(executable, work / "right", "Right")
        try:
            offer = left._request("offer", "native_webrtc_offer", {
                "session_id": "native-left", "ice": ICE, "channels": CHANNELS})
            answer = right._request("accept", "native_webrtc_accept", {
                "session_id": "native-right", "offer_sdp": offer["sdp"],
                "ice": ICE, "channels": CHANNELS})
            left._request("apply", "native_webrtc_apply_answer", {
                "session_id": "native-left", "answer_sdp": answer["sdp"]})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                left_state = left._request("stats", "native_webrtc_stats",
                                           {"session_id": "native-left"})["data_channel_state"]
                right_state = right._request("stats", "native_webrtc_stats",
                                             {"session_id": "native-right"})["data_channel_state"]
                if left_state == right_state == "open":
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("native data channel did not open on both sides")
            accepted = left._request("control", "native_webrtc_control", {
                "session_id": "native-left", "label": "mesh-onboarding",
                "text": json.dumps({"probe": "packaged-native"})})
            assert accepted["accepted"] is True
            event = right.wait_event(
                "webrtc_control",
                predicate=lambda item: item.get("label") == "mesh-onboarding"
                and json.loads(item.get("data", "{}")).get("probe") == "packaged-native")
            assert json.loads(event["data"]) == {"probe": "packaged-native"}
            tree = descendants(left.process.pid) + descendants(right.process.pid)
            assert not any("msedgewebview2" in name for name in tree), tree
            print(json.dumps({
                "passed": True, "sidecar": executable.name,
                "sidecar_sha256": digest(executable),
                "source_commit": args.expected_source,
                "transport": "native_webrtc_datachannel",
                "channel": "mesh-reticulum",
                "control_event": event["event"],
                "owned_processes": sorted(set(tree)),
                "webview_processes": 0,
            }, sort_keys=True))
        finally:
            right.close()
            left.close()
            for sidecar in (left, right):
                if sidecar.process.returncode not in (0, None):
                    error = sidecar.stderr()
                    if error:
                        print(error, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
