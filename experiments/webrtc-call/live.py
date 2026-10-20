"""C1 device spike: real microphone through a WebRTC/Opus call.

This is an isolated experiment, not a shipped dependency. It connects two local
peer connections, sends the system microphone through Opus, and measures the
decoded audio. With --play it also writes the decoded audio to the selected
output device (use headphones to avoid feedback).

The production C1 path still needs the service command surface, call UI,
permissions, and Reticulum/LXMF signaling transport.
"""

from __future__ import annotations

import argparse
import asyncio
import fractions
import queue
import sys
import time
from pathlib import Path

from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import AudioFrame
import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service" / "src"))

import RNS  # noqa: E402

from mesh_chat.webrtc_signaling import (  # noqa: E402
    create_call_answer,
    create_call_invite,
    verify_call_answer,
    verify_call_invite,
)

SAMPLE_RATE = 48_000
FRAME_SAMPLES = 960
CALL_ID = "call_c1_0123456789"


def fingerprint(sdp: str) -> str:
    for line in sdp.splitlines():
        if line.startswith("a=fingerprint:"):
            return line.removeprefix("a=fingerprint:").strip()
    raise ValueError("WebRTC SDP has no DTLS fingerprint")


def destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


class MicrophoneTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, device: int | None) -> None:
        super().__init__()
        self.queue: queue.Queue[bytes] = queue.Queue(maxsize=20)
        self.stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=device,
            callback=self._callback,
        )
        self.stream.start()
        self.frames = 0

    def _callback(self, indata, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            return
        try:
            self.queue.put_nowait(bytes(indata))
        except queue.Full:
            pass

    async def recv(self) -> AudioFrame:
        while True:
            try:
                data = self.queue.get_nowait()
                break
            except queue.Empty:
                await asyncio.sleep(0.005)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self.frames * FRAME_SAMPLES
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        frame.planes[0].update(data)
        self.frames += 1
        return frame

    def stop(self) -> None:
        self.stream.stop()
        self.stream.close()


class SpeakerSink:
    def __init__(self, device: int | None) -> None:
        self.queue: queue.Queue[bytes] = queue.Queue(maxsize=20)
        self.stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=device,
            callback=self._callback,
        )
        self.stream.start()

    def _callback(self, outdata, frames, time_info, status) -> None:
        del frames, time_info
        try:
            data = self.queue.get_nowait()
        except queue.Empty:
            data = b"\x00\x00" * FRAME_SAMPLES
        if status:
            data = b"\x00\x00" * FRAME_SAMPLES
        target = len(outdata)
        outdata[:] = data.ljust(target, b"\x00")[:target]

    def write(self, frame: AudioFrame) -> None:
        try:
            self.queue.put_nowait(frame.to_ndarray().astype("<i2").tobytes())
        except queue.Full:
            pass

    def stop(self) -> None:
        self.stream.stop()
        self.stream.close()


async def wait_for(predicate, *, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {label}")


async def run(seconds: float, input_device: int | None, output_device: int | None, play: bool) -> int:
    left = RTCPeerConnection()
    right = RTCPeerConnection()
    microphone = MicrophoneTrack(input_device)
    received: list[AudioFrame] = []
    speaker = SpeakerSink(output_device) if play else None

    left.addTrack(microphone)

    @right.on("track")
    async def on_track(track):
        while True:
            try:
                frame = await track.recv()
                received.append(frame)
                if speaker is not None:
                    speaker.write(frame)
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
    invite = verify_call_invite(
        create_call_invite(
            caller,
            call_id=CALL_ID,
            callee_destination=destination(callee),
            media="audio",
            sdp=left.localDescription.sdp,
            dtls_fingerprint=fingerprint(left.localDescription.sdp),
        )
    )
    verify_call_answer(
        create_call_answer(
            callee,
            invite,
            sdp=right.localDescription.sdp,
            dtls_fingerprint=fingerprint(right.localDescription.sdp),
        ),
        invite,
    )

    await wait_for(
        lambda: left.connectionState == "connected" and right.connectionState == "connected",
        timeout=15,
        label="peer connection",
    )
    await asyncio.sleep(seconds)

    energy = max((frame.to_ndarray().std() for frame in received), default=0.0)
    print(f"microphone_frames={microphone.frames}")
    print(f"received_frames={len(received)}")
    print(f"received_energy={energy:.1f}")
    print(f"output={'enabled' if play else 'disabled'}")

    microphone.stop()
    if speaker is not None:
        speaker.stop()
    await left.close()
    await right.close()

    if len(received) < 10:
        print("FAIL: microphone audio did not cross the WebRTC path")
        return 1
    if energy < 1.0:
        print("FAIL: decoded microphone audio is silent")
        return 1
    print("PASS: microphone captured and decoded over WebRTC/Opus")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--input", type=int, default=None)
    parser.add_argument("--output", type=int, default=None)
    parser.add_argument("--play", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return 0
    return asyncio.run(run(args.seconds, args.input, args.output, args.play))


if __name__ == "__main__":
    raise SystemExit(main())
