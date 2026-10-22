# Android feature parity

The 2026-10-16 direct-connectivity increment shares signed workspace-join
receipts and evidence-based UI between desktop and Android. Restart retains the
exact join, verified receipt and interrupted route-setup intent. It adds no
background execution, push service or notification-delivery guarantee.

Phase 2 embeds Quinn in the native mobile plugin with private bounded IPC. Its
bootstrap engine uses a non-exported Android service in a separate Python process;
the renderer shares the version-2 Offer/Answer/Ready email/file flow with desktop.
Process-boundary packages passed at `acdd868` in
[run 39077271626](https://github.com/ahouchens/mesh-chat/actions/runs/39077271626).
The fully integrated flow is tracked in the
[Phase 2 evidence record](DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md).
Native socket binding on real networks, Doze/resume, physical QUIC/LXMF traffic,
battery measurements and Windows↔Android execution remain unqualified. Package
compilation and desktop topology tests are not Android device evidence. See
[ADR 0018](adr/0018-authenticated-direct-underlay.md).

This document compares the Android client with the Windows desktop 0.9.5
implementation. It is a source-and-evidence audit, not a claim that shared code
automatically behaves the same on a phone. The Android client shares the React
renderer, Python messaging core, protocol, encrypted record model, and renderer
command allowlist with desktop, while its lifecycle, storage key, notifications,
camera, deep links, and packaging are native Android integrations.

As of 0.9.5, Android shares the shipped renderer/service feature set, including
1:1 WebRTC calls and automatic reconnect. It is **not full parity**: Android
cannot complete an I2P join because it has no bundled/managed router; background
execution is intentionally unavailable; personal/group per-conversation
notification preferences and generic inbound `ACTION_SEND` are gaps; physical
validation and accessibility remain incomplete; and the published 0.9.2 APK is
debug-signed, not a production upgrade identity.

Status labels are deliberately strict:

1. **Parity confirmed** — the relevant behavior was exercised on both sides or
   the platform-independent boundary has direct, current automated evidence.
2. **Implemented but unverified on hardware** — the source and automated tests
   cover the Android path, but no current physical-device result exists.
3. **Partial** — a useful subset exists, with a named gap.
4. **Missing** — no adequate Android implementation or evidence exists.
5. **Intentionally different** — Android cannot or should not mirror desktop;
   the justification is recorded.

## Matrix

| Capability | Status | Android evidence and remaining gap |
| --- | ---: | --- |
| Personal direct chat, receipts, retries, drafts, deletion, and reactions | 2 | Shared service/UI and service, renderer, direct-LAN, and packaged-sidecar regressions cover the behavior. The embedded Android runtime uses the same command boundary. A physical Android↔Windows send/receive/retry/relaunch run is still required. |
| Contacts: approve, decline, rename, verify, block, unblock, delete, and search | 2 | Shared service and renderer regressions cover authorization and local erasure. Android Back and compact layout paths are automated. No current TalkBack or physical touch-flow result exists. |
| Personal invitations: create, paste, QR, file, approve, decline, expiry, and retry | 2 | Canonical invitation validation remains in Python. Shared import classification routes each document family to its own parser, while Android uses a native unfiltered document picker followed by bounded extension, UTF-8, and shape validation. Camera permission, Files-provider variation, and end-to-end approval remain unverified on hardware. |
| Participant-hosted Internet invitations | 2 | Desktop and Android share the explicit-prepare v3 flow, sanitized Connection Doctor, actual-default-route selection, PCP → UPnP → NAT-PMP mapping, native public IPv4/IPv6 candidates, IGD2 IPv6 pinholes, manual forwarding, renewal/invalidation, safe recipient candidate outcomes, and prepared-versus-authenticated state. Android uses the same Python service and renderer command allowlist. Real carrier, OEM firewall, background suspension, router-protocol, Windows-firewall, and cross-network reachability remain hardware gates. No rendezvous or external reachability-probe service is used. |
| I2P relay | 3 | Android has the opt-in I2P settings, access-point list, and consent UI, but no bundled or managed `i2pd`/SAM router, so it cannot complete an I2P join as of 0.9.2. Desktop bundles and manages `i2pd`. Physical Android I2P behavior is unverified, and the settings copy should not imply I2P works without a router. |
| Email-assisted role reversal and reconnect updates | 2 | Shared service/UI implement signed v4 invitations with optional inviter candidates, challenge-bound single-use signed callback replies, and audience/identity/scope/generation-bound reconnect updates. Android native ingress accepts the same bounded text, deep-link, `.meshchat-connect`, and `.meshchat-route` forms and delegates authority checks to the shared service. Reply import cannot approve contacts or workspace membership. A physical Windows-on-home-Wi-Fi ↔ Android-on-cellular role-reversal, process-death, expiry, stale-update, and membership-removal run remains required. |
| Remote Connection Profiles and consent | 2 | Desktop and Android use the same canonical Python records, encrypted vault, four-profile/two-endpoint bounds, DNS policy, scope accounting, retry state, and service commands. Preview is network-free and the outbound TCP interface runs in the embedded native service. Physical DNS-change, Wi-Fi/cellular handoff, suspension, and process-death evidence remains open. |
| 1:1 WebRTC calls | 2 | Shared renderer `RTCPeerConnection`, signed call documents, and the native media-permission bridge. Call SDP/candidates are stored by default and can be kept memory-only via `store_call_signaling`. Physical Android call audio/video, NAT/TURN, route changes, and lock/foreground behavior remain open. |
| Automatic reconnect (WebRTC) | 2 | Shared renderer coordinator, Python reconnect profiles, pair-token mailbox, and the per-contact consent/status UI. Reconnect runs only while the app is open and unlocked. Physical restart, NAT/TURN, process-death, and battery/backoff behavior remain open. |
| Remote personal invitation, approval, DM, and receipt | 2 | `MESHCHAT2`, deep-link/file bounds, privacy disclosure, explicit consent, isolated outbound-only Reticulum topology, approval, message, and authenticated application receipt passed shared/native/source automation. A physical desktop-on-Wi-Fi ↔ Android-on-cellular run is still required. |
| Remote workspace invitation, owner approval, channels, and workspace DMs | 2 | `MESHWORKSPACE2` wraps the unchanged single-use invitation; workspace-only scope, unknown-source join checks, owner approval, admitting manifest, channel message, and participant-only workspace DM passed the real isolated topology. Physical Android owner/joiner, removal, revocation, and expiry runs remain open. |
| Optional LXMF propagation | 3 | Recommendation and transport approval are separate, allowlisting is bounded, automatic peering stays off, ratchets remain mandatory, and startup/foreground/network-recovery retrieval is implemented. A real store-while-recipient-offline and later Android retrieval run has not yet been completed. |
| Private groups | 2 | Signed membership epochs, fan-out, receipts, retries, removal/leave/close, reactions, and renderer flows have automated coverage. Physical 3/5/8-device Android runs remain open. |
| Announcement channels | 2 | Owner/admin posting policy and authorization are shared and automated. This increment adds the distinct native `announcement_message` notification category. Physical notification and multi-device behavior remain open. |
| Workspace creation/join/switching and public/private channels | 2 | Shared canonical service and UI have extensive source tests, bounded pages, signed controls, and direct-LAN evidence. Workspace text pasted into the generic invite surface now routes directly to Join workspace, including profile-less first run, instead of entering the personal parser. Android uses device-neutral linked-device text. Physical multi-install operation remains open. |
| Workspace DMs | 2 | Deterministic pair authorization, isolation from Personal contacts, paging, hiding, erasure, delivery, renderer, and local notification tests exist. Physical Android partition/reconnect is open. |
| Workspace connectivity diagnostics | 2 | Shared People dialog and service commands report per-device path/delivery state and request missing paths. This is advisory only and does not create a workspace reconnect profile. Physical multi-device path/TURN/NAT and suspension behavior remain open. |
| Workspace access recommendation | 2 | Shared out-of-band `MESHACCESS1:` document, authority/manifest verification, preview, explicit consent, workspace-scoped profile attach, and per-device automatic delivery. Receipt still requires consent and is not a workspace reconnect profile. Physical Android import/delivery/attach and multi-device routing remain open. |
| Workspace threads and mentions | 2 | One-level signed threads, structured mentions, independent reads, mutations, paging, and notification precedence are automated. Android notification tap/permission and accessibility behavior remain unverified on hardware. |
| Workspace search, history recovery, and retention | 2 | Encrypted bounded indexes, authenticated cursors, pruning, gaps, peer-limited recovery, and renderer states are automated. Physical suspension, storage pressure, and long-running recovery are open. |
| Workspace administration and authority transitions | 2 | Signed owner/admin requests, rotation/transfer, fork suspension, loss diagnostics, and renderer confirmation are automated. Concurrent physical Android partitions and kill points are open. |
| Linked devices | 2 | Fresh per-device identities, countersigned admission, caps, fan-out, recovery, read hints, and revocation are automated. The UI now says “device” on Android-visible surfaces. No identity or vault is copied. Physical link/revoke/replace remains open. |
| `meshchat://invite/`, `workspace/`, `workspace-device/`, `connect/`, and `route/` links | 2 | A native `singleTask` ingress validates v1/v2/v3/v4 invitation envelopes plus connection-response and route-update exact outer shapes under per-family byte bounds, stores one minimum pending value in app-private preferences, sanitizes the Activity intent, and atomically takes it for the renderer. Cold, delayed-renderer, warm, recreation/deduplication, malformed, unrelated, and oversized cases have source/JVM/frontend/Rust coverage. OEM/browser dispatch remains unverified. |
| `.meshchat-invite`, `.meshchat-connect`, `.meshchat-route`, legacy `.meshchat`, and validated `.json` files | 2 | The in-app Android action launches `ACTION_OPEN_DOCUMENT` with `CATEGORY_OPENABLE` and `*/*`, so providers that expose a Mesh Chat file as `application/octet-stream` no longer grey it out. Selection is still fail-closed: only supported names, bounded `content:` streams, strict UTF-8, and recognized outer shapes cross the native bridge; filesystem paths never do. Full cryptographic and local authorization checks remain in the shared service. Physical Files/Drive/provider matrices remain open. |
| QR scanning | 2 | Real workspace envelopes are compressed only for camera transport as bounded `MESHQR1` values, rendered at level L with a full quiet zone and responsive 600 px source size. The shared continuous camera preview has visible stop, permission, and settings states; image import uses the same normalization path. Recovered signed documents still enter their original parser. Runtime camera permission/denial, rotation, focus, and low-light behavior need physical verification. |
| Clipboard invitation copy/paste | 2 | Shared UI disables keyboard correction on invitation fields, classifies the full value before preview, and gives workspace-specific incomplete-prefix guidance. Workspace copy explicitly says it copied the complete invitation and reports its character count. Android version/keyboard/permission behavior needs a physical matrix. |
| Outgoing invitation sharing | 2 | Shared UI uses `navigator.share` when available and provides copy/save fallbacks. Android Sharesheet destinations and cancellation remain unverified. |
| Generic inbound Android `ACTION_SEND` shares | 4 | Only registered deep links and `.meshchat` `ACTION_VIEW` documents are accepted. Arbitrary shared text is intentionally not ingested by this increment. |
| Cold launch, warm `singleTask` launch, Activity recreation, delayed renderer | 2 | The native pending slot owns accepted launch input until one renderer command handoff; the Activity intent is replaced with `ACTION_MAIN`, and visible polling retries every 750 ms. Automated tests pass; process/OEM hardware testing remains open. |
| Visible event polling and duplicate delivery | 2 | The native bridge drains only while visible at a bounded 750 ms cadence. Invitation and event paths serialize polling; service identifiers remain idempotent. Hardware timing remains open. |
| Event overflow and authoritative reconciliation | 2 | The 256-item native queue now emits one explicit overflow marker, persists the service-side gap, clears the marker after drain, and triggers bounded reconciliation/snapshot refresh. Overflow and drain regressions pass. |
| Resume, renderer recreation, and refresh overlap | 2 | Foreground reconciliation is coalesced; a completed reconciliation always refreshes, while an event arriving during refresh schedules the existing trailing refresh. Foreground/background, overflow, and overlap regressions pass. OS process-death timing remains unverified. |
| Continuous execution while backgrounded or suspended | 5 | Unlike desktop, Android may suspend or terminate the embedded runtime. Mesh Chat intentionally uses neither cloud push nor a permanent foreground service or battery-optimization exemption. Durable state is reconciled when execution resumes; live receipt/notification timing is therefore best effort. |
| Local notifications: Personal direct, group, announcement, workspace channel/DM, thread, and mention | 2 | All live inbound families now share the durable authorization-first queue, opaque ID, sealed route, foreground suppression, preview hiding, native acknowledgement, and open-time reauthorization path. Mutation, replay/duplicate, historical, erasure, and category tests exist. Physical permission, lock-screen, tap, and suspension results remain open. |
| Per-conversation notification preferences | 3 | Workspace conversation preferences remain supported. Personal direct/group notifications honor device permission, foreground state, hidden conversations, and global preview hiding, but do not add a new per-conversation preference model in this increment. This avoids silently weakening established workspace semantics. |
| Notification as delivery/read evidence | 5 | Native presentation and taps intentionally never change message delivery or read state. Delivery remains application-level authenticated evidence; reading remains an explicit in-app action. |
| Protected profile storage | 2 | The profile is in app-private internal storage, records are authenticated/encrypted, the vault key is Android-Keystore-wrapped, backup is disabled in the merged manifest, and cleartext traffic is disabled. JVM/Python round trips exist; a physical full-tree plaintext scan and lock/reboot test remain open. |
| Published ARM64 release APK | 2 | The 0.9.2 artifact is `mesh-chat-0.9.2-android-arm64-release.apk`, 34,302,211 bytes, SHA-256 `e2a0a6efcdc59123e31a5092d689afe5a6308e141e31cb98b52a39e5c450b785`. `aapt2` reports `com.meshchat.mobile`, version 0.9.2 (9002), min API 24, target API 36, ARM64 only. `apksigner` verifies the standard Android Debug certificate (`CN=Android Debug`, SHA-256 `d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`), so this is a debug-signed sideload artifact, not production/upgradeable. No physical install was performed. |
| External release signing | 3 | Gradle accepts only externally supplied properties/environment values, creates no release signing config when incomplete, validates the keystore path, and fails clearly without inputs. No production key is available to the automated release; the published 0.9.2 APK is debug-signed. No key, alias, password, or certificate is committed. |
| Android App Bundle | 2 | `scripts/build_android.py --aab` selects a release AAB and the immutable publisher records a release-AAB artifact. Publication tests use non-secret fixtures. No signed production AAB has been built. |
| Upgrade preservation | 3 | Package ID/version-code continuity and prior debug-certificate package inspection are recorded, and migrations are automated. The current APK is debug-signed, so it cannot be upgraded to a production-key build without an uninstall/reinstall; no in-place upgrade over an older profile was tested on a device. |
| Accessibility and compact layout | 3 | Labels, live regions, keyboard/IME guards, native Back handling, safe-area treatment, and compact renderer tests exist. TalkBack order, focus restoration, font scaling, contrast, switch access, and touch targets require physical review. |
| Physical Android validation | 4 | No authorized device was attached during this increment. No install, battery, memory, camera, notification, lock-screen, process-death, upgrade, or cross-device result is claimed. |

## First bounded parity increment

The increment implements five connected changes without adding infrastructure:

1. Android-visible linked-device surfaces use device-neutral wording, backed by
   a renderer regression that opens both creation and linked-device dialogs.
2. Android launch invitations pass through a bounded native validator and a
   durable app-private one-value handoff. Cold/warm launches, recreation, and a
   delayed renderer cannot replay the Activity intent. Desktop launch arguments
   and `.meshchat` files now use equivalent strict validation and size limits.
3. Native queue overflow is explicit, resume reconciliation cannot overlap
   itself, and every completed reconciliation is followed by a fresh bounded
   snapshot. The existing trailing-refresh mechanism covers an event arriving
   during a refresh.
4. Personal direct, private-group, and announcement messages now enter the same
   secure local-notification architecture as workspace live messages. Routes
   are reauthorized on drain and open, duplicate/foreground/hidden traffic is
   suppressed, previews are bounded, and conversation erasure removes records.
5. Release APK/AAB builds use external signing configuration and fail closed if
   it is absent. Debug APK publication remains unchanged and both artifact forms
   retain immutable manifests and hashes.

The implementation preserves the server-free/account-free model, protocol
bytes, payload limits, renderer sandbox, protected-storage failure behavior,
and per-device identities. It adds no FCM, APNs, analytics, cloud storage,
hosted relay, foreground service, or battery exemption.

## Increment acceptance criteria

- Android linked-device dialogs contain no incorrect “desktop” wording.
- Supported invitation families and `.meshchat` content are bounded and
  validated before renderer exposure; malformed/unrelated launches reveal
  neither filesystem paths nor unvalidated content.
- One accepted Android launch value survives delayed renderer initialization,
  is removed on native command handoff, and is not replayed by Activity
  recreation or the deep-link plugin.
- Overflow, resume, duplicate, and overlapping-refresh paths converge through
  bounded authoritative state rather than history scans.
- Every live inbound message family either produces one authorized local
  notification or a durable suppression decision; mutations, duplicate/replay,
  foreground, hidden, historical, and erased content do not produce stale work.
- Notification presentation/open never marks a message delivered or read, and
  every open rechecks current local authorization.
- Debug APK behavior remains reproducible; release APK/AAB requests require all
  external signing inputs and publish through the immutable artifact layout.
- Automated evidence and hardware evidence are reported separately.

## Remaining work

- Run the physical-device matrix below on an authorized disposable ARM64 phone
  before calling Android parity complete.
- Design Personal per-conversation notification controls only if they can share
  the established sealed preference and reauthorization semantics.
- Decide whether intentionally unsupported generic `ACTION_SEND` text ingestion
  is desirable; any implementation must use the same strict bounds and must not
  expose unrelated shared content.
- Exercise a real externally signed release APK/AAB with release-key continuity,
  Play pre-launch checks, and upgrade/rollback policy. Secrets must remain
  outside the repository.
- Complete TalkBack, large-font, switch-access, rotation, split-screen, and
  low-memory review.

## Exact physical-device tests still required

Use only an explicitly authorized disposable device and retain OS/build/package
hashes with the results:

1. Install the exact debug APK without clearing data; repeat as an in-place
   upgrade from the supported older candidate and verify profile continuity.
2. Open each supported deep link and a `.meshchat` file from Files and at least
   one document provider during cold launch, warm `singleTask`, Activity
   recreation, renderer delay, rotation, background/resume, and process kill.
   Verify exactly one dialog and no unrelated intent/path disclosure.
3. Run paste, copy, QR image, native camera scan, and Android Sharesheet flows,
   including permission denial, later grant, cancellation, invalid/oversized
   input, and screen rotation.
4. Put Windows on ordinary home Wi-Fi and Android on cellular. Exercise direct
   public IPv4, native IPv6, each available router mapping protocol, the Windows
   firewall prompt, mapping renewal/router reboot invalidation, manual forward,
   timeout/refusal/no-IPv6-route reporting, and invitation expiry. Confirm the
   host stays prepared-unverified until the authenticated Android client connects.
5. Exchange Personal direct, private-group, announcement, workspace channel,
   workspace DM, thread, and structured-mention messages with Windows 0.2.42.
   Cover offline/reconnect, duplicate delivery, mutation, replay, history catchup,
   linked-device fan-out/revocation, and foreground/background transitions.
6. For each live family, test notification permission allow/deny/settings,
   preview hiding, grouping, foreground suppression, background/screen-off,
   lock screen, tap routing, authorization removal, local erasure, duplicate and
   historical suppression. Confirm taps create no read or delivery receipt.
7. Force native-event overflow, renderer recreation, Activity recreation,
   Android process death, network restoration, and rapid focus changes while a
   refresh is running; verify the visible state converges without duplicates or
   unbounded work.
8. Reboot and unlock, then inspect the app-private tree for known plaintext
   markers and confirm fail-closed vault behavior. Verify Android backup/restore
   does not export the profile and cleartext network policy remains disabled.
9. Record battery/memory behavior during an extended foreground session and
   confirm no permanent foreground service, cloud push registration, or battery
   exemption appears.
10. Complete TalkBack navigation/focus announcements, 200% font scaling, touch
   target, contrast, IME composition, hardware/software Back, rotation,
   split-screen, and system-bar inset checks.
11. With release-operator credentials supplied out of tree, build and verify a
    signed APK and AAB, signature schemes/certificate continuity, Play bundle
    inspection, and release-to-release upgrade. No credentials belong in logs
    or repository artifacts.

Introducing a permanent foreground service or requesting a battery-optimization
exemption requires explicit product/security approval. Cloud push, hosted
relays, analytics, telemetry, cloud storage, identity/vault copying, or protocol
byte changes are outside this parity plan.

## Phase 3 relationship persistence boundary

The shared protected service now atomically stores admitted relationship
evidence with its replay floor and implements fresh-key reconnection, foreground
reconciliation, same-socket UDP renewal and supported QUIC client migration with
reconnection fallback. Suspension retires all native ownership; an encrypted
relationship does not preserve a process or socket. Controlled desktop service
lifecycle tests and Android compilation are distinct from physical Android
process-death, network-switch, battery and router qualification. Background
availability is not promised. Physical Phase 2 Windows/Android qualification remains pending;
see [Phase 3 criterion tracking](DIRECT_CONNECTIVITY_PHASE3_EVIDENCE.md).
