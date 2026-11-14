# Mesh Core refactor: remaining work and completion map

Prepared November 13, 2026; refreshed November 14 through private admission
`de7c54f`, image attribution `4a92903`, release intake `a1f1657`, and
the source-bound results below. The last full native qualification remains failed;
focused diagnostics do not replace it. This is a compact planning register, not
new qualification evidence.
Refresh it when integrating each coherent batch.

The immediate execution plan is in
[the restart strategy handoff](MESH_CORE_RESTART_STRATEGY_HANDOFF.md).
Keep that debugging plan separate from this long-term completion map.

## Intended outcome

A reusable protected Python messaging Core owns policy and durable domain state.
The UI, CLI and independent applications use supported, authorized public APIs.
Thin SDKs carry no peer retry policy. Trusted hosts supply private platform facts;
native adapters perform transport work through ports. Pure state machines,
the connection supervisor and bounded effects have distinct responsibilities.
Migration finishes by retiring superseded messaging policy after parity is proven.

Preserve the Tauri/WebView2 UI and its audio/video calls. Windows headless native
messaging must not depend on a WebView, but the GUI and calls may and should retain
their existing WebView2 implementation. Use the Uncle Bob skill for implementation
and review. The [architecture diagram](architecture/mesh-chat-core.png) expresses
the target boundaries; it is not proof that every milestone is implemented.

## Sources and how to interpret this register

- [Specification](Mesh_Chat_Connection_Runtime_Spec.md): requirements and definition
  of done; includes INV01–INV26 and SC01–SC26.
- [Detailed roadmap](Mesh_Chat_Connection_Runtime_Roadmap.md): milestone history and
  the existing remaining-work checklist.
- [Acceptance reconciliation](Mesh_Chat_Connection_Runtime_Acceptance.md): individual
  invariant/scenario evidence levels and gaps.
- [Qualification ledger](Mesh_Chat_Connection_Qualification_Ledger.md): exact source,
  run, artifact and result evidence.
- `docs/Mesh_Chat_Core_Integration_Coordination.md` in the active lead checkout:
  current assignments and integration decisions. This file is absent from the
  older review checkout where this handoff was prepared; read the active copy
  identified in the companion handoff.
- [Windows/media handoff](NATIVE_WINDOWS_WEBRTC_HANDOFF.md): explicit media
  preservation and coexistence requirements.

These documents contain historical entries. Use the newest matching source/run
evidence; do not promote an old component result to current packaged acceptance.
If a table and newer evidence disagree, reconcile the specific row instead of
silently counting it as complete. The R IDs below group work; they do not replace
the specification's IDs or imply equal effort. Several packages overlap.

## Current checkpoint

- Active `ec81f1f` full/call runs are `43586982197` and `43586979596`. Layout
  and Android builds exposed an optional hook return-type declaration. Correction
  `6797f86` matches the hook's always-present methods; actual `tsc -b --force`
  passes. The earlier root-config no-emit command did not check application
  types. R8's reviewed disposable controller through `a9e650a` passes 14 Python
  and 16 Node tests and is ready for its separate installed CI execution.
  Native/call prerequisites and full acceptance remain open.
- `e543df1` full/call CI exposed a Linux Windows-path fixture mismatch and an
  unsupported idempotency key in the installed private-admission settings probe.
  Both are corrected (`4585da2`, `3fc6590`, strict bridge count `227630b`). Root
  reproduced the installed failure, then passed all 11 corrected fixture checks
  against the unchanged CI sidecar, including revocation and owner EOF/death;
  EFS and owned workspace cleanup passed. Fresh exact-source CI remains required.
  The 14 affected producer/bridge checks pass. See the latest ledger entry for
  exact source, artifacts and the distinction from qualification.
- Recommendation-send UI recovery through `85cdf56` passes 283 App/profile
  tests; application types require the `6797f86` correction above. R8's bounded UI readback contract through
  `983ce05` passes 15 Node tests; the disposable installed continuity controller
  is under review. These advances do not close native, media or upgrade gates.
- Earlier checkpoint before the `e543df1` execution:
- Both `a9f10b3` runs are closed failed. Full-run Windows job `132410157418`
  passed installed image admission, pairing and paired consumer recovery;
  exact artifact and binary validation confirms receiver reopen and authenticated
  later delivery. This verifies the cleanup-slot repair at its declared Windows
  scope. The cross-platform native job was skipped after the Linux test-setup
  failure. The R5 runner separately failed image admission with no inner phase;
  `4a92903` now retains fixed failure phases, and 161 affected checks pass with
  one platform skip. Its actual call role did not execute.
- Integrated candidate `de7c54f` passed 7,204 connection tests with two platform
  skips, exact-source SDK staging, strict types and 44 affected service tests.
  It includes the reviewed installed private-admission producer. A new tested
  source with the small reporting correction needs fresh Linux/native/call CI.
- Earlier checkpoint before those runs closed:
- Source `a9f10b3` passed 7,142 local connection tests, two platform skips,
  exact-source SDK staging and strict types, then started full run `43581311705`
  and installed-call run `43581311710`. Their Linux policy/verification jobs
  exposed seven identical mock-setup failures: `ctypes.get_last_error` does not
  exist on Linux. Correction `7a8ca2f` passes all 16 pipe retirement tests with
  that attribute removed. Native/Windows jobs are still running; the correction
  needs fresh Linux CI. Neither current run qualifies the refactor.
- Opt-in Python/Node private owner and helper admission is integrated through
  `5fa473f`, with 133 Python and 451 Node/integration checks passing. The live
  Windows process witness passed positive and wrong-parent/image controls.
  The installed producer is under independent review; default admission and
  R7/full isolation acceptance remain unchanged.
- All published 0.9.66 Windows installer and Android APK bytes passed the new
  offline intake at `a1f1657`, whose 22 focused tests also pass. This establishes
  released baseline bytes at `7c40f7b`; installed upgrade and compatibility
  scenarios remain open. No old binary was executed during intake.
- Latest full run `43568841923` at `d9ab09f` closed failed at the first Android
  cold `initialize`: control EOF, ADB instrumentation client exit 255, then
  offline transport during rollback. Windows exhausted the partner started
  barrier. The cause remains unresolved; image admission and the separate
  installed capture pass remain valid. Gateway `43571468699` at `12fd342` failed
  because its strict directional-loss parser omitted Linux's numeric seed field.
  The corrected capability passed in `43572907432` at `e6fbbe0`, including 208
  counted directional drops, restored echo and exact cleanup. It remains
  `qualification=false`; actual packaged-peer partition acceptance is open.
- Public owner-restart `43571465943` at `12fd342` failed the Windows paired-process
  recovery prerequisite after 45.543 seconds. Neither public role ran. The inner
  failure frame was discarded; reviewed fixed-stage attribution is now integrated.
  A local mixed-source diagnostic instead timed out waiting for the initial
  invitation after 360 seconds, which does not establish the CI cause.
- Successor CI `43575546186` at `9833142` passed verification and failed Windows
  recovery at `receiver_reopen/unavailable`. The real cleanup registry rejected
  the required second answerer lifetime. Correction `3322776` reserves cleanup
  before launch and permits both second lifetimes within the four-slot bound.
  Actual installed recovery still requires a new passing run.
- Android custody/initialize changes at `8b0befd` passed 7,041 local connection
  tests with two platform skips and strict typing. Follow-ups through `8b1c119`
  passed 106 affected tests with one platform skip. The native EOF cause is still
  unproven. The actual CallDialog harness through `b549f90` is implemented and
  reviewed, with local lifecycle, browser and DOM evidence. Its installed audio
  and messaging execution remains pending. R7 roster, Windows pins, generic
  authorization and private codecs are integrated through `0843761`; coherent
  Python/Node admission wiring and installed negative cases remain in progress.
- Core/API, SDK packages, typed UI migration and native transport implementations
  already exist. Do not restart them from scratch.
- All ten nonnative jobs passed in historical full run `b8e3e20`. Both native peers
  completed the six direct/TURN/impaired path cases.
- Full native qualification failed at the first Android cold restart. Initialization
  lost its socket; rollback then observed ADB offline. Zero cold receipt cycles
  completed. The precise cause remains unknown.
- Windows separately failed artifact-inventory transport at the partner barrier.
- Console-observation candidate `82c3364` passed 6,640 required local tests,
  exact-source SDK staging, configured types and independent review. Full run
  [43529724766](https://github.com/ahouchens/mesh-chat/actions/runs/43529724766) is
  closed failed after native Android exited before boot. Exact JVM83 and Android
  component evidence passed. No restart repair is established.
  Earlier intermittent failures remain in the ledger.
- Focused boot run `43535708090` booted the baseline launcher. The observed
  launcher never started because ADB still listed the exited baseline emulator.
  Diagnostic cleanup now waits for that owned transport to disappear before
  releasing its AVD. Successor `43536862480` launched both cases and isolated a
  stdio conflict in the instrumented launcher. Candidate `563b91a` removes the
  extra kernel console while retaining filtered Android logs; 2,072 harness
  checks pass. Run `43537710895` then booted both variants and retired them cleanly.
  Same-source run `43538167917` built APKs but failed source binding before any
  reopen attempt. The Gradle wrapper executable bit is corrected and build
  checkpoints now expose remaining file/mode changes. The shared emulator owner
  also retains custody until its ADB transport disappears (2,078 tests pass).
  Run `43540388648` at `6819084` passed all three packaged crash/reopen attempts,
  preserving identity/profile handle and verifying retirement. All five build
  source checkpoints were clean. Next reproduce the six-path prefix and first
  paired cold cycle; this Android-only result has no paired receipt evidence.
  The manual paired diagnostic is now implemented and independently reviewed,
  with separate reports, strict paired evidence and explicit qualification exclusion.
  The original cold-restart and Windows inventory failures remain open.
- Invitation dismissal now retains its operation identity across uncertain replies
  within the current profile lifetime. Channel creation now also reuses its
  submitted action identity after an uncertain reply (197 UI tests and types pass).
  Verified-contact invitation retries now retain their action identity too
  (201 App tests and types pass).
  Reducer event classification adds eight cases; signed collision/replay adds a
  component interleaving trace (65 related tests pass). Packaged acceptance remains open.
- Full native acceptance, shared-owner promotion and the complete refactor are
  still open. Test count growth is not a measure of roadmap completion.

## Active batch ownership

Availability was refreshed with the existing chats on November 13; the earlier
quota notes no longer describe the returned live status. Each worker preserves
its owned checkout and reports source evidence and gaps before integration.

| Owner | Roadmap batch | Exclusive file scope / concrete deliverable | Next milestone |
| --- | --- | --- | --- |
| Lead | R0/R6/R9 | Working 0.9.66 baseline identified; public pair controller, strict checker and isolated workflow integrated and reviewed. | Integrate reviewed fixes and bind platform results to the roadmap; full acceptance remains open. |
| C | R1/R6/R7 | Initialize attribution and partial-stream preservation are integrated through `f824e0e`; parked native edits remain separate. | Review installed CallDialog evidence and exact-source Windows recovery CI routing. |
| B | R3/R5/R8 | Media run `43568844257` at `d9ab09f` passed all seven installed WebView2 capture checks and app/policy cleanup. | Implement the next bounded actual CallDialog/media plus receipt scenario; preserve baseline modal semantics. |
| A | R1/R6/R8 | Exact Android stop-reader custody is integrated and independently reviewed. | Specify trusted caller admission for the unresolved same-image cross-application boundary. |
| D | R1/R4/R7/R9 | Gateway capability passed in `43572907432`; bounded recovery attribution is integrated through `8b1c119`. | Diagnose the actual Windows paired recovery failure with fixed stage labels; distinguish local invitation timeout from CI. |

R2 helper retirement remains gated. R6 preparation is assigned; R7's installed
process fixture and exact report validation passed for fresh-profile detach,
reattach and owner shutdown. Same-image Node
process attachment alone cannot prove cross-application isolation: the current host
assigns the same owner grant to each admitted client. Focused runs never close the full native or public-consumer
gates. Baseline, UI and compatibility preparation documents are integrated. The
mixed-actor trace and event-classification batch are integrated. A's repaired
Windows pair/refusal fixture passed independent review and is integrated; installed execution
requires a matching source-bound sidecar. These batches do not establish missing
physical, signed-signaling, native or public cross-platform acceptance. The user
identified 0.9.66 off main as the last working physical Windows/Android build.
Published release provenance is pinned in [the baseline reference](MESH_CORE_BASELINE_REFERENCE.md);
exact installed-device bytes and scenario coverage remain unconfirmed.

## Work register

The active batch table above controls current ownership. The responsibility column
below describes later work; it does not grant additional file ownership.

| ID / milestone | Remaining outcome | Current evidence and gap | Closure evidence | Dependency / proposed responsibility |
| --- | --- | --- | --- | --- |
| R0 — M0/M1 baseline and policy audit | Reconcile baseline platform timings, state/event classification and remaining adversarial invariants. Compare applicable behavior with the working main build. | User identifies 0.9.66; release source and published checksums are pinned. Exact device bytes, timing/classification/corpus reconciliation and installed comparisons remain open. | Each relevant invariant has a mapped test or justified environment limit; reproducible baseline reference and minimized failure traces are retained. | Can proceed independently; policy/audit owner. |
| R1 — M3/M4 native stability | Make restart, identity/authority preservation, receipts and cleanup reliable on the actual packaged Windows/Android transports. | Three Android reopens passed; a paired run completed one cold cycle before a repaired uploader rejection. Replacement failed earlier on a partial Android test-control response; its cause remains unknown. Private native evidence is not public-consumer acceptance. | Demonstrated repair, focused real-platform reproduction, required fault matrix and 100-cycle receipts/cold starts/resource accounting pass on exact artifacts; aggregate accepted. | Current critical path; one lifecycle/harness implementer and independent reviewer. |
| R2 — M2/M4 ownership and retirement | Finish isolated bootstrap-helper retirement, exact resource cleanup and shared-supervisor promotion; remove migrated legacy messaging loops. | Components and retirement design exist; production retirement/promotion is deferred. | No competing policy owner; exact handles/processes retire; replacement resources survive stale cleanup; regression/rollback coverage passes. Audit all callers before deletion. | Depends on R1 and relevant unresolved-failure disposition; host/core owner. |
| R3 — M2 application lifecycle and pairing | Complete Android onboarding/approval/carrier transfer, manual workspace pairing, participant connectivity, profile create/select/unlock/lock and native credential recovery. | Typed operations and many component cases exist; complete application paths and platform parity remain partial. | Packaged supported flows exercise current authority, restart, cancellation, stop/lock/revocation and foreground/background transitions; transferred carriers retain correct ownership. | Contract/UI preparation may proceed now; lifecycle integration depends on R1/R2 where shared code overlaps; UI + host owners. |
| R4 — M3/M4 faults and bounded operation | Reconcile the complete impaired fault matrix, queue saturation, cancellation/disposal parity, timing budgets and soak evidence. | Path scenarios now complete in the latest run, but full cold/soak acceptance is absent and older acceptance rows lag or remain partial. | Exact requirements in SC04–SC07, SC10–SC12, SC16 and §9 pass with real traffic, declared impairment, counted negative controls and resource bounds. | Overlaps R1; harness owner plus policy reviewer. |
| R5 — M2/M5 UI/media coexistence | Finish remaining transitional UI policy/bridge and private pending-action recovery integration; prove calls and messaging coexist. | Installed Windows capture preflight passed seven real WebView2 checks in `43568844257` at `d9ab09f`. Actual CallDialog plus packaged WebView2/Android messaging coexistence remains unqualified. | Actual available CI/emulated media and messaging paths preserve receipts across call start/end/failure, dialog closure, navigation and reconnect. No caller loses resources owned by another operation. Remove only superseded messaging code. | Exercise actual calls with inbound-during and two-way before/after receipts; preserve the modal behavior also present in 0.9.66. Risky cleanup follows R2/R3; UI/media owner. |
| R6 — M5 independent public consumers | Complete distribution-only Windows–Android pairing, messages, authenticated receipts, restart, partition and authority recovery using public SDK/API packages. | Installed public roles and strict aggregate passed fresh pairing and one delivered message each way in `43564598454` at `0685cfb`. Owner-restart flow and routing have 390 affected test passes; `43567293402` failed its Android prerequisite at an ADB disconnect before instrumentation, so both restart roles were skipped. Combined SC21 remains open. | Independent apps built outside the source checkout from staged distribution artifacts complete SC21; no private imports, test-only controls or direct private native calls substitute for public behavior. | Execute owner restart with continuous Android; then partition and authority recovery; SDK/consumer owner. |
| R7 — M5 isolation and durable recovery | Complete packaged multi-client/caller isolation, detach/reattach, owner shutdown, pending-work recovery and event resynchronization. | Installed Windows detach, reattach and owner shutdown passed at `ebcfa38`; distinct executable-path admission passed in `43568841923` at `d9ab09f`. Full-run Windows job `132410157418` in `43581311705` at `a9f10b3` passed same-image paired consumer recovery on exact validated artifacts: application-side discarded enqueue reply, independently observed pending commit, same-key original handle after trusted owner reopen, changed-payload refusal, receiver reopen, one authenticated later delivery with single inbound/outbound records, four clean owner exits, two helper exits, EFS and cleanup. This is a Windows subcase; same-image cross-application caller isolation, installed private helper admission, event resynchronization, UI detach and cross-platform/native completion remain open. | Required SC22–SC26 / INV21–INV24 scenarios prove caller boundaries, stable idempotency, resnapshot/replay behavior and exact resource ownership on installed hosts. | Continue installed caller isolation, private helper and event-cursor cases; helper lifecycle depends on R2. SDK + host owners. |
| R8 — M3/M5 compatibility and distribution | Declare candidate runtime/SDK/API/IPC/wire/package pairs, exclusions and bounded upgrade/data windows; qualify exact installed pairs. | Experimental Python/TypeScript/Kotlin packages, staged AAR/APKs and source-pinned upgrade fixtures exist. Supported-pair coverage is incomplete. | Baseline wire compatibility, incompatible-version refusal, install/upgrade/data preservation, storage ownership and export/uninstall behavior are documented and tested as required; redistribution obligations accounted for. | Inventory/fixtures can proceed now; final pairs require integrated runtime; packaging/SDK owner. Publication is separately deferred. |
| R9 — M3 CI and final acceptance | Add focused native diagnosis and justified dependency-aware suite selection; reconcile all acceptance rows and final architecture/docs. | Conservative broad CI selection exists; repeated diagnostic full runs are costly. Some historical table entries need reconciliation. | Focused runs cannot falsely satisfy full gates; relevant changes select required suites; INV01–INV26 and SC01–SC26 map to exact evidence or explicit deferrals; final available automated acceptance passes. | Focused restart job is immediate; broader selection and final reconciliation can proceed independently; CI owner + lead. |

Do not mark a whole row complete because one component or one operating system
passes. Record source, evidence level and the remaining subcase. Do not infer the
remaining effort from the number of rows or unchecked historical bullets.

## Required details that must not disappear during debugging

### Runtime and messaging

- Sole connection lifecycle owner; pure transitions and bounded external effects.
- Current epoch/attempt/resource correlation, exact disposal and stale completion
  rejection, including native creation and replacement races.
- Current consent/authority before effects; reconnect never grants trust.
- Durable outbox and stable logical IDs; authenticated application receipts, not
  transport acknowledgments, establish delivery.
- Profile and runtime ownership, foreground/background facts, stop/lock/revocation
  and user-visible recovery through supported host/API paths.
- Retire transitional messaging policy only after parity and rollback requirements
  are met. Keep unrelated Direct/QUIC recovery and audio/video behavior intact.

### Qualification

- Spec §9.6 separates nominal bridge repair within 20 seconds, recovery within
  240 seconds after a 30-second partition under the declared 150 ms RTT profile,
  and application receipts within 30 seconds after messaging readiness.
- The 100-iteration gate includes both roles, actual messages/receipts, periodic
  cold starts, no duplicate visible logical messages and quiescent resource
  accounting. The separate fault matrix is still required.
- Retain loss/delay/partition, permitted signaling outage, carrier failure,
  saturation, cancellation and authority-change coverage. A successful handshake
  or a native Direct test is not enough to close these requirements.
- Media tests using substitutes do not prove actual packaged media coexistence.
  Public-consumer tests cannot be replaced by private native harness operations.
- Explain intermittent failures or retain a narrowly scoped unresolved item;
  an unchanged rerun passing is not a demonstrated repair.

### Reusable Core

- Thin public SDKs, caller-derived grants and private host facts remain separate.
- Supported staged packages must work outside the repository, including Kotlin
  packaging and independent Android Binder consumers.
- Complete multi-client lifetime, separate caller/process isolation, replay gaps,
  idempotency recovery and compatibility/data-preservation evidence.
- Verify actual UI call sites and runtime behavior; deleting wrapper names alone
  does not prove architectural migration.

## Sequencing and use of workers

1. Finish R1's focused restart diagnosis and repair without stacking unrelated
   lifecycle changes. A focused CI reproduction may be necessary; local simulation
   cannot replace the real platform.
2. In parallel, assign available workers nonoverlapping slices of R0, R5–R9 that
   do not depend on the unstable lifecycle implementation. Review the exact
   interfaces and files first. Worker capacity must be checked, not assumed.
3. After accepted full native evidence and relevant failure disposition, implement
   R2 retirement/promotion and complete R3 lifecycle flows in reviewed batches.
4. Complete combined public consumers, compatibility and media coexistence, then
   rerun the affected integrated qualification and reconcile the whole register.

Every worker assignment must name an R ID, linked specification IDs, a concrete
deliverable, file ownership, dependencies and evidence required to close it.
Use coherent batches; do not create conflicts by assigning several workers to the
same harness or lifecycle files. Keep independent work on owned branches.

## Deferred work and honest completion language

| Item | Reason / treatment |
| --- | --- |
| Release tag, public SDK/CLI publication and published supported-pair matrix | User instructed no release/publication. Prepare and validate staged artifacts and candidate compatibility documentation; do not publish or claim release support. |
| Physical Windows/Android checklist | No devices/physical network available. Preserve Wi-Fi/cellular, Doze/screen-off, real-device media and process-death checks as unavailable; do not call emulator results physical evidence. |

These deferrals do not excuse missing automated SDK, upgrade, lifecycle or
cross-platform tests. The specification's literal full/release definition of done
includes requirements outside this environment. Report "authorized implementation
and available automated qualification complete, with listed deferrals" only when
that narrower statement is true; do not mark all M0–M5/specification requirements
complete while physical/publication requirements remain open.

## Maintenance rule

For each integrated batch, update only the affected R rows and a short current
checkpoint. Include owner, source/run, demonstrated outcome and remaining gap.
Keep full chronological failure reports in the qualification ledger. At the end
of every diagnostic batch, explicitly state which roadmap item it unblocks and
which implementation batch comes next. Review the complete register at each
milestone and before final acceptance so CI repair does not become the project.

## Earlier integration checkpoint — November 13, 2026

Source `6773e64` is pushed on the isolated diagnostic branch. Runs at `ef86e8f`
failed prerequisite verification in two diagnostic tests before either requested
scenario. The staged/worktree inventory and workflow-expression test repairs pass
146 affected tests. R1/R4 replacement `43546317181` exercises the six-path prefix
and first paired cold cycle after its same-run package producers; the normal
required qualification gate is excluded from this diagnostic route. R8 replacement
`43546319373` passed broad verification (7,990 passed, 52 skipped) and the
corrected installed Windows fixture. Its TypeScript current/old-client checks
include same-identity reopen, two clean exits and EFS storage. Native upgrade,
Python API and peer receipt evidence are outside this result.
The paired run closed failed after both peers appended their first completed cold
cycle: the Node artifact uploader rejects `cold_complete_1`, which Python allows.
D's guarded admission fix is integrated as `22d2fb6`; 291 real-uploader,
artifact/workflow/pair-checker regressions pass. Final
cleanup/result acceptance still needs a repaired run. The R6 Android
public-session fixture is integrated through `0f93b9c`:
one ordinary main-process host and installed Binder SDK span public profile
creation/query and shutdown. Exact-source and explicit disposable-emulator
admission precede device mutations; bounded I/O and a shared deadline govern the
session. Its isolated manual CI route is integrated as `deeb8f4`. Pairing/receipts, restart and
network-interruption orchestration remain the next cross-platform consumer batch.
A separate Python-owned Windows consumer and its
opt-in CI step are integrated through `849600c`, with 189 related tests passing;
actual installed execution remains pending. Caller authority is unchanged.
The reusable Android adapter is integrated through `82b8927`, with 56 related
checks passing. It preserves one session and reserves a final completion frame;
an otherwise successful context reports cleanup failure. These later commits
are not covered by the active first-platform run at `c5f4484`.
B's installed Windows WebView2 media preflight and NSIS installer runner are
integrated through `33c027b`. They bind the actual installed application and
sidecar to the same-source delivery report and manifest. Manual CI route
`c3e19b6` and timeout reporting follow-up `af6f7ef` are integrated. This first run exercises capture and peer
connection availability only; actual CallDialog plus messaging coexistence
remains open. Combined local session/media/workflow checks passed 186 tests,
with one unavailable file-symlink test skipped. Another 646 Android distribution,
qualification and matrix regressions passed; two Bash cases hit local sandbox
and long-path limits, then both passed with a short path outside the sandbox.

The preceding three packaged Android reopens passed at `6819084`; the historical
six-path cold failure and Windows artifact-inventory failure remain unresolved.
Invitation dismissal, channel creation and verified-contact invitation retry
repairs are integrated. R2 remains gated on full native acceptance and failure
disposition. Exact run outcomes, artifact hashes and component test evidence are
in the ledger. Baseline provenance, full automated gaps and physical/publication
deferrals remain explicit.

## Current integration checkpoint — source 4565ce1

The user-identified 0.9.66 baseline now has a pinned release commit, tree,
published package checksums and successful release pipeline. This closes the
unknown-version question for R0; it does not establish exact device bytes or
complete historical scenario coverage.

Android public-session run `43549708208` passed at `c5f4484`, including the six
public fixture checks and cleanup. Windows run `43551698115` at `ceb84c5` passed
broad verification, the installed current/old TypeScript fixture and the
Python-owned public SDK fixture. The latter exercises profile creation, keyed
replay/rejection and same-identity reopen with clean exits and protected storage;
it does not prove peer traffic.

That Windows run's separate media job failed before capture because installed
bytes differed from the expected build. It did not record which binary differed.
Observed app/sidecar size and digest reporting is integrated; replacement run
`43554916988` at `c808769` passed verification and Windows host checks but failed
media installation again. The sidecar matches exactly; the installed desktop app
has the expected 8,690,688 bytes but a different digest. Packaging/staging cause
is under investigation. R5's next milestone is a diagnosed and repaired installed
capture preflight, followed by actual CallDialog plus messaging.

Native replacement `43551695082` at `ceb84c5` passed its producers but failed in
impaired receipts before any cold restart. Android read one byte of a four-byte
test-control reply header before EOF; Windows later hit its receipt deadline.
The available process snapshots do not identify why the control stream closed.
D is adding a bounded test-harness observer, with C reviewing. This continues
R1 fault diagnosis; it establishes no WebRTC defect and does not justify changing
WebRTC. R2 promotion/retirement remains gated.

The installed public fresh-pair implementation is integrated through `4565ce1`.
Its separate sealed setup transport, public flow, strict paired checker, bounded
Action and isolated workflow passed 301 focused tests with no skips. Independent
review found no remaining blocker. First platform run
[43556580958](https://github.com/ahouchens/mesh-chat/actions/runs/43556580958)
is active at source `4565ce1c7c265fa56acdc3990036cedf2277deeb`, tree
`dac53090fbfdcbc0a56f8fb1911c844332d38c1a`. It tests fresh pairing and two-way
delivered messages only. After that result, R6 proceeds to owner reopen and
controlled network interruption, as described below. Full native, SC21,
media coexistence and physical acceptance remain open.

## Independent public-consumer execution and next extensions

Follow-up source `92e50bb11b72e5fb86c379167b79bbfefa6fe60f`, tree
`2bba9680c95d490d23a46794487cac8e91e4c8a8`, includes the reviewed native observer,
Windows same-data reopen adapter and Windows packaging repair. Integrated checks
passed 1,382 native observer/peer/controller tests, 59 public adapter/flow tests,
and 38 desktop release/media tests. The packaging repair disables Tauri's
per-bundle executable patch on Windows, preserving the exact installed-byte gate;
the current app has no updater integration. Native diagnostic
[43557683098](https://github.com/ahouchens/mesh-chat/actions/runs/43557683098) and
media replacement [43557685270](https://github.com/ahouchens/mesh-chat/actions/runs/43557685270)
are active at that source. The earlier public fresh-pair run retains its own
`4565ce1` source. None of these pending runs establishes a pass.

The first combined R6 case uses the ordinary installed Windows app-owned host
and the independent Android main-process host through their public SDKs. A
separate controller exchanges bounded, sealed setup/control metadata bound to
one source, run and attempt; product pairing and messages use the normal Core
transport. Keep this namespace and producer allowlist separate from private
native-peer diagnostics.

Create two fresh identities, request relay-only operation with explicit broker
consent, pair with explicit invitation/approval decisions, and require public
messaging readiness. Send one keyed message in each direction. Both sender
delivery state and receiver message records must agree, with exactly one inbound
and outbound record per message. Finish and confirm each actual owner exits.
This first case establishes pairing/receipt evidence only.

After that baseline, reopen the Windows owner on the same protected data and
check identity, contact, keyed-message state and a new receipt. A later controlled
network interruption uses an emulator OS rule targeted to the app UID, with
rule/counter evidence and verified rollback, while retaining the localhost ADB
control channel. Prove delivery is withheld under the rule and resumes exactly
once afterward. No WebRTC fork is needed. Android cold credential-unlock behavior
remains a separate case requiring the real OS credential flow.
