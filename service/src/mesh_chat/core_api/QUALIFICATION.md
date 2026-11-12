# Private packaged qualification control

The next candidate integrates three independently reviewed follow-ups:
`488f95c` gives the policy CI job fifteen minutes, `0577f58` adds bounded test-only
retirement failure observations, and `a686f9e` adds guarded archive-404 retries.
Artifact metadata is checked before archive download. Only an archive-open HTTP
404 for a valid artifact may retry; fresh inventories must retain its exact ID,
provenance, size and digest. The existing maximum of two retries is shared with
HTTP 503, with the same three-second cadence and original deadline. Inventory or
blob 404s, other statuses, uploads, changed or missing identity, and invalid
archives remain failures. Post-download digest, archive and producer checks remain
required, and the repository token is never forwarded to signed blob storage.

The archive/rendezvous focused pair passes **259 cases**, retaining all 218 prior
cases and adding 41 controls. Retirement observations pass **22 focused cases**,
retaining all 18 prior cases and adding four controls. Fresh combined local checks
and full native qualification remain pending. The prior local retirement failure
and TCP socket ambiguity are unresolved, and the remote cause of HTTP 404 is unknown.

The latest completed qualification is `97c32d5951fffa9f66161b17ae01c98484e22cab`
(tree `2ef51343ce32fe4aebd7a4950d849c2a20f524c6`), full diagnostic run
[43124732545](https://github.com/ahouchens/mesh-chat/actions/runs/43124732545).
GitHub records the run as **cancelled: eight successful jobs, four failed jobs,
one cancelled job, zero skipped jobs**. The policy job exceeded its ten-minute
limit during artifact upload and cleanup, after all **5,636 tests** and required
evidence validation passed. Its required gate correctly failed. The retained
annotation explicitly reports the ten-minute execution limit.

Independent artifact checks verify exact local/CI policy and Python UI inventories,
**1,852 Python UI + 12 rendered cases**, Windows packaged/public-SDK pairing and
lifecycle, Android **56 emulator + 83 JVM cases and 17 artifact hashes**, layout
**72 cases**, and Linux and Windows direct **25 transport + 10 recovery + 12 setup**
cases. These passing reports do not override the cancelled policy job or establish
full native acceptance. General service evidence remains historical at `67a5210`.

The first local policy attempt on this source failed one retirement-composition
case and its teardown (`native_webrtc_cleanup_pending`). The exact case then passed
in isolation; one unchanged full policy retry passed all 5,636 cases. The first
failure, both passing attempts and their hashes remain retained. Its cause is
unresolved; this is not clean local qualification or a demonstrated repair.

Native Windows failed at `turn_udp_native_lease_retirement/completion_receive`:
the GitHub archive endpoint returned **HTTP 404** before retirement commit. The
report also retains `cleanup_failed=true`. Android subsequently exhausted its wait
for the Windows TURN/TCP offer. The remote reason for HTTP 404 is unknown; eventual
consistency is not established. This run never reached TCP kernel correlation,
so the earlier ambiguous socket selection remains unresolved and the new labels
have not yet supplied the needed evidence.

Two follow-ups are independently reviewed: `488f95c` raises only the policy CI
job limit from ten to fifteen minutes; `0577f58` adds test-only, failure-only
retirement observations with fixed labels, nonblocking lock attempts, a bounded
loop responsiveness probe and a capped note. Its **22 focused cases** retain all
18 prior cases plus four diagnostic controls. Neither change repairs or explains
the original retirement failure. A separate bounded archive-404 correction is
being prepared with strict metadata preflight and unchanged post-download checks.
Helper retirement and later roadmap promotion remain on hold pending full native
acceptance and disposition of unresolved failures.

That source integrated reviewed diagnostic-only component `d6abde0`.
Ambiguous TURN/TCP or TURN/TLS own-process socket matches now carry two private,
fixed-enum labels: `tcp_state_summary` distinguishes one established plus other
states, multiple established, no established, or unclassifiable states;
`owned_inode_relation` distinguishes same versus distinct inode identities without
exposing those identities. The labels are accepted only together on the exact
ambiguous kernel-correlation failure. Endpoints, ports, socket rows, process IDs,
UIDs, inode values, raw exceptions and counts are never emitted.

Socket selection and ambiguity rejection are unchanged. The observation cannot
select a socket, alter a deadline, drive a retry or change fault injection. The
focused two-module run passes **89 cases**, retaining all **75 prior cases** and
adding **14 diagnostic controls**. Five focused pre-change regressions fail on
the absent labels while preserving the expected socket rejection. Independent
review approves diagnostic integration only. The diagnostic run above does not
provide socket-selection acceptance or establish a repair.

The preceding completed qualification is `f0c06c82dbf4003a732d8301f9d1d3facc955fb2`
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

Windows: launch the retained sidecar with sole flag
`--qualification-native-webrtc`. Use its existing private length-prefixed IPCv1
initialize envelope, with exact payload `profile_dir`, `vault_key` (base64),
`parent_pid`, `display_name` (literal `Mesh qualification`). The absolute profile
leaf must start `mesh-qualification-` under a controller-owned protected parent.
First boot requires a nonexistent leaf. After platform protection and successful
initialization, a local marker authenticates the path and a random nonce with
that vault key. Only the same marked path/key may reopen. An existing ordinary
vault, copied marker, wrong key or tampered marker fails before runtime startup.
Do not retain this key or marker in qualification artifacts.

Private commands are `qualification.inventory` with `{}` and
`qualification.path_evidence` with `{logical_session,expected_physical,sample_request}`. Replies
use the existing IPC `{type:"response",id,ok,result|error}` envelope. The latter
calls the production inspector with exact current resource fencing. These names
are absent from public Core, native commands and ordinary sidecar dispatch.

Android: actual host-UID instrumentation first calls
`NativeWebRtcBridge.attach(context)`, then directly imports the packaged
`mesh_chat.core_api.qualification_host` via Chaquopy. `android_initialize(raw)`
accepts exact JSON `{profile_dir,vault_key,display_name:"Mesh qualification",platform:"android"}`.
`android_control(raw)` accepts exact `{command,payload}` using the names above.
Both return JSON `{ok,result|error:{code}}`, check actual Binder calling UID
against process UID, and are outside all renderer/Core/mobile-command routes.
Initialization refuses an existing live runtime; shutdown through the normal
trusted host path before reopening. Control is fenced to the exact initialized
mobile instance. Ordinary host replacement cannot inherit qualification access.

Inspectors enforce their production 2-second sample deadline and 16KiB bound.
The controller generates a fresh 16-byte random `sample_request`, encoded as
exactly 32 lowercase hexadecimal characters, for each existing sampling call.
The private service forwards it to the native sampler and requires its exact
echo before accepting the observation or advancing the sequence. The native
coroutine or callback binds the challenge to that sampling invocation; neither
the service nor a wrapper may attach a new challenge or timestamp to cached data.
Missing or mismatched challenges and old private shapes fail closed.

The producer checks the original capture's age in its own monotonic clock
domain. Android encodes the original capture relative to its adapter's clock
origin. The controller treats `sampled_at_ms` as bounded opaque metadata, never
as a wall-clock timestamp or a tick count comparable to another device. It
requires the matching challenge, its own monotonic request-to-consumption span
of at most two seconds, the existing service elapsed bound and a 2000ms validity
window. Integer rounding must not extend the producer's deadline. These checks
bind freshness to the current invocation without synchronizing clocks or adding
another sampling call; they do not reinterpret internal WebRTC metric clocks.

Recheck service/profile/adapter/resource epoch
and sample sequence; discard after resource or epoch changes. Selected ICE alone
does not prove readiness or delivery. Restrict raw endpoint tuples to transient
controller memory/fault correlation; export only categories, availability,
hashes and truthful counters. Never export SDP, credentials, bearer documents,
vault keys or raw addresses. Unit admission tests are not packaged OS evidence.

The private v2 owner-retirement producer `3172d02` and controller `b3751ae`
are implemented and source-reviewed together at `6459710`. Reviewed composition
`ce4b9c4` passes 28 controls with actual Windows localhost native hosts for both
role labels, including late commit and raw closed delivery after mapping release.
Approval/Reticulum boundaries remain modeled. This is not Android/JNI, full
controller/path-case or packaged acceptance. Combined local qualification at
`30c9e4d` passes 5,311 policy cases, 1,657 Python UI + 12 rendered cases, nine
Windows boundary cases and all 28 composition controls. Full run `42886878229`
passes all non-native families but fails native initialization: Android reports
`PeerFailure/internal`, Windows later `RendezvousUnavailable`. The phase spans
several setup calls and the initial key exchange; the failing Android operation
and inner cause remain unidentified. No full native acceptance is established.
Reviewed controller diagnostics `7058909` now label ten existing initialization
call sites on failure. The original exception, calls, budgets and cleanup remain
unchanged; 1,093 focused component cases pass. Labels expose no payload or raw
exception text and do not identify the SDK's implicit capability request versus
the requested Core operation. Exact-source `379e38a` local gates pass
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
deadlines remain unchanged. This does not establish the CI failure cause. The
`qualification.retire_carrier` request has exactly `action`, `operation_id`,
`request_id`, `logical_session`, `expected_physical`,
`expected_service_incarnation` and `expected_adapter_epoch`. Action is exactly
`prepare` or `commit`; missing/unknown actions reject, with no legacy fallback
or wire abort. The pairing operation identifies this caller's existing
transferred case; request and epoch values compare against current trusted state
and do not confer authority. The request nonce is 32 lowercase hexadecimal
characters. Current synthetic-profile/key, caller, service, identity, host and
owner bindings are rechecked. Source/run verification remains in the trusted
controller launch; the profile marker does not attest a source SHA or run.

After all local measurements and successful fault cleanup, both peers prepare,
publish then receive their exact sealed case completion marker, and commit the
same immutable tuple and nonce. First preparation returns
`{request_id,state:"prepared"}` without disposing the current carrier. First
commit returns `pending`, even if normal failure cleanup has already completed.
Correlated inventory accepts exactly `{operation_id,request_id}` and returns the
ordinary inventory plus `carrier_retirement:{request_id,state}`. It may report
`prepared` before commit; postcommit polling accepts only `pending` or
`acknowledged`. Ordinary inventory `{}` remains unchanged.

Commit invokes normal supervisor retirement without persisting Stop, changing
consent, bypassing the managed-close guard or directly calling native disposal.
Failed cleanup retains the existing exact-resource retry behavior. Per-case
success requires matching acknowledgment in the same service/profile scope,
empty logical inventory and complete zero native lease counts. The retained
case records `owner_retirement_acknowledged:true`, not private request or resource
identifiers. Existing polling, deadlines and retry budgets remain unchanged.
Terminal cleanup uses the current scoped Core `connection.stop`, followed by the
same zero-accounting checks and normal host shutdown. Its desired-state reply
is not cleanup completion.

Preparation preserves current traffic and health inspection, permits normal
failure cleanup and rejects replacement admission. Only a fresh transferred
pairing context allocated by the current service is eligible. Retained proof
requires its exact owner's actual retirement, the trusted native `closed` edge,
successful cleanup completion and fresh bound clearance. Capture the raw physical
closed edge before logical mapping lookup can discard it. This uses the existing
trusted in-process callback and nonreused fresh identity, not an independently
tagged JNI receipt; restored resources are excluded. The sole permitted authority
successor changes manual-carrier authorization from true to false after an
attested exact close start. Other active-ticket authority/lifecycle changes
invalidate irreversibly. An already-completed historical receipt grants no
authority over a later generation and cannot satisfy a different request nonce.

Markers are exactly `{completed:true}` at
`case_complete_<scenario>_<initiator>` for the six fixed full cases or the first
three quick cases. Existing source/run/role binding and deadlines remain. Full
uploads including reports become 17 Windows/15 Android; quick becomes eight each,
within the unchanged run inventory cap of 100. Any failure ends the case and uses
existing owned-host teardown; forced termination is never positive retirement
proof. The frozen contract SHA-256 is
`6ca4ca2ccd4807d66e38396258f0361f8721ac0cec255ed8a73b7516dbbd3fed`.

The cold-start setup follow-up is implemented and source-reviewed. After the final manual
acknowledgment/zero gate, each peer performs the existing local auto-reconnect
consent update, publishes its returned signed capabilities in the sealed
`reconnect_capabilities` setup phase, then receives and imports the peer's document.
The phase accepts exactly `{capabilities:<nonempty string>}`, at most 16KiB of
UTF-8 text and within the existing 48KiB canonical plaintext bound. Other setup
schemas, envelope provenance, expiration and one-shot rules remain unchanged.
Both peers publish before receiving. Each must persist the import through the
existing signature/recipient/expected-peer validation and check the same contact,
profile and device association plus mutual consent before its own first crash.
Publishing alone is insufficient. Capability plaintext contains credentials and
must not appear in retained reports or logs. Manual cases keep consent disabled;
the cold-start workload, deadlines and receipt requirements remain unchanged.

Before case-completion markers, cold-start setup alone added one setup artifact
per role (Windows ten setup artifacts plus one report, Android eight plus one;
quick four plus one each). With the six full/three quick completion markers,
the current totals are the 17/15 full and eight/eight quick counts above.
The run inventory bound remains 100. GitHub's
[artifact platform release](https://github.blog/changelog/2024-02-12-github-actions-artifacts-v4-is-now-generally-available/)
and [current upload action documentation](https://github.com/actions/upload-artifact#number-of-artifacts)
document 500 artifacts per job. The toolkit README's conflicting ten-artifact
wording is retained in the audit; lock-verified SDK 6.3.1 upload/client/config
source showed no ten-artifact guard. No SDK or workflow update is required.

The `902b12d` full qualification run `42796005344` executed all 18 native-path
JVM controls (71 JVM cases overall), all 52 required Android emulator cases and
the installed Windows platform suites successfully. Its cross-platform native
Android role failed earlier at checked `adb root` preflight; the original cause
is unknown because command output was not retained. These passing component/
platform results do not qualify the full Windows–Android sample/receipt matrix.

The later `1b3a2be` full run `42802755780` passes 4,563 policy cases,
1,130 Python UI plus 12 rendered cases, nine Windows boundary cases, installed
Windows bootstrap, 52 Android emulator and 71 JVM cases, and all controlled
direct suites. Installed Windows public pairing fails; final cleanup masks the
original work failure. Native interop is skipped, so no current pairing,
shared-host lifetime or Windows–Android acceptance is inferred from this run.
The earlier Windows lifetime pass remains bound to `902b12d`.

The later `c0b3cf7` full run `42810308484` passes 4,651 policy cases,
1,130 Python UI plus 12 rendered cases, nine Windows boundary cases, installed
Windows bootstrap/public pairing/two receipts and same-app lifetime checks,
52 Android emulator and 71 JVM cases, and all controlled direct suites. Native
Windows fails at `rendezvous_receive` / `approval_acknowledgment` with
`RendezvousUnavailable`; Android fails during `direct_authenticated_receipts`
with `PeerFailure` / `scenario_deadline`. Windows reached initial local readiness
validation, but that is not retained scenario-specific sample/receipt acceptance.
The exact transport branch is unrecorded. Full native qualification and isolated
helper retirement remain unfulfilled; no timeout/retry/authority relaxation is
authorized by these passing component/platform checks.

Checkpoint `5e6d0da` full repeat `42824231976` passes all non-native suites,
including 4,760 policy, 1,239 Python UI plus 12 rendered cases, installed Windows
pairing/lifetime, 52 Android emulator and 71 JVM cases. Both actual native roles
fail at `direct_native_lease_retirement` with a scenario deadline. The compatibility
native close is deliberately non-authoritative for adopted supervisor-owned
carriers (`state:managed`); the controller ignores that reply before waiting for
zero leases. Existing protected owner Stop has durable later-admission consequences.
The guard, exact-resource custody and strict empty accounting must remain intact;
no full native or isolated-helper qualification is established by this checkpoint.

Checkpoint `ccd3b51` has passing exact-source local SDK/types, 5,068 required
policy cases, 1,482 Python UI + 12 rendered cases, nine Windows boundary cases,
and broader local service execution (6,298 pass/49 optional-platform skips).
First full run `42857623266` fails Windows public-SDK invitation waiting and skips
native interoperability; its first cause remains unresolved. The unchanged full
retry `42862760087` passes Windows public pairing/lifetime and all non-native
gates but fails native Android under TURN TCP negative-control phase with an
unclassified `ValueError`; Windows later reports TURN TLS wait-answer timeout.
No full native acceptance, isolated-helper completion, separate-caller/process,
physical or media qualification is inferred. Coordination/diagnostic follow-up
is under review; no timeout, authority or negative-control relaxation is assigned.

Checkpoint `36466e0` full run `42843336931` verifies 5,066 policy cases,
1,482 Python UI plus 12 rendered cases and the Windows/Android platform suites.
General verification fails two composition fixture setups before their test
bodies; native interoperability is skipped. The fixture bypasses production
serialization during consent/control setup. Reviewed fixture-only correction
`c4e6036` closes that finding; 18 local controls pass, including two deterministic
signed-capability races. Fresh full qualification is pending.
This run supplies no packaged owner-retirement or cold-start native acceptance.
