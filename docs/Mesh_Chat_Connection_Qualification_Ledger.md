# Connection runtime qualification ledger

This ledger records the automated evidence behind the connection-runtime refactor at
commit `3517e3d` (2026-11-02). The transport and packaged-Windows evidence below
was captured at
`67ac8fe34b19db335fc9b772af0bd0cd7ff78d49` (tree
`bd09a02ade1b83a2515fd2a0f515c7f4d23467bd`); later commits add tests, clients,
release-pipeline fixes, documentation and ledger rows. It separates what was executed from what this
environment cannot execute; it is not a physical-device qualification.

## Independent Android messaging consumer increment (2026-11-03)

The CI-only Binder host seeds one approved fixture contact. The standalone APK,
built only from the public Kotlin AAR, then enqueues a text message through
`CoreClient` and reads it back from the facade across UIDs. A second case
force-stops the host process, rebinds, and queries the same SDK message handle
with its text intact. Repeating the identical enqueue key then returns the same
handle and leaves exactly one listed message. This qualifies the SDK send/read,
durable facade readback and restart-safe idempotency boundary against a
host-owned contact, a changed payload for the same key is rejected with
`idempotency_conflict` without a duplicate record, and an arbitrary unknown peer
handle is rejected as forbidden. It does not claim transport
delivery, receipts, pairing or partition recovery. The Android consumer inventory
is now 36 required cases.

## Native Windows messaging evidence (2026-11-03)

At `c6a0f61`, the complete local required inventory passed **1,794 tests, zero
failures and zero skips**. Two independent Reticulum service processes deliver
durable messages and authenticated receipts over the native aiortc DataChannel,
including a 100-message receipt soak, bridge replacement, full peer-process
restart, duplicate-packet deduplication, and five-/thirty-second packet
partitions recovering under the 30-/240-second budgets. Handshake cancellation at
the offer, acceptance and answer phases and shutdown retirement are covered. A
100-cycle packaged
transport soak enforces 20-/30-second open/control budgets. The durable tests use
the legacy bridge policy; supervisor-owned promotion, Windows-Android/WebView
interoperability, TURN/forced relay and the 150 ms RTT impairment profile remain
open.

## Binder and independent Android package slice (2026-11-02)

At source `d2590ff`, the complete local required inventory passed **1,768 tests,
zero failures and zero skips** in 93 seconds. This includes 294 cancellation
cases across all 14 reachable phases and both offer roles. Strict policy typing
is clean. The Kotlin client, bounded exchange transport and dispatcher passed
**21 JVM tests**, including 1,000 sequential exchanges, overload, timeout,
caller capture and uncorrelated admission errors.

The production Binder host compiled locally. The public Kotlin AAR and local
Maven staging task built successfully, and the independent consumer application
and instrumentation APKs compiled outside the checkout with only the staged AAR
and example. The AAR content verifier passed. These are local packaging checks,
not executed emulator or full M5 messaging evidence.

Run [41559732693](https://github.com/ahouchens/mesh-chat/actions/runs/41559732693)
passed all **34 Android emulator cases**, zero failures/skips, for the earlier
package slice at branch source `461c2e9`. Its recorded merge source is
`9cc4eb5101927a7a0a83d2ae46f927e96462e0c9`; tree
`5d4c7e879bf1adebf348554b66155ec4cd566b4b` matches that branch commit. The four
cross-UID consumer cases passed on API 35 x86_64, with host-process cleanup
verified. The report includes host/consumer/test APK hashes and AAR SHA-256
`41735a4138f7b9648b00106161c2d9e70c03b7c28acc24d15f2557e2984f909b`.
The workflow's final result must still be checked separately.
The later process-owned dispatcher and cancellation additions require CI on their
own source; earlier green manifests do not qualify them.

A later local emulator attempt was stopped after exhausting local disk during
host APK packaging. It contributed no execution evidence. Its disposable build
directories were removed; source, reports and the previously built SDK/consumer
artifacts were retained. Physical qualification remains unavailable.

## Connection qualification workflow

Run [41293162273](https://github.com/ahouchens/mesh-chat/actions/runs/41293162273)
concluded **success** with every required job and the final gate:

| Job | Result |
| --- | --- |
| policy / policy | success |
| verification / Verify and test | success |
| verification / Check Windows desktop host | success |
| direct / android-compile | success |
| direct / controlled-peers (ubuntu-latest) | success |
| direct / controlled-peers (windows-latest) | success |
| layout / browser-layout | success |
| Select dependent qualification suites | success |
| android / Android build and optimized native Chromium interop | success |
| policy / Required connection policy gate | success |
| Required connection qualification gate | success |

The Android job ran the emulator suites and emitted
`android_emulator_optimized_native_and_python_components` evidence whose
`source_tree` equals the tree above; GitHub supplies a synthetic merge commit as
`source_commit` for pull-request runs, so the tree is the binding identifier.

## Main CI and packaged Windows

Workflow-dispatch run
[41295548962](https://github.com/ahouchens/mesh-chat/actions/runs/41295548962)
concluded **success**:

- Verify and test: 2,600 passed, 51 skipped (skips are platform-bound packaged
  tests), SDK conformance 1 passed, frontend 587 passed.
- Check Windows desktop host: `cargo test --lib` 27 passed and
  `--features experimental-shared-webview` 27 passed; packaged lifecycle,
  WebView2 private-host transport, packaged pre-approved peers and explicit
  pairing evidence all report `passed: true` with `source_commit` exactly
  `67ac8fe…` and the tree above.

## Local qualification

| Suite | Command | Result |
| --- | --- | --- |
| Required policy inventory | `python scripts/connection_evidence.py --run --junit … --expected-source <tree>` | 1,775 passed, zero skips at 3517e3d |
| Strict typing | `mypy --config-file mypy-connection.ini` | clean |
| Frontend | `node scripts/run-frontend-tests.mjs` | 587 passed |
| TypeScript client + package | `node --test sdk/typescript/dist/**/*.test.js` | 42 passed |
| Compatibility | `pytest service/tests/connection/test_core_compatibility.py` | 18 passed |
| Budget conformance | `pytest service/tests/connection/test_core_budgets.py` | 3 passed (exact advertised limits; over-budget rejected; edges accepted) |
| Received-page byte budget | `pytest service/tests/connection/test_core_received.py::test_received_page_respects_the_byte_budget` | 1 passed (80 x 16 KiB inbound messages truncate below 1 MiB with a cursor) |
| Packaged client smoke (unpublished) | `node scripts/check_typescript_distribution.mjs` | passes: npm pack, install into an empty project, import `@mesh-chat/core-client` |
| Packaged service wheel (unpublished) | `python scripts/check_python_distribution.py` | passes: wheel build, install into an empty target, import `mesh_chat.core_api`, both console entry points installed, `mesh-chat-core --version` prints `0.2.0-experimental`, and the packaged service answers `runtime.capabilities` and `workspace.query` through the facade |
| Release qualification executed end-to-end (branch build, **not published**) | `release_qualification.py` against fresh branch release artifacts and the generated exact-source manifest | **passed**: setup 28,187,035 B, msi 30,187,520 B, apk 47,283,410 B; manifest and artifacts bound to source `affc1dd`, tree `1bca66f`; version 0.9.66 |
| Packaged pipe consumer (unpublished, Windows) | `python scripts/check_packaged_pipe_consumer.py` | passes: installed wheel hosts a real named-pipe endpoint and a second installed-wheel consumer negotiates capabilities and queries workspaces over it |
| Native Windows WebRTC host (component) | `pytest service/tests/connection/test_native_windows_webrtc.py` | 4 passed: real offer/answer, three channel purposes, binary packets, control text, stats and exact close |
| Packaged native WebRTC messaging (unpublished, Windows) | `python scripts/check_native_windows_messaging.py --expected-source 3517e3d` in CI run 41573294373 | passed: two packaged sidecars exchanged offer/answer and a control message; no WebView process in either owned process tree |
| Native peer-process restart (component) | `pytest service/tests/connection/test_native_windows_delivery.py` | 1 passed: restart preserved the profile identity, a message queued offline delivered over the new native session with an authenticated receipt |
| Native bridge replacement recovery (component) | `pytest service/tests/connection/test_native_windows_delivery.py` | 1 passed: a message queued while the native bridge was absent delivered with a receipt after replacement |
| Native partition and duplication (component) | same suite | 2 passed: duplicate packets yielded one inbound copy; five- and thirty-second native packet partitions recovered with receipts under 30 and 240 seconds respectively |
| Native durable messaging (component) | `pytest service/tests/connection/test_native_windows_delivery.py` | 1 passed: two independent Reticulum processes, native offer/answer, attached bridge, contact approval, durable messages and receipts both directions, plus a 100-message alternating receipt soak with one inbound copy per logical ID |
| Native handshake cancellation (component) | `pytest service/tests/connection/test_native_windows_webrtc.py` | 3 passed: cancellation after offer creation, acceptance and answer application retires exactly that session, frees its slot and leaves no observable state; shutdown retires all live sessions and refuses further work |
| Installed-wheel Windows consumer messaging | `python scripts/check_packaged_pipe_consumer.py` in consumer and owner scopes; a second host starts from the same vault and new pipe and the consumer queries the saved handle successfully | passed: installed wheel host plus separate installed-wheel consumer enqueues through a profile peer, queries the message, reuses the same key for the same handle, rejects changed text with idempotency_conflict and rejects an unknown peer handle with forbidden in consumer and owner scopes |
| Workspace invitation creation (facade) | `pytest service/tests/connection/test_core_workspace_admin.py` | 2 passed: owner creates replay-safe signed workspace material (default, WebRTC, email and I2P modes), participant returns typed unavailable without a direct host, joiner previews/joins through the facade, delivery reaches the owner, approval exposes both members; consumer grant is forbidden |
| Android native-host cancellation | `pytest` Android qualification suite | 5 direct cases cover cancellation after offer/accept/answer, closeAll retirement and fail-closed bounds/missing channels, each asserting exact absence and reusable capacity |
| Native contact-deletion retirement (unit) | `pytest service/tests/connection/test_native_peer_retirement.py` | 1 passed: only live sessions bound to the deleted destination close; end-to-end deletion teardown remains unqualified |
| CLI workspace invitation round trip | `pytest service/tests/connection/test_core_client_e2e.py` | 1 passed: owner-granted CLI lists a real workspace and creates I2P-mode invitation material through the host stream |
| Native transport soak (unpublished, Windows) | `python scripts/check_native_windows_messaging_soak.py --iterations 100` | passed: 100 packaged offer/answer/open/control/close cycles, 3 cold starts, max open 716 ms, max control 1,230 ms in CI run 41626323911, no WebView process; durable messages/receipts not claimed |
| Media-track ownership boundary | `vitest src/webrtc-session.test.ts` | passed: closing a messaging session stops its peer connection but not a media-call track |
| Consumer host boundary (unpublished, Windows) | same packaged pipe consumer | passes: workspace creation is refused with `forbidden` for the default consumer scope |
| Per-channel posting override (component) | pytest service/tests/test_workspace_rejoin.py::test_channel_posting_override_restricts_regular_members and 	est_core_workspace_admin.py | passes: signed override denies a regular member, inherit restores posting, facade update returns the effective value |
| Owner-scoped packaged consumer (unpublished, Windows) | `MESH_CHAT_PIPE_SCOPE=owner python scripts/check_packaged_pipe_consumer.py` | passes: the installed wheel host grants the opt-in owner scope and a second installed-wheel consumer creates a channel and reads members |

## Definition-of-done disposition

The specification's section 13 requires more than this branch has implemented and qualified. Each
condition is recorded with its actual status:

| Definition-of-done condition | Status | Evidence or gap |
| --- | --- | --- |
| M2: INV01–INV19 pass in applicable suites | partial | Local/component suites
  pass; INV12/16/17/20 remain partial for packaged lifecycle, parity and carrier
  reuse. |
| M2: one policy owner for Android foreground/background and desktop
  transitional messaging | partial | Single-owner composition and tests; full
  platform lifecycle parity is not qualified. |
| M2: baseline compatibility and surviving-carrier repair | component |
  Compatibility tests and bridge-repair components pass; no packaged cross-platform
  run. |
| M2: replaced scheduling/repair loops are removed | **not met** | Legacy loops
  remain; removal is gated on the packaged parity above. |
| M2: dependency checks enforce the boundary | met | Import/boundary checks and
  the policy inventory pass. |
| M2: required coverage intact with explicit skip reporting | met | Gate fails
  missing, skipped, canceled or stale evidence; inventory has zero skips. |
| M4: production Windows and Android transports no longer require a WebView |
  **partially met** | Android native transport exists; Windows uses packaged
  WebView2, and the production native Windows DataChannel is not implemented. |
| M4: scenario runner on those exact transports, fault and 100-iteration
  matrices | **not met** | Packaged WebView2 scenarios pass; the native Windows
  fault/receipt soak does not exist. |
| M4: defined physical qualification checklist on a release candidate |
  unavailable | No physical devices or isolated network. |
| M5: INV21–INV26 and SC21–SC26 pass | **not met** | INV21/22/25/26 and
  SC21/25 are partial or open; the rest pass at component/local level. |
| M5: independently built packaged consumers through the public API | **not met**
  | Packaged TypeScript and Python component smokes install and answer facade
  requests; the opt-in owner scope now permits administration for the trusted
  pipe host and the Android app UID. Full independent messaging and recovery
  acceptance remains open. |
| M5: supported Mesh Chat messaging UI uses the same facade | **not met** | Not
  routed or qualified in this environment. |
| M5: install/upgrade/caller isolation/resync/compatibility evidence | partial |
  Component tests cover isolation and resync; installation/upgrade and supported
  version pairs are absent. |
| M5: API documentation and support matrix release-ready | partial | Contract and
  compatibility declarations are test-bound and package shape is checked; no
  published matrix. |
| Release gating: INV20 exact source/artifact evidence, skips fail, publication
  cannot bypass the matrix | met at gate level | The gate and aggregator refuse
  without exact evidence. A branch-build release qualification was executed and
  passed end-to-end on setup/MSI/APK artifacts bound to source affc1dd/tree 1bca66f; no tag
  has exercised publication. |

**Conclusion.** The specification's M2–M5 definition of done is not met. The
facade and clients cover the implemented operation inventory, which is not proof
that all specification requirements are implemented. Native Windows transport,
packaged consumers, UI migration, profile lifecycle, legacy-loop removal and the
remaining automated scenarios are implementation/qualification work. Only the
physical checklist requires the unavailable physical test environment. Release
publication remains gated on complete evidence and release authorization.

## Explicit limits

These were **not** executed and are not claimed anywhere in this ledger:

- physical-device qualification across independent Android and Windows devices;
- packaged Windows↔Android interoperability (the packaged evidence above is a
  single Windows host with WebView2 and frozen peers);
- full distribution-only Windows and Android messaging consumer acceptance;
  component package and caller-scope checks do not establish pairing, durable
  receipts, restart/partition recovery, or upgrade compatibility;
- published SDK/package artifacts and a supported version-pair matrix;
- a **tagged** release qualification and any publication; a branch-build release
  qualification was executed and passed but is not a release;
- a native Windows DataChannel implementation.

The corresponding acceptance rows (INV21, INV22, INV25, INV26, SC01, SC21, SC25)
remain partial or open for exactly these reasons.

## Reproduction

```text
python scripts/connection_evidence.py --run \
  --junit dist/reports/connection-policy.xml \
  --expected-source "$(git rev-parse HEAD)" \
  --output dist/reports/connection-policy.json
cd service && mypy --config-file mypy-connection.ini
node scripts/run-frontend-tests.mjs
node --test "sdk/typescript/dist/**/*.test.js"
```
