# Acceptance reconciliation: specification invariants and scenarios

Executed automated evidence for the current commit is recorded in the
[qualification ledger](Mesh_Chat_Connection_Qualification_Ledger.md);
it separates automated runs from physical and packaged limits.


This page reconciles [the specification](Mesh_Chat_Connection_Runtime_Spec.md)
with executed evidence. It is deliberately conservative: a requirement is only
marked at the level the evidence actually reaches, and physical-only acceptance
is marked unavailable rather than inferred from emulation or CI.

## Revalidation at the 2026-11-09 integration baseline

The repaired Wave 1 application/Core boundary is now accepted at `174728e`:
full workflow `42644737670` passed, and the lead independently validated its
retained source-bound reports and all seven tested Android package hashes.
Wave 2 is active. This checkpoint does not promote the historical invariant
and scenario rows below to complete; their named remaining obligations still
apply, including packaged cross-platform transport and unavailable physical
qualification.

The shared feature branch now contains `d411eb5e8a2bd72e36254011f26c4cbc992ce4a9`
(tree `830d3af24ffb5299a8d76dd48c34d069c338249f`). Its only implementation delta
is D's selected network health diagnostics: `network_present` and a fixed
`service_error` enum from existing snapshots, preserving observation subphase.
No requests, request order, deadlines or public APIs change. The lead passes
**367 focused cases**, zero skips, in 18.02s. Existing broad/Windows CI
[42720210733](https://github.com/ahouchens/mesh-chat/actions/runs/42720210733)
is running to observe frozen startup; duplicate PR run `42720186216` was canceled.
This diagnostic run is not full combined qualification.

The preceding full-qualification checkpoint is `677b6bf9e9ea0f50d4465e04cca9f79038632187`
(tree `0e2516336d33d0febd5b152a25ab9b6972f7212b`). Full manual qualification
[42716355520](https://github.com/ahouchens/mesh-chat/actions/runs/42716355520)
is running. Retained selection independently confirms all six suite families and
native workload `full`; duplicate PR run `42716363961` was canceled.

This exact source passes SDK staging, **3,554 required policy tests**, **670 Python
plus 12 rendered App/Core cases**, and **nine Windows component cases**, with
zero failures and skips. It integrates C's public AGP DSL receiver fix `595b1bf`
and D's bounded stage timing/read-count/provenance diagnostics `1f177e4`.
The independent Android build and two installed cases remain unqualified;
Windows pairing's cause remains unproven. C repairs Android generated-source
registration; A reviews frozen main-network startup offline. B/D hold source.
No release, default or scenario promotion.

Current CI independently passes all 3,554 policy cases and the 670/12 boundary;
broad verification also passes. Windows public pairing fails again, but its new
timing evidence excludes late acceptance in this run: acceptance starts at
28,701 ms and returns at 28,714 ms. The pending-request wait completes **1,945
snapshot reads** before failure at 240,072 ms; no clipping occurs and its entry
deadline flag is false. The final offerer snapshot is explicitly from that wait
and contains zero contacts. Both final pairing probes are retired, not expired.
This establishes a real post-accept observation period without the required
request; it does not establish delivery failure or retirement cause.

Android independently passes all 50 existing emulator cases, seven APK/AAR
hash bindings and 62 JVM cases. The DSL receiver repair clears the earlier cast;
configuration now rejects a Provider passed to the legacy source-set API at
`runtime-host/build.gradle.kts:33`. Its two new independent cases never build or
run. C will use the generated-source Variant API with task dependencies intact.
Linux direct transport/recovery/setup independently pass 25/10/12 cases with
zero skips; Windows direct evidence remains pending. No overall Android or
combined platform acceptance is claimed.

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

Earlier checkpoint evidence follows.

Latest public pairing integration `787b6aa` has 79 passing actor/installed-SDK
controls and 50 passing TypeScript SDK tests. Its full policy run remains failed
with nine inventory defects and 3,359 passes. Native channel disposal and
profile-bound WebRTC effects have focused component coverage; actual platform
cleanup, credential UI, independent cross-platform receipts and media retirement
remain required. The new normal Windows installed-runtime gate requires actual
EFS and frozen execution; its wiring and component tests are not that evidence.
CI `42683615511` finishes failed at the older source because both native interop
jobs fail initialization. The pipe-name repair requires a fresh full run.

The repaired combined source `5ea2949` passes all 3,379 required policy cases,
664 Python plus ten rendered-App boundary cases, and nine Windows host components,
with zero failures/skips. Full CI `42693457737` completed failed: the policy and
exact boundary artifacts independently pass, and each direct platform passes
25 fabric, ten recovery and 12 setup cases. Windows bootstrap assertion,
Android test-module compilation and one broad CSS guard failed; all three have
local repairs. These passes supersede the nine earlier local inventory failures.
Packaged, device authentication, independent cross-platform and media obligations
remain. The next group-composer batch at `02f83b8` has 275 focused producer and
installed-SDK passes, 41 UI/controller passes and 51 SDK passes, but its exact
boundary fails the missing three-operation vector inventory and one outdated
rendered group-send fixture. It is not accepted pending those repairs and the
queued-send retirement fix.

Wave 2 now has a complete local policy pass at `538ba226` (2,815 cases, no skips),
exact rendered-App/Core recovery evidence, installed SDK consumer checks and
pinned component upgrade/downgrade fixtures. These strengthen the local boundary
evidence for INV21–INV26 and SC23/SC25. They do not close packaged independent
transport, full profile lifecycle, remaining mutation-key or physical obligations.
Exact commits, counts and limitations remain in the ledger. Interim CI at
`dcac85e` independently passes 2,871 policy cases but fails other required jobs.
Runtime profile catalog/credential/selection component checks at `8ef8dd5` and
older-client selected-slot checks at `d8869d0` strengthen INV21/22/25/26 and
SC22/25/26. Actual platform key-provider installation and renderer unknown-call
recovery remain required; these checks do not promote the historical rows.

The later combined policy pass at `a3a98ce` executes 3,178 cases without skips.
Exact boundary `d4091fd` passes 640 Python and eight rendered-App cases; mobile
host routing and optional keyed group acceptance add focused component evidence.
Supervisor-owned Windows/Android topology qualification is ready to execute,
but these local checks do not establish native interoperability. Platform OS
authentication, independent app-owned consumers, remaining mutation families,
and delayed settings/contact/admin UI admission remain active obligations.

Current full CI `42676194199` at `da81565` fails synthetic run-context fixtures
and packaged Windows first-time pairing. The fixture repair and final UI API
admission guards pass local checks; exact `a899b85` boundary evidence is 640
Python plus eight rendered-App cases, zero skips. Independent application
staging at `50474ec` passes nine checks, including a real outside-checkout SDK
install/import. None closes SC21, native topology or actual platform lifecycle
acceptance. The pairing defect remains under production/harness investigation.

The final CI gate failed despite both controlled direct-network platforms
passing. Local `5556cc0` adds 248 passing recovery/SDK/contract checks; call
recovery is explicitly gated on an unavailable production media-retirement
provider. Android instrumentation hooks and Kotlin packaging have local repairs
pending CI confirmation. Cold-start catalog key separation is still required
before accepting the actual Android profile-provider wiring.

The corrected local checkpoint passes all 3,251 required policy cases at
`6875b00`. Narrow first-contact repair `e7f6497` passes real native/isolated-RNS
pairing and receipt checks; exact `efbddfa` passes 649 Python and ten rendered-App
cases without skips. Fresh frozen/Android CI confirmation is still required.
Actual provider wiring also needs isolated credential-result routing; the local
passes do not change the remaining M2–M5 acceptance obligations.

The rows below summarize historical evidence, not qualification of baseline
`435b497150e5f0d12cb1c5dc7b4602da7a66ec4c` or subsequent integration commits.
The historical baseline audit supplied to this integration found 25 passing schema tests
but only 84 accepted component examples and 40 rejections/errors through the
production request parser. Parser parameter access, mutation idempotency
admission, UI workspace field translation, mobile Core stubs and direct-send
retry/refresh handling required repair and combined revalidation. Those bounded
Wave 1 repairs passed at `174728e`; remaining restart and lifecycle obligations
are assigned in Wave 2.

Consequently the checked UI/Core migration items in the roadmap establish
implementation intent, not blanket application acceptance. Wave 1 exercised the
actual Windows and Android routes through serialization and production Core,
including workspace state, messaging, settings and call control. See the
[ownership and gate inventory](Mesh_Chat_Core_Integration_Coordination.md).
The exact-source ledger closes that bounded gate; historical `local`, `component`
or `workflow` labels below do not establish broader current-source completion.

## Environment limits

These constraints cap the evidence above and are recorded again in the
[qualification ledger](Mesh_Chat_Connection_Qualification_Ledger.md):

- No physical Android or Windows device and no isolated physical test network is
  available; Android evidence is API 35 emulator evidence only.
- Packaged Windows evidence runs WebView2 and frozen peers on one Windows host;
  it is not Windows-and-Android interoperability.
- Packaged component smokes exist (TypeScript tarball, Python wheel, an
  installed-wheel Windows pipe consumer in consumer and owner scopes, and two
  packaged native WebRTC messaging sidecars). The Kotlin AAR and independent
  Android APK compile; four cross-UID consumer cases passed on the API 35
  emulator at `461c2e9` (see ledger). Full independent messaging consumers
  remain open; the specification does not require a graphical UI.
- No SDK or package is published, so no supported version-pair matrix exists.
- Branch-build release qualification executed and passed; no tagged release or
  publication was performed.
- The native Windows data-channel host is implemented behind trusted mode and
  packaged, but durable service messaging, Windows-Android/WebView interop,
  TURN/forced relay, GUI media coexistence and physical acceptance remain
  unqualified.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `local` | Deterministic or in-process tests exercise the production policy, facade or adapter boundary on the recorded source. |
| `component` | A native, emulator or packaged component run in CI proves the behavior for the recorded source and artifacts. |
| `workflow` | The required qualification matrix and final gate executed for the exact source. |
| `partial` | Evidence covers a named part of the requirement; the remainder is listed. |
| `open` | No executing evidence. |
| `unavailable` | Requires physical devices or an isolated physical network, neither of which exists in this environment. |

Component evidence never implies a supported release, and emulator evidence is
never described as physical-device qualification.

## Invariants

| ID | Status | Evidence and remaining gap |
| --- | --- | --- |
| INV01 | `local` | Supervisor fairness, single-owner and single-negotiation tests; the shared composition constructs exactly one owner at trusted startup. |
| INV02 | `local` | Stale epoch, generation, operation and timer regressions in the policy suite; runtime reconciliation tests pin bounded tombstones. |
| INV03 | `component` | Late-allocation disposal by exact handle is tested locally; Android JNI instrumentation and packaged Windows checks exercise native disposal. |
| INV04 | `local` | Stop, lock, revocation, quarantine and incompatible-authority regressions in the reducer, runtime and intent transactions. |
| INV05 | `local` | Reconnect cannot create trust, membership or disclosure; separate consent and workspace-authority suites. |
| INV06 | `component` | Manual-carrier adoption requires signed SDP, capabilities, device binding and privacy authority; native adoption scenarios exercise it on Android. |
| INV07 | `local` | Readiness requires an authorized bridge plus current route/path evidence; path loss invalidates readiness without retiring a healthy carrier. |
| INV08 | `component` | Bridge repair and mailbox-outage separation are covered locally; packaged Windows crash recovery reuses the surviving carrier. |
| INV09 | `component` | Stale cleanup and replacement retirement fences; packaged scenarios prove exact carrier reuse after restart. |
| INV10 | `component` | Durable outbox and logical IDs are covered locally; packaged crash/restart delivers without a duplicate visible message. |
| INV11 | `component` | Only an authenticated application receipt establishes delivery; packaged peers assert receipts. |
| INV12 | `partial` | Policy, effect-runner, JNI ingress, startup-packet and Windows endpoint bounds are tested, including concurrent-client and idle-session limits. Other legacy queues have not been re-qualified as part of this work. |
| INV13 | `local` | Every phase has a deadline, cancellation path and classified exit in the reducer corpus; cleanup reservations survive late completion. |
| INV14 | `local` | Fair scheduling and capacity tests, including the property corpus. |
| INV15 | `component` | Committed Stop fences immediately; packaged lifecycle proves the reopened profile keeps its identity and committed preference. |
| INV16 | `partial` | The shared composition has one owner across foreground/background. Full platform lifecycle parity for every mode remains open. |
| INV17 | `partial` | Shared-policy UI detach cannot retire a transferred carrier; media-call teardown parity across all modes is not re-qualified. |
| INV18 | `local` | Deterministic traces, replay and the seeded simulator corpus. |
| INV19 | `local` | Failed persistence keeps the in-memory denial and never reports durable success; intent-batch and authority-write regressions. |
| INV20 | `partial` | The gate rejects failed, canceled, skipped or missing required evidence; publication re-hashes staged assets against that manifest. A branch-build release qualification executed and passed on setup/MSI/APK artifacts; no tag has exercised publication. |
| INV21 | `partial` | The facade enforces caller, profile, permission and private-event boundaries in tests. The Windows named-pipe endpoint adds OS access control, executable allowlisting and an installed-wheel consumer in consumer/owner scopes; the Android Binder endpoint carries a signature permission, caller-derived grant and required gate suites, and its standalone APK now enqueues and reads a message against a host-owned approved contact, queries it after a host-process restart, rejects a changed payload for the repeated key with no duplicate, and the installed-wheel Windows consumer performs the same enqueue/query round trip plus repeated-key handle reuse, changed-payload conflict and unknown-peer rejection over the named pipe, and queries the saved handle after a host restart on the same vault. Full transport delivery, receipt, pairing and partition qualification of the independent messaging consumer remains open. |
| INV22 | `partial` | Clients carry no peer policy. Named-pipe and Binder host components exist; exclusive vault ownership is enforced by the runtime. Full packaged multi-client attachment, owner stop and lifecycle qualification remain open. |
| INV23 | `local` | Durable enqueue receipts, conflicting payload rejection and stable logical IDs across restart; acknowledgments never change peer delivery state. |
| INV24 | `local` | Explicit `resync_required` for gaps, expiry and authority change; the client consumer clears its position and resnapshots. Long-term retention is not promised. |
| INV25 | `partial` | A declared compatibility file fixes the public API, IPC, peer-wire and client namespaces, and the Python, TypeScript and Kotlin component versions are bound to it by test. Every client refuses an unsupported major before side effects, and the aggregator checks the contract. The TypeScript package shape is pinned to the declaration and ships only dist, but no published package matrix or upgrade fixtures exist. |
| INV26 | `partial` | Installed-wheel and TypeScript tarball component smokes exist. Independent Android AAR/APK Binder qualification passed four cases at `461c2e9`; full distribution-only Windows and Android messaging consumers, upgrade fixtures and support promises remain open. |

## Required scenarios

| ID | Status | Evidence and remaining gap |
| --- | --- | --- |
| SC01 | `component` | Packaged Windows peers exchange messages and authenticated receipts in both roles; no physical cross-device run. |
| SC02 | `local` | Simultaneous start, duplicate signaling and role collisions are covered by the reducer/supervisor corpus. |
| SC03 | `local` | Old answers, late native callbacks and expired timers cannot advance state; exact orphan cleanup is asserted. |
| SC04 | `partial` | Partitions are simulated deterministically; native five- and thirty-second packet partitions recovered with receipts under 30 and 240 seconds. The required 30-second partition under the specified 150 ms RTT impairment is not measured on the exact headless transports. |
| SC05 | `partial` | Loss and delayed control are simulated; native duplicate-packet and packet-partition component checks now carry durable message traffic, but no run applies the specified 150 ms RTT impairment profile. |
| SC06 | `local` | Mailbox failure keeps a healthy carrier and reports degraded future reconnect separately. |
| SC07 | `local` | Carrier failure with a healthy mailbox schedules a permitted new negotiation. |
| SC08 | `component` | Packaged Windows kills the service and reclaims the same carrier binding without new negotiation. |
| SC09 | `component` | Process and adapter restart produce a fresh epoch; packaged tests reopen the profile and preserve preferences. |
| SC10 | `component` | Stop, lock, revocation and quarantine during native creation are fenced locally; Android instrumentation covers cancelled gathering. The 294-case reducer corpus covers interruption and late completion at all 14 phases, including replacement resource protection. Packaged phase-by-phase parity remains open. |
| SC11 | `partial` | Execution-state changes are policy inputs with one owner; full Android background/foreground parity is open. |
| SC12 | `partial` | Direct Fabric suites exercise real controlled paths and NAT filters, but selected-path and negative-control evidence is not bound to policy traffic. |
| SC13 | `local` | Multiple contacts, scopes and devices are covered for fairness and isolation; no cross-device packaged run. |
| SC14 | `local` | Delayed attachment and missing path are bounded with truthful readiness. |
| SC15 | `component` | Lost receipts, duplicate packets and restart preserve one visible message per logical ID in packaged runs. |
| SC16 | `partial` | Policy and JNI queues enforce budgets and quarantine; a packaged saturation run is absent. |
| SC17 | `partial` | Packaged pairing cancellation and unapproved-restart checks exist, and native handshakes now retire exactly at offer, acceptance and answer phases. Full legacy media-call and pairing-closure re-qualification against the shared policy remains open. |
| SC18 | `partial` | Signed fixtures and existing peers still interoperate; no explicit wire-version matrix. |
| SC19 | `local` | Persistence failure during intent or adoption bookkeeping is tested for safe in-memory behavior. |
| SC20 | `workflow` | The final gate fails on missing, skipped, canceled or stale required evidence for the exact source. |
| SC21 | `open` | Independent packaged consumers can be built and exercised in CI/emulation, and two independent Reticulum processes now exchange durable messages/receipts over the native DataChannel under the legacy bridge policy. Full cross-platform messaging/receipts on production headless transports remain implementation and qualification work; physical hardware is not a prerequisite for this automated scenario. |
| SC22 | `component` | Wrong caller, profile/scope and private-control attempts are rejected before effects in facade tests. |
| SC23 | `local` | Lost reply, timeout and duplicate request after restart resolve by idempotency key; conflicting payloads fail. |
| SC24 | `local` | Bounded replay, explicit gaps, cursor expiry and consumer deduplication are covered by facade and client tests. |
| SC25 | `open` | Component clients declare versions that are checked against the compatibility declaration, but no supported SDK/API/package version pairs are published to validate or reject. |
| SC26 | `partial` | Detach does not stop the runtime; the owner can now request a stop that sets the shutdown event and closes the host stream after the reply, but process exit and packaged multi-client evidence remain unqualified. The Windows endpoint serves a bounded number of concurrent local clients. |

## Completion boundaries

| Boundary | Status | Note |
| --- | --- | --- |
| Shared policy complete | `partial` | One owner drives the experimental Android and desktop compositions, but manual-pairing parity, Windows-and-Android interoperability and legacy-loop removal are open. |
| Headless messaging complete | `partial` | Android native transport and native Windows DataChannel implementation exist. Historical native Windows durable-message and fault components use legacy bridge policy; shared-supervisor promotion, cross-platform interoperability, the complete impaired fault/receipt matrix and physical acceptance remain open. |
| External integration complete (M5) | `partial` | Authenticated host components and experimental clients exist. Supported packages, complete independent messaging consumers, UI migration and compatibility/upgrade qualification remain open. |
| Release gating complete | `partial` | Publication already requires exact-artifact aggregation. Branch-build qualification passed; tagged publication and the supported-pair matrix remain open. |

## Physical checklist

Unavailable in this environment: Wi-Fi/cellular switching, screen-off/Doze,
real process death by OS policy, Stop/lock on physical devices and end-to-end
receipts on physical hardware. No emulator, packaged or CI result on this branch
is presented as that evidence.

## Storage and distribution boundary during Wave 2

The runtime owns the vault and its lifetime profile lock. Public SDK clients
attach through the host and do not open the database or receive the vault key.
Desktop resolves Tauri's application-data directory for `com.meshchat.desktop`
and appends `profile-v1`; its key uses the OS keyring entry
`com.meshchat.desktop` / `vault-key-v1`. Android resolves the application's
private `filesDir/mesh-chat/profile-v1`; its vault key is wrapped using the
Android Keystore alias `mesh-chat-vault-key-v1`. These are implementation paths,
not a portable backup format or permission to copy a live database.

Composer use raises the vault format floor from 1 to 2 in the same transaction
as its first mutation. A format-1-only host must refuse that profile before
starting workers. The current migration tests prove local atomicity and refusal;
the pinned old/new component matrix now checks rollback, preserved records and
precise old-host refusal. Installed native platform upgrade evidence remains
required. Ordinary client
detach does not authorize stopping the owner or removing its data.

No whole-profile export/import or portable private-key backup is qualified.
An exported invitation, reconnect document or redacted diagnostic report does
not back up the profile. Uninstall/data-clear preservation and removal have not
been qualified for these combined packages. In-place upgrade fixtures must keep
the original profile and key material, then verify identity, history, outbox,
drafts and receipts after restart. Destructive uninstall is a separate fixture
with disposable synthetic data, not an upgrade step.

API major/minor, SDK package, internal IPC and signed peer-wire versions remain
separate. Wave 2 stages experimental SDK 0.3 against API 1.1; API 1.0 consumers
must retain their established behavior, while new composer methods require the
advertised minor, operations and limits before sending a mutation. The exact
tested artifact pairs, OS/architecture, permissions, hashes and migration
direction belong in the staged matrix. No historical compatibility window or
published support promise is inferred from these experimental checks.

The earlier audit of 92 keyed mutation actions is bounded. Some current
operations still declare repeatable or convergent behavior, including group
message enqueue, while section 6.6 requires mutation keys. A is auditing actual
parser, session, action overrides and domain behavior. The reviewed audit records
33 families, 45 action rows and 40 public mutation actions; those counts describe
the audit scope, not completed keyed extensions. Compatible optional-key
extensions are being implemented only for operations with atomic parent commits.
SDKs must preserve
the current declared semantics and must not invent retry keys. This unresolved
requirement prevents a full M5 or section 13 completion claim.

The repository records its license in `LICENSE` and bundled attribution in
`THIRD_PARTY_NOTICES.md` (Unicode, Twemoji, i2pd and Android WebRTC). This is an
inventory of existing files, not a completed dependency audit. Qualification
must inspect the actual staged SDK/runtime archives for their applicable
notices, native dependency versions and license materials, and ensure fixture
identities and private fault controls are absent. Windows native dependency
coverage and complete staged notice inclusion remain open until that inventory
is checked. No publication is part of this integration.
