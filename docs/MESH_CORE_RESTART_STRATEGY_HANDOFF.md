# Mesh Core: focused restart investigation and return to the refactoring roadmap

Copy this document into the integration-lead chat or a new coordinating session.
This is an execution handoff, not evidence that the work below has been completed.
Prepared November 13, 2026. Refresh all live state before acting.

## Objective

Continue the Mesh Core refactor to completion within the authorized environment.
First resolve the Android native cold-restart blocker through a focused,
repeatable investigation. Then resume the remaining implementation work. Do not
let diagnostic work replace the long-term refactoring objective.

Keep the separate [remaining-work roadmap](MESH_CORE_REFACTOR_REMAINING.md)
current. It is the compact work register; the original specification, roadmap,
acceptance reconciliation and qualification ledger remain the detailed sources.
Passing native CI is an important milestone, not completion of M2–M5.

Use the Uncle Bob skill at
`C:/Users/webte/.codex/skills/uncle-bob/SKILL.md` and applicable `AGENTS.md` files.
Keep production policy, platform adapters and test orchestration separate. Test
behavior and ownership boundaries; avoid building new abstractions solely to
support one diagnostic field.

## Workspace and coordination

- Repository: `https://github.com/ahouchens/mesh-chat`.
- Long-lived integration target: `codex/mesh-chat-core-refactor`.
- Existing lead workspace:
  `C:/Users/webte/.codex/worktrees/adc9/Mesh P2P connected chat`.
- Existing lead branch: `codex/mesh-core-integration-lead`.
- Existing lead chat: `01a1c070-57f9-7df0-b5f8-fbd96eab1608`.
- Coordination files:
  `C:/Users/webte/Documents/ChatGPT/Mesh P2P connected chat/.test-tmp/mesh-core-parallel-2026-11-09/`.
- These two handoff documents were prepared in a separate review workspace:
  `C:/Users/webte/.codex/worktrees/mesh-core-refactor-integration/Mesh P2P connected chat/docs/`.
  That checkout was detached at historical `435b497`; it is NOT the implementation
  baseline to resume from. Import only these documents into the active branch
  through the lead's normal review/integration process.

Inspect worktree ownership, branch tips, uncommitted changes and current worker
reports before editing. Fetch current remote state in an owned checkout; do not
reset, clean, stash, switch or overwrite another session's worktree. If the old
lead is still working, coordinate with it instead of starting a competing lead.
Some top-level fields in `integration-plan.json` are stale: compare source/run IDs,
recent candidate records, live GitHub state and the newest coordination notes.

Read, in this order:

1. `docs/MESH_CORE_REFACTOR_REMAINING.md` and this handoff.
2. `docs/Mesh_Chat_Core_Integration_Coordination.md` (newest checkpoint first).
3. `docs/Mesh_Chat_Connection_Runtime_Spec.md`, especially §§9–13.
4. `docs/Mesh_Chat_Connection_Runtime_Acceptance.md`, including every INV/SC row.
5. `docs/Mesh_Chat_Connection_Runtime_Roadmap.md` and
   `docs/Mesh_Chat_Connection_Qualification_Ledger.md`.
6. `docs/NATIVE_WINDOWS_WEBRTC_HANDOFF.md` and `docs/architecture/mesh-chat-core.png`.

## Constraints that persist

- No release, publication, tag, main merge or force push. Normal feature-branch
  integration and authorized CI work may continue.
- Use emulation and GitHub CI. Physical-device acceptance is unavailable; record
  it separately and never relabel emulator evidence as physical validation.
- Preserve Tauri/WebView2 UI and existing audio/video calls. Native messaging
  replaces only the messaging transport dependency. Do not remove shared media,
  signaling, permissions or packaging needed by calls.
- Keep the pinned WebRTC dependency. The unique-socket gate was an extra harness
  assumption; controlled-network testing replaced that approach. Do not revive
  the C++ fork/custom AAR merely to make fault injection convenient.
- Preserve required deadlines, authenticated receipts, authority checks, resource
  accounting and failed-run evidence. Do not turn failures into skips or add
  blanket retries to obtain a green run.
- The last physically verified product was a build from `main`. Identify its
  exact historical commit/artifact from available evidence. Do not substitute
  today's main or a refactoring branch. Ask the user only if it cannot be found;
  that lookup need not block native-only investigation.

## Evidence checkpoint to refresh

Full run [43520421850](https://github.com/ahouchens/mesh-chat/actions/runs/43520421850)
tested `b8e3e208efab1f74544d9dd3c4a74b53cb283b4a`:

- Ten jobs passed; both native peers and the aggregate failed. Two optional
  diagnostic jobs were skipped. Both complete Direct suites passed.
- Both native peers completed all six direct/TURN/impaired path cases.
- Android's first cold restart lost its initialization socket before response
  bytes (`peer_closed`). Rollback subsequently reported ADB `device_offline`.
- The running instrumentation host process was an ADB client, not proof of a live
  Android app. A running emulator host process was not proof of guest health.
- Windows completed its restart/identity checks, then failed an artifact-inventory
  transport request at the partner barrier. Do not silently attribute this
  independent error to the Android cause.
- Zero cold receipt cycles completed; the native 100-cycle gate did not pass.

Current integration checkpoint: `82c336423d6dae4d9d19c1923824cf7db0bed0b0`
passed all 6,640 required local cases with zero failures/skips, exact-source SDK
staging, configured type checks and independent source review. Its bounded console
observer is diagnostic instrumentation, not a demonstrated restart repair.
Full run [43529724766](https://github.com/ahouchens/mesh-chat/actions/runs/43529724766)
is already in progress. Preserve and finish that useful run; subsequent restart
diagnostic iterations follow the focused strategy below. Earlier failed/interrupted
local candidates remain retained evidence. The ledger holds detailed history.

## Execution strategy

### 1. Establish one useful reproduction

Make the next diagnostic target: reproduce Android restart/initialize/receipt
failure in the same packaged host and emulator environment, while distinguishing
the original failure from cleanup failures.

Prefer a focused GitHub diagnostic job using the existing native runner's code,
runner image, emulator configuration, packaged artifacts and lifecycle methods.
Reuse verified same-source artifacts where they still exist; otherwise build the
necessary packages. Record hashes and configuration. Do not silently mix old
binaries with new code. Explicitly mixed-origin experiments may diagnose a
problem, but cannot qualify a new source revision.

Start with the smallest credible sequence: prepare the host, establish readiness,
restart, verify identity/authority, exchange a durable message and authenticated
receipt, and check exact cleanup. Keep the second peer when needed for that
sequence. An Android-only startup probe is useful but is not equivalent to the
cross-platform receipt test.

If this does not reproduce the failure, include the preceding direct/TURN/impaired
setup, incrementally or as the full prefix. Do not conclude that the failure is
fixed because a clean-start shortcut passes. Preserve a reproduction that actually
exercises the failing conditions. This focused job is diagnostic only and must
not satisfy the full acceptance gate.

### 2. Capture enough evidence in one pass

Use the existing bounded console observer where suitable. Preserve the first
startup error before rollback; retain cleanup errors separately. Correlate host
phases, initialization EOF, guest/system signatures, instrumentation status and
ADB state without assuming one causes another. Keep exact artifact/configuration
bindings. Retain only approved bounded, sanitized diagnostics; no credentials,
message bodies or raw sensitive logs in public artifacts.

Do not let diagnostic readers block startup or leak processes. A system-wide
signature is a clue, not proof that the application caused it. Absence of a
signature does not rule out a failure. Keep the Windows rendezvous issue visible
as a separate hypothesis.

### 3. Diagnose and repair a demonstrated cause

Maintain a short hypothesis table: supporting observation, contrary observation,
next discriminating experiment and result. Distinguish product lifecycle defects,
test orchestration defects and runner/guest failures. Reproduce against the same
source before changing behavior where practical. Compare applicable existing user
flows against the verified historical main build; new headless-only behavior
requires its own tests.

Make the smallest coherent repair and add a meaningful regression. A harness
change must preserve the requirement it measures. A product fix must remain in
the owning layer. Avoid repeated full runs with only one more error label when
the necessary evidence can be gathered in one bounded diagnostic pass.

### 4. Validate in stages

1. Run focused local regression, relevant types/package checks and source review.
2. Run the focused native reproduction on the real CI platform. Declare the
   repetition count before execution; preserve all results, not just a passing
   retry. Select repetitions based on the observed failure, not an invented SLA.
3. Once the repair survives that reproduction, run the unchanged required native
   fault and 100-iteration acceptance workloads and the required aggregate suites
   against the integrated candidate.
4. Independently verify same-source artifact manifests, required cases, receipts,
   timings and quiescent resource accounting. Record remaining uncertainty.

The full qualification gate remains mandatory for acceptance and migration
promotion. It is not the default debugger for every small diagnostic change.
Follow spec §9.5/§10 selection rules: expensive repetitions need not run for every
unrelated UI edit. No selection change may hide a relevant failure.

### 5. Resume the refactor deliberately

After native/aggregate acceptance and disposition of relevant unresolved failures,
start roadmap R2 helper retirement/shared-owner promotion. Keep public-consumer
acceptance (R6) separate from private native test-harness success. Assign the
remaining roadmap packages to independent owners with explicit file boundaries.

Work that does not depend on unstable lifecycle code may proceed now in isolated
branches: compatibility inventory/fixtures, baseline comparison, consumer scenario
preparation, documentation reconciliation, and review of UI/media coverage.
Do not merge overlapping lifecycle changes while debugging the reproduction.

Verify worker capacity before assigning work. The last coordination record said
Worker C was quota-limited until November 19; refresh rather than assuming all
four workers are available. Use one implementation owner and one reviewer for the
restart path. Other available workers should advance independent roadmap items
instead of all reviewing the same diagnostic field.

## Reporting and completion

At each integrated batch, update the compact remaining-work roadmap and existing
acceptance/ledger records. Give the user a short report containing:

- Roadmap ID advanced, user-visible outcome, and what remains.
- Product fix versus harness fix versus diagnostics-only change.
- Exact local/focused-CI/full-CI evidence and its limits.
- Current blocker, owner and next decision/experiment.
- Independent work continuing in parallel and the next post-blocker milestone.

Do not lead with test counts or duplicate the complete CI history across every
document. Keep the chronological evidence in the ledger and the compact roadmap
focused on present work. Reconcile all INV01–INV26 and SC01–SC26 before declaring
the authorized automated scope complete. Leave release/publication and physical
validation explicitly deferred, not falsely checked off.

## Integration update — November 13, 2026

The 82c3364 run has verified Android component and exact JVM83 evidence. Its
native Android job failed before boot with `emulator_exited_during_boot`, before
any restart or paired path execution. The observer reached EOF with no recognized
signatures. This is a separate startup failure, not an explanation of b8e3e20's
cold initialize EOF. Remaining jobs are still being preserved; full qualification
is not accepted. Root and A are investigating startup while D's focused runner
undergoes review for interruption-safe result retention and exact cleanup.

Reviewed A/B/C documentation and C's competing-actor test are integrated locally
through 694e390. Root reran the supervisor/phase selection: 323 passed, zero skips.
SC02 is corrected to partial because actual two-peer signed-signaling interleavings
remain untested. R0 baseline provenance is still unresolved. B now owns the narrow
App.tsx/App.test.tsx invitation-dismissal retry flow; A owns the installed Windows
candidate-pair fixture; C reviews D's R9 diagnostic. R2 retirement remains gated.
These independent batches do not inherit qualification from the 82c3364 run.
