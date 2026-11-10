# Connection runtime qualification ledger

## Integration revalidation (2026-11-09)

### Cold-restart containment: full CI completed; native pairing remains unqualified

The current shared checkpoint is `994e4b488ba88935569970ac0adfb15c237f621d`
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
C is assigned a guarded offline review of the actual fresh-profile consent,
handoff and adoption sequence. No consent, authority or deadline relaxation is
authorized by this failure; a concrete repair requires a reproduced path.

Retained archives for `994e4b4` / run `42763177698` (SHA-256):

- selection: artifact `13738243733`, `7900cf5803a36a90d56440e272a41e4eefcbb35fb096792e1e3561e2ce0b66e7`.
- policy: artifact `13738781225`, `c9c9038dc1c52a00d237500750b89fef37cbe3bfd854678b1fea355a126b4135`.
- verification: artifact `13739251159`, `38d6c4b209ad66706eb106a4e4912b6f7506d85bb9258e2b183a928ee780cf47`.
- desktop: artifact `13738582329`, `4128aa12db032a0f94b1d1725b74d762fc0eb97ca1ad1455e6fa00962461a8dc`.
- native-windows: artifact `13739250683`, `c5934b9d9ce1ba8e1dc65093cfcbf699f43fadc62b65f79b2dac509c16fd1ce8`.
- android: artifact `13739800523`, `c49ba23ed22e25c4469abf7d6a0e8d0af008cffe06d8cfa082ca8ce26385bf22`.
- android-debug: artifact `13739686333`, `7da888d3f570f06d2088a3a03472d4f919f1b5ff22b1182b16407d15cfa37255`.
- direct-windows: artifact `13739343742`, `bb06a733b08b5b55d2b85e5611dc6a39273061c4183356ded7cd7de04a074e7b`.
- layout: artifact `13738328320`, `259728cb951bd5dc177d518161da73e21655b927b26b0d369d8cba43d1e9163c`.
- native-interop-android: artifact `13738858746`, `ca065176f846ff04cf906e49fdfde81897de5a54a0e034f25ac89edd2278f376`.
- native-interop-windows: artifact `13738619332`, `f52e79fd96f3482931eb95923adf0c7f0082da874e3812ce4a69d0e1c5a5c6b6`.

The next bounded repair adds private inventory `owner_state` metadata while
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
D the consumer; implementation and integrated qualification remain pending.

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

Retained archives for `55e6b19` / run `42758745281` (SHA-256):

- selection: artifact `13735764912`, `96c2e9da2e4b2ae9c86b8ad779fd461812507170a4cc16360f673d8768afa0bd`.
- policy: artifact `13736966320`, `a573f0ca0a710fec57a67ed0c75fac3f0fea999dd2ce57a1d0e846af61658b5d`.
- verification: artifact `13737077521`, `8ce72874b33d69c6cb94905c7a6744517168fb2f302d849a20053b7db89ac247`.
- desktop: artifact `13736559056`, `bfdda1260d10e78e1a416bb87bd0435ab49b83575f3e627ba0b54a017d18b97f`.
- native-windows: artifact `13736623990`, `a6d73c0f399bd48e4002f1b098081f01ceee7172a6cbad57c1e7f392ccbeaeaf`.
- android: artifact `13737148800`, `55919f3e30951bcb5ddd109d90a8141db02450d9f081d9530526e2a41c715cb7`.
- android-debug: artifact `13736834675`, `2f7821f3cddec870d56a605771a7b36dd993f5f79967e13c2c1c04eb2955e98e`.
- direct-linux: artifact `13737872442`, `afd1c6e767ae22fc740bd7d5788197f6bb35cff86042fe94853e5c87d0fa35c1`.
- direct-windows: artifact `13737293553`, `9e42995229a2a686b28836fb209c63941dcd5d15d4dd352d773fb7a841a03137`.
- layout: artifact `13737121127`, `2f4f5fcaeee8711dcf1b424edc5fd00be938e019d26b27fafff21357b9713144`.
- native-interop-android: artifact `13737278035`, `5da76749155accd38f9ef61d8ed1e4e7cd08422bc3bc1174195a78d471702e51`.
- native-interop-windows: artifact `13738210690`, `47370dd328b1e3f74488f465ad74633feb16700482319b8546bea3ad822624d0`.

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

Retained archives for `e7630c8` / run `42752889278` (SHA-256):

- selection: artifact `13733453560`, `b396801fbcbe776f98c859ec47bf301b875a594a8e965dfb73cbffe9849d8ffc`.
- policy: artifact `13734830423`, `d01072c20e4ccba817ccffb5d2bdd63951490cb9fb83bcac66fec3d398851393`.
- verification: artifact `13733714563`, `4b440ca377ec56850fff37aac649f70d9de31e13c0ba9e236bad5b65d2ad6a4c`.
- desktop: artifact `13734058609`, `bc8b8b9cedffca7d345279da54e07eb0f5b11b46ea8bf41ba4fd5a3cf684ed4b`.
- native-windows: artifact `13733494398`, `dc130a6bbfcbac7e5a63a9cbc899d78e42044cd82f552d24d1e6172183abdeb8`.
- android: artifact `13734628215`, `ccd891925b4d62ccf2a3cd0acdf75d8f686ebba8d847b56544d5a9ef1d582e87`.
- android-debug: artifact `13735166312`, `cf2ad9a1b00edcdd2e9cf93ced9df3ac39c864fd08f7c9e18652483028956e0a`.
- direct-linux: artifact `13735067702`, `4dd1079912b6a539eb38fa861407f905ce74524ef7a912a8eb8a1094fe574bf0`.
- direct-windows: artifact `13735451933`, `b3c5ae677b4dfd75ab8f4c0d1d41a325ef5e7661ba49e5bf7c9603c33339e916`.
- layout: artifact `13734232477`, `d0c3a7a576859d610bc052dff6c85e0dee16e864d7a2ccf309386bc2d8614d68`.
- native-interop-android: artifact `13734858003`, `0292b6899f7498bd3255655244e35faa369c51e236a8629658fdb3a342d2be14`.
- native-interop-windows: artifact `13735663069`, `89b9f3db1b4cabc72d4a19a5fe1ee2e685576bc8e55e342b728406ebe7afbb51`.

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

Verified archive provenance for `33d3088` / run `42745577407`:

- selection `13731451753`: `006989282c9c475c29c34e39af4e56e8813480562078dcfc1232ff80f1b21761`.
- policy `13730094713`: `2cbbfcf6e214e982cb79f7180ce14f8531b5e4b2e305ecd46aa3c5a998f216f5`.
- verification `13731651106`: `13b46b53995b7f7b75bf8e1e980cb5e6932cd0c05978f5fbbc11b48f09a30cfe`.
- desktop `13731820168`: `86e5542fbb6a599f5669f4938076bda5c2a2a4587c745af489340842a3f6dd40`.
- native-windows `13730913559`: `dbfd3f6da8704e03f19eb7bd90d05a025558c0f5898387a0cd4bab6475ff3557`.
- android `13732316479`: `433051aeca447ab0a56fdebf1960ed6008191c9f1dfa341eb1201b696cee0cef`.
- android-debug `13732501103`: `4720f056773a6599c2b5680143a3868c64afc2036c40d182beb19b70dc7e10e5`.
- direct-linux `13732506595`: `d33ee0aa26bc1f85c6443b102388460fefc3a4aa47b58d33fee2701fe0affce6`.
- direct-windows `13732925759`: `caa93e06c6285def5c9793d2808b51ba036ef26836f8635d94453de497a084b6`.
- layout `13730823167`: `2af8aebf012d7b1d007439136d0b184767b357dbbcbe99fa2e98bea97dfe39e9`.
- native-interop-android `13732032647`: `cc1ba4e98195f4196a50113e61f800abadb35769fcecc081d09e43ee2e512518`.
- native-interop-windows `13733025004`: `23bd3823a63e54199fdb3b94014a798c470c76460f6ef71cd58be42217b5f5e0`.

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


Verified archive provenance for `a3b6ebc` / run `42736168066`:

- Policy `13727920510`: `d079e9634b359db4cd6c3aed30f57708ff1447bd86969c26046ef02f9b71742f`.
- Broader verification `13728305269`: `e9e978d9f11882a47752917126dd71aa71badd44b8b3545ba357cd003a08c6d8`.
- Desktop `13727077357`: `a97115ea33a8fb47889d0b4f657b979626c43bef31b624d135430aac3585595a`.
- Native Windows `13727601349`: `852d26d82fb42327887f2c471fc758cd16dab820ae5565b662c74c5191dce2d9`.
- Android qualification `13727309152`: `2bfd0b3106b38215fa171d3686add30f3d3bc4b627e53ba01b220aca3a96bb3b`.
- Android debug `13727833012`: `55706a2636077f7c5897e400f61142b564745264efcbdf431548e02d394bef16`; all 179 entries hashed, only required small evidence retained.
- Linux direct `13727244143`: `9eddf81c5343540cc4b013fce29bf1817a6de64aa897180993f0ae2d57d8cb6e`.
- Windows direct `13728303072`: `53b269e06be79e846f4bf105924ee8eaa9c748cd07ac13bbad782ce2492e928f`.
- Failed native Android `13728445860`: `5ae962e9bbf71124ad94df8b5ed78e8ff94ccbed3f7c8084ad553f72942b9034`.
- Failed native Windows `13727514108`: `a226951f6bb2728ff0157848abd50704d9689c0c00da1fa01d672e077f0cf2b6`.

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

At `733c38b`, Android qualification archive `13725011496` has SHA-256
`b2d6986d76a80af40311cef5c2713249c8f9bb9d4cd679544f4d3df1032bbf44`;
debug archive `13724901774` has
`d89a7454577709399c6e6eddea571657bd4b3acec705b2690132849140b46735`.
All 179 entries are independently indexed and hashed, including the 17 artifacts
required by the report. The five device suites contain 21 WebRTC, 10 signaling,
13 Core API, six separate Binder-consumer and two app-owned independent-consumer
cases. The last suite's run ID is `09c6cd6337c541b4a2cff8a35eb91a71`.
Source consumer files and Maven metadata are independently checked against the
exact Git source and archive entries. Broad verification archive `13722974519`
has SHA-256 `fcf37cd3cd4388b5645d2d1768e9f1c0b4795454f672070dce35272f57d0e2bf`;
its 670 Python and 12 rendered cases independently pass. Broader automated
completion remains a runner summary because full-suite XML is not retained.

For `733c38b`, Linux direct archive `13724986632` has SHA-256
`0666d1ca890d3fd3dc3391b444b80c6329d7905e371b0a376426f27bda88d9cf`;
Windows direct archive `13723939962` has
`ed158b0f846b5d869d7847c09c99ba22c0fb2e71aadf709184ddd3f21b21e8b2`.
Both independently reconstruct 25/10/12 required cases without skips; native
binary digests in these report archives remain runner claims.
Failed native Android archive `13725042152` has SHA-256
`7a97177b8beb5d1b4bc4fff48229ab393a1ad54222cfd7aff1632caf8c5be586`;
failed native Windows archive `13724858507` has
`327055445002760baf86cfa33288f991e20cb7dfc85679a2af64371a1630b5c2`.
The archive metadata binds these failure reports to this run/source. Their
phase/type reports establish no paired scenario execution or aggregate pass.

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

At `d0babe9`, desktop artifact `13721134266` has archive SHA-256
`cc202238f51514d94ccb7a12f233d4231edb7363c3b3e4cb58cb3340a82ad33a`;
native artifact `13720154714` has archive
`b871303d9a8f80b4f64d63da531c4bce05eb5d03e4000eb61ed4bd399e609a21`.
The frozen executable SHA-256 is
`3a4c634df666abe2d8db33838fc74b39858089fe08502e185ac225718f179d10`.
Public pairing run `88833827eec044f898a750f1e59ca68d` takes 40.384s and verifies
two fresh profiles, explicit decisions/transfers, disabled alternate paths,
relay-only request with broker consent, two authenticated receipts, key replay,
single inbound/outbound records, two clean exits and actual DPAPI/EFS.
The exact source, installed SDK archive and nine consumer source files bind to
the bootstrap and same executable. This is not selected-path, Android, impairment,
media, physical or SC21 qualification.

At `d0babe9`, Android debug artifact `13723116006` has archive SHA-256
`d9ab9c343e5f4cdad9958247a0140525802571547b443b5b9022c94305d685c9`.
The complete 174-entry archive index independently hashes the original consumer
APK as `1fa7be1327a6538286c800b55f6c573c16541e97f0446578105e8150f17a55a1`
and its raw manifest as
`26f95238c753ad13c543b6c570e4397a3975983c35f9aeca4f0fafb1f7e131ce`.
The tiny locally derived manifest-only ZIP is not an installable APK. Disk
recovery removed only extracted auxiliary logcat/obfuscation-map copies after
recording their hashes; original CI archives, required reports and inventories
remain available. This preserves report admission evidence, not unexecuted tests.
Direct Linux archive `13722158093` has SHA-256
`6d001b2390559b2116c126be95b9f7117d75790dac8dd4916942065bb3ba4a53`;
Windows `13723257746` has
`a6ee2dcb37183792f394d5eb024d0dd4b21566c7792d64874beb17b79f407eef`.
Their binary digests remain runner claims because these report archives do not
retain the native binaries.

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

Local policy qualification is `5d82b74d14c549c1a01aa6bd7316bf33`, 360.88s
wall time (352.138s summed case durations). Exact App/Core wall time is 44.33s;
Python XML SHA-256 `52330790dcf3d7de113a7978261221118d9bf2e2ad3ddb71711fef3cc27ab2a7`,
inventory `b635bc5600be201867defc4f2e24f2db14aecc0a245a681f8f7ab84edda0ac85`,
rendered XML `3a3155e8be51675ae685117845d6b0983e4229debcc38f206183ea399ad698db`.
Windows wall time is 2.82s; XML
`3eafbd3befcdc23dadd6bf77284019fa1b93aa3d21e976e246123e6ee5dc532b`,
inventory `b0cf12b7e390b061552cbec72cdac73808282f128096b85c3cef3391b8dd84ff`.

Selection artifact `13717079674` has archive SHA-256
`67972eb4fc0e4ecdd70d30cda615e4dd6581ae7fada036c332dff4ba3d83d255`.
All 146 validator source files are pinned to the candidate. These local gates
and selection checks do not replace actual platform execution.

At current source `677b6bf`, policy artifact `13718192421` has archive SHA-256
`d8dad64d5240896991a2a10f48550122216a92a0303089535778c730eae90c13`;
qualification `67d805f683724ad0ba7bbc28e569d1cf` independently reconstructs all
3,554 cases with zero failures/skips. Verification artifact `13719560274` has
archive `a4c3d17ce53960a7cb867210de757a9a4464817f878250dcfbdd9c9df6169e4a`;
its boundary XML/inventory independently pass and broad runner summary passes.

Desktop artifact `13719625071`, archive
`6ed700b04d793ba44cb4e2fce4ff1280f49f04241e502ae9bbb9333e70c5ec2a`,
and native artifact `13718691952`, archive
`c730a2bd0d585357bd0a24b441256ab1d6036eb5ad3e2cfbdfeb2e6ed9128131`,
bind nine passing components and normal bootstrap with actual DPAPI/EFS to the
54,571,189-byte executable SHA-256
`3a1f53c1e2b3abaf1fb4f2135d64ada8af965ee93affdaeaeae7077e08f185c9`.
Bootstrap run `9295e4492f7644aabd81f8bda43eb91b` uses the retained SDK and
source-verified consumer files. The failed pairing diagnostics pass the exact
pinned strict parser; report attribution comes from the verified artifact/run,
not intrinsic success bindings. Later packaged gates did not run.

Android qualification artifact `13718793500` has archive SHA-256
`621676d733c640794d99ffb08c566f512b097e5e3ef6a510192819ff35ef35ff`;
debug artifact `13718843412` has archive
`a592d5df18f6b42af8aae2372132f9ddfeec06c536852fcb166700cf236828d5`.
The lead verifies exact-source inventories, all 50 existing case reports, seven
binary hashes and 62 JVM cases. Independent-consumer inventory is absent after
the Provider registration failure; no build or execution of those two cases is
claimed. Native interoperability is skipped after prerequisite failure.

Linux direct artifact `13719651714` has archive
`ef94c75b703322bcebd6b6e4789a54ee00b8cd9ac73ef8ac86c1f1e046f0c101`;
Windows artifact `13719178444` has archive
`b678e30551ed2ec07b06b47b473cb32bef22b4ad86fe82af4a42a1668386774e`.
Both exact-source report sets independently pass 25 transport, ten recovery and
12 setup cases, with zero skips. These report archives do not retain the native
binaries; their reported binary digests are runner claims.

### Completed checkpoint 577250e: evidence and subsequent repairs

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

The policy qualification ID is `5cad48cebef44411abbfc09cb9af6463`;
wall time is 338.71s (summed case durations 328.898s). App/Core wall time is
41.01s, with Python XML SHA-256
`ee6d379fe166e60b36cf63d3ccd5474d705f6258ff2fd075e39c1d23dbf9f89e`,
inventory `6cf45efc09e08c61267ec9697ca0c3387844465bf62613096420e694e92c3dba`,
and rendered XML `8e8b98bb66593b3e4b06f4428f08715b8ff872e95786f3369d784cc99f68c658`.
Windows wall time is 2.18s, XML
`405ecd33d9d66828c037fd4761b1dcf7ee00afb2a1d7fba04f4d6c3f8946995c`,
inventory `6e971b93a93995ed2dd79daefec1deb9f37532ae1d232445691e98a97920e216`.

Selection artifact `13715257587` has archive SHA-256
`1c949a81cd1b53082607b10897fcb2d2085cc78384e099c00fdd971d2cb7f601`.
The lead retains 146 validator source files pinned to the candidate and rebuilds
evidence from the actual reports. Platform passes remain limited to the
independently validated subsets below.

Current CI policy qualification `3f26edfa8dd24644a7909b17e009b92f` is
reconstructed from artifact `13714838414`, archive SHA-256
`ce16f74dcba6b3d7cee497208aeded2156f61b39b4903fdf974a65c020b56c37`.
Verification artifact `13715489962`, archive
`81ad273befe1bea8e8a83c36a6c0cdc8ea75f403b9f9b66d6559fdf76e7f2c59`,
contains the independently checked boundary and passing broad runner summary.

Windows desktop artifact `13715963206` has archive SHA-256
`ab1cd7f35c59cc80d5ac57d18ed16b3f341d78aca71eaec45dd74c80d3e25bb6`;
native artifact `13716975306` has
`097e1704312dcfc3c84a62f882912068efee974c4fae0e29f1d1ce2dea0afaaf`.
All entries were independently hashed; the tested executable is 54,570,175 bytes,
SHA-256 `5fe19776a8b7ac90325c663e8664d9982bc65e716990319e749812c873cbd59e`.
Normal bootstrap run `74ca552be65e450ab7923d6b75a57ef6` binds that runtime,
the retained installed SDK and all nine consumer source files. D separately
validates the failed report with the exact-source strict failure parser; this
is valid failure evidence, not successful pairing qualification.

At `577250e`, Android debug artifact `13717720185` has archive SHA-256
`d5bab65c4687de051c51fc70c38ac34eac0fea1ea4a17e1ad82cbde0f91adef3`;
qualification artifact `13716109078` has
`be31503f0244a616302322def92e4f4e1caaa54914fd19d243f7435f5ce36206`.
The lead validates every one of the 50 executed case reports against its exact
inventory/run identity and retained APK/AAR hashes, plus all 62 JVM results.
The absent `core_independent` inventory is explicitly excluded, not counted as
passed or skipped. The Gradle error is at runtime-host `build.gradle.kts:32`:
the actual source-set class cannot cast to the legacy `AndroidLibrarySourceSet`.

Linux direct artifact `13717875392`, archive SHA-256
`ee5a42cebf2d274760a9b07b79d0fa89c02967ed94ceca483f4898d9088072eb`,
and Windows artifact `13716998197`, archive
`26b24c473d9afe0a7a855b4702e7692874833926c100ab6dcf6ee3cf56896b5b`,
each independently validate 25/10/12 transport/recovery/setup cases. Their binary
digests remain runner assertions because these report archives do not retain
the tested executables. No full-gate or cross-platform receipt claim follows.

### Clean Android consumer integration and Windows bootstrap evidence

CI `42704405112` completed failed at **22:05:03 UTC**. Each direct platform
independently validates **25 fabric, ten recovery and 12 setup passes**, zero
skips. Linux artifact `13713568714` archive SHA-256:
`4eb7044f09e276f19d8be667a45ebd7470c036b9d3c85b4918817a06e8a88ff8`;
Windows `13715525750`:
`1918afbc35ca8a325e6ec338ec817fc8e7d40225bc4e8e94752138d192a78972`.
These report archives do not retain their native binaries; binary hashes remain
runner assertions. Native interoperability was skipped because prerequisite
qualification failed.

Android's retained evidence independently verifies **47 successful case reports
and three failures**, all 50 required cases present, plus **seven APK/AAR hashes
and 62 JVM passes**. Failures are native-offerer cleanup in
`nativeOfferCanConnectToChromiumWithReconnectControl`,
`repeatedChromiumMediaCallsPreserveNativeOfferedMessaging` and
`productionDesktopTransportAnswersNative`: `native_webrtc_cleanup_pending`.
The aggregate fails; no overall Android cleanup/platform acceptance is claimed.
Debug artifact `13714895133` archive SHA-256:
`817cef86bb251339a57cbe26035fc13420e488cec8a3e0531e1183d4f6047871`;
qualification `13714326555`:
`00989330164c5fa83daf0b517df3372471e54ac0821ccc35d2b4b744657fef1f`.
The archive was hashed in memory; retained text/XML/JSON was losslessly NTFS
compressed. C subsequently corrected the shared cancellation test helper to consume the
expected pending signal, then require the existing unwind wait and actual
disposal acknowledgment, without weakening production custody.

Subsequent source `ba2b12f` integrates D's bounded diagnostics `379d948`, typed
readiness correction `3032436` and failure-only current-state probe `92cb643`.
Lead focused consumer/matrix/selection checks pass **324 cases, zero skips**, in
14.46s. Real archived SDK requests reach the production framed parser and current
policy projection for readiness; native effects are simulated in that regression.
Synthetic failure-path tests exercise actual Node producer control flow and
privacy filtering, not actual peer delivery. The probe uses at most two concurrent
existing public queries, two seconds each, retains the original failure and
requires host shutdown. The Windows timeout's cause remains unproven.

C's correction `f161626` changes only `NativeWebRtcInteropTest.kt`. An actual
compiled-host JVM control with explicit Android thread doubles reproduces the
old helper skipping its creator wait when main-thread close reports pending.
The corrected flow reaches the wait, retains custody after creation unwind, and
requires disposal acknowledgment before off-main close returns. The edited
instrumentation source separately compiles against cached production classes.
It retains existing timing bounds, adds complete zero-accounting assertions,
and preserves the original exception while attempting all teardown. No production
code or emulator results change in this local evidence; all affected cases must
rerun in CI. Temporary ownership of this single test file returns to D.

Lead `72a531937653de41a2368fc4356cc8e91d30aaed`, tree
`03b31043171811d4c1f7ea42dbabb92de9cab41d`, integrates the tracked group SDK
import repair `1866660` and reproduced Android runner stdin repair `b59f951`.
Exact SDK staging and **3,494 required policy tests** pass, zero failures/skips,
in 341.81s with only service source on `PYTHONPATH`; qualification
`7b71e3df88b042259cdf8f4d927b00a9`. The exact boundary passes **670 Python plus
12 rendered cases**, and **nine Windows cases**, zero failures/skips. This
checkpoint is local evidence; it has not been platform-qualified.

The original Android runner returned success after fake ADB consumed the second
case from stdin. Its new real-Bash regression fails before repair and proves both
ordered launches afterward, including force-stop/process absence checks and
strict report parsing. That is runner control-flow evidence, not Android execution.

At CI source `32cc1d5`, the lead independently validates the retained **670 Python
plus 12 rendered boundary cases**, despite the later broad collection failure.
The normal installed Windows bootstrap also passes: fresh empty host, keyed
profile create/replay/conflict, reopen, clean exits, actual DPAPI/EFS. Bootstrap
run `93ed168a6cdf4eadb59d7d120a963087` binds the retained SDK and all application
file hashes to executable SHA-256
`281ced48e2370832d667791143a5a576612c4ec071ff6f78e97db8320515f2c8`
(54,571,611 bytes). Desktop artifact `13712738380` archive SHA-256:
`9bee34e0b635a2e5f4bb444633bc5cdcdbda32c06870095bef28eb91e4d6da9d`;
native artifact `13712838210`:
`b6405cec1f199c0bd7ee5dd8277811840aead246970ab64714531910e41b9ed9`.
All archive entries were independently hashed in memory; no binary extraction
was needed. Nine Windows component cases and runtime materials also validate.

Public pairing **fails**, with `explicit_approval`/`unavailable` after 242.10s.
The broad phase does not identify whether invitation, approval, relationship or
readiness stalled. D adds bounded diagnostics. A separately identified a latent
consumer error: `connection.query` is unsupported; readiness must use typed
`connectionSnapshot()`/`connection.snapshot`. That mismatch is not yet evidence
for this timeout. Later packaged traffic gates did not run. No receipt or SC21
qualification follows from the passing bootstrap subset.

### Repaired group checkpoint dispatched

Full manual workflow [42704405112](https://github.com/ahouchens/mesh-chat/actions/runs/42704405112)
completed failed at source `32cc1d5765a1ae1a3ad91e752e341b95cbce2e40`, tree
`cae703b3360004bdd0bf2d0b55793fed7efafe08`. Duplicate PR run `42704390818`
was canceled. All 143 retained validator source files are pinned to this source.
There is no CI success claim yet.

The selection artifact independently confirms all six required families and
native workload `full`: artifact `13711994100`, archive SHA-256
`43f3a22b282768059cb72ed56293fff4e11e0b38738c4940ac0b1e30e97e43de`.
Policy and broad verification subsequently **fail test collection** because
`test_core_group_composer_sdk.py` imports the standalone Python SDK without
tracked import setup. The local policy command below explicitly added
`sdk/python/src` to `PYTHONPATH`, masking this clean-run defect. Its executed
results remain valid only for that environment; they do not qualify clean CI.
The failed policy archive `13712074019` has SHA-256
`9c23a28ee7a0de7742ecebc0d103a066a4edd4e30ddfbccba766f1306afd429d`;
verification `13713062285` has SHA-256
`c827efcf494eb32d8ad7b3430786054d7aad30bc20bac2b98f2ad1481844b8fb`.
The policy archive contains no passing suite execution. The verification archive
also retains the earlier passing exact boundary, independently validated above;
its broad automated summary remains failed. A's isolated setup repair is now
integrated and locally requalified at `72a5319`.

Exact SDK staging passes. The full required local policy passes **3,463 tests,
zero failures/skips**, in 365.09s; qualification ID
`9328e6cfe05c44c8aff5572e7bfbd497`. Exact Windows boundary passes **nine cases,
zero failures/skips**, in 2.50s, XML SHA-256
`549c7ff85d7c703a5958de2836e3c649927e7fc4354118549ebcc0ed985d62ea`.
These cover in-process policy and Windows named-pipe/DPAPI components, not
frozen/EFS execution or independent peer receipts.

At ancestor `986815f`, the exact App/Core boundary passes **670 Python plus
12 rendered cases**, zero failures/skips, in 56.66s. Python XML SHA-256:
`06c18bbbf3ffb6be41a034fc53f670b34c290d033d46ac037b3b6884cbd2e4ef`;
rendered XML: `22c3ee116023b415b80da6a4d2ceb6d83f21fe0ea85b6d3556322c322d8dc514`.
Only the static Binder guard changes between that source and the dispatched
checkpoint. Actual-source Kotlin SDK checks pass **24 JVM tests** in 0.124s.
Windows writable-settings/consumer controls pass 160 cases; repaired Binder
guards pass seven cases. The earlier full policy at `4da0ccf` had 3,460 passes
and one stale Binder guard failure. An earlier disk-full attempt was aborted
and supplies no qualification result.

The dispatched checkpoint includes D's group vectors and real rendered durable
composer cases (`03f1ac3`), public writable Windows settings (`7d0c055`), Binder
guard repair (`69ef1c8`) and C's public Activity dependency export (`53225a1`).
D's independent Android consumer `cd08903` is deliberately excluded, pending a
separate checkpoint. It has source-level tests and C review only; no built
publication, installed Android, OS credential or cross-platform receipt claim.

The independent Android source is subsequently integrated at `75b7719`.
Lead verification passes **401 consumer, matrix, CI selection, interop controller
and Android report cases**, zero skips, in 22.73s. The required Android inventory
now includes 52 cases and 17 artifact hashes, preserving the previous 50 cases.
C's source review is accepted. Actual Maven publication, APK assembly and the
two installed lifecycle cases remain pending a separate CI checkpoint.

### Atomic group integration and completed profile CI

Subsequent lead source `a175ae5` integrates C's standalone Android host
`c2fc072` and safeguards `dfc47da`, plus B's composer owner-retirement fix
`839c076`. Lead host/profile checks pass **38 cases in 5.03s**; actual-source
key-policy/native-custody JVM checks pass **26 cases in 0.171s**. The cached
compiler uses explicit native/platform doubles, not Android execution. B's
shared App/controller regression selection passes **80 cases in 16.01s**,
including queued work after navigation and posting revocation. D's required
boundary inventory and real rendered fixture corrections are still pending.

Lead source `02f83b8` includes A's atomic group producer `76ed4fb`, its additional
expiry/target controls `306feb3`, B's gated UI `86366d0` and D's explicit
relay-only Windows producer correction `2cf3f41` (applied as `b156300`). At
`5f9f614`, exact SDK staging passes, then **275 producer/contract/installed-SDK
cases**, **41 UI/controller cases**, **51 TypeScript SDK cases** and strict
model/reducer typing pass. Relay consumer/matrix checks separately pass 159
cases, no skips, in 13.09s. The exact boundary at `02f83b8` is **not passing**:
663 Python pass and one fails the missing group-operation vector inventory;
nine rendered cases pass and one fails the old group-send retry fixture.
D owns these independent test repairs. B owns a queued-send-after-navigation
correction discovered in follow-up review. No complete group acceptance yet.

Profile CI `42693457737` has finished failed. Both controlled direct platforms
independently validate 25 fabric, ten recovery and 12 setup passes with no skips.
Linux artifact `13710340526` archive SHA-256:
`5248d706fe58efd37f0d45e8cae232f36cb526c7b14129f09a2e50f9957612be`;
Windows `13708739825`:
`b618aac9c476bcc683c6882373e5287c7b237e48d4649c4cdc2af2a26bacfdf5`.
The verification artifact `13709365916`, SHA-256
`037c8c37187968daeab142d63c6f33ca5394888407078ad0af46b356c6120860`,
independently validates all 664 Python and ten rendered boundary cases at
`5ea2949`; its broader automated summary correctly remains failed. Validators
and reports are retained under `.test-tmp/ci-evidence-5ea2949`. The direct
archives retain reports, not native binaries; their binary digests remain
runner assertions. These passes do not qualify later group source.

### Repairs after the profile checkpoint

Run `42693457737` at `5ea2949` cannot pass. The lead independently validated
its policy artifact: **3,379 passes, zero failures/skips**, qualification
`16d5f26166cf411c8bd3bce3487b6f93`. Windows bootstrap failed because its
test confused an authorized profile scope with an existing identity. Android
instrumentation compilation failed on missing AndroidX dependencies and access
to an internal class across separate modules. Broad verification had 4,583
passes, one CSS-selector guard failure and 52 platform skips. Native interop
was skipped; the direct-platform jobs remain pending at this recording.

The Windows assertion repair `e8f73e0` is integrated at `ed1a82d`; the lead
reproduced nine Windows component and 29 consumer passes. Android repair
`d23452c` adds the test dependencies and test-only internal visibility access.
Separate production/test Kotlin compilation fails without the suppression and
passes with it; this is not an APK or device execution result. Layout repair
`706df7f` is integrated at `361780f`, with all nine layout guards passing.
At that exact source, SDK staging and the **664 Python plus ten rendered App**
boundary cases pass with no failures/skips in 43.51s. Python XML SHA-256 is
`6bb4b53f2114bee9778417111ccd50a3cce4f23b5e763d1214003614b9495724`;
rendered XML is `8869e7c3255ba50ff4a8dd2455019d74f347415693a2f1fbf40cc5324e586d95`.

D's independent Windows public-pairing producer `9070db4` is integrated at
`90a0004`; 287 focused consumer, matrix and selection checks pass without skips
in 16.10s. Actual frozen-host traffic is still unexecuted. Review identified
that direct gathering consent does not grant persistent personal messaging
consent. A follow-up must explicitly select relay-only pairing before dispatch;
no private consent bypass or selected-path/SC21 acceptance is authorized by
these component results. The standalone Android host and group composer remain
separate pending integration batches.

### Current combined checkpoint and full CI dispatch

Source `5ea29493d0420896a8801169c78145e640fdc5dd`, tree
`d1a963ce25ff98dc9ce93a692f7b497a06c6986d`, integrates both inventory repairs
and B's native profile controls, including pending-host replacement regressions.
The lead's exact SDK staging passes, then:

- Complete policy: **3,379 passes, zero failures/skips**, 356.92s wall time,
  347.422s summed test duration, qualification `c91d7315479947e3af2ac9e713c0120f`.
  Reports: `dist/reports/profile-policy.{json,xml,inventory.json}`.
- Exact App/Core boundary: **664 Python and ten rendered-App cases**, no failures
  or skips, 47.88s. Python XML SHA-256
  `b7b18ae8ad8b776a238acace3d5a1e02679ff4a7f566366294d48b7857ffd428`;
  rendered XML `c1e3906ade4ecb227966b18633449391f96a5457aab006d674d205db37a66520`.
- Exact Windows host components: **nine passes, zero failures/skips**, 4.11s.
  XML SHA-256 `c6fbc6bb985540b6019a9794c29716d8df6013b27a5edf32a875b3608c96b1b6`;
  inventory `01120350612b18ebafd6873465d2856ca8d2a58ad63ecd558cce61815430c2d1`.
  These use explicit test-only Vault storage and do not prove EFS or packaging.
- Integrated profile UI/effect controls: 34 passes, 15.70s. Worker B separately
  reports all 777 frontend tests and TypeScript checks passing.

The checkpoint is pushed to the shared feature branch. Full manual CI
[42693457737](https://github.com/ahouchens/mesh-chat/actions/runs/42693457737)
is dispatched; duplicate PR run `42693436511` is canceled. The lead pinned 137
validator/source files under `.test-tmp/ci-evidence-5ea2949`. CI outcomes remain
pending. None of these local passes establish OS credential UI, native
cross-platform receipts, physical behavior or trusted browser-media retirement.

### Integrated public pairing and native cleanup review

Source `787b6aa4f9fff789a251668cf82b3da3b5fbc8f9`, tree
`fcdeca25187e2fc2aa7bd2e6bcc7267241897936`, includes A's public pairing
producer and deadline/terminal corrections. Exact SDK staging passes. The lead
executes 79 pairing protocol/actual-actor/installed-SDK tests without skips in
11.81s (`dist/reports/pairing-positive-review.xml`), plus all 50 TypeScript SDK
tests and strict model/reducer typing. Native/mailbox boundaries in the public
actor controls are explicit doubles; these do not qualify native traffic.

Full policy at that source finishes with **3,359 passed, nine failed, zero
skipped**, 417.68s (`dist/reports/pairing-policy.xml`). Eight direct-evidence
fixture cases expose an inventory path anchored to the plugin checkout instead
of the invocation repository. One case requires the three new public pairing
vectors. This is failed qualification; repairs and a complete rerun are required.

Earlier integrated component checks:

- `b31a3a9`: B's WebRTC effect-owner wiring, 61 frontend passes in 3.59s.
- `60e3ec4`: finite Windows-host audit paths, 103 passes in 3.01s.
- `0d4758e`: C's exact Android peer/channel disposal coordinator, actual Kotlin
  source compilation and 21 JVM passes in 0.113s. Failed wrappers remain owned;
  successful disposal stages are not repeated. Platform callback quiescence and
  device cleanup still require actual Android execution.
- `b4d3277`: D's required installed Windows bootstrap report, 162 focused passes
  in 9.01s. The producer requires an outside-checkout installed SDK and source-bound
  frozen executable, actual EFS attributes and two acknowledged clean exits.
  That producer has not yet executed locally or in CI; no EFS/SC21 pass is inferred.

### Current full run and Android provider integration

Full CI [42683615511](https://github.com/ahouchens/mesh-chat/actions/runs/42683615511)
targets `21bb99ca338e5c1d16059cbdc5d529d114ba6ede`, tree
`1a98f05242f29b0950da9ac841861b4d1ef91358`. Selection artifact `13702709168`
requires all six families and the full native workload; duplicate PR run
`42683596152` is canceled. The lead pinned 134 validator/source files.

Policy artifact `13703528817` independently validates **3,256 passes, zero
failures/skips**, duration 187.282s, qualification ID
`238472989f5b47f390b2a0ba47c1af3e`. ZIP SHA-256:
`a9cad6ea98d10d74a664f2b532b4010fc3ccb9589f39db8d8b24435e81f1c616`.

Windows packaged first-time pairing now passes all five required checks,
including explicit approval, cancellation, pending-invitation restart, carrier
transfer and two authenticated receipts. Preapproved transport also passes its
three receipts; native lifecycle passes 100 pairs/controls and three cold starts.
All three required production pipe cases execute without failure or skip.
The lead validated report schemas/inventories with pinned validators and bound
six packaged reports to the retained sidecar/build manifest. Every archive entry
was hashed in memory; no executable extraction was needed:

- Desktop artifact `13704560441`, ZIP SHA-256
  `4a2e7390b59cf996cee0d617f7cfbdb3dfc558de0479a2b1972850a3f48cadce`.
- Native artifact `13702964768`, ZIP SHA-256
  `11a166f38ad63e9b999f72d27a7db03dc62a834c11c44735f79445a1e18226af`.
- Sidecar: 54,532,753 bytes, SHA-256
  `fd22f032b8c3f2d78ffc093017cdf864c0fbcb594d9fbeee2859812ba0e27b5b`.
- Build manifest SHA-256
  `cfb6f840edc13c15bf822402cabca112bd2e3dbf8cf174cf98ec29eb42be5b0b`;
  build input SHA-256
  `44f3ff3467c26d150177b524b09b2d1e17356eb0ebc5a0d3edb4bc8068170b0a`.

Evidence and lead validations are under `.test-tmp/ci-evidence-21bb99c`.
The seven Python WebView probe source hashes match exact source with Windows
CRLF checkout bytes. The WebView executable hash remains runner-reported because
that executable is not in these archives; embedded materials were not locally
re-extracted. These Windows passes do not establish SC21 or physical/media
qualification.

Broad verification subsequently passes. Artifact `13705515395` (ZIP SHA-256
`84cfb6a3ae38301dede1dc3d4819da970e1af7559d0912459f9eb44ba9d8d761`)
contains independently validated 649-Python/ten-rendered-App XML inventories,
zero failures/skips, 32.46s. The broader automated run's success is a retained
runner summary; its complete test XML is not present in this archive.

Android artifact `13705331645` (ZIP SHA-256
`78605e64020e343215cead5f43c29508bef5861f4964e9cb6eb2ecb17f33fec2`)
validates 47 required emulator cases: 21 WebRTC, ten signaling, ten Core and six
independent Binder consumer cases, no skips. Debug artifact `13705006908` has
ZIP SHA-256 `c4584e039aa5280633432345994c71d5561632e40d4e32ae2b4894ad68ae31ed`.
The lead hashed every archive entry in memory, matched all seven tested APK/AAR
hashes, and revalidated each scenario's actual report/run identity. Five retained
JVM reports add 40 passes without skips. The later provider and three registry
cases are not part of this source and cannot inherit these passes.

Linux direct artifact `13705632218` (ZIP SHA-256
`2772f3471f3ea02ad43c0c09c48ffce8df4cb41f9339f94ac2f98bd2f5db77a8`)
independently validates all 25 fabric, ten recovery and 12 setup cases, zero
failures/skips. Its runtime binary hashes remain runner-reported; the archive
contains reports rather than those binaries.

The full run cannot pass: Windows native-interoperability job `129394480007`
fails at `initialize` with `FileNotFoundError`. Failure artifact `13705616595`
has ZIP SHA-256 `b5ec990d9a99d15cfa531e2665b416224465acb9afb9767a1d2f003a48249a42`.
Source review and the actual pipe validator identify the controller's
`mesh-native-qualification-` prefix as invalid; production requires `mesh-chat-`.
Initialization succeeds before endpoint construction rejects that name, leaving
the controller's 15-second connect wait to fail. D's harness correction and
regression are integrated as `19dcf00` / `1ba621c`; production pipe policy
and deadlines remain unchanged. The exact nine-case Windows component gate
passes after repair (3.55s, zero skips). Android interoperability subsequently
fails at initialize with `RendezvousUnavailable`, artifact `13706216921`, ZIP
SHA-256 `a3675eaf674183c49d4e56b285180284166a754d1d83ba5a2a4a5e84b6214fef`.
All other jobs pass; the final gate fails. There is no passing Windows–Android
native traffic evidence from this run.

Windows direct artifact `13705073010`, ZIP SHA-256
`8d8f5399b2abe59c46c342f7a0eb61ad602322da10f978c2517dbcdb469dcf86`,
independently validates all 25 fabric, ten recovery and 12 setup cases without
failures/skips. Binary hashes remain runner-reported because this archive contains
reports, not the binaries.

Subsequent local integration `9cfc3363fb55b8a22a2961fdccf358b65bb2185e`, tree
`c6018a370cb09f3e24c6afda417846eede62aa45`, includes provider fix `0bfb95d`.
Its catalog uses separate protected metadata key authority without loading the
original profile key. Dedicated per-confirmation AndroidX registrations replace
Tauri's shared activity-result callback. Exact SDK staging passes, followed by
115 mobile bridge/profile lifecycle/runtime-host checks, zero failures/skips,
14.14s (`dist/reports/provider-ready.xml`). The first invocation had 109 passes
and six setup errors from omitted SDK/Node environment; the complete rerun uses
staged exact-source artifacts and Node 24. C reports 13 JVM passes and production
plugin compilation; three real AndroidX routing tests only compile so far.
D is wiring required Android execution. Successful OS credential interaction
still needs platform evidence. The running `21bb99c` CI excludes this provider.

Further local integrations: `0e681b8` requires all three Android registry cases
(future inventory total 50), with 158 lead gate checks passing in 13.46s.
`b2f8701` integrates original pairing deadlines, durable cancellation callbacks,
terminal custody checkpoints and modern native SCTP SDP; 59 actor/real-bootstrap/
Windows-native checks pass in 24.43s. A's public producer remains held pending
positive parent recovery checks and its original-deadline binding.

`95f620a` adds the independent launcher: ten checks pass in 2.51s, including
eleven subprocess protocol cases and outside-checkout installation using the
actual `9cfc336` SDK archive (SDK source unchanged). The first invocation omitted
the artifact environment and failed one prerequisite; the configured rerun is
complete. `fff258f` adds normal Windows app-owned bootstrap, with 15 component
checks passing in 2.46s. These use actual DPAPI and authenticated pipes but an
explicit test-only vault-storage bypass; they do not qualify EFS/frozen traffic.
`330fa99` adds native effect-scope helpers, with 13 passes; full call-site wiring
and authoritative native/media retirement remain work in progress.

Exact source `7eefaf313824c79b5986dbfd0195ba63629d3618`, tree
`43679f2cb63e46638edb85699e99ebc297afc308`, requires nine Windows component
cases and passes all nine, zero failures/skips, 2.90s. JUnit SHA-256:
`73a243550596064c826665d9bc1a4ea9334ac6c81214be91098ed4b9ee0c88ce`;
inventory SHA-256:
`fc9841a8aa26395c5d96199952a3e76cd0a257b04d2545fc713c90afde5fb43b`.
A cache-directory permission warning does not affect those executed cases.

### Corrected pairing and combined qualification checkpoint

Source `6875b00d7a3502ce662b33acdfdc6bc84c0b4ab7`, tree
`b9e02254cf654040c47ecc6e5223153e0d993575`, passes the complete 3,251-case
required policy inventory, zero failures/skips, in 336.65s. Qualification ID:
`a666ed1903c74a8889fde787d9df5d59`; reports are
`dist/reports/policy-recovery-group.{xml,json,inventory.json}`. Exact SDK staging
also passes. Its exact boundary passes 649 Python plus eight rendered-App cases
in 47.54s without skips. Completed policy scratch was removed; reports remain.

C reproduced first-time pairing with real native DataChannels and isolated
Reticulum processes. The carrier and explicit approval were intact, but the new
pairing projection called an approval-requiring lookup for a pending contact,
faulting the entire connection runtime. Narrow repair `0af2687` uses the
host-derived destination only for that denial projection; actual authority
checks remain in the grant/adoption paths. It was cherry-picked with attribution
as `e7f6497`, excluding the still-held Android provider ancestor `0b012c3`.
The lead's real first-contact/receipt and pairing-runtime regressions pass 31
cases, zero skips, in 21.78s. This is source execution, not frozen-package proof.

Source `efbddfa2ed35bfbdda85ff220a83c925abd3bf3e`, tree
`0bd10b8c6a73e5d4a7d4f37d134a2accbda22361`, adds D's two rendered group replay
cases and B's final reconnect-factory admission guard. Its exact boundary passes
649 Python plus **ten** rendered-App cases, zero failures/skips, in 41.42s.
The group cases lose real committed replies, replay the exact caller key and
payload after modal reopening, and preserve a newer draft without another
durable group/message/outbox/receipt. Group membership uses real signed domain
messages over an explicitly in-process fixture. The lead's 27 focused reconnect
admission/runtime checks pass. None establishes full renderer-restart group-key
durability, physical media retirement, native interoperability or SC21 traffic.

The corrected source is ready for a new full packaged qualification run. Android
profile-provider wiring remains held for separate protected catalog-key storage
and dedicated native credential-result routing; the shared Tauri activity-result
callback cannot establish which activity supplied a successful result.

### Current full CI failure and local repairs

Full run `42676194199` targets `da815655792241629f19f0e7ac02b8402a744790`,
tree `ea96a33605a4cff7620023bbff8ca4c1e88163a1`. Its retained selection
requires all six families and the full native workload. The lead verified
selection artifact `13700217574`, ZIP SHA-256
`235e2a75c7d219b931a2a4f32cb09bf5c04ec425024d82f82af7ece0f83b6964`.
The run cannot pass: policy recorded 3,184 passes and two failures, zero skips;
broad verification recorded 4,389 passes, the same two failures and 51 platform
skips. Synthetic matrix fixtures inherited the real GitHub run context. Repair
`3425095` isolates those fixtures while explicit positive/negative CI controls
retain strict production run/attempt matching. The lead reran all 94 matrix
checks under an unrelated live-style CI context: zero failures or skips, 4.64s.

Windows also failed explicit first-time pairing at `approved_path`, with both
carriers absent and bridges detached. Preapproved durable receipts, native
control/lifecycle, pipe consumers, WebView2 and frozen-material checks had passed.
Those preceding passes do not qualify first-time pairing. The retained failure
reports no transport faults or peer stderr; process termination during cleanup
is not a diagnosed cause. C owns production handoff diagnosis and D owns probe
diagnostics. Desktop report artifact `13700996616` has verified ZIP SHA-256
`279dd742957f2b5cafb38b898cbc3a21ce8d941e375b3cd6b79f3d8b88ae9c0f`.
Reports are retained under `.test-tmp/ci-evidence-da81565/desktop-transport`.
The lead subsequently hashed every entry of native artifact `13700018594` in
memory (ZIP SHA-256
`1c42f24bb6fdb543501148f97fa8222ac24d2d5561f12ede6559a550020faeaf`). The
retained sidecar SHA-256
`8f4719e2f6b167d64241961ba009a5c8a453f487ff14b377967893f5862d0575` and
build-manifest digest match the native control/lifecycle, materials, packaged
lifecycle and preapproved-transport reports. No executable was extracted or run
locally. The separate WebView2 probe binary digest remains a runner claim.
Required native topology has not executed in this run.

Android also failed two manual native adoption instrumentation cases, the Kotlin
`workspaceJoinIsConvergentWithoutACallerKey` unit assertion (20 passes, one
failure), and public AAR license verification. The final runner exception must
not obscure the earlier test failures. Failed report artifact `13701676421` has
verified ZIP SHA-256
`a5c1bc1f29487851dc1a3279c95445f8bbb1fcdba5ecfbd76f13f5d1a95bdb84`.
Lead inspection found that the manual-adoption fixture assigns synthetic path
readiness to the new outer executor wrapper instead of its reconnect executor;
the same fixture also accesses the native port through the obsolete location.
D owns correcting those instrumentation hooks and verifying the intended inner
port. A owns the Kotlin assertion and license packaging diagnosis. This fixture
finding does not establish the cause of the separate Windows pairing failure.
The required native-interoperability job was skipped after prerequisite failure.

The workflow finished with a failed final gate. Both direct-network jobs passed;
the lead independently validated 25 fabric, 10 recovery and 12 setup cases per
platform with zero skips using pinned `da81565` validators. Linux artifact
`13701687559` has ZIP SHA-256
`5bfee1c2a84e83155122a239295a7a6814b98a6395d42e46b8eca6e99c577af0`;
Windows artifact `13701943154` has ZIP SHA-256
`f0513f652452ebce3f77b425b83ab767cd5d951810fc8b27fefa3b311cc22f10`.
These controlled native/Python suites do not qualify packaged cross-platform
interoperability. Their binary digests remain runner claims in report archives.

Local source `a899b8576ee2130510b5bf98b6a64b7b44bf7f71`, tree
`ebd717956b4b7ff7ceb215b8afa4cc4357879b77`, integrates the fixture repair,
independent group authority tests and the remaining API/component admission
guards. Its exact boundary gate passes 640 Python plus eight rendered-App cases,
zero failures/skips, in 34.57s. B reports 719 frontend passes and TypeScript
compilation passing at `ddf4776`; plain native effect auditing remains separate.
At `50474ec78d082ad17e4bafd450187780823abd2a`, nine independent consumer staging
checks pass without skips in 1.36s, including actual offline archive installation
and public SDK import outside the checkout. This is staging evidence only:
normal app-owned host bootstrap and public pairing/receipt traffic remain open.

### Gated call recovery and Android fixture repairs

Source `5556cc0f502c70da10f81f7685f3a5b2b6963ac1`, tree
`2171f4e3b46cf67c1e0f4617d3e0fe2964ffcbe2`, integrates protected call acceptance,
caller-scoped discovery and abandonment, exact trusted retirement tickets,
asynchronous completion, SDK helpers and the Kotlin CI repairs. Exact SDK staging
passes; the lead's 248 call-recovery, legacy-call, installed-consumer, license
and contract checks pass without skips in 13.92s. The extension remains
unadvertised on ordinary hosts. A typed substitute retirement provider in tests
does not establish actual browser media cleanup, native recovery or permission
to replace unresolved media. A host that has activated the protected catalog
cannot bypass its fences by rebinding without the provider.

D's `3a122d4` Android instrumentation correction targets the actual inner
reconnect executor while preserving the existing synthetic-path scope and
readiness deadline. The lead's 20 adapter checks pass without skips in 1.99s;
emulator confirmation remains required. Follow-up `7b2718b` retains all failed
case inventories and JVM reports. `f7d9844` completes the three call-recovery
request vectors through actual Core framing, with explicit component-provider
scope and ordinary-host unsupported controls. No required vector is waived.

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
could not resolve its transitive Binder SDK dependency. Direct jobs subsequently
completed successfully: both Windows and Linux passed 25 fabric, 10 recovery
and 12 setup cases with zero skips. The lead validated each retained inventory
and report using pinned `dcac85e` validators. Binary hashes in these report-only
archives remain runner claims. The final workflow gate failed.

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

### Combined native custody review

Source `5cf3478f45bd8052d1e0dd4684c2c0ada4a7362d` integrates concrete supervisor
pairing, complete private native lease accounting, the queued-creation
cancellation fix, and the Android instrumentation dependency correction. Strict
model/reducer typing passes. The complete local required run executed 2,982 cases:
2,977 passed, five failed, zero skipped in 287.14 seconds. Four failures were
boundary vectors still routing runtime lifecycle requests through the ordinary
service session or omitting `profile.catalog`; D owns their correction. The
remaining Bash fixture failed sandbox path traversal and passed independently
with the necessary filesystem access. This is not a passing policy gate.

Follow-up `02db485`, integrated at `8e396b7`, retains an acquired profile service
through any handle-authority validation failure. The full corrected policy run
and packaged CI remain required. Supervisor-owned initial pairing still needs
its trusted host entry wired into the topology controller; a manually driven
native handshake does not establish that coverage.

The corrected complete policy run at
`1e288ecbf9da00d49c84ee63ff9ece76a3f15f7d` passes all 3,108 collected/executed
cases with zero failures or skips in 306.43 seconds. Qualification ID:
`6b165305c11c4d418b07f57484b6b60c`; retained files are
`dist/reports/policy-runtime-custody.{xml,json,inventory.json}`. Seven warnings
concern existing JUnit metadata/upstream deprecation behavior. This source also
contains the two-role topology infrastructure, whose actual execution and
supervisor-owned pairing-entry followup remain pending. Passing its controller
component tests is not transport qualification.

### Native retirement and UI lifetime follow-up

Source `5a523d75940e903a023f5637c5cb37074631e4f1` integrates the private,
marked-profile supervisor pairing entry, immediate routing removal after a lost
native creation return, and truthful mobile shutdown acknowledgment. Android
keeps its native response pump alive until deferred vault cleanup finishes.
The lead's combined Windows host, private pairing, mobile bootstrap and profile
lifecycle check passed 76 tests, zero skips, in 6.74 seconds. The retained report
is `.test-tmp/native-retirement-review.xml`.

Source `0f19638a58aa2086af97813ce2cdf78ff8167dbb` adds the private mobile profile
host foundation. Its 14 encrypted-vault/Core lifecycle tests passed in 2.39
seconds with zero skips (`.test-tmp/mobile-profile-review.xml`). OS key retrieval
and authentication are explicit boundary doubles in this run; production
Kotlin/Binder/provider wiring remains pending.

UI worker source `bb14d2bce5f043df9e8ae129901e7217c8d1815c` passed 630 Python
boundary cases plus eight rendered-App cases, zero skips, in 41.81 seconds.
Final worker source `002ddd4fae9b979748f2c6d45d6f7c9d913d27af` changes only the
notification presentation fixture after that gate and passes all 700 frontend
tests across 43 files in 58.98 seconds, plus TypeScript compilation. These are
worker-reported checks, not a claim that the exact final worker head repeated
the Python boundary gate. The batch is integrated at `ec96794708876675ee02d9fea97a8a6cd25fa362`.
It hides retired profile content, bounds final UI work to one second, preserves
uncertain lock outcomes for retry, and fences delayed notification admission.
Full renderer-restart call intent recovery and live public profile selection
remain open. No new packaged qualification is claimed by these local checks.

### Supervisor topology and optional group-key checkpoint

Source `a3a98ce69624d5a7d083c7264da5af3a320d9f09`, tree
`147ab5d759b3e060da3f0824a22055fe6ccfbc51`, passes all 3,178 required policy
cases with zero failures or skips in 324.46 seconds. Qualification ID:
`35a8948d124c4779abb5e52c00097eb4`; reports are
`dist/reports/policy-supervisor-group.{xml,json,inventory.json}`. Source-bound
Python/TypeScript SDK staging and isolated imports also pass. The new optional
group create/enqueue caller keys retain legacy unkeyed SDK behavior; keyed
acceptance commits primary records, recipient jobs, quota and receipts together.
This closes two advertised optional extensions, not the remaining mutation audit.

That source also contains D's supervisor-driven topology controller and explicit
quick/full selection. Full manual qualification requires both direct initiators,
Windows-initiated TURN UDP/TCP/TLS and impairment cases, selected-path negative
controls, and 100 receipt iterations per role with ten periodic cold restarts.
Quick PR smoke has a distinct evidence level and cannot satisfy the full or
release gate. Neither mode has executed on the combined native artifacts yet.

Follow-ups are integrated at `d4091fdabb4514f85d181865c417d4f5f0263425`, tree
`c425112e0868173dc460bcf515571a2233157f68`: offline keyed group invalidation
observations, mobile runtime-host routing and failed-opener channel custody,
group/workspace draft/send/read admission fences, and crossed-caller call-media
denial. The lead's exact-source boundary gate passes 640 Python cases plus eight
rendered-App cases, zero skips, in 48.03 seconds. The focused actual mobile/group
run passes 63 cases, zero skips, in 13.28 seconds. Reports are
`dist/reports/core-ui-boundary.json` and `.test-tmp/host-group-final.xml`.
B separately reports all 708 frontend tests and TypeScript compilation passing
at `b2b632e`. Remaining delayed settings/contact/admin admission paths are being
repaired; live platform authentication and independent public consumers remain
open. Subsequent documentation-only merge `0e110070` clarifies the accepted
independent-consumer design and ownership; it adds no execution claim.

### Runtime catalog and installed SDK checkpoint

Source `8ef8dd5388e617ad4dae0a1425318cd05f08d8f7`, tree
`609d4f4797eac4b90c3b62d8df87e3cf17ad738a`, stages the updated public SDK archives
and passes 239 runtime-host, installed SDK, pinned upgrade and contract cases
without skips in 35.28 seconds. The encrypted host catalog survives profile-vault
closure, preserves derived opaque-handle authority and fences active services
against the final persisted selection. A two-slot constructor race rejects the
changed selection before publication. Trusted platform key-slot openers are still
required; this is not installed Windows/Android lifecycle evidence.

Source `d8869d06c92cc1f6dae3eb8ce1e8a5b97ac52d0e` keeps the selected profile first
in capability results for existing clients. The lead ran the four pinned Python
and TypeScript 0.2 consumer cases with both selected slots: four passed, zero
skips, 4.68 seconds (27 unrelated cases explicitly deselected). The earlier
frontend history repair at `5fa62a9` passes all seven layout checks in 0.39 seconds.

Renderer-restart recovery of an unknown call start still needs a protected Core
operation query and authoritative cleanup disposition. An in-memory UI ticket or
a bare `resync_required` response does not close that obligation.

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
