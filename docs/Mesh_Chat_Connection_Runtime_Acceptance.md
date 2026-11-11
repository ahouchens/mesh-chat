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

The next candidate integrates reviewed diagnostic-only component `d6abde0`.
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
review approves diagnostic integration only. Fresh combined local qualification
and full native evidence remain pending; no socket-selection repair is claimed.

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

The preceding completed qualification is `67a521053772ccdac437cf6ae4e771a79eafea4e`
(tree `ac0447e24597d15102f862aa008c63ae055aa6f1`), full manual run
[42973285262](https://github.com/ahouchens/mesh-chat/actions/runs/42973285262).
All fresh local gates pass: SDK staging/upgrade, strict policy types, **6,811
service cases with the same 49 optional/platform skips**, **5,577 policy cases**,
**1,824 Python UI + 12 rendered cases**, and **nine Windows boundary cases**.
Required suites have zero skips. All 28 composition controls remain, and all
baseline cases are retained with exactly 59 additions since `fed31cc` (29 since
`ce96840`). CI policy and Python UI inventories exactly match local execution.

Nine CI jobs pass. Independently verified components include the policy/UI and
packaged Windows public-SDK slices above, **56 Android emulator cases, 83 JVM
cases, 17 distribution/binary hashes**, Linux direct **25 transport + 10 recovery
+ 12 setup**, and 72 zero-overflow layout report cases. Screenshots were not
visually reviewed. Windows direct recovery has **nine passes and one failure**:
`address_loss` recovers the connection but the queued workspace message remains
absent at the receiver through the existing 45-second delivery wait. The same
case failed at `fed31cc` and passed at `6b3fb8e` and `ce96840`; affected recovery,
network and workspace source blobs match the last passing candidate. The report
contains receiver state, not sender outbox/send evidence, so no cause or repair
is inferred. Windows fabric/setup do not run after this failure.

Native Windows fails at `initialize_key_wait` with `RendezvousUnavailable`.
Its entire controller step lasts 68 seconds, below the configured 900-second
initial key wait; normal key-wait deadline exhaustion is ruled out. Artifact
metadata records Windows key publication at 06:58:40 UTC and Android publication
at 06:59:37 UTC. No key contents were downloaded. The existing reporter omits
transport failure details at this initialization site. Android subsequently
reports `partner_wait/deadline_exhausted` while awaiting Windows's first direct
offer. Neither peer reaches TURN/TCP, so the earlier `ce96840` failure remains
unclassified and the new path diagnostic is not native-qualified.

The next bounded changes cover initial-key diagnostic projection and both-peer
workspace-event failure evidence. A separate one-day retained Windows dispatcher
artifact will enable scoped native reproduction without rebuilding Rust locally.
These preserve existing retries, deadlines and acceptance checks. Bootstrap
helper retirement and later roadmap implementation remain deferred pending full
native qualification. The aggregate gate is failed; historical runs remain below.

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

The preceding completed qualification is `ce96840ee8f138190e1a1048e5deeb5997edee88`
(tree `c8a272e1b3fec9f24741ca3542093284410c018e`), full manual run
[42961670166](https://github.com/ahouchens/mesh-chat/actions/runs/42961670166).
Fresh local SDK staging/upgrade and strict policy types pass. The full local
service suite has **6,782 passes, 49 unchanged optional/platform skips**, and
zero failures/errors; all 28 composition controls and all 6,801 baseline cases
remain with exactly 30 new cases. Required local gates pass **5,548 policy**,
**1,795 Python UI + 12 rendered**, and **nine Windows boundary** cases, with
zero required skips. CI policy and Python UI inventories exactly match local.

All ten non-native CI jobs pass. Independently validated evidence includes
**56 Android emulator cases, 83 JVM cases and 17 distribution/binary hashes**,
packaged Windows and its installed public-SDK lifetime slice, and both Linux
and Windows direct **25 transport + 10 recovery + 12 setup** cases. The two
previous Windows setup failures now pass. All 72 layout report cases have zero
overflow; screenshots were not visually reviewed.

Both native roles and the required aggregate fail. Android reports `ValueError`
at `turn_tcp_authenticated_receipts`; Windows reports `scenario_deadline` at the
same phase. The source places the Android failure before the named kernel block
negative control, but the retained report and job log do not distinguish kernel
path construction from authenticated receipt validation. The earlier `ccd3b51`
negative-control failure is a different phase; a common cause is unproven.
Progress markers show initialization and earlier direct/TURN-UDP work advanced,
but do not establish final scenario, cleanup or full native acceptance. The
prior DNS failure did not stop this run; no underlying DNS repair is inferred.

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

The next bounded task is native failure attribution and correction, preserving
socket uniqueness, native receipt requirements and all deadlines. Bootstrap
helper retirement and later roadmap implementation remain deferred until full
native qualification passes. Historical failures below remain retained.

The preceding completed qualification is `6b3fb8e2f5b92858ca62935066f8b607e3edecd9`
(tree `ecc484ffa393e45de96ae14d8390d3bae8fcedae`), full manual run
[42932168650](https://github.com/ahouchens/mesh-chat/actions/runs/42932168650).
The runtime-host source-selection correction is confirmed: all **56 Android
emulator cases**, **83 JVM cases** and **17 distribution/binary hashes**
independently validate. CI also passes **5,522 policy cases**, **1,770 Python UI
+ 12 rendered cases**, packaged Windows and its installed public-SDK lifetime
slice, Linux direct **25 transport + 10 recovery + 12 setup**, and 72 zero-overflow
layout cases. Policy inventory equals the retained `fed31cc` baseline; the prior
full local Python results remain labeled `fed31cc`. Current-source targeted
evidence is the affected Kotlin compile plus 410 existing boundary tests.

The run nevertheless fails. Android native initialization reports the actual
`ice_servers` operation at `broker_open`, category `network_unavailable`, cause
`name_resolution`. Runner outbound preflight completed earlier; the report does
not identify broker-versus-proxy hostname or prove a DNS configuration defect.
Android exits before key publication; Windows later fails `initialize_key_wait`.
No full native scenario, paired receipt, cold-restart or zero-accounting acceptance
follows. Windows direct transport and all ten recovery cases pass, including the
previous address-loss failure. Two of twelve setup cases fail at the same
25-second general-channel discovery wait: the joining workspace is active but
has no channel; the owner's channel-record delivery remains sending after three
attempts, with a future retry and no endpoint receipt. Its stored
`transport_unavailable` may persist after a later accepted send and does not
identify the current attempt's cause. The revocation/cancellation branches have
not yet run. These two failures remain separate from Android DNS.

The reviewed corrective batch contains C's `4523f43` payload-aware workspace
readiness repair and D's `5988882` private Android postfailure network snapshot.
Actual source-transport traces show a channel record admitted by bootstrap
readiness even though that payload uses the ordinary transport and its ratchet
is absent. Workspace preflight now checks the exact payload before spending a
send attempt; it retains the existing five-second key wait. Once bootstrap
delegation is skipped, the ordinary send branch requires its own identity and
ratchet even if bootstrap becomes ready concurrently. Both old behaviors have
semantic failing regressions; the corrected focused network/workspace suite
passes 94 cases. Six source setup cases passed on `7de1a54`; a representative
source setup case passes on the final correction. The two prior native Windows
setup failures subsequently pass in the `ce96840` CI run recorded above.

The Android snapshot adds one nonce-authenticated, same-publication inspect only
after the correlated ICE broker-open name-resolution failure. Within at most
two seconds of the existing controller deadline, it returns fixed app network
capability/DNS-presence booleans and current broker/proxy/unknown route selection.
It preserves the original failure and emits no raw network values. Custom opener
or proxy-handler behavior yields unknown. This is postfailure diagnostic context,
not a DNS repair or proof of the historical failing hostname. All 928 focused
Python cases pass, retaining all prior 903; the focused Android source compile
exits zero with its declared close-time android.jar warning. Actual packaging
and native acceptance still require CI.

The first combined local candidate `9708104` staged fresh SDK/upgrade artifacts
and passed strict model/reducer typing. Its full service run executed 6,831 cases:
6,780 passed, two failed, and the same 49 optional/platform cases skipped. All
6,801 baseline cases and exactly 30 new cases were present; all 28 composition
cases passed. Both failures were benchmark `RecordingNetwork` doubles missing
the new payload-readiness method. The reviewed `6c89920` correction adds only
that method to their shared `NoRouteNetwork` base, delegating to the subclass's
existing readiness behavior. The affected three-test benchmark selection now
passes; limits and assertions are unchanged. The failed run is retained. The corrected candidate subsequently passes
fresh full local gates; its full CI result is recorded above.

Combined fresh SDK, strict policy types and full service/policy/UI/Windows
gates subsequently pass at `ce96840`; full six-family CI fails at the native gate. No deadline,
bootstrap allowlist, public API or acceptance requirement is relaxed. Bootstrap
helper retirement and later roadmap implementation remain deferred until full
native qualification passes.

The preceding completed qualification source is
`fed31cc1a3104b0333bdfc8ed5251691002827e3` (tree
`3ec75b3aad730b470a1ed6a38b24c418fb830ba1`). Fresh local SDK staging and
strict policy types pass, as do **5,522 required policy cases**, **1,770 Python
UI + 12 rendered cases**, and **nine Windows boundary cases**, without required
skips. The full local service run passes **6,752 cases with 49 unchanged
optional/platform skips**, zero failures/errors, including all 28 composition
controls. All prior cases remain alongside exactly 116 new controls.

Full manual run
[42926669465](https://github.com/ahouchens/mesh-chat/actions/runs/42926669465)
completed **failed** on November 11 at 00:13:07 UTC. CI policy has exact
local/remote inventory parity; UI, packaged Windows and its installed public
SDK pairing/receipt/same-application lifetime slice independently validate.
Linux direct **25 transport + 10 recovery + 12 setup cases** pass. All 72 layout
report cases have zero overflow; screenshots were not visually reviewed.

Android runs **83 JVM cases** and **54 successful emulator case reports**,
including all four new optimized local Binder/Chaquopy diagnostic controls.
Those reports and their seven available binary hashes independently validate.
The separately packaged runtime host then fails Kotlin compilation because
its explicit source selection omits `CoreFailureObservationState.kt`, now
referenced by `CoreDispatch` and `MeshCoreApiService`. The two independent
consumer cases, complete 17-artifact distribution and final platform/cleanup
acceptance are unavailable. Cross-platform native interoperability is skipped;
the original `379e38a` ICE initialization cause remains unknown.

Windows direct recovery has **nine passes and one failure**: `address_loss`
does not observe the queued workspace message within its existing 45-second
delivery wait after the recovered-connection checks pass. Fabric and setup
do not run after that failure. The relevant test and direct-recovery/workspace
source blobs match the earlier passing `379e38a` run, but this does not explain
the failure or establish an environmental cause. No product repair is inferred.

D's narrow packaging correction `e552dd9` adds only the missing private state
source. Its isolated compiler reproduces the unresolved-reference failure and
passes after the change; 32 existing boundary cases pass. Independent review
approved the one-file source selection fix, integrated at `10d08c3`. The app
facade, bridge and host client remain excluded from this distribution. The
full local results above remain evidence for `fed31cc`; they are not relabeled
as a new-source run. The correction receives targeted validation and fresh full
six-family CI, including actual Gradle compilation and published-host checks.
The Windows recovery failure remains separate and unexplained. Bootstrap
retirement remains deferred until full native qualification passes.

The preceding completed checkpoint is `379e38ae385a398bfc5a6ec878ac12bc7969560a`
(tree `2cea47a5971980ac34e63949e5f221a2ced09184`). Fresh SDK staging and
strict policy types pass. Exact-source local gates pass **5,406 required policy
cases**, **1,752 Python UI + 12 rendered cases** and **nine Windows boundary
cases**, without required skips. The full local service run passes **6,636
cases with 49 unchanged optional/platform skips**, zero failures or errors,
including all 28 composition controls. The previous inventories are preserved
with the 95 new initialization diagnostic controls.

Full manual run
[42899863270](https://github.com/ahouchens/mesh-chat/actions/runs/42899863270)
completed **failed** on November 10 at 21:29:30 UTC. All non-native families
pass and independently validate, including exact local/CI policy inventory
parity, UI/Windows boundaries, packaged Windows and the installed public SDK
pairing/two-receipt/same-application lifetime slice, **52 Android emulator
cases**, **71 JVM cases**, all **17 Android distribution hashes**, and each
Linux/Windows **25 transport + 10 recovery + 12 setup cases**. All 72 layout
report cases have zero overflow; screenshots were not visually reviewed.
The exact broader service counts above belong to the local run. Existing
separate-caller/process, helper-retirement, physical and media limits remain.

The new failure labels narrow Android to `initialize_ice_servers` /
`PeerFailure` / `internal`. Windows reports `initialize_key_wait` /
`RendezvousUnavailable`. Both failed during initialization and retain no
successful native scenario rows, paired authenticated receipts, cold-restart
iterations or final zero accounting. Bounded inspection of both job logs adds
no fixed diagnostic discriminator. The typed SDK performs an implicit
`runtime.capabilities` exchange before the requested `call.ice_servers`, so
the failing inner operation and exception remain unknown. Existing broker/TLS
and response-encoding paths are possibilities, not established causes.

The private same-exchange diagnostic is now integrated from producer
`c6a31bb` plus reviewed correction `6246303`, Android/controller consumer
`364eb313`, and required Android inventory registration `a996252`. It selects
only bounded operation, stage, category and cause enums for an existing
correlated internal failure. The original local caller, cached Core client,
initialized qualification publication and each frame's isolated result must
still match; timeout, replacement, success or malformed metadata omits the
diagnostic. Public Core bytes, errors, request count and deadlines are preserved.
No broker/TLS repair or claim about the observed CI cause follows.

Independent component evidence preserves the prior selected inventories:
**285 producer Python cases** (207 prior plus 78 new), **903 consumer Python
cases** (885 prior plus 18 new), **24 JVM cases**, and **239 required-inventory
cases** (219 prior plus 20 new) pass. The producer corrections have three
semantic RED controls; the producer, consumer and required-inventory additions
also retain their initial semantic RED evidence. All source and final artifact
hashes were independently checked. Four new Android local Binder/Chaquopy
instrumentation methods compile and are required by the optimized emulator
inventory, increasing it from 52 to **56**; they have not yet run on a device.
This is component evidence, not combined qualification or native acceptance.

The exact-source combined local and failed full CI outcome at `fed31cc`
is recorded above. No unchanged-source retry was dispatched. Full native
acceptance remains open; bootstrap retirement remains deferred until it passes.

The preceding checkpoint is `30c9e4d996715aec9459da803119d1697bfba086`
(tree `3e30ef753eef5ab20940bbb242494f715a9f81d2`). The reviewed private v2
producer, controller and 28-case real Windows composition are integrated.
Fresh local SDK staging and strict policy types pass, alongside **5,311 required
policy cases**, **1,657 Python UI + 12 rendered cases** and **nine Windows
boundary cases**, without required skips. The full local service inventory is
**6,541 passing cases and 49 unchanged optional/platform skips**, zero failures
or errors. All 28 composition controls pass; prior inventories remain present
after the 16 explicitly recorded earlier uploader-vector renames.

Full manual run
[42886878229](https://github.com/ahouchens/mesh-chat/actions/runs/42886878229)
completed **failed** on November 10 at 20:13:24 UTC. All non-native families
pass and their retained evidence independently validates: exact local/CI policy
inventory parity, the UI/Windows boundaries, packaged Windows and installed
public-SDK pairing/two receipts/same-application lifetime, **52 Android emulator
cases**, **71 JVM cases**, all **17 Android distribution hashes**, and both
Linux and Windows **25 transport + 10 recovery + 12 setup cases** without skips.
The 72 layout report cases show no overflow; screenshots were not visually
reviewed. General CI verification passes, but the exact broader service counts
above belong to the independently retained local run. Existing separate-caller,
process, helper-retirement, physical and media limits remain unchanged.

Native Android reports `initialize` / `PeerFailure` / `internal`. Windows later
reports `initialize` / `RendezvousUnavailable`. Both reports are hash-verified;
neither retains successful native scenario rows, paired authenticated receipts,
cold-restart iterations or final zero accounting. The initialization phase spans
peer startup, five Core setup operations, ordinary inventory and the initial
key publication/partner binding. It does not identify the failing Android call.
Bounded in-memory inspection of both job logs exposes no fixed failure message,
script frame or additional safe discriminator. No aggregate acceptance follows.

Independent producer and consumer source audits find no concrete new defect
explaining this failure. Startup errors ordinarily become
`android_host_start_failed`; a later correlated Core `internal` response is a
source-consistent route, not a retained operation trace. An unchanged broker
credential error path is one possibility, not the selected cause. Reviewed failure-only diagnostics `7058909` are now integrated. Ten fixed
initialization call-site labels preserve the same escaping error, call order,
cleanup and budgets. All **1,093 focused cases pass without skips**, preserving
the prior 998 and adding 95. Eleven original-source semantic failures demonstrate
the missing labels. Tests execute actual initialization/run/reporting paths with
scripted external boundaries and check both roles, errors and guards, unchanged
successful reports, stale-label rejection, sensitive-data omission and cleanup
failure custody. Independent source comparison preserves the underlying calls
and explicit raised expressions. This is diagnostic component evidence, not a
repair or identification of the original Android cause.

The labels add no probe, retry, raw exception text, credential export or Core
error remapping. A Core call-site label cannot distinguish the SDK's implicit
capability request from its requested operation. Exact-source combined qualification at `379e38a` is recorded above; its
full native run fails during initialization. Bootstrap retirement remains deferred until
full native qualification.

The preceding checkpoint is `ccd3b5164181aae6de47e1a939f52a2a05464378`
(tree `39fd544a48f0461a4828f3f6339d274902f9e7b1`). Reviewed fixture
serialization `c4e6036` is integrated. Fresh SDK staging and strict policy types
pass; **5,068 required policy cases**, **1,482 Python UI + 12 rendered cases**
and **nine Windows boundary cases** pass with zero skips. The complete local
service inventory executes 6,347 cases: **6,298 pass, 49 optional/platform skips,
zero failures or errors**, including all 18 retirement composition controls.
The two new policy cases remove no prior inventory entries. Two failed local
launcher attempts (missing tooling import path, then missing Windows spawn
guard) are retained separately; neither is passing qualification evidence.

First full run
[42857623266](https://github.com/ahouchens/mesh-chat/actions/runs/42857623266)
fails installed Windows public-SDK pairing at `explicit_approval` /
`invitation_wait`, with a preserved local `wait_deadline` at 240,008 ms.
Both pairing probes find acknowledged retirement before caller cleanup, with
`expired:false`; current stopped/idle/ineligible actors do not identify the
first retirement cause. The zero remaining cleanup budget does not establish
positive host shutdown or a separate permanent shutdown defect. Nine Windows
boundary cases and installed DPAPI/EFS bootstrap pass; later Windows packaged
gates do not run. Native interoperability is **skipped**. Other required suites
pass and are independently verified. Frozen service, SDK archive and consumer
application hashes exactly match the prior passing Windows run at `36466e0`;
three source audits find no new concrete caller/producer/harness defect. The
invitation cause remains unresolved, including after the following retry.

One unchanged-source full retry,
[42862760087](https://github.com/ahouchens/mesh-chat/actions/runs/42862760087),
passes installed Windows public-SDK pairing, receipts and the recorded
same-application/caller lifetime slice, plus later packaged Windows gates.
All required non-native evidence independently validates: the exact 5,068-case
policy inventory, UI/Windows boundaries, **52 Android emulator cases**, **71 JVM
cases**, all **17 Android distribution hashes**, and Linux/Windows each
**25 transport + 10 recovery + 12 setup cases** with zero skips. The 72 layout
report cases show no overflow; screenshots were not visually reviewed. Existing
separate-caller/process, isolated-helper, physical and media limits remain.

The retry nevertheless **fails native interoperability**. Android reports an
unclassified `ValueError` while its phase is
`turn_tcp_kernel_block_negative_control`. That phase also remains selected
during post-negative observation, traffic validation and kernel-fault cleanup;
the failing assertion/producer boundary is not identified. Windows subsequently
reports `turn_tls_supervisor_owned_pairing_windows` with
`supervisor_pairing_retired`; its exact first-retirement diagnostic is
`wait_answer` / `tick` / `phase_timeout`. This is consistent with a partner
stopping in the previous scenario, not proof of the Android cause. The bounded
Android job-log inspection exposes no fixed exception message or script frame.
Failed reports retain no successful case rows for independent receipt/path
replay, 100 iterations, cold restarts or final zero accounting. No full native
acceptance or aggregate pass follows from source-reachable progress.

There is no third unchanged retry. A deterministic two-controller reproduction
on the unchanged `ccd3b51` source now demonstrates the coordination defect:
one peer enters retirement while its partner still needs its final selected-path
measurement or fault cleanup. Both runs contain **one passing ordered control
and two intentional semantic failures**, with no errors or skips. The actual
controller methods and strict checks execute; Core delivery, native observations,
kernel faults, transport, retirement effects and acknowledgments are scripted.
The lead verified all 14 source/evidence artifacts. This establishes ordering
vulnerability under those boundaries, not native proof or the CI failure cause.

Failure-only diagnostics `b7f323e4cd3874ca685e038472c2f652b280842b`
(tree `5789a83cfbdca3df3c503d710d3ca302b12a1180`) are integrated at `508198f`
after lead evidence verification and an independent review with no new findings.
All **739 focused cases pass with zero skips**: 667 prior cases remain and 72 are
added. Three original-source semantic failures demonstrate missing classified
evidence while preserving the original exception and phase. The separate
16-failure launcher attempt omitted the pinned Node runtime; its evidence is
retained, and the same source passes with the correct runtime. All literal
exception-message multisets are unchanged. The optional failure field contains
only a scenario, one of 23 fixed stages and an optional actual-branch reason.
Unknown causes stay unclassified; cleanup replacement uses its own exception.
This is component evidence, not native qualification or a fix for the race.

The independently reviewed private v2 preparation/completion/commit contract is
implemented at the common checkpoint below. After successful measurements and
fault cleanup, each role prepares its exact fresh transferred owner without disposal, publishes
then receives one sealed `case_complete_<scenario>_<initiator>` marker with exact
`{completed:true}`, commits the same request, and requires real exact owner/native
cleanup proof plus fresh clearance and independent global zero. Preparation
retains cleanup receipts across remote closure before local commit and denies
replacement while preserving current packets, inspection and genuine cleanup.
Only the witnessed manual-carrier True-to-False authority-signature successor is
allowed; all other active-ticket fences remain sticky. Existing owned-host
failure teardown supplies abandonment, never positive acknowledgment. Completed
historical receipts cannot admit or retire a later generation or satisfy its nonce.

The new marker budget is 17 Windows/15 Android uploads including reports for the
full workload and eight per role for quick; the run inventory cap remains 100.
Producer `3172d02` and consumer `b3751ae` are integrated unchanged at `6459710`,
after independent source reviews with no actionable findings. Producer evidence
contains **445 passing component cases**, strict model/reducer types and four
meaningful safeguard-removal failures. Consumer evidence contains **998 passing
cases**, preserving 895 prior cases (16 explicit uploader-vector renames) and
adding 103. Its two actual controllers independently gate the slow final sample
or fault cleanup; native, kernel, receipt and cleanup boundaries remain scripted.
The producer exercises actual service/owner/private-dispatch paths with modeled
native callbacks. Neither focused suite establishes real native completion.
Independent composition `ce4b9c4` is now reviewed and integrated, with all
**28 cases passing without skips**: the original 18 controls remain and ten are
added. Both role labels use actual Windows native hosts on localhost. The tests
retain and forward the host's actual closed callback after mapping removal,
commit the slow original owner after normal remote-loss cleanup, and require
matching native/owner/cleanup proof plus real global zero. They also cover
close-start projection before native cleanup, sticky Stop invalidation with
normal disposal, and historical receipts across an actual later generation.
Dropping the real closed notification produces the intended semantic failure
despite successful cleanup and zero host counts. Review corrected one stale-target
negative to exercise initial preparation; both variants and the complete suite
pass on the corrected commit. No native receipt, owner generation, acknowledgment
or zero count is synthesized. Approval/Reticulum boundaries remain modeled and
runtime steps are driven synchronously; this is not Android/JNI, authenticated
message receipt, full controller/path-case or packaged qualification. Combined local qualification passes at `30c9e4d`; its full native run fails
during initialization as recorded above. No public SDK/grant, JNI/host protocol, timeout,
retry-budget, kernel-drop, receipt or global-zero relaxation is assigned. Bootstrap retirement remains
deferred until full native qualification.

The preceding completed checkpoint is `36466e0245ec9c35d0e7b1bdaf2c544b40c050e0`
(tree `404089a57be9a1feb8cf1ec830331dc8c3123720`), full run
[42843336931](https://github.com/ahouchens/mesh-chat/actions/runs/42843336931).
Fresh local SDK staging, strict policy types, **5,066 required policy/adapter
cases**, **1,482 Python UI + 12 rendered cases** and **nine Windows boundary
cases** pass with zero skips. Inventory comparison retains every prior case
except the explicitly reviewed artifact-budget test rename accompanying the
signed cold-setup phase; the required selection gains 306 cases net.

CI independently verifies the same 5,066 policy cases, UI boundary reports,
Windows packaged/installed public-SDK pairing and receipt/lifetime slice,
**52 Android emulator cases**, **71 JVM cases**, all 17 Android distribution
hashes, and Linux/Windows **25 transport + 10 recovery + 12 setup cases** each.
The 72 layout report cases show no overflow; screenshots were not visually
reviewed. Existing platform, helper-retirement and media limits still apply.

The full gate nevertheless **fails general verification**. Its broader Python
run reports 6,271 passed, 52 skipped and two setup errors in the independent
native-retirement composition fixture; this broader count comes from retained
text, not a complete general-suite XML. Both errors occur before their test
bodies: the Windows-labeled loopback peer adopts while the Android-labeled peer
remains in pairing checks. Both labels use Windows native hosts. The trace omits
the exact rejected readiness condition. Native interoperability is **skipped**
because its verification prerequisite failed; this run provides no native
owner-retirement or cold-start acceptance.

Source audit identifies a fixture defect: direct setup consent and injected
control calls bypass the dispatch serialization used by production entry points,
allowing concurrent signed-capability read/modify/write effects. Normal native
control maintenance is already running, so an omitted explicit pump is not an
established cause. Fixture-only correction `c4e6036` now holds the complete consent preparation
and control receive under the same dispatch serialization as their production
callers; peer locks are released before entering the target service. Independent
review closes the finding with no new findings. Two deterministic signed-capability
regressions first reproduce stale consent publication and lost remote association,
then pass with the correction. All original 16 composition controls remain and
the complete owned file passes 18 cases with zero failures, errors or skips.
The lead verified all ten retained evidence file hashes, immutable source/tree,
the two semantic failures and exact original case preservation. No product code,
native maintenance, adoption deadline or retirement assertion changed. The exact
historical CI interleaving remains unknown. Fresh broader service, required policy,
boundary and full native qualification remain pending on the integrated source.
No product timeout, retry, authority or acceptance relaxation is assigned.

The preceding completed checkpoint is `5e6d0dac9f9cbee8ebdd986d85a4394dbf7b45c0`
(tree `eac21be7c638e72e2eb6f65a92adef5821b61f96`). Its first full run
[42819716492](https://github.com/ahouchens/mesh-chat/actions/runs/42819716492)
failed installing the Android 35 system image: the SDK installer reported an
unknown ZIP archive before emulator tests. No Android qualification report was
produced, and native interoperability was skipped. Every other available suite
passed and was independently validated. The archive/download cause is unknown;
no product change or acceptance relaxation was made for that failure.

The separate unchanged-source full run
[42824231976](https://github.com/ahouchens/mesh-chat/actions/runs/42824231976)
passes **4,760 policy cases**, **1,239 Python UI + 12 rendered cases**, **nine
Windows boundary cases**, **52 Android emulator cases**, **71 JVM cases**, and
Linux/Windows **25 transport + 10 recovery + 12 setup cases** each, all with zero
skips. All 17 Android binary/distribution hashes validate. The 72 layout cases
report no overflow; screenshots were not visually reviewed. Exact-source local
SDK staging, strict types and full policy/UI/Windows gates pass. The 109 added
policy/UI cases remove no prior inventory entries. Installed Windows bootstrap,
public pairing, two receipts and the same-application/caller lifetime slice pass;
the previously recorded isolation, helper-retirement and media limits remain.

The full required gate nevertheless **fails native interoperability**. Both actual
peers report `PeerFailure` / `scenario_deadline` at
`direct_native_lease_retirement`. Source reachability implies a direct case had
completed its transferred/adopted cancellation checks, authenticated exchange and
post-receipt selected-path/counter validation before entering retirement. Failed
reports do not retain those case samples, the direct initiator/index, close reply
or last inventory/counters. This progress is not independently replayable scenario
acceptance, both-direct-initiator coverage, the full relay/fault matrix, 100 receipt
iterations, cold starts or final accounting. No new rendezvous failure is reported;
the historical `c0b3cf7` acknowledgment cause remains unknown.

Read-only source audit establishes a controller/dispatch contract mismatch:
`native.command` / `native_webrtc_close` returns `state:managed` for an adopted
shared-native carrier and does not call the protected physical close method.
The controller ignores that reply and then waits for globally empty inventory
and zero native leases. Disabled automatic reconnect does not revoke an existing
verified manual carrier. The guard is intentional and must remain. The reports
do not retain the actual close result, so no exclusive runtime cause, disposal
leak or replacement allocation is asserted. Existing owner Stop can retire the
carrier but also persists a stopped profile/contact fence; restarting a later
manual case therefore needs a coherent, reviewed admission contract. A simple
command substitution or raw-close bypass is insufficient.

The reviewed follow-up implements private, current-owner carrier retirement
(`b4cd5a6`, corrected by `b06f26c`) and correlated controller acknowledgment
(`95005ca`). Successful cleanup and a fresh, revision-checked absence projection
clear only the temporary hold. Permanent Stop, quarantine and authority fences
remain independent; uncached handoff targets now carry their trusted contact
association into the atomic fence check. The managed-close guard is unchanged.
Each manual case requires both owner acknowledgment and the original global zero
accounting. Terminal cleanup uses the current scoped Core Stop (`7182e58`).

The separately reviewed `a093ca8` exchanges the existing signed cold-start
consent documents in a distinct sealed setup phase after the last manual zero
gate. Both peers publish before receiving; each imports through the existing
product validator and checks unchanged association and mutual consent before its
own first crash. Manual consent, workload, receipts and deadlines are unchanged.
Root verified 737 controller cases, 343 contact-fence follow-up cases and 691
cold-setup cases, including their failing pre-change regressions. These overlapping
component suites are not an aggregate qualification count. Independent sequential
composition (`ba3a7eb`) passes all 16 controls: real Windows loopback native hosts,
actual private request/owner acknowledgment and correlated controller zero checks,
opposite initiators, stale requests, delayed disposal, sealed-journal failure and
Stop/quarantine preservation. Contact approval rows, mailbox and Reticulum
readiness remain modeled; both role labels use Windows hosts. This does not prove
Android execution, full path-case receipts or cold-process behavior. Combined
exact-source local/full native qualification is still pending. SC26 remains
partial; isolated-helper retirement remains deferred.

The rendezvous diagnostic follow-up integrates `bdd2ff6` and `b0888ec` at
`b8d77e6`. It records fixed stage/reason labels at known transport origins,
bound in memory to the exact escaping receive error. An HTTP status is optional
and comes only from an observed standard HTTP error during an initial API or
redirected blob open; it must be an exact integer in 100..599. The controller
checks the same receive error and validates the complete allowed projection.
Foreign, stale, replaced, malformed or throwing observations add no fields.
Raw error text, URLs, headers, bodies and handshake material are never projected.

The existing failure type, wrapper messages, phase/site/substage and cleanup
remain intact. New calls, success and close clear the observation. Upload and
success reports gain no fields. Response context entry/read/exit has a fixed
`read_failed` label; non-decoding parser failures retain `transport_failed`,
while known JSON/encoding decode failures use `json_invalid`. Root review caught
and corrected a stale read label across that parser boundary. All request counts,
receive/open/poll budgets, bearer separation and provenance/digest/envelope checks
are preserved. The receive budget remains a polling deadline with in-flight I/O,
not a newly strict end-to-end cutoff. There is no retry or acceptance change.

The focused suite passes **645 cases**, zero failures/skips. It includes actual
controller report paths with scripted transport faults, negative identity and
redaction controls, and pre-change regressions for the missing fields and parser
mislabeling. Root independently verified XML/inventory/hashes; final immutable
review found no remaining actionable issues. These are offline controls, not a
repair for the unobserved `c0b3cf7` cause. Exact-source local and non-native CI
gates pass at `5e6d0da`; full CI fails native lease retirement as recorded above.
The revised helper-retirement interface has A/B design acceptance
after C's post-fence retirement-only registration correction; production remains
unassigned pending full native qualification.

The earlier completed checkpoint is `c0b3cf7558972b8560bac52e5154674d25603c86`
(tree `4304e0adbee1da7e694fc58b90bf05e933fce518`), full run
[42810308484](https://github.com/ahouchens/mesh-chat/actions/runs/42810308484).
The required gate **failed native Windows–Android interoperability**. Windows
reports `RendezvousUnavailable` during explicit contact approval, at
`rendezvous_receive` / `approval_acknowledgment`. Android reports `PeerFailure`
with `scenario_deadline` during `direct_authenticated_receipts`. These reports
do not establish a common cause. Transport code collapses HTTP, redirect, read,
response/inventory validation and polling failures into the Windows error type;
the exact branch and HTTP status are absent from both retained report and bounded
log inspection. Partner artifact metadata does not prove what Windows received.

Source reachability shows Windows accepted its initial local ready/path
observation before waiting for acknowledgment. That observation did not enforce
the later scenario-specific candidate type or positive traffic deltas. The failed
report retains no sample to replay independently. Neither this progress nor
Android's later phase qualifies correlated receipts, the full native scenario
matrix, impairment, repeated cycles or final resource accounting.

Independently verified passes: **4,651 policy cases**, **1,130 Python UI + 12
rendered cases**, **nine Windows boundary cases**, **52 Android emulator cases**,
**71 JVM cases**, and Linux/Windows **25 transport + 10 recovery + 12 setup cases**
each, all with zero skips. All 17 Android binary/distribution hashes validate.
The 72 layout cases report no overflow; screenshots were not visually reviewed.
Exact-source local SDK staging, strict types and policy/UI/Windows gates pass.
Both worker-deselected installation cases executed in the full policy gate.

Installed Windows bootstrap, public pairing and two authenticated receipts pass.
The lifetime slice covers two sessions in the same Node application/caller,
detach-survivor/reattach, competing-owner refusal with exit status 2, and original
pending-message/key identity across trusted owner stop/reopen. Three owned hosts
exit positively and the runtime lock is reacquired. This does not prove separate
consumer-process exit, cross-caller/user/app isolation, isolated-helper retirement,
pending-message delivery after restart, Android credential UI or media coexistence.
The earlier `1b3a2be` invitation failure remains unexplained by this later pass.

The follow-up recorded above retains fixed rendezvous stage/reason and an observed,
validated HTTP status only for the same escaping transport error. It adds no
request, retry, timeout, fallback or acceptance change and exports no raw error,
URL, header, body or handshake material. SC26 remains partial. Helper-retirement
production remains deferred; its private-interface review separately requires
retirement-only registration to remain legal after fencing productive startup.

The Windows pairing diagnostic follow-up integrates `1f73cdf` at `93a1448`.
It preserves the original thrown value and its phase, subphase, safe error code,
deadline flag and first timing before failure probes and final cleanup. Owned
budget/wait errors use identity-bound fixed origins; unknown thrown values remain
unknown. Cleanup-only failure still fails qualification. Separate bounded records
distinguish the original hosts, rejected contender and reopened offerer; attempts
are counted, while detach, stop and budget fields describe the latest attempt.
Positive process stop does not turn failed client detach into successful retirement.

Failure probes use the existing public `diagnostics.query` permission and
operation, with at most four selected current actor observations per role.
They expose fixed categories without handles, payloads, cursors or timestamps,
and cannot identify an actor with a pairing intent or establish first cause.
Roles run concurrently. Because the SDK serializes requests per client, pairing
status runs first and diagnostics receives only the positive time remaining in
the same two-second monotonic probe allowance. Exhaustion omits that request;
no new timeout window, client, retry or authority is introduced.

The focused worker gate passed **578 cases**, zero failures/skips; two installation
cases were explicitly deselected and remain required in full qualification.
The lead verified the complete XML/inventory and hashes. Actual application
controls reproduce the old masking failure and cover primitive throws, secondary
probe/cleanup failures, queue serialization, distinct owner incarnations and the
unchanged 4096-byte report bound. Independent immutable review found no actionable
issues. This is offline component evidence, not installed Windows acceptance or
a proven repair for the original invitation failure. Exact-source SDK staging,
types, local gates and installed Windows CI passed at `c0b3cf7`; full CI failed
native interoperability as recorded above. Success checks,
work/stop/outer deadlines, consent and positive shutdown requirements are unchanged.

The earlier completed checkpoint is `1b3a2be94816958d3fe26052e9fbaf5d2f42245c`
(tree `e1ac699f1b0bd32c07037f5eb9d5dcf5b29b1267`), full run
[42802755780](https://github.com/ahouchens/mesh-chat/actions/runs/42802755780).
The required gate **failed Windows installed public-SDK pairing**; native
interoperability was **skipped**, not passed. The report records retirement
failure after the first work failure at 240,043 ms. Source review proves that
the application's `finally` could replace the primary exception, phase and
subphase with cleanup failure. Its exhausted work deadline leaves a zero-ms
stop-observation budget; this is not proof of a host shutdown defect. The
original failed operation and producer cause are not recoverable from this
report. Earlier saved pairing states are not current failure-time observations;
the subsequent probes found both intents retired before expiry, without a cause.

The installed sidecar, SDK archive and application file hashes are identical
to the passing `902b12d` Windows checkpoint. This neither establishes an
environment cause nor excludes a latent timing defect. Nine Windows boundary
cases and installed DPAPI/EFS bootstrap pass, but this run does not qualify
pairing, shared-host lifetime or the later packaged gates. The earlier passing
Windows lifetime evidence remains explicitly bound to `902b12d`.

Independently verified current passes: **4,563 policy cases**, **1,130 Python UI
+ 12 rendered cases**, **52 Android emulator cases**, **71 JVM cases**, and
Linux/Windows **25 transport + 10 recovery + 12 setup cases** each, all with zero
skips. All 17 Android binary/distribution hashes validate. The 72 layout cases
report no overflow; screenshots were not visually reviewed. Exact-source local
SDK staging, strict types and all local gates passed. The 81 net added policy
and UI cases retain the prior root-identity controls and add strict root-command
diagnostic coverage. The new Android root diagnostic path itself did not run
in native CI because the Windows prerequisite failed.

The diagnostic follow-up recorded above preserves original work-failure identity
and observations, reports cleanup independently, and uses existing public current
diagnostics with a bounded projection. It is diagnostic work, not a proven product repair
or first-cause history. No timeout, consent, receipt, positive shutdown, native
authority or success criterion is relaxed. SC26 remains partial; the separately
reviewed helper-retirement implementation stays deferred.

The preflight diagnostic follow-up integrates `2fef6f3` at `88ea975`.
It preserves the single checked `adb root` invocation, fatal outcome, UID
requirement, command order, deadlines and cleanup. Only that root invocation
captures stderr in memory. Failure reports may include a strict bounded nonzero
exit status and a fixed diagnostic-family label, selected only for the same
escaping checked exception and validated preflight site. Raw command/output,
private suffixes and environment values are not exported. Unknown, conflicting
or overlong diagnostic text remains unclassified. The 4096-byte bound applies
to classification, not total subprocess stderr capture.

The worker's complete focused controller/peer/preflight suite passed **484
cases**, zero failures/skips; the lead independently verified XML and inventory
hashes. Immutable source review found no actionable issues. This is a reporting
change with scripted-boundary regression evidence, not a fix for the unknown
`902b12d` root-command cause. The exact-source local gates and CI components
passed as recorded above, but installed Windows pairing failed before the native
interop job. No retry, root bypass or native acceptance is added.

The earlier completed qualification checkpoint is `902b12d1470177fe4207e027bf3d44fbe839cc91`
(tree `ad829c7716cb2b4c15620a9d69504c6ce114922e`), full run
[42796005344](https://github.com/ahouchens/mesh-chat/actions/runs/42796005344).
The required gate **failed native interoperability**. Android failed during
`platform_outbound_preflight`, at the checked `android_root` command, with
`CalledProcessError`. Its subsequent root-identity, pairing and native sample
checks were not reached. Windows reported `RendezvousUnavailable` at
`initialize`. The retained Android output does not contain the exit
status or cause: stderr was discarded and captured stdout was not serialized.
No transience, root-privilege rejection or successful cross-platform freshness
validation is inferred. The failed attempt remains recorded.

All other families independently verified **PASS** on that exact source:
**4,482 policy cases**, **1,049 Python UI + 12 rendered cases**, **nine Windows
boundary cases**, **52 required Android emulator cases**, and **71 JVM cases**,
with zero skips. The JVM inventory retains all 62 prior cases and executes all
nine new sampling controls, including the actual invocation helper. All 17
Android binary/distribution hashes validate. Linux and Windows each pass the
25 transport, 10 recovery and 12 setup cases; 72 layout cases have no overflow
(runner reports checked; screenshots not visually reviewed). Local SDK staging,
strict types and all full local gates also passed.

Installed Windows public-SDK lifetime acceptance is reconfirmed on `902b12d`:
two same-application/same-caller SDK sessions, detach/reattach, refusal of a
competing owner, pending-message/key preservation across trusted owner restart,
positive host exits and native-host shutdown acknowledgement. This does not
prove separate consumer-process isolation or isolated-helper completion.
The separate helper-retirement draft has independent architecture review but
remains unimplemented. Its exact-completion proposal covers helper child/I/O,
pipes, protected temporary directory, executor and registered local carrier/
handoff work; native preparation and router-mapping cleanup retain their current
best-effort scope. SC26 remains partial. A narrow preflight diagnostic follow-up
preserves the checked failure, one root invocation, UID guard and all deadlines;
no rerun or diagnostic label retroactively assigns the failed attempt's cause.

The native sample freshness follow-up combines producer `14e10f4`, consumer
`a542589` and independent composition regression `ae585ec` at `377ab38`.
Source inspection proves the former controller compared native monotonic ticks
with wall-clock time. The retained `65b0872` failures do not prove either job
reached that comparison, so the exact CI cause remains unassigned.

Each existing private path RPC now carries a fresh `sample_request` challenge
through the actual native sampling operation. The producer and service require
its exact echo; a cached first response cannot acquire the current request.
Observation v1 retains a bounded opaque timestamp. Producers validate original
capture, request window and timestamp binding at full resolution in their own
clock domains; Android encodes the capture relative to its adapter origin.
Its actual callback uses one invocation owner for capture, result publication,
completion and exact-slot release. Late or duplicate callbacks cannot take a
new request's slot. The consumer keeps its finite, nonnegative local two-second
round-trip bound and existing service elapsed, identity, sequence, readiness,
selected-path and counter checks. No clock synchronization, additional RPC,
retry, deadline extension, public SDK operation or authority grant is added.

Failure-only fixed enums identify the approval/adoption substage and sample
rejection reason for the same escaping exception. Original phase, error code
and nested pairing/rendezvous attribution remain intact; private sample values
and arbitrary exception text are not exported. Independent consumer review
found no actionable issues.

The lead ran **706 combined focused cases**, all passing with zero skips in
9.96 seconds, including **19 real Python producer/service/controller composition
cases with modeled native effects** and all 45 Windows host conformance cases.
The old clock comparison fails the retained behavioral regression. Nine new
Android JVM vectors invoke the production callback helper and subsequently
passed in the exact-source CI run recorded above. All local gates and platform
suites passed; packaged cross-platform acceptance remains blocked by native
Android preflight. No receipt-matrix or helper-retirement acceptance is promoted;
the separate bootstrap-retirement implementation stays deferred.

The preceding qualification checkpoint is `65b08727264f463f7337b9be06e36799f5a3a364`
(tree `77cedce295df08a7be13cec774bea289ac302ee5`). Full manual run
[42784376932](https://github.com/ahouchens/mesh-chat/actions/runs/42784376932)
completed **failed in native interoperability**. All six families and native
`full` were selected. Every other family passed; duplicate PR run `42784377833`
was confirmed canceled. There is no aggregate pass or experimental-default promotion.

Exact-source SDK staging, strict types, **4,263 policy cases**, **913 Python plus
12 rendered UI cases**, and **nine Windows boundary cases** passed locally with
zero skips. CI independently verifies the same policy inventory and UI results.
The policy inventory adds 134 cases to `606f68d`, removing none. The preliminary
`46e34af` policy run was intentionally interrupted for a review correction; it is
neither a product failure nor qualification evidence.

Installed Windows evidence now verifies the shared-host lifetime slice: two SDK
sessions in one Node application, session close with a surviving client,
reattachment, refused concurrent ownership with positive rejected-process exit,
and original pending-message identity and idempotency key across trusted owner
stop/reopen. All 25 exact predicates passed in 46.14 seconds, including three
clean normal-host exits and native shutdown acknowledgments, one refused-owner
exit, and two EFS-protected profile directories and vaults. Existing public
pairing and two authenticated receipts remain required and passed. The report,
SDK, executable, bootstrap report and source bindings were independently checked.
The tested sidecar is 54,599,551 bytes, SHA-256
`4abb51d142a5d747f21832120fe2b86d8393c6735fa75faaa9e8be03a3ecf28f`.

Android independently verifies **52 required emulator cases**, including the
previously failing manual-carrier replacement case, **62 JVM cases**, and all
17 retained binary/distribution hashes, with zero skips. Both Linux and Windows
direct suites verify **25 fabric, 10 recovery and 12 setup cases**, with zero
skips. Layout reports 72 cases without overflow; archive entries were hashed,
but PNGs were not retained or visually reviewed. Direct binary and WebView2
probe hashes retain their runner-claim limitations.

Both native peer reports fail at `explicit_contact_approval` with `ValueError`.
This reaches beyond the earlier negotiation failure, but the retained reports
do not distinguish approval, observation freshness, resource identity or other
validation failures within that phase. No complete native pairing, adoption,
selected-path receipt matrix or underlying root cause is inferred. The clock-contract repair and precise
content-free diagnostic follow-up are integrated above.

The Windows lifetime result remains narrower than full SC26: it does not prove
independent consumer-process exit, caller/cross-user/multi-application isolation,
isolated bootstrap-helper retirement or delivery of the pending message after
restart. Android credential UI, independent public Windows–Android receipts,
media coexistence and physical qualification remain open. C's read-only audit
found missing retained helper completion across both bootstrap producers; A is
reviewing constructor races, lock order and existing capacity semantics. No
helper-retirement implementation or stronger Android exit claim is included.

The implementation checkpoint combines Android fixture repair `adc6f41`
and Windows consumer lifetime slice `911ed8c` at `2d99222`. The lead reviewed
the immutable changes; worker focused reports pass **99 Android retirement and
related component cases** and **492 Windows consumer/evidence cases after review
correction**, with zero
skips. The latter include 26 actual subprocess protocol controls. These results
precede the combined exact-source gates and do not qualify native execution.

The Android fixture retains the original ten-second wait but now checks routing,
creation and both exact registry bindings under the existing dispatch/native
locks. The actual post-Stop callback is exercised against a gated production
close adapter and real registry. The old callback admits premature reuse; the
new one stays false until confirmed release. The same logical ID then receives a
new physical identity, and a stale old callback cannot retire that replacement.
Production resource limits, admission, disposal and authority remain unchanged.

The Windows application preserves public pairing and two authenticated receipts,
then checks two SDK sessions sharing one host, session-close independence,
reattachment, refused concurrent-owner positive exit and original pending-message
identity/key preservation across trusted owner stop/reopen. Three normal host
exits and one refused-owner exit are required. Work is enqueued only after the
receiver positively exits. All shutdown requests use trusted inherited EOF; no
SDK runtime-stop grant is added. Advertised operations describe bound ports,
not permission-filtered grants, so advertised `runtime.stop` alone is not owner
authority. Operation inventories remain stable and private `native.command`
remains absent. The original 240-second main budget is preserved.

This is a same-application, two-session scenario. Independent consumer-process
exit, caller/cross-user/multi-application isolation, isolated-bootstrap-helper
retirement and subsequent delivery of the preserved pending message remain
outside its scope. Strict report predicates reject the prior two-exit report and
unexecuted claims. Independent review found that a conflicting replay could add
an extra message while still returning the expected error. Follow-up `846da34`
compares copied outbound message-ID sets before and after replay; a new fault
inserts that extra record and then throws the expected conflict. The old producer
fails this control, and the corrected 492-case focused suite passes. Combined exact-source gates and actual CI results are recorded above.
SC26 remains partial and no experimental selector is promoted.

The preceding qualification checkpoint is
`606f68df05cd0538dbff0b76e6c6745eeda4c24b` (tree
`7c3cdde2a07108df9c9f8ec58852b98f286bc10c`). Full manual qualification
[42776359931](https://github.com/ahouchens/mesh-chat/actions/runs/42776359931)
completed **failed** in the required Android gate. All six families and native
`full` were selected. Native interoperability was **skipped** because Android
failed; neither reserved-only creation waiting nor the preceding pending-adoption
repair received device qualification in this run. Duplicate PR run `42776365861`
was confirmed canceled. No aggregate pass or acceptance promotion is claimed.

Exact-source local SDK staging, strict types, **4,129 policy cases**, **912 Python
plus 12 rendered UI cases** and **nine Windows boundary cases** passed with zero
skips. Policy completed in 406.95 seconds. The inventory adds exactly 46
controller cases and 11 actual-Core allocation cases to the prior checkpoint,
removing none. CI independently verifies the identical policy inventory, UI
results and packaged Windows reports, including independent public-SDK bootstrap,
pairing and two authenticated receipts. These Windows reports precede the planned
shared-host SDK-session lifetime scenario and do not qualify it.

Both Linux and Windows direct reports independently verify **25 fabric, 10
recovery and 12 setup cases** with zero skips. Layout reports 72 cases without
overflow; all archive entries were hashed, but PNGs were not retained or visually
reviewed. The tested Windows sidecar remains 54,599,551 bytes, SHA-256
`4abb51d142a5d747f21832120fe2b86d8393c6735fa75faaa9e8be03a3ecf28f`.
WebView2 probe and direct binary hashes retain their runner-claim limitations.

Android failed-run diagnostics independently reconstruct **51 passing and one
failing report among 52 required emulator cases**, with no missing/unvalidated
reports, plus **62 passing JVM cases** with zero skips. Seventeen inventory
artifact hashes match the retained debug archive. This is failed-run diagnostic
evidence, not Android platform, cleanup or overall acceptance. The failing case is
`SignalMailboxAndroidTest.sharedRuntimeAdoptsVerifiedManualNativeCarrierWithoutMailbox.none`.
The retained stack reaches `run_manual_native_adoption` line 484's replacement
offer, then `_claim_native_session` and `NativeResourceRegistry.reserve`, which
raises `NativeUnavailable: Native resource reservation unavailable`.

The fixture waits for absence from the live-routing set before reusing the
logical session. Production deliberately removes routing before confirming
physical disposal and releasing the reservation. This identifies a plausible
fixture observation gap, not proof of the precise native callback ordering or
the registry's duplicate-versus-capacity branch in this run. The subsequent fixture repair and
Windows shared-host lifetime implementation are recorded above. No early
resource reuse, capacity relaxation or arbitrary retry was introduced. The
Windows scenario excludes
independent consumer-process exit and isolated-bootstrap-helper retirement.

The reserved-creation follow-up is integrated: controller `a872e7f` and
allocation regressions `a92e69a` are combined at `24f0b1b`. The lead
reviewed the changes and independently ran **522 focused cases**, all passing
with zero skips. The controller inventory now contains 287 cases, and the new
allocation-observation module contains 11 cases through the actual Core
request, native adapter and service lifecycle boundaries with explicitly modeled
native/mailbox effects. These are offline component results, not device evidence.

The guard reuses the existing operation-bound pairing status call. Only an exact
string `reserved` defers inventory and stats through the unchanged wait. Other
states and malformed metadata preserve their original behavior; retirement,
foreign operation identity and stats failures still propagate. No extra RPC,
exception retry, owner, timer, authority grant or public contract is introduced.
Stats success still does not establish approval, attachment or messaging readiness.
Exact-source local gates passed; the full CI outcome and its Android failure
are recorded above. Native qualification remains open.

The previous shared checkpoint is `82aaf19c3671777724d7da5e8cab0e5b2a5d6de2`
(tree `c489caaa361329d9dd50d1d26590bbe2d691fdd8`). Full manual qualification
[42770728559](https://github.com/ahouchens/mesh-chat/actions/runs/42770728559)
completed **failed** in native interoperability. All six families and the native
`full` workload were selected; duplicate PR run `42770735359` was confirmed
canceled. No aggregate pass or release/default promotion is claimed.

Every exact-source local gate passed: SDK staging, strict model/reducer types,
**4,072 policy cases**, **866 Python plus 12 rendered UI cases**, and **nine
Windows boundary cases**, with zero skips. Policy completed in 410.49 seconds.
The inventory adds exactly 51 pending-handoff producer cases and 90 controller
cases, removing none. CI independently verifies the identical 4,072-case policy
inventory and 866-plus-12 UI results, all passing with zero skips.

Packaged Windows reports, independent SDK bootstrap/pairing/receipts and the
sidecar binding pass independent validation. The sidecar is 54,599,551 bytes,
SHA-256 `4abb51d142a5d747f21832120fe2b86d8393c6735fa75faaa9e8be03a3ecf28f`.
Android verifies **52 emulator cases**, **62 JVM cases** and **17 artifact
bindings**. Both Linux and Windows direct verify **25 fabric, 10 recovery and
12 setup cases**, with zero skips. The previous Linux package-install timeout
did not recur. Layout reports 72 cases without overflow; every archive entry was
hashed, but PNGs were not retained or visually reviewed. WebView2 probe and direct
binary hashes remain runner claims. These results do not establish successful
native credential UI, public-SDK cross-platform delivery, media or physical acceptance.

This native attempt failed before the repaired approval-stage window. Android
reports `direct_supervisor_owned_pairing_windows`, `PeerFailure/invalid_request`,
at `negotiate_native_stats`. Windows reports the same scenario and
`supervisor_pairing_retired` at `pairing_status`, with
`wait_answer/tick/phase_timeout`. The Android report has no retirement DTO or
underlying native exception. `NativeUnavailable` is a `ValidationError`; a
directly raised domain failure through `ServiceNativeCommands` reaches the Core
session's validation mapping and can become `invalid_request`. That source trace
does not identify the actual device cause. C and D reproduce a valid stats
request failing while the pairing reservation is visible before native creation.
Retirement before or during stats can produce the same code. A narrow follow-up
is assigned: defer inventory/stats only for an exact `reserved` pairing state,
under the existing operation identity and wait deadline. Other states, malformed
metadata, retirement and stats errors preserve their existing behavior. C owns
the actual Core-path regression; D owns the controller guard and its tests. No
retry, authority, timeout or evidence relaxation is authorized. The pending-
adoption repair remains locally proven, not demonstrated as a device fix by
this earlier-failing run.

The pending-adoption repair is integrated: producer `b268842` and consumer
`f0da5d6` are combined at `32f6061`. The lead reviewed both complete diffs and
independently ran **465 focused cases**, all passing with zero skips in 10.29
seconds. The producer contributes 51 offline cases; the controller inventory is
now 241 cases. Pure observations require an exact committed pairing handoff,
current running DISCOVER work, matching deadlines and unfenced authority.
Inventory metadata grants no path permission. A unique `pending_adoption` row
defers one readiness poll through the existing wait; malformed, ambiguous,
missing and nonpending metadata retain the existing sampling and exceptions.
Actual path pre/post authority checks and all readiness/traffic evidence remain.

The producer's preliminary full suite had two Git Bash fixture permission
failures; both passed outside the sandbox without source/assertion changes.
That preliminary run is not final-source qualification. C subsequently passed
3,631 final-source connection tests with zero skips. Integrated local gates and
CI component evidence are recorded above; native acceptance remains open.
The offline reproduced scheduling gap is consistent with the retained native failure, whose exact substage was not
recorded; it is not proof of the sole device failure cause. No-handoff recovery
and automatic pending windows remain outside this narrowly proven contract.

The previous shared checkpoint is `994e4b488ba88935569970ac0adfb15c237f621d`
(tree `70c7ce3b052b0338737010bab628fb6b0b153e94`). Full manual qualification
[42763177698](https://github.com/ahouchens/mesh-chat/actions/runs/42763177698)
selects all six families and native `full`; duplicate PR run `42763183634` was
confirmed canceled. The workflow completed **failed**: both native jobs failed,
and Linux direct was canceled at its 40-minute job limit during `apt-get update`
in the syscall-observer installation step. The retained log shows Ubuntu mirror
index fetching followed by cancellation; the underlying mirror/network cause is
unproven. Required Linux NAT, fabric, recovery and setup steps were skipped and
no direct execution reports were produced. This is not a Linux transport pass.
No aggregate pass or release/default promotion is claimed.

The corrected candidate passes every exact-source local gate: SDK staging,
strict model/reducer types, **3,931 policy cases**, **776 Python plus 12 rendered
UI cases**, and **nine Windows boundary cases**, with zero skips. Local policy
takes 417.68 seconds. Independent inventory comparison finds exactly the three
new bootstrap startup regressions and no removed cases. The same three cases
are present in CI's independently reconstructed **3,931-pass** policy inventory.
The retained CI UI evidence also confirms **776 plus 12 passes**, with no skips.

Windows packaged reports and the sidecar binding pass independent validation,
including actual DPAPI/EFS independent-consumer bootstrap and Windows pairing
receipts. The sidecar is 54,596,632 bytes, SHA-256
`dc4373f98ac9b8c2e634af655f4bde630340b7b7fc147e95d8a49875dd2aa265`.
Android's **52 emulator and 62 JVM cases** pass with **17 artifact bindings**,
including the corrected instrumentation APK. Windows direct's **25 fabric,
10 recovery and 12 setup cases** pass with zero skips. Layout reports 72 cases
without overflow and every archive entry was hashed; PNGs were not retained or
visually reviewed locally. WebView2 probe and direct binary hashes remain runner
claims. These component/platform results do not establish cross-platform receipts,
selected relay paths, OS authentication, media coexistence or physical acceptance.

The startup repair advances both actual native peers through `negotiate()` to
`explicit_contact_approval`: the previous `gather_answer/failed/transient`
retirement does not recur. Both reports now contain `PeerFailure` with
`error_code: contact_not_approved`, without a retirement DTO or substage. This
phase includes explicit decisions, approval polling, a reconnect-consent update,
and private path-readiness inspection. Its label alone does not prove the decision
RPC failed. Ordinary Core/domain error mapping differs from the private path
route, narrowing source review toward native carrier authority during inspection.
C completed a guarded offline review of the actual fresh-profile consent,
handoff and adoption sequence. The integrated repair above preserves consent,
authority and deadlines and is based on the reproduced claim/adoption window.

The integrated bounded repair adds private inventory `owner_state` metadata while
preserving the existing mapping-based `adopted` flag and every resource row.
`pending_adoption` must be proven from an existing committed pairing handoff
lease and the exact current, authorized, unfenced target DISCOVER operation,
with matching resource/runtime/generation/revision and unexpired deadlines.
The query has no effects or new custody registry. Readiness polling will defer
only a strict positive pending result for one uniquely matching resource;
other, missing, malformed or ambiguous states and `ready=False` retain protected
path sampling and its errors. Current path authority checks remain intact.
An offline gated claim reproduces the gap between publishing the service mapping
and applying the worker's Adopted completion. Releasing that gate authorizes the
same physical resource. Consent-retirement controls establish valid denial but
do not explain the initial-direct sequence. The actual CI substage is not retained.
No-handoff manual/recovered/automatic pending windows lack this exact proof and
remain unavailable under this narrow repair. C owns the read-only producer and
D the consumer; implementation and local qualification are complete, while
native qualification remains open after the earlier negotiation failure above.

The previous shared checkpoint is `55e6b1924a31b978403555aa6be83487ce86553d`
(tree `81d4ab8f07cc488d3cab09037226e9a7e6eab5ae`). Full manual qualification
[42758745281](https://github.com/ahouchens/mesh-chat/actions/runs/42758745281)
completed **failed** on 2026-11-10. Selection confirms all six families and the
native `full` workload; duplicate PR run `42758746355` was canceled. The final
gate fails because native Windows–Android pairing remains unqualified.

All exact-source local gates pass: SDK staging, strict model/reducer types,
**3,928 policy cases**, **776 Python plus 12 rendered UI cases**, and **nine
Windows boundary cases**, with zero skips. Local policy takes 396.66 seconds.
The lead independently reconstructs the corresponding CI policy/UI inventories,
the complete Windows packaged report set, Android's **52 emulator and 62 JVM
cases** with **17 artifact bindings**, and **25 fabric, 10 recovery and 12 setup
cases on each of Linux and Windows**. These pass. The previous Windows setup
channel-discovery failure does not recur; this does not establish its cause.
The Windows sidecar remains 54,596,632 bytes with SHA-256
`dc4373f98ac9b8c2e634af655f4bde630340b7b7fc147e95d8a49875dd2aa265`.
WebView2 probe and direct binary hashes remain runner claims. Layout reports
72 no-overflow cases; all archive entries were hashed, but PNGs were not retained
or visually reviewed locally. Native control cycles are not durable-message
receipts, and requested relay policy does not establish the selected ICE path.

Both native failure reports now contain exact-actor retirement metadata.
Android reports `{phase:gather_answer,event:failed,reason:transient}`; Windows
reports `{phase:wait_answer,event:tick,reason:phase_timeout}`. Both retain
`failure_site: pairing_status`, `pairing_state: retired` and
`error_code: supervisor_pairing_retired`. Android startup and bootstrap-key
exchange completed; the previous pre-controller startup failure did not recur.
The Android exception itself was not retained, so the transient reason alone
does not identify its source or prove a native transport timeout.

C's source audit finds a concrete instrumentation prerequisite omission:
`PackagedNativeInteropBoundaryTest` attaches WebRTC without configuring
`BootstrapClient`, although ordinary Android startup configures both. Answer
gathering binds signed onboarding and constructs `AndroidBootstrapProcess`,
whose client requires that context. A guarded offline control reproduces the
exact retirement signature without configuration and reaches `awaiting_approval`
with `initialize_contact` after configuration, with zero external I/O. This is
a harness defect consistent with the CI evidence, not proof of its sole cause.
C is assigned the missing initialization call and narrow regression coverage.
No policy/deadline relaxation or additional live probe is assigned. Native
pending-action recovery, document-bound authority, positive resource-owner
retirement, cross-platform receipts and full acceptance remain open.

The narrow follow-up `6b81322` is integrated as `db10298`: the Android
interop controller now calls `BootstrapClient.configure(context)` before
WebRTC attachment and Python initialization. The only other changed file adds
three offline regressions: startup composition and configured/unconfigured
factory controls through the real gather/sign/bind path. The source guard fails
on the previous harness. C reports 101 focused passes; the lead reviewed the
complete two-file diff and independently reran 73 pairing/runtime/diagnostic
cases with zero failures or skips. The Java client and native/mailbox boundaries
are doubles; this is not device evidence. Full exact-source local and CI
qualification of the corrected candidate is next.

The previous shared checkpoint is `e7630c8b6ed1feda6b3ef049336be309179b6075`
(tree `07beb0ed2d1859b66fe14b19f6ee7fbb4ec2663b`). Full manual qualification
[42752889278](https://github.com/ahouchens/mesh-chat/actions/runs/42752889278)
completed **failed**. Selection independently confirms all six families and the
native `full` workload; duplicate PR run `42752866780` was canceled. There is no
aggregate pass or release/default promotion.

All exact-source local gates pass: SDK staging, strict model/reducer types,
**3,859 policy cases**, **737 Python plus 12 rendered UI cases**, and **nine
Windows boundary cases**, with zero skips. The policy run takes 399.07s and
includes all six installed-runtime SDK cases, 33 independent admission cases,
133 controller cases and 32 new retirement diagnostic cases, separately checked
against the retained XML and inventory.

The lead independently reconstructs the corresponding CI policy/UI inventories,
complete Windows packaged report set, Android's **52 emulator and 62 JVM cases**
with **17 artifact bindings**, and Linux direct's **25/10/12 cases**. These pass.
The frozen Windows executable is 54,596,632 bytes with SHA-256
`dc4373f98ac9b8c2e634af655f4bde630340b7b7fc147e95d8a49875dd2aa265`.
The WebView2 probe and direct binaries retain runner-reported hashes; the layout
job passes with 72 no-overflow report cases and all archive entries hashed, but
its PNGs were not retained or visually reviewed locally.

Windows direct fabric and recovery pass **25 and 10 cases** respectively. Its
setup inventory contains **12 executed cases, 11 passes, one failure and zero
skips**; no passing setup JSON exists. The `unhosted_joiner-native-suspend` case
fails at `test_direct_setup_pipeline.py:258`, awaiting the general channel after
membership becomes active. This happens **before** the suspension branch runs.
Both retained peer diagnostics show authenticated, connected recovery paths;
the channel-bootstrap receive/pending-control boundary is under read-only review.
Neither a suspension defect nor a timing-only explanation is established.

Native Android fails **before controller construction or pairing**, with
`phase: platform_outbound_preflight` and `failure_type: CalledProcessError`.
The retained report does not identify the checked command. Eleven offline
scripted-subprocess controls reproduce that attribution gap; they do not identify
the CI cause. Native Windows then fails in `initialize` with
`RendezvousUnavailable` while awaiting its partner's bootstrap artifact. No new
pairing-retirement cause, successful cross-platform pairing, selected path or
receipt is demonstrated. The earlier `supervisor_pairing_retired` cause remains
unproven; the new exact-actor diagnostics were not reached in this run.

D is assigned bounded, fixed-literal startup failure-site attribution with exact
exception identity and privacy controls. A extends the existing test diagnostic response with bounded workspace
bootstrap metadata. Startup commands, retries, checks, deadlines, cleanup and
successful report shapes must remain unchanged unless a separate reproduced
defect justifies a reviewed repair. No additional live probe or heavy local build
is introduced. Native pending-action recovery remains unavailable; document-bound
authority and positive resource-owner retirement remain separate prerequisites.

The follow-on startup patch `5b28833` adds a separate
`preflight_failure_site` with eleven fixed literals, tied only to the exact
exception escaping a checked Android startup/environment command. It preserves
the previous phase, exception type, error code and pairing diagnostic fields.
Successful reports omit the new field. Command order/count/options, fatal guards,
the 600-second boot deadline, polling interval and cleanup are unchanged. The
lead reviewed the complete patch and reran **211 focused cases**, all passing
with zero skips, including the actual scripted startup and report paths, stale
and foreign exceptions, cleanup substitution and private-data exclusion.

The separate test-only patch `b237e47` extends the existing
`recovery_diagnostic` response with bounded workspace bootstrap metadata. It
reads at most nine workspace rows and 65 rows from each of five other tables,
then projects at most eight workspaces and 64 rows per kind with explicit
truncation. Attempts cap at 32; states/reasons are fixed literals and times become
due/future/terminal classifications. Identifiers, documents, keys, certificate
material, message text and raw errors are omitted. Incomplete/malformed reads
remain unknown. The unchanged failure path makes no additional RPC, sends or
reconciliation call; its 25-second bound and original assertions remain intact.
The lead reviewed both changed test files and reran **30 offline cases**, all
passing with zero skips. These include privacy, limits, cross-workspace presence,
malformed inputs and bounded read-only collection.

Neither patch identifies or repairs the underlying CI failure. Complete
exact-source local and full CI qualification of the combined candidate is next;
the passing focused controls are not native or cross-platform acceptance.

The previous shared checkpoint is `33d30884ef900e6649c7fcec80e2eb7ce9fef83b`
(tree `f6168f0d8600cefc2078ff85113f9aecf543b04a`). Full manual qualification
[42745577407](https://github.com/ahouchens/mesh-chat/actions/runs/42745577407)
completed **failed** at 03:17:11 UTC on November 10. All six families and the
native `full` workload were selected; duplicate PR run `42745583983` was canceled.
There is no aggregate pass or release/default promotion.

Exact-source local SDK staging and strict policy types pass. All **3,784 policy
cases**, **694 Python plus 12 rendered UI cases**, and **nine Windows boundary
cases** pass with zero skips. Policy takes 393.61s and includes all six installed
runtime-SDK lifecycle cases, all 33 independent admission/restart cases and all
90 controller cases, separately checked in the XML.

The lead independently reconstructs the corresponding CI policy/UI inventories,
the complete retained Windows report set, Android's 52 emulator and 62 JVM cases
with 17 artifact bindings, and both direct platforms' 25/10/12 cases. All pass.
The actual frozen Windows executable is 54,592,111 bytes with SHA-256
`e27b71dea27686005252a12da03403544073343b48b4457c1c8e33364010a1fe`.
Direct binaries and the absent WebView2 probe retain runner-reported hashes.
Layout is runner PASS with all archive entries hashed; images were not retained
or visually reviewed locally. These results do not establish successful OS
authentication, cross-platform receipts, media or physical-device qualification.

Both actual native peers fail in `direct_supervisor_owned_pairing_windows` with
`PeerFailure`, `supervisor_pairing_retired` and the new fixed diagnostic
`failure_site: pairing_status`. Android gets through settings, offer receive and
answer admission before observing terminal pairing state. The previous Android
`invalid_request` does not reproduce in this run. The status projection does not
identify why the pairing retired; source and guarded offline diagnosis continue.
No timeout, authority check, payload validation or workload requirement is relaxed,
and no additional live relay/TURN probe is introduced.

This candidate includes the ordinary-host containment, independent restart
regressions, fixed call-site diagnostics and seven-line test-only clock correction
described below. Native pending-action recovery remains unavailable; resource-owner
retirement and document-bound native authority are still separate prerequisites.

The follow-on diagnostic producer `507a1c7` and consumer `d701905` retain the
first retirement-causing transition for the exact pairing actor, runtime,
generation and original source resource. Storage is bounded by registered actors;
the existing payload-free global ring and ordinary status projection are unchanged.
Only authenticated private qualification status for `retiring` or `retired`
exposes `retirement={phase,event,reason}` with strict fixed literals. The controller
retains actual `pairing_state` and the validated optional `pairing_retirement`
only for the same active status exception. Missing or stale bindings remain
unknown; no identifiers, timestamps, exception text, SDP, keys or URLs are exported.
These observations neither change execution nor prove physical cleanup complete.

The lead reviewed both immutable patches and their tests. C reports 172 focused
passes, including 32 new diagnostic cases; D reports 133 controller passes and
186 combined producer/private-port/controller passes, all with zero skips.
Guarded actual-service controls distinguish invalid offer, native answer failure,
gather deadline, execution pause and cancellation; first-cause retention survives
later `ineligible` reconciliation and global-ring eviction. Foreign/stale bindings,
capacity, successful handoff omission and privacy are covered. Native answer errors
can map to `invalid_document`, so this reason alone is not malformed-signaling proof.
Full exact-source qualification of the combined candidate is still required.

The previous shared checkpoint is `a3b6ebc5836128a39bb1cd98bcbca39410f00d42`
(tree `cfb4d1e92e819193a98f5f62995d0c79fdad3432`). Full manual qualification
[42736168066](https://github.com/ahouchens/mesh-chat/actions/runs/42736168066)
completed failed at 01:58:59 UTC on November 10. Retained selection confirms all six families and native workload
`full`; duplicate PR run `42736166905` was canceled. Exact SDK staging and strict
policy types pass locally, followed by **3,739 required policy cases**, **675
Python plus 12 rendered UI cases**, and **nine Windows components**, all with
zero skips. The policy run takes 437.19s and includes all six installed-SDK
cases omitted from workers' earlier focused runs, plus all 19 independent
profile-recovery cases. The lead separately checked those cases in the XML.

This source integrates B's unused internal-wrapper cleanup, C's pure exact
lifecycle-completion lookup, A's sealed private recovery ledger and admission
correction, D's independent regressions and the narrow Android generated-output
ignore repair. Independent review reproduced invalid non-selected lock/unlock
requests stranding later valid actions; correction `874db1a` rejects those new
requests before admission. Proven fresh pre-effect denial releases custody;
denial after an earlier uncertain effect preserves it until explicit recovery.

The first local attempt exhausted disk: 675 Python UI cases passed, six rendered
cases failed with database/disk-full errors, and policy execution aborted. Those
logs and reports are retained. Lossless compression of verified worktree files
preserved content hashes/Git state; the complete repeated gates above pass.
No source or evidence deletion was used to change a result.

Native pending-action recovery remains unavailable. C's reviewed direct-JNI
design can share native Started/dispatch authority, but document-bound ingress
and reply delivery remain separate prerequisites. No native wiring, successful
OS authentication, renderer-crash recovery, public capability expansion or
release/default promotion is inferred from these component passes.

The lead independently validates all 3,739 CI policy cases, the 675/12 UI
boundary, the complete retained Windows report set, Android's 52 device and 62
JVM cases with 17 artifact bindings, and both direct platforms' 25/10/12 cases.
The frozen Windows executable hashes to
`076ebfc0b883647fdbe52e742d2e7e8a78bc81c6d78156b42249af64bd5c4fed`.
The direct binaries and absent WebView2 probe remain runner-reported hashes.

Native interoperability now passes source/artifact admission and reaches
`direct_supervisor_owned_pairing_windows`. Android reports `PeerFailure` with
`invalid_request`; Windows reports `PeerFailure` with
`supervisor_pairing_retired`. The phase spans multiple calls and does not identify
the root cause. Offline payload-path controls pass with explicit native/mailbox
doubles; no extra live probe or cross-platform receipt success is claimed.
D's fixed-enum failure-site diagnostics `539d5b2` are integrated at `918131a`.
Eight literal sites bind to the exact active exception; successful calls clear
the tag. Requests, checks, deadlines and workload are unchanged, and reports
include no sensitive payloads. All 90 controller cases pass in the attempted
local qualification described below; the native CI cause remains unproved.

A/D independently reproduced an ordinary-host cold-restart regression introduced
by the protected dispatch fence. Containment `4018fca`, integrated at `197392d`,
restores prior behavior only for ordinary catalogs without protected-admission
authority or private evidence. Configured catalogs use the sealed monotonic
`host_profile_admission_policy/current` authority; missing ports or a new Core
UUID cannot downgrade it. Existing ambiguous dispatch slots remain protected.
D's `fda1283` and `cf2d0e2` regressions are integrated at `6ab9d92`; all 33
independent cases pass locally with zero skips. A reports 182 focused passes,
with six installed-SDK cases omitted from that focused run. New exact-source
staging and full gates are still required. This containment is not a native
owner-retirement protocol, migration of old ambiguous protected catalogs, or an
older-binary rollback guarantee.

Candidate `918131add72471b99631b76a04a150f8fb89b873` passes exact SDK staging
and strict policy types, but its first complete local policy attempt is **not
qualified**: 3,777 pass, six fail, one setup error, zero skips, in 430.98s. Five
SDK-upgrade failures report disk-full or unavailable database files; npm's setup
exit maps to `ENOSPC`. All six installed runtime-SDK lifecycle cases, all 33
independent admission cases and all 90 controller cases pass within that failed
run. Original log, XML and source-bound collection inventory are retained as
`containment-policy-attempt1` artifacts.

The separate eight-person workspace case reaches an assertion with seven sends
instead of one after 5.810s. Its recording network leaves sends unacknowledged;
the scheduler retries all due deliveries after five seconds, and the observed
extra payload includes an older manifest. No workspace-specific disk exception
is present. A controlled module-local clock run passes the entire scenario with
one decline decision. Advancing that clock past outstanding due times instead
produces one new decision and 15 old manifest deliveries with original logical
IDs and exactly incremented attempt counts. The relevant service and test sources
are identical between `a3b6ebc` and `918131a`; the containment did not introduce
this behavior. The bounded test correction pins only this scenario's workspace
clock, keeping production retry behavior unchanged. Correction `938d7ed` passes
four focused cases, including existing retry and due-batch controls; a separate
5.1-second real delay also preserves exactly one decline decision.

Explicit user-authorized cleanup removes rebuildable Gradle/pip caches and the
stopped Mesh test emulator's old Quick Boot snapshot. Current emulator data disks,
configuration, source and qualification evidence are retained; free space reaches
1,899,499,520 bytes immediately afterward. Full exact-source policy, UI and
Windows qualification remains required before the next shared push/full CI.


The previous shared checkpoint is `733c38b0d084435557ae1d40e640038c8f3e1aa2`
(tree `c6f51445f0049b42b95138c2c168ee5394475c22`). Full manual qualification
[42728488792](https://github.com/ahouchens/mesh-chat/actions/runs/42728488792)
completed failed at 01:04:44 UTC on November 10. Retained selection confirms all six families and native workload
`full`; duplicate PR run `42728497275` was canceled. The lead independently
passes all 225 consumer regressions, then exact SDK staging, strict policy types,
**3,650 required policy cases**, **670 Python plus 12 rendered UI cases**, and
**nine Windows components**, with zero failures/skips.

CI policy independently reconstructs all 3,650 required cases with zero skips.
Windows also independently passes strengthened normal bootstrap, public SDK
pairing and two authenticated receipts, packaged WebView2 pairing/transport and
service recovery, native control/lifecycle and nine boundary components. Desktop
archive `13724620154` has SHA-256
`c19f1ff5d70b109e48a8a6a6f5c5818083c8bedba85305427645906f0f57d32f`;
native archive `13722764946` has
`182dcd4752844ac050d6d0afbf0a97eb1d25c08674f1efa52d35618d6d74a88f`.
The exact frozen executable is unchanged from `d0babe9`, independently hashed as
`3a4c634df666abe2d8db33838fc74b39858089fe08502e185ac225718f179d10`.
The source-bound report set is a new run; no older report is relabeled. The
WebView2 probe digest remains a runner claim, and neither Windows result proves
selected paths, Android receipts or physical execution.

D's repair accepts the exact signature protection value, whether rendered
symbolically as `signature` or numerically as `0x2`. It does not mask extra flags.
The actual decoded APK manifest and negative authority/process cases cover the
failure; production manifests and runtime behavior are unchanged. Android now
independently passes **52 exact installed-device cases**, **62 JVM cases** with
zero skips, and **17 distribution/binary hash bindings**. This includes both
ordinary app-owned independent-consumer cases, Maven publication, application
lifecycle and cold-process restart. Both direct platforms independently pass
25/10/12 transport/recovery/setup cases. The separate native interoperability
gate failed before Android preflight: source/artifact admission reports
`RuntimeError`. Exactly 25 downloaded runtime-host publication files were outside
the generated-output ignore rules; D reproduces the clean-source rejection in
an isolated Git checkout. The Windows partner later reports
`RendezvousUnavailable` in initialization. No cross-platform receipt result is
claimed. Successful OS credential UI, media and physical execution remain open.

D's narrow `.gitignore` repair `975a034` is integrated and independently passes
all 50 native-evidence checks, including rejection of tracked source changes,
unrelated untracked files, adjacent host source and wrong revisions. Source and
artifact validators are unchanged. A new exact-source CI run is still required.

Previous full combined qualification
[42723779984](https://github.com/ahouchens/mesh-chat/actions/runs/42723779984)
completed failed at checkpoint `d0babe9a137bd49c79eb0bbbe8849b942b3632f7`
(tree `66fe66421328f2c75e21b0729f9ab9878a5ae8ab`). Retained selection independently
confirms all six families and native workload `full`; duplicate PR run
`42723762938` was canceled. Exact SDK staging, strict policy types, **3,612
required policy cases**, **670 Python plus 12 rendered boundary cases**, and
**nine Windows components** pass locally with zero skips. The full policy rerun
takes 397.23s. The original restricted run had two Bash filesystem-access failures;
both isolated controls and the entire repeated suite pass with normal access.
The rendered UI gate likewise passes after its sandbox configuration-read block.

CI policy independently reconstructs all 3,612 exact required cases with no
failures/skips. Windows retained evidence now independently passes strengthened
normal bootstrap (including two constructed-network observations), public SDK
pairing and two authenticated receipts, packaged WebView2 pairing/transport,
service lifecycle/crash, native control and native lifecycle. All reports bind
to the exact 54,572,232-byte frozen executable independently hashed in its archive.
Native lifecycle includes 100 channel pairs/controls and three cold starts;
these remain control/resource evidence, separate from public message receipts.
The WebView2 probe executable is not retained, so its digest remains a runner
claim. The run completed with Android failure: the verifier incorrectly required
the literal `signature`, while the actual compiled permission was `0x2`. The
runtime-host Maven publication and both independent APK builds succeeded, but
the two new installed cases did not execute. All 50 existing device cases, 62
JVM cases and seven existing APK/AAR hashes independently pass. Linux and Windows
direct transport/recovery/setup each independently pass 25/10/12 cases. Native
interoperability was skipped after the Android failure; no full combined platform
acceptance is claimed.

The lead has integrated C's startup repair `a62ad39` and Android generated-source
repair `44e74a3`, plus D's bootstrap regression gate `62ceee0`. C and A independently
reproduce the real source failure: fresh public profile creation runs on a worker
thread, where RNS and LXMF each attempt forbidden process signal registration.
The repair scopes adapters to those two upstream modules, preserves Python's
global signal API and main-thread behavior, and does not swallow other startup
exceptions. The lead passes **65 focused startup/network/bootstrap/config cases**
with zero skips in 13.54s; A's six fenced offline controls independently confirm
the failure and repair. The repaired frozen Windows execution is independently qualified above.

Android now registers a tracked generated-directory property through the Variant
API. Actual cached AGP/Gradle checks cover debug/release registration, producer
dependencies, all 14 selected Kotlin inputs and the sources-jar archive. D's
independent review finds no blocker; 26 focused distribution checks pass. This
does not replace the actual Maven/AAR/APK build and two new installed cases.

Normal Windows bootstrap now requires network construction in both already-read
post-profile snapshots, with a strict count of two in retained evidence. It allows
the expected `network_interface_unavailable` status, rejects missing/invalid
networks and startup errors, and adds no RPC. D passes 187 focused consumer checks,
including producer privacy/request/cleanup controls and strict evidence rejection.
Exact-source local gates and full CI status are recorded above.
No release, default or scenario promotion follows from these component results.

The preceding diagnostic checkpoint is `d411eb5e8a2bd72e36254011f26c4cbc992ce4a9`
(tree `830d3af24ffb5299a8d76dd48c34d069c338249f`). Its only implementation delta
is D's selected network health diagnostics: `network_present` and a fixed
`service_error` enum from existing snapshots, preserving observation subphase.
No requests, request order, deadlines or public APIs change. The lead passes
**367 focused cases**, zero skips, in 18.02s. Existing broad/Windows CI
[42720210733](https://github.com/ahouchens/mesh-chat/actions/runs/42720210733)
completed failed at **23:35:00 UTC**. Broad verification passes, and its exact
670 Python plus 12 rendered boundary cases independently pass with zero skips.
Duplicate PR run `42720186216` was canceled. This is not full combined qualification.

The independently validated existing snapshots show **both hosts have no network
object and report `network_start_failed`**. The offerer observation is from
`pending_request_wait`; the answerer observation is from `invitation_guard`.
Acceptance returns in ten milliseconds (27,674–27,684 ms), followed by 1,947
completed offerer snapshot reads before failure at 240,071 ms. The missing
network causes contact bootstrap to skip initialization. Its caught exception
is still under investigation; this evidence does not yet establish the precise
startup defect by itself. The source-level signal-registration cause and repair
are now independently established above; the repaired frozen Windows execution now passes the platform gates recorded above.

The preceding full-qualification checkpoint is `677b6bf9e9ea0f50d4465e04cca9f79038632187`
(tree `0e2516336d33d0febd5b152a25ab9b6972f7212b`). Full manual qualification
[42716355520](https://github.com/ahouchens/mesh-chat/actions/runs/42716355520)
completed failed at **23:25:11 UTC**. Retained selection independently confirms all six suite families and
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
Linux and Windows direct transport/recovery/setup each independently pass
25/10/12 cases with zero skips. No overall Android or
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
| INV17 | `partial` | Separate call teardown and transferred-carrier protection are implemented. Renderer tests exercise repeated answered audio/video cycles in desktop and Android modes with substituted media and carrier boundaries. Actual WebView2/Android media teardown alongside shared-policy messaging remains unqualified. |
| INV18 | `local` | Deterministic traces, replay and the seeded simulator corpus. |
| INV19 | `local` | Failed persistence keeps the in-memory denial and never reports durable success; intent-batch and authority-write regressions. |
| INV20 | `partial` | The gate rejects failed, canceled, skipped or missing required evidence; publication re-hashes staged assets against that manifest. A branch-build release qualification executed and passed on setup/MSI/APK artifacts; no tag has exercised publication. |
| INV21 | `partial` | Caller/profile/permission/private-event boundaries, pipe OS access control and Binder caller-derived grants are implemented. Exact `82aaf19` Windows distribution-only consumers qualify normal-host pairing and two authenticated receipts with original-key replay and single records. Android verifies six Binder-consumer and two app-owned lifecycle/cold-process cases. Independent cross-platform delivery/partitions and successful native credential confirmation remain open. |
| INV22 | `partial` | Policy-free SDK attachment and exclusive runtime-owned vault storage are implemented. Remaining packaged evidence must combine concurrent distribution-only clients on one normal runtime, detach/reattach with pending durable work, competing-owner denial and authorized owner shutdown with exact cleanup. |
| INV23 | `local` | Durable enqueue receipts, conflicting payload rejection and stable logical IDs across restart; acknowledgments never change peer delivery state. |
| INV24 | `local` | Explicit `resync_required` for gaps, expiry and authority change; the client consumer clears its position and resnapshots. Long-term retention is not promised. |
| INV25 | `partial` | Public API 1.1, IPC 1 and peer wire 1 are separated; incompatible-major refusal and source-pinned baseline upgrade fixtures execute. Experimental Python/TypeScript archives and Kotlin publications have staged/package evidence. Supported SDK/runtime/package pairs and a bounded upgrade/data window remain undeclared and require exact installed-pair qualification. |
| INV26 | `partial` | Exact `82aaf19` qualifies Windows distribution-only normal-host bootstrap/pairing/receipts and Android independent app-owned lifecycle/cold-process startup with 17 artifact bindings. Android independent peer delivery, successful native credential confirmation, the complete cross-platform scenario and release support promises remain open; distribution assembly is not a supported-release commitment. |

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
| SC17 | `partial` | Pairing cancellation, unapproved restart, native phase retirement and renderer dialog-dismissal/media-cycle regressions exist. Real WebView2/Android audio/video plus adopted shared-policy messaging and authenticated receipts across hangup, refresh failure and pairing closure remain unqualified. |
| SC18 | `partial` | Signed fixtures and existing peers still interoperate; no explicit wire-version matrix. |
| SC19 | `local` | Persistence failure during intent or adoption bookkeeping is tested for safe in-memory behavior. |
| SC20 | `workflow` | The final gate fails on missing, skipped, canceled or stale required evidence for the exact source. |
| SC21 | `open` | The shared-supervisor Windows public SDK pair/receipt scenario passes on exact `82aaf19`; Android independently qualifies app-owned lifecycle. A complete installed Windows–Android SDK/API-only message/receipt, restart, partition and current-authority scenario remains open. Private native qualification calls and historical legacy-bridge traffic do not substitute for this automated public-consumer boundary; physical hardware is not a prerequisite. |
| SC22 | `component` | Wrong caller, profile/scope and private-control attempts are rejected before effects in facade tests. |
| SC23 | `local` | Lost reply, timeout and duplicate request after restart resolve by idempotency key; conflicting payloads fail. |
| SC24 | `local` | Bounded replay, explicit gaps, cursor expiry and consumer deduplication are covered by facade and client tests. |
| SC25 | `partial` | Declared experimental clients, incompatible-major refusal and actual source-pinned baseline upgrade fixtures execute. Supported runtime/SDK/package pairs, exclusions and a bounded upgrade/data window remain undeclared; those exact pairs require installed qualification. A release tag does not provide missing automated pair coverage. |
| SC26 | `partial` | Exact `902b12d` installed Windows evidence verifies two same-application SDK sessions, detach/reattach, refused competing ownership, pending-message/key preservation across owner restart, three clean host exits and one rejected-owner exit. Android verifies SDK detach/rebind, runtime shutdown/restart and cold locked-process lifecycle. Separate consumer-process/caller isolation and exact isolated-helper/resource retirement remain open. Trusted owner shutdown authority is unchanged. |

## Completion boundaries

| Boundary | Status | Note |
| --- | --- | --- |
| Shared policy complete | `partial` | One owner drives the experimental Android and desktop compositions, but manual-pairing parity, Windows-and-Android interoperability and legacy-loop removal are open. |
| Headless messaging complete | `partial` | Android native transport and native Windows DataChannel implementation exist. Historical native Windows durable-message and fault components use legacy bridge policy; shared-supervisor promotion, cross-platform interoperability, the complete impaired fault/receipt matrix and physical acceptance remain open. |
| External integration complete (M5) | `partial` | Authenticated hosts, experimental clients, direct/group composer facade migration, profile generation guards and unused-wrapper removal are implemented with scoped evidence. Remaining work includes transitional renderer policy/bridge loops, private pending-action UI/native recovery binding, actual media coexistence, complete cross-platform public consumers and declared compatibility/upgrade support. |
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
