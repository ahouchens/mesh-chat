"""C5 DataChannel onboarding prototype.

This proves the transport and signed-document exchange without changing the
shipping invitation flow:

1. two WebRTC peers connect on host candidates;
2. a DataChannel carries a signed personal invitation;
3. the recipient verifies it and returns a separately signed reply;
4. the initiator verifies the reply.

It is an isolated experiment. The shipping app still onboards through LAN,
TCP access point, or I2P; C5 is not exposed in the UI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from aiortc import RTCDataChannel, RTCPeerConnection, RTCSessionDescription

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service" / "src"))

import RNS  # noqa: E402

from mesh_chat.invitations import create_invitation, verify_invitation  # noqa: E402


async def wait_for(predicate, *, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {label}")


async def run() -> int:
    owner = RNS.Identity()
    joiner = RNS.Identity()
    left = RTCPeerConnection()
    right = RTCPeerConnection()
    messages: list[str] = []
    replies: list[str] = []
    remote_channels: list[RTCDataChannel] = []
    channel_ready = asyncio.Event()
    received = asyncio.Event()
    reply_received = asyncio.Event()

    channel = left.createDataChannel("mesh-onboarding", ordered=True)
    channel.on("open", lambda: channel_ready.set())

    @channel.on("message")
    def on_left_message(message: str) -> None:
        replies.append(message)
        reply_received.set()

    @right.on("datachannel")
    def on_datachannel(remote: RTCDataChannel) -> None:
        remote_channels.append(remote)

        @remote.on("message")
        def on_message(message: str) -> None:
            messages.append(message)
            received.set()

    offer = await left.createOffer()
    await left.setLocalDescription(offer)
    await right.setRemoteDescription(RTCSessionDescription(sdp=left.localDescription.sdp, type="offer"))
    answer = await right.createAnswer()
    await right.setLocalDescription(answer)
    await left.setRemoteDescription(RTCSessionDescription(sdp=right.localDescription.sdp, type="answer"))

    await wait_for(lambda: left.connectionState == "connected" and right.connectionState == "connected", timeout=15, label="peer connection")
    await asyncio.wait_for(channel_ready.wait(), timeout=10)

    invitation = create_invitation(owner, "Owner", lifetime_seconds=600)["text"]
    channel.send(invitation)
    await asyncio.wait_for(received.wait(), timeout=10)
    assert messages and messages[0] == invitation

    verified = verify_invitation(messages[0])
    assert verified is not None
    assert verified.destination_hash.hex() == RNS.Destination.hash(owner, "lxmf", "delivery").hex()

    reply = create_invitation(joiner, "Joiner", lifetime_seconds=600)["text"]
    assert remote_channels
    remote_channels[0].send(reply)
    await asyncio.wait_for(reply_received.wait(), timeout=10)
    reply_verified = verify_invitation(replies[0])
    assert reply_verified is not None
    assert reply_verified.destination_hash.hex() == RNS.Destination.hash(joiner, "lxmf", "delivery").hex()
    # The same channel is bidirectional; both signed documents have now
    # traversed it in opposite directions.
    print("invitation_length", len(invitation))
    print("verified_owner", verified.destination_hash.hex()[:12])
    print("reply_length", len(reply))
    print("PASS: signed invitation and reply traversed the DataChannel")
    await left.close()
    await right.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
