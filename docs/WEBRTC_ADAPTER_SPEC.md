# WebRTC adapter specification and roadmap

Status: design and early implementation. No native WebRTC media stack exists in
Mesh Chat yet. The signed call-signaling foundation is being added first.

## 1. Summary

The near-term onboarding path is a **TCP access point**, not WebRTC. A TCP
access point works on Windows and Android with outbound TCP only, needs no local
daemon, and is already the supported remote-profile path.

The **WebRTC adapter is for calls first**:

1. **1:1 audio calls** between approved contacts, using Reticulum-signed call
   signaling and a WebRTC media plane.
2. **1:1 video calls** after audio is stable.
3. **Optional later:** a WebRTC DataChannel that carries Reticulum packets for
   onboarding or browser clients. This is not a prerequisite for joining a
   workspace and is deferred until a concrete need is proven.

WebRTC is not a server-free transport. A practical deployment needs:

- a signaling exchange for SDP and ICE candidates;
- STUN for server-reflexive candidates;
- TURN when direct ICE fails, especially on symmetric NAT or CGNAT.

Reticulum remains the identity and control plane. It authenticates the peers,
carries signed call signaling, and continues to carry messages and workspace
events. WebRTC is a separate media plane.

The adapter must be explicit, consented, non-default, and honest about relay
metadata. It does not replace the existing direct, TCP access point, I2P, or
Reticulum paths.

## 2. Definitions

- **WebRTC adapter** — a native component that creates a peer connection,
  exchanges signed session descriptions, carries media tracks (and later a
  DataChannel), and exposes the result to the service.
- **DataChannel transport** — an ordered, reliable SCTP channel that could
  carry framed Reticulum packets in a later increment.
- **Signaling document** — a signed `call_invite`, `call_answer`,
  `call_candidate`, or `call_hangup` document bound to a contact/workspace and
  session.
- **ICE** — Interactive Connectivity Establishment: host, server-reflexive,
  peer-reflexive, and relayed candidates.
- **STUN** — an observer that reports a peer’s public UDP tuple.
- **TURN** — a relay used when direct ICE cannot establish a path.
- **Call session** — an authenticated audio/video session with explicit
  ringing, accept, decline, and hangup states.
- **Mesh peer connection** — a WebRTC peer connection carrying media, and later
  optionally a DataChannel.

## 3. Why WebRTC

WebRTC provides capabilities Mesh Chat does not currently have:

- mature ICE candidate gathering and connectivity checks;
- DTLS/SRTP media;
- Opus audio and VP8/VP9/H.264 video;
- echo cancellation and device audio/video integration;
- browser-class NAT traversal behavior;
- a path to browser-based calling later.

It also provides a DataChannel, but that is a secondary use until a real
onboarding or browser requirement appears.

The trade-off is substantial: signaling, STUN/TURN, native media stacks,
permissions, codecs, battery, and a second traversal path alongside the
existing QUIC Offer/Answer/Ready work.

## 4. Goals

1. A 1:1 audio call can be placed from an approved contact without joining a
   third-party calling service.
2. A 1:1 video call can be added after audio is stable.
3. Call signaling is authenticated by the existing Reticulum identities; a
   WebRTC DTLS fingerprint alone is not identity.
4. Direct ICE is preferred; TURN is an explicit fallback with bounded
   credentials and quotas.
5. The UI states whether the media path is direct or TURN-relayed.
6. No silent camera/microphone access, no auto-answer, no recording.
7. The adapter is off by default and does not alter existing invitation,
   membership, or delivery semantics.
8. A DataChannel onboarding adapter is considered only after calls, and only if
   a TCP access point or direct path cannot meet a concrete requirement.

## 5. Non-goals

- A server-free WebRTC deployment.
- Anonymous calls or anonymity for relay metadata.
- PSTN, SIP, or phone-number calling.
- Group calls or an SFU in the first call increments.
- Recording, transcription, or cloud media storage.
- Replacing Reticulum/LXMF as the message and membership protocol.
- Making WebRTC the default invitation path.
- Making the WebRTC DataChannel a prerequisite for workspace onboarding.
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

### 6.2 Connection path (C5, conditional)

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

### 6.5 DataChannel transport (C5, conditional)

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

### 6.6 Calls (C0–C3, primary)

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

This is the **target UX** for the adapter; WebRTC media is not implemented in
0.2.76 (the C0a signaling foundation is).
The adapter must feel like one obvious next step, not a networking console. The
guiding rule is:

> **One primary action per screen, plain-language progress, no dead ends, and no
> surprise microphone, camera, or relay use.**

**Priority:** the call UX in section 7.7 is the near-term WebRTC UX. The
connection and workspace flows in sections 7.2–7.6 describe the conditional
DataChannel onboarding adapter (C5), not the current onboarding path. For now,
workspace onboarding uses a TCP access point; calls are the first WebRTC
feature.

WebRTC must not expose SDP, ICE, DTLS, codecs, candidate types, or TURN
credentials in the normal flow. Those belong in diagnostics only.

### 7.1 UX principles

1. **Progressive disclosure.** WebRTC is under **Other connection options**, not
   the default. It becomes prominent only when the current path is unavailable
   or the user explicitly asks for help connecting.
2. **One decision at a time.** Choose a connection method, review the path,
   consent, connect. Do not combine method selection, relay consent, and
   identity verification into one dense screen.
3. **Show the path in human terms.** Use **Direct**, **Relayed**, and
   **Same network** — not “ICE,” “srflx,” or “TURN.”
4. **Explain the trade-off before consent.** “Direct when possible; relayed
   through a server only if needed. The relay sees connection metadata, not
   message or call content.”
5. **Never auto-answer, auto-call, or auto-start media.** The microphone and
   camera stay off until the user accepts a call and grants permission.
6. **Never dead-end.** Every failure has a primary recovery action and a
   secondary **Send message** or **Back** action.
7. **Preserve the relationship.** A failed WebRTC connection or call never
   removes a contact, approval, workspace membership, or saved request.
8. **Consistent states.** The same status words and colors are used for
   invitations, calls, and diagnostics.
9. **Accessible by default.** Keyboard, screen reader, focus order, large touch
   targets, reduced motion, and non-color status text.
10. **No jargon, no raw addresses.** The normal UI shows a short path label and
    a **Details** disclosure. Copied diagnostics never contain SDP, candidates,
    TURN credentials, or media keys.

### 7.2 Connection flow map (C5, conditional)

```text
Start invitation
  → choose WebRTC (Other options)
  → review path + relay disclosure
  → consent
  → create invitation
  → share / wait
  → joiner preview
  → joiner consent
  → checking direct
  → relaying (only if needed)
  → securing
  → connected
  → send signed join / open chat
```

Joiner states:

```text
invitation_ready
  → preparing
  → checking_direct
  → relaying          (only if direct fails or relay-only)
  → securing
  → connected
  → approval_pending  (workspace)
  → approved
  → ended / failed
```

The UI must use:

- **Preparing secure connection…**
- **Checking a direct path…**
- **Relaying through the access point…**
- **Securing the connection…**
- **Connected — Direct** or **Connected — Relayed**
- **Waiting for approval** for a workspace
- **Couldn’t connect** only after a terminal failure

### 7.3 Creator flow: WebRTC DataChannel invitation (C5, conditional)

Entry point:

- **Start a chat → Invite → Other connection options → WebRTC**
- In a workspace: **Invite people → Other connection options → WebRTC**

Screen 1 — **How should they connect?**

- WebRTC option label: **WebRTC — works across many networks**
- One-line description: **Direct when possible; relayed only if needed.**
- If a direct path is already known to be unavailable, show a gentle callout:
  **Direct connection isn’t available on this network. WebRTC or an access
  point can still work.**

Screen 2 — **Review WebRTC**

- Heading: **Connect over WebRTC**
- Body:
  - **WebRTC finds a direct path when it can.**
  - **If direct fails, it can relay through a TURN server.**
  - **The relay sees connection metadata, not message contents.**
- Path summary:
  - **Direct:** available / unavailable / unknown
  - **Relay:** configured / not configured
- If no STUN/TURN is configured:
  - **Use host-only (same network)** — works only on the same LAN.
  - **Set up STUN/TURN** — opens Settings.
- Consent checkbox: **Use WebRTC for this invitation**
- Primary: **Create WebRTC invitation**
- Secondary: **Back**

Screen 3 — **Invitation ready**

- **Your signed invitation is ready.**
- **WebRTC details are inside; the other person will review and consent.**
- Copy / Share / Save.
- **Keep Mesh Chat open while they connect.**
- Path note: **Direct when possible; relay only if needed.**

### 7.4 Joiner flow: DataChannel connection (C5, conditional)

Entry point: paste/import a signed WebRTC invitation.

Screen 1 — **Review invitation**

- Heading: **Connect to {name} over WebRTC**
- Identity block: name, fingerprint, workspace name if applicable.
- **What will happen**
  1. **We’ll try a direct connection first.**
  2. **If direct fails, the connection may relay through a TURN server.**
  3. **The relay sees metadata, not message or call content.**
- Path summary:
  - **Direct:** likely / unknown / unavailable
  - **Relay:** available / not configured
- Consent checkbox: **Use this WebRTC connection**
- Primary: **Connect over WebRTC**
- Secondary: **Cancel**

Do not ask the joiner to paste SDP or candidates. If an out-of-band return
document is required for first contact, use one clear step: **Send this reply
back to {name}**, with Copy / Share / Save.

Screen 2 — **Connecting**

A single progress panel with a short, changing status and a **Cancel** action:

```text
Checking a direct path…
Relaying through the access point…   (only when used)
Securing the connection…
```

Show a path badge as soon as it is known:

- **Direct**
- **Relayed**
- **Same network**

Do not show both a spinner and a technical log. A **Details** disclosure may
show safe, non-address state.

Screen 3 — **Connected**

- Heading: **Connected over WebRTC**
- Path badge: **Direct** or **Relayed**
- For a personal contact:
  - **Send a message** (primary)
  - **Open chat** (secondary)
- For a workspace:
  - **Joining workspace…**
  - **Waiting for approval**
  - **Open workspace** when approved
- Always show a short note: **You can disconnect at any time.**

### 7.5 Existing contact: Improve connection (C5, conditional)

If messages are slow or failing and the contact is approved:

- Show a non-blocking card in the conversation:
  **Trying to reach {name}.**
  **Try WebRTC** (primary) · **Details** (secondary)
- Tapping **Try WebRTC** shows:
  - current path and last delivery state;
  - **WebRTC may find a direct path or use a relay.**
  - consent checkbox;
  - **Try WebRTC**.
- A successful attempt adds a **Connected over WebRTC** badge for the session.
- A failed attempt returns to the conversation with:
  **WebRTC couldn’t connect. Your contact and messages are unchanged.**
  **Try again** · **Send message** · **Connection settings**

No new contact approval is created by **Improve connection**.

### 7.6 Workspace flow via DataChannel (C5, conditional)

Owner:

1. **Invite people → Other connection options → WebRTC.**
2. Review and consent.
3. Create/share the signed workspace invitation.
4. Keep the workspace open while the joiner connects.
5. Approve the pending join request.

Joiner:

1. Import the workspace invitation.
2. Review **Connect over WebRTC** and consent.
3. Watch **Checking direct → Relaying → Securing → Connected**.
4. The signed join request is sent over the WebRTC DataChannel.
5. See **Waiting for approval**.
6. On approval, see **Workspace approved** and **Open workspace**.

If approval is delayed, the UI says **Request delivered; waiting for the owner**
and keeps the request saved. It must not show a connection failure.

### 7.7 Call flows (C0–C3, primary)

#### Call entry points

- A **Call** button appears in a 1:1 conversation header only when:
  - the contact is approved; and
  - WebRTC calls are enabled and configured.
- If calls are not configured, the button opens a small setup card:
  **Calls need WebRTC. Set up calls** · **Not now**.
- Workspace calls are not shown until W8.

#### Call state map

```text
idle → dialing → ringing → connecting → in_call → ended
                         ├→ declined
                         ├→ busy
                         ├→ no_answer
                         └→ failed
```

#### Outgoing call

1. Tap **Call**.
2. Choose **Audio call** or **Video call**.
3. Preflight card:
   - microphone/camera status;
   - selected devices;
   - **Camera and microphone start only after {name} accepts.**
4. Primary: **Call {name}**.
5. States:
   - **Calling {name}…** — cancel
   - **Ringing…** — cancel
   - **Connecting…** — cancel
   - **In call** — timer, path badge, controls
6. If the callee declines: **{name} declined** · **Send message**.
7. If busy: **{name} is on another call** · **Send message**.
8. If no answer: **No answer** · **Call back** · **Send message**.

#### Incoming call

Show a full-screen or high-priority card, never a silent background start:

- caller name, avatar, fingerprint;
- **Incoming audio call** or **Incoming video call**;
- **Camera and microphone are off until you accept.**
- Primary: **Accept**
- Secondary: **Decline**
- Optional: **Message instead**

On **Accept**:

1. Request microphone (and camera for video) permission.
2. If denied, explain exactly what is blocked and offer **Open settings** or
   **Accept audio only** when possible.
3. Connect; show **Connected — Direct** or **Connected — Relayed**.

No auto-answer. No camera preview before acceptance.

#### In-call controls

Always visible, large, and labelled:

- **Mute** / **Unmute**
- **Speaker** / **Earpiece**
- **Camera on** / **Camera off** (video only)
- **Switch camera** (mobile video)
- **Hang up**
- Path badge: **Direct** / **Relayed**
- Quality indicator: **Good** / **Fair** / **Poor** (not a raw bitrate)

In-call failure:

- **Connection lost. Reconnecting…**
- After timeout: **Call ended** · **Call back** · **Send message**
- A failed call never changes contact approval or workspace membership.

#### Missed calls and call history

- Add a timeline event: **Missed audio call from {name}**, **Declined call**, or
  **Call ended — 4m 12s**.
- Actions: **Call back** · **Message**.
- Do not create a message body or transcript.
- Do not imply the call was recorded.

### 7.8 Settings and permissions

**Settings → Connections → WebRTC**

- **WebRTC connections** — off by default.
- **Calls** — off until the call increment; separate consent.
- **STUN servers** — user-supplied; no default public list.
- **TURN server** — address and short-lived credentials; sealed.
- **Prefer relay** — off; when on, the UI says **Relayed** from the start.
- **Test WebRTC** — shows **Direct**, **STUN-assisted**, or **TURN-relayed**;
  no addresses in the result.

**Settings → Calls**

- **Microphone** — device picker and level test.
- **Camera** — device picker and preview test.
- **Speaker** — output picker.
- **Echo cancellation** — on by default.
- **Ringtone/vibration** — on.
- **Call notifications** — respecting OS permission.

Permission rules:

- Request microphone/camera at call time, not at install.
- Explain the specific permission before invoking the OS prompt.
- If denied, keep **Decline** and **Send message** available.
- Never change a permission silently.

### 7.9 Copy and state table

| Screen/state | Primary | Secondary | Never say |
|---|---|---|---|
| WebRTC option | **WebRTC — works across many networks** | — | “ICE,” “SDP,” “TURN candidate” |
| Review | **Create WebRTC invitation** / **Connect over WebRTC** | **Back** / **Cancel** | “Anonymous,” “server-free” |
| Connecting | **Cancel** | **Details** | “DTLS handshake failed” |
| Direct success | **Connected — Direct** | **Send message** | “Peer-reflexive candidate” |
| Relay success | **Connected — Relayed** | **Send message** | “TURN allocation” |
| Workspace waiting | **Waiting for approval** | **Open saved request** | “Connection failed” |
| Outgoing call | **Cancel** | **Message instead** | “Call failed” before timeout |
| Incoming call | **Accept** | **Decline** | “Auto-answer” |
| Permission denied | **Open settings** | **Send message** | “Camera unavailable” without reason |
| Call failed | **Try again** | **Send message** | “User unreachable” when unknown |

### 7.10 Error and recovery matrix

| Situation | User sees | Primary recovery |
|---|---|---|
| No STUN/TURN configured | **WebRTC needs a relay for this network.** | **Set up STUN/TURN** |
| Direct ICE fails, TURN works | **Relaying through the access point…** → **Connected — Relayed** | None needed |
| Direct and TURN fail | **Couldn’t connect over WebRTC.** | **Try again**, **Send message**, **Settings** |
| TURN rejects credentials | **The relay rejected this session.** | **Check TURN settings**, **Send message** |
| Callee offline | **{name} isn’t available right now.** | **Send message** |
| Callee declines | **{name} declined.** | **Send message** |
| No answer | **No answer.** | **Call back**, **Send message** |
| Mic denied | **Microphone access is off.** | **Open settings**, **Decline** |
| Camera denied | **Camera access is off.** | **Audio only**, **Open settings** |
| Network change | **Reconnecting…** | Automatic retry; **Hang up** |
| App backgrounded | **Call may be paused.** | Return to app; OS notification |
| Invitation expired | **This invitation expired.** | **Ask {name} for a fresh invitation** |

Every terminal error must leave the conversation usable and the relationship
intact.

### 7.11 Mobile and accessibility

- Incoming calls use the platform’s high-priority notification/full-screen
  intent where permitted; otherwise a clear in-app banner.
- Audio focus, speaker/earpiece/Bluetooth routing, and screen-lock behavior are
  explicit.
- Release camera/microphone on hangup, background, or permission revoke.
- Show a persistent notification for an active call.
- Minimum 44×44 px touch targets; labels for every icon.
- Screen-reader labels: “Mute microphone,” “Turn camera off,” “Hang up,”
  “Connection relayed.”
- Keyboard: focus the primary action; Escape cancels/hangs up with confirmation.
- Do not use color alone for Direct/Relayed/Failed.
- Respect reduced motion; avoid autoplay ringtones when the OS is silent.
- Test with one hand, large text, and a screen reader.

### 7.12 UX acceptance criteria

1. A first-time user can create a WebRTC invitation after at most two decisions:
   choose WebRTC and consent.
2. A joiner can connect after reviewing one screen and selecting one checkbox.
3. The path is visible as **Direct**, **Relayed**, or **Same network**.
4. No screen shows SDP, ICE, TURN credentials, or candidate addresses.
5. No call starts microphone or camera before explicit acceptance and OS
   permission.
6. An incoming call can be accepted or declined in one tap from the call card.
7. A failed connection or call always offers **Try again** and **Send message**.
8. A failed WebRTC attempt never removes a contact, approval, workspace, or
   saved request.
9. Workspace joining shows **Waiting for approval**, not “failed,” while the
   owner has not responded.
10. All controls have accessible names, keyboard focus, and non-color status
    text.
11. The flow works on Windows and Android with the same words and states.
12. A user can turn WebRTC and calls off without affecting existing messages,
    contacts, or workspaces.

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

The roadmap is calls-first. The DataChannel onboarding adapter is conditional
and comes after calls.

| Increment | Platform | Outcome | Effort | Gate |
|---|---|---|---|---|
| C0a | Desktop | Signed call signaling documents and call state machine | M | G0 |
| C0b | Desktop | Native 1:1 audio spike with self-hosted STUN/TURN | M | G1 |
| C1 | Windows | 1:1 audio call, Opus, mic/speaker, call UI | L | G2 |
| C2 | Android | 1:1 audio call, audio focus/foreground service | L | G3 |
| C3 | Windows/Android | 1:1 video call, codec/device validation | L | G4 |
| C4 | Both | Hardening, TURN quotas, reconnect, diagnostics | M | G5 |
| C5 | Both | Conditional WebRTC DataChannel onboarding adapter | XL | G6 |
| C6 | Research | Group-call architecture (mesh vs SFU/E2EE) | XL | G7 |

### C0a — Signed call signaling foundation

Goal: make call invitation, answer, ICE candidate, and hangup messages
authenticated and replay-safe without adding media yet.

Implemented foundation: `service/src/mesh_chat/webrtc_signaling.py`, with tests
in `service/tests/test_webrtc_signaling.py`. It is not yet wired into the
service command surface or UI.

Scope:

- signed `call_invite`, `call_answer`, `call_candidate`, `call_hangup`;
- contact/workspace identity binding;
- call/session ID, single-use invite, expiry, replay rejection;
- media type (`audio` / `video`);
- SDP and DTLS fingerprint binding;
- bounded document size and strict parsing;
- call state machine: `idle`, `dialing`, `ringing`, `connecting`, `in_call`,
  `ended`, `declined`, `busy`, `no_answer`, `failed`;
- no microphone, camera, SDP generation, or ICE yet.

Exit criteria:

- tampered SDP/fingerprint rejected;
- foreign signer rejected;
- expired or replayed invite rejected;
- answer is bound to the exact invite digest;
- hangup/candidate are scoped to the call ID;
- state transitions are unit-tested.

### C0b — Native audio spike

Implemented experiment: `experiments/webrtc-call`, using aiortc with synthetic
440/660 Hz tracks, host candidates, and the C0a signed invite/answer documents.
It is not a shipping dependency and does not use a microphone yet.

Goal: prove a native 1:1 audio call on a desktop using the C0a signaling.

Scope:

- native WebRTC peer connection;
- Opus audio, microphone, speaker;
- host/STUN/TURN candidates;
- force TURN to measure relay latency;
- no production UI; a bounded harness is enough.

Exit criteria:

- clear audio on LAN;
- STUN-assisted audio across NAT;
- TURN-forced audio when direct fails;
- reconnect after network change;
- measured latency, CPU, and audio quality.

### C1 — Windows 1:1 audio

Device spike implemented: `experiments/webrtc-call/live.py` captures the real
Windows microphone, sends it through the WebRTC/Opus path, and can monitor the
decoded audio. It is still local-only; service signaling, durable call state,
permissions, and UI are not wired yet.

Goal: a consented audio call between approved Windows contacts.

Scope:

- call button, ringing, accept/decline/hangup;
- microphone/speaker device selection;
- mute, audio focus, path badge;
- call timeline events;
- permission preflight and recovery.

Exit criteria:

- clear audio on Windows↔Windows;
- no auto-answer;
- permissions requested only at call time;
- no recording;
- failed calls do not change contact approval.

### C2 — Android 1:1 audio

Goal: the same call path on Android.

Scope:

- native WebRTC plugin;
- audio focus, foreground service, screen-lock behavior;
- microphone/speaker/Bluetooth routing;
- incoming-call notification;
- physical-device test.

Exit criteria:

- Windows↔Android and Android↔Android audio;
- background/network transitions documented;
- battery/data measured;
- no auto-answer or silent microphone.

### C3 — 1:1 video

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

### C4 — Hardening

- reconnect and ICE restart;
- TURN quotas and abuse controls;
- codec/device matrix;
- malformed SDP/fuzz tests;
- network-change and sleep/resume tests;
- diagnostics without addresses, credentials, or media keys.

### C5 — Conditional DataChannel adapter

Only start if a concrete onboarding or browser requirement exists after TCP
access point, direct QUIC, and I2P have been evaluated.

Scope:

- DataChannel framing/MTU/backpressure;
- custom Reticulum interface or application-level LXMF bridge;
- signed WebRTC invitation descriptor;
- explicit joiner consent;
- fallback to TCP/Reticulum.

Exit criteria:

- a real workspace join, approval, receipt, and messages over WebRTC;
- direct/STUN/TURN visible;
- no plaintext or credentials in diagnostics;
- disabling WebRTC removes the interface and leaves other paths intact.

### C6 — Workspace/group calls (research)

Group calls require a topology decision:

- **full mesh**: every participant connects to every other; private, no SFU,
  but N² bandwidth and CPU; practical for a small workspace only;
- **SFU**: a relay mixes/forwards streams; scalable but a third party and
  usually decrypts media unless an E2EE insertable-stream layer is added;
- **hybrid**: mesh for 2–3, SFU with E2EE for larger rooms.

No group-call implementation should start before this decision and a privacy
review.

## 11. Decision gates

- **G0:** call signaling is authenticated, replay-safe, expires, and binds
  SDP/DTLS to the Reticulum identity.
- **G1:** native audio works on a LAN, across STUN, and forced through TURN.
- **G2:** Windows 1:1 audio passes device, permission, and quality checks.
- **G3:** Android 1:1 audio passes physical-device and battery checks.
- **G4:** 1:1 video meets device/codec/thermal thresholds.
- **G5:** TURN quotas, reconnect, and diagnostics pass.
- **G6:** a concrete requirement justifies the DataChannel adapter; a real
  workspace join succeeds over it.
- **G7:** group-call architecture and E2EE decision approved.

## 12. Testing plan

Priority: call signaling and native audio first. DataChannel tests are required
only when C5 is started.

### Unit

- SDP size/structure validation and fingerprint binding;
- offer/answer/candidate signature, expiry, replay, foreign signer;
- ICE policy (`all`, `relay`), candidate parsing, TURN credential scope;
- DataChannel framing, MTU, backpressure, close behavior;
- call state machine and glare handling;
- permission/consent policy.

### Integration

- audio loopback and audio-device test;
- STUN-assisted audio across a NAT;
- forced TURN audio with direct blocked;
- symmetric NAT/CGNAT simulation;
- reconnect after IP change and ICE restart;
- packet loss/latency injection;
- video device test;
- background/sleep/wake on Android;
- workspace join, approval, and receipt over DataChannel only after C5 starts.

### CI

- unit tests and SDP fixtures always;
- optional Linux job with a self-hosted coturn and two native peers;
- no dependency on a public STUN/TURN service for required CI;
- Windows/Android packaging remains in GitHub Actions.

## 13. Acceptance criteria

1. WebRTC is off by default and requires explicit consent.
2. A normal invitation and TCP-access-point onboarding are unchanged.
3. A signed call invite/answer is bound to the Reticulum identity and rejects
   tampering, replay, expiry, and foreign signers.
4. A 1:1 audio call works on Windows and Android without auto-answer.
5. A 1:1 video call works after audio, with camera consent.
6. Direct and TURN-relayed media paths are visibly distinct.
7. TURN is used only when direct ICE fails or relay-only is selected.
8. Microphone/camera permissions are requested at call time.
9. No recording, transcription, or media persistence.
10. Failed calls do not change contact approval or workspace membership.
11. Android and Windows pass the physical call matrix before calls are enabled
    by default.
12. Diagnostics contain no SDP, candidates, TURN credentials, or media keys.
13. A WebRTC DataChannel onboarding adapter is not required for a workspace
    join and remains conditional (C5).

## 14. Open questions

1. Native stack: `str0m`, `webrtc-rs`, platform WebRTC, or a hybrid?
2. Signaling: non-trickle SDP in one document, or signed candidate messages?
3. Default STUN/TURN policy: none, self-hosted, or approved community?
4. Whether the C5 DataChannel should be a Reticulum interface or an
   application-level LXMF bridge.
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
- Group calls before C6.
- A WebRTC DataChannel onboarding adapter before C5.
- Browser client before a separate identity/vault/WASM decision.
- Replacing Reticulum/LXMF or the existing QUIC underlay.

## 16. References

- Reticulum I2P and interface model:
  <https://reticulum.network/manual/interfaces.html>
- WebRTC DataChannel and ICE:
  <https://www.w3.org/TR/webrtc/>
- TURN:
  <https://www.rfc-editor.org/rfc/rfc8656>
