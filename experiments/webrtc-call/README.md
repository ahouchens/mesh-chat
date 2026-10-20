# WebRTC audio spike (C0b)

Status: experimental. Not a shipping dependency and not wired into Mesh Chat.

This harness proves the media plane before C1 replaces the tone with a real
microphone:

- two native WebRTC peer connections on host candidates;
- Opus audio in both directions;
- received frames are decodable and non-silent.

## Install

Use a throwaway virtual environment. `av` must be installed before `aiortc`
because `aiortc` pins an older `av` range than the newest wheels:

```sh
python -m venv .venv-webrtc
. .venv-webrtc/bin/activate
python -m pip install -r experiments/webrtc-call/requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv-webrtc
.\.venv-webrtc\Scripts\Activate.ps1
python -m pip install -r experiments\webrtc-call\requirements.txt
```

## Run

```sh
python experiments/webrtc-call/spike.py --duration 2
```

Expected:

```text
states=['right:connecting', 'left:connecting', 'left:connected', 'right:connected']
received_left=11 received_right=11
left_energy=... right_energy=...
PASS: bidirectional WebRTC/Opus audio
```

## Real microphone test

The C1 device spike sends the microphone through the same WebRTC/Opus path:

```sh
python experiments/webrtc-call/live.py --seconds 2 --input 1
```

Use `--list-devices` to find device indexes. Add `--play --output 4` to monitor
through the speakers; use headphones to avoid feedback.

## C5 DataChannel onboarding prototype

```sh
python experiments/webrtc-call/datachannel_onboarding.py
```

This establishes a host-candidate DataChannel, sends a signed personal
invitation, and returns a separately signed reply. It verifies both destinations
but does not bridge the channel into Reticulum/LXMF or expose an onboarding UI.

Expected:

```text
microphone_frames=...
received_frames=...
received_energy=...
PASS: microphone captured and decoded over WebRTC/Opus
```

## Limits

- Synthetic 440/660 Hz tones for the loopback test.
- The live test uses a real microphone but still a local peer only.
- Host candidates only; no STUN/TURN yet.
- No Reticulum/LXMF signaling transport or call UI yet.
- No UI, permissions, Android, or persistence.
- Not part of the service dependency set or CI.

## Next

C1 wires the C0a signaling documents into the service, adds durable call state,
and puts a Windows 1:1 audio call UI over this media path.
