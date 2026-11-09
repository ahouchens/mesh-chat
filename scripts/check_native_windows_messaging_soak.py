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
)
from native_windows_evidence import COUNTS, qualify, write_result


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
    for sidecar, session in ((left, left_id), (right, right_id)):
        try:
            sidecar._request(f"stats-{session}", "native_webrtc_stats", {"session_id": session})
        except AssertionError as error:
            assert ("native_webrtc_session_missing" in str(error)
                    or "native_unavailable" in str(error)), error
        else:
            raise AssertionError(f"closed session is still observable: {session}")
    return opened, controlled


def exercise(executable, iterations=100):
    if type(iterations) is not int or iterations != 100:
        raise ValueError("Required native lifecycle qualification executes exactly 100 cycles")
    scratch = ROOT / ".test-tmp/native-lifecycle"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as directory:
        work = Path(directory)
        left = right = None
        opened_times, controlled_times, cold_starts = [], [], 0
        clean_exits = 0
        try:
            left = Sidecar(executable, work / "left", "Soak Left")
            right = Sidecar(executable, work / "right", "Soak Right")
            for index in range(iterations):
                if index and index % 25 == 0:
                    right.close()
                    if right.process.returncode != 0:
                        raise AssertionError("Cold-start peer did not exit cleanly")
                    clean_exits += 1
                    right = Sidecar(executable, work / f"right-{index}", f"Soak Right {index}")
                    cold_starts += 1
                opened, controlled = run_cycle(left, right, index)
                opened_times.append(opened)
                controlled_times.append(controlled)
            tree = descendants(left.process.pid) + descendants(right.process.pid)
            assert not any("msedgewebview2" in name for name in tree), tree
            p95 = statistics.quantiles(controlled_times, n=20)[-1]
            assert max(opened_times) < 20.0, "native channel open exceeded its budget"
            assert max(controlled_times) < 30.0, "native control round trip exceeded its budget"
        finally:
            errors = []
            for sidecar in (left, right):
                if sidecar is not None:
                    try:
                        sidecar.close()
                        if sidecar.process.returncode != 0:
                            raise AssertionError("Packaged native peer did not exit cleanly")
                        clean_exits += 1
                    except Exception as error:
                        errors.append(error)
            if errors:
                raise errors[0]
    return {"counts": {**COUNTS["lifecycle"], "channel_pairs": len(opened_times),
                       "controls_received": len(controlled_times), "cold_starts": cold_starts,
                       "processes_started": 2 + cold_starts, "clean_exits": clean_exits},
            "timings_ms": {"open_max": max(opened_times) * 1000,
                           "control_max": max(controlled_times) * 1000, "control_p95": p95 * 1000}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/native-windows-lifecycle.json")
    args = parser.parse_args()
    return write_result(args.output, qualify("lifecycle", args.expected_source, args.sidecar,
                                             lambda binary: exercise(binary, args.iterations)))


if __name__ == "__main__":
    raise SystemExit(main())
