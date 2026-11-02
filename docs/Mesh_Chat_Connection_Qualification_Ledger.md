# Connection runtime qualification ledger

This ledger records the automated evidence behind the connection-runtime refactor at
commit `5174676` (2026-11-02). The transport and packaged-Windows evidence below
was captured at
`67ac8fe34b19db335fc9b772af0bd0cd7ff78d49` (tree
`bd09a02ade1b83a2515fd2a0f515c7f4d23467bd`); later commits add tests, clients,
release-pipeline fixes, documentation and ledger rows. It separates what was executed from what this
environment cannot execute; it is not a physical-device qualification.

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
| Required policy inventory | `python scripts/connection_evidence.py --run --junit … --expected-source <tree>` | 1,449 passed, zero skips at 5174676 |
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
| Consumer host boundary (unpublished, Windows) | same packaged pipe consumer | passes: workspace creation is refused with `forbidden` for the default consumer scope |
| Per-channel posting override (component) | pytest service/tests/test_workspace_rejoin.py::test_channel_posting_override_restricts_regular_members and 	est_core_workspace_admin.py | passes: signed override denies a regular member, inherit restores posting, facade update returns the effective value |
| Owner-scoped packaged consumer (unpublished, Windows) | `MESH_CHAT_PIPE_SCOPE=owner python scripts/check_packaged_pipe_consumer.py` | passes: the installed wheel host grants the opt-in owner scope and a second installed-wheel consumer creates a channel and reads members |

## Definition-of-done disposition

The specification's section 13 asks for more than this branch can execute. Each
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
  pipe host and the Android app UID, but no independent graphical application exists. |
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

**Conclusion.** The refactor's facade, clients, tests and automated qualification
are complete for the operations the domain supports, but the specification's M2–M5
definition of done is not fully met. The unmet conditions are the legacy-loop
removal, the native Windows DataChannel, packaged consumers, physical qualification
and publication, all of which are outside this environment or authorization.

## Explicit limits

These were **not** executed and are not claimed anywhere in this ledger:

- physical-device qualification across independent Android and Windows devices;
- packaged Windows↔Android interoperability (the packaged evidence above is a
  single Windows host with WebView2 and frozen peers);
- packaged Windows or Android graphical consumer applications; consumer-scoped
  packaged callers cannot administer the vault, and the opt-in owner scope is
  exercised only by component smokes (installed-wheel pipe host, Python/Python
  client) rather than a graphical app;
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
