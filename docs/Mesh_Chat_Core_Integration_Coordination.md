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

The current shared feature checkpoint is `677b6bf9e9ea0f50d4465e04cca9f79038632187`
(tree `0e2516336d33d0febd5b152a25ab9b6972f7212b`). Full manual qualification
[42716355520](https://github.com/ahouchens/mesh-chat/actions/runs/42716355520)
is running. Retained selection independently confirms all six suite families and
native workload `full`; duplicate PR run `42716363961` was canceled.

This exact source passes SDK staging, **3,554 required policy tests**, **670 Python
plus 12 rendered App/Core cases**, and **nine Windows component cases**, with
zero failures and skips. It integrates C's public AGP DSL receiver fix `595b1bf`
and D's bounded stage timing/read-count/provenance diagnostics `1f177e4`.
The independent Android build and two installed cases remain unqualified;
Windows pairing's cause remains unproven. All workers hold source while the lead
validates platform reports. No release, default or scenario promotion.

Current CI independently passes all 3,554 policy cases and the 670/12 boundary;
broad verification also passes. Windows public pairing fails again, but its new
timing evidence excludes late acceptance in this run: acceptance starts at
28,701 ms and returns at 28,714 ms. The pending-request wait completes **1,945
snapshot reads** before failure at 240,072 ms; no clipping occurs and its entry
deadline flag is false. The final offerer snapshot is explicitly from that wait
and contains zero contacts. Both final pairing probes are retired, not expired.
This establishes a real post-accept observation period without the required
request; it does not establish delivery failure or retirement cause. C reviews
frozen-runtime/bootstrap differences offline; A/D audit existing public request
state observations. Android and direct results remain pending.

The previous feature-branch checkpoint is `577250e7b0dad8fca7a9d460f5e990dcc29af8dc`
(tree `2ff3f7c8aac2d558e9af05a1d3aaca04e0a6048b`). Full manual CI
[42711039872](https://github.com/ahouchens/mesh-chat/actions/runs/42711039872)
completed failed at **22:46:32 UTC**. Its retained selection confirms all six families
and native workload `full`; duplicate PR run `42711014339` was canceled.

At this exact source, SDK staging and **3,529 required policy tests** pass using
only the service source path. The App/Core boundary passes **670 Python plus
12 rendered cases**, and the Windows component boundary passes **nine cases**,
all with zero failures and skips. These local results do not qualify actual
Android execution, frozen Windows pairing, or cross-platform receipts.

The completed run independently passes **3,529 policy cases**, the **670 Python
and 12 rendered boundary cases**, normal Windows bootstrap with actual DPAPI/EFS,
nine Windows components, and both direct-platform suites (25 transport, ten
recovery and 12 setup cases each), all zero skips. Broad verification also passes.
Android independently passes **all 50 existing emulator cases**, including the
three repaired cleanup cases, with seven retained APK/AAR hashes and 62 JVM
passes. Its two new independent-consumer cases never run because runtime-host
Gradle configuration fails on an AGP 9.3.1 source-set type cast. There is no
overall Android acceptance. Native interoperability is skipped after prerequisite
failure; later Windows packaged gates also do not run.

Windows public pairing fails after 245.79s at **pending_request_wait**. An
invitation reached the answerer and its accept call returned. Last snapshots may
predate acceptance: the wait checks the shared deadline before its first read,
so no post-accept poll is proven. Both fresh public probes report `retired` with
`expired: false`. Neither acceptance timing nor delivery/retirement cause is
established. A finds no missing public operation or dropped effect wiring.
C's controlled direct-permitted source reproduction delivers the request quickly;
it does not reproduce the CI relay route.

D's isolated diagnostics `1f177e4` are integrated at `f0372da`, with **349 focused
lead checks passing** without skips in 16.23s. Monotonic stage offsets, bounded
post-accept read counts and snapshot provenance preserve existing requests,
deadlines, original failures and cleanup. C owns the narrow Gradle configuration
repair. The next source still requires exact local gates and full CI.

C's one-file repair `595b1bf` is now integrated: runtime-host uses the public
`com.android.build.api.dsl.LibraryExtension` receiver, preserving its configuration
body, generated-source provider, task dependencies and publication. An actual
cached AGP 9.3.1 object rejects the old cast and accepts the new one; the exact
configuration body compiles against cached AGP/Gradle APIs. Twenty-six focused
distribution checks pass. This is API/component evidence; the independent
publication, APK build and two installed cases still require CI execution.

This checkpoint includes the clean SDK import repair, ordinary independent
Android consumer and ADB stdin repair, supported Windows readiness query and
bounded pairing failure diagnostics, and the Android cancellation test repair.
The Android inventory now requires **52 cases and 17 artifact hashes**, retaining
all previous 50 cases. Production native disposal and timing bounds are unchanged.
The single instrumentation test ownership has returned from C to D.

Previous full CI `42704405112` at `32cc1d5` completed **failed**. Its retained
evidence independently passes the 670/12 App/Core boundary, normal installed
Windows bootstrap with actual DPAPI/EFS, and both direct-platform suites.
Policy/broad collection failed on SDK import; public Windows pairing timed out;
three of 50 Android cases failed in native-offerer cleanup. The import and helper
repairs need this new CI run. The pairing timeout's root cause remains unproven.

Protected pending-action recovery and personal direct-IP consent remain reviewed
proposals. Workers hold source unless assigned a specific review or repair; the
lead owns artifact validation and the next integration decision. No Wave 2,
SC21, default selector, release or physical-device promotion follows from these
component results.

Earlier checkpoint history follows. At `a175ae5`, the feature branch was
`5ea2949`.
CI `42693457737` has three known failures, repaired locally: Windows empty
identity assertion (`e8f73e0`), separate Android instrumentation module compile
(`d23452c`) and exact CSS-selector/layout guards (`706df7f`). The exact repaired
UI boundary passes 664 Python plus ten rendered cases. D's public Windows
pairing producer is integrated with 287 focused passes, but requires an explicit
relay-only follow-up before dispatch: direct pairing gathering consent does not
grant persistent personal messaging consent. No private bypass is permitted.
C's standalone Android host plus catalog/startup safeguards `dfc47da` is
integrated, with 38 lead host checks and 26 actual-source JVM checks passing.
A's atomic group producer/SDK `76ed4fb` plus `306feb3`, B's group UI `86366d0`
and owner-retirement follow-up `839c076` are integrated. Eighty App/controller
checks pass after retirement integration. D first repairs the independent
group-operation vectors and real rendered fixture, then continues the
outside-checkout Android runtime-host consumer. Existing worker ownership and
human follow-up authorization remain in effect. No standalone AAR/device claim
follows from cached Kotlin compilation or Python/JVM components.

The shared checkpoint includes C's reviewed Android provider correction
`0bfb95d`. Separate protected catalog authority avoids reading the profile key
at locked startup; each OS credential confirmation uses its own AndroidX result
registration. The lead's exact SDK staging and 115 lifecycle/mobile-host checks
pass, including installed consumers. B may bind the actual Android credential
facade; Windows remains unsupported until its native provider exists. D adds the
three registry cases to required Android execution. Compilation and JVM checks
do not qualify successful OS credential interaction on a device.

Full CI `42683615511` completed with a failed gate at the earlier `21bb99c`
checkpoint. Policy, Windows packaged first-contact pairing, 649-Python/ten-App
boundary, 47 Android cases and both direct-transport platforms are independently
validated. Broad verification also passes. Windows native interoperability fails
because its controller used an invalid pipe namespace; Android then fails
rendezvous. Repair `19dcf00` is integrated at `1ba621c`, with all nine Windows
component cases passing. A fresh full run is required for the repaired controller
and all subsequently integrated production changes.

C's hooks and A's durable public pairing producer are integrated at `787b6aa`.
Exact SDK staging, 79 actual-actor/installed-consumer checks, 50 TypeScript SDK
tests and strict model/reducer typing pass. B's WebRTC call-site scope wiring
passes 61 focused checks. C's native disposal coordinator retains failed peer
and channel wrappers until exact acknowledgments; all 21 actual-source JVM
checks pass after integration at `0d4758e`. Actual Android execution is pending.
D's normal installed Windows bootstrap gate is integrated at `b4d3277`, with
162 focused checks passing. Its actual frozen/EFS producer remains CI-only;
these component results do not qualify SC21. The full local policy run at
`787b6aa` has 3,359 passes and nine failures: eight external-fixture inventory
path failures and one missing pairing-vector inventory. D's pairing vectors
are integrated; the inventory-root repair and complete rerun remain required.
B continues native profile UI and C the standalone Android host. The older
checkpoints below retain their chronology.

The inventory repairs and B's native profile controls are now integrated at
`5ea29493d0420896a8801169c78145e640fdc5dd`. Its exact SDK stage, complete policy
(3,379 passes, zero skips), App/Core boundary (664 Python plus ten rendered cases)
and nine Windows host components all pass. The lead pushed this checkpoint and
dispatched full CI `42693457737`; duplicate PR run `42693436511` was canceled.
Native profile UI retains explicit keys and rejects late credentials/results
after host replacement. Device credential execution, renderer-restart key
recovery and actual browser-media retirement remain unqualified. A/B review the
next bounded storage/ownership contracts; C continues the standalone Android host
and D the normal Windows installed-SDK pairing producer in separate checkpoints.

Current Wave 2 CI `42676194199` at `da81565` fails two synthetic run-context
fixtures and Windows first-time pairing (`approved_path`, both carriers absent).
The fixture repair is integrated and passes all 94 matrix checks under CI-like
context. C and D prioritize production handoff diagnosis and bounded probe
diagnostics before another full dispatch. Local `a899b85` passes the exact
640-Python/eight-rendered-App gate; `50474ec` adds independently installed public
SDK application staging, with nine focused passes. These do not establish SC21
traffic or packaged acceptance. A's call recovery must preserve ordinary
start/end/start behavior and require actual trusted retirement before replacing
uncertain media resources. B's group keys remain explicit and capability gated.

The run has finished with a failed overall gate. Both controlled direct-network
platforms pass independently validated 25/10/12-case inventories. Android's two
manual-readiness fixture failures are repaired by targeting the inner reconnect
executor (`3a122d4`); Kotlin explicit-key assertion and license packaging repairs
are integrated with host-gated call recovery (`5be412a`, `dee09a7`). The lead's
248 focused checks pass at `5556cc0`. D supplies complete recovery vectors and
failed-run reporting. C's Android provider batch `0b012c3` remains under review:
cold catalog initialization must not read the profile vault key before native
authentication. Windows first-time pairing diagnosis remains the CI priority.

Corrected checkpoint: complete policy at `6875b00` passes 3,251 cases without
skips; exact `efbddfa` boundary passes 649 Python plus ten rendered-App cases.
C's isolated pending-contact projection fix `0af2687` was cherry-picked as
`e7f6497` with attribution, leaving held provider ancestor `0b012c3` out. The lead
passes 31 actual native pairing/runtime checks, including two authenticated
receipts over the original carrier. Full packaged CI is next. A continues public
pairing, C fixes catalog-key/auth-result isolation and app-owned host composition,
B continues lifecycle/effect admission, and D continues independent consumers.

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

Interim CI `42665862417` at `dcac85e` passed the independently reconstructed
2,871-case policy gate, but exposed Windows archive verification, Android test
dependency and stale frontend history assertion failures. B owns the narrow
`service/tests/test_frontend_layout.py` correction; D coordinates the Android
instrumentation repair with C's Gradle ownership. Archive repairs and B's pure
reaction/invitation hooks are integrated at `67ff95b` (225 focused passes, no
skips). A's runtime profile host remains under review for persisted-selection
versus active-vault authority. No new packaged acceptance is claimed.

Runtime host `08e29df` plus persisted-selection fence `fc7e5d9` are integrated
at `8ef8dd5`; source-bound SDK staging and 239 runtime/installed-consumer/upgrade
cases pass without skips. Selected-first compatibility `540d959` is integrated
at `d8869d0`, with four actual older-SDK two-slot cases passing. B now owns
src-only profile lifecycle facade/UI work coordinated with C's platform credential
bridge. A retains `call_manager.py` for protected unknown-call recovery after the
group mutation batch; C owns any required `service.py` glue. Caller operation
keys, consent and unresolved cleanup must survive these boundaries.

Combined `1e288ec` passes 3,108 required policy cases, zero skips, after D's
runtime-host vector correction. D's topology workflow/controller infrastructure
is integrated but held from acceptance until C's trusted supervisor pairing
entry replaces manual handshake orchestration and both platform initiator roles
are exercised. C now exclusively owns `core_api/qualification_host.py` and new
`test_native_pairing_host_port.py` for this narrow private route; ordinary public
SDK/native command authority is unchanged. C also corrects mobile shutdown
acknowledgment when a retiring service still holds its vault and removes the
Windows long-lived initialization-key reference. B's bounded UI lifetime barrier
must keep such pending shutdown outcomes uncertain, with a retry action.

The next checkpoint `ec967947` includes the reviewed private supervisor pairing
entry and truthful mobile retirement acknowledgment (76 lead checks pass),
unwired mobile profile host foundation (14 lead checks pass), and B's bounded
UI lifetime guards (700 frontend tests and the recorded worker boundary pass).
C continues actual platform provider/authentication wiring; B consumes that
contract when available. D migrates the topology controller to the private
supervisor entry and declares quick/full qualification selection. A continues
atomic optional group keys, then protected call-operation recovery. No new
packaged run or broader milestone acceptance is implied.

The complete policy checkpoint `a3a98ce` passes 3,178 tests, zero skips. Follow-up
`d4091fd` passes the exact 640-Python/eight-rendered-App boundary and 63 focused
mobile/group cases. It includes optional keyed group acceptance, supervisor
topology control, source-bound quick/full workloads, actual mobile Core routing
and group/workspace UI admission fences. The next full native CI checkpoint is
ready for dispatch; platform authentication remains pending and is not inferred
from OS boundary doubles.

The reviewed SC21 handoff is in `tests/core-ui-boundary/public-consumer-plan.md`.
A implements public pairing begin/query/cancel after protected call recovery;
begin and cancel both require caller keys. C owns new ordinary app-owned host
bootstrap/composition and Android runtime-host packaging, plus the necessary
`__main__.py` route. A retains `core_api/sidecar_host.py` and `pipe_endpoint.py`.
Existing Python/TypeScript consumer examples remain A-owned; D creates separate
independent consumer directories and their build/evidence scripts. The private
qualifier and seeded cross-UID fixtures cannot qualify SC21. B continues the
remaining asynchronous admission repairs while C completes the real native
credential facade. These are authorized implementation handoffs.

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
