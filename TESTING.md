# Verification and release gates

## Commands

Focused service and UI checks:

```text
python scripts/test.py
```

`scripts/test.ps1` is the equivalent Windows helper used by the recorded build.

Sidecar packaging:

```text
python scripts/build_sidecar.py
```

The script derives the native Rust host triple, builds with the current Python
interpreter, and deliberately refuses cross-compilation. Run it on every
target operating system.

Real four-process mesh topology (opens loopback TCP listeners):

```sh
MESH_CHAT_RUN_NETWORK_TESTS=1 python -m pytest service/tests/test_topology_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_NETWORK_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_topology_harness.py -v -s
```

Require the same topology to use the OS encrypted-workspace adapter:

```sh
MESH_CHAT_RUN_NETWORK_TESTS=1 MESH_CHAT_REQUIRE_PROTECTED_STORAGE=1 \
  python -m pytest service/tests/test_topology_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_NETWORK_TESTS = "1"
$env:MESH_CHAT_REQUIRE_PROTECTED_STORAGE = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_topology_harness.py -v -s
```

Rust/Tauri boundary:

```text
cargo check --locked --manifest-path src-tauri/Cargo.toml
python scripts/build_desktop.py
```

Windows toolchain helpers:

```powershell
.\scripts\cargo-check.cmd
.\scripts\desktop-build.cmd
```

Mobile packaging:

```text
python scripts/build_android.py
python3 scripts/build_ios.py  # macOS with Xcode and Apple signing only
```

Direct local fallback (opens a local TCP listener and launches two processes):

```sh
MESH_CHAT_RUN_DIRECT_LAN_TESTS=1 python -m pytest service/tests/test_direct_lan_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_DIRECT_LAN_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_direct_lan_harness.py -v -s
```

Increment 12 administrator scale benchmark:

```powershell
.\.venv\Scripts\python.exe .\service\tools\workspace_administrator_benchmark.py `
  --events 50000 --samples 30 `
  --output .\docs\benchmarks\increment-12-workspace-administrators.json
```

The 0.2.7 harness runs two configurations. The first advertises signed TCP hints
from both peers, times reverse-route approval, then verifies direct chat,
application receipt, group invitation and join, a group message, and another
direct message after group activity. The second shapes the joining peer like a
phone: it opens the inviter's signed TCP hint but exposes no reverse listener,
then proves direct messages and receipts in both phases over that full-duplex
connection. Keep the always-on deterministic two-peer service flow and the
focused approval/direct-message regression file in the ordinary suite as well;
the opt-in real-network harness does not replace them.

## Private-group release gates

Passing ordinary one-to-one tests is not sufficient to release private groups
or announcement channels. Group verification must use the reference RNS/LXMF
stack and individual destinations; a test double or accidental
`RNS.Destination.GROUP` path cannot establish this gate.

Automated protocol and security coverage must include:

- canonical round trips for genesis, member cards, active and closed manifests,
  targeted invites, join and leave statements, every group payload kind, and
  the eight-member boundary;
- exact-field rejection, malformed encodings, oversize documents, signature
  substitution, identity/destination mismatch, group-ID re-derivation, duplicate
  members, unsorted manifests, multiple or missing owners, and unauthorized
  roles or posting policies;
- invitation expiry, wrong-target invitations, replayed acceptances, acceptance
  bound to the wrong nonce/manifest/group, and group-scoped consent that does
  not silently create ordinary direct-message trust;
- durable invitation delivery states, application-receipt promotion to
  **Invitation ready for review**, bounded automatic backoff, restart recovery,
  and owner-triggered **Retry invitation** using the contact's newest approved
  route hints without creating a duplicate invitation;
- manifest next-epoch and previous-hash enforcement, rollback, skipped epoch,
  two owner-signed manifests for one epoch, owner substitution, stale sender,
  removed sender, stale posting-policy attacks, owner leave rejection, and the
  terminal closed-state rule;
- strict group metadata kind combinations, logical child IDs versus the common
  group-message ID, sender-sequence bounds/replay, receipt source binding, and
  a receipt that attempts to update another member's delivery;
- exactly one child delivery for every other active recipient, with no copy for
  the sender, an invited-but-unaccepted person, a departed person, or a removed
  person;
- atomic creation of the logical message and complete child set, idempotent
  recovery after a process kill at every fan-out/handoff/receipt boundary, and
  no duplicate visible message after native retransmission or delivery-method
  change;
- no history backfill on admission, future-copy exclusion after removal, and
  honest aggregate states for all delivered, partial, pending, expired, and
  mixed outcomes; and
- encrypted-vault and full-profile marker scans covering group names, member
  display names, manifests, messages, drafts, outbox children, and receipts.

Real-network integration must exercise three-, five-, and eight-device groups
over direct and propagated LXMF. Partition at least one recipient, deliver to
the others, restart the sender mid-fan-out, reconnect the recipient, and prove
that only the missing child is retried. Repeat while rotating a route hint,
changing an IP address, suspending a mobile device, and making the owner
offline. A blind propagation node must store only recipient-encrypted objects;
scan its persistent files and capture traffic as release evidence.

The invitation test must not rely on Firebase, APNs, or any other central push
service. With propagation disabled, remove every Reticulum path and confirm the
owner remains honestly at **Invitation queued** or **Trying to find device**
and the recipient sees no invitation. Restore a permitted Reticulum path and
confirm that the same durable invitation arrives without creating a second
logical invitation. If an approved propagation node is tested, distinguish
**Stored securely for delivery** from endpoint receipt and application receipt.

Membership-partition testing must remove a disconnected member, deliver the
next signed epoch to the reachable members, and attempt both an old-epoch
message and an old invitation replay. The expected result is explicit eventual
revocation: updated members reject the removed sender, while a still-partitioned
endpoint may retain its last valid view until it receives the new epoch. No UI
may describe that transition as instantaneous global removal.

Physical-device release testing must cover Windows-to-Android and, when a
signed build is available, macOS-to-iOS creation, invitation, acceptance,
posting policy, partial delivery, suspend/resume, removal, and upgrade from a
profile containing only one-to-one chats. Test the eight-person limit and
screen-reader/keyboard announcements for group invitations, membership changes,
posting restrictions, and per-recipient delivery details.

Install the same current candidate build on every device in a physical group
test. Older group-unaware builds are not a compatibility result even when an
existing one-to-one chat still works. On Android, repeat invitation delivery
with Mesh Chat visibly in the foreground, local-network permission granted,
battery restrictions removed for the test, and both devices on the same
non-guest network for the default direct path. Then background/suspend the app,
verify that the UI makes no promise of cloud push delivery, return it to the
foreground, and verify recovery when a Reticulum path becomes available.

### Group invitation reliability procedure

For every release candidate, retain a timestamped screen recording and service
logs for this sequence:

1. Verify that the owner and invitee packages report the same current candidate
   version. Upgrade in place so the established contact and its signed route
   hints remain available.
2. With no usable path and no propagation node, create a two-person group.
   Confirm that **Members & security** shows **Invitation queued** or **Trying
   to find device**, and that the invitee receives no dialog.
3. Restore the intended Reticulum path with both apps running. Record the
   transitions through **Sending invitation** and, when applicable, **Reached
   device · confirming receipt**. Only the verified application receipt may
   produce **Invitation ready for review**.
4. Break the path again while the invitation is still pending. Use **Retry
   invitation** and prove that it starts an immediate attempt with current
   contact hints but does not falsely advance the state or create a duplicate.
   Restore the path and verify that automatic or manual retry delivers the
   original logical invitation once.
5. Keep the Android app in the foreground through **Accept invitation** and the
   owner's next signed membership epoch. Confirm that the owner does not count
   the invitee as an active recipient before that acceptance completes.
6. Exercise restart and Android suspend/resume at queued, endpoint-received,
   and application-receipted boundaries. State must recover from the encrypted
   outbox and must never be inferred merely from a network acknowledgment.
7. Exercise signed expiry. After expiry, **Retry invitation** must not revive
   the capability, and the invitee must be unable to accept it.

## Recorded 0.1.7 first-message layout hotfix verification — 2026-10-03

- Version 0.1.7 fixes the approved-conversation grid layout that could make the
  Windows and Android chat views look blank immediately after the first message
  replaced the larger empty-thread panel. The messaging transport and saved
  records remained active during the observed failure.
- Install 0.1.7 over 0.1.6 on **both** the Windows computer and Android phone.
  Do not uninstall either app and do not clear either app's data. Existing
  profiles, contacts, invitation relationships, and saved messages remain.
- Devices already connected on 0.1.6 do not need a new invitation after this
  hotfix upgrade. A new invitation is still required when establishing the
  direct-LAN relationship from an invitation created before 0.1.6.
- The Android package is
  `dist/mobile/mesh-chat-0.1.7-android-arm64-debug.apk`, with version name 0.1.7
  and version code 1007. The Windows packages are
  `Mesh Chat_0.1.7_x64-setup.exe` and `Mesh Chat_0.1.7_x64_en-US.msi`.
- The focused run passed 58 Python service/layout tests with three expected
  platform/opt-in skips, 12 renderer tests, TypeScript compilation, and the
  production Vite build. The regression coverage pins the optional connection
  banner, message list, and composer to named grid areas and exercises the
  first stored message, invalid timestamps, send failure recovery, and the
  top-level renderer recovery screen.
- A live Windows 0.1.7 run against the profile that exhibited the fault loaded
  the saved chat without clearing data. WebView geometry reported a collapsed
  0 px optional-banner row, a 624.61 px message row, and an 81.39 px composer;
  two saved messages rendered and no renderer exception occurred.
- The packaged Windows sidecar passed EFS-protected profile initialization,
  signed invitation creation with a direct-LAN hint, graceful shutdown, and
  stderr-redaction checks. The Windows app and NSIS installer report version
  0.1.7. The development installers are not Authenticode-signed.
- The Android arm64 APK reports minimum API 24 and target API 36. APK Signature
  Scheme v2 verification passed with the same debug certificate used by 0.1.6
  (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).
- A physical post-upgrade Windows-to-Android send-and-render retest remains
  open. The observed physical message delivery, persistence, application
  receipt, and both established TCP directions were confirmed during diagnosis;
  the new APK has not yet been installed on that phone.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `4474639F6772EEE6FD5E993086E4B35DAC6E396FFE0ECCA2835731A44681CBCA` |
| `mesh-chat.exe` | `5FBFAD8E4D006C0317F912353B8EEA4A3939C4FE4585C0892D5051D0709CDE11` |
| `Mesh Chat_0.1.7_x64_en-US.msi` | `D3E9A476B7F954299797AC9662470E54DCFB951ABD2DFCFB100DEFA29EE3C1B8` |
| `Mesh Chat_0.1.7_x64-setup.exe` | `4BE40433B346363E553DF4D52DE43C5CAF2159AA47458A85969E9032938464FE` |
| `mesh-chat-0.1.7-android-arm64-debug.apk` | `14A3E37EB184073F741067CB2815CFA07A84F06E56723FB2670690DC27D32CA5` |

## Recorded direct LAN fallback verification — 2026-10-03

- Version 0.1.6 adds a bounded local TCP listener and advertises concrete local
  addresses only through cryptographically signed invitation hints. It is a
  same-LAN fallback for blocked IPv6 multicast, not an Internet relay.
- The opt-in TCP-only harness passed with automatic nearby discovery disabled.
  Two isolated Mesh Chat service processes established the hinted TCP path,
  delivered a first contact request from an initially unknown identity,
  completed explicit acceptance, exchanged a chat message, and completed the
  application receipt flow.
- The first-contact bootstrap verifies both the signed invitation and the
  native LXMF message signature against the identity carried by that invitation
  before remembering the sender. Unknown or invalid messages remain rejected.
- Re-importing a new invitation for an existing contact refreshes its signed
  connection hints and retries an awaiting request without clearing either
  profile.
- **Upgrade/retest procedure:** install 0.1.6 over the existing Windows and
  Android apps, preserving their data; put both devices on the same non-guest
  LAN; create a NEW invitation/QR on the computer; scan or paste it on the
  phone; keep both apps open; and accept the foreground request on the computer.
  Invitations created by earlier versions do not contain this fallback hint.
- A physical Windows-to-Android 0.1.6 retest is still pending. The automated
  TCP-only pass proves the service path but does not substitute for Android OS,
  Wi-Fi access-point, and Windows firewall validation on the affected devices.
- The complete verification run passed 57 Python service tests and 8 renderer
  tests, followed by TypeScript compilation and the production web build. The
  opt-in direct-LAN harness also passed separately.
- The packaged Windows sidecar passed EFS-protected profile creation,
  initialization, invitation creation with a signed direct-LAN hint, graceful
  shutdown, and stderr-redaction checks. The Windows app and NSIS installer
  report version 0.1.6; the current development packages are not
  Authenticode-signed.
- The Android arm64 APK reports version 0.1.6 (version code 1006), minimum API
  24, and target API 36. APK Signature Scheme v2 verification passed with the
  same debug certificate as the prior package (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `837DB3659AD6BFE9388D07F0514979CB759AC879D40013A3EC955853E5E6E5DB` |
| `mesh-chat.exe` | `14CEAC2901F59AE215C94885F8EC572637D3CD07B3AB72A5D883FA0F64DDC904` |
| `Mesh Chat_0.1.6_x64_en-US.msi` | `52ABB7B65A4438EFD4D9646E3D8FCD215F09F0D185505DE7FC0201C35987557B` |
| `Mesh Chat_0.1.6_x64-setup.exe` | `F90DCC3441684C2BB95C982FF811A3B6C5F8815BD9E1E8063B169B252FC95263` |
| `mesh-chat-0.1.6-android-arm64-debug.apk` | `B05FB98D83D11BE2F83F573D15D4B1813F2FE26C89640D0F8489A2C1A1C6F104` |

## Recorded 0.1.5 connection-request regression verification — 2026-10-03

- Focused suite: 45 Python tests passed with 2 expected platform/opt-in skips;
  7 renderer tests, TypeScript compilation, and the production Vite build
  passed.
- An incoming request now opens a foreground **Connection request** prompt with
  Accept and Decline on the invitation-creating device. If the QR/invitation
  dialog is open, it remains mounted behind the request prompt so its state is
  preserved.
- Desktop request state is reconciled when the window regains focus, when it
  becomes visible, and on a short foreground interval. This covers a request
  that arrived before the renderer listener was attached or whose one-time
  event was otherwise missed.
- The joining device now distinguishes a locally queued request from endpoint
  evidence. It says **Trying to reach...** until the request reaches the other
  device, and says **Waiting for acceptance** only after endpoint receipt.
- Embedded-network startup cleanup, usable-interface reporting, and recovery
  are covered by regression tests. The app reports when no receiving
  AutoInterface is available instead of silently presenting a healthy state.
- The Windows packaged-sidecar smoke passed initialization, EFS-protected
  profile creation, signed invitation creation, graceful shutdown, and stderr
  redaction.
- Windows x64 executable, MSI, and NSIS bundles report version 0.1.5 and were
  linked successfully. These development installers are not Authenticode
  signed.
- Android arm64 APK version 0.1.5 was assembled with minimum API 24 and target
  API 36. APK Signature Scheme v2 verification passed, and the signing
  certificate matches the prior development build so it can be installed over
  the existing app without clearing its profile.
- A physical Windows-to-Android delivery test remains open. The previously
  observed phone request did not reach the running Windows Reticulum instance;
  local IPv6 multicast, firewall, or wireless client-isolation conditions
  still need to be checked on the affected network if 0.1.5 remains on
  **Trying to reach...**.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `4DB0335F04ECA0C0F6CF6E2B8069DBB98DE31238D663703A058AA261C042E96B` |
| `mesh-chat.exe` | `428AEE347210F43F6BE765E8862245EA2739EE768C27706FDDD2DCA89C642072` |
| `Mesh Chat_0.1.5_x64_en-US.msi` | `D4B3A4257F36AA4CB334B4B0432F1C993B285EA71CFB4F2FB6D572D030D7B5CA` |
| `Mesh Chat_0.1.5_x64-setup.exe` | `EBBCB5D53C8BAC0CBBA5E7370920C2534A9F87684B7DF99EEEF6CCBE7877DC53` |
| `mesh-chat-0.1.5-android-arm64-debug.apk` | `419E41FF14493AF6A55A8E92381157C37C14DB45AEB0EFDA479486F75B324D72` |

## Recorded Windows verification — 2026-10-02

Environment: Windows 10.0.19045 x64, Python 3.12.14, Rust 1.99.0,
RNS 1.5.5, LXMF 1.2.0, Node.js 24.19.0.

- Focused suite: 31 Python tests passed with the opt-in topology and the
  Linux-only `/sys` device-tree test skipped; 2 renderer tests passed;
  TypeScript and the production Vite build passed.
- Full protected integration suite: 27 tests passed, including the real
  four-process A→B→C→D topology. The destination reported exactly three hops,
  its ratchet was present before send, the LXMF signature validated, and no
  plaintext marker appeared in B or C persistent files.
- Packaged-sidecar smoke: initialize, EFS-protected profile creation, signed
  invitation generation, graceful shutdown, and stderr-redaction checks all
  passed through the built executable's framed stdin/stdout IPC.
- `cargo check --locked` passed. A release executable, MSI, and NSIS installer
  were linked and bundled successfully. Native visual automation was not
  available on the verification host, so manual UI and assistive-technology
  review remain open.
- Android arm64 debug packaging passed with minimum API 24 and target API 36.
  `apksigner` verified the APK Signature Scheme v2 signature. The merged
  manifest disables backup and cleartext traffic and includes the camera and
  Wi-Fi multicast permissions. A physical-device smoke test remains open.

Artifact hashes for this run:

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `CC4EEEBB7CFC4A044ECE02DAFEC9516F0E0E4DDD2530EAB7A06C3720AF30C8AB` |
| `mesh-chat.exe` | `52DC68028A9B06755D387A0D7CF97B8D78084027E68759FEB90D51D27668CED0` |
| `Mesh Chat_0.1.0_x64_en-US.msi` | `843B49788ED705ED34D4E92075D7A5CD1011741500EDDFECD9F6B37ABB7326BB` |
| `Mesh Chat_0.1.0_x64-setup.exe` | `70A1C1119F33DB3967199396B45504733361FC926863D8B92263EA65D178D130` |

## Recorded Android regression verification — 2026-10-03

- Focused suite: 35 Python tests passed with 2 platform/opt-in tests skipped;
  2 renderer tests, TypeScript, and the production Vite build passed.
- Phone clipboard formatting tests cover wrapped tokens, invisible formatting
  characters, and an invitation embedded in ordinary shared text. Signature,
  destination, expiry, and identity checks remain authoritative.
- Android command payloads are forwarded as the original serialized JSON. This
  avoids Jackson's unsupported `JSONObject` field conversion, which previously
  replaced nested payloads such as `{ "invitation": "..." }` with an empty
  object before they reached the service.
- The mobile UI uses Tauri's native barcode-scanner plugin on Android and iOS;
  the browser camera path remains only as the desktop fallback.
- Both invitation-creation screens show the full shareable invitation first,
  along with its signed expiry, Copy, Share, Save, and QR options.
- A subprocess lifecycle regression now covers mobile profile creation,
  forced AutoInterface failure, invitation acceptance, idempotent retry, and a
  second-process reopen of the encrypted profile. The process remains alive
  and returns a structured network state instead of Reticulum's status-255
  process exit.
- The Android bridge now uses one process-long executor thread for Python
  initialization and every command. Embedded RNS process exits are converted
  to recoverable errors, while a failed optional interface is isolated.
- Android arm64 APK version 0.1.4 was assembled with minimum API 24 and target
  API 36. `apksigner` verified its v2 signature. The merged manifest includes
  camera access and continues to disable backup and cleartext traffic.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-0.1.4-android-arm64-debug.apk` | `8ACE8B42D4967B5A1E13723DCE9F2ED29FEAA1B4039B777F55C32BD8D83689D3` |

## Recorded Windows 0.1.3 packaging regression — 2026-10-03

- The focused suite passed with 33 Python tests, 2 expected skips, 2 renderer
  tests, TypeScript compilation, and the production Vite build.
- The Python messaging sidecar was rebuilt so `create_invitation` returns the
  signed expiry used by the updated invitation panel.
- The release executable reports product and file version 0.1.3. MSI and NSIS
  installers were linked successfully for Windows x64.
- Both invitation-creation screens place the complete shareable invitation at
  the top, followed by Copy, Share, Save, signed expiry, and QR options.
- These development installers are not Authenticode-signed. Windows may show
  an unknown-publisher warning until a production signing certificate is used.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `E4C540ACEE919E4C01DA17EC65480801D4E739B5384AB3308FAE1118C5FD3721` |
| `mesh-chat.exe` | `6BC4603D4971A2A9213F93D41E47A791B35DDAD7B76BC4E1640CF1A9C4ABAC75` |
| `Mesh Chat_0.1.3_x64_en-US.msi` | `703226D61F15C8183DF0957A79E54E8C724BCF360933E7A99D20EE4B3F7AA0E9` |
| `Mesh Chat_0.1.3_x64-setup.exe` | `9DB43D5299CBBE45724DCFC6BAD7C9BB71A4F5626D30F246ED869044A60876CE` |

## Recorded 0.2.0 private-group package verification — 2026-10-03

- The complete automated run passed **80 Python tests** with three documented
  platform/integration skips, **18 renderer tests**, TypeScript compilation,
  and the production Vite build.
- The opt-in real Reticulum/LXMF direct-LAN harness passed separately, as did
  the isolated four-process A→B→C→D topology harness.
- Eleven focused group-service tests passed, including simultaneous invitees,
  reversed membership-epoch arrival, replay after removal, remove/leave/close,
  old-epoch owner equivocation, restart recovery, application-receipt retry,
  and strict duplicate handling. Group protocol and IPC regressions bring the
  focused protocol/service/IPC total to 28 passing tests.
- The Windows x64 Rust release build completed. The NSIS and MSI packages both
  contain a sidecar whose SHA-256 exactly matches the newly built group-aware
  PyInstaller sidecar. The MSI reports product version 0.2.0.
- The Android arm64 APK reports version name 0.2.0, version code 2000, minimum
  API 24, and target API 36. `apksigner` verified its v2 Android debug
  signature. The packaged Chaquopy archive contains `group_protocol.pyc` and
  `group_service.pyc`; staged Android group sources are byte-identical to the
  service sources; and the packaged native library contains the complete group
  command allowlist.
- These Windows development packages are not Authenticode-signed, and the APK
  uses the Android debug certificate (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).
  Physical Windows↔Android multi-member group, suspend/resume, partition, and
  upgrade testing remains required before sensitive use.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `56BF76A316D11D18FB3AC04B48AA3BED388C39033B31CBC9FD6DA6902FB53C39` |
| `Mesh Chat_0.2.0_x64-setup.exe` | `84899608932B1DD80C7DF62C9909BC2E723A430C9E3EB7F5172BC184931AC8A6` |
| `Mesh Chat_0.2.0_x64_en-US.msi` | `53E93942B04763D216CFE1469B0184FA9AF28E504E5E00A62627A344B6327947` |
| `mesh-chat-0.2.0-android-arm64-debug.apk` | `DB8DE84EC8DCFD06BBE08284D1B29A5EE6A4B0DCC52FF4592CE82AFDCD663381` |

## Recorded 0.2.1 group-invitation reliability verification — 2026-10-03

- The complete automated run passed **82 Python tests** with three documented
  platform/integration skips and **19 renderer tests**. TypeScript compilation
  and the production Vite build also passed.
- The real two-process Reticulum/LXMF direct-LAN harness passed the complete
  contact invitation and approval, direct chat, group creation, targeted group
  invitation, recipient application receipt, and explicit group-acceptance
  sequence without a central relay or push service.
- Group-invitation reliability coverage verifies durable per-invite delivery
  state, application-confirmed **Invitation ready for review**, bounded
  automatic retry, restart recovery, manual `retry_group_invitation` with
  refreshed approved contact hints, signed expiry, and duplicate suppression.
- The Windows x64 executable, NSIS installer, and MSI report version 0.2.1.
  The installers contain the newly built invitation-reliability sidecar; the
  development packages remain unsigned by Authenticode.
- The Android arm64 APK reports version name 0.2.1, version code 2001, minimum
  API 24, and target API 36. `apksigner` verified its APK Signature Scheme v2
  debug signature.
- Packaged Python source hashes match the release source tree. The packaged
  native renderer-command allowlist contains `retry_group_invitation`, so the
  owner-side Retry control reaches the embedded service instead of being
  rejected at the native boundary.
- Physical Windows↔Android foreground/background, route-loss, and multi-member
  group testing remains required before sensitive operational use; the passing
  two-process harness does not substitute for Android lifecycle and Wi-Fi
  behavior.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `038EAA173698DC48C0F6EA342851F8A46526D073804DE5A6574E775DE4362E21` |
| `mesh-chat.exe` | `3EC66D870655698268C97C26CDA35AE2DD872EBC990EE89319853FC085CFD894` |
| `Mesh Chat_0.2.1_x64-setup.exe` | `D3057B8AE65D8757502F70141316D9E65DCAAD45AAF8040A1BD9196C1868F7F1` |
| `Mesh Chat_0.2.1_x64_en-US.msi` | `EF864D759D4C0D39C0FD60A34352049FF4FFA7D6E77A08460CD6E12DF266A07E` |
| `mesh-chat-0.2.1-android-arm64-debug.apk` | `B2C9E877CCBA22534097FE21FBBE39E17D2F17F4B5E92398F8BDA81AB08DF4EE` |

## Recorded 0.2.2 desktop lifecycle verification — 2026-10-04

- This is a historical record, not the current install recommendation. A later
  live 0.2.2 reproduction found that the PyInstaller supervisor and worker
  could survive a busy close. The worker retained the valid EFS-encrypted
  profile lock, and the lock-contention error was incorrectly presented as
  `protected_storage_unavailable`. The profile remained encrypted; no private
  data was lost and no plaintext fallback was used. Version 0.2.3 supersedes
  the lifecycle conclusion recorded here.
- The desktop close/relaunch failure was traced to the main Tauri window being
  destroyed without exiting the application. The headless process retained the
  single-instance endpoint and PyInstaller sidecars, so a later launch handed
  control to an instance with no window and appeared to do nothing. For an
  already affected 0.2.1 session, ending **Mesh Chat** and its
  `mesh-chat-service.exe` processes in Task Manager, or restarting Windows,
  releases that stale instance before launching 0.2.2.
- Version 0.2.2 changed desktop close to request application exit and attempted
  to release the messaging sidecar and single-instance endpoint. A launch handed to an
  already running instance now shows, restores, and focuses its main window.
  It forces a native hide/show refresh and recreates the configured main window
  when no live webview window remains.
  Exit cleanup uses a non-blocking service lock and a two-second process
  fail-safe. The later reproduction established that this was not sufficient
  to guarantee cleanup when a PyInstaller worker remained busy.
- The complete automated run passed **83 Python tests** with three documented
  platform/integration skips and **19 renderer tests**. TypeScript compilation
  and the production Vite build also passed.
- The Windows x64 Rust release compilation and full release build completed.
  All three Rust release unit tests passed, including the service-lock
  contention regression test for non-blocking exit cleanup.
  The executable, NSIS installer, and MSI report version 0.2.2, and both
  installers contain the matching rebuilt sidecar.
- That packaged Windows lifecycle smoke verified the exact sequence for its
  tested run: the first
  launch displayed the actual `Mesh Chat` Win32 title window; a second launch
  restored that window after both a raw native hide outside Tauri and a supported
  minimized state; an exact title-bar close terminated the host and every
  PyInstaller service process; and the following clean launch displayed the main
  window again. The final test close left no Mesh Chat GUI or service process.
  It did not reproduce the later busy-worker case and therefore did not prove
  cleanup for every close path.
- The matching Android arm64 debug APK reports version name 0.2.2 and version
  code 2002. Minimum API 24 and target API 36 remain unchanged.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `909F277F3FEB8548819B7F19AA4CAAF56CA8D40921084FECEACB0FCE39D5B3CD` |
| `mesh-chat.exe` | `E75E8A1D91B3CBD45FB0480241C04F3E6E594D41BA152A33EF8A31FE93A43668` |
| `Mesh Chat_0.2.2_x64-setup.exe` | `20722CEA3CCC9B7550EE7AA173E22B6418FF4E9B3947E3BC1B55D74785F1FABA` |
| `Mesh Chat_0.2.2_x64_en-US.msi` | `9B685D8D321DFFB820AACBC74CD0E6FFA2977571DCB6B30ABC58480D7241DED5` |
| `mesh-chat-0.2.2-android-arm64-debug.apk` | `75FB7EC1F8EAAF64724D683452B5694AF6C06C35B669CC2217E3AFF20ECCC5D0` |

## Recorded 0.2.3 profile-lock and desktop lifecycle verification — 2026-10-04

- The observed startup safety screen was traced to a stale 0.2.2 PyInstaller
  worker holding the profile lock, not to loss of NTFS EFS protection. The
  profile directory and private files remained EFS-encrypted, no private data
  was lost, and no plaintext fallback was used. Lock contention now has the
  distinct `profile_in_use` code and UI guidance; genuine protected-storage
  failures retain their fail-closed message.
- Invitation creation now has its own visible error state and **Retry
  invitation** action. A failed or timed-out attempt can be retried in the same
  dialog without discarding the rest of the UI state.
- Desktop initialization passes its exact `parent_pid` to the service. The
  service starts a parent-death watchdog before opening the vault, so a worker
  exits if its owning desktop disappears. Desktop close has an independent
  deadline: it first requests graceful shutdown, then terminates the recorded
  sidecar PID tree with the Windows system `taskkill` executable before exiting
  the host. Cleanup is bounded and ordered, and it never selects processes by
  executable name.
- The complete automated run passed **96 Python tests** with three documented
  skips, **22 renderer tests**, all **3 Rust release tests**, and the production
  frontend build. The packaged sidecar smoke passed EFS-protected profile
  initialization, signed invitation creation, connection-hint discovery, and
  shutdown.
- The live Windows lifecycle run created exactly three relevant processes: the
  desktop host plus the PyInstaller supervisor and worker. Closing the window
  left zero of those exact processes after **2,237 ms**. Immediate relaunch of
  the same encrypted profile succeeded, and the second close again left zero
  processes.
- The Windows executable, NSIS installer, and MSI report version 0.2.3. The MSI
  `File` table contains `mesh-chat.exe` at **4,760,064 bytes** and the matching
  sidecar at **18,147,673 bytes**. These development Windows packages are not
  Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.3, version code 2003,
  minimum API 24, and target API 36. It contains `arm64-v8a`, and APK Signature
  Scheme v2 verification passed with the development debug certificate.
- Install 0.2.3 directly over an existing release; do not uninstall the app or
  clear app data. To recover a stale pre-0.2.3 Windows process, restart Windows
  or use Task Manager to end **Mesh Chat** and every
  `mesh-chat-service.exe` process, then launch or install 0.2.3.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `36D1FF9EC2A88525C59068C4636C91E5698495DD1DE118D3D24841E1C0D3FB4F` |
| `mesh-chat.exe` | `42E63C5C8366653B77BF0E5CC73D5AAD8AA4D508809D7293293C95CA6B1D3A24` |
| `Mesh Chat_0.2.3_x64-setup.exe` | `B1158B7DDFF01790E03DD2471C41BB3974A22E493EE2F3D6F0181EC51C6975DC` |
| `Mesh Chat_0.2.3_x64_en-US.msi` | `D1E9E3F41BCF5D033746BE7AC73622A8AB41F0CB1C75D3825C44FD87E38CAD44` |
| `mesh-chat-0.2.3-android-arm64-debug.apk` | `C47BDC54472283AA9B113BCDBFEB6230FDEB116F06D2247592C2BC7BCFAC1ED2` |

## Recorded 0.2.4 one-to-one approval regression verification — 2026-10-04

- A physical Windows-to-Android run on the previous release reached the
  desktop **Connection request** dialog but failed after **Accept and open
  chat**. The group-route work caused approval to attach every signed reverse
  TCP route synchronously. Each unreachable address could consume Reticulum's
  connection timeout, so several valid hints could outlive the desktop command
  deadline even though the approval had already begun committing. The same
  approval path also attempted the durable `CONTACT_ACCEPT` once directly and
  again during its immediate outbox flush.
- Version 0.2.4 selects Reticulum's supported asynchronous TCP-client startup
  before configured or dynamically attached clients are constructed. It
  atomically commits the approved contact and exactly one retryable
  `CONTACT_ACCEPT`, then performs one outbox flush. Optional route-application
  failures remain contained, mark the settings dirty, and retry on a later
  send without creating another acceptance. This shared Python core is
  packaged in both the Windows desktop sidecar and Android APK.
- The complete automated run passed **106 Python tests** with three documented
  skips, **24 renderer tests**, and all **3 Rust tests**. The 21 focused group
  protocol/service tests remained green. All **9 tests** in
  `test_approval_regressions.py` passed, including eight reverse routes within
  the command budget, atomic approval/outbox persistence, exactly one
  `CONTACT_ACCEPT`, in-flight duplicate suppression, contained transport and
  route failures, dirty-route recovery, and retry without duplication. Renderer
  coverage also verifies that a timed-out approval is reconciled from a fresh
  service snapshot when it committed, while a truly pending request stays open
  with actionable retry guidance.
- The always-on deterministic two-peer service test completed profile and
  invitation creation, request delivery, approval, acceptance delivery,
  two-way trust, direct chat, application receipt, and delivered state while
  asserting that the one-to-one path created no group state.
- The opt-in real two-process Reticulum/LXMF direct-LAN harness advertised
  signed TCP hints in both directions. Approval completed in approximately
  **0.03 seconds**; direct chat and its application receipt passed, followed by
  group invitation and join, a group message, and another direct message after
  the group flow. This guards both one-to-one and group behavior in the same
  reference-stack run without a hosted relay.
- The packaged Windows sidecar smoke reported every EFS protection and command
  check true. Both the MSI and NSIS contained a sidecar whose SHA-256 matched
  the standalone release sidecar. The Windows development installers are not
  Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.4, version code 2004,
  minimum API 24, and target API 36. APK Signature Scheme v2 verification
  passed with development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  It contains only the `arm64-v8a` native architecture and packaged Python
  bytecode markers for atomic approval, dirty-route recovery, and asynchronous
  TCP startup.
- Install 0.2.4 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, and saved messages are retained. A physical
  Windows-to-Android retest of these exact 0.2.4 packages remains pending and
  is still required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,148,139 | `8BD4639B78A0F26F28BE481BA3E8C8B3924C856CC0F577967186B35C4AF059F8` |
| `mesh-chat.exe` | 4,760,064 | `E1CBFCD2615FB4DA052DB63EA7DA76ACEEDAC639380595DE0575172DEC1E373E` |
| `Mesh Chat_0.2.4_x64-setup.exe` | 19,624,480 | `7BC771E518E5ABA36737497BA949D8DAB27BCE3EA276B4629E65343E9F537675` |
| `Mesh Chat_0.2.4_x64_en-US.msi` | 20,373,504 | `63DBFE071984FFEA776728BC3262F337B6BFAD114FA6112264B34C44102080ED` |
| `mesh-chat-0.2.4-android-arm64-debug.apk` | 44,252,597 | `5AEC41364390FB73C96FB8B18F3C22FE8ABF11E8A74AB13EAFAE0C87FECBFFEE` |

## Recorded 0.2.5 first-message visibility and delivery-state verification — 2026-10-04

- A physical Windows-to-Android run on 0.2.4 connected both peers, but the
  first direct message did not appear in the conversation. Runtime metadata
  did not establish whether that particular chat command reached the sender's
  service. Separately, code analysis and a deterministic mobile regression
  reproduced a path where a durably saved send remained hidden: on mobile,
  where the desktop's periodic snapshot timer is not used, a stale snapshot
  already in flight could settle after the send event. A successful send could
  also be reported as unsent when only the separate saved-draft cleanup failed.
  Independently, synchronous or delayed direct-message callbacks could replace
  stronger delivery evidence with an older state or associate an old attempt's
  evidence with a newer retry.
- Version 0.2.5 queues a new snapshot after an older in-flight refresh for
  mutations and service events, including the no-timer mobile path. Direct and
  group sends refresh after the durable send, and draft-cleanup failure is
  reported without restoring the composer or inviting a duplicate submission.
  The service re-reads durable state after a native handoff, correlates callback
  evidence to the current native packet, and preserves the strongest state for
  that attempt. These changes retain the 0.2.4 non-blocking reverse-route and
  atomic one-to-one approval fixes.
- The complete automated run passed **116 Python tests** with three documented
  platform/opt-in skips, **27 renderer tests**, TypeScript checking and the
  production renderer build, and all **3 Rust tests**. Regression coverage
  includes a stale mobile refresh already in flight during the first send, a
  trailing mobile snapshot while a service event arrives during refresh,
  successful send with failed draft cleanup, synchronous endpoint/delivered
  callbacks before `send()` returns, a callback followed by a transport error,
  stale callbacks from a prior native attempt, and monotonic evidence for the
  current attempt.
- The opt-in real two-process Reticulum/LXMF direct-LAN harness passed with
  signed TCP hints in both directions. It delivered a direct message and
  application receipt before group activity, completed group invitation and
  join plus a group message, then delivered another direct message and receipt
  after the group flow. This guards the one-to-one/group boundary with the
  reference stack and no hosted relay.
- The Windows x64 executable, MSI, and NSIS package report release 0.2.5; the
  sidecar was built from service release 0.2.5. Extraction checks found that
  both installers contain a sidecar whose
  SHA-256 exactly matches the standalone release sidecar. The development
  installers are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.5, version code 2005,
  minimum API 24, and target API 36, and contains only `arm64-v8a` native
  libraries. APK Signature Scheme v2 verification passed with the unchanged
  development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Inspection also verified that the embedded Python service contains the
  current direct-message retry, endpoint-evidence, and progress-ranking
  constants used by the 0.2.5 callback protections.
- Install 0.2.5 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. A physical
  Windows-to-Android retest using these exact 0.2.5 packages remains pending
  and is required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,149,347 | `F905EF929DA65667E0274664ECB12A0EB79AE813366825ED2ADE712F987E60BE` |
| `mesh-chat.exe` | 4,760,064 | `01E7CA9173D77652E815BBCDA01598365694FD65ADDBA29EA4792A4139E0F500` |
| `Mesh Chat_0.2.5_x64-setup.exe` | 19,625,157 | `D5BF79342F2A3C89CCAF50C166EDF75C1BFDD0C38F744C479A6BC8BFC6A4A941` |
| `Mesh Chat_0.2.5_x64_en-US.msi` | 20,373,504 | `248E139BFA3EF4F2594E3434FCB9BF05D8C364895AB9CF5012E081DCD94110FC` |
| `mesh-chat-0.2.5-android-arm64-debug.apk` | 44,252,597 | `755F77029CE7D21EFBC74781DE56C30E0D2C973F36545C4DAD07FECF6B4FC510` |

## Recorded 0.2.6 phone-to-desktop route and mobile-send verification — 2026-10-04

- A physical Windows-to-Android run on 0.2.5 completed invitation delivery and
  explicit acceptance, but a chat submitted on the phone did not reach the
  desktop. The exact 0.2.6 Windows-to-Android package pair has not yet been
  physically retested, so the release remains gated on that run.
- The route audit reproduced a Reticulum selection condition relevant to the
  failure: an earlier equal-hop nearby-discovery announce can remain selected
  after the outbound TCP client imported from the signed invitation is online.
  This is especially important for a phone that can initiate that full-duplex
  TCP connection but does not accept an unsolicited reverse listener
  connection. Version 0.2.6 gives only explicitly configured, signed-hint TCP
  clients the minimum higher route gravity. Before a direct LXMF handoff it
  waits at most 0.75 seconds for an exact matching client and requests the
  destination only on that interface. It never raises the wildcard LAN
  listener's preference, still authenticates the destination with Reticulum's
  identity and recipient ratchet, and falls back to normal Reticulum routing if
  the signed path does not answer.
- The Android renderer no longer waits for a separate draft cleanup and
  snapshot before displaying a successful send. It immediately reconciles the
  authoritative message returned after the encrypted record is durable and
  keeps that result visible until a snapshot contains the same message ID.
  Direct and group draft persistence now coalesces rapid typing for 200 ms.
  Send cancels an unstarted stale draft save, waits for the sole active write,
  submits exactly once, and writes the empty draft last. The composer is held
  read-only while that ordered operation is active, and an Android IME
  composition Enter event cannot submit incomplete text.
- Mobile-bridge coverage verifies that the raw Android JSON boundary preserves
  both `contact_id` and `text` for `send_message`. Renderer regressions hold the
  draft-cleanup bridge call open while requiring the durable bubble to appear,
  submit three rapid input updates plus a duplicate form event while requiring
  exactly one send and one final empty-draft write, and exercise IME composition
  handling.
- The complete service suite passed **123 tests** with four expected skips: two
  opt-in direct-LAN runs, the opt-in four-peer topology, and the Windows
  `/sys`-topology limitation. The renderer suite passed **30 tests**. TypeScript
  checking, the production Vite build, and all **3 Rust release tests** passed.
- With the direct-LAN opt-in enabled, both real two-process Reticulum/LXMF tests
  passed. The original bidirectional signed-hint run retained approval, direct
  chat and receipt before and after group activity, and the intervening group
  invitation/join/message flow. The new phone-shaped run disabled the joining
  peer's listener and proved phone-to-desktop direct chat and application
  receipts over its single outbound, full-duplex signed-hint TCP client. A
  separate real-stack probe demonstrated the route transition from an earlier
  nearby path to `Private TCP peer 1` after the signed client announce.
- The Windows executable, MSI, and NSIS report version 0.2.6. Extraction checks
  found the same sidecar in both installers, with SHA-256
  `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107`.
  A hidden packaged-desktop launch loaded the interface, started the live
  sidecar, and reported zero JavaScript exceptions. These development Windows
  packages are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.6, version code 2006,
  minimum API 24, and target API 36; contains only `arm64-v8a` native libraries;
  and passes APK Signature Scheme v2 verification with the unchanged debug
  certificate. Inspection also found the embedded signed-route preference
  markers in the packaged service.
- Install 0.2.6 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. A physical
  Windows-to-Android direct-message and group retest using these exact 0.2.6
  packages remains required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,151,729 | `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107` |
| `mesh-chat.exe` | 4,760,576 | `42A320E157B2C2743CA87127E00E8BB1E55E6C2DE8C7F80D9434307933908DCA` |
| `Mesh Chat_0.2.6_x64-setup.exe` | 19,627,219 | `FC613FCB06121172391E92DD7A95BFE7E92E3B60391BD82673A61D22BB79EE43` |
| `Mesh Chat_0.2.6_x64_en-US.msi` | 20,377,600 | `B70F6F5C268D44D9757D429743AF482DE52A129B336C3298E10454F9B7B0447D` |
| `mesh-chat-0.2.6-android-arm64-debug.apk` | 44,252,593 | `C67159232A3F45628F039E97E67914A47487C36BFE6B0ABB0C18EF4DD0441D44` |

## Recorded 0.2.7 desktop-reply concurrency verification — 2026-10-04

- A physical Windows-to-Android run using 0.2.6 successfully delivered the
  phone's first direct message to the desktop. After the desktop user entered a
  reply, the desktop reported **Something went wrong** and the reply did not
  appear on the phone. This is evidence about the 0.2.6 failure only: the exact
  0.2.7 Windows installer and Android APK have not yet been physically tested.
- A later attempted retest also ran 0.2.6, despite occurring after the 0.2.7
  package build. Process inspection proved that Windows was still running the
  raw workspace `src-tauri\target\release\mesh-chat.exe` with file/product
  version 0.2.6 and SHA-256 `42A320E1...`, plus its sibling 0.2.6 sidecar with
  SHA-256 `9901F784...`. Those are the exact recorded 0.2.6 hashes. No installed
  Mesh Chat entry or 0.2.7 program directory existed. The generic **Something
  went wrong** wording also belongs to the 0.2.6 renderer; 0.2.7 reports
  timeout/busy/stopped errors distinctly. This retest therefore reproduced the
  known 0.2.6 failure and is not evidence of a 0.2.7 send failure.
- Content-free runtime metadata showed that the phone's inbound chat and the
  desktop's application receipt were committed, but no outbound desktop chat
  record was created for the failed reply. The service processes remained
  alive while command processing stopped. Code tracing identified a lock
  inversion: LXMF can invoke a native delivery/failure or inbound callback
  while retaining its outbound-processing lock; the callback could wait for
  Mesh Chat's global dispatch lock while the background retry worker held the
  dispatch lock and waited for LXMF. Repeating the bounded signed-route wait
  for a historical backlog also allowed that retry cycle to monopolize the
  command lock beyond the desktop IPC deadline.
- The 0.2.7 network adapter places verified inbound and native status callbacks
  on one bounded dispatcher before they re-enter the service, allowing LXMF/RNS
  to release upstream locks first without waiting for service work or queue
  capacity. Inbound work is prioritized, status transitions retain their order,
  and explicit saturation behavior prevents unbounded memory growth. The durable
  retry loop locks one queued record
  at a time and yields between records, so an interactive renderer command or
  deferred callback can run between historical retries. The transport and
  cryptographic path remain Reticulum/LXMF; this is a concurrency and
  scheduling change, not a fallback protocol.
- The encrypted idempotency journal now retains at most 512 recent mutation
  responses for eight days and prunes pre-existing excess rows when a profile
  opens. Read-only `snapshot`, `search`, and `connection_help` commands are no
  longer journaled. Mutation retries retain their stable command-response
  behavior.
- Desktop timeout, busy, and stopped-service failures now have distinct
  guidance, while the direct-message composer keeps the exact text and tells
  the user to check the conversation before sending again. This avoids implying
  that a timed-out request definitely failed before its durable commit. The
  generic fallback remains for unrelated errors.
- Regression coverage includes native failure and inbound callbacks that must
  return without waiting for a simulated service lock, a historical two-record
  outbox that must yield to an interactive command between records, command
  cache cap and upgrade pruning, and renderer checks for the three actionable
  service errors with exact draft preservation. The phone-shaped real-stack
  harness now performs the reported order: phone-to-desktop chat and receipt
  first, followed by a desktop reply over the same outbound-client/no-listener
  connection; it verifies command IDs, logical message IDs, receipt state, and
  message text in both directions.
- The complete service suite passed **148 tests** with five expected skips: the
  two opt-in direct-LAN configurations, the opt-in exact-packaged-sidecar flow,
  the opt-in four-peer topology, and the Windows `/sys` topology limitation.
  The callback-dispatch suite includes
  exact lock inversion, saturation, delivery-then-failure ordering, bounded
  shutdown, and deferred exact-once vault closure. Python bytecode compilation
  passed. The renderer suite passed **33 tests**, TypeScript checking and the
  production Vite build passed, and all **3 Rust release tests** passed.
- With the direct-LAN opt-in enabled, both real two-process Reticulum/LXMF tests
  passed. The phone-shaped run sent from the outbound-only phone first, received
  its application receipt, then delivered the desktop reply over that same
  full-duplex signed route and received the return application receipt. Both
  framed service commands completed inside the production 20-second desktop
  deadline. The bidirectional-hint run still completed direct chat before and
  after group invitation, join, and group-message activity.
- A new release-only regression launched **two exact frozen 0.2.7 sidecar
  binaries** with separate EFS-protected profiles and communicated exclusively
  through production framed IPC. It completed invitation, approval,
  phone-to-desktop chat and application receipt, then desktop-to-phone reply and
  return application receipt; both send commands completed inside the 20-second
  desktop deadline, both logical message IDs were preserved, shutdown was
  clean, and stderr remained content-free. This closes the gap where the earlier
  real-stack test exercised source services but not the distributed binary.
- Desktop publishing now resolves the actual Cargo target directory, rejects
  inconsistent source versions, a stale executable version, a mismatched
  sidecar, missing version-matched MSI/NSIS files, unsafe target identifiers,
  same-version byte replacement, and post-publication tampering. It publishes
  the executable, sibling sidecar, and installers transactionally to
  `dist/desktop/releases/0.2.7/x86_64-pc-windows-msvc` and atomically updates
  `dist/desktop/current.json`. Seven focused release tests passed. The live raw
  0.2.6 developer output was deliberately left untouched while its process and
  possible draft remained open.
- Version metadata is 0.2.7 in the web package, Python service, Rust package,
  Tauri configuration, Cargo lock entry, renderer expectation, Windows bundle,
  and Android package. The packaged Windows sidecar passed EFS-protected profile
  initialization, signed invitation creation with a direct-LAN hint, graceful
  shutdown, and stderr-redaction checks. MSI and NSIS extraction found the exact
  same sidecar bytes as the standalone build, and both bundled desktop
  executables report file/product version 0.2.7. These development Windows
  packages are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.7, version code 2007,
  minimum API 24, and target/compile API 36; contains only `arm64-v8a` native
  code; and passes APK Signature Scheme v2 verification with the unchanged
  development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Embedded-package inspection found the callback queue, deferred-close,
  bounded-journal, and signed-route markers in the packaged service bytecode.
- Install 0.2.7 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. The packaged desktop
  UI launch was not repeated while the affected 0.2.6 process remained open,
  deliberately preserving the user's unsent draft; installer extraction,
  version inspection, sidecar smoke testing, and automated UI/service tests
  passed. A physical Windows-to-Android reply retest using these exact 0.2.7
  packages remains required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,156,375 | `2A974B58ECAB92FCDB703747AE92F2126FF39FCB8536F3CA620E9C0ED654FE6F` |
| Immutable release `mesh-chat.exe` | 4,760,576 | `B437EA0FBEFC145BF286D3AB9138C14F856C3202261ACAABE7A38E3377527AB4` |
| MSI payload `mesh-chat.exe` | 4,760,576 | `CD063F479087BE43E88C4DE10E78994040CD3CD3E1DC074F0B3F2B2EF1C2B6C3` |
| NSIS payload `mesh-chat.exe` | 4,760,576 | `9C75DD37D5B3320FBBEA183780414E1A331D865667A3523D3AFEFE42BEA04630` |
| `Mesh Chat_0.2.7_x64_en-US.msi` | 20,381,696 | `DABD29E59AA29C10C01F6294DAFE07BF7AE0793AE8CBF1F1AFE579EF6929229D` |
| `Mesh Chat_0.2.7_x64-setup.exe` | 19,633,234 | `7B5C2297AC9C20B43584FD21045476FE25D37C46B0759EE41A00022F2AC41179` |
| `mesh-chat-0.2.7-android-arm64-debug.apk` | 44,252,597 | `663D46518E861E89E0939A26E2FC91D0C1C1E0993F8A3F6DF16CC82B29FF859F` |

## 0.2.8 responsive UI and conversation-management verification — 2026-10-04

- Source metadata is set to 0.2.8 across the web package, Python service, Rust
  package, Tauri configuration, Cargo lock entry, renderer expectation, and
  desktop release-publisher expectation.
- The 0.2.8 verification scope covers Android system-bar-safe sizing and native
  Back navigation, independently scrollable conversation lists, local direct
  and group conversation deletion/restore, and the responsive desktop layout at
  its supported minimum window size. The existing one-to-one and group suites
  remain release gates so these UI and local-record changes cannot regress
  message delivery or membership behavior.
- The final automated run passed **170 Python tests** with five documented
  opt-in/platform skips, **43 renderer tests**, TypeScript compilation, Python
  bytecode compilation, the production Vite build, and all **4 Rust bridge
  tests**. The two signed direct-LAN scenarios and the real three-hop topology
  harness passed separately. The phone-shaped LAN case exposes no reverse
  listener and verifies phone-first delivery followed by a desktop reply over
  the same full-duplex route.
- Conversation-deletion coverage includes direct and group history, drafts,
  queued chat payloads, exact command-ID replay, fresh-inbound reopening,
  send/unhide transaction failure, native LXMF cancellation, trust and signed
  membership preservation, malformed commands, and failed BEGIN/COMMIT vault
  transactions. The exact frozen Windows sidecar also passed an EFS-protected
  two-peer run covering phone-first delivery, desktop reply, local deletion,
  retained contact trust, draft/history removal, fresh-inbound reopening,
  application receipts, and clean shutdown.
- The immutable Windows x64 release contains a 0.2.8 executable and the freshly
  built matching sidecar. Both the NSIS and MSI were extracted: each payload
  reports FileVersion and ProductVersion 0.2.8 and contains the same sidecar
  SHA-256 as the immutable release. The portable ZIP was expanded and its two
  executable hashes were rechecked.
- The Android arm64 APK reports package `com.meshchat.mobile`, version name
  0.2.8, version code 2008, minimum API 24, target/compile API 36, and only the
  `arm64-v8a` native architecture. `apksigner` verifies APK Signature Scheme v2.
  Its certificate SHA-256 is unchanged from 0.2.7:
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`,
  so an in-place upgrade preserves the installed app identity and data.
- Physical Android and Windows checks are pending. They must include portrait
  and landscape sizing, modal/conversation/root Back behavior, a long scrolling
  list, direct and group deletion plus search-based restoration, small desktop
  windows, and bidirectional direct messaging with the exact 0.2.8 packages.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,163,361 | `2D6B89A23721778EC04DC5873FB18F4D783BF11B68516370BAA6FDE1FC6679A3` |
| Immutable release `mesh-chat.exe` | 4,763,136 | `D6A87789BE4738295A04EBD2C5CA6C1487A5F43CE149DC650FB276BF3C722091` |
| MSI payload `mesh-chat.exe` | 4,763,136 | `48F768BF6BCDBC6ABA0D8D2C7CF8C1B629438B7B4F48B69766057623A124AEF4` |
| NSIS payload `mesh-chat.exe` | 4,763,136 | `2A93FE66FD29F8940EEAACF95074DA4BB154F168F81DF1F6720D6C6B4639ABCE` |
| `Mesh Chat_0.2.8_x64_en-US.msi` | 20,389,888 | `D9E963264FCAE92DADDC4643038AC99B1DC7F2DD93B0393B6A685D2D33F97388` |
| `Mesh Chat_0.2.8_x64-setup.exe` | 19,642,155 | `C9401D5250EFC709DE29572BE65695D8054FECF80B464D1D1C8AA09AB62306DA` |
| `mesh-chat-0.2.8-windows-x64-portable.zip` | 20,141,161 | `C475956801516B3764B740BBDEE3F22801DF58D8043D0F551DD20E8C5DC9B875` |
| `mesh-chat-0.2.8-android-arm64-debug.apk` | 44,268,965 | `7977CC17810AFCC8AE77A652D7D4E878226C7F05F2A46FCDC3681ACD2EC0C56D` |

## 0.2.9 encrypted emoji reactions verification — 2026-10-05

- Source metadata is set to 0.2.9 across the web package, Python service, Rust
  package, Tauri configuration, Cargo lock entry, renderer expectation, and
  desktop release-publisher expectation. Android uses version name 0.2.9 and
  version code 2009.
- The reaction extension supports exactly 👍, ❤️, 😂, 😮, 😢, and 🎉 in direct
  chats, private groups, and announcement channels. Each actor has at most one
  active reaction per message. Choosing another emoji replaces it; choosing the
  current emoji again removes it. Active announcement-channel readers may
  react even though only the owner may post messages.
- Reaction state, retries, and inactive tombstones are stored in authenticated
  encrypted records. Network updates remain authenticated, individually
  encrypted Reticulum/LXMF traffic; the extension adds no hosted service or
  fallback protocol. The native source determines the actor, and group updates
  require both current active membership and entitlement to the target
  message's historical membership manifest.
- The complete Python suite passed **205 tests** with **5 documented skips**.
  An independent focused reaction/deletion audit passed **86 tests** with **2
  documented skips**. Python bytecode compilation also passed.
- The renderer suite passed **47 tests**, including keyboard-accessible picker
  behavior, replacement/removal, direct/group/channel permissions, Android
  Back handling, and a 320×480 clipping regression. TypeScript checking and the
  production Vite build passed.
- All **4 Rust release tests** passed. Both opt-in signed direct-LAN scenarios
  passed (**2 tests**), and the opt-in real three-hop topology passed (**1
  test**).
- Delivery of a reaction is best effort after authenticated endpoint evidence.
  An old peer, crash, overload, or group-manifest ordering race may therefore
  cause a reaction update to be missed without weakening ordinary message
  delivery. A malicious same-actor, same-revision equivocation is
  first-seen-wins; a later higher revision restores convergence.
- The exact frozen 0.2.9 Windows sidecar passed the EFS-protected two-peer
  packaged harness (**2 tests passed**). Through production framed IPC and the
  native network path it completed bidirectional chat and receipts, phone 👍
  add, desktop 😂 add, desktop replacement with ❤️, phone removal, convergence
  after every update, local deletion/reopen, content-free stderr, and clean
  shutdown.
- The immutable Windows executable, sidecar, MSI, NSIS, and portable ZIP were
  inspected and hashed. The immutable, MSI-payload, and NSIS-payload
  executables all report file/product version 0.2.9. Both installers contain
  the exact immutable sidecar bytes. The bundle-specific executable hashes
  differ because Tauri patches bundle-type metadata. The development
  executable and installers are not Authenticode-signed.
- The clean Android APK reports package `com.meshchat.mobile`, version name
  0.2.9, version code 2009, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verification passed with the
  existing debug certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Inspection of its Chaquopy `app.imy` found the new `mesh_chat/reactions.pyc`,
  the `set_message_reaction` command allowlist/dispatch, group-reaction code,
  and reaction snapshot aggregation.
- **Pending — physical devices:** test the exact 0.2.9 Windows and Android
  packages in both directions for direct, group, and announcement-channel
  reaction add/replace/remove, compact counts, picker placement, Back behavior,
  offline recovery, and continued ordinary chat with an older peer. A signed
  iOS package and physical iOS test still require macOS/Xcode.

| 0.2.9 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,182,181 | `34E0A2B7DF8BAD5503EA8D0F40AD73DAB16EDA3A255875A726426FAE3EF891A6` |
| Immutable release `mesh-chat.exe` | 4,766,720 | `3A8C69CF8762560EB9364E0146260C91E481F3DFACC39708A90AC9703701BCA7` |
| MSI payload `mesh-chat.exe` | 4,766,720 | `65C4388B7D39B786C5CE695223FAA6709EB4654C410D5BCD4F8DC73E59C1AB02` |
| NSIS payload `mesh-chat.exe` | 4,766,720 | `4F6516D48C4FE8F08C250A57E9DBA710F3B4CDB8AEB72379CD40D4C3BE9BFCD2` |
| `Mesh Chat_0.2.9_x64_en-US.msi` | 20,414,464 | `B5F97E3DDA5A5F45BCACA7821EE03946145A1EB8221D508E322DD1F8020204CD` |
| `Mesh Chat_0.2.9_x64-setup.exe` | 19,663,792 | `1AB486BCFE9BDC5C44A27C6795219A4D4DF15D4849B0AE17659DE03A65E81443` |
| `mesh-chat-0.2.9-windows-x64-portable.zip` | 20,164,196 | `79E9B343EE094FB4A42E67EE845EDAA0A1DA6564B79E3650A23590A920CC4017` |
| `mesh-chat-0.2.9-android-arm64-debug.apk` | 44,318,285 | `6BFE002A17A9EB4F6A098ABCD144F5D60C0072AF358089A808911B3D29171A83` |

## 0.2.10 expanded Unicode emoji reactions verification — 2026-10-05

- Source metadata is set to 0.2.10 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  and desktop release-publisher expectation. The Android package reports
  version name 0.2.10 and version code 2010.
- The six familiar quick reactions remain one click away. **More emojis** opens
  eight searchable categories with 253 unique common choices, and **Use emoji
  keyboard** accepts any official fully-qualified Unicode Emoji 18.0 sequence.
  The picker is viewport-clamped and independently scrollable, including with
  the Android keyboard open, and Android Back closes the nested catalog before
  the reaction picker and conversation.
- The renderer and service carry the same exact 3,963-entry catalog in official
  source order. Independent comparison against Unicode's Emoji 18.0
  `emoji-test.txt` found zero missing and zero extra entries. The source SHA-256
  is `8F3735CDA1F92A779D78AF67CF86066BB1F07143DC22F2AC29394D9BC57AB21A`;
  the newline-joined catalog SHA-256 is
  `D4F4B496CF4A6F621575353540A4F778F3461535AEEBB62DE408369BD40608F9`.
  Exact membership, a 16-codepoint limit, and a 64-byte UTF-8 limit reject
  component-only, unqualified, minimally-qualified, text-presentation,
  adjacent-emoji, redundant-selector, invented joiner, and invented tag
  sequences instead of normalizing or repairing them.
- Direct, private-group, and announcement-channel authorization and encryption
  are unchanged. Reactions still use authenticated, individually encrypted
  Reticulum/LXMF traffic and encrypted local state; there is no hosted reaction
  service or fallback protocol. Snapshot aggregation now counts arbitrary
  supported emoji deterministically while keeping legacy quick reactions first.
- The complete Python suite passed **258 tests** with **6 documented skips**,
  and Python bytecode compilation passed. Coverage includes command, protocol,
  storage, pending/replay, direct, group, announcement, replacement/removal,
  invalid-catalog, and dynamic snapshot cases.
- The renderer suite passed **55 tests** across four files. It iterates every
  one of the 3,963 valid entries, checks the generated-catalog fingerprint,
  rejects adversarial near-matches, and covers search, categories, custom
  entry, focus/keyboard behavior, Android Back, and compact mobile layouts.
  TypeScript checking and the production Vite build passed with 1,817 modules.
- All **4 Rust release tests** passed. The two opt-in signed direct-LAN
  scenarios passed (**2 tests**), and the opt-in real three-hop topology passed
  (**1 test**).
- The exact frozen 0.2.10 Windows sidecar passed the EFS-protected packaged
  two-peer harness (**2 tests passed**). Through production framed IPC and the
  native network path it completed phone-first and desktop-reply chat plus
  application receipts; a multi-code-point 👩🏽‍🌾 reaction; desktop 😂 add and
  replacement with ❤️; removal and convergence; local deletion/reopen;
  content-free stderr; and clean shutdown.
- The frozen 0.2.10 sidecar also passed the EFS-protected mixed-version harness
  against the exact 0.2.9 sidecar (**3 packaged tests passed** when run together).
  Ordinary chat remained bidirectional before and after reaction traffic, the
  original six reactions interoperated in both directions, 0.2.9 safely ignored
  an expanded 👩🏽‍🌾 reaction, and both peers stayed alive and shut down
  cleanly without private stderr output.
- The immutable Windows application, sidecar, MSI, NSIS, and portable ZIP were
  published and hashed. The application and NSIS executable report file and
  product version 0.2.10; the MSI file table reports application version
  0.2.10.0. The immutable sidecar equals the freshly built external binary.
  The release, MSI, and portable ZIP contain the 2,401-byte Unicode notice.
  The Windows development artifacts are not Authenticode-signed.
- The Android APK reports package `com.meshchat.mobile`, version name 0.2.10,
  version code 2010, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Its Chaquopy archive contains the exact Emoji 18 validator, dynamic reaction
  aggregation, and command path. Its native library is from the fresh Android
  web/Rust build, and the APK embeds `assets/THIRD_PARTY_NOTICES.md`.
- Compatibility is additive: 0.2.9 peers continue exchanging the original six
  reactions but ignore other Emoji 18 choices; earlier peers ignore reactions;
  ordinary chat continues. Install 0.2.10 on every participating device for
  the expanded set.
- **Pending — physical devices:** test the exact 0.2.10 Windows and Android
  packages in both directions for catalog/search/custom entry, direct, group,
  and announcement reaction add/replace/remove, compact counts, picker
  placement, nested Back behavior, offline recovery, and 0.2.9 compatibility.
  A signed iOS package and physical iOS test still require macOS/Xcode.

| 0.2.10 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,199,655 | `DEBC7A9704978794BD4B2D383AC959AD94BDD4BBB1909D6A28006B5DF9310EBB` |
| Immutable release `mesh-chat.exe` | 4,778,496 | `8677B02B191E2BADDA909F6FACE76A6BC8B8E8B5A100139A00B83A04873842C7` |
| `Mesh Chat_0.2.10_x64_en-US.msi` | 20,443,136 | `BF6CD5FE81840BCD08A433A8D651D33E1A5B04898941A64F4FD3E0C4C1BE8986` |
| `Mesh Chat_0.2.10_x64-setup.exe` | 19,695,613 | `6B39A87B69167E0C0059AF64FF1AE5E4B340E8EC9AC8D682B1FD5D6ED705ACD3` |
| `mesh-chat-0.2.10-windows-x64-portable.zip` | 20,208,096 | `F41157EE015C486E7036F7DE9E496723D3D1DBB5A60D95714D8B3D265176CA45` |
| `mesh-chat-0.2.10-android-arm64-debug.apk` | 44,368,811 | `8C20E7297D22F1ABB0818A0782590C5DC7C59F36C63A08060A8D11BC4C506B44` |
| `THIRD_PARTY_NOTICES.md` | 2,401 | `987A3B010A0ECB5FFA13D3F4504E5D0F1251895A8C4172E1A91ED0626B520DF8` |

## 0.2.11 bundled offline emoji artwork verification — 2026-10-05

- Source metadata is set to 0.2.11 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  and desktop release-publisher expectation. The Android release target uses
  version name 0.2.11 and version code 2011.
- Reaction identity and compatibility are unchanged from 0.2.10: the exact
  fully-qualified Unicode Emoji 18.0 sequence remains the value validated,
  counted, encrypted in the vault, and transported through Reticulum/LXMF.
  No artwork path, sprite coordinate, or vendor identifier enters protocol or
  persistent reaction state.
- The renderer now uses local palette-optimized sprite sheets derived from
  Twemoji 17.0.3 at pinned commit
  `b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`. One 16×16 curated sheet covers
  all **253 of 253** picker choices. Eight 32×16 general sheets cover another
  3,691 sequences, for **3,944 of 3,963** fully-qualified Emoji 18 sequences
  with bundled pictorial artwork.
- The remaining 19 sequences are new Emoji 18 entries not present in that
  pinned Twemoji release. Each has a generated catalog name and deterministically
  renders as a neutral tile marked **18**. Loading, local-image failure, and
  forced-colors behavior retain a neutral fallback rather than exposing a tofu
  glyph. The fallback does not alter or collapse the underlying Unicode value.
- All artwork URLs produced by the generated lookup are app-local. No Twemoji
  CDN, font download, analytics request, or other artwork network path is used.
  Settings displays **Emoji artwork: Twemoji (CC BY 4.0)**. The source tree
  includes `ATTRIBUTION.txt`, the complete graphics license, pinned source
  metadata, and the Twemoji section in `THIRD_PARTY_NOTICES.md`.
- The frontend suite passed **64 tests across 6 files**. It covers all 253
  picker mappings; the exact 3,944-artwork/19-fallback partition across all
  3,963 accepted sequences; local-only URLs and sprite bounds; source/version
  pins; deterministic loading, missing, error, and accessible-name fallbacks;
  reaction-chip fallback labeling; and the Settings attribution. TypeScript
  checking and the production Vite build also passed.
- The package-artwork verifier passed **3 tests**. It rejects missing logical
  asset paths, matches Brotli-decoded package bytes to the source assets, and
  can verify a final stripped native binary without retaining its Cargo build
  directory.
- The Python service suite passed **261 tests** with **6 documented skips**.
  Its artwork tests independently verify the manifest, the expected 1+8 PNG
  set, every recorded file size and SHA-256, sprite dimensions, generated
  metadata fingerprint, attribution, and third-party notice. The service and
  protocol tests continue to cover all 3,963 Unicode reaction values and do not
  treat artwork coverage as a transport allowlist.
- All **4 Rust release library tests** passed with the serialized release test
  command. The exact frozen 0.2.11 Windows sidecar then passed the
  EFS-protected package harness against itself and the mixed-version harness
  against the exact 0.2.9 sidecar (**3 packaged tests passed**). Phone-first
  delivery, the desktop reply, application receipts, reaction add/replace/
  remove convergence, deletion/reopen, legacy expanded-reaction handling,
  content-free stderr, and clean shutdown all passed through production IPC.
- The Windows x64 application, sidecar, MSI, NSIS installer, and portable ZIP
  were built and published under the immutable 0.2.11 release directory. The
  release manifest and `current.json` hashes validate; raw, MSI, NSIS, and
  portable application payloads report file/product version 0.2.11; their
  sidecars and notices match the immutable files. The packages are development
  builds and are not Authenticode-signed.
- The package-artwork verifier decoded and matched all **12** local artwork
  files (**1,947,195 source bytes**) in the immutable Windows executable and
  the application extracted independently from the MSI, NSIS installer, and
  portable ZIP. Those files are the nine sprite sheets plus the integrity
  manifest, attribution, and full graphics license. Source and production
  renderer inspection found no Twemoji CDN or other remote artwork reference.
- The Android arm64 APK reports package `com.meshchat.mobile`, version name
  0.2.11, version code 2011, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Its packaged notice exactly matches the source notice. The verifier decoded
  and matched all 12 artwork files directly from the stripped native library
  extracted from the exact APK; that library is 14,258,592 bytes with SHA-256
  `0FB9B99AECB1E61C3D4848704D5F41793B5D7BA79A22AAFC5601F2EC55A7687B`.
- **Pending — physical devices:** test the exact 0.2.11 Windows and Android
  packages for quick-picker, searchable catalog, reaction-chip, 19-entry
  fallback, loading/error, compact layout, forced-colors where available, and
  direct/group/announcement add-replace-remove flows in both directions. The
  signed iOS build and physical iOS rendering test still require macOS/Xcode.

| 0.2.11 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,199,967 | `2322827C7A0EB9602A92E6C8516B1CDCCC4AFE8B8F8FD5FDA827506C41640C64` |
| Immutable release `mesh-chat.exe` | 6,702,080 | `6DC69994FE4AEDB7A4C2DE0C0F8A7B0E620CE5D3BF3C2C16C0C420CD366C8AB3` |
| `Mesh Chat_0.2.11_x64_en-US.msi` | 22,364,160 | `D7396792D706CAF799C93EE9D6ADC191A9B37732847172DCF7D8A66F6AA820BD` |
| `Mesh Chat_0.2.11_x64-setup.exe` | 21,626,898 | `00C084262B106C81F5D645F32C5B578887D8E0286C34CAA09BEF34F8026C67CD` |
| `mesh-chat-0.2.11-windows-x64-portable.zip` | 22,127,373 | `0B96FEF68D887AAA0F7E1717BB54697AFD3B9D30F9570864AAE52E1169882337` |
| `mesh-chat-0.2.11-android-arm64-debug.apk` | 46,300,720 | `59B0DC9D6C516AED846E72C908C400C0571FB014E8AC0F55E438FE947C08DC75` |
| Packaged `THIRD_PARTY_NOTICES.md` | 3,239 | `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44` |

## 0.2.12 contact management verification — 2026-10-06

- Source metadata is set to 0.2.12 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  desktop release-publisher expectation, and generated Android metadata.
  Android uses version name 0.2.12 and version code 2012.
- The shared responsive Contacts dialog searches saved contacts and supports
  local rename, mark/remove verification, block/unblock, open conversation,
  and confirmed contact deletion. Desktop and mobile use the same React bundle;
  the mobile Back path closes the dialog before leaving the app.
- Service commands cover update, verify/unverify, block/unblock, and delete.
  Deletion removes the direct conversation, messages, drafts, receipts, and
  contact record atomically, retains group identity/membership, and refuses a
  contact still referenced by a pending group invitation. Blocking preserves
  the preceding trust state so unblocking restores it.
- The complete frontend suite passed: 6 files and 66 tests. The complete
  service suite passed: 265 tests, with 6 environment-gated tests skipped.
  This includes the dedicated contact-management service tests and Contacts UI
  interaction coverage.
- Windows x64 release packaging produced and immutably published the EXE,
  sidecar, MSI, and NSIS installer at
  `dist/desktop/releases/0.2.12/x86_64-pc-windows-msvc`. The release manifest
  hash is
  `787E9DA2E44364DA1FE827590E8379A89A93D90417C8DC26D930EAA957D5783F`.
  The NSIS update installed successfully over 0.2.11 without clearing the
  profile; the installed executable reports product version 0.2.12 and was
  launched from `%LOCALAPPDATA%\Mesh Chat`. The stale Start-menu shortcut was
  corrected to that installation.
- The Android arm64 debug APK reports package `com.meshchat.mobile`, version
  name 0.2.12, version code 2012, minimum API 24, target/compile API 36, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`,
  so it can upgrade the prior debug build in place. The stripped native library
  is 14,266,024 bytes with SHA-256
  `C73777847ED3C485ADA9ADDD0CDB660D5906807C1CADE1BFFDE8C6BA141D62BA`.
- Package inspection matched the exact compressed JavaScript asset containing
  `Search contacts`, `Delete contact`, and `0.2.12` inside the APK native
  library. The artwork verifier also decoded and matched all 12 local artwork
  and notice files from that exact library. The Android helper now requests
  `--split-per-abi`, matching the arm64 artifact path it publishes and
  preventing reuse of a stale split APK.
- **Pending — physical devices:** no Android device was attached, so the exact
  APK still needs an in-place `adb install -r` and a physical Windows↔Android
  contact-management/interoperability run. The APK is debug-signed for direct
  testing; a production AAB still requires a private release keystore. macOS,
  Linux, and iOS native package validation also remain pending.

| 0.2.12 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,203,625 | `D8F5457F43777D6289E3A1F80A2DAE7CDEBAB9BA4EA222E05F930E43A9D0FE00` |
| Immutable release `mesh-chat.exe` | 6,704,128 | `A4266B18A30BA5984406F95C162825B2E3A51897FAEBE0362EA5E2D0AD55DD0A` |
| `Mesh Chat_0.2.12_x64_en-US.msi` | 22,372,352 | `5081825AA72F99882671A4EA88C33C484D50C184FC2F773438737619FC72F479` |
| `Mesh Chat_0.2.12_x64-setup.exe` | 21,633,130 | `451A8DE7DDC082FD7918BDD8E3AE31954F425ED7C5EDF6038500A1C23A2056AD` |
| `mesh-chat-0.2.12-android-arm64-debug.apk` | 46,300,716 | `51D4C98F29CC601B7461B008C246D365B9FE816AE4E167927DB389528B290963` |
| Packaged `THIRD_PARTY_NOTICES.md` | 3,239 | `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44` |

## Automated focused coverage

- IPC frame boundaries, concatenation, malformed JSON and truncation.
- Invitation link/text/file equivalence, signatures, destination binding, expiry, and hint validation.
- Authenticated local record round trips, plaintext scanning, wrong-key
  failure, mutation command deduplication, bounded command-journal retention,
  and upgrade-time pruning.
- Mobile bridge validation plus authenticated mobile record round trips and plaintext scanning.
- App payload rules, conversation-ID stability, and receipt constraints.
- Full deterministic two-peer one-to-one flow from invitation through approval,
  direct chat, application receipt, and delivered state, with an assertion that
  no group records are created.
- Approval regressions covering asynchronous attachment of up to eight signed
  reverse TCP routes, atomic trust/acceptance persistence, exactly one
  `CONTACT_ACCEPT`, in-flight handoff suppression, contained route/transport
  failures, dirty-route retry, and bounded signed-route preference before the
  first direct-chat handoff.
- Concurrency regressions covering deferred native status/inbound callbacks
  that cannot retain an LXMF/RNS lock while waiting on the service, plus
  per-record retry locking and a scheduling yield between queued records.
- First-message regressions covering a stale snapshot already in flight on the
  no-timer mobile path, a trailing refresh for a concurrent service event,
  durable send versus draft-cleanup failure, synchronous callback-before-return
  ordering, immediate reconciliation of the durable send result, bounded draft
  coalescing, duplicate-submit suppression, Android IME composition, callback-
  then-error handling, native-attempt correlation, and monotonic endpoint/
  delivery evidence.
- Group-document canonicalization, signature and destination binding, manifest
  membership/role limits, targeted invite/join consent, and strict group
  application-field combinations.
- Reaction coverage includes exact membership in the 3,963 fully-qualified
  Unicode Emoji 18.0 sequences, independent codepoint/byte bounds, adversarial
  near-match rejection, native-source actor binding, direct/group namespace separation, historical group-message
  entitlement, active-member and announcement-reader permissions, one-state
  replacement/removal, monotonic revisions, encrypted tombstones, bounded
  pending work, receipt compaction, restart/offline replay, old-peer rejection,
  and snapshot indexing that avoids per-message record scans.
- Offline artwork coverage verifies the pinned Twemoji source and CC BY 4.0
  attribution, every sprite sheet against its manifest size/hash/dimensions,
  all 253 curated picker choices, all 3,944 locally illustrated Emoji 18
  sequences, the complementary 19 named neutral fallbacks, local-only asset
  URLs, deterministic sprite coordinates, loading/error behavior, and Settings
  disclosure. The dedicated package verifier also matches every decoded asset
  in the final Windows and Android native binaries; physical rendering remains
  a separate release gate.
- In-process group-service flows cover targeted invitation, join acceptance,
  owner epoch advancement, recipient fan-out, inbound commit, recipient-specific
  application receipts, two simultaneous invitees with reversed epoch arrival,
  accepted-invite replay after removal, remove/leave/close, old-epoch
  equivocation freeze, restart terminal-state preservation, application-level
  retry, and strict duplicate metadata. These use recording network doubles and
  do not replace the real-network group gates above.
- Native status mapping that distinguishes propagation storage, endpoint proof, and application delivery.
- RNS profile isolation, no inherited/public interface, and independent role settings.
- UI wording distinctions for delivery and contact consent.
- Optional real two-process RNS/LXMF direct-LAN flows with signed TCP hints:
  the bidirectional route with timed approval, direct chat before and after a
  group invitation/join/message flow, and application receipts; plus a
  phone-shaped joining peer with an outbound client and no reverse listener
  that sends the first chat and then receives a desktop reply with application
  delivery confirmed in both directions.
- Optional exact-package flow using two frozen sidecars, protected profiles,
  production framed IPC, phone-first delivery, and the desktop reply inside the
  real command deadline.
- Real-stack route-preference probing in which an earlier equal-hop nearby path
  remains selected at equal gravity, then is replaced by the exact signed TCP
  client after its minimally preferred announce.
- Optional real RNS/LXMF A→B→C→D delivery using only A–B, B–C and C–D interfaces, with ratchet presence, three-hop assertion, signature validation, and intermediate persistent-file plaintext scan.

## Deterministic delivery pipeline verification — 2026-10-06

- `python scripts/release.py check --expected-version v0.2.12` passed and
  reported consistent npm, Tauri, Cargo, Cargo-lock, Python, and Android version
  metadata. It also selected Node 24.19.0 and pnpm 11.19.0 without relying on
  the host's obsolete default Node installation.
- The complete maintained verification command passed: 277 Python tests, 6
  intentionally skipped environment/device tests, 66 frontend tests, 3 package
  artwork-verifier tests, TypeScript compilation, and the production web build.
- The new version-transaction, Android immutable-publisher, and desktop
  publisher suites contributed 19 focused passing tests. They cover invalid and
  inconsistent versions, Android version-code derivation, root-only Cargo.lock
  mutation, preservation of unrelated metadata, same-version/different-byte
  rejection, manifest/current pointers, and tamper detection.
- The first sidecar run populated the content-addressed PyInstaller cache in
  about 34 seconds. The immediately repeated build verified and reused it in
  about 4 seconds instead of running PyInstaller again.
- The initial Vite production bundle completed in 4.86 seconds. The immediately
  repeated build reused its input digest and completed in under one second.
- The existing 0.2.12 Android APK was adopted into the new immutable layout at
  `dist/mobile/releases/0.2.12/android-arm64-debug`; its versioned manifest,
  checksum, current pointer, and documented top-level alias all verified.
- The generated Android Gradle launcher no longer contains a developer-specific
  absolute Node path. Repeated generated-project preparation produced the same
  native input digest, confirming that unchanged files are not rewritten.
- CI and tag/manual release workflows are present and use the same repository
  release driver. The release job tests once, then packages desktop and Android
  concurrently with pnpm, pip, Rust, Gradle, SDK, and NDK caches. They have not
  run remotely because this workspace currently has no commit history or Git
  remote; that remains an external activation prerequisite rather than an LLM
  build step.

## Workspace increment 2 verification — 2026-10-07

- The complete Python suite passed with **290 tests passed and 6 intentional
  environment/device skips**. Thirteen focused workspace tests cover deterministic
  canonical fixtures, tamper and noncanonical rejection, profile isolation,
  verified unknown-source join admission, two-service join and chat, reversed
  control arrival, bounded paging, stale cursors, receipt aggregation without
  delivery scans, operation replay, genesis/checkpoint authority pinning,
  active-source admission, fork resistance, scoped join decisions, actionable
  sync state, close invalidation, and destructive local-data redaction. The
  increment-two topology test admits seven people from concurrent invitations
  referencing the same checkpoint, proves ordered catch-up to all eight
  replicas, propagates metadata and approved display-name changes, returns a
  signed name-request decline, removes one member, materializes a cancelled
  delivery leg, and delivers a member-authored event to the remaining peers
  while the owner process is offline. The sender then restarts with its
  committed event and frozen delivery legs intact, and the restarted owner
  receives the withheld canonical event after reconnect.
- The six frontend source suites passed with **76 tests**, including the
  disclosure-first workspace create flow, bounded message loading, attachment
  button/drop/paste rejection, paused-state action gating, close confirmation,
  scoped invalidation, and stable retry event and operation IDs. The workspace
  refresh regression test verifies that desktop polling and draft invalidations
  do not reload the open `#general` page, while message invalidations update it
  in the background without clearing visible messages. TypeScript project
  compilation and the Vite production build also passed. Increment-two UI
  coverage verifies independent invitation revocation/creation, owner removal
  and display-name decisions, member name requests, opt-in propagation-node
  consent, per-person/per-device delivery disclosure, and replacement of a
  removed member when eight historical member records remain.
- The Rust library suite passed with **6 tests**, including every workspace
  renderer command, mobile workspace rejection classification, and workspace
  deep-link admission. `cargo fmt --check` passed.
- The maintained release driver built and immutably published desktop 0.2.16.
  WiX `light.exe` completed CAB creation, MSI database generation, and ICE
  validation when the build had Windows Installer access; no ICE suppression or
  alternate packaging path was used. The earlier `LGHT0217` failure was isolated
  to ICE validation being unable to access Windows Installer from a restricted
  process; CAB creation and MSI database generation had already succeeded. It
  was an execution-environment failure, not a malformed MSI source. The final
  run published a 22,478,848-byte MSI with SHA-256
  `21D590178B248A8C6D0366B527BC5403D50C315B17619714B6580E4EE329BA98`
  and a 21,739,441-byte NSIS installer with SHA-256
  `E3199396A213E46F054563A2724C6226B99D6D5EAE7E2C5DA76B5854C845052D`.
- The immutable portable `mesh-chat.exe` was launched with its sibling sidecar;
  process inspection confirmed product version 0.2.16 and both processes came
  from the 0.2.16 release directory. Windows automation found the running Mesh
  Chat window, but the capture helper failed its initial attempt and one fresh
  window retry with `0x80004002`, so this run does not claim an interactive
  native-window walkthrough. Renderer and eight-service workspace flows passed.
- Physical two-install delivery, restart at injected commit boundaries,
  partition recovery, package extraction, and protected-profile plaintext scans
  remain release gates; automated tests do not claim those device results.

## Workspace increment 3 verification — 2026-10-07

- The maintained suite passed **295 Python tests with 6 intentional
  environment/device skips**, **79 frontend tests**, all 3 package-artwork
  verifier tests, TypeScript compilation, and the Vite production build. The
  Rust release suite passed all **6 tests**, and `cargo fmt --check` passed.
- Protocol and service coverage exercises public-channel creation, browsing,
  subscription, rename/topic changes, two-party management transfer, authority
  recovery, terminal archive, active-channel capacity recovery, retained-channel
  summary paging, exact policy enforcement, unauthorized signed events, stale
  and forked controls, stable duplicate-name disambiguation, unread persistence,
  restart, partitions, reversed control/event arrival, quarantine draining, and
  eventual signed-chain fetch convergence. Existing canonical fixtures and wire
  kinds remain byte-for-byte unchanged; new kinds are additive and bounded.
- The opt-in network topology harness passed its isolated peer run, and both
  direct-LAN harness scenarios passed. The exact immutable 0.2.17 packaged
  sidecar passed the process-level phone-first/desktop-reply test under Windows
  protected storage. The full three-test packaged compatibility harness also
  passed against its intended pre-expanded-reaction 0.2.9 baseline.
- The first release attempt stopped before native packaging while pnpm rebuilt a
  partially reconciled `node_modules` tree without registry access. Restoring
  the lockfile-pinned tree resolved that environment failure. A later restricted
  run linked the application but stopped when WiX `light.exe` could not access
  Windows Installer for ICE validation. The same maintained pipeline then ran
  with Windows Installer access and completed both formats with ICE checks still
  enabled; no WiX source, validation flag, or alternate packaging path was used.
- The maintained release driver immutably published desktop **0.2.17**. The MSI
  is 22,511,616 bytes with SHA-256
  `2FF6554841148AA6EF57A803F3BE0ABCC07E43CC2BA2DB9C214BCA41190EEA33`.
  The NSIS installer is 21,775,013 bytes with SHA-256
  `30A72CEEC05FA54C8B3F1F0910EDB9239546BD30D8296214BACE1A83CD9F40B6`.
  The portable application reports product/file version 0.2.17, and the current
  pointer records manifest SHA-256
  `831CBC1AC975C042F8477B418814754B4FC101BEF1BC8554EA98CD4AC87D966D`.
  Immutable 0.2.16 artifacts remain present and were not overwritten.
- This run exercised the packaged service processes but did not stop the user's
  existing 0.2.16 single-instance desktop session, install either 0.2.17
  installer, or obtain a successful native-window capture. It therefore does
  not claim an interactive walkthrough. Production signing, physical
  multi-install discovery/delivery, real-device restart and partition recovery,
  packet capture, protected-profile plaintext scans, and Windows-to-Android
  workspace validation remain release gates.

## Workspace increment 4 verification — 2026-10-07

- The complete maintained verification passed **298 Python tests with 6
  intentional environment/package skips**, **80 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. The Rust boundary passed `cargo check`, `cargo fmt
  --check`, and all **6 release-profile tests**.
- Private-channel protocol and service coverage now exercises canonical signed
  rosters, exact private audiences, one-to-eight member bounds, creation,
  manager-only roster changes, member admission without predecessor metadata or
  message backfill, control-before-event quarantine across restart, duplicate
  and delayed delivery, unread persistence, metadata changes with delayed
  historical events, member-only transfer, owner recovery only from inside the
  roster, voluntary leave, scoped pending-leg cancellation, terminal archive,
  nonmember storage/snapshot exclusion, and a valid channel-local fork that
  leaves the workspace active. Renderer coverage creates a private channel,
  manages its signed roster, and gates leave, transfer, recovery, archive and
  read-only states.
- The opt-in isolated three-hop RNS/LXMF topology passed. Both direct-LAN
  scenarios passed: bidirectional signed hints and the phone-shaped outbound
  client with no reverse listener. The exact immutable 0.2.18 packaged sidecar
  passed the phone-first/desktop-reply harness and its current-versus-0.2.9
  compatibility flow. A restricted first attempt correctly failed closed with
  `protected_storage_unavailable`; the required native EFS run passed all 3
  packaged-harness tests.
- The maintained release driver published desktop **0.2.18** with WiX ICE
  validation and NSIS packaging enabled. The 22,528,000-byte MSI has SHA-256
  `9E180DA9581B266C2C3F0C29474F0B1E54FDB31037B65837AEEA72DA3E3749DE`.
  The 21,790,733-byte NSIS installer has SHA-256
  `95ECD02F768DCECDDDAD2B8F7C84CB76D8251247790EBB14F5D836178212E113`.
  The portable application reports file/product version 0.2.18 and hashes to
  `B074D515455A54714BDCDA6D63B99F5A8B79E6C786A0384005221B488288B263`;
  the sidecar hashes to
  `C78EA75F111939C2D4483A50512C897819EEE8FF620774347FB496F4C54DE8B7`.
  The immutable manifest hashes to
  `1B4A9A6263973BD9E1BD0FE1A9050FD710BFB4A78875FF9B2E197B3CFE6DCA45`.
- No installer was launched and no existing Mesh Chat process or profile was
  altered. Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install private-channel partition/reconnect,
  packet capture, and protected-profile plaintext scans remain release gates.

## Workspace increment 5 verification — 2026-10-08

- The complete maintained verification passed **300 Python tests with 6
  intentional environment/package skips**, **81 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. The Rust boundary passed `cargo fmt --check` and all **6
  release-profile tests**.
- Protocol and service coverage verifies the deterministic workspace-scoped
  two-member conversation UUID, null channel digest, exact sorted audience,
  author and current-participant authorization, participant-only fan-out,
  independent sealed paging/drafts/unread state, local hide and People-based
  reopen, restart persistence, bidirectional delivery, removal-driven read-only
  state, and cancellation of unhanded DM legs. Both endpoints retain empty
  global Contact lists. Renderer coverage opens from People, sends, hides,
  reopens, and confirms the Contacts view remains unchanged.
- The opt-in isolated three-hop RNS/LXMF topology and both direct-LAN scenarios
  passed. The exact immutable 0.2.20 packaged sidecar passed the
  phone-first/desktop-reply harness and the current-versus-0.2.9 compatibility
  flow under native Windows EFS; all 3 packaged-harness tests passed. The final
  application executable also matched all 12 bundled artwork, metadata, and
  license files.
- The maintained release driver immutably published desktop **0.2.20** with WiX
  ICE validation and NSIS packaging enabled. The 22,536,192-byte MSI has
  SHA-256
  `7C22F0FE9B8E4A9C78B259E8FECFFC12DEF1054604144544E28BB94527C48D00`.
  The 21,799,832-byte NSIS installer has SHA-256
  `5E5C85C39F582DE6ED32450F84ED3FBCB1EAA31249B149D69D0F7E86C9D74D95`.
  The portable application reports file/product version 0.2.20 and hashes to
  `D90D5DBB3B184F8983DBEEE46EA73D1177F1BB9B2076A0BE3DE49DB1EFAE190E`;
  the sidecar hashes to
  `184D9809CB83AF9B3E1605B0D503A14ACE3E248102F9491D6589AE19790FA148`.
  The immutable manifest hashes to
  `0850FFFAD09E8EA9EE3DDAED129DC6A8A66BA8CD8FDD1E98809C5825318DC773`.
  The earlier immutable 0.2.19 build was superseded before installation after
  the final authorization review established that channel posting policy must
  not suppress active-participant workspace DMs; 0.2.20 contains that fix.
- No installer was launched and no existing Mesh Chat process or profile was
  altered. Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install DM partition/reconnect, packet capture,
  and protected-profile plaintext scans remain release gates.

## Workspace increment 5 corrective verification — 2026-10-08

- Final review found that confirmed local workspace removal did not include the
  new sealed `workspace_direct` summary records, and that cancellation of a DM
  leg after removing its sender could relabel the remaining recipient in local
  delivery details. Version **0.2.21** deletes the DM summaries with the rest of
  the workspace, preserves the actual recipient identity in cancelled delivery
  state, rejects a delayed unseen DM after removal, and adds regressions for all
  three behaviors. The renderer also rejects pasted attachments in DMs and uses
  accurate read-only wording for workspace-wide paused states.
- The complete maintained verification passed **300 Python tests with 6
  intentional environment/package skips**, **81 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The opt-in protected three-hop topology
  and both direct-LAN scenarios passed, as did all **3** exact packaged-sidecar
  and 0.2.9 interoperability tests. The final application executable matched
  all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.21** without
  changing the verified 0.2.20 release. The 22,540,288-byte MSI has SHA-256
  `F7316C13C9B7A24EA6ED0953500B4EC48711DBFE567A21F1FCE31CD623C98C40`.
  The 21,800,652-byte NSIS installer has SHA-256
  `C9B8538923FB0F04F6F5C34E099652F1195C8D8B66187197BDCA7493F5AC6569`.
  The portable application reports file/product version 0.2.21 and hashes to
  `FEFEB0253F4426288645E00D9B4B64DDC5F3827FB9EC67F81A07928D1F1E1AC0`;
  the sidecar hashes to
  `0C2FF802C4E21721D7D9624C92202416DD21BE52BE9C499871EEF30DBCD8B0DE`.
  The immutable manifest hashes to
  `2804AE21DE4860CCB6FAC90087C5CE8135B33287A8931B4430636653E5546299`.
- A first follow-up Rust check/test attempt exhausted the nearly full system
  drive while creating an additional debug tree after packaging. Only
  reproducible Cargo and PyInstaller intermediates were removed; immutable
  releases were preserved. The release tests then passed from a clean serial
  build, followed by the locked release-profile check. No installer was
  launched and no existing Mesh Chat process or profile was altered.
- Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install DM partition/reconnect, packet capture,
  and protected-profile plaintext scans remain release gates.

## Workspace increment 6 verification — 2026-10-08

- Protocol coverage preserves the exact Increment 5 message envelope and adds
  exact-field signed edit, delete, and reaction events with target UUIDs, base
  revisions, next revisions, bounded payloads, and canonical verification.
- Service coverage exercises author-only edits/deletes, durable deletion and
  inactive-reaction tombstones, multiple emojis per member, reactions under an
  owner-only posting policy, unauthorized-author rejection, deterministic
  concurrent winners, visible conflict resolution, same-device equivocation
  freeze, exact replay, reversed stream delivery, automatic pending drain, and
  encrypted restart durability. Public channels, private channels, and
  participant-only workspace DMs are all covered without creating Personal
  Contacts or extra timeline rows.
- Renderer coverage edits inline, confirms deletion, presents tombstones,
  displays conflict/security state, and uses the local Emoji 18 picker with
  independent workspace reactions. Rust and Python expose only the three named
  mutation commands.
- The complete maintained verification passed **304 Python tests with 6
  intentional environment/package skips**, **82 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process topology and
  both direct-LAN scenarios passed, as did all **3** exact 0.2.22
  packaged-sidecar and 0.2.9 interoperability tests. The final executable
  matched all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.22** without
  changing prior releases. The 22,552,576-byte MSI has SHA-256
  `62CC4897C9A88DE826022322E873C5FAAA33CB8F9DEBD4F0AE81EC6C17DC5FA4`.
  The 21,812,216-byte NSIS installer has SHA-256
  `73FA42E3B2BCDA29CBEDAF7392F52B6BBAC08B6F5DD7E2746E401D8B0B9A8CCC`.
  The portable application reports file/product version 0.2.22 and hashes to
  `48A5914D0A580EFF26959CABBC0BA16E564E5BEC19C1A2A0BACC55DB617D92A3`;
  the sidecar hashes to
  `6B5AC3183DBC53CA632D40C78307C5D5626DFCCFCB51DC7EEC3C98EA6D1C9891`.
  The immutable manifest hashes to
  `9A1E0D6D9057B1F5476145916CAA34614BB58060F75B4A11CED08937832960B8`.
- No installer was launched and no existing Mesh Chat process or user profile
  was modified.
- Physical concurrent-device partition/reconnect, interactive native-window
  accessibility, packet capture, protected-profile plaintext scanning,
  production signing, and in-place installation remain release gates.

## Workspace increment 7 verification — 2026-10-09

- Increment 7 adds canonical structured workspace mentions to messages and
  edits. Protocol coverage verifies stable sorted member UUIDs, the eight-target
  limit, exact signed-field validation, raw `@name` text remaining inert,
  active-member authorization, private-channel and DM audience binding, and
  edit/non-edit mention semantics.
- Service coverage exercises mention delivery from unsubscribed public
  channels, private-channel visibility, edit-time add/remove/re-add behavior,
  stale-index suppression, independent encrypted paging/read state, per-channel
  mention mute, encrypted draft mention IDs, restart durability, and removal or
  local-leave filtering. Renderer coverage exercises the compose and edit
  pickers, mention chips, highlighted messages, the paged Mentions inbox,
  mark-all-read, mute controls, unread indicators, and stale-draft filtering.
- The complete maintained verification passed **306 Python tests with 6
  intentional environment/package skips**, **84 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process topology and
  both direct-LAN scenarios passed, as did all **3** exact 0.2.25
  packaged-sidecar and 0.2.9 interoperability tests. The final executable
  matched all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.25** without
  changing prior releases. The 22,564,864-byte MSI has SHA-256
  `AFBC45AB6339BC164E9DCAA0AFA3BAF4EC153BD28B4B3D43592F33153A2E7808`.
  The 21,824,074-byte NSIS installer has SHA-256
  `C59031E1A26A046924E53AA99E21EDC3019BEC9985372C1B01A87A03DDA0C4B9`.
  The portable application reports file/product version 0.2.25 and hashes to
  `41B6F21ED568A32C05BE4D51ABDD67F979E2027A8204906852490A1262730345`;
  the sidecar hashes to
  `B4649D04C799452566DF370B0580F8F5A3723E2A35FCB33A4AA6DBE4052F2C2C`.
  The immutable manifest hashes to
  `4AF385BDAB447916E3F29ECB89F90D3A7E62FBBDC0F2C6E74430D84D634F76D9`.
  The immutable 0.2.23 and 0.2.24 builds remain preserved but were superseded
  before installation. Final review found that hiding a workspace DM did not
  suppress its otherwise inaccessible Mentions row. Version 0.2.24 corrected
  that and filtered stale draft/edit mention targets, but its startup snapshot
  still derived the mention badge by reading unread message bodies. Version
  0.2.25 persists the derived count, migrates older records once, and verifies
  that ordinary startup snapshots do not read message bodies.
- No installer was launched and no existing Mesh Chat process or user profile
  was modified. Physical concurrent-device mention partition/reconnect,
  interactive native-window accessibility, packet capture, protected-profile
  plaintext scanning, production signing, and in-place installation remain
  release gates.

## Workspace increment 8 verification — 2026-10-09

- Increment 8 activates the existing signed `thread_root` field while
  preserving the canonical bytes of ordinary messages and mutations. Protocol
  and service coverage verifies retained same-conversation roots, rejection of
  nested replies, exact public/private/DM authorization, private removal and
  re-admission gaps, participant removal, local hides, archived or left
  channels, tombstones, retention invalidation, bounded encrypted reply and
  activity indexes, independent read high-waters and drafts, and stale-cursor
  rejection.
- Delayed reply-before-root delivery, duplicated and reversed events,
  mutations, reactions, controls, restart recovery, structured reply mentions,
  deterministic conflict resolution, and thread-specific unread/read state are
  automated. Renderer coverage opens a mentioned reply directly into the
  dedicated root-context thread view, pages replies, persists the encrypted
  draft, sends a reply, marks only that thread read, and exposes the bounded
  Threads activity view. Startup regression coverage verifies that ordinary
  snapshots use persisted bounded thread summaries and authorization metadata
  without decrypting message bodies or scanning the complete event/delivery
  collections. Global Contacts and Personal/group protocol state remain
  isolated.
- The complete maintained verification passed **309 Python tests with 6
  intentional environment/package skips**, **85 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check` and all **6 release-profile Rust
  tests** passed. The protected four-process/three-hop topology and both
  direct-LAN scenarios passed, as did all **3** exact 0.2.28 packaged-sidecar
  and frozen 0.2.9 interoperability tests under native Windows EFS. The final
  application executable matched all **12** bundled artwork, metadata, and
  license files (1,947,195 source bytes).
- The maintained release driver immutably published desktop **0.2.28** without
  changing the preserved 0.2.23, 0.2.24, 0.2.25, 0.2.26, 0.2.27, or any
  earlier release. The
  22,581,248-byte MSI has SHA-256
  `676B0BF354F93EF131A201B40EF562C2E4A790D0926582A21A9803AC3EE15376`.
  The 21,841,451-byte NSIS installer has SHA-256
  `195E798F7076055EB2AB4B88DF9389BC79EA90E47F2AEC30AB1F71D533216E7E`.
  The 6,724,608-byte portable application reports file/product version 0.2.28
  and hashes to
  `3C9184E591563C55310ADEE78AB92852B4B7C9395CD7844A0632EA5991A5FB22`;
  the 18,393,761-byte sidecar hashes to
  `15859086925CE4D3F429491562D0C4AEFF050EBF629E9D2132B2AAC33AC13F28`.
  The 3,239-byte release notice hashes to
  `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44`.
  The immutable manifest hashes to
  `411E531D96786425027E041BB612B47CC71FE73125CEC55521741AE4170AD356`,
  and `dist/desktop/current.json` selects that manifest. The successful release
  report is
  `dist/reports/0.2.28/20261010T005138Z-0d94f736/report.json`. The immutable
  0.2.26 review build was superseded before installation after final review
  found that an inbound reply or mutation signed after private-channel
  re-admission could reference a locally retained root from the member's prior
  admission era. Version 0.2.27 applies the same root-era/current-access check
  to inbound replies and reply/root mutations and includes hostile regression
  coverage for both cases. The immutable 0.2.27 review build was then
  superseded before installation because repeated local hide operations could
  decrement the derived unread summary for the same reply more than once.
  Version 0.2.28 makes that derived update idempotent and verifies that hiding
  one of two unread replies twice leaves the other reply unread.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device thread
  partition/reconnect, interactive native-window accessibility, packet capture,
  protected-profile plaintext scanning, production signing, and in-place
  installation remain release gates.

## Workspace increment 9 verification — 2026-10-09

- Increment 9 adds retained encrypted local history for active and archived
  conversations, per-message revisions and reactions, author-signed deletion
  tombstones, durable sequence floors and permanent gaps, and restart-safe
  bounded pruning. The owner may publish a signed cooperative retention value
  of 30, 90, or 365 days, or indefinite retention. It is not remote erasure:
  peers can retain exports, backups, screenshots, or modified-client copies.
- Protocol and service coverage verifies authority-only retention transitions,
  stale-cursor rejection after policy changes, bounded revision and tombstone
  views, pruning across restart, retired-event replay rejection, the independent
  seven-day live-delivery window, former-member read-only archives, private
  re-admission gaps, workspace-DM participant isolation, and owner non-access
  to other members' DMs. Renderer coverage exercises the retention selector,
  cooperative-policy warning, manual bounded prune progress/restart state,
  per-message History view, deleted-message history, and explicit pruned/gap
  states.
- The complete maintained verification passed **318 Python tests with 6
  intentional environment/package skips**, **87 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process/three-hop
  topology and both direct-LAN scenarios passed. All **3** tests against the
  exact immutable 0.2.29 sidecar passed, including the frozen 0.2.9
  interoperability run. The final application executable matched all **12**
  bundled artwork files (1,947,195 source bytes). The maintained verification
  report is
  `dist/reports/0.2.29/20261010T021333Z-b7520d86/report.json`.
- The reproducible `service/tools/workspace_retention_benchmark.py` fixture ran
  on Windows 10.0.19045, Python 3.13.15, a 12-logical-CPU Intel Family 6 Model
  158 host with 17,019,686,912 bytes of physical memory, and a SQLite
  DELETE/FULL vault with per-record AES-256-GCM. It retained **50,000** events
  across 8 synthetic members and 32 channels: 42,000 roots, 3,000 replies,
  2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery
  legs, and a 2,000-item pending queue. Startup summary took **36.374 ms** and
  read no event or delivery bodies. Latest-50 warm p95 was **78.886 ms** over 30
  samples; process-cold p95 was **71.872 ms** over 30 samples, where
  process-cold means a new `VaultStore` and service instance without flushing
  the OS file cache. Send commit returned in **22.043 ms** with zero route
  attempts. Fifty restart-safe batches of 1,000 pruned all expired events in
  **233.816 s**; a restart recovered exactly 2,000 pending items without false
  delivery or duplication, chatting continued, and replay of a pruned event ID
  was rejected. Peak working set was 226,795,520 bytes and Python tracemalloc
  peak was 99,413,606 bytes. The seeded vault grew 531,517,440 bytes; after
  pruning its 531,918,848-byte file contained 109,814 reusable SQLite free
  pages rather than claiming physical compaction. All benchmark assertions
  passed in **378.225 s** total.
- The maintained release driver immutably published desktop **0.2.29** without
  changing 0.2.28 or any earlier release. The 22,282,240-byte MSI has SHA-256
  `86232CA3647C69D23DE39BCB6F3DD4445D780E21CED8A863D476969265E55741`.
  The 21,548,937-byte NSIS installer has SHA-256
  `357DA13F386534C672F90BA60687814B8C7B190B82B327A620A140E751A196E5`.
  The 6,725,632-byte portable application reports file/product version 0.2.29
  and hashes to
  `D5C00874A3FC4CCD48D4F1A2E5D26FB1246465344BE4F2CE4307C943C316D0DA`;
  the 18,065,086-byte sidecar hashes to
  `91D6EC6D477DF257FD2BACEA608C5291023F377E4E237FC8AC8AF153ED1D0568`.
  The 3,239-byte release notice hashes to
  `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44`.
  The immutable manifest hashes to
  `A8ABA27F3CE65BD2B2A645EAC55E514A4899BEF3DABB123106B67A6C9A2A25FC`,
  and `dist/desktop/current.json` selects that manifest. The successful release
  report is
  `dist/reports/0.2.29/20261010T023701Z-4a2f1ca1/report.json`.
- Three earlier delivery attempts are retained as failure evidence. The first
  stopped in preflight with only 0.84 GiB free; the second hit a transient pnpm
  EPERM while restoring `node_modules`; and the third linked the application
  but WiX failed under tight disk pressure. After restoring dependencies,
  deleting only disposable generated compiler symbols, and successfully
  exercising Tauri's bundle-only path, the full maintained release entry point
  completed and transactionally published the immutable candidate.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device
  retention/prune partition and reconnect, interactive native-window
  accessibility, packet capture, protected-profile plaintext scanning,
  production signing, in-place installation, and Windows-to-Android validation
  remain release gates.

## Workspace increment 10 verification — 2026-10-09

- Increment 10 adds encrypted local exact-token search over retained workspace
  message roots, thread replies, current permitted people names, and visible
  channel names/topics. Frozen NFKC/default-casefold/NFC normalization feeds
  workspace-keyed HMAC token IDs and sealed 100-reference pages. Queries are
  capped at 256 characters, 1,024 UTF-8 bytes, and eight tokens; execution is
  capped at eight shard pages, 256 decrypted candidates, and 50 results.
  Authenticated cursors contain opaque query/scope digests and bind access,
  retention, search generation, shard, page, and offset. They never carry raw
  queries.
- Service/protocol coverage verifies normalization and punctuation, token/query
  limits, deterministic ordering and duplicate-free pagination, cursor MAC
  tampering and cross-query/scope/generation staleness, incremental edit
  replacement, reaction non-indexing, deletion/hide/prune suppression, bounded
  shards/candidates/pages, 0.2.29 migration and restart recovery, roots/replies,
  people/channels, former-member read-only archives, private removal and
  re-admission gaps, owner/nonparticipant workspace-DM isolation, no whole-kind
  query scan, encrypted-at-rest representative markers, and SQLite-safe keyed
  metadata. Renderer coverage exercises All/Messages/Threads/People/Channels,
  debounce/loading/pagination, accessible labels and focus, and exact thread
  navigation. Rust coverage verifies the desktop-only command allowlist.
- The complete maintained verification passed **322 Python tests with 6
  intentional environment/package skips**, **88 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process/three-hop
  topology and both direct-LAN scenarios passed. All **3** tests against the
  exact immutable 0.2.30 sidecar passed, including frozen 0.2.9
  interoperability. The final application matched all **12** bundled artwork
  files (1,947,195 source bytes). The maintained verification report is
  `dist/reports/0.2.30/20261010T032511Z-61d71b79/report.json`.
- The reproducible `service/tools/workspace_search_benchmark.py` ran on Windows
  10.0.19045, Python 3.13.15, a 12-logical-CPU Intel Family 6 Model 158 host
  with 17,019,686,912 bytes of physical memory. Its Increment 9-derived fixture
  retained **50,000** events for 8 synthetic members and 32 public channel
  chains plus one private authorization probe: 42,000 roots, 3,000 replies,
  2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery
  legs, and 2,000 pending items. Metadata-only startup took **76.582 ms** and
  opened no event/message bodies or whole message collection. Restart-safe
  indexing covered 50,000 event positions in **190.148 s** across **391**
  transactions, producing 45,041 search documents and 95,226 keyed index/page
  records without reference duplication after restart.
- Over 30 samples per series, first-page p95 was **728.881 ms** for a common
  message query, **13.699 ms** rare, **1.437 ms** no-result, **16.365 ms**
  thread, **4.123 ms** person, **3.404 ms** channel, **786.925 ms** warm, and
  **773.836 ms** process-cold. Process-cold means a new `VaultStore` and service
  instance without flushing the OS file cache. All remained below the 2-second
  desktop target. The common query opened 256 candidates and three shard pages;
  ordinary send committed in **111.378 ms** with zero route attempts. Peak
  working set was 970,940,416 bytes and Python tracemalloc peak was 897,159,730
  bytes for the combined seed/rebuild/timing process. The encrypted index grew
  the vault by 364,130,304 bytes; the final benchmark vault was 896,327,680
  bytes. All access, mutation, cursor, prune/restart, no-scan, and plaintext
  absence assertions passed. The 10,637-byte evidence JSON hashes to
  `6A25C46812A4921CD2EED77975AE24D49112D149ED962D130A9E3371A228C05E`
  at `dist/reports/0.2.30/increment10-search-benchmark.json`.
- The first full benchmark attempt stopped during index growth with SQLite
  `database or disk is full` when only 4 MiB remained. No release or user data
  changed. Three validated temporary benchmark profiles and the disposable
  generated Rust release cache were removed, restoring 3.3 GB, and the full
  rerun above passed. An initial unscoped `vitest run` also collected the
  separate Node `node:test` artwork file and reported “no test suite”; the
  maintained scoped frontend runner then passed all 88 Vitest tests and the
  separate Node runner passed its 3 artwork tests. A direct shell `cargo`
  lookup was absent from `PATH`; the pinned `~/.cargo/bin/cargo.exe` toolchain
  completed all required Rust gates.
- The maintained release driver immutably published desktop **0.2.30** without
  changing 0.2.29 or any earlier release. The 22,302,720-byte MSI has SHA-256
  `B573C7E457FB69411890A8B36293EE1F1DD18E5B4D6DFD1A2EB4A129B109B158`.
  The 21,569,391-byte NSIS installer hashes to
  `2B8ADB16FD3F2623ECDD95925E1FC667F7C5B92BBB8FF0AEBEBC527E6C524DEE`.
  The 6,727,680-byte portable application reports file/product version 0.2.30
  and hashes to
  `8BC26948ADE1B4FC93C2CE20DD84D2B002DF78E5A5677BD66DCFEC66B84B4320`;
  the 18,082,474-byte sidecar hashes to
  `B87B171E1553EB9BD3609C1D2E4CE58AE5D425DCAE2FC72BCEAA0CC13DAE86C7`.
  The immutable manifest hashes to
  `05F773EFFF28FF231AC33B86131B01B39BBB08AAD7C026EB1EEA10624C44C530`,
  and `dist/desktop/current.json` selects it. The successful release report is
  `dist/reports/0.2.30/20261010T032654Z-daea9a5a/report.json`.
- No installer or application executable was launched and no existing Mesh
  Chat user profile was modified. Physical concurrent-device search under
  private removal/re-admission and retention partition/reconnect, interactive
  native-window keyboard/screen-reader review, packet capture, protected-profile
  full-tree plaintext scanning, production signing, in-place installation, and
  Windows-to-Android validation remain release gates.

## Workspace increment 11 verification — 2026-10-10

- Increment 11 adds peer-to-peer workspace history catch-up without a server,
  relay, or global archive. Canonical signed requests and bounded signed
  responses are tied to opaque request IDs, requester/responder device IDs,
  exact public/private-era/DM scope, request nonce, continuation, prior-page
  digest, retention policy, and access state. Responses carry prerequisite
  controls and signed author checkpoints before ordinary events, expose signed
  heads and floors, and distinguish permanent/local-prune gaps from peer-limited
  coverage. Requests are capped at 32 streams and 64 ranges; a response is
  capped at 32 controls, 32 checkpoints, 32 events, and 128 KiB.
- Protocol/service coverage verifies canonical bytes, signature and field
  binding, nonce and page replay rejection, exact continuation chaining,
  count/byte/range bounds, public/private-era/DM disclosure, inactive-author
  checkpoint commitments at removal, direct indexed responder lookup, exact
  canonical event recovery between two independently encrypted profiles,
  durable restart, checkpoint-first validation, permanent-gap recording, honest
  `complete_known`/`peer_limited` status, and erasure of jobs, caches, coverage,
  nonces, and checkpoints. Scheduler state is sealed, allows at most two jobs
  per workspace and four per profile, and caps a pass at 256 sequence probes.
  Renderer and Rust coverage verify the History & retention sync status,
  start/cancel/refresh controls, accessible live updates, exact desktop command
  allowlisting, and explicit peer-unavailable, local-prune, and permanent-gap
  states. Ordinary live delivery still emits one event packet; checkpoints are
  retained for authenticated history disclosure rather than doubling traffic.
- The complete maintained verification passed **337 Python tests with 6
  intentional environment/package skips**, **88 frontend tests**, all **3**
  package-artwork source tests, TypeScript compilation, and the Vite production
  build. `cargo fmt --check`, the locked Rust release check, and all **6**
  release-profile tests passed. The protected four-process/three-hop topology
  and both direct-LAN scenarios passed. All **3** tests against the exact
  immutable 0.2.31 sidecar passed, including frozen 0.2.9 interoperability;
  all **7** desktop release tests passed with an isolated pytest base temp. The
  final application matched all **12** bundled artwork files (1,947,195 source
  bytes). The maintained verification report is
  `dist/reports/0.2.31/20261010T140647Z-7a8673ff/report.json`.
- The reproducible `service/tools/workspace_history_catchup_benchmark.py` ran
  on Windows 10.0.19045 with Python 3.13.15, Node 24.19.0, Rust 1.99.0, a
  12-logical-CPU Intel Family 6 Model 158 host, and 17,019,686,912 bytes of
  physical memory. Its Increment 9-derived encrypted fixture retained **50,000**
  events for 8 members and 32 channels: 42,000 roots, 3,000 replies, 2,000
  edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery legs,
  and 2,000 pending items. The fixture vault was 532,119,552 bytes. A real
  independently encrypted requester recovered 32 exact canonical events after
  all 32 ordinary delivery legs were durably expired beyond the independent
  live-delivery window. Recovery used two responses totaling 35,446 bytes,
  including two prerequisite controls and checkpoint validation.
- Across 30 samples, request sign/verify p95 was **2.045 ms**, bounded response
  construction p95 **1.679 ms**, and response verification p95 **7.469 ms**.
  First-response commit took **987.224 ms**, continuation processing
  **80.008 ms**, total catch-up **1,288.147 ms**, duplicate rejection
  **12.666 ms**, private-nonmember denial p95 **11.211 ms**, DM-nonparticipant
  denial p95 **7.863 ms**, and restart/resume **8.560 ms**. Throughput was
  24.842 useful events/s; peak working set was 225,460,224 bytes and Python
  tracemalloc peak was 99,626,288 bytes. The requester vault grew 479,232 bytes
  to 544,768 bytes, and the serving vault grew 1,171,456 bytes to 1,265,664
  bytes. All boundary, authorization, canonical-byte, expired-live-leg, replay,
  signed-head completion, restart, and full-size-fixture assertions passed in
  **111.390 s**. The 2,665-byte evidence JSON hashes to
  `15E1E687C73E26EC27D8885E27DE61E1AFA3A311E27D12739BC28D48A1C4B514`
  at `dist/reports/0.2.31/increment11-history-benchmark.json`.
- The maintained release driver immutably published desktop **0.2.31** without
  changing 0.2.30 or earlier releases. The 22,347,776-byte MSI hashes to
  `498418B04CFD9CE5DFAC8D56F5FD8DB3ECFE29C70AC7A017AE4BE4D7D4818A38`;
  the 21,614,129-byte NSIS installer hashes to
  `DB092CB491241ACD98CF405BA8B3D58CA3D1257703286BD2E7EBED1BF28CB1E8`.
  The 6,728,704-byte portable application reports file/product version 0.2.31
  and hashes to
  `D397F3DE2C85D506C23A2E5E8C32888F18A368F63CEBFBA878236DB9CAEAF813`;
  the 18,126,664-byte sidecar hashes to
  `56CD521282D9FE87A626C94F1AE1C4E1882E2878F7DE656C537B8A825BE0568B`.
  The immutable manifest hashes to
  `FBAED26CF0A298F0132D3D3960D2A21927DFDC703E8BF93A78A5B8B45753B142`,
  and `dist/desktop/current.json` selects it. The successful release report is
  `dist/reports/0.2.31/20261010T141349Z-1aca514c/report.json`.
- Failure evidence was retained while converging. Early checkpoint delivery
  doubled live packets and broke seven workspace expectations; checkpoints were
  moved to history disclosure and the full suite passed. One guessed pytest
  filename selected no tests. The first final Python run found a renderer
  wording mismatch, then passed after the status copy and assertion agreed.
  Early frontend attempts hit the system Node 14 shim and one pnpm sandbox
  `EPERM`; the pinned Node 24 runner passed. Benchmark smoke runs first found a
  missing `local_pruned` metric and then the required empty terminal page; both
  were corrected. A full benchmark rerun later reached reporting before a
  mistyped working-set field failed; the corrected full rerun above passed.
  Exact disposable benchmark-profile cleanup once required a scoped elevated
  retry. A combined package/desktop pytest run passed the three package tests
  but hit seven setup errors from an inaccessible stale global temp directory;
  rerunning the seven desktop tests with a unique base temp passed. Three
  artwork-verifier invocations used, in turn, a missing flag, a stale Node path,
  and a wrong executable subdirectory; the final exact-binary run passed.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device
  catch-up across partition/removal/re-admission, hostile peer fault injection,
  native-window keyboard/screen-reader review, packet capture,
  protected-profile full-tree plaintext scanning, production signing, in-place
  installation, and Windows-to-Android validation remain release gates.

## Workspace increment 12 verification — 2026-10-10

- Increment 12 adds effective `owner`, `admin`, and `member` roles, exact
  `all_members|owner_and_admins` channel/posting policies, and exact
  `owner_only|owner_and_admins|all_members_request` invitation-request policy.
  Administrators can create/post and manage channels for which they hold the
  signed manager role while the owner is offline. They gain no manifest key,
  global policy/retention/closure authority, arbitrary channel control,
  private-channel discovery/recovery, or third-party DM access.
- ADR 0011 freezes the 4 KiB request and 48 KiB decision phases of
  `workspace_admin_request`, seven-day lifetime, 250-character note, replay and
  result bindings, one-target invitation/removal/role workflows, and
  pending/approved/declined/stale/superseded/expired/safe-cancel lifecycle.
  Sealed HMAC-addressed indexes cap pending requests at 128 per workspace, 512
  per profile and 32 per requester/source; pages are at most 100 rows, inert
  decisions at most 64, and terminal replay/audit retention 90 days. Role
  manifests change exactly one active nonowner between member/admin and cannot
  combine another mutation.
- Protocol/service tests cover canonical and worst-case Unicode serialization,
  byte/field/signature/workspace/base/target/role/result binding, every
  invitation policy, unauthorized members and administrators, duplicate and
  conflicting results, safe cancellation, direct owner transitions,
  supersession/staleness/expiry, restart durability, demotion enforcement,
  owner-only operations, manager-transfer constraints, private/DM isolation,
  erasure and bounded indexed paging. Renderer tests cover effective versus
  requested roles, owner review warnings and confirmation, destructive removal,
  outgoing outcomes, pending counts, and immediate control changes. Rust tests
  cover every new desktop-only command.
- The maintained verification passed **347 Python tests with 8 intentional
  environment/package skips**, **90 frontend tests**, all **3** standalone
  package-artwork verifier tests, TypeScript project compilation, and the Vite
  production build. `cargo fmt --check`, locked Rust release check and all
  **6 release-profile tests** passed. The Windows protected four-process,
  three-hop topology passed. All three direct-LAN scenarios passed, including
  the two-real-process administrator owner-offline flow. The exact immutable
  0.2.32 package passed phone-first/direct/reaction/delete/reopen and
  administrator flows. Exact 0.2.31 interoperability converged its supported
  expanded reaction; frozen 0.2.9 safely ignored it and continued bidirectional
  chat. Final app artwork matched all **12** bundled files (1,947,195 source
  bytes). The successful maintained report is
  `dist/reports/0.2.32/20261010T172636Z-6519e129/report.json` and the successful
  delivery report is
  `dist/reports/0.2.32/20261010T173233Z-0abbc471/report.json`.
- The reproducible administrator benchmark ran on Windows 10.0.19045,
  Intel64 Family 6 Model 158, Python 3.13.15, Rust 1.99.0, Node 24.19.0 and
  17,019,686,912 bytes physical memory. Its encrypted fixture held 50,000
  events, 8 members, 24 public/4 private/4 archived control chains, 42,000
  roots, 3,000 replies, 2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000
  linked-device legs and 2,000 pending items across independent owner/admin/
  member profiles. Over 30 samples, request p50/p95 was **2.509/2.683 ms**,
  owner-page **7.407/8.132 ms**, decision **4.386/4.802 ms**, role commit
  **26.814/30.432 ms**, invitation approval **54.088/57.892 ms**, owner-offline
  admin create/post **80.455/98.869 ms**, duplicate rejection
  **0.480/0.758 ms**, and stale/superseded resolution **70.278/87.311 ms**.
  Restart was **12.454 ms**, first owner-visible request **2,635.476 ms**, and
  end-to-end 30-request approval/result delivery **4,754.499 ms**.
- The benchmark observed 1,686-byte maximum canonical requests, 5,248-byte
  decisions, 4,063-byte invitations and 2,576-byte result manifests; 62 queued
  packets, 1,447 route attempts and 196 modeled transactions; 99,636,650-byte
  peak Python allocation and 228,233,216-byte peak working set. Vault growth was
  3,063,808 owner, 3,022,848 admin and 987,136 member bytes. All 31 policy,
  state, replay, conflict, demotion, private confidentiality, resource and
  timing assertions passed in 142.669 seconds. The 4,917-byte evidence file is
  `docs/benchmarks/increment-12-workspace-administrators.json`, SHA-256
  `90D6A5F18E1D45E3AA54E2334CB4F88597DEBEF2C97995F6E8CF3449E98DF379`.
- The release driver immutably published desktop **0.2.32** without changing an
  earlier release. The 22,380,544-byte MSI hashes to
  `2E9417144762F9C74046FDE0B4FEDAA1B567B9D6D37E961A06D440F290B52909`;
  the 21,644,516-byte NSIS installer hashes to
  `7A06986FC4174A685E8A59B524460E34932858EA77CEED02FE404487AEAC9590`.
  The 6,730,752-byte portable app reports file/product 0.2.32 and hashes to
  `850C8004FD9A3498943F9560AFDF33874C81E894A05027B83F95B33BF5F5A740`;
  the 18,156,246-byte sidecar hashes to
  `407AE337232FEBC83D90566766A47CEFDFF5C3868CE12D6DB04978A337891CF2`.
  The immutable manifest is 1,345 bytes, hashes to
  `B17156AAC0D1A6E6D33AA7F293FBA67974A8E98CE26AE524B276EC55A727EEFD`,
  and is selected by `dist/desktop/current.json`.
- Transient failures were preserved honestly. A full Cargo debug test first
  exhausted the host disk/PDB allocator; after deleting only the exact
  disposable target, single-job non-incremental release check/test passed with
  debug symbols disabled. An unscoped Vitest run collected the separate Node
  artwork test until the dedicated config was scoped. The first full benchmark
  confidentiality probe counted unrelated retried public packets by destination
  until it was narrowed to the exact private channel document; the corrected
  50K run passed. Initial direct-LAN probes used an overlong IPC request ID and
  then matched a snake-case error instead of the typed `ContactNotApproved`;
  the exact flow passed after those harness fixes. The first maintained verify
  run found a widened Vite `minify` type; restoring `UserConfig` passed. The
  first package build hit pnpm sandbox `EPERM`; the identical elevated retry
  reused the sidecar, repaired local dependencies, and passed. A mixed 0.2.31
  assertion initially expected old-peer ignore behavior; capability-aware
  0.2.31 convergence and exact 0.2.9 ignore gates both passed.
- No installer or application was launched and no existing Mesh Chat process
  or user profile was modified. Physical concurrent-device admin partitions,
  hostile request floods/fault injection, native-window keyboard/screen-reader
  review, packet capture, protected-profile full-tree plaintext scanning,
  production signing, in-place installation, and Windows-to-Android validation
  remain manual/physical release gates. Permanent owner-authority loss remains
  intentionally unresolved until Increment 13.

## Acceptance matrix

| Gate | Current evidence |
| --- | --- |
| No infrastructure | Config and code automated; direct TCP-only two-process harnesses passed both bidirectional-hint chat/group/chat and phone-shaped outbound-client/no-listener direct chat without a relay; two-device disconnected-LAN packet capture not yet run |
| Real mesh | Protected four-process A→B→C→D run passed with exactly three reported hops |
| Intermediate confidentiality | B/C persistent-file marker scan passed; process-memory inspection not yet run |
| Offline propagation | Adapter implemented; end-to-end offline retrieval not yet proven |
| Propagation independence | Not yet proven |
| Unavailable path | Durable state, contained route failure, dirty-route marking, and later-send recovery unit-covered; isolated real-peer recovery run pending |
| Cryptographic mode policy | Invitation binding and recipient-ratchet gating passed in the real path; altered-ciphertext full-path test pending |
| Receipt semantics | Mapping, validation, and packaged IPC covered; crash matrix pending |
| Group cryptographic documents | Canonical document and payload validation unit-covered; independent review and hostile-input fuzzing pending |
| Group fan-out and receipts | Three-endpoint in-process simultaneous-invite/catch-up plus invite/join/chat/receipt flows passed; real two-process bidirectional-hint invite/join/message and post-group direct chat passed; real 3/5/8-device direct and propagated runs pending |
| Group membership changes | Service-level remove, signed leave, terminal close, accepted-invite replay rejection, reversed epoch catch-up, and old-epoch equivocation suspension passed; partitioned real-device removal, owner-loss, and upgrade runs pending |
| Group history boundary | No-backfill behavior requires service integration and encrypted-profile marker scans |
| Duplicates/order | Logical mutation deduplication implemented with a bounded encrypted response journal; one-to-one approval commits and submits exactly one durable `CONTACT_ACCEPT`; direct-message retries correlate native attempt IDs and reject stale callbacks while retaining stronger endpoint evidence; native callbacks are deferred outside upstream locks, retry records yield to live commands, and renderer duplicate-submit/stale-draft ordering regressions are present; broader network fault-injection run pending |
| Crash consistency | Transaction boundaries implemented; kill-point matrix pending |
| At-rest protection | Encrypted-record scan, Windows protected topology/sidecar, and mobile Token round-trip tests passed; macOS/Linux adapters unit-covered, Android device and iOS native full-tree scans pending |
| Isolation/process safety | Config and IPC parser covered; local hostile-process run pending |
| Abuse/limits | Static caps implemented; stress/flood run pending |
| Emoji reactions | Direct, group, and announcement-channel authorization, encrypted durability, bounds, replay/tombstone behavior, old-peer compatibility, and desktop/mobile renderer behavior passed coverage. The 0.2.11 local artwork mapping covers 253/253 picker choices and partitions the full catalog into 3,944 sprites plus 19 named fallbacks; all 12 artwork/metadata/license files were decoded and matched in the final Windows and Android binaries. Physical Windows↔Android/iOS rendering validation remains pending. Delivery is best effort after authenticated endpoint evidence and same-revision equivocation is first-seen-wins |
| One-to-one approval | Always-on deterministic full flow and prior real bidirectional-hint Reticulum/LXMF runs passed; the phone-shaped harness covers phone-first delivery followed by the desktop reply on the same connection. Exact 0.2.12 physical Windows↔Android validation remains pending |
| Contact management | Rename, verification toggling, block/unblock trust restoration, deletion cleanup, active-group identity retention, pending-group-invitation refusal, search, confirmations, mobile Back handling, and responsive dialog layout are covered. The shared UI was matched inside the exact Android APK; physical desktop/phone interaction remains pending |
| Reconnection/interoperability | Upstream format preserved; bidirectional direct-LAN attachment, dirty-route retry, signed-client route replacement, deferred callback re-entry, and phone-shaped full-duplex return traffic are covered; reference-client and suspend/resume runs pending |
| Platform packaging | Windows x64 0.2.32 MSI/NSIS and Android arm64 debug 0.2.12 packages were built, hashed, and inspected; the exact 0.2.32 Windows binary and sidecar were verified but the app/installer was not launched. Versions, manifest, installer payloads, Android v2 signature/certificate, native architecture, embedded contact UI, and all 12 embedded artwork files were verified. The transactional publisher rejects mixed/stale output and records immutable release/current manifests. Physical Windows↔Android 0.2.12 validation, a 0.2.12 portable bundle, macOS/Linux/iOS native package runs, and production signing remain pending |
| First-message usability | 0.2.12 retains desktop timeout guidance, exact draft preservation, callback/retry concurrency regressions, and the phone-first/desktop-reply harness together with durable-result, bounded-draft, duplicate-submit, IME, stale-refresh, delivery-state, and responsive-layout coverage. Exact 0.2.12 physical Windows↔Android validation and a broader human study remain open |
| Invitation entry points | UI and validation implemented; installed-app OS matrix pending |
| Common flow without technical setup | UI implemented; fresh/returning human run pending |
| Connection help | State/action mapping implemented; recovery scenarios pending |
| Accessible joining | Labels, focus, keyboard, contrast and live regions implemented; assistive-tech audit pending |
| Workspace increment 3 | Increment 2 coverage remains green. Public-channel signed chains, paged summaries/fetches, explicit incomplete discovery, duplicate names, policy enforcement, management transfer/recovery/archive, subscriptions, unread persistence, reversed controls, channel-scoped forks, Tauri allowlisting, and manager/member UI denial paths are automated. Isolated and direct-LAN process topologies plus the immutable packaged sidecar passed; physical eight-install restart/kill-point/partition runs and a native-window walkthrough remain release gates |
| Workspace increment 5 | Increment 4 coverage remains green. Deterministic participant-only workspace DMs, canonical authorization, independent encrypted local state, bidirectional delivery, hide/reopen, restart, removal gating/cancellation, desktop command allowlisting, and Contacts isolation are automated. Isolated, direct-LAN, packaged-current, and 0.2.9 compatibility paths passed; physical multi-install DM partition/reconnect, native-window, and plaintext-scan gates remain open |
| Workspace increment 6 | Canonical edits, author deletion tombstones, per-member/per-emoji reactions, inactive tombstones, target/base revision binding, deterministic concurrent resolution, same-device equivocation freeze, out-of-order pending/drain, restart durability, current/historical audience authorization, posting-policy independence, desktop command allowlisting, and public/private/DM renderer/service paths are automated. Immutable package verification passed; physical concurrent-device partition/reconnect, native-window interaction, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 7 | Canonical structured mentions, exact audience authorization, edit add/remove/re-add semantics, encrypted mention index/paging/read/mute/draft state, unsubscribed-public delivery, private/DM isolation, stale-index and stale-draft filtering, desktop command allowlisting, and compose/edit/inbox renderer paths are automated. Protected topology, direct-LAN, immutable packaged-current, 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device mention partition/reconnect, native-window accessibility, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 8 | One-level signed-root replies, non-thread canonical-byte compatibility, exact public/private/DM authorization, nested-reply rejection, mutations/reactions/mentions/tombstones, deterministic out-of-order recovery, encrypted bounded paging/activity/read/draft/cursor state, metadata-only startup summaries, current-access and private re-admission filtering, desktop command allowlisting, mentioned-thread navigation, reply composition, and thread-specific unread behavior are automated. Protected topology, direct-LAN, immutable packaged-current, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device thread partition/reconnect, native-window accessibility, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 9 | Signed cooperative 30/90/365-day or indefinite retention, bounded encrypted history/revision/tombstone indexes, stale-cursor invalidation, restart-safe pruning, seven-day live-delivery preservation, durable floors and gaps, replay-resistant retired event IDs, historical/current entitlement checks, former-member read-only archives, and desktop retention/history/prune states are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable packaged-current, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device retention/prune partition/reconnect, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 10 | Encrypted workspace-keyed exact-token search, bounded shard/candidate/result execution, authenticated query/access/retention/search cursors, incremental atomic mutation updates, restart-safe migration, current plus historical authorization, private-era and DM isolation, honest indexing/pruned/incomplete states, desktop filters/navigation, and SQLite plaintext absence are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable 0.2.30 package, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device access/retention partitions, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 11 | Canonical signed history requests/responses, bounded streams/ranges/pages/bytes, replay-safe continuation binding, prerequisite controls, signed author checkpoints, removal commitments, encrypted restart-safe jobs/caches/nonces/coverage, direct indexed disclosure, exact canonical-byte acceptance, public/private-era/DM authorization, honest complete/peer-limited/pruned/permanent-gap states, scheduling bounds, erasure, desktop status/actions, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable 0.2.31 package, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device partition/removal/re-admission, hostile peer fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 12 | Effective owner/admin/member roles, exact role-aware channel/posting/invitation-request policies, signed bounded owner-approved invitation/removal/role requests, exact one-member manifest transitions, sealed indexed lifecycle/replay/audit state, owner-offline channel operation, private/DM isolation, accessible owner review/outgoing history, demotion enforcement, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, all direct-LAN scenarios, immutable 0.2.32 package administrator flow, exact 0.2.31 and frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device admin partitions, hostile request floods/fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |

Do not mark a release complete from unit tests alone. Store packet captures, topology configs, full-tree scans, package hashes, platform versions, human timing sheets, and failure notes with the release evidence.
