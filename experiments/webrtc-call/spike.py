"""C0b WebRTC audio spike.

This is an isolated experiment, not a shipped Mesh Chat dependency. It proves:

1. two native WebRTC peer connections can connect on host candidates;
2. an Opus audio track flows in both directions;
3. received audio frames are decodable and non-silent.

It uses synthetic audio, not a microphone. C1 replaces the tone with the real
Windows audio device and wires the signaling into the service.
"""

from __future__ import annotations

import argparse
import asyncio
import fractions
import math
import sys
import time
from pathlib import Path

from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import AudioFrame
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service" / "src"))

import RNS  # noqa: E402

from mesh_chat.webrtc_signaling import (  # noqa: E402
    create_call_answer,
    create_call_invite,
    verify_call_answer,
    verify_call_invite,
)


SAMPLE_RATE = 48_000
FRAME_SAMPLES = 960  # 20 ms
AMPLITUDE = 0.25
CALL_ID = "call_c0b_0123456789"


def sdp_fingerprint(sdp: str) -> str:
    for line in sdp.splitlines():
        if line.startswith("a=fingerprint:"):
            return line.removeprefix("a=fingerprint:").strip()
    raise ValueError("WebRTC SDP has no DTLS fingerprint")


def destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


class ToneTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, frequency: float, phase: float = 0.0) -> None:
        super().__init__()
        self.frequency = frequency
        self.phase = phase
        self.started = time.monotonic()
        self.frames = 0

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(FRAME_SAMPLES / SAMPLE_RATE)
        elapsed = time.monotonic() - self.started + self.phase
        t = np.arange(FRAME_SAMPLES, dtype=np.float64) / SAMPLE_RATE + elapsed
        samples = (np.sin(2 * math.pi * self.frequency * t) * AMPLITUDE * 32767).astype("<i2")
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self.frames * FRAME_SAMPLES
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        frame.planes[0].update(samples.tobytes())
        self.frames += 1
        return frame


async def wait_for(predicate, *, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {label}")


async def run(duration: float) -> int:
    left = RTCPeerConnection()
    right = RTCPeerConnection()
    received: dict[str, list[AudioFrame]] = {"right": [], "left": []}
    states: list[str] = []

    for name, pc in (("left", left), ("right", right)):
        pc.on(
            "connectionstatechange",
            lambda pc=pc, name=name: states.append(f"{name}:{pc.connectionState}"),
        )

    right_track = ToneTrack(440.0)
    left_track = ToneTrack(660.0, phase=0.1)
    left.addTrack(right_track)
    right.addTrack(left_track)

    @right.on("track")
    async def on_right_track(track):
        while True:
            try:
                received["right"].append(await track.recv())
            except Exception:
                return

    @left.on("track")
    async def on_left_track(track):
        while True:
            try:
                received["left"].append(await track.recv())
            except Exception:
                return

    offer = await left.createOffer()
    await left.setLocalDescription(offer)
    await right.setRemoteDescription(RTCSessionDescription(sdp=left.localDescription.sdp, type="offer"))
    answer = await right.createAnswer()
    await right.setLocalDescription(answer)
    await left.setRemoteDescription(RTCSessionDescription(sdp=right.localDescription.sdp, type="answer"))

    caller = RNS.Identity()
    callee = RNS.Identity()
    invite_raw = create_call_invite(
        caller,
        call_id=CALL_ID,
        callee_destination=destination(callee),
        media="audio",
        sdp=left.localDescription.sdp,
        dtls_fingerprint=sdp_fingerprint(left.localDescription.sdp),
    )
    invite = verify_call_invite(invite_raw, expected_callee_destination=destination(callee))
    answer_raw = create_call_answer(
        callee,
        invite,
        sdp=right.localDescription.sdp,
        dtls_fingerprint=sdp_fingerprint(right.localDescription.sdp),
    )
    verify_call_answer(answer_raw, invite)
    print(f"signaling=verified call_id={invite.call_id} digest={invite.digest[:12]}")

    await wait_for(
        lambda: left.connectionState == "connected" and right.connectionState == "connected",
        timeout=15,
        label="peer connection",
    )

    deadline = time.monotonic() + duration
    while time.monotonic() < deadline and (
        len(received["right"]) < 10 or len(received["left"]) < 10
    ):
        await asyncio.sleep(0.05)

    left_frames = received["right"]
    right_frames = received["left"]
    left_energy = max((frame.to_ndarray().std() for frame in left_frames), default=0.0)
    right_energy = max((frame.to_ndarray().std() for frame in right_frames), default=0.0)

    print(f"states={states}")
    print(f"left_track_frames={right_track.frames} right_track_frames={left_track.frames}")
    print(f"received_left={len(left_frames)} received_right={len(right_frames)}")
    print(f"left_energy={left_energy:.1f} right_energy={right_energy:.1f}")

    await left.close()
    await right.close()

    if len(left_frames) < 10 or len(right_frames) < 10:
        print("FAIL: not enough audio frames received")
        return 1
    if left_energy < 1.0 or right_energy < 1.0:
        print("FAIL: received audio is silent")
        return 1
    print("PASS: bidirectional WebRTC/Opus audio")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=1.5)
    args = parser.parse_args()
    return asyncio.run(run(args.duration))


if __name__ == "__main__":
    raise SystemExit(main())
