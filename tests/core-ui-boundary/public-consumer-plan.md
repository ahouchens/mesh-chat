# Independent public consumer qualification proposal

The latest completed qualification is `f0c06c82dbf4003a732d8301f9d1d3facc955fb2`
(tree `7b5fec7599cfda3fd44884ffbc9ee88b1d063a31`), full manual run
[43115277007](https://github.com/ahouchens/mesh-chat/actions/runs/43115277007).
The reviewed bounded HTTP 503 read retry is integrated. Fresh local checks pass:
SDK staging/upgrade, strict policy types, **5,622 policy cases**, **1,838 Python
UI + 12 rendered cases**, **nine Windows boundary cases**, and **six source-carrier
setup cases**, with zero skips. Policy and Python UI inventories match CI exactly;
all 28 lifecycle composition controls remain. Broader general service evidence
remains historical at `67a5210`.

The upstream DNS hold cleared when Canonical reported operational at 17:19:50 UTC
on November 11. The candidate was pushed normally to the shared feature branch.
**Ten CI jobs pass, three fail, none skip.** Independently verified artifacts cover
the policy/UI cases above, Windows packaged/public-SDK pairing and lifecycle,
Android **56 emulator + 83 JVM cases and 17 artifact hashes**, browser layout
**72 cases**, and both Linux and Windows direct **25 transport + 10 recovery +
12 setup** cases. The optional APT hardening remains unmerged.

Native initialization advances beyond the earlier artifact-download failure;
this does not prove a retry occurred. Android reaches `turn_tcp_authenticated_receipts`
and rejects `kernel_socket_correlation/ambiguous_owned_matches`. Its kernel helper
finds more than one app-owned socket row matching the TURN endpoint. The current
predicate does not inspect TCP state or bind an individual socket to the selected
ICE transport. Retained reports contain no socket rows, so concurrent established
connections, lingering states and duplicate rows remain unresolved possibilities.
Windows subsequently fails at `receipt_inbound_wait` with `scenario_deadline`.
Both native jobs and the aggregate gate fail; earlier scenario markers do not
replace full authenticated native acceptance.

The next bounded candidate adds privacy-safe, fixed-enum TCP match-state
diagnostics while preserving socket selection, ambiguity rejection, deadlines,
faults and all acceptance requirements. No unconditional discriminator is yet
justified. Bootstrap helper retirement and later roadmap promotion remain gated
on independently validated full native qualification.

The preceding candidate integrated reviewed artifact-read correction `503b18e`.
An exact HTTP 503 at inventory, archive API or signed-blob open may retry at most
twice, using the existing three-second cadence within the original wait deadline.
Each open retains a ten-second maximum clipped to remaining time, including the
redirect. Reads and artifact verification completed at or after the deadline
cannot admit setup. Retry eligibility is private and tied to the exact exception;
optional diagnostic observers cannot drive behavior. Uploads, other HTTP errors,
identity checks, cryptographic validation and native product behavior are unchanged.
Every retry obtains a fresh same-run inventory/archive response, and the repository
token is never forwarded to the signed blob request.

The focused artifact module passes **130 cases**, retaining all 120 prior cases
and adding ten retry/deadline controls. The original code fails the deterministic
single-503-then-success regression. At that checkpoint combined qualification was pending;
the full native gate remains unmet. This correction tolerates a transient read
failure; it cannot repair a persistent provider limit or upstream DNS outage.
The optional APT hardening remained outside that candidate. Its full CI run
waited for recovery of the upstream package infrastructure.

The preceding completed qualification is `11213ee5dde971ad7cacfdee153793fab6ff519b`
(tree `72bc64f7ac50841c334d64672c80cc453508962e`), full manual run
[43050419628](https://github.com/ahouchens/mesh-chat/actions/runs/43050419628).
All fresh scoped local checks pass: SDK staging/upgrade, strict policy types,
**5,612 policy cases**, **1,828 Python UI + 12 rendered cases**, **nine Windows
boundary cases**, and **six source-carrier setup cases**, with zero skips.
Policy and Python UI inventories match CI exactly; all 28 lifecycle composition
controls remain. The broader service result remains historical at `67a5210`.

Eight CI jobs pass. Retained artifacts independently verify Windows direct
**25 transport + 10 recovery + 12 setup** cases, Android **56 emulator + 83 JVM
cases and 17 artifact hashes**, and the policy/UI checks above. Windows installed
public-SDK pairing now passes, including two authenticated receipts, shared SDK
session lifetime, pending-message/key preservation across owner reopen and clean
host exits. This pass does not establish a cause or repair of the prior timeout.

Five jobs fail. Linux direct and browser layout again fail Ubuntu package DNS
before their required tests. Canonical's [official status feed](https://status.canonical.com/rss)
reports a DNS major outage from 14:26 UTC on November 11, before these failures;
the [runner incident](https://github.com/actions/runner-images/issues/15296)
corroborates matching failures elsewhere. This is consistent with an upstream
outage, without proving the runners' exact failing DNS hop. Optional APT
fail-fast hardening `b1dc7ee` is reviewed separately and held out of integration;
it cannot restore DNS or replace required package and font installation.

Android native initialization fails at `initialize_key_wait`: the signed GitHub
artifact blob download returns **HTTP 503**. The 48-second native step is below
the original 900-second key-wait ceiling. The new diagnostic projection exposes
`blob_request/http_rejected/503`; the current read path aborts immediately.
Windows subsequently retires at `wait_answer/tick/phase_timeout`. Neither role
reaches TURN/TCP, and the aggregate gate fails. A separate lead artifact download
also returned 503, then succeeded on one later read; its precise cause is not
assumed to match Android's failure.

The correction proposed at that checkpoint retried selected transient read failures within
the existing deadline, with unchanged uploads and immutable artifact validation.
It required independent review and fresh qualification. Full native acceptance,
bootstrap helper retirement and later roadmap promotion remained pending. A new
full run also had to wait for recovery of the upstream package infrastructure.

The preceding candidate integrated reviewed component `f8e4e9f`: at most five
public pairing/diagnostics observations during invitation wait, scheduled at
0, 1, 5, 20 and 90 seconds. A single-flight observer leaves the original snapshot
predicate, 100-millisecond polling and 240-second work deadline intact. Each
sample has a two-second request budget and preserves a work-deadline reserve;
stopping the wait discards late results and prevents further diagnostic reads.
Selected fields exclude handles, codes, addresses and raw errors. Actor state
is current and unassociated; it is not a pairing-specific first-cause history.

The focused module has **419 passing cases**, with no failures or skips.
Regression controls cover stalled observations, late completion, earlier state
surviving later retirement, strict fixed offsets and real bytes output from the
installed checker. Fresh combined local qualification and full native CI remain
pending. The Linux package DNS failures warrant fresh runners without a mirror
override. This component adds evidence; it does not establish a pairing repair.
Bootstrap helper retirement remains on hold until the full native gate passes.

The preceding completed qualification is `bc26ec45b9e6fc99c4b1c41052bf48e0bb2b6128`
(tree `5f69bf4b02298e9c26ea358ebb46d4ea94852fd7`), full manual run
[43040952044](https://github.com/ahouchens/mesh-chat/actions/runs/43040952044).
Fresh scoped local checks pass: SDK staging/upgrade, strict policy types,
**5,596 policy cases**, **1,828 Python UI + 12 rendered cases**, **nine Windows
boundary cases**, and **six source-carrier setup cases**, all with zero skips.
All 28 lifecycle composition controls remain. Policy and Python UI inventories
match CI exactly. The broader 6,811-pass/49-skip service result remains historical
evidence at `67a5210`; it was not rerun or relabeled for this diagnostic-only delta.
An initial local rendered-UI startup was blocked by sandbox filesystem access;
its report is retained separately and the same-source boundary rerun passes.

Seven CI jobs pass. Independently retained evidence includes Windows direct
**25 transport + 10 recovery + 12 setup** cases, Android **56 emulator + 83 JVM
cases and 17 distribution/binary hashes**, the policy/UI slices above, and nine
Windows boundary cases plus normal installed public-SDK bootstrap with DPAPI/EFS.
The recurring Windows `address_loss` case passes in CI and in one separate local
native reproduction using the exact CI-built dispatcher. That single local pass
and this CI pass do not establish a repair of the intermittent failure.

Four jobs fail and one is skipped. Linux direct and browser layout fail Ubuntu
package downloads with DNS resolution errors for `azure.archive.ubuntu.com`,
before their required transport/layout tests run. APT already attempted multiple
Ubuntu endpoints; no repository mirror override, signature failure or product
cause is established. Windows desktop fails public pairing at `invitation_wait`
after the original 240-second work deadline. Its final probe sees both pairing
sessions retired with unexpired leases; cached earlier snapshots and current
stopped/ineligible actor state cannot recover the preceding failure reason.
The Reticulum interface warning describes a separate path and is not evidence
of the cause of native mailbox/WebRTC pairing failure. Later receipts, shared
host lifetime and clean exits are not qualified by this run.

The native cross-platform job is skipped because the Windows desktop prerequisite
failed; neither initial-key nor TURN/TCP diagnostics execute. The aggregate gate
fails. The next bounded change records earlier public pairing/connection states
without delaying invitation polling or changing the work deadline, acceptance,
network policy or SDK contract. Helper retirement and later roadmap promotion
remain deferred until independently verified full native qualification.

Previous evidence: `67a5210` passes all fresh local gates (6,811 service passes,
49 unchanged optional/platform skips; 5,577 policy; 1,824 Python UI + 12 rendered;
nine Windows boundary). [Full run 42973285262](https://github.com/ahouchens/mesh-chat/actions/runs/42973285262)
fails Windows `address_loss` queued delivery after connection recovery and native
startup. Windows stops retrieving the Android key before the configured wait
expires; Android later exhausts its wait for the first Windows offer. No TURN/TCP
case runs. Receiver-only recovery evidence and omitted initial-key transport
details prevent root-cause attribution. The next bounded diagnostic corrections
do not establish native, helper-retirement or public cross-platform acceptance.

The reviewed diagnostic components are now integrated: `8a4c4ae` projects
the existing bounded artifact-transport failure details at `initialize_key_wait`,
and `94b5d05` adds failure-only snapshots of both recovery peers. The snapshots
include at most eight workspace-event delivery rows with capped attempts and
due/future/terminal scheduling, plus a 16-entry trace with explicit truncation.
Status and acceptance outcomes describe literal handler returns; they do not
claim new message materialization. The original 45-second delivery wait, native
deadlines, retries and acceptance criteria are unchanged. The already-built
Windows dispatcher is retained for one day in a separate source-named CI artifact.

Component evidence verifies **734 controller cases**, including root reproduction
of three missing-projection failures before the correction and four passes after
it; D's **45 focused diagnostic cases and all six source-carrier setup cases**
also pass. There are exactly 19 new cases relative to `67a5210`. Fresh combined
SDK/type, full required policy/UI, Windows boundary and six source-carrier checks
are pending. The broader 6,811-pass/49-skip service result remains prior-source
evidence at `67a5210`; it is not rerun or relabeled for this six-file diagnostic
delta. Full native CI qualification remains required before helper retirement.

Prior evidence: `ce96840` passes fresh local gates and all non-native CI jobs
in [run 42961670166](https://github.com/ahouchens/mesh-chat/actions/runs/42961670166),
including both previously failing Windows setup cases. Android native fails
with `ValueError` before the TURN/TCP negative control; Windows reaches the
same-phase deadline. Exact inner cause remains undiagnosed. No full native,
helper-retirement, separate-caller/process or media acceptance follows. See the
qualification ledger for exact counts and retained historical failures.

Reviewed diagnostic commit `6af9e81` adds fixed, exception-bound labels to
the existing kernel-path constructor and receipt checks. Socket correlation
distinguishes no owned match from ambiguous owned matches without exposing
endpoints, PIDs or inodes. Observer construction is optional, cleanup replacement
cannot inherit the original error's label, and all acceptance criteria and
deadlines remain unchanged. Independent source/artifact review verifies **805
focused passes**, retaining 776 prior cases and adding 29; the new module is
included in the fast boundary gate. This is diagnostic instrumentation, not a
repair of the still-unidentified CI cause. Fresh local gates later pass at
`67a5210`; full CI fails earlier in initialization as recorded above.

Status: the original proposal below is partly implemented. Public pairing
intents, normal app-owned hosts and independent distribution inputs exist.
Checkpoint `902b12d` independently verifies installed Windows bootstrap, public
pairing and two authenticated receipts; its full run `42796005344` failed native
Android root preflight. The later `1b3a2be` run `42802755780` passes bootstrap but
fails installed public pairing, with its original work failure masked by final
cleanup failure. Native interoperability was skipped. Neither run is aggregate
Windows–Android qualification. The private topology controller remains a
separate transport test.

The installed Windows lifetime slice passed at `902b12d`: two SDK sessions in one Node
application, session close/reattach, concurrent-owner refusal with positive child
exit, and original pending-message/key preservation across trusted owner
stop/reopen. It does not prove separate consumer-process exit,
caller/cross-user/multi-app isolation, isolated-helper retirement or delivery of
that pending message after restart.
Successful Android credential UI, independent cross-platform receipts, native
helper cleanup, media coexistence and the supported release matrix remain open.

The later `c0b3cf7` full run `42810308484` again passes installed Windows
bootstrap, public pairing, two receipts and the same-application lifetime slice
described above. Native Windows fails receiving the approval acknowledgment;
Android reaches a direct-receipt scenario deadline. Full cross-platform native
acceptance remains unfulfilled; these separate failures do not identify a common
cause or explain the earlier installed invitation failure. The next diagnostic
change preserves transport failure while selecting only safe origin metadata.

Checkpoint `5e6d0da` full repeat `42824231976` passes the same installed Windows
public pairing/receipt/lifetime slice plus the Android and other component suites.
Both actual native peers fail later at a direct-case native lease-retirement
deadline. The controller requests a compatibility close which deliberately returns
managed for an adopted supervisor-owned carrier. The reviewed follow-up adds
private owner retirement with correlated cleanup acknowledgment and later-case
admission, plus signed cold-start consent exchange after the final manual zero
gate. The public API, managed-close guard and strict zero-lease acceptance remain
unchanged. Combined qualification is pending; no full cross-platform or
isolated-helper acceptance follows from the component tests.

Checkpoint `ccd3b51` has passing exact-source local SDK/types, 5,068 required
policy cases, 1,482 Python UI + 12 rendered cases, nine Windows boundary cases,
and broader local service execution (6,298 pass/49 optional-platform skips).
First full run `42857623266` fails Windows public-SDK invitation waiting and skips
native interoperability; its first cause remains unresolved. The unchanged full
retry `42862760087` passes Windows public pairing/lifetime and all non-native
gates but fails native Android under TURN TCP negative-control phase with an
unclassified `ValueError`; Windows later reports TURN TLS wait-answer timeout.
No full native acceptance, isolated-helper completion, separate-caller/process,
physical or media qualification is inferred. Failure-only diagnostics `b7f323e`
are reviewed and integrated, with 739 focused component cases passing (667 prior
cases preserved plus 72 new) and three meaningful original-source failures.
An original two-controller reproduction demonstrates measurement/cleanup
overtaking under scripted native boundaries; it does not identify the CI cause.
The private prepare/completion/commit producer `3172d02` and consumer `b3751ae`
are reviewed and integrated at `6459710`, with 445 producer component cases and
998 consumer cases passing. Native callbacks and controller/native boundaries
are modeled in those focused suites. Reviewed composition `ce4b9c4` additionally
passes 28 actual Windows localhost host controls for both role labels, preserving
all 18 prior cases. It covers retained native cleanup proof across late commit;
approval/Reticulum remain modeled. It does not establish Android/JNI, full
controller/path-case or authenticated message receipts. Combined local gates
pass at `30c9e4d`. Full run `42886878229` again passes installed Windows public
pairing, two receipts and the same-application lifetime slice, together with all
other non-native families. Native Android fails in initialization with `internal`;
Windows later reports `RendezvousUnavailable`. The exact Android operation and
cause are unclassified. Full cross-platform and isolated-helper acceptance remain
open; the private controller diagnostics do not extend public SDK support.
Reviewed failure-only initialization labels `7058909` pass 1,093 focused
component cases without changing public Core/SDK behavior. These labels name
the controller call site, not an implicit capability check or inner cause;
Exact-source `379e38a` local gates pass
5,406 policy cases, 1,752 Python UI + 12 rendered cases and nine Windows
boundary cases. Full run `42899863270` passes all non-native families but
fails native initialization: Android `initialize_ice_servers/internal`, Windows
`initialize_key_wait/RendezvousUnavailable`. The inner capability-versus-ICE
operation and cause remain unknown. No full native acceptance or expansion of
public SDK support follows. Private same-exchange diagnostics are integrated
from producer `c6a31bb`/`6246303` and consumer `364eb313`, with inventory
registration `a996252`. Focused evidence passes 285 producer and 903 consumer
Python cases, 24 JVM cases and 239 inventory cases. Four compiled Android
local Binder/Chaquopy controls raise the required optimized inventory to 56.
At `fed31cc`, all four pass within 54 verified Android case reports and 83 JVM
passes, but full run `42926669465` fails: the separately packaged runtime host
omits the private observation-state source and cannot compile. Independent
consumer execution and cross-platform native interoperability do not run.
Windows direct recovery separately fails its address-loss delivery wait
(nine other recovery cases pass); its cause is unestablished. The narrow
packaging correction `e552dd9` has isolated compiler RED/GREEN and 32 existing
boundary passes, independent review approval and integration at `10d08c3`.
Full run `42932168650` at `6b3fb8e` confirms the correction with 56 Android
cases, 83 JVM cases and 17 distribution hashes. Native Android then fails the
actual ICE broker open with a name-resolution observation; Windows waits for
its unpublished partner key. Separately, Windows direct recovery passes all ten
cases but two setup cases time out awaiting the joining workspace's general
channel. No full native acceptance follows. Prior full local results retain
their `fed31cc` source; targeted `6b3fb8e` compile and 410 boundary cases pass.

The subsequent reviewed corrective batch `4523f43` repairs payload-blind workspace
readiness and retains ordinary-transport ratchet enforcement across a bootstrap
transition. Semantic regressions and 94 focused cases pass; the exact prior
native failure still needs fresh CI. `5988882` adds a bounded private Android
postfailure network snapshot with 928 focused Python cases and a focused source
compile. It provides diagnostic context only; the underlying guest DNS cause
remains unresolved. Fresh combined local and full native qualification are
pending. Public SDK behavior and authority are unchanged.

Candidate `9708104` then ran the full service suite: 6,780 pass, two benchmark
double interface failures, and the same 49 platform/optional skips. The reviewed
three-line `6c89920` benchmark adapter correction passes the affected three-case
selection. The failed run is preserved; fresh combined gates remain pending.
Only fixed operation/stage/category/cause enums may accompany the same
correlated internal failure, under the original local caller and initialized
publication. Public Core responses, SDK surface, grants, call counts and
deadlines remain unchanged. This does not establish the CI failure cause.
No public API/grant, timeout, authority or negative-control relaxation is assigned.

Checkpoint `36466e0` full run `42843336931` again verifies the installed Windows
public-SDK pairing, receipt and same-caller lifetime slice and all required
Android component suites. General verification fails two loopback composition
fixture setups; native interoperability is skipped. A test-only serialization
correction `c4e6036` is reviewed with 18 local controls passing; fresh full
qualification is pending. These results do not expand the public-consumer or
cross-platform acceptance scope.

## Gaps observed when this proposal was written

The following observations motivated the implementation; they are historical,
not a statement that the implemented Windows host and public pairing are absent.

- The TypeScript archive and Kotlin AAR contain thin protocol clients, not an
  independently usable app-owned runtime host. The normal frozen Windows
  `--native-webrtc` mode requires a trusted initializer to provide a vault key;
  the sidecar can expose an image-authenticated pipe when its launcher asks.
- The Android example is an external UID bound to `core-api-host`. That CI host
  seeds a profile, workspace and fabricated approved contact. These are useful
  packaging/denial checks, but cannot qualify independent pairing and receipts.
- Native offer/answer admission currently exists only behind
  `QualificationControl`, with a qualification profile marker and private
  commands. The existing public signed-invitation operations do not admit that
  production native negotiation actor. `connection.start` starts reconnect for
  an existing relationship; it does not replace onboarding.
- The production Android runtime library currently has Tauri project
  dependencies and service Python source paths. The independent client build
  cannot use that project dependency as a versioned runtime distribution.

## A: public pairing intent, not a native command port

Add a bounded public pairing intent family, backed by C's existing actor:

| Operation | Request | Result and authority |
| --- | --- | --- |
| `peer.pairing_begin` | `profile`, `role: offer|answer`, optional `pairing_code` (answer only, 1..2048 UTF-8 bytes), optional `allow_direct_ip_disclosure` (boolean, default false); required caller envelope idempotency key | `profile`, caller/profile-scoped opaque `pairing` handle, `state`, `expires_at`, nullable `pairing_code`; requires current approve permission |
| `peer.pairing_query` | `profile`, `pairing` | Same selected projection, including shareable code; current approve permission plus original caller/profile binding |
| `peer.pairing_cancel` | `profile`, `pairing`; required explicit caller envelope idempotency key | Same projection; approve permission; durable cancellation of this exact intent |

Use actual actor states: reserved, offer_ready, awaiting_approval, transferred,
retiring, retired. Offer codes are shareable admission material, not SDP. An
answer must supply a code; an offer must omit it. A transferred intent remains
transferred on cancellation and cannot reclaim the adopted carrier.

Derive the actor operation UUID with the existing keyed-action namespace from
the host-derived caller, profile and caller key; never accept an internal
operation UUID or caller identity in JSON. Bind a live authorization callback
to the exact service incarnation and profile identity. Recheck authority on
begin replay, query, cancel and each asynchronous effect. Preserve the existing
actor's resync requirement after an interrupted runtime; do not invent an
automatic fresh intent. Advertise only when the concrete native actor is bound.
Bind cancellation's own caller key and input digest durably before returning
success, and recheck current authority before replay. A cancellation key cannot
be reused for another pairing target or the begin action. Replaying an accepted
cancellation must not cancel a replacement intent or an adopted carrier.
Document the actual 32-intent bound, one active onboarding intent, 300-second
maximum expiry and byte limit. SDKs must require the advertised feature and
limits, with no retries or replacement keys.

Existing public `application.snapshot`, `peer.approve` and `contact.invitation`
can supply explicit contact decisions for this first owner-app consumer. No
new public raw native, SDP, signaling HTTP, reducer-event, vault-key or grant
operation is needed. Disclosure consent remains explicit. Later reconnect uses
the existing public connection intent and consent semantics.

A file boundary: `contracts/core-api/operations-v1.json`,
`contracts/core-api/request-v1.schema.json`, `service/src/mesh_chat/core_api/requests.py`,
`session.py`, `views.py`, `pairing.py`, `service_pairing.py`, `composition.py`,
the relevant keyed-action/capability implementation, and thin helpers/types in
`sdk/typescript/src/` and `sdk/kotlin/src/main/java/com/meshchat/runtime/core/`.
A owns producer contract/authority/idempotency tests. This is an additive
experimental API feature, not an API stability declaration.

## C: ordinary app-owned bootstrap and host distribution

Windows: add a documented normal packaged host launch mode that creates/reopens
one app-owned data directory and retrieves its vault key through Windows
protection inside the runtime. The trusted launcher provides the owned directory,
unique pipe and exact client image outside public request JSON. The runtime
returns only pipe/startup status, never keys. Admit that app's owner operations
without exposing private native controls to its public SDK session. Start empty;
the app's explicit `profile.create` request creates the identity. Reuse the
existing frozen native host, same-user image authentication and exact shutdown
ownership. Do not add an unprotected network daemon or attach to the user's
installed Mesh Chat profile. Proposed C paths: a new production app-owned host
composition module under `service/src/mesh_chat/`, its `__main__.py` launch route,
and existing platform key/provider glue. Coordinate the public endpoint binding
with A's `core_api/sidecar_host.py` / `pipe_endpoint.py` ownership.

Android: provide a documented trusted host bootstrap API, for example
`MeshCoreRuntime.start(context)`, which owns that application's private directory,
Keystore wrapping and native host initialization. The app then uses the installed
Kotlin SDK against its own real Binder service/UID. Keep external packages at
their existing consumer grants. The API must not accept owner UID, grant, raw
vault key or private command in JSON. A separate versioned runtime-host AAR/POM
should package the existing production host sources, Python assets, ABI inputs
and declared dependencies without a Tauri project dependency. A small new Gradle
host module can reuse the production files; no replacement transport or service
implementation. Proposed C paths: new `MeshCoreRuntime.kt` and runtime-host module
under `plugins/tauri-plugin-mesh-runtime/android/`; existing
`NativeWebRtcBridge.kt`, `MeshCoreApiService.kt`, `mobile_bridge.py` and platform
key/provider code only as needed. C retains native-pairing/custody tests and
proves normal shutdown acknowledges actual native/store retirement.

The host bootstrap is part of the installing application's trust boundary,
separate from the thin SDK. It must work through documented distribution inputs;
no qualification marker, Python reflection, seed fixture or test dispatcher is
available to the consumer app.

## D: independent apps and source-bound qualification

After the reviewed A/C contracts are available, build both consumer applications
outside the checkout with access only to versioned SDK/runtime artifacts and
public documentation. The TypeScript app launches its normal frozen host; the
Kotlin app initializes its installed runtime-host library and binds normally.
Create fresh identities, disable alternate LAN/discovery paths through supported
settings, explicitly exchange offer code and consent decisions, and enqueue
messages in both directions with caller keys. Query actual authenticated receipt
state and verify one durable message per logical identity. Repeat with swapped
platform initiators, then add real restart/reopen, caller isolation and event
recovery cases as separate declared inventories.

D owns NEW `examples/typescript-independent-consumer/` and
`examples/android-independent-consumer/`, consumer packaging/orchestration scripts,
native workflow wiring and strict
source/artifact/run evidence. Test infrastructure can terminate processes or
impair networking externally, but cannot initialize product internals or supply
private authority. Retain installed SDK/runtime/APK hashes and actual case
identities. Missing supported bootstrap/pairing fails the required qualification;
component archive/import/Binder checks never stand in for receipt traffic.

Planned exact D files: `examples/typescript-independent-consumer/package.json`,
`consumer.mjs`, `README.md`; `examples/android-independent-consumer/settings.gradle.kts`,
`build.gradle.kts`, `gradle.properties`, `README.md`, `app/build.gradle.kts`,
`app/src/main/AndroidManifest.xml`,
`app/src/main/java/com/meshchat/core/independent/ConsumerApplication.kt`,
`app/src/androidTest/java/com/meshchat/core/independent/IndependentConsumerTest.kt`;
`scripts/stage_independent_core_consumers.py`,
`scripts/verify_independent_core_consumers.py`, and
`scripts/check_independent_core_consumers.py`. A retains the existing
TypeScript/Python consumer examples. Existing Android Binder consumer remains
unchanged as its separate cross-UID component inventory.

This first traffic batch does not close physical qualification, a supported
release/upgrade matrix, the full SC21–SC26 inventory, UI media or the separate
30-second impaired partition requirement.
