# UI / Core boundary qualification

This suite replaces only Tauri `invoke` and OS event subscriptions. It renders
the production `App` and executes the production `api.ts` serializers against a
separate Python process running `FramedSession`, `CoreSession`, domain services
and a fresh encrypted test vault. Network startup is disabled. It neither maps
typed operations into legacy command mocks nor claims native transport evidence.
The mandatory rendered onboarding case uses the explicit empty-vault host mode:
neither its profile nor its identity is seeded. The form submits through the real
serializer and private bootstrap port; a lost committed response is resolved by
the production snapshot path, with exactly one identity and one creation request.

The retained request vectors separately exercise every advertised component
operation through JSON serialization, schema validation, the production parser
and permission admission. The permission-denied session must reject before any
domain effect. Unsupported future operations are not advertised as implemented.
The `native.command` vector uses the separate private-host schema and is rejected
by the public schema. Only the explicit trusted UI fixture bootstrap attaches the
private native port; ordinary public owner grants do not acquire it. The separate
`bootstrap.preview` vector uses the private-bootstrap schema and is also rejected
by the public schema.

After committing source, run the exact-source fast gate:

```text
python scripts/check_core_ui_boundary.py --expected-source <HEAD SHA> --node <Node 20+ executable>
```

It rejects dirty or mismatched source, missing runtimes, empty results, skipped
tests, failing tests and incomplete execution. Python uses the existing
collection/run inventory binding. JSON evidence records the source commit/tree,
JUnit hashes, runtime version and wall time under `dist/reports/`. CI executes it
immediately after dependency installation, before distribution package checks.
The full qualification matrix remains a separate required integration gate.

The final qualification workflow downloads this verification artifact and the
Windows host artifact. It rechecks the boundary reports against the required
source commit/tree, retained JUnit and collection digests, run identities and
zero-failure/zero-skip execution. The uniform manifest includes separate
`core_ui_boundary_python`, `core_ui_boundary_rendered` and
`core_windows_boundary` records. Rendered execution must contain all ten named
cases, including composer remount and keyed group create/send reply-loss controls; Windows must contain
all three named cases. Python counts come from the
complete collection of the required boundary files, rather than a historical
case count. The final gate requires only the standard library.

The group send case opens a real group only after another real identity signs
its join statement and production invitation, manifest and correlated receipt
handlers finish the membership update. The fixture uses an in-process recording
transport for that setup. It does not patch member status, mock Core responses
or claim native delivery evidence. UI requests still reach the actual framed
Core and encrypted journal. Lost keyed creation/send replies must replay the
original prepared scope, payload and caller key, preserve a newer draft, and
leave one durable group/message and unchanged outbox/receipt counts. The opaque
group acceptance reference is never queried as a direct message. Full renderer
restart recovery of group action keys remains outside these two cases.

Independent authority tests pass JSON frames through the actual Core session.
Signed workspace removal must deny replay of an earlier accepted message or
read-hint change. Explicit consent administration requires both `send` and
`approve`: remote profile create/remove and propagation approve/remove,
workspace access recommendation apply/apply-by-ID, and reconnect consent.
These tests validate ordinary consumer grants, successful owner effects, and
denial of the same key after the host removes only `approve`. Workspace access
fixtures deliver a real owner-signed recommendation to a joined member;
transport is then unavailable while real consent/storage logic executes.

`noop-audit.json` records a finite audit of 92 supported keyed mutation actions
and 63 concrete adapter/helper methods at its stated source commit. It lists
documented queries separately and identifies four early-success sites covering
five actions. `test_ui_core_boundary_noop_idempotency.py` reproduces each through
framed Core requests, requiring identical retries to converge and changed
payloads to conflict. The audit records that source checkpoint; it does not
qualify later source or replace A/C's separate parent-durability work.

Wave 2 adds independent framed composer cases for pure scoped reads, opaque
update-ticket consumption including unchanged text, changed-payload rejection,
current grant/contact authority, actual vault reopen after a discarded committed
send reply, preservation of a newer draft on late replay, and real SQLite
seal/write/commit rollback. Two rendered App cases cross renderer remount and
vault reopen. They intentionally fail at missing composer capabilities until
the production port and UI integration land; no fallback, skipped feature, or
mocked composer result qualifies them.

Native packaged control/lifecycle checks separately bind the clean source/tree,
sidecar build fingerprint, strict build manifest and tested binary hash before
and after execution. Missing Windows/binary and incomplete execution fail.
The lifecycle check requires 100 actual control cycles, three cold starts and
five clean process exits. It remains control/resource-lifecycle evidence;
product pairing, Windows-Android delivery, authenticated receipts, selected
paths, impairment and media coexistence require their own actual evidence.

The required native topology workflow uses concurrent Windows and Linux KVM jobs
after both source-bound packages are available. `native_interop_rendezvous.py` and
`native_interop_artifacts.py` bound setup/control to repository, source commit,
workflow run, run attempt, workflow-owned publishing role and phase. Each runner
keeps an ephemeral X25519 private key in memory; only its public key and
HKDF/AES-GCM sealed setup/control bundles can be uploaded. Key lifetime is two
hours, each sealed phase lasts ten minutes, and each phase is single-use. The
official artifact SDK is pinned in `scripts/native-interop-artifact`; the
publisher requires the expected `GITHUB_JOB` and rejects unknown/plaintext fields
before writing an upload file. Producer job is a checked bundle declaration
under trusted workflow code; GitHub REST does not independently attest its job
of origin. REST authenticates the repository/run/source; attempt is bound in
artifact names and bodies. Downloads rehash the immutable archive against
authenticated same-run REST metadata before reading one
bounded JSON member. Repository bearer credentials are not forwarded to signed
blob URLs; transient bundles and raw SDK errors are not retained.

Artifacts carry setup/control only. Production encrypted mailbox signaling and
native transport message/authenticated-receipt delivery remain separate required
paths. Production broker/mailbox probes return only availability and advertised
transport types, which do not prove allocation or selected TURN TCP/TLS. The
preflight and crypto/artifact tests are controller component evidence until the
actual packaged peer jobs execute. GitHub supports artifact exchange while a
workflow is running; see the [official artifact toolkit](https://github.com/actions/toolkit/blob/main/packages/artifact/README.md)
and [artifact REST provenance/digest fields](https://docs.github.com/en/rest/actions/artifacts).

The Node Action owns its KVM emulator for the whole controller lifetime. Both
roles rehash the exact retained producer artifacts before starting product
hosts. The trusted private pairing port delegates native offer/answer creation,
signing, mailbox polling and custody transfer to the production supervisor.
Controllers supply explicit Core contact decisions and disclosure consent.
Direct paths run with both Windows and Android initiating; TURN UDP/TCP/TLS and
impairment paths run with Windows initiating. Both platforms exchange messages
and receipts in every case. Full runs execute 100 receipt iterations with a
same-vault process restart every ten iterations. Known affected pull requests
retain an actual native quick smoke: both direct initiators, TURN UDP, five
receipt iterations and one cold restart. Manual, scheduled, release, merge-queue,
push and unknown-diff selection stays full. Each host and the final gate recompute
selection from the source and event; quick reports have a distinct evidence
level and cannot satisfy full requirements. Native allocation accounting must be complete;
unavailable disposal counts cannot stand in for zero leases. Every path retires
its exact native reservations, and the soak compares actual allocations with
its quiescent warm baseline.

The Android emulator's Linux kernel applies a selected-socket profile of 75ms
delay and 10ms jitter in each direction with 0.1% random loss. This adds 150ms
nominal RTT to the hosted-runner baseline. Reports retain actual selected-pair
RTT separately and report whether random loss was observed. Own-process socket
descriptors and actual kernel flows correlate packet counters; TCP/TLS and UDP
negative controls require counted kernel drops, no authenticated receipt during
the block, and the same queued message's receipt after restoration. Missing
kernel support, ambiguous sockets, absent RTT, stale observations, platform
substitution or incomplete evidence fail the required suite.

These controllers use private qualification authority for transport inspection.
They do not qualify section 11's independently installed public Windows
TypeScript/Android Kotlin consumer scenario, physical devices, UI media,
packaged upgrade/uninstall, or a supported release matrix. Controller and fault
unit fixtures are component evidence; only actual source-bound CI reports from
both jobs can qualify the native matrix.

For development, run `python tests/core-ui-boundary/run_python.py --source <HEAD SHA> --junit .test-tmp/boundary.xml`
or `vitest run --config tests/core-ui-boundary/vitest.config.ts` directly.
`MESH_BOUNDARY_PYTHON` selects the Python interpreter; the default is the local
`.venv` on Windows and `python` on other platforms. Tests create and remove their
own directories under `.test-tmp/core-ui-boundary/`.

The baseline at `435b497` deliberately fails the new regressions: direct sends
use a new idempotency key on retry, accepted text is restored after a failed
snapshot, and workspace requests fail at parser/session admission. The control
case verifies one queued durable direct message without a forged delivery state.

The Android counterpart is the separately owned
`TypedCoreBridgeBoundaryTest.kt`. It calls the production typed app bridge and
real Binder/dispatcher/mobile session, with private access only for isolated
fixture setup and domain inspection. Its six cases are mandatory members of the existing
artifact-bound Android qualification inventory. They require C's typed bridge
implementation and A's parser/session fixes. Mutation cases change and read back
network/call settings, then start/end an approved audio call and verify the stored
state and signed queued invite/hangup documents. These assertions qualify call
signalling, not media execution or peer receipt delivery. The embedded Python
fixture also executes through mobile Core framing in the fast Python suite.
Three additional `NativeProfileResultRegistrationTest` cases require actual
AndroidX result-registry routing for unrelated results, cancelled registrations,
replacement challenges and cancelled credential UI. Their explicit component
scope does not qualify successful OS credential confirmation. The required Core
API inventory has 13 cases; all four Android suites together require 50 cases.
The separate required Windows gate now collects nine cases: the original three
app-pipe cases and six normal app-owned host checks. The latter execute actual
DPAPI and image-authenticated pipes with explicitly unprotected test Vault
storage. They do not qualify EFS or the independently installed frozen runtime.
The distinct `windows-independent-bootstrap.json` producer runs the copied
frozen runtime and installed SDK outside the checkout in normal app-owned mode.
It requires real EFS protection, explicit fresh profile creation/key replay,
changed-payload rejection, public identity continuity after reopen and two
acknowledged clean host exits. The final matrix binds its executable/build
digests to the other tested native Windows artifacts. Missing EFS, bootstrap or
cleanup fails this gate. This is installed Windows bootstrap evidence only;
Android, pairing and SC21 receipt traffic remain separate requirements.
The three public pairing vectors use an advertised production Core actor with
real framing, vault records and signatures. The fixture admits one offer to
`offer_ready`, then revokes the caller's grants. Begin/query/cancel must return
`forbidden` without disclosing the code, mutating sealed records, allocating or
closing native resources, or publishing mailbox documents. Ordinary unbound
hosts must omit and reject all three operations. Native/mailbox boundaries are
explicit test doubles in these vector checks; they do not qualify native traffic.
The fresh-profile case starts with no profile or identity, verifies a signed
invitation through private preview without any vault write or network/event
effect, then creates only through
the keyed Core operation, rejects changed-payload key reuse and repeats after a
service/vault reopen without changing the identity. This is not OS process-death
evidence. Compilation or emulator execution
has not been claimed locally; disk-constrained native builds run in GitHub CI.

## Timing evidence

`ci-baseline-timing.json` retains step durations from the integration lead's
GitHub jobs API snapshot for run `42598859239`, at the exact baseline. The
verification job took 519 seconds, including 478 seconds in `Validate and test`;
the Windows host job took 387 seconds. These are CI workflow measurements,
excluding queue time, and do not measure the full Android/Direct matrix.

The first local boundary run took 19.20 seconds (7.63 seconds executing five
tests); the request/parser/session corpus took 3.00 seconds. These are local
Windows samples, not a prediction for CI. The new fast gate records fresh wall
time so integrated CI can quantify the change. Dependency selection narrows only
isolated boundary/test changes to their actual policy and verification consumers.
Production, Android, workflow, tooling, mixed, manual and release changes retain
the conservative full matrix. No required final evidence is removed.

## Windows application pipe

`python scripts/check_core_windows_boundary.py --expected-source <HEAD SHA>`
executes three mandatory cases through the production application sidecar pipe
host, executable-image authentication, production pipe client and serialized
Core client. They assert real settings write/readback and signed call start/end
domain effects. Its independent fresh-profile case starts an empty service,
creates only through the keyed pipe request and verifies replay/conflict and one
identity across vault reopen. The script fails when Windows is unavailable, clears stale
success, checks the complete collected case inventory and writes exact-source
JUnit/hash evidence. It runs in the Windows CI host job before native builds.
It does not claim packaged, cross-process media, or physical qualification.

## Frozen Windows runtime materials

`native_runtime_materials.py` stages installed, exact-lock dependency metadata
and available wheel notices into the PyInstaller archive. After freezing, the
required Windows job opens the actual executable's CArchive and embedded PYZ,
rehashes every staged notice, requires aiortc/aioice/PyAV code, inventories every
DLL/PYD, and requires every DLL from the installed PyAV wheel to survive staging.
The retained report binds the same source, build manifest and executable digest
as the native control/lifecycle runs. The final gate rejects missing, changed or
partial materials evidence.

The inventory preserves declared Python-package licenses and identifies native
files by their actual wheel-byte owner. It explicitly lists native files with
no matched wheel owner. A PyAV wheel notice does not establish licensing or
corresponding-source completeness for its bundled FFmpeg and codec libraries;
the report makes no redistribution/legal approval claim. Component regressions
include an actual small CArchive/PYZ fixture, not execution of the production
frozen Windows application. That archive inspection remains mandatory in CI.
