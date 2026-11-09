# Core integration coordination — 2026-11-09

Baseline: `435b497150e5f0d12cb1c5dc7b4602da7a66ec4c`.
Lead branch: `codex/mesh-core-integration-lead`.
This file records assignments and integration decisions, not passing evidence.

Current checkpoint: Wave 1 is accepted at `174728e`, pushed to the shared feature
branch. Full qualification run `42644737670` passed all five suite families and
the final gate; the lead independently rebuilt the aggregate from retained
reports. Exact evidence and limits are in the ledger. Wave 2 is activated below.
Existing human authorization covers continued implementation, integration and
worker follow-ups without another permission request.

Wave 2 local checkpoint: `8950053` passes 420 Python and all eight rendered
boundary cases, including same-vault reopen and uncertain-send recovery. The
earlier full policy gate passed 2,630 cases at `6e97db5`. Composer storage,
migration fences, retained deferred cleanup and selected-path inspector code
are integrated. Full combined packaged qualification remains pending.

The next integrated checkpoint is `cabf71f`: standalone SDK staging (`7bc9fea`),
frozen runtime archive/material verification (`9844419`, `27f1236`), and trusted
profile lifecycle transitions (`da18ef3`). The lead's 154 combined lifecycle,
path, package-evidence and call-replay checks pass without skips. Python SDK
staging needs the pending temporary-source build correction before installed
consumer verification; the TypeScript isolated package check passed. B's retained
call-operation ticket is under review, including the incoming-call cleanup guard.
Private host bindings, key release after worker drain, pairing policy, upgrade
checks and actual cross-platform topology qualification remain active work.

Follow-up `7e7249a` is integrated at `f61d480`: temporary-source SDK builds,
private packaged inspector bindings and release of vault crypto references after
successful close. All 12 installed SDK cases pass on the combined source; the
broader run passes 70 cases with one existing Linux-only test skipped on Windows.
CI staging prerequisites are integrated at `d8d47ce` and exact-source staging
passes. Pairing handoff review and incoming-call profile/cleanup guards remain
pending before the next combined policy and packaged qualification run.

The combined policy checkpoint `538ba226` passes all 2,815 required tests without
skips and strict model/reducer typing. Call recovery and incoming profile guards
are integrated; exact UI boundary `7dd1034` passes 471 Python and eight rendered
cases. Subsequent `7b4dc3f` integrates reviewed upgrade fixtures and bounded peer
drivers; 37 focused cases pass. Concrete pairing composition, private profile
host admission, remaining mutation-key extensions and actual topology execution
remain active. Only Wave 1 has complete accepted packaged CI evidence.

## Active Wave 2 handoff

All workers merge the current lead branch before edits. Source `174728e` is the
qualified baseline; subsequent lead-only documentation commits record that
evidence without being relabeled as separately tested source.

- A retains `contracts/core-api/**`, `service/src/mesh_chat/core_api/**`,
  `vault.py`, Core tests and `test_vault.py`. A owns `sdk/**`, the new standalone
  Python client and TypeScript/Python consumer examples, and SDK upgrade fixtures.
  The public Kotlin `CoreClient`, `CoreTransport`, `CoreExchangeTransport`, their
  two JVM tests and `IMeshCoreApi.aidl` transfer from the plugin tree to A for a
  move into `sdk/kotlin`; package and AIDL identities stay compatible. The SDK
  freeze is lifted for A only. A additionally owns `check_python_distribution.py`,
  `check_typescript_distribution.mjs`, `verify_kotlin_distribution.py` and
  `check_core_sdk_upgrade.py`. D retains other qualification orchestration.
- B retains `src/**` and background preference files. Implement the agreed
  Core-persisted composer contract and recovery flow, then cohesive UI/media
  cleanup. Preserve WebView2 calls and do not add renderer retry policy.
- C takes exclusive `service.py` ownership from A (both paths checked clean).
  C owns `mobile_bridge.py`, connection composition/runtime, native onboarding
  and WebRTC service/control, `native_windows_webrtc.py`, the new private path
  evidence adapter, Android `MeshRuntimePlugin.kt`/`NativeWebRtcHost.kt`, and
  the plugin's Gradle SDK dependency wiring. C owns their focused lifecycle,
  runtime, pending-carrier and path-evidence tests. Initial commits cover trusted
  bootstrap, profile-incarnation fences, approved carrier transfer and truthful
  selected-path diagnostics. Native pairing policy and full profile lifecycle
  follow within the existing authorization; exact additional paths are recorded
  before editing. A retains Core host bindings and vault semantics.
- D retains workflows, remaining qualification/build scripts, boundary tests,
  Android instrumentation and independent consumer tests. D adds independent
  composer restart/fault/caller tests, strict packaged source/artifact checks,
  real Windows–Android topology, selected-path negative controls, impairment and
  100-iteration authenticated-receipt/cold-start evidence. C supplies diagnostics;
  A supplies public contracts and staged SDKs. Missing infrastructure is reported
  concretely rather than replaced by simulation or Linux-only transport.

The agreed composer uses public API 1.1 with unchanged existing response shapes,
three additive operations, a stable send revision and a distinct rotating Core
update key. State and matching-draft enqueue commit in the encrypted vault.
Queries stay read-only; replay uses current authority and preserves newer text.
First use atomically raises the vault format floor to prevent older hosts from
bypassing migration fences. SDK 0.3 staging is experimental and unpublished;
baseline Python 0.2 is the actual service-carried client, not an invented older
standalone wheel. Full defaults/legacy-loop retirement remain gated on their
replacement's packaged/emulator qualification. No publication or physical-device
claim is authorized by this handoff.

C's additional C2 paths are assigned exclusively: connection `model.py`,
`reducer.py`, `ports.py`, `commands.py`, new `adapters/pairing.py` and
`test_pairing_runtime.py`; new `native_profile_lifecycle.py` and
`test_profile_runtime_lifecycle.py`. Existing C service/mobile/Android lifecycle
ownership continues, including the plugin's standalone `settings.gradle` wiring.
A retains Core host lifecycle/inspector bindings and vault semantics. Strict
model/reducer typechecking and qualification before default promotion remain
required. A separately audits mutations outside the prior 92 keyed-action
inventory and records domain-hook ownership needs before edits.

C additionally owns `connection/supervisor.py` for atomic pairing handoff and
stale-completion retirement fences. A additionally owns `group_service.py` and
new `test_group_operation_idempotency.py` for additive explicit-key mutation
support, preserving declared legacy request behavior. D independently verifies
the new capability and replay/authority contract after A supplies it.

B additionally owns `reactions.py`, `contact_invitations.py`, and new
`test_reaction_keyed_preparation.py` / `test_contact_invitation_keyed_preparation.py`
for prepared domain writes and post-commit effects coordinated with A's caller
receipt transaction. A additionally owns `direct_recovery.py` for import/export
resource intents. C retains `service.py`, reconnect and participant glue; current
pairing work stays first. No owner silently changes another owner's files.

## Historical Wave 1 ownership and gate

| Owner | Exclusive changes | Required outcome |
| --- | --- | --- |
| A | `contracts/core-api/`, `service/src/mesh_chat/core_api/`, existing Core contract/parser/session tests | Serialized requests agree with production parsing and session validation; mutation idempotency is durable and caller-scoped. |
| B | Application `src/` and its tests | Core parameter names survive serialization; ambiguous sends reuse their key; accepted sends cannot be restored after a refresh error; media remains in WebView2. |
| C | `src-tauri/src/`, runtime-plugin Rust, Android runtime/Binder implementation and host tests | Windows and Android expose working snapshot, profile, request and send routes with caller authority and correlated typed errors. Public Kotlin SDK files remain frozen. |
| D | Workflows, qualification scripts, new cross-boundary tests | Tests exercise serialized frontend/host traffic through the production parser/session or actual host, and required evidence cannot silently skip. |
| Lead | Roadmap, acceptance, ledger and this coordination file | Review and merge A, C, B, D in order; run combined checks; inspect exact-source CI artifacts. |

No owner edits another owner's file. Cross-owner requirements belong in worker
reports until assigned. Worktrees and their build caches stay separate. D owns
coordination of emulator/packaged verification resources; no concurrent local
emulator reservation is granted during bootstrap.

Wave 1 passes only when actual Windows and Android app paths load application
and workspace state and execute representative messaging, settings and call
control through Core. Native Windows transport replaces messaging only. WebView2
audio/video remains supported. Schema validation, simulated service ports and
legacy command mocks cannot alone satisfy this gate.

## Cross-owner interface requirements

1. A/B/D: `conversation` and `thread_root` remain Core contract fields. Conversion
   to legacy domain IDs occurs inside the protected adapter, never before a typed
   Core request reaches the production parser.
2. A/B/C/D: request idempotency keys must survive the host route unchanged. The
   parser and session must agree on accepted keys for all mutation operations.
3. B/D: distinguish uncertain enqueue outcomes from confirmed acceptance and
   subsequent snapshot failure. Retry the former with the same key and payload;
   the latter must not reinsert text into the composer or send again.
4. C/D: test the mobile entry points rather than passing Android via desktop-only
   mocks. Preserve Binder caller identity across executor dispatch.
5. D: full qualification must be explicitly dispatched for the integration head.
   The baseline workflow push filter does not include this feature branch;
   a successful push by itself does not establish a CI run.

## Remaining specification ownership inventory

Wave 2 assignments below are active after Wave 1 integration and qualification.
The handoff above records first-batch paths and the Kotlin ownership transfer.
Additional paths are assigned before edits; each worker keeps its exclusive scope.

| Owner | Remaining acceptance obligations |
| --- | --- |
| A | SDKs and independent distribution-only consumers; install/upgrade and preserved data; API/package compatibility and rejection; event replay/gap recovery; runtime ownership and multi-client consumer semantics (INV21–26, SC21–26, sections 6.5–6.7). |
| B | Remove UI compatibility/policy paths after qualified replacement; media teardown and pairing closure coexistence; supported UI through the same facade (INV17/22, SC17, section 3.3). |
| C | Supervisor promotion, native contact/workspace pairing, profile create/select/unlock/lock host lifecycle, exclusive runtime ownership, legacy policy retirement, all-mode foreground/background parity and exact-resource cleanup (INV01–19/22, SC01–19/26). |
| D | Packaged Windows/Android and WebView interoperability; selected ICE path with negative control; forced relay, UDP denial and rebinding; 150 ms RTT fault budgets; saturation and 100-iteration receipt/cold-start matrix; baseline timing and wire fixtures; mandatory exact-source CI evidence (SC01–26, INV20). |
| Lead | Reconcile all 26 invariants, all 26 scenarios and section 13 boundaries; document storage/export/uninstall, support windows and redistribution obligations with implementation owners; keep publication and physical evidence separate. |

## Evidence rules

Each integration batch records base/result SHA, changed files, command and test
counts, dependencies and limits. Historical manifests qualify only their named
source/artifacts. Unit/local, native component, emulator, packaged and workflow
evidence are distinct. No physical qualification is available. No release, tag,
publication, force push or main merge is authorized.

## Historical Wave 1 follow-up assignments and checkpoint

At `8a902a05b580408a4f1853904f8e6ade01f41d95`, the private native host port
separation and Android enqueue `kind: text` fix are integrated. Ordinary public
owner grants cannot advertise or invoke the native command port. The lead ran
211 contract, host and real Windows pipe cases with no failures or skips; strict
model/reducer typechecking also passed.

The complete required policy inventory at `d4945d0` executed 2,240 cases:
2,239 passed and one failed, with zero skips. The isolated contact worker test
reached recipient readiness but received no inbound invitation. A focused rerun
at `8a902a0` reproduced that failure (one pass, one failure). This is not passing
qualification evidence.

C now exclusively owns `service/src/mesh_chat/contact_bootstrap.py`,
`isolated_bootstrap.py`, `direct_bootstrap_process.py`,
`direct_bootstrap_worker.py` in that same directory, and
`service/tests/connection/test_contact_bootstrap.py` for this gate repair.
A owns the production `core_api/pipe_client.py` buffer correction exposed by D's
new real-transport tests. D owns
`service/tests/connection/test_matrix_evidence.py` and the reserved
`TypedCoreBridgeBoundaryTest.kt` instrumentation file. These assignments do not
activate Wave 2 or transfer the public SDK files.

For durable keyed mutations, A additionally owns `service.py`, `vault.py`,
`call_manager.py`, `workspace_service.py`, and `remote_service.py` under
`service/src/mesh_chat/`, plus `service/tests/test_vault.py`. Prefer prepared
domain writes and the existing `VaultStore.commit_operation` boundary. External
network/resource effects need committed intent and recovery; a vault transaction
cannot make those effects atomic. C's later lifecycle ownership excludes these
files until explicitly transferred.

Subsequent transfer: C exclusively owns `service/src/mesh_chat/remote_service.py`
and the new `service/tests/connection/test_remote_profile_idempotency.py` for
remote-profile keyed durability. A's worktree was verified clean before transfer.
A retains the Core adapter in `service_workspace_admin.py`, and wires the optional
domain `operation_id` argument supplied by C. Persisted runtime intent must use
current consent/settings during reconciliation; replay cannot restore revoked
approval or return cached connectivity as current state.

B resumes bounded Wave 1 onboarding work: stable profile-create keys and retry
handling. A supplies the trusted private bootstrap on an already-started empty
service, without widening ordinary public-owner grants. B's Core-owned composer
revision/CAS and atomic draft-bound enqueue proposal is the accepted Wave 2
design direction; implementation remains gated on Wave 1.

Further Wave 1 transfer: C exclusively owns
`service/src/mesh_chat/reconnect_service.py` and the new
`service/tests/connection/test_reconnect_prepared_mutations.py`, alongside its
remote-profile files. C prepares remote approval and reconnect device/profile
writes without storage or network effects. A retains `workspace_service.py`
and `service.py`, composes parent records and operation receipts into the atomic
commit, then reconciles current consent. D independently audits supported keyed
mutations and required host inventories. General Wave 2 remains inactive.

A additionally owns `service/src/mesh_chat/background_availability.py` for
keyed runtime preference changes and post-commit reconciliation. D's independent
signed-membership-removal replay regressions remain in its reserved
`test_ui_core_boundary*.py` files; A repairs the production authority ordering.

To parallelize the remaining bounded Wave 1 work, the lead verified A's
`background_availability.py` path clean, then transferred it exclusively to B,
with the new `service/tests/connection/test_background_preference_idempotency.py`.
A retains the Core runtime adapter. C additionally owns
`service/src/mesh_chat/participant_service.py` and the new
`service/tests/connection/test_participant_keyed_preparation.py` for route resource
reservation and prepared access replacement; A retains route parent operations
in `service.py`. These assignments do not activate general Wave 2.

Consent administration requires `approve` in addition to the existing `send`
grant for remote-profile create, approve/remove propagation and remove; workspace
access-recommendation apply/apply-by-ID; and workspace reconnect consent. Query,
test, retry and ordinary send actions retain their separate requirements. A owns
contract metadata and enforcement; D owns independent consumer denial, owner
success and revoked-grant replay checks, plus aggregate boundary evidence wiring.
