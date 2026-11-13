# Mesh Core compatibility and distribution candidates

Prepared November 13, 2026 for roadmap R8, specification INV25–INV26 and SC25
(§§6.7, 9.7 and 12). This is a candidate inventory at source
`82c336423d6dae4d9d19c1923824cf7db0bed0b0`, tree
`6eade6145309d100f6db82869a31638eb5da2fd3`. It does not declare a
supported release pair or an upgrade window. The source declaration remains
`experimental_unfrozen`, with `upgrade_window: none until independent consumers
pass M5` in [`compatibility-v1.json`](../contracts/core-api/compatibility-v1.json).
The required native and aggregate acceptance for this source is pending. Full
run [43520421850](https://github.com/ahouchens/mesh-chat/actions/runs/43520421850)
at `b8e3e20` is closed failed, with zero cold receipt cycles.

## Version identities to keep separate

| Boundary | Candidate identity | Source of truth and present limit |
| --- | --- | --- |
| Public Core API | Major 1, minor 1; frame `api_version: 1` | `contracts/core-api/operations-v1.json`, `compatibility-v1.json`, and `service/src/mesh_chat/core_api/session.py`. Additive minors within major 1 are accepted; operations and limits still require capability checks. |
| Local internal IPC | Version 1 | `compatibility-v1.json`; this is separate from the public API and peer wire. |
| Signed peer wire | Version 1, declared unchanged by this refactor | `compatibility-v1.json`; explicit installed wire-version pairs remain unqualified. |
| Desktop application and Python service | `0.9.66` | `package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`, and `service/pyproject.toml`. A common package number is not an SDK/API compatibility promise. |
| Service-carried Python client | `0.3.0-experimental` | Service wheel component, not the standalone client distribution. |
| Standalone Python client | `0.3.0.dev0` | `sdk/python/pyproject.toml`; an isolated wheel is staged, while the declaration still marks this experimental component `packaged: false`. |
| TypeScript client | `@mesh-chat/core-client` `0.3.0-experimental` | `sdk/typescript/package.json` is private. A tarball is staged and installed outside the checkout for tests; it is unpublished. |
| Android Kotlin client | `com.meshchat:core-client:0.3.0-experimental` | `sdk/kotlin/build.gradle.kts` builds a thin AAR; the declaration marks it packaged and unpublished. |
| Android app-owned runtime host | `com.meshchat:core-runtime-host:0.3.0-experimental` | `plugins/tauri-plugin-mesh-runtime/android/runtime-host/build.gradle.kts`; this is distinct from the client AAR. ABI, host permissions and exact AAR/APK digests must accompany any tested pair. |

The Python, TypeScript and Kotlin SDKs negotiate capabilities before sending
ordinary commands. The server's versioned frame and the clients' package
versions do not substitute for caller-derived grants, profile scope or native
host authority. The Kotlin runtime host keeps the pinned Android WebRTC
dependency; compatibility work must not replace it with a custom fork.

## Candidate pair evidence, not a support matrix

| Pair or refusal | Executing evidence | What remains |
| --- | --- | --- |
| Old Python `0.2.0-experimental` client carried by the pinned service wheel → candidate API 1.1 Core | `test_core_sdk_upgrade.py::test_actual_old_sdk_to_candidate_core[python]` installs the old component outside the checkout and exercises its established operations against candidate Core. | Packaged Windows/Android native transport and a declared supported window. There was no standalone Python 0.2 wheel. |
| Old TypeScript `0.2.0-experimental` tarball → candidate API 1.1 Core | The `typescript` case of the same installed component test. | A retained installed-platform pair and distribution commitment. |
| Candidate Python or TypeScript 0.3 → pinned API 1.0 host | `test_actual_candidate_sdk_to_pinned_old_host_with_local_composer_refusal` accepts old operations; new composer calls are refused locally before a composer frame reaches the old host. | Complete package/host upgrade pair and data-lifetime evidence on installed platforms. |
| Unsupported API major or malformed capability | `test_core_compatibility.py` rejects unsupported majors before a client command beyond capability negotiation; Kotlin `CoreClientTest.kt` checks malformed majors and transport closure. | Installed incompatible package pair, rejection before mutation on each host, and an explicit exclusion row. |
| Candidate Windows SDK/client with normal host | `test_core_sdk_distribution.py` runs isolated installed SDK flows with real Core; acceptance reconciliation records distribution-only normal-host Windows pairing and two authenticated receipts at `82aaf19`. | Re-run the chosen exact candidate pair on installed host artifacts; complete independent Windows–Android SC21 and SC25. |
| Candidate Kotlin AAR with Android app-owned host | `test_kotlin_distribution.py` checks the public AAR boundary; acceptance reconciliation records independent Binder and cold-process lifecycle components at `82aaf19`. | Exact staged AAR/APK pair, cross-platform peer delivery, native credential confirmation and installed upgrade. |

`test_core_compatibility.py` also checks declaration/version alignment, major-1
additive minor acceptance and operation inventory. The archive smoke tests
verify client-only contents and isolated imports. These tests give component
evidence; none declares all package combinations supported.

## Exact local staged artifacts and pinned upgrade baseline

The `82c3364` local source freeze binds the complete required regression
(6,640 passed, zero failed/skipped), SDK staging and strict model/reducer types
to the source/tree above. The retained local files are under
`.test-tmp/reviewed-controlled-network-82c3364/`; the source freeze and root
review hashes are `b5336b71ff56bcd636a8169350edf246f1aeef9a6891dabdf30e162e20e48dc8`
and `afd46ba7c868c68a29d738bd552e083ffca13105d8a0ccfd5d15b67ae4598b1f`.
The selected full-CI binding names run
[43529724766](https://github.com/ahouchens/mesh-chat/actions/runs/43529724766),
attempt 1, native workload `full`; its result must be read separately.

| Local staged item | SHA-256 | Provenance and limit |
| --- | --- | --- |
| Candidate Python `mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl` | `a6c67d3a4b74c197a6295e95cff862fe7097cd21ed7ba422687262ea2fefaee6` | Fresh `82c3364` standalone-client archive and isolated import. |
| Candidate TypeScript `mesh-chat-core-client-0.3.0-experimental.tgz` | `d74e1c997b2cc1ccee90b88be93d65084154f8ec5251df79e6ae8a9cdca471a1` | Fresh `82c3364` private tarball and isolated import. |
| Pinned old service carrier `mesh_chat_service-0.9.66-py3-none-any.whl` | `446ab4038ddddfb27628a22705cf4aabec8d63e5f526bf7691ebbb1849fb7e9e` | Rebuilt component from exact old Git source; not a retained platform binary. |
| Pinned old TypeScript `mesh-chat-core-client-0.2.0-experimental.tgz` | `731f8c0667aede8bf0c177898d608cdf17d53f93578122324c27449fc5104200` | Rebuilt component from exact old Git source; not a retained platform package. |

The old source is `174728edad62aae6ef16e95b075183d06c5cdda3`, tree
`239d041f87b26f50879008ac947481464dcf4551`, API 1.0. These hashes
identify this particular local staging, not a claim that all rebuilds are
byte-identical. The recorded environment is Windows AMD64, Python 3.13.15 and
Node 24.22.1. The pinned fixture rebuilds an actual service wheel and old
TypeScript tarball from `git archive`; it never treats a source import as a
distribution install. See [`tests/core-sdk-upgrade/README.md`](../tests/core-sdk-upgrade/README.md)
and `android-system-complete-sdk-staging.json` in the freeze.

## Storage, export and uninstall boundary

The runtime owns the vault and its lifetime lock. SDK clients attach through
the authorized host and do not open the database or receive its key. Desktop
uses the `com.meshchat.desktop` application-data `profile-v1` and OS keyring
entry `vault-key-v1`; Android uses private `filesDir/mesh-chat/profile-v1` and
Keystore alias `mesh-chat-vault-key-v1`. These paths are implementation facts,
not a portable backup contract.

The pinned component fixture copies a real format-1 vault, preserves queued
message/receipt/draft records through an injected migration failure, commits
composer format 2, verifies replay after reopen, and checks that the actual
old format-1 host refuses format 2 before service construction. Wrong key,
corrupt record and corrupt database controls do not count as schema refusal.
This is local component evidence, not installed Windows or Android upgrade
evidence. A destructive uninstall fixture must use disposable synthetic data
and stay separate from in-place upgrade. Whole-profile export/import,
portable private-key backup, uninstall/data-clear preservation or removal,
and native installed upgrade are unqualified.

## Smallest next implementation batch

Create a source-pinned **candidate pair manifest and installed-pair fixture**
for one Windows AMD64 package set. Bind the exact staged service/runtime and
standalone Python and TypeScript archives, public API 1.1, IPC 1 and wire 1,
OS/toolchain, permissions and hashes. From an isolated install outside the
checkout, exercise one declared compatible old-client/new-host pair and one
incompatible-major refusal before mutation. Upgrade a disposable profile in
place without replacing its key, then assert identity, history, outbox, draft
and receipt continuity after restart. Keep wrong-key/corrupt-data controls
separate from version refusal. Record the pair and exclusions as *candidate*
results; do not publish a support window from this batch.

After that, qualify the matching staged Kotlin client/runtime-host AAR and
independent APK pair on Android, including installed upgrade and ABI/permission
binding, then reconcile SC25 and INV25–INV26 against exact artifacts. Complete
the distribution notice/license inventory for the actual archives and native
dependencies. Only the integrated, independently installed Windows–Android
consumer and native acceptance evidence can promote the matrix beyond the
current experimental candidate status. Publication and physical-device checks
remain separately deferred.
