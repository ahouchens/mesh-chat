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

## Limits

- Synthetic 440/660 Hz tones, not a microphone or speaker.
- Host candidates only; no STUN/TURN yet.
- No Reticulum-signed signaling; C0a documents are not wired in yet.
- No UI, call state, permissions, or Android.
- Not part of the service dependency set or CI.

## Next

C1 wires the C0a signaling documents to this media path, replaces the tone
track with the Windows microphone, and adds an isolated 1:1 call UI.
