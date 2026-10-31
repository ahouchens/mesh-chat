# Connection runtime implementation and qualification

Feature branch: `codex/mesh-chat-core-refactor`.

The supplied [specification](Mesh_Chat_Connection_Runtime_Spec.md) remains the
requirements baseline. Its referenced companion roadmap was not supplied; this
file records implementation work and evidence without claiming that missing
roadmap's PR numbering or approvals.

![Proposed Mesh Chat Core architecture](architecture/mesh-chat-core.png)

## Baseline and diagram review

Implementation starts at v0.9.66, `7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516`,
one release after the specification's v0.9.65 review. The working tree was clean
when the feature branch was created. Later unrelated link-preview edits in the
shared checkout are excluded from the refactor's commits.

The diagram agrees with the specification: a protected service owns lifecycle
policy; private hosts provide platform facts; message payloads bypass the
policy reducer; and external API qualification follows headless transport.
The diagram is a **target**, not evidence that all illustrated components ship.
The green bridge/path states do not represent authenticated message delivery.

`AUTO_RECONNECT_SPEC.md` and the Android background ADR describe the legacy
implementation. Statements that the renderer always owns reconnect, or that
background execution needs a separate policy owner, are superseded for the
experimental `shared-native` composition. They still describe the default
legacy composition until migration is qualified. Existing QUIC recovery and
media-call ownership are unchanged.

## Baseline policy inventory

| Concern | Renderer | Android background | Experimental shared policy |
| --- | --- | --- | --- |
| Concurrent attempts/work | 2 | 2 | 2 effect reservations |
| Disconnect grace | 10 s | 10 s | 10 s |
| Backoff | 1/2/5/15/30/60 s | 1/2/5/15/30/60 s | Same sequence and cap |
| Mailbox poll | 5 s | 5 s | 5 s; one fetch per effect |
| Request/answer wait | 25 s | 45 s | 45 s per phase |
| Native gathering | Native operation bound | 20 s native; 45 s following phase | 25 s gather budget; 45 s following phase |
| Actor/native limits | Per-coordinator bounded workers | Native host limit 16 | 256 actor records; native host limit unchanged |

The shared policy intentionally uses background phase budgets initially;
platform latency parity remains a qualification item. No native session capacity
is raised. Runtime epoch is fresh; actor keys retain scope, profile and device
identity. Monotonic deadlines never enter persistent storage.

## Milestones

| Milestone | Implementation status | Required remaining evidence/work |
| --- | --- | --- |
| M0 baseline | Spec and diagram imported; baseline regression corpus passes | Record platform timing baselines in CI |
| M1 policy/contract foundation | Immutable model, pure phase reducer, fair supervisor, bounded effects, native domain adapters, simulator, strict model checks, executing snapshot schema and initial public request/error design contracts | Complete public result/event schemas and facade design; extend adversarial corpus to all invariant classes |
| M2 shared policy | Experimental service composition, renderer fencing, native manual-carrier adoption, isolated contact onboarding and private Windows transport registration/rebinding | Remaining manual-pairing modes, Windows/Android interoperability, full native authority conformance, broader restart/fault cases and removal of migrated legacy loops |
| M3 qualification gates | Deterministic inventory/evidence gate; shared conservative workflow selector and final execution gate | Narrower dependency selection after isolation is qualified; complete cross-suite evidence and exact-artifact release aggregation |
| M4 headless messaging | Existing Android native transport reused | Production native Windows DataChannel adapter, packaged fault matrix and receipt soak |
| M5 supported consumers | Not implemented | Public authenticated facade, durable idempotency/event cursors, packaged SDKs/CLI, independent Windows and Android consumers and compatibility matrix |

The user has specified emulation and GitHub CI only. Physical devices and an
isolated physical test network are unavailable. Physical acceptance items in the
original specification remain explicitly unqualified; emulator results cannot
be relabeled as physical evidence.

## Migration and rollback

The private `MeshChatService(..., connection_policy="shared-native")` composition
requires a native host and selects exactly one policy owner for that service.
It is not exposed as a renderer command or a live toggle. Default construction
continues to select `legacy`. Starting the experimental composition does not
promise Windows native support: an unavailable native host fails explicitly.
The private constructor can receive a host object from trusted composition;
required transport methods are checked before service workers start. Android
class loading is isolated in the host adapter and remains the default binding.
No JSON command selects or replaces this object. Constructor-level regressions
exercise explicit and Android-default binding, missing capabilities, idle startup
without a profile, and exclusive shared ownership. A test host is not evidence
of a production Windows transport.

Mobile initialization now accepts the experimental policy only as a trusted
Python host argument, before constructing the service. JSON initialization still
rejects policy and host selectors, default initialization remains legacy, and a
second initialization cannot switch the running owner. Failed profile creation
closes the unpublished service and its workers before releasing storage.
Android's two manual-carrier adoption scenarios now use this bootstrap and the
owner it starts, including the production execution-availability binding. They
no longer mutate a legacy service's policy or install a replacement runtime.
Remote path readiness remains synthetic and approval is seeded: these scenarios
are native composition evidence, not first-time pairing or application-receipt
qualification. Legacy wrappers remain until the other M2 gates pass.

The new runtime uses existing signed request/offer/answer and consent methods;
it does not alter peer wire formats, mailbox choices, vault schema, or receipts.
Explicit Stop closes the in-memory gate before persistence. A failed write
cannot allow the current runtime to restart that profile. Shutdown retains keys
until native effects and cleanup have finished; late allocation is retired by
exact handle.

Connection Start/Stop now delegates to one domain intent component, separate
from signed signaling and retry policy. Each operation commits its selected
profile intents as one sealed batch; a global Stop includes the global status in
that transaction. Profile preparation and legacy preference migration precede
Start's intent batch. No resume notification happens before a successful commit,
and Start without reciprocal consent cannot clear a Stop fence. Start-all resumes
only the contacts whose Start intent was committed, preserving failed-Stop fences
on excluded manual peers. Automatic activation cannot release explicit fences.
Stop still fences before storage access and independently invalidates surviving
carrier checkpoints before attempting the intent batch. A failed batch retains
those safety effects but reports persistence failure; it does not claim durable
Stop. Legacy native disposal runs after the complete batch and attempts every
target even if one close fails. These compatibility methods still exist; they are
not public facade mutations and do not add a second retry owner.

Native callbacks for service-owned profiles report transport facts; the reducer
alone admits attachment and retirement. Periodic native/channel/route inspection
uses the same bounded effect runner, with a poll-interval deadline. Failed or
late inspection cannot restore readiness. A missing route invalidates readiness
while preserving a healthy carrier for bridge repair. Default activation cannot
clear an explicit Stop, including one issued before the first profile scan.

Before mailbox negotiation, a bounded private discovery effect can claim an
existing native manual carrier. The protected service checks current approval,
privacy policy, exact local/remote device profile,
signed onboarding SDP against the actual applied remote description, and signed
capabilities received on that carrier. The reducer then requires fresh native
inspection, bridge attachment and path readiness. Mailbox configuration is not
required to retain this established carrier. Pending onboarding in the shared
composition keeps its control channel and a limited isolated contact-handshake
scope; it cannot attach the main messaging bridge before ownership transfer.
UI close/detach commands cannot
retire it after transfer; explicit Stop still does. Failed durable Stop also
retires verified manual peers awaiting transfer while retaining the memory fence.
Native attachment evidence requires the exact online interface to remain in the
current RNS registry with a running network. Missing, detached or unregistered
bridges are repaired on the same carrier. Stale interface callbacks cannot send
through its replacement, and packets are not fed into an unregistered interface.
Shared bridge attachment and packet forwarding additionally require the owner's
current exact-resource lease. Stop revokes that lease synchronously, including
before a failed durable write or delayed native disposal. This read-only lease
check uses a profile index and does not run policy transitions for packet traffic.
Manual carriers can be adopted when automatic reconnect is disabled locally or
by the peer. The composition derives this limited authority from the actual
signed, live carrier; it is absent from public commands and profile responses.
Adoption does not change saved reconnect preferences, activate automatic intent,
or allow signaling/new peer allocation. Losing that carrier ends this authority.
Explicit Stop and failed durable Stop still fence it. Signed control cannot
rebind a carrier to another scope or local/remote device. Desktop WebView carriers
remain outside this adoption path.

`DISCOVER` and `Adopted` extend the private in-process effect contract. Its
producers are the native executor and simulator; its consumers are the reducer,
supervisor and bounded effect runner. No public event injection or peer wire
version changes accompany this addition. The Android signaling instrumentation
includes a production-service/composition adoption scenario with real signed
control, JNI channels and packet traffic. It injects execution availability and
path readiness, seeds approval, and cannot qualify invitation UI or LXMF receipts.
Its passing emulator result must be recorded against the tested commit.
An additional emulator scenario covers disabled automatic reconnect; its result
is not claimed until that exact source passes CI.

JNI ingress has separate lifecycle (512 events / 64 KiB) and data (256 events /
2 MiB) budgets. Packet overflow records loss; lost lifecycle or consent control
quarantines the adapter. Android metadata callbacks admit at most 64 tasks plus
a reserved disposal task per native session. Stalled effects retain their
reservations and protected key lifetime; the UI reports `adapter_quarantined`
until a new runtime is started. These bounds do not qualify all other legacy
queues or constitute a packaged saturation result.

Adapter quarantine is now a terminal runtime fence, separate from persisted user
intent. Private native admission also covers manual offers/answers, onboarding
binding, control delivery and pending contact interpreters before a connection
profile exists. A missing, quarantined or stopped shared owner cannot admit this
work. Late native allocations are retired by exact handle, late answer/control
results cannot claim success, and pending-worker completions cannot update
message status after admission closes. Serialized worker requests recheck
admission after acquiring their lock, including activation and packet exchange.
That recheck now uses the complete pending-scope admission rule: cancellation,
signed/monotonic expiry, blocked identity, exact carrier ownership, scope removal
and execution availability, as well as the terminal runtime fence. An expired
scope cannot allocate an interpreter. Scope loss during allocation closes the
new worker before identity-key access or initialization. The change implements
the specification's limited onboarding scope and stale-work/revocation rules
(sections on ownership, cancellation and admission); it adds no retry owner.
Regression traces cover each denial after serialized waits, a real contended
worker lock, startup expiry and allocation cleanup. They are in-process evidence;
the existing isolated-worker exchange test also passes, while JNI and packaged
onboarding still require their matching CI run.
Existing native maintenance disposes
unmanaged carriers; supervisor-owned carriers keep their existing cleanup owner.
Explicit disposal and closed-resource callbacks remain available. These checks
extend the shared policy fence without promoting it or removing legacy wrappers.

The terminal fence remains separate from persisted user
intent and diagnostic failures. Neither a contact Start nor Start-all can release
it, including before the first actor scan. Shutdown has the same permanent
admission boundary. Terminal runtimes cannot activate profiles, admit recovered
carriers or begin startup inventory reconciliation. A later cleanup failure or
driver exception cannot replace the quarantine classification. Exact-resource
disposal still retries on the existing bounded schedule while quarantine is in
effect; cancellation retains the allocation reservation until its completion is
consumed. A late allocation is retired and cannot regain a messaging lease.
Only a new runtime can re-evaluate stored intent and current authority. These
in-process fault regressions cover the lifecycle requirements in section 5.3 and
INV13; they do not constitute packaged adapter saturation evidence or remove any
remaining legacy-policy wrapper.

Shared native carriers retain early encrypted packets while bridge attachment is
pending or RNS registration is being repaired. A separate private buffer admits
at most 16 physical allocations, 16 packets and 16 KiB per allocation, with a
1,064-byte packet bound. Overflow drops incoming data and counts the loss without
evicting lifecycle events. Unadopted manual peers cannot populate this buffer.
Attachment installs the registered consumer, rechecks the current owner lease,
and drains packets before announcing. Closing or releasing an exact allocation
discards its queued packets even if native disposal fails. Public ID reuse cannot
replay packets from an earlier allocation. The producer is the private JNI message
callback and the consumer is the existing RNS interface; peer wire and public
API contracts are unchanged. Unit regressions cover bounds, authorization,
generation isolation and same-carrier repair. The emulator fixture delays the
attachment port and checks an actual JNI packet reaches the replacement RNS
interface; this does not assert valid RNS routing or authenticated LXMF receipts.

Android's 16-session capacity includes pending creation and physical disposal.
Duplicate native IDs cannot replace an existing peer. Empty-candidate gathering
fallback retains its original reservation, waits for the exact old peer to be
disposed, and cannot restart after cancellation. Native observers capture their
session instance rather than resolving an ID that may have been reused. A
failed physical disposal retains capacity and reports adapter overflow. JVM
concurrency tests cover these reservation rules; Android instrumentation also
checks duplicate creation and cancellation during real ICE gathering.

The service maps public session IDs to private native identities containing a
fresh service epoch and increasing allocation number. It resolves callbacks
only when dequeued, and removes mappings after creation/cleanup accounting.
Reusing a public session ID therefore cannot redirect queued native events,
late answers, inspections, close completions or old bridge sends to the new
peer. The registry admits at most 16 resources; native creation/disposal retains
its separate capacity enforcement. This changes the private host binding only;
public session IDs and signed peer wire documents remain unchanged. Instrumentation
uses private test access to resolve native handles, which is absent from public
commands and packages.

Adopted runtime resources carry the physical allocation identity rather than the
reusable public session ID. Composition resolves that identity for inspections
and attachment, and retirement verifies the expected physical allocation inside
the native lock. Delayed cleanup cannot close a later public-ID reuse. The
supervisor retains bounded retirement reservations until successful cleanup and
rejects rediscovery of a resource pending disposal. The production runtime and
deterministic simulator both acknowledge exact cleanup; failed cleanup retains
the reservation. This refines private handle semantics without changing the
versioned observation schema or signed peer protocol.

Compatibility wrappers owned by this branch: `background_reconnect.py`, the
renderer coordinator/runtime, and renderer bridge repair remain until M2
adoption and parity checks pass. Removing them before desktop and manual-pairing
adoption is implemented would break the surviving-carrier recovery guarantee.
In the shared composition the ordinary dispatcher rejects legacy negotiation,
signaling, raw renderer bridge/packet operations and status writes before reading
the persistent command cache. Managed control/answer injection is also rejected.
Private effect/domain methods remain available to the owner. Ephemeral native
results and signed onboarding verification are not replayed from a previous
process's persistent command cache. Start/Stop and durable user operations retain
their existing command semantics. The default legacy dispatch is unchanged.
Rollback uses a complete service stop and cleanup before selecting legacy in a
new runtime; live switching and dual supervision are unsupported.

Local consent/token changes, verified peer capability writes (including workspace
capabilities), and contact block/unblock/delete writes use a bounded private
authority transaction fence. Effects and packet leases are denied before the
write; only its matching successful commit permits a fresh domain scan. An old
scan cannot restore authority after a concurrent mutation. Failed writes keep
the in-memory denial until that authority change is successfully retried; they
do not claim a durable preference change. Explicit Stop fences remain independent.
The shared consent path no longer invokes native close directly: exact cleanup
is owned by the supervisor. Default legacy behavior retains its compatibility
wrapper. Blocked, missing and unapproved contacts now report
`contact_not_approved` in the existing reason-list field, consumed by reconnect
settings and both diagnostic filters. No signed document version changes.

Workspace domain writes now pass through a narrow application persistence
adapter. A change to the workspace's active state, pinned manifest/genesis,
local identity or authorization generation fences every connection in that
workspace before the existing vault transaction. The private scope key is a
typed workspace tuple, so it cannot collide with a contact/profile identifier.
The same rule covers verified incoming manifests, member/device revocation,
leaving, closure, fork quarantine and deletion. Failed writes keep the denial;
cached operation results and unrelated unread/status updates cannot clear it.
The vault still owns atomic persistence and durable replay and does not import
connection policy. Only a matching successful authority commit releases the
fence for a fresh domain scan. Domain transaction tests and an architecture
guard prevent workspace writes from bypassing this boundary. The full workspace
suite is included in the required connection evidence inventory.

The transitional desktop transport component now owns bounded browser allocations,
SDP operations, exact callback fencing and packet/control admission. It preserves
the supplied ICE policy and has no negotiation signatures, authority decisions or
peer retry timers. Failed lifecycle admission or disposal quarantines the host;
bulk overflow is counted separately. Its production module is bundled into the
Android instrumentation APK to exercise both offer roles against native WebRTC.
Unit tests cover cancellation, deadlines, resource/operation limits, error
redaction and disposal failure. The instrumentation source compiles locally;
actual Chromium/JNI execution is a separate CI gate. A private inherited-pipe
binding and browser protocol now translate the existing native method contract,
fence process epochs and monotonic requests, bound admission, and quarantine
unknown outcomes without waiting for a blocked writer. Pipe tests exercise
reordered replies and callbacks while ordinary dispatch waits. The browser
protocol is included in both emulator offer roles. Chromium/JNI instrumentation,
standard CI, policy/layout gates and Direct Fabric tests passed for
`7e3c1e5a7a00394119712bf146efecce56c326dc`. This is component evidence;
service-restart adoption is not yet connected to this component. Existing
renderer compatibility paths remain active until those parity gates pass.
The service entry point can bind this channel at private process launch with
`--shared-webview`; it selects the shared owner before workers start. JSON
initialization rejects host/policy selectors. An executing inherited-pipe test
covers replies and callbacks while dispatch waits, and shutdown wakes pending
work. The opt-in Windows Cargo feature `experimental-shared-webview` now selects
this launch mode and registers a separate hidden transport window. Default builds
still use the legacy composition. The trusted host binds a random capability to
the exact window label, fixed local document and service PID; JSON cannot choose
these identities. The broker bounds pending work, validates whole reply batches
before consuming them and reserves reset admission. A bounded browser pump keeps
lifecycle and packet budgets separate. Lost windows or stalled IPC quarantine the
Python adapter. Unexpected service exit now suspends eligible carriers in that
window; explicit shutdown and host faults dispose it. Full surviving-carrier
restart adoption remains required before M2 promotion.

The private desktop host now exposes a bounded carrier inventory for recovery
reconciliation. It reports a stable adapter epoch, exact physical resources,
description hashes, channel states and pending work without SDP/ICE credentials
or identity claims. Browser snapshots are rejected if a resource or operation
changes during hashing. The Python binding validates the complete inventory and
fences a changed adapter epoch; ordinary snapshot races remain retryable.
Cross-language digest vectors, stale-resource tests, real WebView2 observations
and both Android Chromium offer roles cover this port. This is a prerequisite,
not full restart adoption. Protected binding checkpoints and invalidation use
the encrypted vault as described below; packaged restart and receipt evidence
remain open.

Conflicting browser SDP operations now have one admitted operation per peer.
Overlap is rejected before native dispatch without retiring the active resource;
different peers retain the shared bounded operation budget. Exact retirement can
still interrupt gathering or answer application. No adapter retry queue is added.

Before the experimental desktop adapter attaches a leased messaging carrier, it
checks the native inventory against the service's signed-exchange descriptions,
current profile/device/peer binding and privacy policy. The bounded checkpoint
stores only hashes and binding identifiers in one encrypted vault record. Native
inventory I/O runs outside the dispatch lock; authority and exact resource are
rechecked before the atomic write and attachment. Stop and contact/profile/
workspace authority changes invalidate matching records before the authority
write. A persisted revision rejects stale checkpoint completions even after
permission is restored. Unrelated records remain intact; native retirement also
removes its exact checkpoint. Write failures cannot claim durable success or
prevent attempted native disposal. New private adapter incarnations discard
obsolete host records on checkpoint. Failed checkpoint retirement retains the
exact registry reservation for cleanup retry even after the native peer closes.
Startup now reconciles that protected journal against the private inventory
before profile scanning or native allocation. It rechecks current scope, peer,
device, intent, expiry and privacy authority, retires unmatched or ambiguous
resources even when no profile remains, and registers survivors under fresh
logical handles. Current journal membership is checked again after orphan
cleanup, preserving unrelated survivors while rejecting Stop/revocation races.
Recovered evidence contains no SDP and cannot bypass a new supervisor lease or
bridge/path readiness checks. Failure quarantines startup admission. Controlled
tests run this preparation and adoption through the production supervisor,
including manual carriers with automatic reconnect disabled. These component
and vault-reopen tests do not qualify packaged service-crash recovery: the
combined vault, supervisor, RNS/LXMF and receipt restart test remains required.

Windows process retirement now captures the originating PID and detaches its
transport host, native host and pending requests before a replacement is
published. Delayed cleanup cannot retire the replacement. The lifecycle guard
does not wait for a blocked stdin writer; exact process termination and deferred
handle cleanup remain available. Regression tests cover stale retirement,
delayed disposal and blocked writers. This fixes host cleanup isolation; it does
not by itself qualify surviving-carrier adoption.

The private Rust host now suspends the browser pump after an unexpected process
exit and rebinds that same window to a replacement process with a fresh service
epoch. Bounded generation controls precede new requests; obsolete completions,
queued packets and old-process observations cannot cross the boundary. Only
stable connected peers without unfinished operations survive. Each stays held
until the service checkpoints its evidence and activates the exact resource under
a fresh supervisor lease. Control or lifecycle changes while held retire the peer;
bulk packets are dropped. Explicit lock/exit also closes a retained host when no
service PID remains, without terminating a recycled OS PID. Window destruction
uses window identity across process rebinding. No retry policy moves into this
mechanism, and the experimental selector remains unpromoted.

The native WebRTC application adapter is now separated from the main service
class in `native_webrtc_service.py`. Its 26 allocation, callback, bridge and
retirement methods retain their existing behavior and command signatures.
It composes the existing signed control mixin and depends on the native host,
Reticulum interface and current owner lease. It does not import the concrete
service or move lifecycle decisions out of the reducer. Legacy compatibility
paths remain until the same M2 parity gates pass.

The experimental Windows host supplies a read-only UI routing hint before the
application loads. Manual pairing then uses the existing service transport
commands rather than allocating a second renderer peer. This hint is not a host
capability: private IPC still requires the registered window and process binding.
Pairing observes DataChannel openness independently from bridge attachment, so a
pending invitation can be reviewed without a premature transport timeout. The
dialog reports a connected path; service authority still controls packet leases
and messaging attachment. Component regressions cover both Android and Windows
routing with an open channel and no bridge. Full Windows pairing and restart
parity remain qualification requirements.

The separate `transport-qualification` executable exercises the real Windows
WebView2 host, production Python pipe binding, both offer roles, bidirectional
packets/control, actual Python process replacement, retained adapter/resource
identity, held traffic before activation, and exact retirement without opening
a vault. Windows CI requires
this result and records the source revision and binary/source hashes. Its evidence
level is `windows_webview2_private_host_component`: it does not qualify packaged
application messaging, LXMF receipts, supervisor restart adoption or headless Windows native
transport. Missing execution or missing checks fail qualification. The executable
and its report command are test tooling, absent from normal shipping builds.

## Local validation

Initialized packaged-service qualification exposed a shutdown crash hidden by
the earlier startup/EOF smoke test: the private reader could remain blocked on
buffered stdin while Python finalized. The inherited input adapter now uses
cancellable, single-reader pipe reads from the first frame onward, and private
reader shutdown joins the worker within a bounded deadline. It borrows the file
descriptor; it never closes a parent's writer or bypasses framing limits.
Regression cases cover partial headers/bodies, EOF, queued initialization frames
and actual process exit while the parent retains its writer.

Windows CI now requires an exact-build packaged lifecycle report in addition to
the real WebView2 report. It initializes protected profiles in default/shared
mode, verifies clean shutdown, force-terminates a shared-mode process tree, and
reopens the encrypted profile with the same identity and committed preference.
Private service epochs must change. The adapter fixture reports an empty
inventory, and its only other supported action is reset. Its evidence level is
`windows_packaged_service_lifecycle_empty_adapter`; it does not qualify surviving
carriers, bridge readiness, message delivery or receipts. The gate verifies a
clean source revision, the packaging input fingerprint, tested binary digest,
execution counts and source tree. Missing, partial or stale reports fail the
aggregate gate.

The combined Windows scenario now runs two frozen services through production
private WebView2 hosts with isolated, pre-approved encrypted fixture profiles.
LAN discovery, TCP and other alternate routes are disabled. Ordinary service
commands exchange signed onboarding descriptions and durable messages; both peers
must receive authenticated receipts. After killing one service process tree,
the replacement opens the same protected profile, reclaims the same physical
carrier binding and delivers another message with a receipt. Host operation
counts must prove that recovery performed no new offer/answer negotiation. A
second forced exit permits journal comparison without bypassing the profile lock.
The original delivered message must remain present exactly once.

Its evidence level is `windows_packaged_webview2_preapproved_peers`. Windows CI
requires all three checks, three process starts, two forced exits and three
authenticated receipts. The aggregate gate requires the same frozen binary/build
inputs as the lifecycle suite and the same native host as the component suite.
This closes that narrow packaged Windows recovery gap. Windows-to-Android packaged
interoperability, independent public consumers and release qualification remain open.

Shared first-time contact onboarding now uses an isolated RNS interpreter with
one exact peer and only the existing signed LXMF contact request/accept/decline
payloads. The workspace bootstrap mechanism is extracted from its workspace
scope; workspace scope behavior and peer formats are preserved. The new private
`initialize_contact` worker operation is absent from public service commands.
The worker has no alternate interfaces or routing, a five-minute/signed-expiry
ceiling and bounded packet/control queues. Only one pending scope per service
may run. Main-profile chat, workspace traffic and application receipts cannot
cross it. The existing durable outbox retains all retry decisions.

The parent revalidates exact resource, signed peer, current execution and contact
authority before each exchange, outbound packet and completion event, and
independently verifies inbound LXMF signatures. Shutdown during a host send
discards the remaining packets and events in that worker batch.
Worker completion events are selected before draining outbound packets and remain
held across full packet batches. This preserves delivery-proof ordering when a
contact completion transfers the carrier and retires the isolated interpreter.
Regressions cover a completion arriving during the drain and a proof beyond the
32-packet response limit.
Lock, shutdown, expiry, cancellation and revocation stop the scope. Endpoint
status cannot claim an application receipt. Adoption waits for contact-handshake
completion and current authorization, and retires the isolated scope before
granting the main messaging owner its carrier. Capability/control JSON alone
never approves a contact.

The separate `windows_packaged_webview2_explicit_pairing` scenario starts with no
contacts, receives an invitation without granting authority, explicitly accepts
it, receives the signed contact request, explicitly approves, and verifies both
approved states without granting direct-IP messaging. Both sides then opt into
direct-IP messaging and transfer the initial pending carrier to the authorized
messaging owner for bidirectional messages and authenticated receipts. Private
non-relay adoption requires both current signed direct-IP permissions, preventing
one side from transferring while the other's initial consent update is pending.
Relay-only carriers do not require direct-IP consent.
Private
host operation counts on both sides must show no replacement negotiation or
closure during that transfer.
The required packaged scenario now also closes both unapproved native sessions
after receipt of the invitation, checks that inspection/control on their retired
IDs fail with the expected service error, and confirms that the host executed
native disposal. It crashes and restarts the receiving service, verifies the same
pending invitation survives without contact approval or messages, then reuses the
logical session names for a fresh signed exchange. Only a subsequent explicit
acceptance and approval may enable messaging. Its report requires both fault
checks, three process starts, one forced exit and two authenticated receipts;
an older success-path-only report cannot satisfy the gate. Controller and scenario
negative controls are in-process evidence; this extended packaged sequence is
qualified only when the matching CI artifacts execute it successfully.
Workspace pairing, cancellation at other handshake phases and Android bootstrap
integration remain unqualified.
The `00628a0` CI run failed the pre-approved Windows crash/restart scenario during
transport admission with `transport_host_unavailable`; no Python startup failure
was captured. The packaged harness now retains up to eight host fault outcomes
per peer, distinguishing a WebView-reported fault from a pipe failure, with only
allowlisted codes and a boolean flag in failure artifacts. This improves diagnosis
of the recurring restart failure; it does not establish a root cause or fix. The
same WebView2 host failure recurs intermittently rather than deterministically: it
failed at `44af158` and `af4b1ce` with `NativeUnavailable`, `pending: 1, polls: 0,
queued: 1, registered: true` during offer, while the same job passed at `4a2c52c`,
`16a0dea`, `874c805` and `fea361b`. Both failing revisions were unrelated to the
Windows host (documentation and Python-client changes). The cause remains open; no
retry is masked and no successful matrix is claimed for a revision whose Windows
job failed.
Broker regressions now reproduce a process-publication race: the new process ID
is visible before trusted host rebinding, so a retained window could be rejected
as an unauthorized caller while still suspended. Poll routing now keeps the
suspended binding's process identity until explicit rebinding. Suspended polls
discard old replies and cannot admit replacement-service work; window/capability
checks and fresh-epoch admission remain enforced. Both new regressions failed
with the previous routing and pass with the fix. This establishes the broker
race and its local correction, not resolution of the recurring packaged failure;
fresh packaged crash/restart and pairing evidence is still required.
Its report is required separately from the pre-approved crash test,
with a distinct run identity and the same tested binaries.

`connection-qualification.yml` is the common PR, main-branch and merge-queue
entry point. It invokes the existing policy, verification/Windows, Android,
Direct Fabric and layout workflows; each remains manually runnable. Code,
contracts, build dependencies, selector changes and unknown paths select the
complete matrix. Only isolated documentation changes may omit Android, Direct
Fabric and layout; policy and normal verification still run. Missing diff bases,
empty changes and manual/merge-queue events expand coverage. Rename detection is
disabled for selection so both old and new paths participate. No code boundary
is assumed safe to narrow merely from its directory name.

The final `Required connection qualification gate` re-derives the plan from the
same checkout, source tree and event, then rejects absent, failed, canceled or
unexpectedly skipped workflows. This is the check to require in repository
branch protection when adopting this workflow layout; repository rules are not
changed by this source refactor. The gate downloads policy, Windows and selected
Android evidence from that workflow run. It revalidates the policy JUnit against
its complete inventory, the actual Windows transport checks and component
digests, and Android source/tree, APKs, scenario counts, run identities and
cleanup. Its manifest includes component report hashes and execution counts;
missing required reports fail. Evidence retains its component labels.
The native Direct Fabric recovery, packet-carrier and setup suites also record
their full pytest collection before execution on Linux and Windows. Required
native binaries are hashed before and after the tests; missing binaries, skips,
filters, changed source/binaries and partial execution fail. The final gate
revalidates all six JUnit inventories and requires recovery/setup to identify
the same shipping dispatcher on each platform. Source-pipe setup cases run in
that complete setup selection, without a second filtered native invocation.
This evidence covers controlled native QUIC and Python components, not packaged
consumer or physical qualification. Other Direct Fabric unit/build checks and
Linux NAT/network-provenance checks still retain their workflow gates.
The workflow result manifest is not a release qualification:
uniform scenario/count/artifact evidence across every suite and exact release
artifact aggregation remain outstanding.

Android qualification now uses one required inventory for its 16 optimized native
WebRTC cases and ten signaling/runtime cases. The buffered contact-bootstrap case checks
the private service manifest and exchanges signed contact requests and accepts
through the real Android Binder/Python worker while RNS is already active in the
calling interpreter. It rejects ordinary chat, retires the worker and checks
process cleanup. Packets are routed by the test; this is isolated worker evidence,
not Android first-time pairing over JNI or application-receipt qualification.
The additional native contact-bootstrap case runs the same signed request/accept
and ordinary-chat rejection through two real JNI DataChannels and the private
Binder worker. Its instrumentation-only callback capture has bounded queues and
packet sizes, fails on native errors or overflow, requires native receive counts
in both directions, retires both native handles and restores the callback on
exit. It cannot intercept a running application. The required report inventory
includes this case; the previous 25-case report cannot satisfy the updated gate.
This tests native contact-scope transport, not main-service approval, carrier
transfer, Windows-to-Android pairing or application receipts. Desktop harness
tests and isolated-worker checks do not substitute for its emulator execution.
Each invocation writes a fresh
run marker into its instrumentation log. Evidence requires exactly the expected
class/method, one started and successful test, no skip/failure status, and the
same source/tree and optimized host/instrumentation APK digests recorded before
execution. The reporter verifies emulator identity and that the isolated test
app's processes stopped. Missing or stale logs, changed APKs and cleanup failure
fail the job. Its evidence level is
`android_emulator_optimized_native_and_python_components`; these test-host APKs
are not proof of physical-device or independently packaged consumer acceptance.

Private observation contracts live in `contracts/connection/`; experimental
application request/error contracts and the permission inventory live separately
in `contracts/core-api/`. JSON Schema tests validate real policy projections and
reject private fields and incompatible public requests. Public schemas are design
artifacts, not shipping host capabilities: the operation inventory advertises
none as host-accessible. A private facade component now negotiates
capabilities and returns caller-scoped profile/connection observations. Current
grants are checked under the service dispatch lock and handles are bound to caller
and profile. Its message port now atomically commits text outbox records and
caller/profile/operation-scoped idempotency receipts, with bounded query indexes
and quotas. Retried enqueue resolves the original logical message after restart;
conflicts, expired/deleted results and current authority failures are explicit.
Message queries project current domain delivery state without fabricating a receipt.
Regression coverage includes concurrent callers, failed commits, lost replies,
restart, deletion, revocation, bounded UTF-8 payloads and actual signed messages
and application receipts through the deterministic two-peer service harness.
This is internal component evidence, not an authenticated or packaged public API.
It has no public bootstrap or native/event injection. OS-authenticated host bindings,
other durable mutations/events, long-term idempotency storage policy and consumers remain
required. JSON Schema validation is a development-only dependency and
does not replace trusted caller authentication or domain authorization.

The private facade now also implements bounded message snapshots and durable
change replay for its own outbound text messages. A domain journal is attached
before service startup recovery; a storage projection port commits content-free
change records in the original message transaction across every mutation path.
The encrypted ring holds at most 2,048 changes, with a seven-day replay window.
Snapshots expose their replay watermark only after the final consistent page;
concurrent changes during pagination require an explicit resynchronization.
Caller/profile/purpose-bound encrypted cursors survive ordinary service restart,
and expiry, overwritten records and changed contact authority fail explicitly.
Queries scan at most 128 entries plus index lookahead and bound encoded responses
to one MiB. Consumer acknowledgments now atomically commit a caller/profile
checkpoint, idempotency receipt and bounded quota. Null-cursor polling resumes the
last confirmed position across service restart. Lost-reply replay is stable even
when newer progress exists; new acknowledgments cannot rewind it. Polling never
advances progress or renews its seven-day lifetime. Retention gaps, expiry and
changed authority require an explicit fresh snapshot. Acknowledgments cannot
change peer delivery state. Request validation is separated from session authority,
and cursor encoding is separated from durable progress and snapshot/replay adapters.
This is component evidence only. Incoming-message access, authenticated host
bindings, long-term key storage and mixed-version cursor compatibility remain
unfinished; old journal-unaware binaries cannot claim replay compatibility.

The private facade also provides `diagnostics.query` behind a separate `diagnose`
grant. It exposes current shared-policy observations with caller/profile-scoped
connection handles, explicit availability, allowlisted runtime failures and
truncation metadata. Requests return at most 256 entries within 256 KiB; an
oversized source fails rather than being silently truncated. Legacy-only runtimes
report diagnostics unavailable. This read-only adapter cannot expose application-wide
history, scan messages, persist retention changes, inspect native peers or alter
lifecycle policy. Contract, scope, revocation, malformed-result and no-effects
regressions qualify the component only; host authentication remains unfinished.

A private framed-session adapter now drives the facade over host-supplied binary
streams. Strict single-line UTF-8 JSON decoding rejects duplicate members, invalid
Unicode/numbers and oversized/deep/over-complex requests before dispatch. It reads
one bounded frame and completes one response before another request; short writes
do not reexecute commands. Malformed frames and stream errors detach the session.
Read/write waits occur outside the service dispatch lock. Lost enqueue replies are
resolved with the same durable key on a new authenticated session. The adapter adds
no listener, bootstrap authority, peer retry policy or runtime ownership. Its tests
use component/in-memory streams; authenticated OS endpoints, SDK packaging and
independent consumers remain required.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest service/tests/connection -q
```

From `service/`:

```powershell
..\.venv\Scripts\python.exe -m mypy --config-file mypy-connection.ini
..\.venv\Scripts\python.exe -m tools.connection_harness simulate --scenario stale_completion --seed 42
..\.venv\Scripts\python.exe -m tools.connection_harness simulate --scenario fault_sequence --seed 48 --output trace.json
..\.venv\Scripts\python.exe -m tools.connection_harness replay --trace trace.json
```

Saved traces include their schema version, policy constants and an implementation
digest. Replay rejects incompatible code, malformed actions and incomplete resource
cleanup; it executes the saved actions through the production supervisor and oracle.
Reproducing an older trace requires its matching source revision. This CLI is a
qualification tool, not a shipping private-event injection endpoint.

The simulator runs the production reducer/supervisor with virtual time. Its
resource oracle and Hypothesis state machine exercise 1,000 sequences of up to
100 actions, including successful and failed manual adoption, duplicated
completion, cancellation and recovery. The CI policy runner records every
collected node ID before execution and binds JUnit results to that run. Filters,
collection failures, missing suites, skipped cases, stale reports, duplicate
results and partial execution fail the gate. The inventory is retained beside
the report and evidence JSON. These are policy tests, not native transport, cryptographic,
application-receipt, real-clock, or packaged interoperability evidence.

## Received-message visibility

The private facade could enumerate only the messages a caller had enqueued, so a
consumer could not read an authorized conversation. That gap blocked external
integration independently of host authentication. The service now maintains a
second transaction-local projection over the message namespace: an ordered,
content-free index of inbound chat messages. The index stores the message identity,
its contact and its creation time; text and delivery state stay in the
authoritative message record and are read from it. Outbound messages, receipts and
every other message kind are excluded, so the surface cannot enumerate another
direction or unrelated domain records. Deleting a message removes its index entry
in the same transaction, and a projection failure aborts the message commit rather
than leaving an unlistable message.

`message.received` pages that index oldest first, after capability negotiation and
the `read` grant, and reuses the profile-scope and contact-authority checks of the
recovery adapter. Each item returns caller-scoped opaque message and peer handles,
the retained text, the committed delivery state and `created_at`. Cursors are bound
to caller, profile, purpose and the current contact-authority signature; they
survive ordinary service restart, expire with the seven-day replay window, cannot
be exchanged with snapshot or replay cursors, and return `resync_required` after
contact revocation rather than silently skipping a hidden message. A request scans
at most 128 index entries, returns at most the requested 1-128 items, and keeps the
encoded page within one MiB. The vault now accepts several independent projections
per source namespace; each observes the same committed changes, sees no sibling's
derived records, and any failure rolls back the whole transaction.

Replay extends to those messages: a journal record now carries the message
direction, so `events.poll` emits `message.changed` and `message.removed` events
for inbound text with the same opaque handle `message.received` returns. Events
select the direction explicitly; records written before the field existed are
treated as the caller's outbound stream, which is the only stream they could have
belonged to. Authority changes still invalidate the cursor instead of skipping a
now-hidden message, and the snapshot watermark closes the inbound query/subscribe
race.

Evidence: 18 in-process regressions cover atomic commit and rollback, content-free
index records, chronological pagination without duplicates, direction and kind
filtering, contact-authority hiding and resync, caller-scoped handles and cursors,
cursor-purpose confusion, state changes, deletion, bounds, request validation,
service restart, inbound replay for changes and removal, hidden changes after
blocking, the watermark handshake and outbound direction. Journal tests pin the
stored direction, including its removal with the message. AST guards keep the
received index free of ambient I/O and outer-layer imports, and keep the
application facade from importing the service, workspace, native or reducer
modules. The complete required inventory passed at 1,208 tests with zero skips and
the strict model type check passed; these remain in-process and component
results. Four further vault regressions cover multiple projections, one
failing sibling rolling back the batch, duplicate binding rejection and the binding
cap. The full connection directory passed locally (850 tests), the strict model
type check passed, and the contract vectors and schemas were updated. This closes
inbound text enumeration for the private component only. Incoming-message events,
other message kinds, connection intent commands, authenticated host bindings, SDKs
and independent consumers remain open.

## Uniform qualification and release evidence

The final gate manifest now carries a uniform `suites` array in addition to the
component summary. Every required component contributes one record with the same
keys: source commit and tree, evidence level, executed test counts or check count,
artifact digests, cleanup outcome and the report digest. A suite record with a
failed or skipped case, a non-positive check count, a missing or malformed digest,
or a duplicate identity fails the gate instead of being summarized away. The
records keep their component labels; they do not promote emulator, packaged or
native packet-count evidence to another level.

`scripts/release_qualification.py` implements the exact-artifact step that
publication needs. It accepts the gate manifest, the source commit and tree, the
semantic release version and exactly three artifacts (NSIS installer, MSI and the
signed Android APK), verifies each file's name binds the version, refuses empty or
oversized files, and records size and SHA-256 for each. It rejects a manifest that
did not pass, belongs to another source or tree, skipped a required job, omitted a
required component, contains failed or skipped counts or reports an unsupported
public API contract version. Its output binds the exact binaries to the qualified
source, API contract, internal contract and the component records, and states its
scope rather than implying release or physical qualification.

Its thirteen tests cover the accepted path and every refusal: wrong source, wrong
tree, unpassed manifest, failed required job, skipped case, missing component,
missing, empty or version-mismatched artifact, incomplete inventory and unsupported
API major. Publication wiring is still required: the release workflow does not yet
run this step, so INV20 is not enforced for a real publication.

## Qualification status at this revision

The run for `14b79f3` (`41118651018`) reported a real failure, not an infrastructure
one: the Android emulator job failed both manual-adoption scenarios
(`sharedRuntimeAdoptsVerifiedManualNativeCarrierWithoutMailbox` and
`sharedRuntimeAdoptsManualCarrierWithAutomaticReconnectDisabled`) with a bare
`AssertionError` at the fixture assertion that the shared owner holds exactly one
state whose carrier resource is the exact adopted allocation. The previous complete
Android matrix predates `469c727`, which moved shared-owner construction to trusted
startup; the intervening runs were canceled before Android executed, so this failure
had not been observed. An in-process reproduction explains it: trusted startup
registers the profile while its signed remote device is still unknown, and when the
capabilities bind that device the reconciler registers the new connection key and
retires the old one. `ConnectionSupervisor.retire` intentionally keeps a bounded
stopped tombstone so a late completion cannot recreate the actor (specification
section 3.1), so two states now exist where the fixture began from one. The fixture
assertion counted states instead of checking ownership; it now requires exactly one
carrier, that the carrier is the exact adopted physical allocation, and that every
other state is a stopped tombstone, and it reports the observed keys and carriers on
failure. A new in-process regression pins that behaviour: one live actor for the
current key, one stopped tombstone, no duplicated actor on repeated reconciliation,
and no carrier on the tombstone. Production policy is unchanged. The emulator rerun
that would confirm the corrected assertion had not executed when this entry was
written. Policy, verification,
Windows packaged checks, layout, Android compilation and the final policy gate passed
on the same run; the Direct Fabric jobs were still executing when this entry was
written.

## Host binding component

`core_api/host.py` lets a trusted host hand the private facade a binary stream
pair it already accepted, with the caller identity, permission subset and profile
scope that host authenticated. The grant is captured before serving, so a frame
cannot select a caller, widen its permissions or change scope; runtime ownership
is not an available permission. Serving runs until EOF and detaches that one
session without stopping the app-owned runtime or its outbox. Ten in-process
regressions cover negotiated requests, a caller-injection attempt, caller-scoped
handles, permission bounding, invalid caller/permission/scope forms, EOF detach
and malformed-frame detach.

This is a component binding only. No operating-system access control is implied:
a Windows named pipe or Android Binder endpoint must still supply the streams and
prove the peer's identity, and no SDK or packaged consumer exists. The checklist
below therefore keeps authenticated host bindings open.

## Windows host endpoint

`core_api/pipe_endpoint.py` binds the facade to a private Windows named pipe.
The security descriptor grants only SYSTEM and the current user, remote clients
are rejected, and the endpoint refuses to reuse an existing pipe name, so a
squatter cannot serve a caller first. A connection is admitted only when the
client's real executable image matches a host-supplied allowlist exactly; the
observed image is not assumed to equal a launcher path, and rejection happens
before any frame is read. A bounded number of authenticated clients (one to
eight, four by default) is served concurrently, each session carrying the fixed
caller and permission set the trusted host supplied; the endpoint never starts or
stops a runtime, and every client shares the one app-owned runtime. An
inactivity deadline (sixty seconds by default, bounded to one hour) closes an
idle connection so one silent client cannot hold a worker slot indefinitely.

All pipe I/O is overlapped so shutdown cancels a pending accept or read instead
of blocking on a synchronous handle close. The endpoint is Windows-only by
construction; its portable rules live in `pipe_policy.py` and are checked on every
runner. Seven Windows integration tests cover an allowed client negotiating
through the real service, rejection of an unlisted image without a session,
sequential and concurrent clients, the client budget, idle disconnection and its
bounds, refusal to reuse a live pipe name, and untrusted configuration. Three portable tests cover the name
namespace, allowlist validation and exact image matching. This is component evidence: no packaged consumer, Android Binder
endpoint, SDK distribution or support matrix exists.

## Experimental TypeScript client

`sdk/typescript/` is a thin, strict client for the same frame contract: it
negotiates capabilities, serializes requests because the host binding reads one
frame at a time, correlates each response with its own request id, maps stable
error codes to typed errors with their retry hint, and turns malformed,
oversized, uncorrelated or closed-stream responses into distinct failures. Typed
helpers cover profile query, connection snapshot, received pages, durable
enqueue, event polling, acknowledgment and diagnostics; out-of-bounds limits and
a missing idempotency key fail before anything is written. A resynchronizing
consumer walks every snapshot page, deduplicates redelivered events, clears its
position on `resync_required` and acknowledges only a caller-confirmed position;
an AbortSignal cancels before dispatch without writing, or reports an unknown
outcome without resending. Twenty-two Node tests cover those paths, including
abort, timeout, deduplication and confirmation. A cross-language conformance
test runs the compiled client against the real Python facade over inherited
stdio: capability negotiation, profile query, received pages, snapshot watermark
and replay all traverse the production frame contract. General verification runs
it after building the client.

It carries no host authentication, socket, runtime ownership, peer retry or
private import. It is not wired into CI, no package is published, no Kotlin
client or production CLI exists, and no independent consumer uses it. It does
not qualify M5.

## Experimental Python client and CLI

`core_api/client.py` is a strict synchronous client for the same frames: it
negotiates capabilities, checks the response version and correlation, raises a
typed error carrying the stable code and retry hint, and treats malformed or
truncated responses as protocol failures. `core_api/cli.py` exposes
`capabilities`, `profile`, `received`, `events`, `enqueue`, `ack` and
`diagnostics` over a host-owned Windows pipe, prints selected JSON and exits
non-zero on a typed failure without raising. `core_api/pipe_client.py` is the
minimal blocking Windows transport; it never listens and never starts a runtime.

Ten portable tests cover negotiation, typed failures, malformed and misrouted
responses, helper parameters and idempotency keys, CLI output and error mapping,
and command rejection. Four end-to-end tests run the client and CLI against the
real framed facade over OS pipes: negotiated capabilities, durable enqueue and
query, replay from a snapshot watermark, null-cursor resynchronization, and handle
rejection. One Windows test runs the CLI against the real endpoint through its
pipe. This is not a packaged console script: there is no installed
entry point, no versioned distribution, no Android transport and no support
matrix.

## Contact-wide connection intent

A consumer could observe and message but could not ask the runtime to connect or
stop. `connection.start` and `connection.stop` now apply contact-wide desired
state to an approved peer handle. The domain keeps ownership of durable intent
and its fences; `ServiceIntent` only rechecks current caller, profile and peer
authority, applies the domain command and projects the resulting state. A start
that no current consent or capability makes eligible reports `stopped`/inactive
rather than claiming intent, and a failed write returns `unavailable` without
reporting a stop. Both commands converge on the same state, so the contract
declares them convergent mutations instead of inventing a receipt that could not
share the domain transaction.

Seven in-process regressions cover convergent stop, truthful ineligible start,
applied start/stop after both consents exist, blocked and unknown peers, the
connect grant and caller scope, failed-persistence honesty, and capability
advertisement. This is contact-wide intent; per-device selection, workspace
pairing and the shared-runtime parity gates remain open.

## Compatibility declaration and packaged entry point

`contracts/core-api/compatibility-v1.json` now states the compatibility posture
explicitly: public API major 1 with additive minors, internal IPC 1, the signed
peer wire unchanged, TypeScript `0.1.0-experimental`, Python an unversioned
component and Kotlin absent. Incompatible combinations are rejected before side
effects and no upgrade window is promised before M5. A declaration test compares
the file with the operations inventory, so the namespaces cannot drift.

Both clients refuse an unsupported public API major during negotiation, before
any other command, and accept additive minors inside major 1. The service also
declares a `mesh-chat-core` console entry point and `python -m
mesh_chat.core_api` runs the CLI; neither is a published distribution, and the
CLI reports `unsupported_platform` rather than a traceback where no Windows pipe
exists. Eight Python regressions and one TypeScript regression cover the rules,
the client refusal, the entry-point help path, the declared script and the typed
platform failure.

## Release publication gate

Publication no longer depends only on a green build. The release workflow now
calls the connection qualification workflow for the tag commit, requires its
final manifest, stages the exact Windows and Android artifacts, and runs the
release aggregator to bind their names, sizes and SHA-256 digests to the qualified
source, tree and API contract. Publication then downloads that manifest and
re-hashes the staged files with `scripts/verify_release_assets.py` immediately
before upload; a changed byte, missing asset, unpassed manifest or different
release version fails the job instead of publishing.

Seven asset-verification regressions cover the accepted bytes and every refusal
(changed byte, missing asset, unpassed manifest, wrong version, incomplete
inventory), and three narrow packaging guards keep the workflow wiring present:
the qualification workflow is callable, publication depends on it, and the
pre-upload digest check still points at the manifest. No release run has executed
this path yet, so it is wiring evidence rather than an executed release
qualification.

## Peer approval and revocation

The relationship family now has its explicit, convergent half: `peer.approve`
accepts a pending request (a no-op for an already approved or verified peer, a
refusal for any other trust state) and `peer.revoke` blocks the peer. Both address
the caller-scoped peer handle, require the `approve` grant, and reuse the existing
domain transactions: approval queues the signed acceptance, revocation fences
connection work before the trust write commits, and a failed write returns
`unavailable` without reporting the change. No consent default, disclosure
preference or workspace membership is modified.

Seven in-process regressions cover pending approval and convergence, an already
verified peer, refused states (blocked, awaiting consent, identity changed),
revocation and its convergence, the approve grant with caller scope, failed-write
honesty and capability advertisement. Pairing-document creation/acceptance and
workspace relationships remain open.

## Inbound pairing acceptance

`peer.pairing_accept` lets an authenticated caller submit a signed invitation the
user obtained out of band. Verification stays in the existing domain rules:
signature, destination, expiry and kind are checked before a contact exists, a
self-invitation is refused, and I2P invitations are refused because their consent
cannot be inferred from a request. The result returns only the peer handle and its
trust state; accepting the same document again converges on the same contact, so
the operation is declared convergent. The contact remains unapproved until the
ordinary explicit approval flow completes, and no disclosure or reconnect consent
is changed.

Four in-process regressions cover acceptance into an unapproved contact plus
convergence, invalid/self/oversized documents, the pair grant with caller scope,
and capability advertisement. Outbound pairing creation, per-peer documents,
workspace invitations and the Android binding remain open.

## Outbound pairing material

`peer.pairing_create` exposes the profile's signed invitation in the forms the
application already displays (`file`, `link`, `expires_at`). It is a query: no
durable state changes, it is declared `query` in the manifest rather than a
mutation, and it requires the `pair` grant. The returned material is public
onboarding data, not identity key material, and the adapter re-checks the type,
size and timestamp before the view accepts it.

Two in-process regressions verify that the returned file verifies to the local
destination and that repeated calls succeed, plus refusal without the grant or
for another caller's profile. Per-peer documents, workspace invitations and the
Android binding remain open.

## Owner-authorized stop

`runtime.stop` is available to the trusted host that holds the `runtime_owner`
grant. It sets the service's existing shutdown event, replies with
`{stopping: true, already_stopping}` and lets `FramedSession` close the stream
after the reply; the owning host still performs resource cleanup, because calling
`close()` under the dispatch lock would be a deadlock rather than a graceful stop.
Afterward the same session answers `forbidden` and other sessions on that service
become `unauthenticated`, since the grant callback returns nothing once shutdown is
requested. The operation is convergent, rejects a caller key rather than ignoring
it, and its result is bounded by `stop-result-v1`.

Five regressions cover the shutdown request and refusal of further work, the
adapter's already-stopping observation, owner-only access, caller-key rejection and
a framed stream that returns the stop reply and then closes. Actual process exit is
the host's responsibility and is not claimed by this component.

## Remaining work checklist

Reconciled against the specification's invariant list, SC01-SC26 and definition of
done. A checked item has executing evidence at the named level and never implies a
higher evidence level. The per-invariant and per-scenario status table, including
every `partial`, `open` and `unavailable` entry, is maintained in the
[acceptance reconciliation](Mesh_Chat_Connection_Runtime_Acceptance.md) and is
enforced by a test so it cannot silently drift or overclaim.

M2 - shared policy

- [x] One policy owner for the experimental Android composition, including startup
      construction, quarantine fencing and stale-scope rejection.
- [x] Manual native carrier adoption with signed control, exact resource identity
      and bridge repair (in-process and emulator component evidence).
- [ ] Windows-Android packaged interoperability (no shared runner topology).
- [ ] Full Android application onboarding/approval/carrier transfer through the
      application path; the isolated worker and the native contact-scope transport
      are component evidence only.
- [ ] Workspace pairing and non-default manual pairing modes in the shared
      composition.
- [ ] Cancellation at every handshake phase, plus partition/restart/revocation and
      resource-disposal parity across both platforms.
- [ ] Removal of migrated legacy loops and promotion of the shared owner. Neither is
      permitted before the gates above pass.

M3 - qualification

- [x] Deterministic inventory-bound policy evidence and a required final gate.
- [x] Uniform per-suite scenario/count/artifact manifest for every required suite.
- [x] Publication requires the qualification manifest and re-hashes the staged
      assets against it before upload.
- [ ] An executed release run and cross-suite compatibility validation; the
      aggregator and its refusal tests exist, but no tag has exercised them.
- [ ] Narrower dependency selection after the architectural isolation is itself
      tested. Conservative selection remains in force.

M4 - headless messaging

- [x] Android native transport and the private Windows WebView2 host with packaged
      crash, pairing and receipt scenarios.
- [ ] Production native Windows DataChannel adapter to replace the WebView2
      dependency.
- [ ] Packaged fault matrix, real-clock budgets and the 100-iteration receipt soak
      on those exact headless transports.

M5 - supported reusable core

- [x] Private facade with scoped capabilities, durable enqueue/idempotency, message
      snapshots, replay cursors, acknowledgments, diagnostics, bounded framing and
      received-text enumeration.
- [x] Trusted host grant binding over a host-owned stream pair (component only).
- [x] Private Windows named-pipe endpoint with OS access control and an executable
      allowlist (component only; no packaged consumer).
- [ ] Authenticated Android Binder endpoint and packaged consumers; the facade
      remains a private component until they exist.
- [x] Contact-wide connection start/stop intent with convergent semantics
      (component only; no per-device selection or workspace pairing).
- [x] Explicit convergent peer approval and revocation (component only).
- [x] Convergent inbound signed-invitation acceptance (component only).
- [x] Profile-level outbound invitation material (query, component only).
- [x] Owner-authorized runtime stop that closes the host stream (component only).
- [ ] Per-peer pairing documents, workspace relationships and their
      idempotency/retention semantics.
- [x] Experimental TypeScript client over the frame contract (component only; no
      packaging, CI conformance, Kotlin client or consumer).
- [x] Experimental Python client and Windows CLI over the host pipe, with a
      declared console entry point (component only; no published distribution).
- [ ] Versioned TypeScript/Kotlin SDKs, production CLI and the supported
      compatibility matrix.
- [ ] Mesh Chat messaging routed through the supported facade.
- [ ] Independent Windows and Android consumers built only from distribution
      artifacts and documentation.

Release and physical

- [ ] INV20 enforcement for exact source/artifact evidence (M3).
- [ ] Physical Windows/Android checklist: Wi-Fi/cellular switching, screen-off/Doze,
      real process death, Stop/lock and end-to-end receipts. Unavailable in the
      current environment (emulation and GitHub CI only); emulator results must not
      be relabeled as physical evidence.
