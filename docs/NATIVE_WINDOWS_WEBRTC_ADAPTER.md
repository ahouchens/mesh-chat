# Native Windows WebRTC messaging adapter

Status: implemented component, enabled by default for Windows messaging builds;
full cross-platform, media-coexistence and physical qualification remains open.

## Decision

The Windows messaging data channel runs inside the protected Python service using
`aiortc` 1.13 with its pinned `av`/`aioice`/`pylibsrtp` wheels. It is browser-free:
the adapter creates `RTCPeerConnection` objects and data channels directly and
never initializes Tauri, React or WebView2.

A bounded DataChannel spike exercised all three channel purposes, binary packets,
control text, DTLS fingerprints and host candidates. The C/C++ candidates
(`libdatachannel`, Google libwebrtc) were not built here because they require a
large additional native toolchain and the workspace is disk-constrained;
`webrtc-rs` would duplicate an existing, already-tested Python-adjacent stack.
The aiortc prototype under `experiments/webrtc-call` supplied the initial
compatibility evidence; this adapter is the production integration behind the
existing host contract.

Only data channels are created. The UI frontend and audio/video call
implementation remain on WebView2. Closing or reconnecting messaging cannot close
a call peer connection or release a call track.

## Ownership and integration

- `service/src/mesh_chat/native_windows_webrtc.py` owns one asyncio loop thread,
  bounded sessions (16), bounded packet/control sizes, adapter callbacks and
  exact-session disposal.
- `WindowsNativeWebRTCHost` implements the same contract as the Android host:
  `createOffer`, `acceptOffer`, `applyAnswer`, `send`, `sendControl`, `stats`,
  `activate`, `close`, `shutdown`.
- `service/src/mesh_chat/__main__.py` accepts `--native-webrtc` only as a
  trusted-launcher mode. Initialization JSON cannot select it.
- Windows builds launch the sidecar with `--native-webrtc` by default. The
  `experimental-shared-webview` feature remains a rollback path for the old
  hidden WebView messaging host. WebView2 remains required and packaged for the
  UI and media calls in both modes.
- Events are delivered through the service's existing bounded native-event queue:
  `signaling`, `gathering`, `ice`, `channel`, `open`, `message`, `control`,
  `closed` and `overflow`.

## Bounds and cleanup

- 16 concurrent sessions; 1,064-byte binary packets; 65,536-character control
  messages; 256 KiB private frames remain unchanged.
- Methods run on the adapter loop; synchronous callers receive JSON strings or
  booleans and cannot send on a foreign thread (which would silently lose SCTP
  flush scheduling).
- The SDP carries exactly one `sha-256` fingerprint; aiortc's additional
  sha-384/sha-512 attributes are removed before signing.
- Relay-only configuration filters non-relay candidates from the local SDP.
- Close removes the exact session, closes its channels and peer connection, and
  emits `closed`; it never walks UI/media sessions.

## Evidence

- `service/tests/connection/test_native_windows_webrtc.py`: real aiortc pair,
  binary packets, onboarding/reconnect channels, control text, stats, exact
  close and session bounds.
- `service/tests/test_native_webrtc_runtime.py`: the protected service accepts a
  real native SDP, and closing one native bridge leaves an unrelated call bridge
  attached.
- `src/webrtc-session.test.ts`: closing a messaging session closes its peer
  connection but never calls `stop()` on a media-call track.
- `scripts/check_native_windows_messaging_soak.py`: 100 packaged two-sidecar
  offer/answer/open/control/close cycles with three cold starts, enforced 20 s
  open and 30 s control budgets, and closed-session absence checks. Local run:
  max open 385 ms, max control 406 ms. CI run 41626323911: max open 716 ms,
  max control 1,230 ms, no WebView process. This is transport lifecycle
  evidence, not durable message/receipt soak.
- `service/tests/connection/test_native_windows_delivery.py`: two independent
  Reticulum service processes exchange a native offer/answer, attach the
  authenticated bridge, create and approve a contact, deliver durable messages
  plus application receipts in both directions, then exchange a 100-message
  alternating receipt soak with exactly one inbound copy per logical ID. This
  uses the legacy bridge policy, not the shared supervisor. Additional tests
  prove queued-message recovery after a bridge replacement, duplicate-packet
  deduplication and bounded recovery after five- and thirty-second native packet
  partitions; the thirty-second case recovered inside the 240-second budget. A
  full peer-process restart preserves the profile identity, sends a message
  queued while the process was offline and receives its authenticated receipt
  over the replacement native session.
- `scripts/check_native_windows_messaging.py`: two packaged sidecars exchange a
  real native offer/answer, open the data channel, send a control message and
  report no WebView process in their owned process trees.

## Remaining qualification gaps

- Durable messages and receipts are proven with two real native hosts under the
  legacy bridge policy. Supervisor-owned native promotion, cancellation and
  restart during that flow remain unqualified.
- Native Windows to Android and native Windows to the legacy WebView transport
  interop is not executed here.
- TURN UDP/TCP/TLS, forced-relay paths and UDP-denied operation are not exercised;
  only host-candidate gathering is proven.
- GUI-level audio/video coexistence, real microphone/camera tracks, physical
  call quality and physical-device acceptance remain unqualified. Emulator and
  simulated media results must not be described as physical evidence.
- Fault matrices, real-clock budgets, 100-iteration receipt soak and the removal
  of the rollback host remain open.
