# Mesh Core refactor: remaining work and completion map

Prepared November 13, 2026 from the active integration lead's records, most recent
completed qualification `b8e3e20` / run `43520421850`, and integrated diagnostic candidate
`82c3364`. Its full run `43529724766` closed with a native Android boot failure. This is a compact planning register, not new qualification evidence.
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
| Lead, D reviewing | R1 | Boot repair and three packaged reopens passed; all build checkpoints clean. | Reproduce the original six-path prefix and first paired cold restart, then unchanged full native acceptance. |
| C | R0/R1 preparation | Mixed-actor and event-classification tests integrated; physical baseline provenance remains unresolved. | Review a diagnostic reuse plan for the six-path prefix and first paired cold cycle. |
| B | R3/R5 | Invitation dismissal, channel creation and verified-contact invitation retry repairs integrated. | Packaged lifecycle, invitation delivery and UI/media coexistence remain open. |
| A | R8/R1 review | Repaired candidate fixture and build-mode review integrated. | Review results of exact-source installed Windows execution. |
| D | R9/R8 | Paired diagnostic workflow integrated with manual admission and isolated concurrency. Windows `43539960943` failed in its fixture; the snapshot-field repair is integrated. | Execute the repaired Windows fixture and paired restart diagnostic on one new source. |

R2 helper retirement remains gated. R6/R7 implementation is not assigned by these
preparation batches. Focused runs never close the full native or public-consumer
gates. Baseline, UI and compatibility preparation documents are integrated. The
mixed-actor trace and event-classification batch are integrated. A's repaired
Windows pair/refusal fixture passed independent review and is integrated; installed execution
requires a matching source-bound sidecar. These batches do not establish missing
physical, signed-signaling, native or public cross-platform acceptance. Baseline
clarification remains pending.

## Work register

The active batch table above controls current ownership. The responsibility column
below describes later work; it does not grant additional file ownership.

| ID / milestone | Remaining outcome | Current evidence and gap | Closure evidence | Dependency / proposed responsibility |
| --- | --- | --- | --- | --- |
| R0 — M0/M1 baseline and policy audit | Reconcile baseline platform timings, state/event classification and remaining adversarial invariants. Identify the physically verified main build for regression comparisons. | Extensive deterministic policy tests exist; the roadmap still calls out timing/classification/corpus reconciliation. Exact verified main artifact is not identified in this handoff. | Each relevant invariant has a mapped test or justified environment limit; reproducible baseline reference and minimized failure traces are retained. | Can proceed independently; policy/audit owner. |
| R1 — M3/M4 native stability | Make restart, identity/authority preservation, receipts and cleanup reliable on the actual packaged Windows/Android transports. | Six path cases complete; first Android cold restart fails. Private native evidence is not public-consumer acceptance. | Demonstrated repair, focused real-platform reproduction, required fault matrix and 100-cycle receipts/cold starts/resource accounting pass on exact artifacts; aggregate accepted. | Current critical path; one lifecycle/harness implementer and independent reviewer. |
| R2 — M2/M4 ownership and retirement | Finish isolated bootstrap-helper retirement, exact resource cleanup and shared-supervisor promotion; remove migrated legacy messaging loops. | Components and retirement design exist; production retirement/promotion is deferred. | No competing policy owner; exact handles/processes retire; replacement resources survive stale cleanup; regression/rollback coverage passes. Audit all callers before deletion. | Depends on R1 and relevant unresolved-failure disposition; host/core owner. |
| R3 — M2 application lifecycle and pairing | Complete Android onboarding/approval/carrier transfer, manual workspace pairing, participant connectivity, profile create/select/unlock/lock and native credential recovery. | Typed operations and many component cases exist; complete application paths and platform parity remain partial. | Packaged supported flows exercise current authority, restart, cancellation, stop/lock/revocation and foreground/background transitions; transferred carriers retain correct ownership. | Contract/UI preparation may proceed now; lifecycle integration depends on R1/R2 where shared code overlaps; UI + host owners. |
| R4 — M3/M4 faults and bounded operation | Reconcile the complete impaired fault matrix, queue saturation, cancellation/disposal parity, timing budgets and soak evidence. | Path scenarios now complete in the latest run, but full cold/soak acceptance is absent and older acceptance rows lag or remain partial. | Exact requirements in SC04–SC07, SC10–SC12, SC16 and §9 pass with real traffic, declared impairment, counted negative controls and resource bounds. | Overlaps R1; harness owner plus policy reviewer. |
| R5 — M2/M5 UI/media coexistence | Finish remaining transitional UI policy/bridge and private pending-action recovery integration; prove calls and messaging coexist. | Large typed UI migration and renderer media tests exist; real packaged WebView2/Android media coexistence remains unqualified. | Actual available CI/emulated media and messaging paths preserve receipts across call start/end/failure, dialog closure, navigation and reconnect. No caller loses resources owned by another operation. Remove only superseded messaging code. | Audit and test preparation can proceed now; risky cleanup follows R2/R3; UI/media owner. |
| R6 — M5 independent public consumers | Complete distribution-only Windows–Android pairing, messages, authenticated receipts, restart, partition and authority recovery using public SDK/API packages. | Windows SDK pairing/receipts and Android Binder/app-owned lifecycle components exist. Combined SC21 remains open. | Independent apps built outside the source checkout from staged distribution artifacts complete SC21; no private imports, test-only controls or direct private native calls substitute for public behavior. | Prepare consumers now; final transport evidence follows R1 and needed lifecycle work; SDK/consumer owner. |
| R7 — M5 isolation and durable recovery | Complete packaged multi-client/caller isolation, detach/reattach, owner shutdown, pending-work recovery and event resynchronization. | Same-application Windows sessions and Android detach/rebind have evidence; separate consumer-process/caller isolation and exact helper retirement remain partial. | Required SC22–SC26 / INV21–INV24 scenarios prove caller boundaries, stable idempotency, resnapshot/replay behavior and exact resource ownership on installed hosts. | Independent boundary cases can proceed now; helper lifecycle depends on R2; SDK + host owners. |
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

## Integration update — November 13, 2026

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
D monitors the paired run, whose same-run producers passed and both native roles
started. The R6 Android public-session fixture is integrated through `0f93b9c`:
one ordinary main-process host and installed Binder SDK span public profile
creation/query and shutdown. Exact-source and explicit disposable-emulator
admission precede device mutations; bounded I/O and a shared deadline govern the
session. Its isolated manual CI route is integrated as `deeb8f4`. Pairing/receipts, restart and
network-interruption orchestration remain the next cross-platform consumer batch.
A separate Python-owned Windows consumer and its
opt-in CI step are integrated through `849600c`, with 189 related tests passing;
actual installed execution remains pending. Caller authority is unchanged.
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
