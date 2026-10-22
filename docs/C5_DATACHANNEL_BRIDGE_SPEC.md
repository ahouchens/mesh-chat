# C5 DataChannel onboarding bridge specification

Status: C5a–C5d shipped (Python interface + service packet IPC, renderer
DataChannel pump, signed QR/copy offer/answer, and inline personal/workspace
onboarding over a second control DataChannel). C5e physical qualification
remains open. The DataChannel is a supported onboarding and transport path as of
0.9.x, and automatic reconnect reuses the same bridge.

## 1. Goal

Carry Reticulum/LXMF traffic over a WebRTC DataChannel so two users can
bootstrap a contact or workspace when neither has a reachable TCP access point.
The bridge must preserve every existing rule:

- signed invitations and single-use requests;
- explicit consent before relay/WebRTC use;
- identity and destination binding;
- workspace approval and membership semantics;
- no hidden fallback, no contact auto-approval;
- TCP access point remains the default onboarding path.

## 2. Architecture

```text
React / WebView
  RTCPeerConnection + DataChannel "mesh-reticulum"
        │ binary messages, length-bounded
        ▼
Tauri Rust shell
  allowlisted webrtc_packet / event bridge
        │ base64 framed IPC
        ▼
Python service
  WebRTCInterface (RNS.Interface)
        │ raw Reticulum packets
        ▼
Reticulum / LXMF / existing invitation + workspace services
```

The DataChannel carries **Reticulum packets**, not application JSON. The
existing signed documents and membership logic remain authoritative.

## 3. WebRTCInterface contract

- Subclass `RNS.Interfaces.Interface.Interface`.
- `IN = True`, `OUT = True`, `FWD = False`, `RPT = False`.
- Name: `Mesh Chat WebRTC`.
- `HW_MTU = 1064`, `bitrate = 1_000_000`, mode point-to-point.
- `online = True` only while the DataChannel is open.
- `receives = True`.
- `process_incoming(data)`:
  - reject empty/oversized packets;
  - increment `rxb`;
  - call `RNS.Transport.inbound(data, self)`.
- `process_outgoing(data)`:
  - reject when offline/oversized;
  - increment `txb`;
  - hand bytes to the service bridge callback.
- `detach()`:
  - mark offline;
  - remove from `RNS.Transport.interfaces`;
  - release callbacks.
- The interface is added with `RNS.Transport.add_interface(interface)`; it is
  not written into the Reticulum config file.

## 4. IPC contract

Service commands:

```text
webrtc_attach          -> { bridge_id, max_packet }
webrtc_packet          <- { bridge_id, data: base64 }
webrtc_detach          <- { bridge_id }
```

Service event:

```text
{ "type": "event", "event": "webrtc_packet",
  "bridge_id": "...", "data": "base64..." }
```

Rules:

- One bridge per DataChannel session.
- `data` is a single Reticulum packet; no HDLC framing is needed because SCTP
  preserves message boundaries.
- Maximum packet is 1064 bytes; larger messages are rejected.
- Unknown/closed bridge IDs fail closed.
- The renderer never receives a raw socket, path, or identity key.
- A bridge is detached on DataChannel close, call end, app lock, or service
  shutdown.

## 5. Signaling

Use signed `webrtc_offer` and `webrtc_answer` documents over QR or copy/paste:

```json
{
  "v": 1,
  "type": "webrtc_onboarding_offer",
  "session_id": "...",
  "sdp": "...",
  "dtls_fingerprint": "sha-256 ...",
  "ice": { "stun": ["..."], "turn_configured": true },
  "expires_at": 0,
  "signer_public_key": "...",
  "signature": "..."
}
```

- The offer/answer are signed by the inviter/joiner Reticulum identities.
- The SDP fingerprint must match the DTLS certificate.
- Session IDs are single-use and expire within minutes.
- ICE candidates may be embedded after gathering (non-trickle) for QR/copy.
- A pasted answer must match the offer digest and signer.
- No SDP, candidates, TURN credentials, or media keys are written to
  diagnostics.

## 6. Onboarding flow

1. Owner selects **Connect with WebRTC** under Other connection options.
2. Owner creates a DataChannel offer; the app shows a QR and copy text.
3. Joiner scans/pastes the offer, reviews identity/relay disclosure, and
   creates a signed answer.
4. Owner pastes/scans the answer; both apply SDP and ICE.
5. DataChannel opens; each side calls `webrtc_attach` and starts pumping binary
   packets.
6. Reticulum announces/paths over the interface. The existing invitation or
   workspace-join flow runs over that path.
7. Owner approves the contact/workspace request using the existing UI.
8. Messages and receipts use the normal LXMF path; the bridge remains until the
   session ends or the user disconnects.

The DataChannel is not a replacement for approval. It is only a transport.

## 7. TURN and STUN policy

- **Google STUN is the default** for ICE candidate discovery:
  `stun:stun.l.google.com:19302`. The user can replace or clear it.
- **No free Google TURN exists.** Mesh Chat does not ship a default TURN
  endpoint or shared credentials.
- A built-in Cloudflare TURN broker is available but disabled until the user
  enables relay consent. Users can replace or disable it.
- Users can configure their own TURN server. `deploy/relay` provides a
  one-command coturn deployment with TURN over TCP 443, and `deploy/turn` is
  the manual reference. `deploy/cloudflare-turn` provides a Worker that
  exchanges a Cloudflare TURN key for short-lived ICE credentials.
- A public/operator TURN relay sees connection metadata, not decrypted media;
  the UI must disclose that.
- Cellular/CGNAT connections generally require TURN. STUN-only is not a
  guarantee.
- TURN credentials stay in the encrypted service record and are released only
  to an active session.
- Relay-only mode is explicit; no silent downgrade.

## 8. UI states

- `idle`
- `creating-offer`
- `waiting-for-answer`
- `reviewing-offer`
- `creating-answer`
- `connecting`
- `connected — Direct` / `connected — Relayed`
- `onboarding — waiting for approval`
- `ended` / `failed`

No microphone or camera is requested for DataChannel onboarding. Those belong
only to calls.

## 9. Security

- DataChannel/DTLS is not identity; the signed offer/answer binds the Reticulum
  identity.
- Consent is required before using WebRTC, STUN, TURN, or a relay.
- No auto-approval of contacts/workspace requests.
- A failed bridge never changes contact approval or membership.
- One bridge/session, bounded packet size, bounded queue, and rate limits.
- QR/copy documents expire; replays fail.
- No default TURN credential or public relay.

## 10. Increments

### C5a — Python interface and IPC

Implemented in 0.2.89:

- `WebRTCInterface` (`service/src/mesh_chat/webrtc_interface.py`);
- `webrtc_attach`, `webrtc_packet`, `webrtc_detach` service commands;
- `webrtc_packet` service events with base64 packet bytes;
- bounded 1064-byte packets and detach-on-close behavior;
- interface tests.

- `WebRTCInterface` + service attach/packet/detach commands.
- Base64 packet events.
- Unit tests for size/state/close behavior.
- No UI yet.

### C5b — Renderer DataChannel pump

Implemented in 0.2.90:

- `src/webrtc-onboarding.ts` attaches one open DataChannel to the service;
- binary messages are base64-coded into `webrtc_packet` and decoded from
  `webrtc_packet` events;
- 1064-byte MTU enforcement and detach on channel close/error;
- service event listener cleanup;
- Vitest coverage for base64 round-trip, inbound/outbound packets, MTU, and
  detach.

- DataChannel creation, binary type, packet encode/decode.
- Tauri event listener, attach/detach lifecycle.
- Loopback test harness.

### C5c — Signed offer/answer QR/copy

Implemented in 0.2.91:

- signed `webrtc_onboarding_offer` / `webrtc_onboarding_answer` documents;
- identity binding, session binding, offer digest, expiry, and SDP validation;
- service create/verify commands;
- a **WebRTC** sidebar dialog with Create/Join, QR, copy, paste, Direct/Relayed
  ICE settings, and a persistent connected-session banner;
- the bridge survives closing the dialog; Disconnect closes it explicitly.

- `webrtc_onboarding_offer` / `webrtc_onboarding_answer` documents.
- QR and copy/paste UI; expiry/replay checks.
- ICE configuration from call settings.

### C5d — Onboarding admission

Implemented in 0.4.0:

- a second reliable `mesh-onboarding` DataChannel;
- the offerer creates and sends a signed personal invitation over it;
- optional workspace invitation is created and sent in the same exchange;
- the joiner previews identity/fingerprint and accepts inline;
- owner approval still runs through the existing signed request flow;
- no QR/copy/paste for the contact/workspace invitation after the WebRTC
  connection is established.

Still open: signalling the joiner when owner approval completes, automatic
invitation transfer after a reconnect, and physical qualification.

### C5e — Physical qualification

- Windows↔Android cellular with TURN.
- Direct/LAN with STUN only.
- Relay disclosure, permissions, and forensic checks.

## 11. Acceptance criteria

1. A signed offer/answer establishes a DataChannel between two devices.
2. `webrtc_attach` creates exactly one Reticulum interface; detach removes it.
3. A Reticulum/LXMF packet traverses the DataChannel in both directions.
4. A normal personal invitation and a workspace join can complete over the
   bridge.
5. Owner approval is still required.
6. Direct and relayed paths are visible.
7. No default TURN credential or hidden relay is used.
8. Closing/failing the bridge leaves contact/workspace state unchanged.
9. The UI works on Windows and Android; Android requires no call media
   permission for onboarding.
10. A physical Windows↔Android cellular test passes with TURN and documents
    the relay path.

## 12. Out of scope

- A Mesh Chat-operated public TURN service.
- Anonymous onboarding.
- Auto-approval.
- Replacing Reticulum/LXMF.
- A browser-only client.
