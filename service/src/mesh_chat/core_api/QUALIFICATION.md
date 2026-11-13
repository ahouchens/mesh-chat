# Private packaged qualification control

Full run [43494402594](https://github.com/ahouchens/mesh-chat/actions/runs/43494402594)
at `5c54739` is **failed**: nine jobs passed, Windows Direct, both native peers
and the aggregate failed; two optional jobs were skipped. Policy passed 6,589
cases without failures or skips. UI passed 2,309 Python and 12 rendered cases;
Android passed 56 emulator and 83 exact JVM cases; desktop SDK pairing, eight
reports, nine pipe cases and 72 layout cases passed. Linux Direct passed its
complete fabric, ten recovery and twelve setup cases.

Windows Direct passed nine recovery cases. The blocked case failed during
initial admission, before blocking the path: the receiver had no general
channel after the original 45-second wait. The owner control was
`waiting_for_keys`, with zero native send attempts and a future retry schedule.
This was not the previous worker reply timeout. The report did not retain
which main key was missing. A later local run passed; that does not establish
a cause or Windows Direct acceptance for this CI source.

Both native peers completed all six direct/TURN/impaired path cases. Windows
completed the first restart and identity checks, then exhausted the partner's
started barrier. Android failed during startup rollback in the first restart:
ADB reported `device_offline` on forward removal, after a force-stop error.
The original startup failure was masked. A successful old stop had cleared the
old forward; removal during rollback therefore indicates a new forward had
been assigned during startup. The later instrumentation exit 255/EOF does not
prove that no startup port marker was previously received. The emulator process
was running; guest/ADB health and the cause of disconnection remain unknown.
Both reports flagged cleanup failure. Zero cold receipt cycles completed;
neither the native 100-cycle gate nor aggregate acceptance passed.

The successor corrects a source-level initial handoff gap: signature-only
announce observation can precede main RNS identity/ratchet and path acceptance.
Initial confirmation now requires main keys and the selected admitted interface;
bounded standard announces continue for the opposite peer. Recovery keeps its
old authenticated route until durable winner commit and requires main keys,
without claiming that cached keys prove a new announce was processed. The
existing 10/12-second confirmation windows reject readiness observed too late.
This is a demonstrated source gap, not proof of the particular CI failure's
cause. The admission report also retains the existing first sixteen process-wide
channel attempts through a fixed-field sanitizer; that trace is not a complete
or workspace-specific history. Full acceptance, helper retirement and later
roadmap gates remain open. WebRTC stays at the pinned dependency.

Full run [43477424970](https://github.com/ahouchens/mesh-chat/actions/runs/43477424970)
at `16eb381` is **failed**: nine jobs passed, Windows desktop public pairing and
the aggregate gate failed, and native interop was skipped after the desktop
prerequisite failed. Policy passed 6,468 cases without failures or skips; UI
boundary passed 2,309 Python and 12 rendered cases; Android passed 56 emulator
and 83 exact JVM cases. Both Direct platforms passed 25 fabric, 10 recovery and
12 setup cases. All 72 layout cases and nine Windows pipe cases passed. These
component results do not establish full native acceptance.

Windows public SDK bootstrap passed with DPAPI/EFS. Public pairing then failed
before an offer code became available. The trusted owner retained one offer
intent retired at `gather_offer/failed/invalid_document`. `NativeUnavailable`
inherits `ValidationError`, so this classification also covers native failures;
it does not identify a malformed document, a native code, or the failed stage.
The later `network_interface_unavailable` snapshot is not causal evidence. The
sidecar bytes match the preceding desktop pass. No specific network, TURN,
candidate, signing, or SDP cause is established by this attempt.

The next diagnostic slice extends existing private gather observation to offers
and projects an optional, strictly validated field through the trusted owner's
existing failure frame. It records fixed stage and exception labels at the
accepted failed-result time or original phase deadline, with exact source/work
custody and bounded lock acquisition. It adds no raw error/SDP fields, RPC, retry,
public SDK operation, deadline, native acceptance, or WebRTC change. The Android
lifecycle diagnostic from `16eb381` remains in place but was not exercised by
native interop in this run. Full native/aggregate acceptance, helper retirement
and later roadmap gates remain open.

Full run [43468072180](https://github.com/ahouchens/mesh-chat/actions/runs/43468072180)
at `4cf7e0b` is **failed**: ten jobs passed, both native peers failed, and the
aggregate rejected incomplete qualification. Policy passed 6,445 cases with no
failures or skips; UI boundary passed 2,309 Python and 12 rendered cases; Android
passed 56 emulator and 83 exact JVM cases. Both Direct platforms passed 25 fabric,
10 recovery and 12 setup cases. Windows `address_loss` passed in 162.455 seconds
with the scoped shared fixture deadline and unchanged production backoff. Eight
Windows desktop/native reports, nine pipe cases and 72 layout cases also passed.
These component results do not establish full native acceptance.

Both peers completed all six direct/TURN/impaired path scenarios. Android then
failed in the first cold-start iteration at `restart`, with zero cycles complete,
a `CalledProcessError`, and `cleanup_failed=true`. The report and job log retain
neither the failing command nor a cleanup-site label. The gateway reported no
operation or cleanup failure. Source inspection identifies the possible escaping
ADB lifecycle operations but cannot select the failed command, distinguish an
original error from one replacing it during cleanup, or establish emulator exit,
memory pressure, a missing forward, or a WebRTC defect. Windows reached
`cold_started_0` and timed out waiting for Android's corresponding checkpoint.
The cold exact-path checks and new final-evidence attribution were not reached.

The next diagnostic slice records fixed Android lifecycle command labels,
bounded exit status and owned process state for the exact caught error before
final cleanup. Existing commands, deadlines, startup error wrapping, cleanup
ordering and error replacement remain unchanged. It introduces no retry, extra
ADB/RPC, production policy or WebRTC change. The exact Android restart cause,
full native/aggregate acceptance, helper retirement and later roadmap gates
remain open.

Full run [43457917143](https://github.com/ahouchens/mesh-chat/actions/runs/43457917143)
at `c7e1704` is **failed**: nine jobs passed, Windows direct recovery and both
native peers failed, and the aggregate rejected the incomplete qualification.
Policy passed 6,421 cases, UI boundary 2,309 Python and 12 rendered cases, Android
56 emulator and 83 exact JVM cases, Linux direct 25/10/12 cases, and layout 72
cases with no overflow. Eight Windows desktop/native reports and nine pipe cases
passed. These exact-run component results do not establish full acceptance.

All six direct/TURN/impaired path cases have reciprocal completion markers.
Both peers reached `cold_complete_10` and `cold_started_10`. Android failed at
iteration 12, with 11 completed cycles, in `exact_path` after its receipt; that
iteration did not restart the process. Its `ValueError` has no retained skip
reason or observation substage. Source inspection strongly points to the exact
path no longer being ready, but cannot distinguish missing ownership from an
attachment/readiness/selection change. Windows completed 12 cycles and timed out
in iteration 13 exchange. Android gateway operation and cleanup failures were
absent. The cold loop and checkpoints were reached; the full 100-cycle gate failed.

Separately, Windows `address_loss` recovery passed its authenticated reconnection
checks but failed queued-message delivery: nine recovery cases passed and one
failed. Five sends had no usable main path, no native message ID, and a future
retry scheduled. The unchanged local case passed in 143.24 seconds using the
dispatcher from this exact run. A controlled-clock demonstration through the
actual workspace due-work methods shows the fifth failure schedules an 80-second
delay: after path restoration at time 90, the next send occurs at time 155, beyond
a fresh 45-second test wait. CI lacks the timestamps needed to prove that ordering
was its cause; this is a demonstrated fixture timing hazard, not a confirmed
explanation of the runner failure.

The successor retains fixed final-observation and traffic failure labels during
cold cycles, using the same samples and checks without an extra observation or
retry. Its Direct fixture correction scopes one 225-second recovery/receipt
budget to `address_loss`, starting after both signed updates are imported and
retaining each connected check's 180-second ceiling. Queued and bidirectional
receipt checks share the remaining budget; no late result can pass. This is a
composition of existing test windows, not a Direct product SLA or SC04 claim.
Production retry policy and WebRTC remain unchanged. It does not establish a
prompt-outbox-wake guarantee for legacy QUIC recovery. Exact native failure
causes, full native/aggregate acceptance, helper retirement and later roadmap
gates remain open.

Full run [43448951902](https://github.com/ahouchens/mesh-chat/actions/runs/43448951902)
at `9483e3d` is **failed**: ten component jobs passed; both native peers and the
aggregate failed. Policy passed 6,404 cases, UI boundary 2,292 Python and 12
rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct platforms
passed 25 transport, 10 recovery and 12 setup cases; layout passed 72 cases with
zero overflow. Windows reports and nine pipe cases passed. All component
artifacts were checked against this exact source/run; they do not establish
full native acceptance.

Both direct initiator cases have reciprocal completion markers. Android then
failed during `turn_udp_authenticated_receipts` with a bare `ValueError`, without
a retained substage, native-path reason or error code. Gateway operation failure
was null and cleanup failures were empty. Windows completed its own TURN UDP
evidence, published its marker and timed out at `completion_receive`, before
committing carrier retirement. No cold-start checkpoint was reached, so this
attempt did not exercise or qualify the cold readiness/checkpoint corrections.

The source audit identifies two strong unlabelled candidates: the final
observation returned no selected path, or the before/after traffic comparison
rejected resource/service identity, selected-pair identity, sequence or native
packet deltas. The report does not establish which happened. An earlier peer
message included in the baseline is insufficient to explain a zero inbound
delta: a later own authenticated receipt also contributes native Reticulum
packets when that channel carries it. No timing-only cause is established.

The next candidate adds bounded content-free attribution to the existing final
observation and traffic checks for every path scenario, including direct and
TURN UDP. It preserves the same RPCs, samples, polling, acceptance rules,
deadlines and primary failures; it adds no retry or product/WebRTC change.
Actual failure cause, cold-start qualification, full native/aggregate acceptance,
helper retirement and later roadmap gates remain open.

Full run [43436650996](https://github.com/ahouchens/mesh-chat/actions/runs/43436650996)
at `31ac1c3` is **failed**: ten component jobs passed; both native peers and the
aggregate failed. Policy passed 6,319 cases, UI boundary 2,246 Python and 12
rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct platforms
passed 25 transport, 10 recovery and 12 setup cases; layout passed 72 cases with
zero overflow. Windows reports and nine pipe cases passed.

Both controllers completed all direct, TURN UDP/TCP/TLS and impaired cases and
reached `cold_start_receipts`. Android then failed `path_read` with
`native_unavailable`; Windows reached `scenario_deadline`. Android gateway
operation failure was null and cleanup failures were empty. This attempt moved
past the earlier impaired recovery failure. The retained report does not identify
the cold-start iteration, completed cycle count, exact native unavailability cause,
or whether the failed read preceded or followed its receipt exchange. Windows'
timeout is not proven to have the same cause. Full native/aggregate acceptance
remains open.

A deterministic service/private-port regression reproduces authorized inventory
followed by exact resource retirement: the old path read raises
`native_unavailable`, while fresh inventory has unchanged service/profile
incarnations and no old resource. Still-current native inspection failures and
changed incarnations produce the same error code. This uses a real Windows
native host fixture, not packaged Android JNI, and does not prove this CI cause.

The candidate corrects only pre-receipt cold-start readiness: after that error,
a fresh validated inventory must positively show the failed physical resource
absent with both incarnations unchanged before discovery may continue. Every
later poll takes fresh inventory and a fresh sample. Still-current resources,
changed identities, malformed or unavailable inventory, other errors and the
post-receipt exact-resource read remain failures. The original 120-second readiness
and 3,000-second global budgets remain; late results cannot qualify. Fixed,
bounded cycle/stage and recheck diagnostics retain no private resource identifiers.
A separate controller ordering gap is also demonstrated: a faster peer could
start its next scheduled process kill while the other was still checking the
previous cycle's exact path or resource accounting. Fixed sealed checkpoints now
require both peers to finish each ten-cycle evidence block before the next kill,
and both to finish restarting before readiness/exchange begins. The final
completion checkpoint precedes cleanup. Quick smoke uses its five-cycle final
checkpoint. These Boolean controls carry no product messages or receipts.
The conservative full-run artifact bound is 87, below the unchanged 100-item
inventory limit. Original global and bounded artifact-wait budgets remain.

The checkpoints enforce controller ordering; they do not themselves establish
native recovery, cross-peer quiescent accounting or the cause of the failed run.
The narrow readiness candidate at `8d636f0` passed all 6,358 required local tests;
the combined checkpoint successor requires its own exact-source validation.
No WebRTC, product service, policy, consent or dependency change is selected.
These corrections are not yet natively qualified; helper retirement and later
roadmap gates remain held pending full native/aggregate acceptance.

Full run [43427814301](https://github.com/ahouchens/mesh-chat/actions/runs/43427814301)
at `522d2c5` is **failed**: ten component jobs passed; both native peers and the
aggregate failed. Policy passed 6,257 cases, UI boundary 2,228 Python and 12
rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct platforms
passed 25 transport, 10 recovery and 12 setup cases; layout passed 72 cases with
zero overflow. The Windows reports and nine pipe cases passed. These component
results do not establish full native acceptance.

Both peers completed the direct cases, TURN UDP/TCP/TLS and twenty impaired
baseline exchanges, then failed impaired `restored_delivery`. The new Android
evidence bounds the fully installed exact block to at least **16,755ms**, within
a **17,525ms** command-operation interval, with **241 actual packet drops**.
Artifact ready/checked coordination was inside that outage. The local two-second
no-receipt loop did not bound the rule lifetime.

The exact Android carrier loss witness records an inspection that observed
SUSPECT followed by a tick with `carrier_lost` and prior health SUSPECT. The
policy's suspect grace is ten seconds; ownership loss preceded the native local
close request. Windows records inspection-driven `carrier_lost` from OPEN and
a native close callback after a local request. Both same-service/profile terminal
inventories contained zero resources. This establishes exact carrier retirement.
The scenario disables automatic replacement consent, so queued traffic cannot
assume a newly permitted replacement negotiation after losing that carrier.

The retained witness does not timestamp SUSPECT onset or retirement relative to
rule removal, identify Windows' exact terminal ICE/channel state, or identify
the RNS/LXMF requeue cause. Sending changed to queued at 49,910ms on Android and
66,304ms on Windows during restored polling; these are not retirement timestamps.
No gateway operation/cleanup error, Android control EOF or empty TURN offer was
reported in this attempt. Impaired completion and cold starts were not reached.

The candidate moves short negative-control coordination to a fresh, separate
encrypted mailbox room. Its capability crosses the authenticated sealed artifact
channel before blocking, and the remote peer arms before the rules are installed.
Only fixed run/attempt/source/scenario/role/room-bound ready and checked controls
cross that room during the block. Application messages and authenticated receipts
continue over the production Core/native path. Expired, foreign or malformed
controls fail; capability expiry is rechecked after blocking HTTP calls.

Both original two-second no-receipt observations, positive drops, exact rule
cleanup and once-only authenticated restored delivery remain mandatory. Every
accepted Android block must have a measured command-operation interval from
2,000 through 8,000ms, including verified exact rule deletion. The paired report
validator requires that evidence. This is an acceptance bound, not a physical
watchdog: a delayed HTTP call or cleanup can extend a failing outage but cannot
qualify it. Cleanup retains its single existing owner. The original 90-second
recovery and 3,000-second global limits, WebRTC and reconnect consent are unchanged.
No native recovery correction is qualified yet. The separate long-partition and
permitted-renegotiation requirements, native/aggregate acceptance, helper retirement
and later roadmap items remain open.

Full run [43419926345](https://github.com/ahouchens/mesh-chat/actions/runs/43419926345)
at `c17cdf1` is **failed**: all ten component jobs passed; both native peers and
the aggregate gate failed. Policy passed 6,232 cases, UI boundary 2,220 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases; layout passed 72
browser cases with zero overflow cases. The rebuilt Windows host includes the
final-SDP candidate guard. These results do not grant full native acceptance.

The paired run completed both direct initiators, TURN UDP/TCP/TLS and all twenty
impaired baseline exchanges, then both peers timed out at the impaired negative
control's `restored_delivery` stage. Each changed from sending to queued once
within the original 90-second recovery window. Android observed 295 restored
polls ending at 89,824ms; Windows observed 358 ending at 89,971ms. Android reached
this stage after positive drop counts and verified removal of its exact rules.
The gateway reported no operation or cleanup failure. No control EOF or empty
TURN candidate offer was reported; cold starts were not reached.

These reports do not retain transition timing or carrier ownership after the
block. Sending is emitted before the native handoff, so it does not prove packet
transmission. Queued can follow a native failure callback or handoff exception;
source review found no deterministic retry defect. A lost manual carrier could
remain without a replacement because automatic reconnect is not enabled in this
scenario. The block also spans artifact coordination and ADB work beyond its
two-second receipt check. Neither carrier loss nor its cause is established.

The bounded diagnostic retains transition times from existing query polls and
bounds around existing kernel block/unblock calls. On an attributed recovery
timeout only, one existing private inventory read captures the exact carrier's
current ownership and retained loss witness before cleanup. It uses existing
exchange bounds and is skipped near the global deadline. It adds no success-path
poll, retry or public/native API; the original timeout and cleanup remain in
force. Unavailable or mismatched observations are not evidence of a cause.
WebRTC dependencies, policy, deadlines and acceptance remain unchanged. Full
native/aggregate acceptance, cold starts, helper retirement and later roadmap
items remain open.

Full run [43414231985](https://github.com/ahouchens/mesh-chat/actions/runs/43414231985)
at `25396ef` is **failed**: all ten component jobs passed; both native peers and
the aggregate gate failed. Policy passed 6,231 cases, UI boundary 2,220 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases. The Ubuntu 24.04
layout pin is now verified by 72 browser cases with zero overflow cases. These
component results do not grant native or aggregate acceptance.

Both native peers failed in `turn_udp_supervisor_owned_pairing_windows` with
`supervisor_pairing_retired`, checking/tick/phase_timeout. Windows' retained
signed local SDP contained zero candidates; Android's local SDP contained one
IPv4 UDP relay candidate, reflected as Windows' remote candidate. Windows'
observed gathering state was complete; Android observed gathering to complete.
Both direct initiator cases completed before this failure. TURN TCP/TLS,
impaired receipts, the prior Android control EOF path and cold starts were not
reached. The original TURN allocation failure cause remains unproven.

Source inspection identifies a separate concrete adapter validation gap: the
Windows host checks for candidates before applying its relay-only SDP filter,
then publishes success even if that filter removes every candidate. The existing
relay-only tests permit an empty candidate list through a vacuous `all` check.
The bounded fix requires a candidate in the final published SDP and returns
the existing `native_webrtc_no_candidates` error through the existing exact-peer
cleanup path otherwise. It does not change the WebRTC libraries, gathering
deadlines, retry policy, consent or acceptance requirements, and does not claim
to repair the underlying absence of a TURN allocation. Full native and aggregate
acceptance, cold-start validation, helper retirement and the remaining roadmap
remain open.

Full run [43406689324](https://github.com/ahouchens/mesh-chat/actions/runs/43406689324)
at `d1cbcc4` is **failed**: nine component jobs passed; layout, both native peers
and the aggregate gate failed. Policy passed 6,213 cases, UI boundary 2,220 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases. These component
results do not grant native or aggregate acceptance.

Layout failed before browser execution: `ubuntu-latest` selected Ubuntu 26.04,
which the pinned Playwright 1.55 rejects. The preceding passing run used Ubuntu
24.04. Commit `6fab11e` pins only this job to `ubuntu-24.04`; browser commands,
the Playwright version and acceptance checks are unchanged. This is a confirmed
infrastructure cause with a source fix; successor CI verification remains open.

The native receipt observations now distinguish the failing exchanges. Android
completed its own delivery at impaired index 17 (10 polls, queued to delivered),
then received control-socket EOF (`peer_closed`) during its first inbound snapshot
read. No snapshot returned; `records: null` is unknown, not an empty inbound set.
Windows completed index 17 and timed out at index 18 with its own message queued
(357 polls, two state transitions). The reports therefore do not show a failed
same-message exchange. Android also reported cleanup failure; the gateway itself
reported no operation or cleanup error. Instrumentation, emulator, forwarded
socket and outer frame/serialization termination remain indistinguishable.

The controlled Core/Binder limits return explicit errors rather than socket EOF;
source inspection does not establish a deterministic payload-size defect. The
next diagnostic retains only bounded facts from existing socket reads, owned
process handles and the already-running instrumentation output reader, plus the
cleanup boundary that failed. It adds no RPC, retry or wait and does not modify
Kotlin, WebRTC, message policy or deadlines. Full native and aggregate acceptance,
cold-start validation, helper retirement and the remaining roadmap remain open.

Full run [43398691571](https://github.com/ahouchens/mesh-chat/actions/runs/43398691571)
at `9cc1e51` is **failed**: ten component jobs passed; both native peers and
the aggregate gate failed. Policy passed 6,185 cases, UI boundary 2,220 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases. Layout passed
72 cases with zero overflow. These component scopes do not grant native acceptance.

Both native failures occurred in baseline `impaired_authenticated_receipts`,
before impaired negative control and before cold starts. Android timed out in
`receipt_inbound_wait` after its own delivery wait returned; Windows timed out
in `receipt_delivery_wait`. The reports do not retain exchange indices, so they
cannot establish that both peers failed at the same index. Gateway cleanup
reported no error. Direct and TURN/UDP/TCP/TLS completion markers exist, but
the pending-negotiation cold-start correction was not exercised on this run.

The packet, carrier and delivery cause remains unproven. Source inspection found
no snapshot message pagination and no deterministic oversize violation for the
1,024-byte padded workload; it exercises LXMF resource transfer. The successor
retains each failed exchange's index, fixed first/last message-query states and
capped poll/transition counts. When an existing snapshot was requested, it also
retains both exact-text record counts and a unique outbound native-ID-present
boolean. An absent snapshot remains unknown, never zero. Error, operation and
phase bindings reject stale evidence; identifiers and message contents stay in RAM.
This adds no RPC, retry, native policy or deadline change. Full native/aggregate
acceptance, helper retirement and the remaining roadmap remain open.

Full run [43389512594](https://github.com/ahouchens/mesh-chat/actions/runs/43389512594)
at `b583f25` is **failed**: ten component jobs passed; both native peers and
the aggregate gate failed. Policy passed 6,163 cases, UI boundary 2,208 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases. Layout passed
72 cases with zero overflow. These component scopes do not grant native acceptance.

Both controllers reached `cold_start_receipts` after the sequential direct,
TURN/UDP, TURN/TCP, TURN/TLS and impaired path cases. Android then failed at
`path_read` with `contact_not_approved`; Windows reported `scenario_deadline`
in the same phase. Android gateway teardown reported no operation or cleanup
failure. The failure reports omit the iteration, resource ownership snapshot
and specific authority check. Human consent revocation and a product defect
are therefore unproven. Earlier path failures did not recur on this run;
completion markers cannot replace a complete passing native report.

The separate manual Linux gateway capability run
[43389004149](https://github.com/ahouchens/mesh-chat/actions/runs/43389004149)
passed at the same source, including synthetic egress STUN request and ingress
response capture and cleanup. It proves that observer capability, not native
ICE success. WebRTC and qualification thresholds remain unchanged.
An isolated actual-service/runtime regression reproduces a fresh reconnect
candidate becoming visible before its owner grants a carrier lease, for both
offer and answer creation. This is a deterministic qualification-readiness gap;
the missing CI inventory prevents attributing that particular failure to it.
The successor adds a private `pending_negotiation` inventory hint for an exact
current fresh candidate during gather, publish, answer wait/apply and checking.
It checks the distinct logical/physical mapping, owner operation, current work
or bounded polling state, authority, fences, retirement and the existing deadline.
It excludes recovered DISCOVER claims and grants no carrier permission.

Readiness waits only for one consistent pending row; raw inspection, ambiguous
resources, unavailable authority and revocation still fail closed. The controller
keeps its existing readiness deadline. A consistent pending row waits for
permission; raw, unavailable and ambiguous observations still inspect the path
and preserve its authority errors. WebRTC, reducer policy and authenticated receipt requirements are
unchanged. Full native and aggregate acceptance, helper retirement and the
remaining lifecycle/distribution roadmap remain open.

Full run [43379098108](https://github.com/ahouchens/mesh-chat/actions/runs/43379098108)
at `2af0009` is **failed**: ten component jobs passed; both native peers and
the aggregate gate failed. Policy passed 6,126 cases, UI boundary 2,176 Python
and 12 rendered cases, Android 56 emulator and 83 exact JVM cases. Both direct
platforms passed 25 transport, 10 recovery and 12 setup cases. Layout passed
72 cases with zero overflow. These component scopes do not grant native acceptance.

Both peers retired the first Windows-initiated direct pairing at
`checking/tick/phase_timeout`. Android's last existing stats poll reported ICE
failed; Windows reported checking. Neither a channel nor handoff was reached,
so the new carrier-loss witness and prior TURN/recovery failures were not tested.
The gateway reported no operation or cleanup failure. The underlying ICE cause
is unknown: this run contains no candidate inventory or connectivity-check trace.

The successor adds an exact authorized terminal retained-SDP candidate summary
and gathering labels from existing stats calls. Private ufrag digests correlate
bounded passive IPv4/UDP STUN observations at the owned Android gateway veth;
only fixed counts leave the observer. Missing correlation, socket drops, bounds,
ambiguous transactions or changed interface identity yield unavailable. Responses
are packet observations, not authenticated ICE success, and no observed return
at this veth cannot locate an upstream or Windows failure. Raw SDP, addresses,
ports, credentials and correlation digests are excluded from final reports.

A one-shot scoped socket broker transfers its descriptor to the existing gateway
parent and exits. The existing cleanup inventory request carries correlation;
no native RPC, poll, traffic, timeout, WebRTC library or acceptance change is added.
The manual gateway capability probe checks synthetic request/response capture
on its disposable veth separately; it cannot satisfy native qualification.
Full native and aggregate acceptance, helper retirement and the remaining
lifecycle/distribution roadmap remain open.

Full run [43370860477](https://github.com/ahouchens/mesh-chat/actions/runs/43370860477)
at `62c232d` is **failed**: all ten non-native jobs passed; both native peers
and the aggregate gate failed. Policy passed 6,072 cases; UI boundary passed
2,130 Python and 12 rendered cases. Android passed 83 exact JVM identities and
56 emulator cases. Both direct platforms passed 25 transport, 10 recovery and
12 setup cases, including Windows `address_loss`. Windows installed pairing and
lifecycle passed; all 72 layout cases reported zero overflow.

Android reached TURN/TCP `final_observation` after restored delivery and its
exact-resource current check, then failed `path_missing/no_resource`. The last
poll lacked its logical resource; the report does not establish when or why
that resource disappeared. Windows prepared retirement and waited for Android's
completion marker, but never committed it. Normal controller retirement is not
supported as the cause. No gateway operation or cleanup failure was reported.
TURN/TLS and impaired recovery were not reached, so their prior failures remain
unresolved. Full native and aggregate acceptance remain open; helper retirement
and the remaining lifecycle/distribution roadmap are not complete.

The successor adds bounded private evidence for the exact adopted carrier's
first owner-loss transition, suspect precursor and locally observed native-close
order. Existing final-path inventory requests carry the exact transferred
pairing target; stale, ambiguous or evicted observations are unavailable. The
controller retains capped first/last inventory facts and emits fixed labels only
for the matching final-path failure. Local event order does not prove physical
or remote failure order. No extra polling request, transport change, authority
bypass, recovery deadline change or relaxed acceptance is introduced.

Full run [43365547066](https://github.com/ahouchens/mesh-chat/actions/runs/43365547066)
at `a21646c` is **failed**: all ten non-native jobs passed; both native peers
and the aggregate gate failed. Policy executed and passed 6,047 cases; UI boundary
passed 2,105 Python and 12 rendered cases. Android passed 83 exact JVM identities
and 56 emulator cases; both direct platforms passed 25 transport, 10 recovery
and 12 setup cases. Windows `address_loss` passed, so the previous admission
timeout did not recur; its cause remains unproven. Installed Windows pairing
and lifecycle passed, as did all 72 browser layout cases.

Native Windows failed during TURN/TLS pairing at `path_read` with
`contact_not_approved`. This code also denotes native carrier authority denial;
it does not establish that human contact approval changed. Android timed out
at `adopted_observation` in the same scenario, with no gateway operation or
cleanup failure reported. The reports omit the exact owner/readiness state
needed to distinguish pending adoption from lost authority. The earlier impaired
restored-delivery failure was not exercised. Full native and aggregate acceptance
remain open, and helper-retirement implementation remains gated.

A deterministic service control reproduces a pre-claim inventory becoming stale:
the same carrier is claimed before owner adoption, and path inspection correctly
denies authority while contact approval remains intact. The controller now waits
when one exact matching resource is explicitly `unadopted` and `adopted=false`.
This deliberately omits a known-unready path sample; it neither catches a path
denial nor grants authority. Other metadata and raw inspection retain their path
checks. Permanent non-adoption reaches the original deadline. This source race
is not established as the cause of the retained CI failure.

Failure-only readiness evidence now retains fixed owner/readiness labels and
capped poll/resource counts from existing observations, bound to the exact
scenario, logical session, pairing and exception. It distinguishes initial
adoption from observation after transfer cancellation without exposing IDs.
The diagnostic adds no RPCs. Runtime policy, WebRTC, work deadlines, selected-path
validation and native acceptance requirements are unchanged.

Full run [43360865677](https://github.com/ahouchens/mesh-chat/actions/runs/43360865677)
at `4cf6cab` is **failed**: nine jobs passed, four failed and two optional probes
were skipped. Policy passed 6,013 cases; UI boundary passed 2,091 Python and 12
rendered cases; Android passed 83 exact JVM identities and 56 emulator cases.
Installed Windows pairing/lifecycle passed. Linux passed 25 transport, 10 recovery
and 12 setup cases. Windows recovery passed nine cases but failed `address_loss`
before fault injection: admission had an active epoch-2 workspace but no General
channel after 45 seconds. Subsequent Windows transport/setup checks did not run.
Separate manifest/channel delivery permits that intermediate state; the retained
evidence does not explain why channel discovery remained incomplete.

Native Android failed before pairing at `android_root`, exit status 1,
`connect_failure`; Windows then exhausted its partner-key wait. The discarded
ADB suffix does not establish a transport subtype or transient cause. The prior
impaired restored-delivery failure was not exercised and remains unresolved.
The successor retains exact-workspace, bounded admission failure observations
and optional fixed labels from already-captured ADB root errors. Original
failures, admission/root deadlines, one root attempt and WebRTC are unchanged.
Delivery and pending controls must share one exact General channel ID; missing
or conflicting channel bindings produce unavailable evidence.
Local combined boundary/diagnostic checks passed 2,180 cases; 6,047 policy cases
were collected, not executed locally. One actual two-worker source-mode setup
case verified diagnostic wiring. Full native and aggregate acceptance remain
open, and helper-retirement implementation remains gated.

Full run [43355120945](https://github.com/ahouchens/mesh-chat/actions/runs/43355120945)
at `a6ba6dd` is **failed**: all ten non-native jobs passed; both native peers and
the aggregate gate failed. Windows public pairing and lifecycle passed. Policy
passed 5,993 cases; UI boundary passed 2,071 Python and 12 rendered cases; Android
passed 83 exact JVM identities and 56 emulator cases. Both direct platforms
passed 25 transport, 10 recovery and 12 setup cases.

The native peers reached `impaired_kernel_block_negative_control/restored_delivery`
and both failed within the unchanged restored-delivery window of up to 90 seconds. Source
sequencing requires 20 impaired authenticated exchanges before that stage.
The Android controller had verified dropped packets and removed its exact block
rules; its failure report records no gateway operation or cleanup failure.
Message and connection state at the failed restoration were not retained, so
the underlying retry/recovery cause remains unproven. No parser error recurred.
Full native, 100-iteration and aggregate acceptance remain open; helper-retirement
implementation stays gated. WebRTC, work deadlines and success criteria are unchanged.
The successor retains bounded first/last message states and poll/transition
counts from existing queries on a matching restored-delivery failure. It adds
no RPCs, retry action or timing allowance; successful qualification reports are unchanged.

Full run [43349556210](https://github.com/ahouchens/mesh-chat/actions/runs/43349556210)
at `3094405` is **failed**: nine jobs passed, the packaged Windows public-pairing
job and aggregate gate failed, and native interop was skipped. Policy passed
5,950 cases; UI boundary passed 2,071 Python and 12 rendered cases; Android passed
83 JVM and 56 emulator cases; each direct platform passed 25 fabric, 10 recovery
and 12 setup cases. These results do not establish cross-platform acceptance.

Windows failed at `explicit_approval/invitation_wait`. The offerer was waiting
for an answer at five seconds and retired by twenty seconds; its first cause
was not retained. The current `ineligible` observation is not that cause, and
no response-parser error was reported. A default-off trusted-owner diagnostic
now captures the exact public intent's bounded terminal phase/event/reason
before client detach and host cleanup. It adds no public operation or authority,
changes no work deadline or success criterion, and cannot turn missing cleanup
acknowledgment into success. Full native qualification and helper retirement
remain open; the WebRTC dependency is unchanged.

Native run [43342460513](https://github.com/ahouchens/mesh-chat/actions/runs/43342460513)
at `10365b3` passed all ten non-native jobs but remains **failed**. Android
published `impaired_ready`; Windows then failed at receipt-inbound polling with
`CoreClientError: protocol`, and Android timed out awaiting delivery. Android
reported no gateway operation or cleanup failures. Completed impairment,
negative-control recovery and the 100-iteration native workload are not claimed.

A real framed-facade regression reproduced a valid 30-message snapshot rejected
by the Python client's request-only JSON structure limit. Response decoding is
now separate in the in-tree Python, standalone Python and TypeScript clients;
request depth/token limits and response byte, JSON, envelope and correlation
validation remain in force. A 256-message real-facade snapshot also passes.
The actual rejected CI frame was not retained; full native CI on this exact
correction remains required before helper-retirement work.

Native gateway integration [43337130170](https://github.com/ahouchens/mesh-chat/actions/runs/43337130170)
at `aa75c1f` remains **unaccepted**. Its Windows direct recovery test sampled
an attempted migration before a completed outcome; a condition-based wait now
preserves the original deadline and certificate/identity/message checks, and
both real Windows route-change cases pass locally. Independent review also
found bootstrap subprocess credential inheritance, now restricted to explicit
allowlists before the validated private-pipe handoff.

The native Windows peer timed out awaiting Android's impairment readiness.
A real subprocess regression reproduced a competing reader on the gateway's
stdin pipe: long-lived `adb shell` inherited the same reply stream. The wrapper
now keeps private, non-inheritable input/output descriptors and redirects both
standard streams before starting subprocesses. The stalled Android job was
cancelled without a final report; neither completed impairment nor cleanup is
claimed for that run. Full source-bound native CI is still required before
helper-retirement refactoring. WebRTC and the guest queue policy are unchanged.

Host gateway capability [43332384324](https://github.com/ahouchens/mesh-chat/actions/runs/43332384324)
at `bc064e9` passed on the same API 35 emulator image, including exact helper,
namespace, veth and firewall cleanup. The real guest completed three impaired
UDP echoes, both netem directions recorded positive packet/byte deltas, one
blocked packet produced no echo, and delivery recovered after unblock. ADB
forwarding and namespace DNS/HTTPS also passed. This is **capability evidence**,
not Windows–Android authenticated-receipt qualification or Spec 9.3 acceptance.
The native integration now uses the owned host namespace/veth for impairment
and retains the guest app-UID IPv4/IPv6 UDP negative control; Android's existing
`clsact` and the WebRTC dependency remain unchanged. Full native qualification
and the subsequent helper-retirement refactoring remain open.

Full qualification [43312523571](https://github.com/ahouchens/mesh-chat/actions/runs/43312523571)
at `2971c32` is closed **failed**: 10 successful, three failed and one
intentionally skipped diagnostic job. Android fails at
`impaired_authenticated_receipts/kernel_link_coverage/conflicting_qdisc`;
Windows times out waiting for its partner. No `impaired_ready`, completed
impairment, counted blocking/recovery or full native acceptance was established.
The fixed reason alone cannot distinguish initial queue admission from the later
pre-replacement equality check or establish whether mutation occurred.

Read-only diagnostic [43322062943](https://github.com/ahouchens/mesh-chat/actions/runs/43322062943)
at `e56285a` completed with successful bootstrap and cleanup. Both bounded,
untruncated samples of admitted `wlan0` show `noqueue` root plus existing
`clsact`. This concrete shape fails the current single-line queue predicate.
The report nevertheless remains **unavailable** under its strict consistency
check: IPv6 route expiry counters decrease by three seconds between reads.
It is not app-active proof of the earlier failure site or native qualification.
The revised diagnostic passes 23 focused cases and four unchanged resource
contracts; its workflow and WebRTC dependency are unchanged.

A production correction must preserve Android's existing queue policy. Merely
admitting a second line is insufficient: the current harness next creates an
ingress queue and assumes ownership of that queue during cleanup. Controlled
external network impairment remains permitted by Spec 9.3, with actual peer
traffic, bidirectional counters, no bypass, counted blocking and recovery.
The broader refactoring remains incomplete; helper retirement stays behind
independently accepted full native qualification.

## Earlier checkpoints

Latest full run `43231844458` at `a537bac` failed at direct supervisor pairing
on both peers before network controls. The retained terminal cause is
`checking/tick/phase_timeout`, not proof of a specific readiness blocker.
Integration `e220c96` adds only fixed failure-report labels from existing
controller status/inventory/stats reads; 1,410 offline interop cases pass.
It introduces no Core request, product/WebRTC change, extra read or deadline
extension. Full native qualification and causal diagnosis remain pending.

Full run `43223611381` at `98a5d9e` is closed failed on one false final TLS
supervisor-readiness sample after restored delivery. All nonnative checks
validate. Integration `a88674b` keeps the private final-path checks within the
existing 90-second restoration window and passes 1,400 offline interop cases.
The public API and WebRTC dependency remain unchanged; native CI is pending.

The controlled TCP/TLS harness is integrated through `b71cb05`; all 1,386 offline
interop cases pass. Private negative-control evidence now names a UID and TURN
destination scope, while UDP retains its socket/flow scope. No public Core API
or WebRTC dependency changed. Full packaged native qualification is pending.

Current direction (2026-11-12): TCP/TLS network negative controls are being
revised to use isolated app-UID/TURN-destination scope, without a WebRTC fork
or public Core API change. Runtime specification §9.3/SC12 does not require a
unique internal socket. Keep selected ICE, application counters, authenticated
receipts, exact cleanup, recovery and resource ownership checks; report the
network scope rather than an individual-socket claim. This revision is pending
qualification. Historical prototype and failure records below are retained.

The earlier qualification recorded below is `8fd57a445eec2ab12a86de51f3e0f4342f372d9c`
(tree `d2c69a224cd348ef316b623004d52fe7e16092ea`), full run
[43152914113](https://github.com/ahouchens/mesh-chat/actions/runs/43152914113).
It **failed: ten successful jobs, three failed jobs, zero cancelled or skipped
jobs**. All fresh local gates pass, including **5,711 policy cases**, **1,918 Python
UI + 12 rendered cases**, 32 lifecycle composition controls, six source-carrier
cases, nine Windows boundary cases, SDK staging/upgrade and strict policy types.
Policy and Python UI inventories exactly match CI, retaining all previous cases.

Every nonnative CI job passes and its evidence independently validates: Windows
packaged/public-SDK pairing and lifecycle, Android **56 emulator + 83 JVM cases
and 17 artifact hashes**, layout **72 cases**, and both Linux and Windows direct
**25 transport + 10 recovery + 12 setup** cases. Windows `address_loss` passes in
**142.770 seconds**; this diagnostic-only candidate does not establish repair of
the previous delivery failure. Layout screenshots were not visually reviewed.

Android fails at `turn_tcp_authenticated_receipts` before message exchange or
kernel block. Its `native_path_failure` reports `kernel_socket_correlation` /
`ambiguous_owned_matches`, with `tcp_state_summary=multiple_established` and
`owned_inode_relation=distinct`. Multiple app-owned TCP sockets match the TURN
endpoint, but the retained evidence does not bind one to the selected ICE pair
or explain why they coexist. Filtering only established sockets cannot resolve
this occurrence. The native DTO explicitly leaves the client-to-TURN socket
unavailable; relay candidate endpoints are not that socket.

Windows subsequently reports `PeerFailure` / `scenario_deadline` at
`receipt_delivery_wait`; the aggregate gate rejects the failed native workload.
The final-observation diagnostic below is not reached. No full native acceptance
is established. Read-only work is determining an implementable selected-socket
binding from the native transport owner; arbitrary socket selection, broad
blocking, added retries or a weaker gate are not justified. The previous final
path disappearance, local `97c32d5` lifecycle timeout and Windows delivery failure
remain unresolved. Helper retirement and subsequent roadmap promotion remain
deferred pending native acceptance and failure disposition.

This tested source integrates independently reviewed diagnostic component
`67aca65`. Its failure-only `final_path_missing` field classifies the existing
final observation as `no_resource`, `pending_adoption`, `adopted_not_true`,
`attached_not_true`, `messaging_ready_not_true`, `nonselected`, `mixed`, or
`unavailable`. It preserves the exact inventory/path reads and the first failed
readiness getter, keeping at most two distinct fixed labels. The field is bound
to the exact escaping `final_observation` / `path_missing` error and omitted for
cleanup replacement, unrelated failures or invalid projection. It adds no probe,
retry, wait, alternative path or relaxed acceptance rule.

Retained pre-implementation evidence contains **nine expected failures**. The
final affected controller/fault/path-setup run passes **848 cases**, preserving
823 prior cases and adding 25. Root and the independent reviewer verified the
committed source, artifacts and inventories. Precise classifications are tested
at the observation level; the serialized report path is tested with `unavailable`.
Source inspection confirms the connection, but this remains a coverage limit
until separate exact-source native execution exercises a precise failure label.

Fresh combined local and CI inventories contain **5,711 policy** and **1,918
Python UI** cases as verified above. The closed `ee1d8d1` failure and all earlier
unresolved histories remain retained. This diagnostic is not a repair or native
acceptance, and helper retirement remains deferred.

The preceding completed qualification is `ee1d8d11732bf0e749cef42217a822e2c156cce1`
(tree `be9b17f4ace1d4dab35678d4f1529c8de5c0a924`), full run
[43144241820](https://github.com/ahouchens/mesh-chat/actions/runs/43144241820).
The run **failed: ten successful jobs, three failed jobs, zero cancelled or skipped
jobs**. Fresh local SDK staging/upgrade, strict policy types, six source-carrier
cases, **5,686 policy cases**, **1,893 Python UI + 12 rendered cases**, and nine
Windows boundary cases pass. All 32 lifecycle composition controls pass. Policy
and Python UI inventories exactly match CI, retaining all prior cases and adding
only five reviewed policy diagnostics.

Every nonnative CI job passes and its evidence independently validates: Windows
packaged/public-SDK pairing and lifecycle, Android **56 emulator + 83 JVM cases
and 17 artifact hashes**, layout **72 cases**, and both Linux and Windows direct
**25 transport + 10 recovery + 12 setup** cases. The Windows `address_loss` case
passes in **152.093 seconds**. This candidate changes only test observations and
documentation; that pass does not establish repair of the prior delivery failure.
Layout screenshots were not visually reviewed; general service evidence remains
historical at `67a5210`.

Native Android system-image installation succeeds and both peers execute the
paired workload. Android fails later at `turn_tcp_kernel_block_negative_control`,
with `negative_control` reporting `final_observation` / `path_missing`. The source
ordering shows that the block/restore message checks returned before a single
immediate final `observe()` returned `None`. That result does not identify whether
the exact resource was absent, adoption pending, a readiness flag false, or the
path sample nonselected. The failure report retains no branch detail or complete
successful-case manifest, so neither a transport cause nor full path acceptance
is established.

Windows reports `turn_tcp_native_lease_retirement`, waiting at `completion_receive`
for Android's case-completion marker, with zero retirement polls. Its retirement
commit occurs after that marker; the retained source and reports rule out an
early Windows retirement commit as the cause of Android's observation failure.
The aggregate gate rejects the failed native workload before constructing a full
manifest. Both role reports are retained, and no aggregate acceptance is claimed.

The next bounded work classifies the failed observation using only its existing
inventory/path reads, fixed labels and bounded output. It must preserve the
one-shot final check, all receipt/path/retirement assertions and existing deadlines;
no added polling or relaxed gate is justified by this report. The earlier local
`97c32d5` lifecycle timeout, Windows delivery failure and TCP socket ambiguity remain
separately retained and unresolved. Helper retirement and later roadmap promotion
remain deferred pending full native acceptance and failure disposition.

That source integrates independently reviewed test-only component
`6076d30`. After the existing delivery wait fails, its existing diagnostic RPC can
inspect one unambiguous workspace-event delivery and up to four exact native
attempts. It uses nonblocking message/callback locks, at most 64 router entries,
object-identity correlation and fixed native/link/queue labels. Counts and output
are capped; the last message page is reduced to counts. The original 45-second
wait, retries, application behavior and acceptance rules remain unchanged.

The focused offline module passes **20 cases**, retaining all 15 prior cases plus
five controls. Its committed source and passing XML were independently verified.
The author reports three expected pre-implementation failures, but retained RED
XML is unavailable. This limits the independently archived regression evidence.

One local mixed-origin diagnostic pairs this test-only source with the retained
`75df902` CI dispatcher after all 14 tracked Rust/build-input rows and the binary
hash match. Its first attempt fails during bootstrap admission before address-loss
recovery. A filesystem-only call to the actual storage preflight reproduces a
failure at 301–307-character paths on this host, where long paths are disabled,
and succeeds at shorter paths. The original child exception was discarded, so
the first log alone does not prove its cause.

A separately reviewed and guarded second attempt uses a fresh short temporary
directory. Both real storage preflights pass at 238 characters; the single
`address_loss` case then passes in **156.53 seconds**, with unchanged source and
binary hashes and the first attempt retained. The CI delivery failure is not
reproduced and the failure-only native snapshot is not exercised. This local pass
is diagnostic evidence, not a repair or exact-source native qualification.

Fresh combined local checks pass as recorded above; full exact-source CI fails
at the later Android TURN/TCP final observation. The policy inventory adds
exactly five cases and the Python UI inventory is unchanged. Earlier failure
histories and helper-retirement prerequisites remain open.

The preceding completed qualification is `75df9027596b29bc0ee0f23675d2faa85b4c21f7`
(tree `98e06fdb1480bd1376ee5d6cead071436bfd0776`), full diagnostic run
[43133004290](https://github.com/ahouchens/mesh-chat/actions/runs/43133004290).
The run **failed: nine successful jobs, four failed jobs, zero cancelled or skipped
jobs**. Fresh local SDK staging/upgrade, strict policy types, six source-carrier
cases, **5,681 policy cases**, **1,893 Python UI + 12 rendered cases**, and nine
Windows boundary cases pass without skips. All 32 lifecycle composition controls
pass. The earlier `97c32d5` retirement timeout remains retained and unexplained;
these passes do not establish its repair. General service evidence remains
historical at `67a5210`.

CI policy and its required gate now succeed. The policy job takes nine minutes
and 23 seconds, including cleanup; it does not exceed the old limit on this run.
Policy and Python UI inventories exactly match local execution. Independently
validated reports also cover Windows packaged/public-SDK pairing and lifecycle,
Android **56 emulator + 83 JVM cases and 17 artifact hashes**, layout **72 cases**,
and Linux direct **25 transport + 10 recovery + 12 setup** cases. Layout screenshots
were not visually reviewed.

Windows direct recovery has **nine passes and one failure**: the recurring
`address_loss` case reconnects both authenticated peers, but the queued workspace
message remains absent at the receiver through the original 45-second delivery
wait. The sender trace now shows five sends rejected with no main RNS path, then
one accepted LXMF handoff and a local `sending` update. No later endpoint status
or receiver application ingress is recorded. The retained `transport_unavailable`
field can describe earlier attempts; it does not prove the accepted handoff failed.
The cause within native outbound processing, callback delivery or receiver ingress
is still unknown. Later Windows fabric and setup suites do not execute.

Native Android fails before peer execution while SDK manager prepares the API 35
Google APIs x86_64 `r09` system-image ZIP, reporting a ZIP read error. The log does
not establish network corruption, disk exhaustion or an SDK defect. Earlier runs
unpacked the same revision successfully. No Android role report is produced;
Windows exhausts its unchanged initial partner-key wait. The aggregate job fails
while downloading the absent Android report, before manifest validation. No paired
native path, guarded archive-404 recovery or TCP socket observation is exercised.

The next bounded work adds reviewed test-only failure observations around the
exact outbound native attempt. A scoped local reproduction may reuse the retained
CI dispatcher only with verified unchanged compiled inputs and explicit mixed-origin
labeling; it cannot establish new-source qualification or repair. A subsequent
full CI must use a fresh run with both peers and exact-source artifacts. There is
no justified SDK setup code change from this one unexplained extraction failure.
Helper retirement and later roadmap promotion remain on hold until full native
acceptance and disposition of the outstanding delivery, retirement and socket issues.

That source integrates three independently reviewed follow-ups:
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
retaining all 18 prior cases and adding four controls. The combined local checks
pass as recorded above; the full CI run does not establish native qualification. The prior local retirement failure
and TCP socket ambiguity are unresolved, and the remote cause of HTTP 404 is unknown.

The preceding completed qualification is `97c32d5951fffa9f66161b17ae01c98484e22cab`
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
