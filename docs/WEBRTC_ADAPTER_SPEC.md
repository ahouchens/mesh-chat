# WebRTC adapter specification and roadmap

Status: design proposal. No WebRTC implementation exists in Mesh Chat. This
document defines how a WebRTC adapter could carry a first connection and,
later, 1:1 calls without changing the existing Reticulum/LXMF or workspace
protocols.

## 1. Summary

Add an optional **WebRTC adapter** for two purposes:

1. **Connection bootstrap:** carry Reticulum/LXMF traffic over a WebRTC
   DataChannel so a user can join a 1:1 conversation or workspace when direct
   QUIC and TCP access points are unavailable or unsuitable.
2. **Calls:** reuse the same authenticated peer relationship for 1:1 audio and
   video calls, then consider workspace calls.

WebRTC is not a server-free transport. A practical deployment needs:

- a signaling exchange for SDP and ICE candidates;
- STUN for server-reflexive candidates;
- TURN when direct ICE fails, especially on symmetric NAT or CGNAT.

The adapter must therefore be explicit, consented, non-default, and honest
about relay metadata. It does not replace the existing direct, TCP access
point, I2P, or Reticulum fallback paths.

## 2. Definitions

- **WebRTC adapter** — a native component that creates a peer connection,
  exchanges signed session descriptions, carries a DataChannel and/or media
  tracks, and exposes the result to the service.
- **DataChannel transport** — an ordered, reliable SCTP channel used to carry
  framed Reticulum packets.
- **Signaling document** — a signed `webrtc_offer`, `webrtc_answer`, or
  `webrtc_candidate` document bound to a contact/workspace and session.
- **ICE** — Interactive Connectivity Establishment: host, server-reflexive,
  peer-reflexive, and relayed candidates.
- **STUN** — an observer that reports a peer’s public UDP tuple.
- **TURN** — a relay used when direct ICE cannot establish a path.
- **Call session** — an authenticated audio/video session with explicit
  ringing, accept, decline, and hangup states.
- **Mesh peer connection** — a WebRTC peer connection carrying the
  DataChannel, media, or both.

## 3. Why WebRTC

WebRTC provides capabilities Mesh Chat does not currently have:

- mature ICE candidate gathering and connectivity checks;
- DTLS/SRTP media;
- Opus audio and VP8/VP9/H.264 video;
- browser-class NAT traversal behavior;
- a path to browser-based onboarding later.

It also provides a DataChannel that can carry framed application packets.

The trade-off is substantial: signaling, STUN/TURN, native media stacks,
permissions, codecs, battery, and a second traversal path alongside the
existing QUIC Offer/Answer/Ready work.

## 4. Goals

1. Two consented users can establish a WebRTC DataChannel and carry a signed
   workspace join, approval, receipt, and messages.
2. The connection is authenticated by the existing Reticulum identities; a
   WebRTC DTLS fingerprint alone is not identity.
3. Direct ICE is preferred; TURN is an explicit fallback with bounded
   credentials and quotas.
4. A 1:1 audio call can be placed from an approved contact without joining a
   third-party calling service.
5. A 1:1 video call can be added after audio is stable.
6. The UI states whether the path is direct, STUN-assisted, or TURN-relayed.
7. No silent camera/microphone access, no auto-answer, no recording.
8. The adapter is off by default and does not alter existing invitation,
   membership, or delivery semantics.

## 5. Non-goals

- A server-free WebRTC deployment.
- Anonymous calls or anonymity for relay metadata.
- PSTN, SIP, or phone-number calling.
- Group calls or an SFU in the first call increment.
- Recording, transcription, or cloud media storage.
- Replacing Reticulum/LXMF as the message and membership protocol.
- Making WebRTC the default invitation path.
- Browser client support in the first increments.

## 6. Architecture

### 6.1 Component placement

```text
React renderer
  └─ call/connection UI only; no SDP, ICE, sockets, or media keys
Tauri Rust shell / Android plugin
  └─ native WebRTC peer connection, media devices, permissions
Python service
  └─ identity, signed signaling documents, policy, consent, delivery state
Reticulum / LXMF
  └─ signaling transport and message/membership protocol
```

The renderer must not own a peer connection, camera, microphone, TURN
credential, or SDP. The service owns identity binding and policy; the native
host owns media and the WebRTC stack.

### 6.2 Connection path

```text
Signed invitation / contact
        ↓
webrtc_offer  (SDP + DTLS fingerprint + ICE policy)
        ↓  via existing Reticulum path, QR, or file
webrtc_answer (SDP + fingerprint)
        ↓
ICE: host → server-reflexive (STUN) → relay (TURN)
        ↓
DataChannel "meshchat-data"
        ↓
framed Reticulum packets
        ↓
LXMF / workspace join / messages
```

The DataChannel is a byte transport. The adapter frames Reticulum packets with
a bounded length prefix and MTU, and exposes a custom Reticulum interface. The
existing identity, destination, ratchet, invitation, approval, and receipt
logic remains authoritative.

### 6.3 Signaling

Signaling documents are signed with the same Reticulum identity as the
invitation/contact:

```json
{
  "v": 1,
  "type": "webrtc_offer",
  "session_id": "opaque",
  "purpose": "personal" | "workspace",
  "workspace_id": "optional",
  "sdp": "...",
  "dtls_fingerprint": "sha-256 ...",
  "ice_policy": "all" | "relay",
  "stun": ["..."],
  "turn": ["..."],
  "created_at": 0,
  "expires_at": 0,
  "signer_public_key": "...",
  "signature": "..."
}
```

Rules:

- The signer must match the invitation owner/contact/workspace authority.
- The SDP fingerprint must match the DTLS certificate in the SDP.
- Session IDs are single-use and expire quickly (minutes, not days).
- Replayed or expired offers/answers are rejected.
- ICE candidates may be included in the SDP (non-trickle) for store-and-forward
  signaling, or sent as separately signed candidate documents when a live
  signaling path exists.
- The service never logs SDP, candidates, TURN credentials, or media keys.

### 6.4 ICE, STUN, and TURN

- Prefer **host** candidates on the same LAN.
- Gather **server-reflexive** candidates only through explicitly configured
  STUN servers.
- Prefer direct pairs; use TURN only when direct checks fail or the user
  chooses relay-only.
- TURN credentials are short-lived, scoped to one session, and issued by the
  selected TURN operator.
- The UI shows `Direct`, `STUN-assisted`, or `Relayed via TURN`.
- A TURN relay sees encrypted DTLS/SRTP and connection metadata, not media
  plaintext, but it can observe timing and volume.
- No Mesh Chat-operated STUN/TURN service is part of this design. A self-hosted
  or explicitly approved operator is required.
- A strict server-free deployment can use host candidates only; that works
  only on a shared LAN or when one side has a reachable public address.

### 6.5 DataChannel transport

- Label: `meshchat-data`.
- Ordered, reliable SCTP stream.
- Bounded framing: length prefix, maximum packet size negotiated from the
  DataChannel `maxMessageSize` and Reticulum MTU.
- Backpressure: pause Reticulum ingress when `bufferedAmount` exceeds a
  threshold; drop only according to Reticulum’s own policy.
- Keepalive: WebRTC consent freshness plus an application ping for idle
  connections.
- Reconnect: renegotiate a new peer connection; do not reuse expired ICE
  credentials.
- Close the peer connection on invitation expiry, contact block, workspace
  removal, or explicit disconnect.

### 6.6 Calls

Calls use a separate authenticated media session:

```text
call_invite → call_ringing → call_accept → media
                         └→ call_decline / call_busy / call_timeout
call_hangup
```

- Audio: Opus, mono/stereo negotiated, 20 ms frames.
- Video: VP8 first; VP9/H.264 only after device/codec validation.
- 1:1 only in the first call increments.
- No auto-answer; the callee must explicitly accept.
- Microphone/camera permissions are requested at call time, not at install.
- Mute, camera-off, speaker/earpiece, and hangup are always available.
- Android must use audio focus, a foreground service where required, and
  release media resources on background/termination.
- No recording, transcription, or local media persistence.
- Call signaling is signed and bound to the existing contact/workspace
  relationship; a DTLS fingerprint is not a substitute for identity.

### 6.7 Relationship to QUIC and Reticulum

- WebRTC and the existing QUIC underlay are both UDP traversal paths. Do not
  run both for the same session by default.
- If a direct QUIC path is already established, prefer it for data; WebRTC is
  for cases where ICE/media is the better fit or a call is starting.
- If WebRTC data is established, it can carry LXMF; the service must still
  apply recipient-ratchet and receipt semantics.
- A call may use the WebRTC peer connection while messages continue over
  Reticulum/LXMF or the DataChannel, but the user must see which path is used.
- No silent downgrade from direct to TURN; relay-only mode is explicit.

## 7. UX

### 7.1 Settings

- **WebRTC connections** (off by default).
- **STUN servers** (user-supplied; no default public list).
- **TURN server and credentials** (sealed; session-scoped).
- **Prefer relay** (off by default).
- **Test WebRTC** with a bounded result: host/STUN/TURN, no addresses in
  diagnostics.
- **Calls** (off until the call increment): microphone/camera test, output
  device, echo cancellation.

### 7.2 Invitation and join

- Add **WebRTC** under **Other connection options**, not as the default.
- The invitation carries a signed WebRTC descriptor:
  - session id, expiry, STUN/TURN policy, relay consent.
- The joiner sees:
  - “This invitation will use WebRTC.”
  - whether STUN/TURN is configured;
  - “Direct if possible; TURN relay if needed.”
  - an explicit consent checkbox.
- The joiner is not asked to paste SDP manually if the signed invitation can
  carry it; an out-of-band file/QR path remains for first contact.

### 7.3 Calls

- A call button appears only for approved contacts (and later admitted
  workspace members).
- States: dialing, ringing, connecting, in-call, reconnecting, ended, failed.
- Show audio/video device selection, mute, camera, speaker, hangup.
- Show path: direct / STUN / TURN.
- A failed call never changes contact approval or workspace membership.

## 8. Security and privacy

1. **Identity binding.** The SDP/DTLS fingerprint is signed by the Reticulum
   identity and bound to the contact/workspace. A valid DTLS certificate alone
   is not identity.
2. **Explicit consent.** WebRTC, STUN, TURN, microphone, and camera each require
   consent. No auto-answer.
3. **No recording.** No local or remote recording, transcription, or media
   upload.
4. **Relay disclosure.** TURN can see connection metadata and traffic volume,
   not decrypted media. The UI says so.
5. **Credential scope.** TURN credentials are short-lived and limited to one
   session; never written to diagnostics.
6. **Abuse controls.** Per-contact rate limits, call timeouts, maximum session
   duration, and TURN quotas.
7. **SDP hardening.** Bounded SDP size, strict parser, codec/ICE allowlists,
   no arbitrary URLs, no unsupported extensions.
8. **No silent fallback.** Direct → STUN → TURN is visible; relay-only is a
   user choice.
9. **Permissions.** Camera/microphone are requested at the moment of use and
   released on hangup/background as platform policy requires.
10. **No anonymity claim.** Peer and TURN operators may see IP/timing metadata.

## 9. Platform plan

### Windows

- Native WebRTC library in Rust or the sidecar.
- Microphone/camera permissions through Windows and the Tauri shell.
- No browser renderer sockets or media keys.
- Audio device selection and echo cancellation.
- Test on Windows 10/11 with a headset and built-in devices.

### Android

- Native WebRTC via the existing plugin boundary.
- `RECORD_AUDIO`, `CAMERA`, and foreground-service permissions as required.
- Audio focus, speaker/earphone routing, Bluetooth, and screen-off behavior.
- Battery/thermal measurement for audio and video.
- Physical-device test required before calls are enabled.

### iOS and browser

- Out of scope for the first roadmap. A browser client would need a WASM
  Reticulum/LXMF stack or a native bridge and is a separate product decision.

## 10. Roadmap

| Increment | Platform | Outcome | Effort | Gate |
|---|---|---|---|---|
| W0 | Desktop | DataChannel spike with self-hosted STUN/TURN; measure ICE, latency, throughput | M | G0 |
| W1 | Desktop | Signed offer/answer/candidate documents; authenticated loopback | M | G1 |
| W2 | Windows | DataChannel as a Reticulum interface; workspace join over WebRTC | L | G2 |
| W3 | Android | DataChannel client with native WebRTC; physical device test | L | G3 |
| W4 | Windows | 1:1 audio call, Opus, mic/speaker, call UI | L | G4 |
| W5 | Android | 1:1 audio call, audio focus/foreground service | L | G4 |
| W6 | Windows/Android | 1:1 video call, codec/device validation | L | G5 |
| W7 | Both | Hardening, TURN quotas, reconnect, diagnostics | M | G6 |
| W8 | Research | Workspace/group call architecture (mesh vs SFU/E2EE) | XL | G7 |

### W0 — DataChannel spike

Goal: prove two peers can establish a DataChannel using a self-hosted
STUN/TURN pair on a test network.

Scope:

- native WebRTC peer connection;
- host/STUN/TURN candidates;
- DataChannel echo and throughput test;
- force TURN to measure relay latency;
- no Mesh Chat UI or invitation integration.

Exit criteria:

- direct DataChannel on LAN;
- STUN-assisted DataChannel across NAT;
- TURN-forced DataChannel when direct fails;
- reconnect after network change;
- measured latency/throughput and CPU.

### W1 — Signed signaling

Goal: replace the spike’s manual signaling with signed documents.

Scope:

- `webrtc_offer`, `webrtc_answer`, `webrtc_candidate`;
- identity binding to contact/invitation;
- single-use session ID, expiry, replay rejection;
- QR/file exchange for first contact;
- existing Reticulum/LXMF path when available.

Exit criteria:

- tampered SDP/fingerprint rejected;
- foreign signer rejected;
- expired/replayed session rejected;
- candidate exchange works both trickle and non-trickle.

### W2 — Windows data-channel adapter

Goal: carry a real workspace join over WebRTC.

Scope:

- custom Reticulum interface over DataChannel;
- framing/MTU/backpressure;
- service-owned consent and diagnostics;
- invitation option and joiner consent;
- STUN/TURN settings;
- fallback to Reticulum/TCP if WebRTC fails.

Exit criteria:

- workspace join, owner approval, receipt, and messages over WebRTC;
- direct/STUN/TURN visible;
- no plaintext or credentials in diagnostics;
- disabling WebRTC removes the interface and leaves other paths intact.

### W3 — Android data-channel adapter

Goal: prove the same path on Android.

Scope:

- native WebRTC plugin;
- permissions and lifecycle;
- physical device join;
- battery/data measurement.

Exit criteria:

- Android joins a workspace over WebRTC;
- background/network transitions documented;
- no bundled browser dependency;
- fallback to TCP/Reticulum.

### W4–W5 — 1:1 audio

Goal: a consented audio call between approved contacts.

Scope:

- call invite/ring/accept/decline/hangup;
- Opus, microphone, speaker/earpiece;
- mute, device selection, audio focus;
- call UI and diagnostics.

Exit criteria:

- clear audio on Windows↔Windows and Windows↔Android;
- no auto-answer;
- call state independent of message delivery;
- permissions requested only at call time;
- no recording.

### W6 — 1:1 video

Goal: optional camera video on the same call path.

Scope:

- VP8 first; VP9/H.264 later;
- camera permissions, preview, camera-off;
- bandwidth adaptation;
- thermal/battery measurement.

Exit criteria:

- stable 1:1 video on both platforms;
- graceful degradation to audio;
- no camera start before consent.

### W7 — Hardening

- reconnect and ICE restart;
- TURN quotas and abuse controls;
- codec/device matrix;
- malformed SDP/fuzz tests;
- network-change and sleep/resume tests;
- diagnostics without addresses or credentials.

### W8 — Workspace/group calls (research)

Group calls require a topology decision:

- **full mesh**: every participant connects to every other; private, no SFU,
  but N² bandwidth and CPU; practical for a small workspace only;
- **SFU**: a relay mixes/forwards streams; scalable but a third party and
  usually decrypts media unless an E2EE insertable-stream layer is added;
- **hybrid**: mesh for 2–3, SFU with E2EE for larger rooms.

No group-call implementation should start before this decision and a privacy
review.

## 11. Decision gates

- **G0:** DataChannel works direct, via STUN, and forced via TURN with acceptable
  latency/CPU.
- **G1:** signaling documents are authenticated, replay-safe, and expire.
- **G2:** a real workspace join/approval/receipt completes over WebRTC on
  Windows.
- **G3:** Android completes the same flow on a physical device.
- **G4:** 1:1 audio is intelligible, stable, and battery-acceptable on both
  platforms.
- **G5:** 1:1 video meets device/codec/thermal thresholds.
- **G6:** TURN quotas, reconnect, and diagnostics pass.
- **G7:** group-call architecture and E2EE decision approved.
## 12. Testing plan

### Unit

- SDP size/structure validation and fingerprint binding;
- offer/answer/candidate signature, expiry, replay, foreign signer;
- ICE policy (`all`, `relay`), candidate parsing, TURN credential scope;
- DataChannel framing, MTU, backpressure, close behavior;
- call state machine and glare handling;
- permission/consent policy.

### Integration

- two native peers on a LAN, host candidates only;
- STUN-assisted pair across a NAT;
- forced TURN pair with direct blocked;
- symmetric NAT/CGNAT simulation;
- reconnect after IP change and ICE restart;
- packet loss/latency injection;
- workspace join, approval, receipt over DataChannel;
- audio loopback and video device test;
- background/sleep/wake on Android.

### CI

- unit tests and SDP fixtures always;
- optional Linux job with a self-hosted coturn and two native peers;
- no dependency on a public STUN/TURN service for required CI;
- Windows/Android packaging remains in GitHub Actions.

## 13. Acceptance criteria

1. WebRTC is off by default and requires explicit consent.
2. A normal invitation is unchanged unless WebRTC is selected.
3. A signed WebRTC offer/answer is bound to the Reticulum identity and rejects
   tampering, replay, expiry, and foreign signers.
4. DataChannel can carry a workspace join, approval, receipt, and messages.
5. Direct, STUN-assisted, and TURN-relayed paths are visibly distinct.
6. TURN is used only when direct ICE fails or relay-only is selected.
7. Calls are 1:1, explicitly accepted, and never auto-answer.
8. Microphone/camera permissions are requested at call time.
9. No recording, transcription, or media persistence.
10. Failed WebRTC/calls do not change contact approval or workspace membership.
11. Android and Windows pass the physical call matrix before calls are enabled
    by default.
12. Diagnostics contain no SDP, candidates, TURN credentials, or media keys.

## 14. Open questions

1. Native stack: `str0m`, `webrtc-rs`, platform WebRTC, or a hybrid?
2. Signaling: non-trickle SDP in one document, or signed candidate messages?
3. Default STUN/TURN policy: none, self-hosted, or approved community?
4. DataChannel as a Reticulum interface vs an application-level LXMF bridge?
5. Should a WebRTC connection and a call share one peer connection?
6. How long may a call ring before timeout?
7. Group calls: full mesh, SFU with insertable-stream E2EE, or no group calls?
8. Browser client: separate WASM Reticulum, or a native bridge?
9. Codec licensing and hardware acceleration policy.
10. Whether WebRTC should ever be a default connection path, or remain an
    explicit fallback.

## 15. Out of scope

- Server-free WebRTC.
- Anonymous calling.
- PSTN/SIP.
- Recording/transcription.
- Group calls before W8.
- Browser client before a separate identity/vault/WASM decision.
- Replacing Reticulum/LXMF or the existing QUIC underlay.

## 16. References

- Reticulum I2P and interface model:
  <https://reticulum.network/manual/interfaces.html>
- WebRTC DataChannel and ICE:
  <https://www.w3.org/TR/webrtc/>
- TURN:
  <https://www.rfc-editor.org/rfc/rfc8656>
