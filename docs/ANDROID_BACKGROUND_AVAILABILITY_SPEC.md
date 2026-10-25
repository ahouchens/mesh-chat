# Android background availability service with native WebRTC

Status: implemented in source on 2026-10-24, pending CI and physical
qualification. The Android foreground service, native WebRTC host, native
onboarding/reconnect cutover, Python background reconnect supervisor, renderer
opt-in, and focused tests are in the tree. Doze, network-switch, 16 KB
page-size, APK-size, and physical Windows↔Android qualification remain release
gates. The native-WebRTC decision is recorded in
[ADR 0024](adr/0024-android-background-availability-native-webrtc.md). This
document remains the design and qualification plan.

This proposal supersedes the following statements when accepted:

- [ADR 0014](adr/0014-mobile-lifecycle-and-notifications.md) rejects Android
  foreground services and battery-optimization exemptions.
- [AUTO_RECONNECT_SPEC.md](AUTO_RECONNECT_SPEC.md) limits reconnect to the open,
  unlocked app and says there is no Android foreground service.
- The earlier version of this document deferred native WebRTC to Phase 3.
  **Native WebRTC is now required for the first release of this mode**, because
  the requirement is specifically to keep WebRTC connections alive.

Those statements remain true for the default foreground-only mode.

Acceptance of this spec requires a new ADR (next free number is 0024) that
records the native-WebRTC decision and narrows ADR 0014's blanket rejection of
foreground services to this opt-in mode. Until that ADR is accepted, this
document is a proposal, not a release commitment.

## 1. Decision summary

1. **Run an Android foreground service in the existing app process.** The
   service keeps the process at foreground importance and hosts the already
   embedded CPython runtime, the native WebRTC host, and the notification pump.
   It does not move Python into a second process in the first release.
2. **Move WebRTC data channels from the WebView to native ownership.** Use an
   Android native WebRTC implementation in the app process. It owns the
   `PeerConnection`, ICE/DTLS/SCTP, and `DataChannel`. Python exchanges raw
   Reticulum packets with that native host. The WebView is no longer in the
   data path and may be paused or destroyed.
3. **Move automatic WebRTC reconnect into Python for the background case.**
   Python already owns profiles, signed capabilities, mailbox publish/fetch,
   and document verification. Add a bounded background supervisor that asks
   the native host for SDP, signs the documents, publishes/fetches them, and
   monitors the native transport. The JS coordinator remains the foreground UI
   and compatibility path until migration is complete.
4. **Keep the guarantee precise.** While the process lives and the device is
   not Dozing, active native WebRTC DataChannels and Reticulum/LXMF paths stay
   open. After process death, the service can restart and re-establish a **new**
   WebRTC session if automatic reconnect is enabled and a mailbox is configured;
   it cannot preserve the old DTLS session.
5. **Doze, force-stop, OEM killers, and explicit Mesh Chat lock remain hard
   boundaries.** A foreground service does not prevent Doze. Doze may suspend
   networking; the service reports `degraded` and recovers when allowed.
6. **Calls keep their existing path.** Audio/video media continues to use the
   WebView plus `CallService` in this phase. Only data channels move native.
   Moving media is a separate project.
7. **The mode is opt-in, visible, and stoppable.** It starts only from a visible
   user action, shows a persistent generic notification with **Stop**, and is
   disabled by explicit Mesh Chat lock.
8. **No FCM/APNs, no hosted relay, no boot autostart in v1.** Those preserve
   the server-free model and avoid new push infrastructure.
9. **Enabling the mode renegotiates active WebRTC data sessions.** A WebView
   `PeerConnection` cannot be migrated into the native host; DTLS/SCTP state is
   not transferable. The user sees a brief reconnect when the mode is enabled
   (and when it is disabled while native data sessions are active). This must
   be disclosed; it is not a silent migration.

The hard requirement is therefore:

> With background availability enabled, an established WebRTC data connection
> between two Mesh Chat users remains open across screen-off and Activity
> destruction, without JavaScript or a visible WebView, for as long as the
> process is alive and the OS permits networking.

“Remains open” means the native `PeerConnection`/`DataChannel` and the Python
Reticulum interface attached to it are alive. It does not mean the peer is
reachable after a network change or after Doze; those are recovery cases.

## 2. Why the current design cannot satisfy this

- `RTCPeerConnection`, SDP, ICE, DTLS, and DataChannel event delivery live in the
  WebView (`src/webrtc-peer.ts`, `src/webrtc-onboarding.ts`).
- Python's `WebRTCInterface` is only a Reticulum interface; it sends raw packets
  through a callback supplied by the JavaScript bridge
  ([webrtc_interface.py](../service/src/mesh_chat/webrtc_interface.py#L1-L83)).
- The JS bridge is driven by `poll_mobile_events` every 750 ms, and that poll
  returns immediately while the page is hidden
  ([api.ts](../src/api.ts#L27-L51)).
- The reconnect coordinator exists only while the unlocked Messenger shell is
  mounted ([App.tsx](../src/App.tsx#L4701-L4736)).
- Android pauses/throttles a hidden WebView; a foreground service keeps the
  process important but does not make hidden JavaScript a reliable real-time
  packet pump. Keeping the WebView object and hoping is not a contract.

A Python-only service would therefore keep Reticulum and direct-native paths
alive but would still lose the WebRTC DataChannel. That does not meet the
requirement. Native WebRTC ownership is the necessary change.

## 3. Current ownership map

| Function | Current owner | Screen off | Activity destroyed | Process death |
| --- | --- | --- | --- | --- |
| Python service and vault | Embedded CPython in app process (`mobile_bridge`) | Alive if process/CPU allow | Alive if process lives | Lost |
| Reticulum/LXMF | Python threads in `ReticulumNetwork` | Alive if process/CPU allow | Same | Lost; restart can reinitialize |
| Direct-native QUIC | Rust `mobile_direct` pump + Python packet/recovery threads | Alive if process and Tauri runtime live | Tauri runtime may stop | Lost |
| WebRTC DataChannel | WebView JS `RTCPeerConnection` | No reliable JS packet flow | Usually lost | Lost |
| Local notifications | Plugin pump calling Python every 750 ms | While plugin/process lives | May stop with plugin | Lost |
| Calls | `CallService` foreground service + WebView media | Yes, subject to OS | Yes while process lives | Lost |
| Mesh Chat lock | `shutdown` + renderer unmount | Stops | Stops | Stops |

`BootstrapService` is not a model for this work: it is a separate
`:mesh_bootstrap` process that kills its process on destroy because RNS has
process-global singletons.

## 4. Guarantee model

### 4.1 States

| State | Meaning |
| --- | --- |
| `disabled` | No foreground service and no background native sessions. Foreground native sessions may still be used for manual onboarding, but they are not promised beyond the Activity lifetime. |
| `starting` | User enabled the mode; service is starting, notification posted, native host and Python runtime initializing. |
| `available` | Service is foreground, process alive, native WebRTC host and Python runtime initialized, locks held, not Dozing. Active native data channels and Reticulum paths are expected to stay open. |
| `degraded` | Service alive but OS networking is restricted (Doze, no network, OEM policy). Existing sockets may drop; reconnect/ICE recovery runs when permitted. |
| `recovering` | Service restarted or transport lost; Python is renegotiating a **new** native WebRTC session through the mailbox. No old DTLS session is claimed. |
| `recovery_required` | The service restarted but at least one path (direct-native, media, or WebRTC without a mailbox) cannot be restored in the background. The user must reopen Mesh Chat for that path. |
| `manual_required` | No mailbox/profile/consent for background recovery; an active session may still be alive, but a lost one must wait for the UI/manual flow. |
| `locked` | Explicit Mesh Chat lock, deletion, or key failure. Service stopped, native host closed, keys released. |
| `stopping` | User disabled the mode or the app is locking; transports are being retired. |

### 4.2 What “available” promises

For every live native WebRTC data session and eligible native path:

- the Android `PeerConnection` and `DataChannel` remain owned by native code in
  the app process;
- ICE consent freshness and DTLS/SCTP keepalives continue to run on native
  threads;
- Python's `WebRTCInterface` stays attached; outbound Reticulum packets are
  handed directly to the native `DataChannel`, and inbound packets are handed
  directly to Python;
- Reticulum/LXMF interfaces, direct-native pumps, outbox retries, notification
  work, and background reconnect supervision continue;
- an inbound message can be committed and notified while the screen is off;
- the service can state whether it is available, degraded, or recovering.

### 4.3 Sleep, Doze, and recovery matrix

| Condition | State | Native WebRTC data channel | Reticulum/LXMF | Notifications |
| --- | --- | --- | --- | --- |
| Screen off, device awake, not Dozing | `available` | Maintained | Maintained | Presented |
| Activity destroyed, process alive | `available` | Maintained | Maintained | Presented |
| Doze entered | `degraded` | May time out; recovery on exit | May time out | Queued until allowed |
| Process killed, service restarted | `recovering` | New session via mailbox, if enabled | Reinitialized | Recovery notice |
| No mailbox / no profile | `manual_required` | Old session gone; no background renegotiation | Reinitialized | Notification |
| Force-stop / OEM kill | `disabled` until launch | No | No | No |
| Explicit Mesh Chat lock | `locked` | Closed | Closed | No |
| Wi-Fi ↔ cellular | `available`/`recovering` | ICE restart or new session | Interface recovery | Delayed |
| Peer offline | `available`/`degraded` | Stays open until ICE/DTLS failure, then retries | Outbox waits | Per policy |

Android's documented limits apply: a foreground service is not a Doze
exemption, and Doze suspends network access and ignores wake locks outside
maintenance windows. See the
[Doze guide](https://developer.android.com/training/monitoring-device-state/doze-standby).

## 5. Options considered

### Option A — Foreground service plus native WebRTC data channel (chosen)

The service keeps the process alive; a native WebRTC implementation owns the
data channel; Python keeps its Reticulum interface and background supervisor.
This is the only option that meets the requirement without a visible WebView.

### Option B — Foreground service only, keep the WebView alive

Rejected as a guarantee. It can keep the process, but hidden WebView timers and
DataChannel event delivery are not reliable. It produces an intermittent
“sometimes connected” state. It remains useful only as a short transitional
fallback while native WebRTC is being qualified.

### Option C — Dedicated `:mesh_core` process

Move Python and native WebRTC into a separate service process; the UI becomes a
Binder client. It improves UI-process isolation but does not solve the WebRTC
ownership problem by itself, and it adds a second interpreter, vault-key
transfer, Binder limits, and a second copy of the native WebRTC library. It is a
later option, not a prerequisite.

### Option D — FCM wake-up

Rejected. It adds Google push infrastructure, a registration identity, and a
new external dependency while still requiring a foreground service or a native
reconnect. Not part of this design.

## 6. Chosen architecture

```text
┌──────────────────────────── app process ─────────────────────────────┐
│                                                                      │
│  Activity + WebView (UI, signaling documents, media calls)           │
│        │                                                             │
│        │ Tauri commands/events                                       │
│        ▼                                                             │
│  MeshRuntimeHost (process singleton, application context)            │
│    - CPython lifecycle and vault key                                  │
│    - MeshChatService command dispatch                                 │
│    - notification pump                                                │
│    - background availability state                                    │
│        │                                                             │
│        ├──────────────► NativeWebRtcHost (Kotlin)                     │
│        │                  - PeerConnectionFactory                      │
│        │                  - PeerConnection / DataChannel per session   │
│        │                  - ICE, DTLS, SCTP, TURN, stats               │
│        │                  - no WebView dependency                      │
│        │                                                             │
│        └──────────────► CPython threads                                │
│                           - Reticulum / LXMF                           │
│                           - WebRTCInterface per native session         │
│                           - BackgroundReconnectSupervisor             │
│                           - direct-native packet/recovery              │
│                                                                      │
│  MeshAvailabilityService (foreground, same process)                   │
│    - persistent notification + Stop                                   │
│    - partial wake lock / Wi-Fi lock / multicast lock                   │
│    - ConnectivityManager and Doze observers                           │
│    - restart and recovery policy                                      │
│                                                                      │
│  Rust Tauri runtime + existing mobile_direct pump                      │
└──────────────────────────────────────────────────────────────────────┘
```

Key ownership rules:

- `NativeWebRtcHost` is process-scoped and initialized from the application
  context. It never holds an Activity.
- Python never touches a `PeerConnection` object directly; it calls a small
  native bridge with session IDs and opaque SDP/ICE strings.
- JavaScript never handles `webrtc_packet` events for native data sessions.
  It may still own media `RTCPeerConnection`s for calls.
- The service owns the native host's lifetime only in the sense of starting and
  stopping availability; the host itself is a singleton like the runtime.

## 7. Native WebRTC transport

### 7.1 SDK choice

Primary candidate: the maintained Android WebRTC build
`io.github.webrtc-sdk:android` (Maven Central), which tracks upstream libwebrtc
and exposes the standard `org.webrtc` API. It supports data channels, ICE,
TURN, DTLS, and `getStats`, and it is a native library independent of the
WebView.

`NativeWebRtcHost` is not initialized only by the availability service. It is
safe to initialize lazily for any native data session, including manual
onboarding while availability is disabled. The availability service controls
whether sessions may survive Activity destruction; it does not gate the basic
native transport.

Adoption is gated on:

- **16 KB page-size support.** Android 15+ devices may use 16 KB pages; the
  native `.so` must be aligned and load on those devices. Verify with
  `zipalign -c -P 16 -v 4` and `readelf -l` (`LOAD` alignment 0x4000), not just
  a successful build.
- **APK size.** The arm64 native library is expected to add several megabytes;
  measure the actual release APK and update the size budget. The 0.9.36 CI
  arm64 release APK (including libwebrtc) measured 46,741,669 bytes and passed
  `zipalign -c -P 16 -v 4`; this is the current budget baseline.
- **License/notices.** Add the WebRTC license and any transitive notices to
  `THIRD_PARTY_NOTICES.md`.
- **ABI policy.** The app currently publishes `arm64-v8a` only; keep that.
- **Security/maintenance.** Pin an exact version; no dynamic version ranges.

If the SDK fails the 16 KB or maintenance gates, the fallback is a Rust
data-channel implementation (`webrtc` or a data-channel-focused stack) in the
existing native layer. That is a larger integration and must not be started
without a measured comparison. Do not use the unmaintained
`org.webrtc:google-webrtc` artifact for a target-36 app.

### 7.2 Native host API

```kotlin
object NativeWebRtcHost {
    fun initialize(context: Context)
    fun createOffer(
        sessionId: String,
        ice: IceConfiguration,
        channels: List<ChannelSpec>,
    ): NativeSdp
    fun acceptOffer(
        sessionId: String,
        offerSdp: String,
        ice: IceConfiguration,
        expectedChannels: List<ChannelSpec>,
    ): NativeSdp
    fun applyAnswer(sessionId: String, answerSdp: String)
    fun restartIce(sessionId: String): NativeSdp
    fun send(sessionId: String, packet: ByteArray): Boolean
    fun sendControl(sessionId: String, label: String, text: String): Boolean
    fun stats(sessionId: String): NativeStats
    fun close(sessionId: String)
    fun closeAll()
}
```

`NativeSdp` contains the gathered SDP and the SHA-256 DTLS fingerprint. The
fingerprint is computed from the SDP exactly as the existing signed-document
validator expects (`sha-256` with colon-separated uppercase bytes).

`ChannelSpec` covers the existing labels and message types:

- `mesh-reticulum`, ordered, binary — the Reticulum packet channel.
- `mesh-onboarding`, ordered, text — manual onboarding control messages
  (invitation and approval JSON). This channel is foreground-only in practice;
  if the Activity disappears, onboarding approval waits for the UI.
- `meshchat-reconnect`, ordered, text — reconnect capability control only.

The native host must reject unexpected labels, duplicate channels, non-binary
messages on `mesh-reticulum`, binary messages on the text control channels,
oversized control messages (for example over 16 KiB), and packets larger than
`WebRTCInterface.HW_MTU` (1064 bytes). It must also bound active sessions (for
example 16), pending control messages, per-session inbound queues, and total
buffered bytes; exceeding a bound closes the affected session with a redacted
reason rather than growing without limit.

### 7.3 Offer/answer flow

Manual onboarding (Android as offerer):

1. JS calls `native_webrtc_create_offer` with the current ICE configuration and
   the channel specs.
2. Native host creates the `PeerConnection`, creates `mesh-reticulum`, creates
   the offer, sets the local description, and waits for ICE gathering to
   complete (bounded, for example 15 seconds).
3. It returns SDP + fingerprint.
4. JS passes those to the existing `webrtc_onboarding_offer` command; Python
   signs the normal onboarding document. The document format does not change.
5. The offer is transferred by the existing copy/file/QR/mailbox UI.

Android as answerer:

1. JS verifies the offer document and extracts SDP.
2. JS calls `native_webrtc_accept_offer`; native host sets the remote
   description, registers `onDataChannel` for the expected labels, creates the
   answer, sets it locally, and gathers ICE. It does **not** wait for the
   incoming channels before returning the answer: `onDataChannel` fires only
   after ICE/DTLS/SCTP connectivity, which needs the answer. It returns the
   answer and keeps the host ready for the channels.
3. It returns SDP + fingerprint; JS calls `webrtc_onboarding_answer` to sign.
4. The answer is returned through the existing UI.
5. When the DataChannel opens, native host calls Python
   `native_webrtc_open(session_id)`; Python attaches the existing
   `WebRTCInterface`, returns the bridge ID, and starts the normal reannounce
   schedule.

The manual-answer keepalive rule from
[WEBRTC_MANUAL_ANSWER_ROOT_CAUSE.md](WEBRTC_MANUAL_ANSWER_ROOT_CAUSE.md) still
applies: the answerer's native PC must remain alive through an initial ICE
`failed` state for up to 120 seconds from offer application, capped by the
signed offer expiry. Do not close the PC on the first native `failed` callback
while the user is still returning the answer. The 120-second timer stops when
the DataChannel opens; an unanswered attempt then closes with the existing
manual-answer timeout diagnostic.

Reconnect:

- `BackgroundReconnectSupervisor` (Python) uses the existing signed
  request/offer/answer documents. It asks `NativeWebRtcHost` for SDP instead of
  the WebView, signs with the existing identity, and publishes/fetches through
  the existing mailbox client.
- Manual foreground reconnect may continue to use the JS coordinator until the
  native path reaches feature parity, but both must not create two competing
  `PeerConnection`s for the same profile/attempt. Use one attempt ID and one
  owner; the Python supervisor wins while the service is `available`.

Control channels:

- Manual onboarding: the native host routes `mesh-onboarding` text messages to
  the renderer through a bounded native event. JS keeps the existing invitation
  and approval logic; it sends replies through `native_webrtc_control_send`
  instead of a local `RTCDataChannel`. If the Activity is gone, onboarding is
  not continued; the data channel may remain but approval waits for the UI.
- Reconnect: the native host routes `meshchat-reconnect` text messages to the
  Python supervisor. Python sends through the same control command. It
  implements the capability request/reply and storage rules from
  `src/reconnect-control.ts`; it never accepts invitations or approval actions
  on this channel.

### 7.4 Packet path

Outbound (Reticulum → peer):

1. Reticulum calls `WebRTCInterface.process_outgoing(packet)`.
2. The interface's send callback calls the native bridge, not a JS event.
3. Native host checks `DataChannel.bufferedAmount`; if the bounded queue is
   full, it drops according to the existing Reticulum behavior or closes the
   session rather than growing without bound.
4. `DataChannel.send(ByteBuffer)` is called on the WebRTC signaling/worker
   thread or a bounded dedicated executor; never on the Python dispatch lock.

Inbound (peer → Reticulum):

1. `DataChannel.Observer.onMessage(ByteBuffer)` receives the binary packet.
2. Native host copies the bytes into a bounded queue and posts them to the
   Python executor.
3. Python calls `WebRTCInterface.process_incoming(packet)`; the interface counts
   bytes and hands the packet to `RNS.Transport`.
4. The queue is bounded (for example 256 packets or 256 KiB); overflow closes
   the session and records a redacted reason. It never blocks the WebRTC
   callback thread.

The startup race fixed in 0.9.36 still matters: native host must install its
observer and open the channel before announcing the Reticulum interface, and
Python must not drop early packets. The native host and Python bridge together
replace the JS startup buffer.

Native sessions must **not** emit the existing `webrtc_packet` service event for
the renderer. `_webrtc_outbound` routes packets to the native sink for native
sessions and to the JS event queue only for legacy WebView sessions. A native
session that also emits to JS would produce duplicate sends and a stale bridge.

### 7.5 ICE, TURN, and network changes

- ICE server configuration comes from the existing `call_ice_servers` command
  and `CallIceConfiguration`; TURN credentials are fetched fresh and never
  persisted by the native host.
- Relay-only consent is preserved: if the profile does not allow direct IP
  disclosure, the native configuration uses `iceTransportPolicy = RELAY`.
- Gather complete SDP for the manual copy/paste flow; do not depend on trickle
  ICE for documents that are copied. Append `a=end-of-candidates` to the
  gathered SDP before signing so the peer's diagnostics and manual-answer
  timing see the same marker as the WebView path.
- On network change, native host invokes ICE restart if the session supports it;
  if the restart does not recover within a bounded window, Python closes the
  session and the background supervisor renegotiates a new one.
- Do not invent a second signaling protocol. Reuse the signed documents and
  mailbox semantics.

### 7.6 Diagnostics

Native host exposes only redacted values:

- `connectionState`, `iceConnectionState`, `iceGatheringState`,
  `signalingState`;
- selected pair type (host/srflx/relay), protocol, family, relay protocol;
- local/remote candidate counts by type;
- DTLS state, bytes sent/received, DataChannel buffered amount;
- last native error code, never raw SDP, TURN credentials, or addresses.

The existing `peerDiagnostics` browser path remains for desktop and for media
calls. Android data sessions use a native diagnostics object and a new
`webrtc_native_diagnostics` command. The WebRTC manual-answer root-cause tests
must be ported or duplicated for the native transport.

### 7.7 Media calls

Audio/video calls remain on the WebView `RTCPeerConnection` plus `CallService`.
This avoids moving media capture, audio focus, camera, and rendering in the same
change. A native data session and a WebView call session can coexist for the
same contact; they are separate `PeerConnection`s with separate DTLS keys.

Do not claim that native data-channel work makes background **calls** reliable.
Calls already have the call foreground service; their media behavior is a
separate qualification.

## 8. Background reconnect supervisor (Python)

### 8.1 Why Python

Python already owns:

- per-contact/workspace reconnect profiles and consent
  ([reconnect_service.py](../service/src/mesh_chat/reconnect_service.py));
- signed request/offer/answer creation and verification
  ([reconnect.py](../service/src/mesh_chat/reconnect.py));
- mailbox publish/fetch and replay state;
- durable outbox and notification work.

The JS coordinator currently adds the WebRTC peer and UI polling. Once the peer
is native, that JS role is only a thin request/response surface; moving the
background loop to Python removes the WebView dependency.

### 8.2 Supervisor behavior

For each eligible profile, while `available`:

1. Read profile and capability state from the service store.
2. If a native session already exists, monitor its state and ICE/DTLS health;
   do not create a second peer.
3. If no session exists and consent/mailbox are ready, run the existing
   request/offer/answer state machine:
   - determine preferred initiator from device IDs;
   - fetch/publish through the mailbox;
   - ask `NativeWebRtcHost` for SDP;
   - sign with the identity;
   - verify the peer document before applying it;
   - attach the Python `WebRTCInterface` when the DataChannel opens.
4. Bound concurrency to two profiles, use jittered backoff
   (1/2/5/15/30/60 seconds), and stop on consent removal, block/delete,
   capability rejection, or user cancellation.
5. Report status through the existing reconnect state records so the UI sees
   the same states as the JS coordinator.
6. On every new DataChannel, port the existing control-channel behavior from
   `src/reconnect-control.ts` into the Python/native path: send a
   `connection_capabilities_request`, answer one with the current signed
   document, verify and store a received `connection_capabilities` document,
   refresh hourly, and retry without changing trust. This channel is
   capability-only; it must not accept invitations or approval actions.
7. Stop all attempts on lock, mode disable, profile deletion, or service stop.

The JS coordinator must not run concurrently for the same profile while the
background supervisor owns it. In v1, the Python supervisor is authoritative
while availability is enabled; the JS coordinator is authoritative only when
availability is disabled or after a documented handoff on foreground.

### 8.3 Recovery after process death

After `START_STICKY` restarts the service:

1. `startForeground` first, then initialize the native host and Python runtime.
2. Load enabled profiles, mailbox configuration, and consent.
3. Mark existing sessions as lost (`recovering`), not connected.
4. Start the supervisor; create new native peers and renegotiate.
5. If the vault key, notification permission, or mailbox is unavailable, stop
   and report the reason.

This can recover a WebRTC data session without the WebView. It cannot preserve
the old DTLS session, and it cannot recover media calls or direct-native paths
that depend on the Tauri runtime.

### 8.4 Foreground handoff

When the Activity returns:

- Python stops creating new background peers for profiles the JS UI is about to
  manage, or keeps ownership and exposes status to the UI.
- The simpler v1 rule: **Python owns data sessions while availability is
  enabled**; JS reads status and uses native control commands for retry/stop.
  Manual onboarding remains JS-driven. This avoids two owners.
- On disable/lock, Python closes all native data sessions; JS may then create
  WebView sessions only if the user explicitly uses the old foreground flow.
- Enabling the mode does not adopt a live WebView peer. The UI must close or
  mark the existing WebRTC data session, then let the supervisor create a
  native session. The signed documents, contact consent, and mailbox are
  unchanged; only the transport instance is replaced.
- If native sessions already exist when the mode is enabled, the supervisor
  adopts them by session/profile ID instead of creating duplicates.

## 9. Service lifecycle

### 9.1 Start

1. The user enables **Stay available in the background** in Settings. The UI is
   visible, so starting a foreground service is allowed.
2. The renderer calls `set_background_availability(enabled=true)`; Python
   persists the sealed preference. The visible app already has an initialized
   runtime, so this is a short command, not a new runtime start.
3. `MeshAvailabilityService` starts with
   `ContextCompat.startForegroundService`.
4. `onStartCommand` calls `startForeground` within five seconds, before any new
   Python or native WebRTC initialization.
5. `MeshRuntimeHost` ensures CPython and `NativeWebRtcHost` are initialized
   (no-op when the visible app already did it); the service acquires
   power/network locks and registers connectivity/Doze observers.
6. Any live WebView WebRTC data session for an eligible profile is marked for
   replacement; it is not migrated. The supervisor creates a native session
   after the service is available. The UI discloses the brief reconnect.
7. The background supervisor starts; Python transitions to `available` or
   `recovering`.

If `startForeground` fails, stop, release everything, and persist `enabled=false`
so a later service restart cannot pretend the mode is on. If Python/native
initialization fails after the notification is posted, update the notification
to a generic failure, release locks, and persist `enabled=false`.

### 9.2 Screen off and Activity stop

- `onActivityPaused` reports `background` for diagnostics.
- When availability is enabled, the 45-second `suspendAfterSharing` timer is not
  used to suspend; the service reports `background_available`.
- `onActivityDestroyed` does not send `suspended` while the service is enabled.
  The native host and Python runtime remain.
- Python's `mobile_lifecycle_transition` maps `suspended` to
  `background_available` when the mode is enabled and **does not retire** native
  WebRTC sessions, direct sessions, packet pumps, or notification work.
- A native WebRTC session remains attached to `RNS.Transport`; there is no
  `webrtc_detach` on Activity stop.
- If availability is **disabled**, native data sessions are foreground-only:
  the UI closes them on renderer unmount and the host closes any orphan on
  Activity destruction. They may still be used for manual onboarding while the
  Activity is visible, but they do not survive the Activity going away.

### 9.3 Resume

On Activity resume, Python reports `foreground` and performs the existing
bounded reconciliation. The UI queries native session status and displays it.
If the background supervisor owns the session, the UI does not create a new
peer for the same profile.

### 9.4 Stop and lock

- **User turns the mode off:** stop the supervisor, close native data sessions
  and their Reticulum interfaces, remove the notification, release locks, and
  return Python to `foreground`. The visible UI may then use the old WebView
  path if the user chooses.
- **Explicit Mesh Chat lock:** stop the service first, close native sessions,
  release locks, then `shutdown` Python and release the vault. Persist
  `enabled=false`. Unlock requires a fresh enabling action.
- **Profile deletion:** same as lock, plus preference erasure.
- **Service failure:** `onDestroy` closes native sessions and releases every
  lock in a `finally` path, then removes the notification if the service is not
  restarting.

### 9.5 Process death and restart

- Use `START_STICKY` only while the preference is enabled.
- On restart, post `startForeground` before initializing the native host or
  Python.
- Reinitialize native WebRTC and Python from the application context; load the
  enabled profiles; mark sessions `recovering`; run the supervisor.
- Never report `available` until a new DataChannel is open and its Reticulum
  interface is attached.
- If the key is unavailable, stop and report `locked`.
- `onTaskRemoved`: keep the service and notification while enabled; do not start
  an Activity.
- No `BOOT_COMPLETED` in v1.

### 9.6 State transition table

| From | Event | To | Side effects |
| --- | --- | --- | --- |
| `disabled` | User enables | `starting` | Persist preference; start FGS; native host init |
| `starting` | Foreground + host ready | `available` | Acquire locks; start supervisor |
| `starting` | Start/key/permission failure | `disabled` | Stop; release; error |
| `available` | Activity pause/stop | `available` | Report background; no detach |
| `available` | Doze / no network | `degraded` | Keep service; backoff; native ICE may fail |
| `degraded` | Network/Doze exit | `available`/`recovering` | ICE restart or new session |
| `available` | Native DataChannel fails | `recovering` | Close old session; supervisor negotiates |
| `recovering` | New DataChannel opens | `available` | Attach interface; status |
| `recovering` | No mailbox/profile | `manual_required` | No background peer |
| `available`/`degraded` | Explicit lock | `locked` | Stop service; close all; shutdown |
| `available`/`degraded` | User disables | `stopping` → `disabled` | Close native sessions; release |
| Any | Process death | `recovering` on restart | New sessions only |

## 10. Android platform contract

### 10.1 Foreground-service type

| Type | Fit | Decision |
| --- | --- | --- |
| `remoteMessaging` | Continuing a user's messaging across devices/background | **Primary candidate**, subject to Play review |
| `specialUse` | General escape hatch with manifest property and Play declaration | **Fallback** if `remoteMessaging` is rejected |
| `dataSync` | Android 15 time limit (six hours in a 24-hour window) | Rejected |
| `connectedDevice` | Requires a companion device relationship | Rejected |
| `phoneCall`/`microphone`/`camera` | Calls only | `CallService` remains separate |

See
[Foreground service types are required](https://developer.android.com/about/versions/14/changes/fgs-types-required)
and [Foreground service timeouts](https://developer.android.com/develop/background-work/services/fgs/timeout).
The final choice is a Play-policy decision, not only an engineering one.

### 10.2 Manifest

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_REMOTE_MESSAGING" />
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

<service
    android:name="com.meshchat.runtime.MeshAvailabilityService"
    android:exported="false"
    android:foregroundServiceType="remoteMessaging"
    android:stopWithTask="false" />
```

- `POST_NOTIFICATIONS` already exists.
- No `RECEIVE_BOOT_COMPLETED`, no `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` in v1.
- `CHANGE_WIFI_STATE` only if the chosen Wi-Fi lock requires it; confirm.
- No intent filter; service is internal.
- Native WebRTC may add its own permissions? Data-only WebRTC needs INTERNET
  only; do not add camera/microphone for this path.

### 10.3 Start restrictions

Start only from a visible Settings action. Android 12+ restricts background
foreground-service starts. No boot or broadcast start in v1. See
[Restrictions on starting a foreground service from the background](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

### 10.4 Notification

- Channel `mesh_chat_availability_v1`, importance `LOW`, no badge/sound/vibration.
- **“Mesh Chat is available”** / **“Keeping your conversations connected”**.
- No contact, workspace, message, destination, or preview text.
- Ongoing, silent, category `service`, lock-screen visibility `private`.
- **Stop** action disables the mode and stops the service.
- Tap opens `MainActivity` singleTask with no sensitive extra.
- If `POST_NOTIFICATIONS` is denied, do not claim the mode is available. Explain
  that Android requires a visible notification and offer Settings. API 24–32
  use the OS notification-enabled state instead of the runtime prompt.

### 10.5 Doze and battery optimization

- Foreground service does not prevent Doze. Report `degraded`.
- Do not use exact alarms as a keepalive.
- A later optional **Allow unrestricted battery use** flow may request
  `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, but only with explicit disclosure and
  Play review. It must be separate from the availability toggle.
- Do not fight Doze with restart loops.

### 10.6 OEM behavior

OEM killers may stop the service or restrict background networking. Report
`recovery_required`/`degraded`, link to OEM battery settings where detectable,
and never claim connectivity that is not observed.

## 11. Python and JavaScript interface changes

### 11.1 Host refactor

Move Activity-owned runtime pieces into `MeshRuntimeHost`:

- Python start/initialize and vault key retrieval;
- `pythonExecutor` and runtime state;
- notification channels and the 750 ms notification pump;
- multicast lock;
- native WebRTC host lifecycle;
- background availability state.

`MeshRuntimePlugin` keeps Activity-bound operations: permission prompts, file
picker, theme, call audio, and Activity callbacks. The host uses
`applicationContext`.

### 11.2 New commands

Native-only commands (not renderer-allowlisted unless explicitly needed):

- `set_background_availability(enabled)`;
- `background_status()`;
- `mobile_network_changed(available, transport)`;
- `native_webrtc_create_offer(session_id, ice, channels)`;
- `native_webrtc_accept_offer(session_id, sdp, ice, channels)`;
- `native_webrtc_apply_answer(session_id, sdp)`;
- `native_webrtc_restart_ice(session_id)`;
- `native_webrtc_control_send(session_id, label, text)`;
- `native_webrtc_close(session_id)`;
- `native_webrtc_diagnostics(session_id)`;
- `native_webrtc_open(session_id)` — native → Python callback; Python attaches
  the interface and returns the bridge ID;
- `native_webrtc_packet(session_id, data)` — native → Python callback;
- `native_webrtc_state(session_id, state)` — native → Python callback.

Python-to-native outbound packet delivery must be direct (Chaquopy Java call or
a registered native sink). Do not route it through the JS event queue.

### 11.3 Python native bridge

Add `NativeWebRtcBridge` that:

- maps native session IDs to `WebRTCInterface` bridge IDs;
- creates the interface with a send callback that calls native `send`;
- registers the interface with `RNS.Transport` exactly as `webrtc_attach` does;
- reannounces at 0, 2, and 6 seconds;
- handles inbound packets/state;
- detaches and closes on failure/stop/lock;
- exposes redacted diagnostics.

The existing `webrtc_attach`/`webrtc_packet`/`webrtc_detach` commands remain for
desktop and the legacy WebView path. Do not make the renderer the packet pump
for native sessions.

### 11.4 Renderer changes

- `webrtc-session.ts` must represent native sessions without a
  `RTCPeerConnection`/`RTCDataChannel` requirement. Add a discriminated union:
  `{ kind: "webview", pc, channel } | { kind: "native", sessionId }`.
- Renderer unmount must not close native sessions owned by the background
  supervisor. The current `Messenger` cleanup path closes every WebRTC session;
  split it into `closeWebViewSessions()` and `leaveNativeSessionsToService()`.
  Only explicit mode disable, lock, profile deletion, or service stop closes
  native sessions.
- The connection status UI reads native session status from the snapshot.
- The manual onboarding dialog calls native create/accept commands on Android
  and the existing browser APIs on desktop. Keep the signed document flow.
- The reconnect coordinator must not run for profiles owned by the background
  supervisor. Add a clear ownership flag.
- Diagnostics use native stats for native sessions.

## 12. Direct-native and Reticulum

- Reticulum/LXMF remain Python-owned; no process split in v1.
- Direct-native QUIC keeps the existing `mobile_direct` Rust pump. It depends on
  the Tauri runtime, so a service-only restart may not restore it; report that
  path as `recovery_required` while WebRTC/Reticulum recover.
- `mobile_direct::stop` only on lock/disable/shutdown, never on Activity pause.
- On network change, call `reconcile_remote_profiles(force_dns=True)` and wake
  direct recovery.
- Do not add synthetic Reticulum pings. Direct QUIC already uses a 15-second
  idle timeout and a 5-second keepalive
  ([direct-fabric lib.rs](../experiments/direct-fabric/src/lib.rs#L25-L30),
  [lib.rs](../experiments/direct-fabric/src/lib.rs#L170-L182)). The wake lock
  exists so native timers can run.

## 13. Security and threat-model delta

- The vault key and decrypted records stay in memory while the screen is
  locked. Today the explicit Mesh Chat lock releases them; this mode extends
  that window. Disclose it.
- The Keystore key is not user-authentication-bound today
  ([MeshRuntimePlugin.kt](../plugins/tauri-plugin-mesh-runtime/android/src/main/java/com/meshchat/runtime/MeshRuntimePlugin.kt#L166-L199)).
  Binding it to biometrics would break headless restart; do not do it silently.
- The service is not exported and has no intent filter. PendingIntents are
  immutable. The notification has no sensitive content.
- Native WebRTC expands the native attack surface: ICE/DTLS/SCTP parsing,
  TURN credentials, SDP handling, and native memory safety. Pin the SDK,
  verify its provenance, run the existing hostile-SDP tests, and keep the
  signed fingerprint check.
- TURN credentials are fetched fresh and not persisted; native host must clear
  them on close.
- No new listening sockets, relays, accounts, or telemetry.
- Explicit lock must close native peers, detach interfaces, close the network
  and vault, release all locks, and remove the notification.
- Add to [THREAT_MODEL.md](../THREAT_MODEL.md): screen-locked key exposure,
  native media/transport attack surface, notification/Task Manager visibility,
  service restart deception, and battery-exemption abuse.

## 14. UX

### 14.1 Setting

> **Stay available in the background**
> Keep WebRTC and Reticulum connections open while your screen is off. Shows an
> ongoing notification. Android may still pause networking in Doze, and some
> device makers stop background apps.

Status values: `Available`, `Waiting for network`, `Restricted by Android`,
`Reconnecting`, `Manual reconnect required`, `Locked`.

Actions: toggle, **Open battery settings** (informational), **Stop**.

### 14.2 First enable

Disclose:

- ongoing notification and generic text;
- battery use;
- Doze/process-death/OEM limits;
- “Locking Mesh Chat stops background availability”;
- WebRTC data channels stay open; audio/video calls still use the call service;
- no push service.

Default off. No pre-check.

### 14.3 Lock

The lock confirmation says keys will be released and availability stopped.
After unlock, the mode is off until enabled again.

### 14.4 Notification

Generic text only; **Stop**; tap opens app; no message/contact/preview.

## 15. Storage and state

Add a sealed device-local record `background_availability`:

```json
{
  "v": 1,
  "enabled": false,
  "mode": "native_webrtc",
  "enabled_at": 0,
  "disabled_at": 0,
  "last_state": "disabled",
  "last_reason": "user_disabled",
  "updated_at": 0
}
```

Rules:

- encrypted profile store; no canonical protocol bytes;
- deleted with profile;
- lock writes `enabled=false` before shutdown;
- service state is derived live, never trusted from the renderer;
- renderer snapshot exposes only `enabled`, `state`, `reason`, `doze`,
  `network`, `notification`, and counts; no peer IDs/destinations.

## 16. Failure and recovery

| Failure | Behavior | User-visible |
| --- | --- | --- |
| `startForeground` throws | Stop; release; persist disabled | “Android did not allow background availability” |
| Notification permission denied | Do not start | “A visible notification is required” |
| Native WebRTC SDK failed to load/16 KB | Stop; disable native path | Stable error; no fallback to WebView claim |
| Python initialize fails | Stop; release | Stable error; no plaintext fallback |
| Network lost | `degraded`; native ICE may fail | “Waiting for network” |
| Doze | `degraded`; no busy retry | “Android is resting background apps” |
| DataChannel failed | `recovering`; close old; new session | “Reconnecting” |
| No mailbox/profile | `manual_required` | “Open Mesh Chat to reconnect” |
| Process killed | `recovering` on restart | “Reconnecting when possible” |
| Key unavailable | `locked` | “Unlock the device and reopen Mesh Chat” |
| OEM killer | Service may die without callback | Next launch reports gap |
| Storage full | Stop service; keep vault safe | “Storage is full” |
| Mode disabled during call | Do not stop `CallService` | Call continues |

## 17. Battery and performance

Native WebRTC adds continuous ICE/DTLS/SCTP timers and possible TURN traffic.

- **Wake lock:** `PARTIAL_WAKE_LOCK`, only while `available`/`degraded` with at
  least one native session or eligible path. Release on disable/lock/no session.
- **Wi-Fi lock:** only while on Wi-Fi with an active session; choose the least
  aggressive mode that passes measurement.
- **Multicast lock:** existing LAN discovery lock while availability is on.
- **Doze:** do not hold a wake lock against it; report degraded.
- **Native WebRTC:** configure ICE consent freshness and keepalives at upstream
  defaults; do not shorten them without measurement. Bound DataChannel buffered
  amount and inbound queues.
- **No synthetic mesh heartbeat.**
- **Provisional targets:** ≤ 3%/h with one active data session and no traffic;
  ≤ 1%/h with availability on but no sessions; no unbounded thread/queue growth
  over 24 hours.
- Measure with `dumpsys batterystats`, `dumpsys power`, `dumpsys wifi`,
  `dumpsys deviceidle`, Android Studio profiler, and TURN byte counters.

## 18. Testing and qualification

Local builds are not part of the workflow. GitHub Actions builds and verifies
artifacts; this spec assumes the existing
[release workflow](../.github/workflows/release.yml) and
[CI workflow](../.github/workflows/ci.yml).

### 18.1 Native WebRTC tests

- Offer/answer interop with the Windows WebView peer, both directions.
- DataChannel open, binary MTU, ordered delivery, backpressure, close.
- ICE relay-only TURN; direct/STUN; candidate gathering timeout.
- DTLS fingerprint matches signed document; hostile SDP rejected.
- 16 KB page-size load and `zipalign` verification.
- APK size and license notices.
- Native host survives Activity destroy; session stays open.
- Process restart: service recreates a session via mailbox.
- Network switch: ICE restart or new session; no duplicate peers.
- Diagnostics redaction.

### 18.2 Kotlin/JVM

- host initialize/close; channel specs; observer threads;
- startForeground type/notification/Stop action;
- wake/Wi-Fi/multicast acquire/release exactly once;
- service restart, task removal, `onDestroy` cleanup;
- notification permission denial;
- no sensitive notification extras.

### 18.3 Python

- `background_available` does not retire native WebRTC/direct sessions;
- `suspended` still retires when disabled;
- notification drain accepts the new state;
- native bridge attach/outbound/inbound/detach;
- background supervisor: consent, replay, glare, backoff, cancellation, stop on
  lock/disable/block;
- no duplicate peer for the same profile;
- process restart marks sessions lost and renegotiates;
- lock closes network/vault.

### 18.4 Frontend

- toggle/disclosure/status/stop/lock warning;
- native vs WebView session union types;
- no `webrtc_packet` subscription for native sessions;
- manual onboarding uses native commands on Android;
- diagnostics.

### 18.5 Physical matrix

At minimum one authorized Android 14+ and one Android 13 device, plus one OEM
skin:

- enable; see notification; establish a WebRTC data session; screen off 30 min;
  send/receive messages; notification; no WebView JS required;
- Activity destroy/task swipe; session stays open;
- force-stop/reboot; recovery behavior;
- Doze force-idle/exit;
- Wi-Fi ↔ cellular; ICE restart/new session;
- notification denied/allowed/revoked;
- lock/unlock;
- battery and memory;
- peer Windows on Wi-Fi and Android on cellular;
- calls separately (not claimed).

### 18.6 Security tests

- service not exported/startable by other UID;
- no key/message/destination in logs/notification;
- native host clears TURN creds on close;
- lock wipes keys/stops service;
- OOM/restart does not reopen vault without key;
- hostile SDP/ICE inputs bounded.

## 19. Rollout

| Phase | Work | Gate |
| --- | --- | --- |
| 0 | Spike native WebRTC SDK: 16 KB, size, data-channel interop, Activity destroy, FGS | Written evidence; SDK decision |
| 1 | `MeshRuntimeHost`, `MeshAvailabilityService`, notification/locks, `background_available` | Debug feature flag; CI green |
| 2 | Native WebRTC host for manual onboarding data sessions; Python native bridge | Android↔Windows data channel without WebView |
| 3 | Python background reconnect supervisor + service restart recovery | Mailbox reconnection while UI absent |
| 4 | Native ICE restart/network-change hardening; diagnostics; battery | Physical matrix pass |
| 5 | Optional `:mesh_core` split, boot flow, media migration | Only if metrics justify |

Sizes: Phase 2 is **XL**; Phase 3 is **L/XL**. This is not a small toggle.

## 20. Acceptance criteria

1. With the mode enabled, screen off, and no Dozing, every established native
   WebRTC DataChannel (up to the supported bound) remains open for at least 30
   minutes; Python continues to send/receive Reticulum packets through each;
   messages and notifications work without any WebView JavaScript.
2. Destroying the Activity does not close the native session; returning to the
   app shows the same native session as connected.
3. The native session survives a task swipe while the process lives.
4. After process death, the service restarts, posts the notification first, and
   either renegotiates a new session (if mailbox/consent) or reports
   `manual_required`; it never claims the old DTLS session survived.
5. Doze produces `degraded` and recovery on exit, not a crash or false claim.
6. Explicit lock closes native peers, detaches interfaces, stops the service,
   clears the vault, and removes the notification.
7. No wake/Wi-Fi/multicast lock leaks after disable/lock/failure/destroy.
8. 16 KB page devices load the native library; the release APK size and notices
   are updated.
9. All tests/builds run in GitHub Actions; the artifact is verified there.
10. The UI claims only what is measured: WebRTC data channels maintained while
    available; calls remain on the call service; Doze/OEM/process-death limits
    are disclosed.

## 21. Open questions

1. Native WebRTC SDK: does the chosen AAR pass 16 KB alignment and the size
   budget on arm64?
2. Can the Windows WebView peer interoperate with native Android SDP in both
   offer directions, including relay-only TURN?
3. Should the Python background supervisor replace the JS reconnect coordinator
   entirely, or only own profiles while availability is on?
4. Are audio/video calls expected to stay alive too, or is the requirement
   limited to data connections? Media migration is a separate project.
5. FGS type: `remoteMessaging` or `specialUse` for Play review?
6. Battery exemption: optional future flow, or never?
7. Separate `:mesh_core` process: worth the cost after metrics?
8. Boot autostart: ever, and how to handle Keystore availability?
9. Direct-native recovery without Tauri: move the Rust pump, or accept
   `recovery_required`?
10. Notification wording and whether the availability and call notifications
    should merge.

## 22. References

Repository:

- [ADR 0014: Mobile lifecycle and local notifications](adr/0014-mobile-lifecycle-and-notifications.md)
- [AUTO_RECONNECT_SPEC.md](AUTO_RECONNECT_SPEC.md)
- [ANDROID_PARITY.md](ANDROID_PARITY.md)
- [WEBRTC_ADAPTER_SPEC.md](WEBRTC_ADAPTER_SPEC.md)
- [WEBRTC_MANUAL_ANSWER_ROOT_CAUSE.md](WEBRTC_MANUAL_ANSWER_ROOT_CAUSE.md)
- [THREAT_MODEL.md](../THREAT_MODEL.md)
- [PHYSICAL_QA_SCENARIOS.md](PHYSICAL_QA_SCENARIOS.md)
- [MeshRuntimePlugin.kt](../plugins/tauri-plugin-mesh-runtime/android/src/main/java/com/meshchat/runtime/MeshRuntimePlugin.kt)
- [CallService.kt](../plugins/tauri-plugin-mesh-runtime/android/src/main/java/com/meshchat/runtime/CallService.kt)
- [mobile_bridge.py](../service/src/mesh_chat/mobile_bridge.py)
- [network.py](../service/src/mesh_chat/network.py)
- [webrtc_interface.py](../service/src/mesh_chat/webrtc_interface.py)
- [reconnect_service.py](../service/src/mesh_chat/reconnect_service.py)
- [webrtc_onboarding.ts](../src/webrtc-onboarding.ts)
- [webrtc-peer.ts](../src/webrtc-peer.ts)
- [mobile_direct.rs](../src-tauri/src/mobile_direct.rs)

Android/native WebRTC:

- [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [Foreground service types are required](https://developer.android.com/about/versions/14/changes/fgs-types-required)
- [Foreground service timeouts](https://developer.android.com/develop/background-work/services/fgs/timeout)
- [Restrictions on starting a foreground service from the background](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- [Optimize for Doze and App Standby](https://developer.android.com/training/monitoring-device-state/doze-standby)
- [Google Play foreground service requirements](https://support.google.com/googleplay/android-developer/answer/13392821)
- [io.github.webrtc-sdk:android](https://github.com/webrtc-sdk/android)
- [WebRTC 16 KB page discussion](https://groups.google.com/g/discuss-webrtc/c/N2-hwMXdsv8)
