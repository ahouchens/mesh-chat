"""Windows-only: 100 native data-channel cycles across two packaged sidecars.

This measures transport lifecycle and cleanup. It does not claim durable Reticulum
message or authenticated-receipt delivery, GUI media coexistence or physical
qualification.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_native_windows_messaging import (  # noqa: E402
    CHANNELS,
    ICE,
    Sidecar,
    descendants,
    digest,
)


def wait_open(sidecar: Sidecar, session: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        state = sidecar._request("stats", "native_webrtc_stats",
                                 {"session_id": session})["data_channel_state"]
        if state == "open":
            return
        time.sleep(0.05)
    raise AssertionError(f"channel did not open: {session}")


def run_cycle(left: Sidecar, right: Sidecar, index: int) -> tuple[float, float]:
    left_id, right_id = f"soak-left-{index}", f"soak-right-{index}"
    started = time.monotonic()
    offer = left._request(f"offer-{index}", "native_webrtc_offer", {
        "session_id": left_id, "ice": ICE, "channels": CHANNELS})
    answer = right._request(f"accept-{index}", "native_webrtc_accept", {
        "session_id": right_id, "offer_sdp": offer["sdp"], "ice": ICE,
        "channels": CHANNELS})
    left._request(f"apply-{index}", "native_webrtc_apply_answer", {
        "session_id": left_id, "answer_sdp": answer["sdp"]})
    wait_open(left, left_id, time.monotonic() + 20)
    wait_open(right, right_id, time.monotonic() + 20)
    opened = time.monotonic() - started
    probe = f"soak-probe-{index}"
    accepted = left._request(f"control-{index}", "native_webrtc_control", {
        "session_id": left_id, "label": "mesh-onboarding",
        "text": json.dumps({"probe": probe})})
    assert accepted["accepted"] is True
    right.wait_event(
        "webrtc_control", timeout=30,
        predicate=lambda item: item.get("label") == "mesh-onboarding"
        and json.loads(item.get("data", "{}")).get("probe") == probe)
    controlled = time.monotonic() - started
    left._request(f"close-left-{index}", "native_webrtc_close", {"session_id": left_id})
    right._request(f"close-right-{index}", "native_webrtc_close", {"session_id": right_id})
    return opened, controlled


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--expected-source")
    args = parser.parse_args()
    if os.name != "nt":
        print(json.dumps({"passed": True, "skipped": "requires Windows"}))
        return 0
    candidates = sorted((ROOT / "src-tauri" / "binaries").glob("mesh-chat-service-*.exe"))
    executable = args.sidecar or (candidates[0] if candidates else None)
    if executable is None or not executable.is_file():
        raise SystemExit("packaged sidecar was not built")
    if not 1 <= args.iterations <= 500:
        raise SystemExit("iteration count is out of bounds")
    with tempfile.TemporaryDirectory(prefix="mesh-native-soak-") as directory:
        work = Path(directory)
        left = Sidecar(executable, work / "left", "Soak Left")
        right = Sidecar(executable, work / "right", "Soak Right")
        opened_times, controlled_times, cold_starts = [], [], 0
        try:
            for index in range(args.iterations):
                if index and index % 25 == 0:
                    right.close()
                    right = Sidecar(executable, work / f"right-{index}", f"Soak Right {index}")
                    cold_starts += 1
                opened, controlled = run_cycle(left, right, index)
                opened_times.append(opened)
                controlled_times.append(controlled)
            tree = descendants(left.process.pid) + descendants(right.process.pid)
            assert not any("msedgewebview2" in name for name in tree), tree
            p95 = statistics.quantiles(controlled_times, n=20)[-1]
            print(json.dumps({
                "passed": True,
                "iterations": args.iterations,
                "cold_starts": cold_starts,
                "channel_open_ms_max": round(max(opened_times) * 1000, 1),
                "control_complete_ms_max": round(max(controlled_times) * 1000, 1),
                "control_complete_ms_p95": round(p95 * 1000, 1),
                "sidecar": executable.name,
                "sidecar_sha256": digest(executable),
                "source_commit": args.expected_source,
                "webview_processes": 0,
                "scope": "native transport lifecycle; durable messages and receipts not claimed",
            }, sort_keys=True))
        finally:
            for sidecar in (left, right):
                try:
                    sidecar.close()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
