# Connection runtime qualification ledger

## Integration revalidation (2026-11-09)

### Wave 2 interim CI and packaging repairs

Full workflow `42665862417` targets source
`dcac85ef30a0ff60f51d7862ad03c3fe692b0299`, tree
`5271a0f95e3f33d20a99cb23ac0a2363d46dede5`. The lead independently reconstructed
the retained policy report using that source's validators: 2,871 collected,
executed and passed, zero failures or skips, qualification ID
`517aba734b0f4586bb04929837e5688f`. This is simulated/in-process evidence.
The workflow is not accepted: Windows failed frozen-material verification;
broad verification passed 4,075 tests but failed one stale frontend history
assertion (51 environment-specific skips); Android instrumentation compilation
could not resolve its transitive Binder SDK dependency. Direct jobs were still
running when this checkpoint was recorded.

Read-only inspection of the retained Windows executable confirmed SHA-256
`1b9d37786c8c626fcd28c4d9e8021480c95e63c9c070255798a87fe4927df8b2` and identified
the declaration basename mismatch and repository CRLF/LF inconsistency. Worker D
also checked 34 notice/metadata files across 17 distributions, 161 DLL/PYD files,
all 36 PyAV wheel DLL hashes, and required PYZ modules. This diagnosis neither
runs the executable nor qualifies repaired source. The lead retained the archive
hash index and build manifest, then removed its temporary executable copy.

Source `67ff95bd346771e1a6d62205a5ecb612c0da6a39` integrates basename and canonical
repository-byte repairs plus prepared reaction/invitation hooks. The lead ran
225 focused domain, legacy behavior, archive and aggregate cases: all passed,
zero skips, 12.30 seconds. Invitation preparation does not itself establish atomic
personal adoption/workspace join; parent integration remains required. Runtime
profile host binding and actual Windows–Android topology remain pending.

### Wave 2 combined policy and upgrade checkpoint

Source `538ba22692657c8af557e0095dd27dc1d23541e9` passes the complete required
policy inventory: 2,815 collected and executed, zero failures/skips, 263.90 seconds
pytest elapsed time. Strict model/reducer typechecking also passes. Reports are
`dist/reports/policy-wave2-sdk.*`, run `af675894f03841c0aaed53e547f10ba0`.
Warnings concern JUnit properties and the existing upstream LXMF deprecation.
The lead also ran 62 focused call-operation, incoming-call and API tests, all
passing. The preceding exact UI boundary at `7dd1034` passes 471 Python and all
eight rendered-App cases, zero skips, 48.11 seconds. Windows pipe checks at
`6a7656c` pass all three cases without skips in 1.81 seconds.

Source `7b4dc3f58d8bbc5aefbf8720807b31a60665da5f` then integrates pinned upgrade
fixtures and packaged peer-controller code. All 37 upgrade/peer-driver cases
pass without skips in 17.46 seconds (`.test-tmp/upgrade-peer.*`). The eight upgrade
cases install rebuilt source-pinned API 1.0 artifacts, test both client/host
directions, preserve format-1 data through migration and require the old reader's
specific schema refusal after format 2. Wrong keys and corrupt storage cannot
qualify as downgrade refusal. The other 29 cases verify controller framing,
deadlines and exact cleanup ownership, including blocked OS-pipe readers.

These upgrades use rebuilt component artifacts from `174728e`, tree `239d041`;
they do not qualify an installed native executable or Android package upgrade.
The new peer drivers have not yet established Windows–Android interoperability,
authenticated receipts, impairment budgets or the 100-iteration matrix. The full
policy result belongs to `538ba226`, not the later fixture/driver source.

### Wave 2 profile transitions and package evidence checkpoint

Source `cabf71fc198dd478b10cd783dd11fa1bb57ff94d` integrates the standalone SDK
batch, runtime archive inventory/license checks and trusted profile lifecycle.
The lead ran 154 combined profile-transition, selected-path, runtime-material,
call-replay and aggregate-evidence cases: all passed, zero skips, 8.94 seconds.
JUnit and the execution log are retained as `.test-tmp/lifecycle-materials.*`.
The lifecycle tests include deferred worker shutdown, failed publication,
committed selection reply loss and old-host replay fences.

These are component and evidence-validator checks. No newly frozen executable,
Android package or Windows–Android path has been qualified by this run. The
TypeScript archive passed isolated installation/import; Python wheel staging
failed with a stale source build directory and awaits a temporary-source build
fix. Neither that failure nor partial SDK execution counts as a passing installed
consumer gate. Shared feature source `174728e` remains the accepted CI baseline.

Follow-up at `f61d480b383ca9d3f6c0fca83664ea32a89a2445` corrects source build
pollution and Windows consumer cleanup, adds private packaged inspector admission
and releases vault crypto references after successful database close. The lead's
combined installed-SDK, private-host, Android retirement, profile lifecycle and
vault run passes 70 cases in 7.90 seconds, including all 12 installed consumer
cases. One existing Linux `/sys` device-node test is skipped on Windows; this is
not a zero-skip policy qualification. Reports are `.test-tmp/sdk-host-vault.*`.

Source `d8d47ce6a94a26ef7c8fd9c097e654c0d2211c6b` adds CI staging prerequisites.
Actual source-bound staging passes for tree `dd2aac53bc3f393f590ae50f0ddb1b7a8bca774c`;
118 staging/selector cases and 47 TypeScript SDK tests pass without skips. These
packages remain experimental and unpublished; packaged transport, old/new upgrade
and cross-platform receipt qualification are still required.

### Wave 2 composer storage checkpoint

Source `30392040a79eb9048ce4ed4ab3164c16451d34d3` integrates A's
`edc0e78` production composer and D's `75d6185` independent requirements.
The lead ran 43 composer contract, storage, migration and real framed boundary
cases: all passed, zero skips, 2.90 seconds. This includes the 11 independent
cases previously failing at capability admission on `1344a1a`. Fifteen
Windows-applicable vault tests also passed in 0.51 seconds; the Linux `/sys`
device-node case was explicitly deselected, not counted as qualified.

Composer updates and draft-bound enqueue now persist atomically with their
receipts; replay preserves newer text and rechecks authority. First use raises
the vault format floor to 2 and persistently fences migrated legacy writes.
These are local durability checks. The eight required rendered-App cases,
packaged upgrade fixtures and combined Wave 2 CI remain pending. The accepted
Wave 1 source and its evidence below remain unchanged.

### Wave 2 lifecycle and private inspector checkpoint

The lifecycle batch `9559312` and deferred-constructor correction `d86b47a`
were integrated at `644c6b6`. A failed unpublished service retains ownership
while cleanup is deferred, and the bridge rejects replacement initialization
until that exact runtime releases its vault. The lead ran 138 combined mobile,
profile-lifecycle, pending-carrier, runtime and composer cases: all passed,
zero skips, 3.90 seconds.

Private inspector `409a4e8` was then integrated at
`1c360bd3d64f09ee95f888f430813d28becf9783`. Thirty-seven inspector, native Windows
and lifecycle cases passed, zero skips, 3.38 seconds. All 669 Core and contract
tests passed on that combined source, zero skips, 30.22 seconds. The inspector
reports current resource/incarnation-bound path observations and marks unavailable
measurements explicitly. These checks do not prove a relay path, cross-platform
traffic or fault budgets; those require the active topology qualification.
At that checkpoint, submission-failure cleanup and Android sampling remained open.

The full required policy inventory subsequently passed at `6e97db5`: 2,630
executed, zero failures/skips, 244.28 seconds, with the upstream LXMF deprecation
warning. JUnit, collected inventory and validated policy report are retained.
This source precedes the composer UI merge.

At `b2df9ae`, the combined composer UI boundary executed all required cases:
359 Python cases passed, while five of eight rendered cases failed (zero skips).
Both newly added remount cases were among the failures. Three actual Windows
pipe boundary cases passed in 1.65 seconds. Rendered failures are assigned to D
and B for diagnosis; neither frontend unit success nor policy success closes
this boundary gate. A local pytest-cache ACL warning did not skip cases.

Inspector cleanup `9df4b1a` and Android sampler `aec8946` were integrated at
`0bf8d04`. All 34 Python inspector/Windows cases passed, zero skips, 3.08 seconds.
Android observes libwebrtc's selected-pair and relay-protocol statistics and
explicitly reports the outer TURN socket unavailable. Its packaged qualification
remains pending; advertised TURN URLs never establish the selected protocol.

The corrected combined UI boundary passed at
`8950053cd904458369d1eaf6245cd003fda0b745`, tree
`d732fec4210721bb3050ee6c26aafd6f6db19096`: 420 Python and all eight rendered
cases, zero failures/skips, 25.74 seconds. D's `8c496ad` repairs the substituted
host's missing peer-destination lookup by using actual Core profile/peer queries,
waits for editable live fields and injects reply loss after the actual atomic
draft enqueue commits. It retains same-vault reopen, same-revision retry,
one-message and no-legacy-fallback assertions. This supersedes the failed
`b2df9ae` rendered checkpoint, without turning substituted Tauri invocation into
packaged-host evidence. Only pytest's cache provider was disabled for the local
ACL issue; collection and required case inventories were unchanged.

This source also includes the standalone Kotlin source move `d308c83`, host
dependency/settings wiring through `7f502fb`, and D's bounded encrypted CI
rendezvous helpers through `8358ba4`. The lead's 27 Kotlin distribution-policy
and compatibility cases passed at `ea0dc29` in 1.14 seconds. Kotlin compilation
and actual cross-runner transport remain unqualified. The artifact helper
rejects plaintext payload shapes at publication; REST metadata authenticates
repository/run/source provenance, while producer-role enforcement relies on
trusted workflow code and is not independent server attestation of the job.

### Wave 1 accepted at the fully qualified combined source

The combined implementation is `174728edad62aae6ef16e95b075183d06c5cdda3`,
tree `239d041f87b26f50879008ac947481464dcf4551`. The feature branch was
fast-forward pushed to that commit. The finite inventory of 92 supported keyed
mutation actions now has implemented parents, including route create/apply;
this inventory is bounded review evidence, not a proof of every runtime property.

Workspace reconnect consent, access approval and contact invitations commit their
prepared records and operation receipts together before effects. Successful
no-op mutations also consume their keys. Current signed membership and explicit
consent are checked before replay. Route creation reserves the resource and key
before allocation, then commits the exact signed document, generation, stable
delivery job and completion together. Route application atomically replaces
consented scope and generation. Resource retirement retries exact cleanup and
retains capacity through the possible lease when storage failure and restart
lose the cleanup handle. A successful transport handoff is not a peer receipt.

| Executed check | Source | Result and limits |
| --- | --- | --- |
| Lead full required policy inventory | `174728e` | 2,489 passed, zero failures/skips, 226.04 s. One upstream LXMF deprecation warning. JUnit and collection inventory retained. |
| Lead combined route/participant regression cases | `174728e` | 45 passed, zero skips, 4.58 s; fault, replay, resource and scope behavior. |
| Strict model/reducer mypy | `174728e` | Passed for both selected source files. |
| D independent UI boundary | `174728e` | 297 Python plus six rendered-App cases, zero failures/skips, 20.55 s; Tauri invocation is substituted. |
| D actual Windows pipe boundary | `174728e` | Three cases, zero failures/skips, 2.36 s; production pipe and in-process domain, not packaged transport delivery. |
| D evidence/CI validation | `174728e` | 86 cases, zero skips, 3.59 s. Production retained-report validators independently accepted exact source/tree, report and inventory hashes, complete case identities and run IDs under `python -S`; negative controls rejected altered evidence. |
| A all Core/contracts/participant tests | `2563b6b` | 664 passed, zero failures/skips, 28.02 s. This precedes the final C lease-capacity follow-up and is not relabeled as combined-source evidence. |

The full five-family workflow
[42644737670](https://github.com/ahouchens/mesh-chat/actions/runs/42644737670)
was explicitly dispatched for `174728e`. Its duplicate PR-triggered run
`42644746899` was canceled. CI policy (2,489 cases), application verification
(including 297 Python and six rendered boundary cases), Windows host checks
(including three pipe cases) and Android qualification have passed. The lead
independently revalidated their retained reports against the exact source,
tree, run identities, case inventories and report hashes. All 47 Android cases
(21 WebRTC, ten signaling, ten Core API and six independent-consumer cases)
passed, and all seven tested APK/AAR files were retained and independently
rehashed. The Android platform is API 35 x86_64 emulation. Windows packaged
lifecycle, transport and pairing reports reference the same tested sidecar and
native host; those archives contain reports only, so their binary digests remain
runner claims rather than independently rehashed binaries.

Both direct-transport jobs passed: each platform executed 25 carrier, ten
recovery and 12 setup cases, zero failures/skips. The lead independently
validated their exact-source inventories and distinct execution IDs. Their
binary digests remain runner claims because these archives also contain reports
only. All five workflow families and the final aggregate gate passed. The lead
rebuilt the complete aggregate from the downloaded reports and obtained an
exact match with CI's retained manifest.

Wave 1 is accepted at `174728e`. Wave 2 is now activated for the remaining
implementation and qualification obligations in the coordination inventory.
This closes the repaired application/Core boundary gate; it does not close the
broader M2–M5 or section 13 requirements.
No release, publication, physical-device or Windows–Android interoperability
claim follows from these local checks.

### First combined implementation checkpoint

The lead merged A `947e338`, C `1141e25`, B `8f1ceab`, then D `28752d5`
(including `e2cf2ca` and `136cb07`) with merge commits, reaching
`2e7536847a351387a5d7fcf5d22b9d3d8c21cd5b`. No feature-branch push or full CI
qualification is claimed for this checkpoint.

| Executed by lead | Exact source | Result and scope |
| --- | --- | --- |
| Existing Core and contract tests | `00d06525d05d033cb8396a532b0b4419354de59a` | 552 passed, zero skips, 20.29 s; production parsing, session and local service coverage. |
| `check_core_ui_boundary.py` | `2e7536847a351387a5d7fcf5d22b9d3d8c21cd5b`, tree `8e9137c91b0108b4eb2e275788a40b8ef3684c2d` | 267 Python cases and five rendered-App cases passed, zero failures/skips, 24.24 s total. Real serializer/framing/parser/session/vault; Tauri invocation is substituted. This is not native-host or packaged evidence. |
| Application and boundary TypeScript checks | `2e75368` | Both passed. |
| Android-host, contract and workspace-admin tests after A `3feb24f` | `963538c408f3cfd8f6397462b27137a5e56f5132` | 197 passed, zero skips, 10.79 s. Service incarnation changes fence cached sessions; nullable workspace notifications and history actions align with UI/domain behavior. |

The first boundary attempt failed because sandboxed esbuild could not traverse
the workspace parent. The complete rerun outside that sandbox passed; a local
pytest cache ACL warning remained, with no skipped test. Test outputs and vaults
were worktree-local. Disk exhaustion interrupted worker native builds; those
builds are not passing evidence. Heavy native/emulator work is assigned to CI.

Review found a blocking defect in C `1141e25`: Android's `sendMessage` convenience
omits the required `kind: "text"` field. The owner has an explicit correction in
the coordination plan; the added Binder instrumentation must execute it against
the production parser. Public-owner access to private native commands, remaining
keyed-operation durability, full settings/call-control mutation coverage, and
full exact-source CI remain open. B's pending-send identity and accepted-draft
suppression are limited to the mounted renderer; restart-safe pending UI work
remains a separate implementation requirement. Wave 1 is not accepted yet.

### Follow-up checkpoint and first full CI dispatch

At `29a56069f085c5a234f9b3a13547b614f9e6d30e` (tree
`92068fce54bd4a4e4f5d7d06859626cec5cdb2dc`), A's private native port and
Windows pipe buffer fixes, C's Android enqueue kind correction, and D's settings
and signed call-control mutation checks are integrated. The lead executed:

- `check_core_ui_boundary.py`: 271 Python cases and five rendered-App cases,
  zero failures/skips, 14.12 seconds. Tauri invocation remains substituted.
- `check_core_windows_boundary.py`: two cases, zero failures/skips, 1.36 seconds
  of test execution. This uses the production named-pipe endpoint and client,
  authenticates the actual client executable, persists settings, and verifies
  signed call invite/hangup records. It does not exercise media or peer delivery.
- 211 contract/host/pipe tests at earlier checkpoint `8a902a0`, zero skips;
  strict model/reducer typechecking passed. The unchanged frontend source also
  passed all 614 tests (37 files, 53.26 seconds).

The full required policy inventory at `d4945d0` failed: 2,239 passed, one failed,
zero skipped, 229.88 seconds. The isolated contact-worker invitation test reached
recipient readiness but observed no inbound event; a focused rerun at `8a902a0`
reproduced it. C owns that repair. Fresh-profile private bootstrap and keyed
mutation durability are also open, with A/B ownership recorded in coordination.

The feature branch was fast-forward pushed to `29a5606`. Full workflow dispatch
[42630080557](https://github.com/ahouchens/mesh-chat/actions/runs/42630080557)
completed for that exact head with all five suite families selected. The
redundant PR-triggered run was canceled to avoid duplicate runner consumption.
Neither dispatch nor the local boundary results establish Wave 1 acceptance.

### Onboarding, storage and durability follow-ups

The full local required policy inventory passed at
`575171609a67b0dfda6e53edd1a06380058168dc`: **2,259 tests, zero failures/skips**,
210.57 seconds. C traced the earlier contact-bootstrap failure to Windows path
limits in RNS resource/cache files. Shorter private paths and an initialization
write probe fixed the original test without extending timeouts or weakening
signature/scope checks.

Atomic private profile creation, verification-only pre-profile preview and the
corresponding onboarding UI are now integrated. Identity/profile/settings/replay
records commit before network effects. Preview does not create an identity,
write the vault, contact a network endpoint or accept an invitation. Ordinary
public owner grants cannot attach either private bootstrap or native ports.

| Executed by lead | Source | Result |
| --- | --- | --- |
| Bootstrap, message and host regressions | `8cc225a` | 94 passed, zero skips, 4.49 s. |
| Bootstrap and contract tests | `1985be8` | 197 passed, zero skips, 13.21 s. |
| Full frontend suite | Frontend source at `1985be8` | 637 passed across 37 files, 51.44 s; the subsequent concurrent merge changed only the boundary harness. |
| Actual Windows pipe gate including empty-profile create/replay/reopen | `e0b2ee2` | Three passed, zero skips, 1.37 s. |
| Admission-grant and legacy workspace regressions | `4c9bda7` | 82 passed, zero skips, 32.74 s. |
| Serialized Core and rendered-App gate | `c49e65b` | 275 Python and six rendered-App cases passed, zero skips, 16.22 s. Includes actual empty-vault profile creation, a dropped committed reply, and explicit UI reconciliation without a second identity. |
| Keyed call, existing call/signaling, mobile-fixture and real pipe tests | `22e0532` | 84 passed, zero skips, 3.22 s. |

The first CI checkpoint `29a5606` passed its Windows host and policy jobs.
The lead checked all 2,247 policy cases against their run-bound inventory. The
Android API 35/x86_64 manifest contains **46 passed cases, zero failures/skips**;
the lead checked every case's exact source/tree, run ID and report hash, including
the five typed bridge cases. The retained consumer host APK, consumer APK, test
APK and AAR hashes were independently recomputed. Three tested instrumentation
APKs were not in that archive; D added explicit retention for future runs.
Windows manifests and source hashes were checked with the checkout's CRLF
encoding; package binary hashes remain runner-generated claims in those reports.

The first CI Verify job failed because a test matched composer text before the
thread mutation arrived. D's integrated correction holds the send deliberately,
waits for a rendered message article, and queries its durable ID/content through
Core. Every platform, direct-transport, policy and layout job passed; Verify and
the final aggregate gate failed. Later source still requires full CI.

At `2f3cbbdba4b07eeb4db32cae286bd58ff165a30b`, remote-profile mutations commit
records, receipts and runtime intent before reconciliation. Call replay returns
the current call projection, including an intervening end or ring expiry,
without another signal. The lead ran 73 focused call/remote cases successfully;
the optional remote-network case initially skipped, then passed separately with
its required opt-in (22.34 seconds). That test runs real isolated clients through
an outbound TCP relay, covering personal and workspace admission and delivery.
Remaining keyed domain actions and the restart-safe composer remain open; these
passing slices do not close Wave 1 or M2–M5.

The next full required policy run at `99dd87d` executed 2,334 cases: 2,333
passed, one failed, zero skipped (208.64 seconds). Its SDK coverage assertion
incorrectly treated private `bootstrap.preview` as a public-client obligation.
The integrated correction verifies the manifest's private visibility and public
operation inventory separately; all 20 compatibility cases passed at `4a8453e`.
This focused repair does not convert the earlier failed full run into a pass.

At `685dd5a`, the lead checked keyed composite actions and remote Core adapters:
207 focused cases passed, then the exact-source boundary gate passed 275 Python
and six rendered-App cases with no skips (15.51 seconds). Strict model/reducer
typechecking also passed on the preceding production checkpoint. Independent
review subsequently found that accepted workspace message/read-hint keys can
return success after signed membership removal; this remains a repair input.

The completed first CI direct-transport reports at `29a5606` were also inspected:
Windows and Linux each executed 25 fabric, 10 recovery and 12 setup cases, all
passing without skips. Source/tree, run-bound collection and executed inventories
match. These are controlled native/service component scenarios, not packaged
cross-platform interoperability; binary hashes in these reports-only archives
remain runner-generated claims.

Prepared remote/reconnect helpers at `2def80a` passed 140 focused and legacy
tests without skips. They supply write sets for parent atomic commits; this is
not yet evidence that every parent action uses them. D's two signed-removal
replay regressions were integrated and independently reproduced at `bddf089`.
Mailbox intent batch `61d7a1c` passed 22 focused signaling/call cases, including
an owned loopback HTTP server and a lost reply after encrypted storage. Three
separate external-Worker tests skipped because no test Worker was configured;
they are not counted as passing execution.

The integrated background-preference and aggregate-evidence batch at `2f44bf5`
passed 159 focused cases. Authority checkpoint `68bbd69` then passed 45 focused
cases, including all 16 independently authored consent and signed-removal
regressions. Its exact-source gates passed 291 Python cases, six rendered-App
cases and three actual Windows pipe cases, with zero skips. The new retained
report validators independently accepted their real source/tree, hashes,
collection inventories and executed case identities.

Core runtime key forwarding at `7f1a503` passed 38 focused cases. The complete
required policy inventory on that exact source passed **2,429 cases, zero skips**
in 223.69 seconds. An additional 132 workspace cases outside that required
selection passed at `6407b76` (29.70 seconds). Subsequent independent audit added
two repair inputs: channel-sync replay after signed removal, and an accepted
member-role no-op that failed to bind its key. These were not part of the
passing 2,429-case checkpoint.

Parent consent integration exposed a distinction between manifest device IDs
and signed reconnect protocol device IDs. C's corrective helper batch at
`56ae789` passed 60 focused cases, including actual capability exchange followed
by preparation. The parent transactions and route resource reservations still
require integration and final-source qualification. No Wave 1 acceptance or
general Wave 2 activation is claimed.

### Baseline findings (historical audit)

The current integration baseline is
`435b497150e5f0d12cb1c5dc7b4602da7a66ec4c`. All runs below retain their
historical source/artifact scope; none is automatically evidence for this head.
The supplied baseline audit reports schema/production-parser disagreement,
mutation idempotency rejection, mobile Core stubs and UI serialization/retry
defects. These findings are repair inputs, not passing evidence. The lead has
verified the clean baseline and presence of the native Windows implementation;
combined Wave 1 execution and full CI qualification are pending.

Lead verification at documentation-only descendant `623a7d0` (production code
unchanged from the baseline): `pytest service/tests/connection/test_contracts.py`
passed **25 tests, zero skips**, in 10.62 seconds. A task-local audit executed
the existing vector-generating test, retained requests listed in the manifest's
`experimental_component_operations`, serialized them through JSON, and called
production `parse_request`: **81 accepted, 40 rejected/errored, 121 vectors**.
This count uses that explicit manifest intersection; it is not the supplied
audit's 124-vector selection. The failures confirm the schema suite does not
establish production request acceptance. D owns the committed regression suite.

The GitHub API reports baseline CI run
[42598859239](https://github.com/ahouchens/mesh-chat/actions/runs/42598859239)
successful at `435b497`; it contains the Windows desktop host and generic verify
jobs. This observation is not a new full qualification run or artifact review.

The [coordination inventory](Mesh_Chat_Core_Integration_Coordination.md) records
owners, cross-boundary requirements and remaining specification obligations.
Physical qualification remains unavailable and publication is outside scope.

## Historical evidence

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
| Native contact-deletion retirement (unit) | `pytest service/tests/connection/test_native_peer_retirement.py` | 2 passed: unit proves only bound live sessions close; two-sidecar deletion removes the contact, retires its native session, leaves the other peer untouched and exits cleanly |
| CLI workspace invitation round trip | `pytest service/tests/connection/test_core_client_e2e.py` | 1 passed: owner-granted CLI lists a real workspace and creates I2P-mode invitation material through the host stream |
| Relay-only offer filtering (Windows) | `pytest service/tests/connection/test_native_windows_webrtc.py` | 2 passed: relay-only offer and answer SDP contain no direct candidates without TURN; real relay connectivity remains unqualified |
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
  **partially met** | Android native transport and a native Windows DataChannel
  implementation exist. Native Windows component evidence uses legacy bridge
  policy; production supervisor promotion and cross-platform parity remain open. |
| M4: scenario runner on those exact transports, fault and 100-iteration
  matrices | **not met** | Historical native Windows component fault and receipt
  soaks are recorded above; the complete shared-policy, impaired, cross-platform
  matrix and exact integrated-source qualification remain open. |
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
that all specification requirements are implemented. Native Windows promotion,
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
- full supervisor-owned native Windows production promotion and its complete
  cross-platform impairment qualification (the native implementation and
  historical component tests do exist).

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
