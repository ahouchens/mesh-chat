# Native Windows WebRTC messaging handoff

Implement browser-free Windows WebRTC **messaging** for Mesh Chat using the Uncle
Bob skill. Complete integration, packaging and available automated qualification,
not just a prototype. Continue on the long-lived refactor branch.

## Explicit UI and media preservation requirement

**Retain WebView2 for the existing Tauri frontend and for audio/video calls in
the UI. This task does not replace or remove that implementation.**

| Responsibility | Intended implementation after this work |
| --- | --- |
| Durable messaging and its WebRTC DataChannels | Native Windows WebRTC adapter, independent of WebView2 |
| Audio/video calls | Existing WebView2 media implementation |
| Application UI | Existing Tauri/WebView2 frontend |
| Direct/QUIC connectivity | Existing native implementation |

Only the superseded **messaging-specific hidden WebView transport host** and
code used exclusively by that host may be removed after native qualification
and rollback requirements are satisfied. Before deleting any module, command,
event, dependency or capability, inspect all callers and preserve everything
still needed by the UI, calls, onboarding or shared signaling.

Do not remove WebView2 from the desktop app's packaging, globally disable browser
WebRTC, migrate microphone/camera capture into the native messaging adapter,
change call signaling semantics, or make native messaging cleanup close media
PeerConnections. Preserve shared SDP/signaling utilities and permission handling.

Browser-free acceptance applies to the **standalone messaging runtime and its
owned process tree**. The GUI application's WebView2 processes are expected.
Do not treat their presence as a headless-messaging failure when testing the GUI,
or claim the whole desktop application is WebView-free.

Mandatory coexistence regressions must prove:

- Starting, answering, ending, failing and repeatedly reconnecting audio/video
  calls leave native messaging and authenticated receipts usable.
- Native messaging reconnect, adapter replacement and service recovery do not
  tear down an active UI call or release its microphone/camera tracks.
- Closing pairing dialogs or retiring onboarding resources cannot dispose of a
  call or a transferred messaging carrier owned by another operation.
- Messaging-specific Stop/cancellation and media-call hangup clean up only their
  owned resources. Explicit app-wide shutdown/lock follows existing product
  semantics; do not redefine it to preserve calls that should be stopped.
- UI navigation and window lifecycle continue to behave as documented. Closing
  the last window must not accidentally change the runtime's ownership policy.

Keep the existing media test corpus and add tests at the actual shared lifecycle
boundaries. Emulator/CI media results are not physical microphone/camera proof.

## Repository and starting context

- Repository: https://github.com/ahouchens/mesh-chat
- Long-lived branch: `codex/mesh-chat-core-refactor`
- Draft PR: https://github.com/ahouchens/mesh-chat/pull/35
- Integration workspace:
  `C:\Users\webte\.codex\worktrees\mesh-core-refactor-integration\Mesh P2P connected chat`
- Original checkout:
  `C:\Users\webte\Documents\ChatGPT\Mesh P2P connected chat`
- Last inspected implementation/documentation baseline before this handoff:
  `25c267a77accd5cadc9bdc54a41fbac4de9b1d39`. Fetch and inspect the actual current
  tip; this identifier is historical context, not a command to reset the checkout.

The integration worktree used detached HEAD with commits pushed to the long-lived
branch. Inspect `git status` and worktree registrations before changing branches.
Preserve unrelated changes in the original checkout. Do not reset, clean, stash
or overwrite them to prepare this task.

Read `C:\Users\webte\.codex\skills\uncle-bob\SKILL.md`, applicable `AGENTS.md`
files, and the following repository documents:

- `docs/Mesh_Chat_Connection_Runtime_Spec.md`
- `docs/Mesh_Chat_Connection_Runtime_Roadmap.md`
- `docs/Mesh_Chat_Connection_Runtime_Acceptance.md`
- `docs/Mesh_Chat_Connection_Qualification_Ledger.md`
- `docs/architecture/mesh-chat-core.png`

The user has emulation and GitHub CI only, without physical paired devices or an
isolated physical network. Complete feasible automated work and leave physical
acceptance explicitly unqualified. Local disk space has been exhausted by native
builds/emulation before; inspect capacity and prefer CI for heavy toolchains.

Windows and Linux already have native Direct/QUIC transport and headless component
qualification. The missing production adapter here is specifically **Windows
WebRTC DataChannels without a WebView**. The aiortc work under
`experiments/webrtc-call` is a prototype, not integrated production messaging.

Known baseline evidence: 1,768 required local tests passed with zero skips at
`d2590ff`; 21 Kotlin JVM tests passed. Run
[41559732693](https://github.com/ahouchens/mesh-chat/actions/runs/41559732693)
passed completely for `461c2e9`, including 34 Android cases. Check the final result
of [41562494353](https://github.com/ahouchens/mesh-chat/actions/runs/41562494353)
and any newer runs before making current-source qualification claims.

## Implementation sequence

### 1. Establish the baseline and acceptance checklist

Fetch the branch, reconcile the implementation and read the specification before
editing. Map this task to applicable invariants and scenarios. Separate native
adapter conformance, protected-service messaging, packaged interoperability,
real-clock recovery, media coexistence and physical evidence.

Inspect the existing UI/media call graph as well as messaging. Record which
modules and process-lifecycle operations are shared so removal work has a clear
boundary. Do not assume a module named WebRTC belongs exclusively to messaging.

Exit: verified baseline, ownership map and explicit native-default promotion gates.

### 2. Select a native WebRTC library through a bounded spike

Evaluate a small candidate set: start with libdatachannel and Google's native
libwebrtc; consider webrtc-rs where it provides a demonstrated integration benefit.
Check current primary documentation and pin selected versions. References:

- https://github.com/paullouisageneau/libdatachannel
- https://webrtc.github.io/webrtc-org/native-code/development/
- https://github.com/webrtc-rs/webrtc

Prove Windows offerer/answerer behavior, reliable ordered binary/text channels,
SDP/fingerprint compatibility, bounded cancellation and required ICE behavior.
Explicitly investigate TURN UDP/TCP/TLS, forced relay and UDP-denied operation;
do not infer support from a library's generic WebRTC claim.

Compare build reproducibility, dependency/package size, callback/disposal
semantics, diagnostics and redistribution obligations. Record an architecture
decision and build one production adapter after selection. Disable unused native
media features where practical; existing UI media remains in WebView2.

Exit: a Windows compatibility spike and an evidence-backed dependency decision.

### 3. Define process ownership and private integration

Preserve the dependency direction: Python supervisor -> private mechanism port ->
native WebRTC host. Keep consent, peer selection, signaling policy, retry policy,
durable state and messaging readiness in the protected service.

Prefer a reusable transport library and small standalone host executable using
the same production code as the desktop integration. The standalone messaging
path must not initialize React, a Tauri window or WebView2. The GUI continues to
initialize WebView2 for its frontend and calls.

Document the owner, launcher, authenticated private IPC, shutdown and crash
behavior. Preserve supported carrier survival across Python service restart;
native-host death destroys its connections and requires fresh permitted
negotiation. Clients attach to one app-owned runtime rather than creating
competing runtimes. Never persist live DTLS state as recovery evidence.

Exit: explicit ownership, security, restart and media-isolation contracts.

### 4. Implement the existing private transport contract

Inspect these integration points before introducing new abstractions:

- `src/desktop-transport.ts` and `src/desktop-transport-protocol.ts`
- `src-tauri/src/desktop_transport.rs` and `desktop_transport_broker.rs`
- `service/src/mesh_chat/desktop_transport_host.py`
- `service/src/mesh_chat/native_webrtc_service.py`
- `service/src/mesh_chat/native_carrier_evidence.py`
- `service/src/mesh_chat/connection/composition.py`

Implement equivalent `createOffer`, `acceptOffer`, `applyAnswer`, `inspect`,
`inventory`, `activate`, `close`, `send`, `sendControl` and `reset` operations.
Preserve `mesh-reticulum`, `meshchat-reconnect` and `mesh-onboarding` channel
purposes. Keep the adapter independent of UI media sessions.

Preserve current bounds unless a separately justified contract change is needed:
256 KiB private frames, 1,064-byte packet payloads, bounded control messages and
bounded resources/operations. Maintain SDP normalization/digests, adapter epochs,
request correlation, replay rejection, held activation and exact resource identity.
Inventory observations support service validation; they do not grant authority.

Exit: shared conformance tests for WebView2 and native messaging implementations.

### 5. Implement bounded execution, cancellation and disposal

Give allocations, callbacks, packet/control queues and operations explicit count
and byte limits. Keep shutdown, revocation and cancellation responsive during
saturation. A timed-out native call retains its capacity until it actually ends;
late allocations remain accounted for until disposed of.

Fence callbacks by adapter epoch and allocation identity. Old cleanup cannot
close a replacement or a media session. Handle reentrancy, callbacks during close,
blocked operations, malformed IPC and host/pipe failure. Keep callbacks small and
deliver observations through bounded queues.

Add behavioral regression tests before fixes. Extend the 294-case production
reducer phase-cancellation corpus with native-boundary evidence; reducer tests
alone do not prove actual native resource disposal.

Exit: bounded resources and correct ownership under interruption and failure.

### 6. Integrate messaging while preserving UI calls

Add a temporary backend selector through trusted host configuration. Retain the
existing messaging host as a controlled rollback option until qualification.
Run only one messaging backend and one policy owner per runtime; do not silently
switch transports during an active session.

Connect packets to the authorized Reticulum bridge. Messaging readiness requires
current authority, bridge attachment, routing and applicable ratchet readiness.
Exercise personal/workspace pairing, approval, manual modes, reconnect control
and approved onboarding-carrier transfer.

Preserve signed documents, consent defaults, relay/privacy permissions, encrypted
persistence, logical message IDs and authenticated receipts. Preserve existing
WebView2 audio/video behavior, devices, permissions and call signaling. Introduce
separate ownership where a shared cleanup operation currently spans messaging and
calls, without creating another peer retry loop.

Exit: real service peers exchange durable messages/receipts in both roles, with
the mandatory UI/media coexistence regressions passing.

### 7. Qualify actual interoperability

Cover native Windows <-> native Windows, native Windows <-> existing WebView2,
and native Windows <-> Android native WebRTC in both offer roles. Begin with
transport conformance, then run fresh identities, explicit pairing/approval,
messages, receipts, cancellation, revocation, restart and recovery.

Distinguish an actual Windows executable communicating with an Android emulator
from a Linux build or Chromium fixture. Record topology and exact artifact
identities. Design a viable CI topology for the actual pair; if unavailable,
continue other implementation and record that precise qualification gap.

Exit: honest platform-pair evidence for each claimed workflow, including calls
coexisting with native messaging in the desktop app.

### 8. Exercise faults, real-clock budgets and receipt soak

Reuse production policy, adapters and domain services. Keep fault controls in
test infrastructure and out of shipping artifacts. Cover partitions, packet
loss/delay/reordering/duplication, signaling outage, bridge/carrier loss, crashes,
delayed allocation, saturation and cancellation at every handshake phase.

Prove selected direct/relay paths with negative controls. Use packet impairment
for UDP; a TCP signaling proxy alone cannot qualify WebRTC packet impairment.
Measure the specification's distinct budgets:

- Healthy-carrier bridge repair: messaging-ready within 20 seconds.
- Recovery after a 30-second partition: messaging-ready within 240 seconds of
  fault removal under the specified 150 ms RTT impairment profile.
- Queued authenticated application receipts: within 30 seconds after readiness.

Run 100 iterations across both roles with real messages, receipts, periodic cold
starts, no duplicate visible messages and no growth in owned resources or queued
work after quiescence. Include repeated UI calls and prove their teardown does
not damage messaging; messaging recovery must likewise preserve active calls.

Exit: exact-transport fault/soak evidence, measured budgets and resource accounting.

### 9. Package and enforce exact-artifact CI qualification

Package the native messaging host and dependencies. In a clean Windows environment,
prove the standalone runtime can message without launching or requiring WebView2
or importing the source checkout. Inspect its owned process tree/dependencies.

Separately prove that the desktop GUI package still includes and uses WebView2
for the frontend and audio/video calls. Preserve installation/upgrade behavior,
device permissions, notices and shared media dependencies.

Validate DLL discovery, supported architectures, clean installation, shutdown,
upgrade/data preservation and redistribution notices. Exclude fixture identities,
credentials and fault controls from shipping packages.

Extend qualification/release aggregators to bind source commit/tree, binaries and
dependencies, build configuration, runtime/adapter versions, scenarios, counts
and cleanup results. Missing, stale, skipped, canceled or mismatched required
evidence fails. Keep native WebRTC, WebView2, Direct/QUIC, emulator and physical
evidence distinct. Retain the existing UI/media CI coverage.

Exit: packaged native messaging and desktop UI/media artifacts with correctly
scoped, source-bound qualification reports.

### 10. Finish messaging migration without removing UI media

Promote native messaging only after its conformance, service integration,
compatibility, recovery, coexistence and packaging gates pass.

Remove only superseded messaging-specific WebView2 hosting and wrappers after
rollback requirements permit. Perform a dependency/caller audit before each
deletion. **Retain Tauri/WebView2 UI hosting, all audio/video call functionality,
media permissions and dependencies, shared signaling/SDP utilities still in use,
and existing native Direct/QUIC connectivity.**

Update the architecture, roadmap, acceptance matrix, qualification ledger and
draft PR. Keep physical acceptance and unrelated M5 work explicit. Native Windows
messaging success does not establish that the entire refactor or desktop app is
WebView-free, nor that every M4/M5 criterion has passed.

Exit: the qualified native messaging path is integrated, remaining legacy
messaging code is deliberate, and UI/audio/video behavior remains intact.

## Working and completion rules

Use small reviewable commits on the existing long-lived feature branch. Apply
the Uncle Bob skill: inward dependencies, narrow mechanism interfaces, explicit
ownership, readable functions and behavioral regression tests.

Run the required connection suite, strict model/reducer typing, affected native
tests, UI/media tests and packaged qualification. Proceed through routine choices
autonomously and report concrete outcomes and remaining work at checkpoints.
Do not tag, publish or merge a release as part of this task.

Finish with native Windows WebRTC messaging integrated and packaged, all available
automated gates completed, WebView2 UI/audio/video preserved, and unavailable
acceptance criteria explicitly identified. Supported SDK publication, the complete
UI facade migration and physical-device release acceptance remain separate work.
