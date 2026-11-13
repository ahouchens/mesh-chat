# Connection runtime qualification ledger

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

## Existing Android clsact conflicts with test harness (2026-11-12)

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

All scoped nonnative evidence for the failed full run validates: 5,907 policy
cases; 2,071 Python UI and 12 rendered cases; scoped Windows reports;
56 Android emulator cases, 83 exact JVM identities and 17 artifact hashes;
72 layout cases; and each platform's 25 transport, 10 recovery and 12 setup
cases. Layout pixels were not reviewed. Full-run closure SHA-256:
`6cca198020e928842333a8d76b21918bd8506e736e2f827be52595076025ea23`.
Diagnostic manifest SHA-256:
`040296aa279aec5c28ea572c8113d30a21f3728cb5d47b00f8f453b01fcf3e26`.

## Android link inventory compatibility (2026-11-12)

Full qualification run `43293822522` at `7b02a9a` completed with 10
successful and three failed jobs. Android reached the impaired case but failed
`kernel_link_coverage/initial_inventory_unavailable`; Windows timed out waiting
for its partner. No `impaired_ready` marker or completed impairment, counted
blocking, recovery, or full native acceptance was established. The report does
not identify which snapshot failed or prove that no kernel mutation occurred.

Read-only diagnostic run `43303328513` at `cae9759` completed successfully,
including emulator boot and cleanup. Its API35 image revision 9 emits invalid
JSON from `ip -j -d link show`: an unused ERSPAN detail contains unquoted text.
The command exits zero without truncation. The same probe finds no `nft` binary
and reads an explicit NF_TABLES-disabled value from the running kernel config.
This is boot-time diagnostic evidence, not application topology or qualification;
the earlier failed run did not retain identical image-byte proof.

Reviewed correction `e055fdd`, integrated as `29bb4e3`, uses complete
one-line link inventory reconciled with individual detailed link and sysfs reads.
It preserves strict topology, identity, group, route, no-bypass and cleanup checks.
Missing `nft` is acceptable only with explicit disabled support in the running
kernel; missing, failed, enabled, module or contradictory evidence is rejected.
Root's eight affected offline suites pass **1,654 cases with zero
failures, errors or skips**. Fresh full native qualification remains required.

Spec 9.3 permits this controlled network test without modifying WebRTC. Actual
selected-path traffic, bidirectional impairment, counters, blocking and recovery
remain required. No WebRTC dependency, native host or public API changed. The
broader refactoring and remaining SC12 scenarios are incomplete; frozen helper
retirement follows independently accepted full native qualification.

All nonnative evidence for the closed full run validates: 5,892 policy
cases; 2,056 Python UI and 12 rendered cases; scoped Windows reports;
56 Android emulator cases, 83 exact JVM identities and 17 artifact hashes;
72 layout cases; and each platform's 25 transport, 10 recovery and
12 setup cases. Layout pixels were not visually reviewed. Closure SHA-256:
`583d94d1fa5c0cb7275754b481695b21026ffb3d34e2d58347151f052d7d3bf1`.
Diagnostic report SHA-256:
`dbe44b3f19a85677dd9d7c6242c7578ed0dfad4a676cded4ec2e491ec2089a90`.

## Impaired-case link admission failed after pairing (2026-11-12)

Full run [43276371484](https://github.com/ahouchens/mesh-chat/actions/runs/43276371484)
at `794ced6cd5af626fb401930a6cc08079a6a34def` completed with **10 successful
and three failed jobs**. All nonnative evidence independently validates:
5,857 policy cases, 2,021 Python UI and 12 rendered cases, scoped Windows host
reports, 56 Android emulator cases and 83 exact JVM identities with 17 artifact
hashes, 72 layout cases, and each platform's 25 transport, 10 recovery and
12 setup cases. Layout pixels were not visually reviewed. The redundant
automatic run was confirmed canceled after the full manual run became active.

Both peers reached `impaired_authenticated_receipts` after negotiation,
transferred-carrier readiness and identity checks. Android failed with
`LinkScopeError` at `kernel_link_coverage/alternate_link`; Windows then failed
at `rendezvous_receive/partner_wait/deadline_exhausted`. No `impaired_ready`
marker was published. The report does not identify the concrete interface or
which admission/install recheck failed, and does not establish that no kernel
mutation occurred. Prior direct/UDP/TCP/TLS completion markers remain progress
metadata, not independently accepted full native case reports. There is no
completed impairment, counted negative-control or recovery evidence for this run.
Closure manifest SHA-256:
`af180904a7a8698d70762fd4a85b3c99dd82d0733258f288d2fcc66f6ff52361`.

Spec 9.3 permits a controlled network test without modifying WebRTC. It requires
actual selected-path traffic, impairment in both directions, no bypass, counted
blocking and recovery; it does not require one internal socket or one interface.
Earlier pairing, checking and lease failures remain unresolved history. Reaching
this later stage does not prove that observation-only diagnostics repaired them.

Reviewed component `d10fa9a`, integrated as `3fa2b92`, controls a
bounded set of independent external emulator links. Each admitted link has
separately owned ingress/egress netem and monotone counters. Supported route
changes within the controlled set are allowed. Known dummy sinks are explicitly
denied; virtual backing alone does not disqualify an independent emulator link.
Continuous IPv4/IPv6 UDP guards require exact interface names and full-width
run-owned netdevice groups, preventing transient or same-name replacements from
using an unimpaired path. No loopback, IFB or dummy allowance exists. Group-
dependent policy or unsupported kernel capability fails preflight. The guard's
scope is app-UID OUTPUT and disposable-emulator UDP INPUT, with positive allowed
traffic and zero uncovered drops required. Existing two-rule UID UDP blocking,
selected native counters, 20 authenticated exchanges, RTT, recovery and original
deadlines remain required. Exact rollback preserves the primary failure and
separate bounded cleanup evidence, and never restores a same-name replacement.

Root's eight affected offline suites pass **1,639 cases, zero failures/errors/skips**.
This is component evidence. Real Android command support, netdevice groups,
IFB reinjection, guards, impairment and recovery require fresh full native CI.
No WebRTC dependency, native host, public API or connection policy is changed.
Remaining SC12 work and the broader refactoring are incomplete. Frozen helper
retirement follows independently accepted full native qualification.

## Impaired-case pairing failed before network controls (2026-11-12)

Full run [43265844092](https://github.com/ahouchens/mesh-chat/actions/runs/43265844092)
at `110833ccb18500f173af1124912f4d4ea032a067` completed with **10 successful
and three failed jobs**. All nonnative evidence independently validates:
5,824 policy cases, 2,014 Python UI and 12 rendered cases, scoped Windows host
reports, 56 Android emulator cases and 83 exact JVM identities with 17 artifact
hashes, 72 layout cases, and each platform's 25 transport, 10 recovery and
12 setup cases. Layout pixels were not visually reviewed. The redundant
automatic run was confirmed canceled after the manual full run became active.

Both peers published completion markers for the two direct initiators and
UDP/TCP/TLS relay cases. Those markers are progress metadata, not independently
accepted full native evidence. The subsequent
`impaired_supervisor_owned_pairing_windows` failed before network controls.
Android retired at `gather_answer/failed/invalid_document`, last observed as
`reserved/unread/unread/unread`; Windows retired at
`wait_answer/tick/phase_timeout`, last observed as
`offer_ready/one/new/connecting`. The new timeout-only diagnostic was correctly
absent on this different Failed event. Unread does not mean absent.
Closure manifest SHA-256:
`954fbad7494a244e58b3ca7fea7b4b4b029b6c9e6673302379dde44fba53103f`.

The source audit confirms that `NativeUnavailable` inherits `ValidationError`.
The pairing adapter maps that family and `IdentityMismatch` to
`INVALID_DOCUMENT`, so the label does not prove a malformed signed document.
The retained reports and generic job logs do not identify the raising call.
Earlier gather timeout, checking and lease failures remain unresolved history.

Reviewed component `422c150`, integrated as `e2b8aaa`, reuses the
existing exact-Work milestones for an accepted gather Failed/invalid_document
event. Its cutoff is the accepted Failed timestamp strictly before the original
deadline. Existing Tick/deadline behavior is preserved. The private failure DTO
adds a fixed exception family and an exact whitelist of existing native codes;
unknown values remain unknown and raw error text is never projected. Both host
and controller enforce retirement-event/DTO affinity and coherent category/code
pairs. Later worker completion or cleanup cannot rewrite the frozen observation.
The primary failure, cleanup, public API, Kotlin, WebRTC dependency, deadlines
and success predicates are unchanged. Generic `answer_failed` does not identify
an internal WebRTC operation.

Root's 15 affected offline suites pass **1,675 cases, zero failures/errors/skips**.
Fresh full CI is required. This diagnostic is not a causal repair or native
acceptance. The UDP-link correction and remaining SC12 scenarios remain
unqualified. Frozen helper retirement follows independently accepted full native
qualification; the broader refactoring is not complete.

## Initial answer gathering failed before network controls (2026-11-12)

Full run [43252465356](https://github.com/ahouchens/mesh-chat/actions/runs/43252465356)
at `1a545b8824950efc201e9706283df9fc2b1a0f28` completed with **10 successful
and three failed jobs**. All nonnative evidence independently validates:
5,805 policy cases, 2,012 Python UI and 12 rendered cases, scoped Windows host
reports, 56 Android emulator cases and 83 exact JVM identities with 17 artifact
hashes, 72 layout cases, and each platform's 25 transport, 10 recovery and
12 setup cases. Layout pixels were not visually reviewed. The automatic
duplicate run was canceled after the manual full run became active.

Both native peers failed during initial `direct_supervisor_owned_pairing_windows`.
Android retired at `gather_answer/tick/phase_timeout`, last observed as
`reserved/unread/unread/unread`. Windows retired at
`wait_answer/tick/phase_timeout`, last observed as
`offer_ready/one/new/connecting`. Android had no supervisor-accepted gather
result within the existing 25-second phase budget, so the normal answer-publish
continuation was not scheduled. The reports do not identify the blocked
suboperation; unread does not mean absent. UDP-link controls were not reached.
Closure manifest SHA-256:
`0db018cd7894d22b275699f96de9d3f0b4fc0f868d9e600dc4031318d218add6`.

Reviewed component `86ea358`, integrated as `dbc3ab5`, adds bounded
private gather-worker and application-stage observations. It retains exact Work
and original-deadline custody, selects only milestones at or before that cutoff,
and freezes a sanitized failure-only result. Later worker completion cannot
rewrite the at-deadline observation. The diagnostic uses fixed labels and age
buckets, preserves the original error and cleanup, and adds no polling or native
query. Public API, Kotlin, WebRTC dependency, deadlines and success predicates
are unchanged. A `native_accept` label identifies only the application call
boundary, not an internal SDP or ICE-gathering wait.

Root's 15 affected offline suites pass **1,642 cases, zero failures/errors/skips**.
Fresh full CI is required; this is diagnostic coverage, not a causal repair or
native acceptance. The reviewed UDP-link implementation remains in place.
Frozen helper retirement follows independently accepted full native qualification;
earlier lease/checking failures and the broader refactoring remain open.

## UDP link impairment replaces socket correlation (2026-11-12)

Full run [43238956725](https://github.com/ahouchens/mesh-chat/actions/runs/43238956725)
at `c28726949d577eaec8769ca891a2b932867dac7f` completed with **10 successful
and three failed jobs**. Independently validated nonnative evidence includes
5,772 policy cases, 1,979 Python UI and 12 rendered cases, scoped Windows
packaged/public-SDK reports, 56 Android emulator cases, 83 exact JVM identities
and 17 artifact hashes, 72 layout cases, and each platform's 25 transport,
10 recovery and 12 setup cases. Layout pixels were not visually reviewed.

Native progress markers reached both direct initiators and UDP/TCP/TLS relay
completion, including TCP/TLS block controls. Android then failed before UDP
impairment installation at `impaired_authenticated_receipts`, classified
`kernel_socket_correlation/no_owned_match`. Windows subsequently exhausted its
partner wait. These markers are progress, not separately accepted native results.
Closure manifest SHA-256:
`30cfd29900d746fa2858d5ba2806e4145242829f02150ae26fad67d4cce3772c`.

Reviewed component `40fd902`, integrated as `347c228`, removes the UDP
socket/DNS correlation gate. It admits a disposable emulator link through both
families' route and policy inventories, applies independent egress and ingress
netem, and blocks all UDP output for the exclusive app UID in IPv4 and IPv6.
The link impairment includes control traffic; evidence names this scope.
Selected relay/resource checks, native and kernel packet counters, no receipt
while blocked, exact cleanup and once-only restored delivery remain required.
Receipt, inbound record and fresh final readiness share the original 90-second
restoration budget. There is no product API or WebRTC dependency change.

Root's seven offline interop suites pass **1,443 cases, zero failures/errors/skips**.
Full native CI remains required. The earlier direct-pairing and native-lease
failures remain unresolved history; this change does not establish their repair.
After full native qualification independently passes, start frozen helper
retirement. The rest of SC12 and the broader refactoring remain open.

## Direct pairing timeout; bounded existing-read observation (2026-11-12)

Full run [43231844458](https://github.com/ahouchens/mesh-chat/actions/runs/43231844458)
at `a537baccf2694f4bf177215073fab3038fa8aee2` completed with **10 successful
and three failed jobs**. Independently validated nonnative evidence includes
5,762 policy cases, 1,969 Python UI and 12 rendered cases, scoped Windows
packaged/public-SDK reports, Android 56 emulator cases and 83 exact JVM identities
with 17 artifact hashes, 72 layout cases, and each platform's 25 transport,
10 recovery and 12 setup cases. Layout pixels were not visually reviewed.

Both native peers failed at `direct_supervisor_owned_pairing_windows` with
`supervisor_pairing_retired`, `pairing_status`, and
`checking/tick/phase_timeout`. Source progression establishes answer
publication/application, but the retained reports do not identify which
readiness condition stayed false or whether checking work was still in flight.
The network negative controls and shared final-readiness correction were not
reached. The aggregate gate correctly rejected native interop failure.
Closure manifest SHA-256:
`42bb24da61abe9482817399fd53b86676aa4c412ddfc4629dc24b1ae5629a389`.

Reviewed component `9921d52`, integrated as `e220c96`, preserves the last
preterminal controller open-session observation as fixed status, resource-count,
ICE and channel labels. It uses only existing reads, resets unread fields each
poll, and binds failure output to the exact operation/scenario/exception. No
extra I/O, retry, deadline, readiness predicate, product or WebRTC change is
introduced. Six new cases failed before implementation; root's seven interop
suites pass **1,410 cases, zero failures/errors/skips**. This is diagnostic
coverage, not a causal repair or native acceptance; fresh full CI is required.

The original `97c32d5` native lease timeout remains unresolved. Its separate
scope does not add a prerequisite to starting frozen helper retirement after
independently validated full native qualification. It cannot be called repaired
from later passes. The broader scenario matrix and refactoring remain incomplete.

## Full network-control run closed; bounded readiness correction (2026-11-12)

Source `98a5d9e7bbb4b0fe5e09f633d3a923e71aaaf6a4`, full run
[43223611381](https://github.com/ahouchens/mesh-chat/actions/runs/43223611381),
finished with **10 successful and three failed jobs**. All nonnative evidence
independently validates: 5,748 policy cases; 1,955 Python UI and 12 rendered
cases; Windows packaged/public-SDK checks; Android 56 emulator cases, 83 exact
JVM identities and 17 artifact hashes; 72 layout cases; and both platforms'
25 transport, 10 recovery and 12 setup cases. Layout pixels were not reviewed.

Both native peers published TCP completion markers under the new endpoint
block. Android then failed in `turn_tls_kernel_block_negative_control` at
`final_observation/path_missing`, classified `messaging_ready_not_true`.
Restored receipt, recovered records, cleanup and current endpoint/resource
checks returned before that read. The sample was filtered before native pair
and counter consumption, so their final state is not established. Windows
subsequently exhausted its partner wait at retirement `completion_receive`;
its retirement commit had not run. No full native acceptance is claimed.

The inspector reads supervisor readiness separately from native statistics.
A delayed supervisor inspection is a plausible explanation, not a proven
root cause. The specification requires bounded recovery and fresh final path
evidence, not an immediately ready first snapshot. Reviewed component
`f96075b`, integrated as `a88674b`, shares the existing absolute 90-second
restored-delivery window among TCP/TLS receipt, inbound and final readiness
checks. The inbound wait loses its former separate allowance. No new deadline
is added. Persistent unreadiness, late samples, scope changes and inspection
errors still fail; resource/epoch/pair and positive counter checks remain.

Eight test-first cases failed on the old implementation. The component passes
899 affected cases and integration passes all **1,400** interop cases with no
skips. A fresh full native run is required. The failed run's closure is retained
at `.test-tmp/ci-evidence-98a5d9e-run43223611381-attempt1/closure/manifest.json`,
SHA256 `be7ddb953eff2d28e3ea48f9afeb239396be6b750aa8faf94b59f5a183eb7ca2`.
Earlier unresolved lifecycle and delivery failures remain separate.

## Controlled network harness integrated (2026-11-12)

TCP/TLS component `bd4d5c2` (including `8de0a3c` and `4b38a9c`) is integrated
through `b71cb05`. It admits multiple app-owned TURN connections and blocks the
app UID at every frozen TURN destination and port. It preserves selected relay
statistics, positive drop counters, no blocked authenticated receipt, exact
rule cleanup and once-only delivery after restoration. The evidence names
`uid_tcp_turn_destination_set`; it does not claim one internal WebRTC socket.

The known retiring `:mesh_bootstrap` helper may overlap only with its verified
identity and no observed external TCP socket. Unexpected processes, resources
or established external endpoints reject the test. Host DNS is a bounded
candidate set, not proof of guest DNS completeness. Loopback is justified by
the instrumentation control server and ADB forwarding; the fixture configures
no local TURN proxy. UDP socket/flow and bidirectional netem checks remain.

The old-source two-socket contract failed and the replacement passes. The
component passes 885 affected cases; integration `b71cb05` passes all **1,386**
cases in the seven interop test files, with no skips and exact execution
inventory. These are offline checks. Full native CI is the next gate; numeric
Android UID inventory and IPv6 firewall capability are not yet demonstrated.
Earlier native/lifecycle failures remain retained and unresolved.

## Design correction: network path evidence, not internal socket identity (2026-11-12)

Specification §9.3 and SC12 do not require a unique internal WebRTC socket. The
harness imposed that constraint and the resulting native-fork investigation
exceeded what the network negative control needs to prove. The replacement
will use isolated app-UID and TURN-destination scope with selected relay stats,
packet drops, no blocked receipt, exact cleanup and restored once-only delivery.
It must report that scope explicitly. No new native acceptance is claimed.

The experimental patch, workflow and its helper/tests are removed from active
source but retained in Git and local evidence. No application AAR was replaced.
Bootstrap fix `abe1eaf`, integrated/pushed as `8ab6abb`, passed 21 focused offline
tests; its run `43217449532` was canceled during design review, as was automatic
full run `43217458228`. Earlier run `43161733290` remains a closed bootstrap
failure. The component descriptions below are historical, not the current plan.

## Integration revalidation (2026-11-09)

### Exact native firewall cleanup component (2026-11-12)

Reviewed component `acf48b989acae127051e059f37403048aec269fe` is integrated as
`9b1baa388ef5abff8c1b7d8d57fa120528e8138c`. `AndroidKernelPath.unblock()` now
attempts deletion of its stored exact DROP rule even when counter reading or
parsing fails. Successful deletion preserves the original counter error;
failed deletion retains rule ownership for the existing close-time retry.
Socket selection, probes, deadlines and acceptance rules are unchanged.

Pre-fix evidence contains seven failures among 11 focused cases. The component
passes all 11 focused and 851 affected offline cases, retaining the previous
848 and adding three regressions. Independent review approved its exact source;
the lead reran all 51 cases in the changed test file after integration, passing.
Evidence is retained under
`.test-tmp/reviewed-exact-rule-cleanup-component/`, including the original
red/green XML, source verification, independent review and integrated test XML.
These are fake-kernel tests. This fix does not resolve the selected TURN/TCP
socket ambiguity, and no newer full native qualification is claimed.

### Selected TURN socket C++ prototype (2026-11-12)

Source-only reviews approve upstream patch `91c8b35` and focused workflow
`8b2a468`, integrated through `c8e3bbaccd18ccedaf8859b8ec009c6b57a793b5`.
The combined cleanup/controller/path and workflow-gate tests pass **869 cases**.
The patch applies to the pinned WebRTC source subset and captures a socket tuple
only for an opt-in selected connection with a live port. Ordinary stats leave
the field empty. Earlier test-scope, GN dependency and nullable-port defects
were corrected before CI. The shutdown assertion checks stale tuple absence;
it does not directly force a selected connection with a null port.

The first focused run,
[43161733290](https://github.com/ahouchens/mesh-chat/actions/runs/43161733290),
failed before C++ compilation. Its 18 offline workflow tests passed; pinned
checkout, dependency sync, revision inventory and patch application passed.
`gn gen` then failed because depot_tools lacked `python3_bin_reldir.txt`.
The pinned checkout needs explicit bootstrap while automatic updates remain
disabled. No native C++ test verdict follows from this failure.

The run's 20 artifact files and failure log are retained under
`.test-tmp/ci-evidence-be7de74-prototype43161733290/`; its 30-file closure manifest
has SHA-256 `1cd2b9e91e054c54c7fc3bc0dc723b2cf344abe325efe08852a39e0468097e09`.
An initial evidence check rejected the Windows reference's CRLF hashes against
Linux LF. Reapplying the original pinned inputs and patch with explicit LF
produced byte-exact matches for all ten CI source files. Both references and
the failed check are preserved; no CI data were normalized.

The bounded workflow must compile `rtc_p2p_unittests` and require all eight
touched cases to execute and pass, with source, binary and XML hashes retained.
It has not yet built a native binary. The prototype has no private collector/JNI
delivery, continuity token, Android AAR or application integration. It therefore
does not repair or qualify the failing application's socket correlation.

### Cold-restart containment: full CI completed; native pairing remains unqualified

The latest completed qualification is `8fd57a445eec2ab12a86de51f3e0f4342f372d9c`
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

Native android archive SHA-256: `9e24455b43718c675488c0230cfc37c5fd2a8a4d5af9a9bb77a86824af921482`;
report SHA-256: `cc8e7020ebeec59191002baefb46c44e78095d45846d740a2545e48a8ded8df6`.

Native windows archive SHA-256: `312b9202f10d1d24a348234317ed7a617d92f31f572fc52f4ced138dc1e5b931`;
report SHA-256: `3f3b4870da54174b3b1edb50f25f1815ba9793ecef1795b5efe8e3e016b3e3e5`.

Same-head PR duplicate `42899863619` was cancelled after the full manual
run became active; it supplies no acceptance.

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

Native Android artifact `13798535981` has archive SHA-256
`ab134f4f3d82d50fa05a91ead0b5b8dbf24ac6d79e6bfb7ed7a4b1df2bdbfaa0`;
its 417-byte report hashes to
`9dc0124be9e166603e0e92d23ffda5e2365a31722eb94a3ef43b600786c7231f`.
Native Windows artifact `13798902788` has archive SHA-256
`feb189910fe9bd15092830da769743b477a11ee957526f637448940ab272cf43`;
its 409-byte report hashes to
`47a335f44729114e3bcced42c1875c9dbefc00df4f96dd6e9f5fa574454c5947`.
The same-head PR duplicate `42886842185` was cancelled only after the full
manual run was active; it supplies no qualification acceptance.

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

Diagnostic evidence binds to `7058909ca7c8e05c43e0ec0de9d2c813117af6cb`, tree
`6f9493108578b1ae4e6a9c7720717d6930353c4a`. The final focused XML SHA-256 is
`1ed6063e4680b2d34f8fd5d83e92a947e066f8682ea0024fdfa3d2b4dd80f595`;
the inventory is
`20a5a2e9606566c25ffe7a36544bb8ed2609fe61acbaeaa1d1ca118c2232aafd`.
The eleven-case semantic RED XML is
`aa2f22697eaf777bde454ea296ede61aa4b1f7e890493e38e94767edd851210a`.
Root verified both changed Git blobs, all nine retained artifacts and exact
preservation against the prior local policy inventory. Intermediate incorrect
test assertions and the mistyped test-path launch remain separately retained.

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

Retained corrected composition XML SHA-256 is
`e8fbc6bffe76a04ce925d48b6e61d5fdc5bbbb41fea3626a872fa6bce4f869df`;
its complete collected/executed inventory is
`726223b5a5ec7972687fce948b6198a5ed786f6712adeece2df5bc0b2071fee2`.
The lost-notification semantic RED XML is
`6d5cc843d2e20d47221d96af5af1b8f1bca10faea1d371b8d0c26da25fda19f9`.
Root rehashed 19 source inputs and 27 retained artifacts, checked all 18 prior
case names, and verified that the serialized fixture functions are unchanged.
The earlier 28-case pass, four incorrect test-expectation failures and launcher
path/import failures remain separately retained. Final evidence is bound to
`ce4b9c468596916b549cad579e13c2b55e7cb9e7`, tree
`973d96e3df636ac9ec97b5e56b5ee0f0f786ffa1`.

Retained producer XML SHA-256 is
`c87c35c3656a693b9bd4911699d9f5db25ec98ef5b9f6cca760eec911532da47`;
its exact 445-case inventory is
`bcd04589ab00fc1870ba7d287a79be82ac6b445e6c0a272bf4f8f481c23a3cc8`.
Consumer XML SHA-256 is
`460a8b87743a7b6f7cbee312256fcd9f34c344b0478eb8f58ce76e45071da638`;
its exact 998-case inventory is
`48f5f233bcf6b0e759ea726eda48d164d90cff6136b5bee759038a440193a8a2`.
Root verified all 21 changed source blobs and the retained artifacts. Four
producer mutations fail when replacement protection, positive native receipt,
fresh contact comparison or current adapter epoch checks are removed. These
sources were restored before the final producer run. Intermediate fixture and
launcher failures remain retained separately; none count as passing evidence.

Retained diagnostic XML SHA-256 is
`263f4ab12da8f6bb31226ed5fccb2390dcd3902f8ac64b8ebea77fec32f9341d`;
the complete 739-case inventory is
`49ac55727b6df90b7d0ab93493c8aa66121722ef9942fd87de99bc43c3603991`.
Three-failure semantic RED XML is
`35f837c93f397be8b4a1b1568b550ab22157a81ae0e3513e5b5001a0c6c097b8`;
the separate launcher-failure XML is
`5ea50fd3741121083fe1e11d32cb97c1bd8b74c158fabe9bcdaf2b582e2b518b`.
The frozen preparation contract is SHA-256
`6ca4ca2ccd4807d66e38396258f0361f8721ac0cec255ed8a73b7516dbbd3fed`.
Its accepted provenance is the trusted in-process native closed callback plus
captured host/service and nonreused fresh physical identity; current callbacks do
not carry an independent host/adapter tag. Restored resources are excluded.
Android failure teardown remains bounded shutdown attempts and service detachment,
not unconditional JVM exit. Those limitations are not upgraded by this design.

Retained `ccd3b51` full-run archive SHA-256 values:

| Run | Evidence | SHA-256 |
| --- | --- | --- |
| 42857623266 | selection | `13d48d59835e5668b19ffc984e494fa9229b03a969b02a7e9e1207e6eb768059` |
| 42857623266 | policy | `483c7567c5a4822708c9b8ca607466382f1d805e59395f4a63f7074444fc2fd8` |
| 42857623266 | verification | `ecdc6fa20fc43b304fd0f8a8b02f92345c5e390941f408269deca86ccf47f68c` |
| 42857623266 | native-windows | `e93035988a145a80838052ebec17dc4a9e59e0dad51166ad8ce7fe341603a123` |
| 42857623266 | desktop | `37a0cda14165e7e3a2782cef38c811ff8b57f7f04a0a603c2692ee650341a958` |
| 42857623266 | android | `62f16a286fe7e5d66fb398efefe74f411c36055682f2f8be907574f737796e1a` |
| 42857623266 | android-debug | `cfffb946906ee57334b512c1ac7c0bb1cfa2da0dafd0b95ba276d7803ba543bf` |
| 42857623266 | direct-linux | `f573231a093baf807f671b168f68db854e5e8d198af68bb3b6f20e3d738294a3` |
| 42857623266 | direct-windows | `77b751a6c24fc7f1252d737ea89ea79335bde81835f7cb74c91dfd3e91cc0030` |
| 42857623266 | layout | `c4f1c507132dcb2d9c5406530b4a413a56df060d3244fa6db889ab36de4f8909` |
| 42862760087 | selection | `da2d6e20fb9dcd870c52fc22f17a1eae818ae7dca08d04390fc82e3ac1f4ccfc` |
| 42862760087 | policy | `e756ed99f28816ce6da68d94a5cb0f23bc8da571b3a0e6329cc528ce0b5935fa` |
| 42862760087 | verification | `ae5607ffd9c234ccf87aeda6f40366cb5159d8b50fc3e096b7bd598e75e235d2` |
| 42862760087 | native-windows | `454af95080d0f215d9169172b51a9346cab1609534a5827d73646615974eca8a` |
| 42862760087 | desktop | `5a465f9828f313881f251ebdabef2e9a0ac93c58468de880066f51e54b2c422d` |
| 42862760087 | android | `be3163b0fe874731ad7bacc2ea22f02179e526cd8b208ab2df44eef851dafc53` |
| 42862760087 | android-debug | `606926c8064357543e9202f62d804e2689a96ce24cfb49b71b6241e18cbe530c` |
| 42862760087 | direct-linux | `9122d2b11d3b5bc0a2bf874f94f7b2b2057824917a1dd344c465a7a5f3ea08ec` |
| 42862760087 | direct-windows | `687aa552a73869e4a75f402af254e1fef097c9a4b5c265d1cabb3bc48f113f36` |
| 42862760087 | layout | `e90227762e84ffedfb3e74e3e6858e1fe94d56e77caba4ed2ac0bdb952f0a3b7` |
| 42862760087 | native-interop-windows | `02f604124435680ce3e63c1f91e46bd14e96f482c12494fabfbd88523a440b96` |
| 42862760087 | native-interop-android | `3d7701c769129884a60930f64a411e3d852d0781a61460caa9ed6c22887b2a63` |

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

Retained `36466e0` / run `42843336931` archive SHA-256 values:

- `selection`: `3ebb98528af0ee7a24fa87a6c1bda38a106d11d1b4717023eac521152a6ac461`
- `policy`: `a3d53bbf92ccd5ffa0c9ce97fdf6ced6d5417220a3a1931aa3308ef65664b7db`
- `verification`: `eb435a0816df2c8a68fe85992b120db9cade31a64abd2f6473128223cb19f67d`
- `desktop`: `3b3b1c368f3a497ea4c84723c1a766e428697d223e6824d32a416c8b8721f084`
- `native-windows`: `6ddf1f2c72c30b715c2ca174a7805e9c16bb268df55e6e46bd83073b11ee38ac`
- `android`: `f45f277f24324a9405c71a58df9bfd5aab2a374d58779a8b75c93de986b822e3`
- `android-debug`: `34cd9af38895ed7d90f13c558b21466fbf3d2cf242f5b4c93127349fa87779af`
- `direct-linux`: `2396f02ca7d03d5f9951ae2473006227211d83c96aab8cf9930c6a74a45028eb`
- `direct-windows`: `48a645b3d7deeb3c67a568b568625c09d819e3226a7bf298855a65ff1fb8bcd8`
- `layout`: `4efc1969063ad0ba9974d5b9b1bffd8a1ae14ee44f498a111b762a4c29cbbbe6`

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

Retained `5e6d0da` / repeat run `42824231976` archive SHA-256 values:

- `selection`: `14d04a033bb7d833c939acfb76e069ffbccc7aea5a645a9bb60f1b0de26aedd1`
- `layout`: `62bebd9fdaebc195323f01a14040a8188533a25afe9d055f0ec0974721663876`
- `policy`: `90e184504247301b76ce3d42d33fefbc0d2521f8b1b4bdc3f380b62e0d6336ad`
- `verification`: `048fe049166b5f6b16183bb2b694dac68895df45c2c4e6b47d6d113b42770321`
- `desktop`: `7bd6b67751cd5ae1d61bcf885f6330c85902ac3a9108c10dec72ee2586447337`
- `native-windows`: `109959089cb79208cd12c538854815ce996577c0f0c554644bfd0269d5d06dfe`
- `android`: `993ba94657e54d075f071a9189610319a65eb98fa9681f2843827e84562ae5d1`
- `android-debug`: `bf181253b8618c656ef13ef9d2066b41bed4424804da0205524d8254fae31071`
- `direct-linux`: `e537bc82187aa1f27f22368c41e7af178bf04412c6aded967cebec16ed36c6e1`
- `direct-windows`: `66a921f7948d74f23659fdc0e9a77e20b4ee75e0a1f88e30cc2c2a3467ec6e06`
- `native-interop-windows`: `54dbe5047862298eb720f356125ebc8fc01f2307e74ecf266ea7748de9b917d2`
- `native-interop-android`: `8b3425c8983876da946157cf57da14529c62940301b40450975bdb61fa518c40`

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

Retained `c0b3cf7` / run `42810308484` archive SHA-256 values:

- `selection`: `af7d3eab67d0fc9728a2ecda0abb03aba3b7972583de957b127f104fea173f0f`
- `layout`: `1edaabfbe1244c897251f2051550eb8650a9dd8e691c6d92f1d1d5340a93887b`
- `policy`: `5144e49a35cf6d61da7755638f3ce04510e47ea5f35c984b8fb82e9091cfc121`
- `verification`: `982a456306800983021e5dbb233467539e76e615522fc598d8e19394affa6dae`
- `desktop`: `f1d5c76c33a07d106e64a6e682d5607ed13c37bf02d42164a14f1c5b52b4f6d6`
- `native-windows`: `029f5eafb903b96f65fa305de84293aff9b00e44f778fa8f5c4503dd920a262a`
- `android`: `ed5385d7e49c404b853177a8a40a0b8a5b54fc8166df6ac701ef8c2e697c62e8`
- `android-debug`: `2ba140e1c73d83a69ce4eb60c0c8575c4024f33c21ab2a7d3d6a609de155ff8b`
- `direct-linux`: `a522d7b6dfaee892036e8895fef7a32910fb11232aaa058b677f9a8e6e2c494f`
- `direct-windows`: `316ed6f6e8c04863b5b5882bbb842d71e7650668751ddde778a156cabc8b78d9`
- `native-interop-windows`: `189d011de45784c8ebb7ad03bf82ddfdb8fa67f2f94d32515d6e19d4dcc1d3bd`
- `native-interop-android`: `646dd8193f2afef1b5523455f82af2c69ece268426e5effa6e1345572891d9d7`

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

Retained `1b3a2be` / run `42802755780` archive SHA-256 values:

- `selection`: `c9ae102a61eea1ac8efdf71f1c231b04a67db21620ee1cbeb1ceb7013004852f`
- `layout`: `d766be7f4b3bc5dfb5d69233c6fe6b206002bd018aaa31638c5c076ac9505157`
- `policy`: `21d6f2d3c07e2eae5058bb76c3d011ad7a9545c9f48f47b0fd6df19f8fd9be44`
- `verification`: `5fd19d0806fd9ad32499bf21d877faa06b39cdd8d9efadee86e5eccde078dc12`
- `desktop`: `19951d1ba4d4e29091b4ecb2c1d50fac9fc0afc37e5fc99d7b07ec4fa07ef7b2`
- `native-windows`: `ed51745e3fd8d97b77b415fb4be3ac572730ddd97136e1718e75dea096aec580`
- `android`: `ec6fe34bcb7ca8129c05d0be1170c716365f9b1be676095bbd029a41127655a8`
- `android-debug`: `d0ed4bdba5c1111acecb25d5b7f5f66720e80f5e523cd6ac4c44bebd20240748`
- `direct-linux`: `c02f4897d594a6c177ba6eac1d7190c2c2ffb814b145e92fa234573ef97d2078`
- `direct-windows`: `b34dd4db155c2ecbc949944c67691dc73f95092084ba5db173e8daa1a1658e91`

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

Retained `902b12d` / run `42796005344` archive SHA-256 values:

- `selection`: `9ea15cba8ef31a7b41157f5de354b91728a6cebf933bb431291b766316c6a98d`
- `layout`: `24039597a5e030b11490f5c8973fc30ecc3fa35c62d3ccde1fb19729eaee816e`
- `policy`: `75b0c15129ae1dfea00d4ae1073a69ad9330e708f3281d435ae4b9633bcb509b`
- `verification`: `8cc6d8980716adcd1280b67e3e9b56a862fcdd25a1d3aba765a2e34a43791e17`
- `desktop`: `3919da52cab7fcee61017306c72b1ef4a782a739b717444db91053a3b310d393`
- `native-windows`: `a530e789f4913e23f23973c5ff282e66401c53fedc508548d5d8c7c7c3a875db`
- `android`: `22e924aa38e6bf9369ff102afb541fef9ce59b4cb9f43edf09fe52395ea97e2e`
- `android-debug`: `effdc5e63cf633a3359c9893e4b52560e0c99a209ca000dcd3f014c9ffa142d1`
- `direct-linux`: `35e1550c41f7f55f3b704929c3c3e9599b09e872b02c8dcde9cab612f2f24e50`
- `direct-windows`: `ccb1c5f856b6b6f02484a80fed177a2c92082e11f763d0969d0e97fa4e9bb12d`
- `native-interop-android`: `a5642f2dd8f25dd065958e1011206e364b671914d46680f1ca71c90daa627b67`
- `native-interop-windows`: `c27a765184af6f327a2a51249015060170773f2f98ffe32a68e4ca040d3c5a04`

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

Retained archives for `65b0872` / run `42784376932` (SHA-256):

- selection: artifact `13747682805`, `54a6dfb0da7936524c3eca31f91ba4586cc22d234b58d015fe394641d3e3a682`.
- policy: artifact `13749610519`, `2a68f9eca4470678360664c242165dfdf2fc12db1b26a8fe2afdbaf397242daf`.
- verification: artifact `13749151806`, `5965f1f8982fd7febd5792bbc3132d767d52e8ac979db1147a7b5bd4770be321`.
- desktop: artifact `13749006155`, `4118d6231117cc18d7bdad520a8d96815452bba4d0b9c8560ab503a8d4355947`.
- native-windows: artifact `13749730859`, `8577a8e98edf40e6232d73b77c45c6652d3d4a7545b9334fddf4e8f5354071c5`.
- android: artifact `13747899912`, `988286843935593a9837962e16359cea4f07da7f25712c2692df88b0ca7ed6c9`.
- android-debug: artifact `13748174795`, `a97266ecfd270c55d8f081213448b99d800cc323429acd4a9287575f7e2a5f53`.
- direct-linux: artifact `13749149429`, `11843afc96d70a33751953144fcffe19b87c28ad475c2a880d5350266812cb66`.
- direct-windows: artifact `13749234385`, `9dbf1df0772e8e356d2c4d4b3538decb0dabc43cdf88d8f56b35f12dadc376a9`.
- layout: artifact `13748151335`, `110f6867f43782eb747788ae2b2466208fbd54b63551f619b071aaa7faa8a830`.
- native-interop-windows: artifact `13750345141`, `e6ce55bdb06ccc585b2d37e5b43220c552a1ba05b7edd5596d854d148a13f9b9`.
- native-interop-android: artifact `13750325135`, `eccabc66bbb3aff11a704e1affe40b927a6b3636d9facaa4a11a48eb58e49ce2`.

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

Retained archives for `606f68d` / run `42776359931` (SHA-256):

- selection: artifact `13743544163`, `56541aa0e795b6befa8eaed597238e337d1c013e2ef786eecf0f88a3e67e1625`.
- policy: artifact `13744316912`, `3cb2057b85ed2b52aa144fdb96f9edef4f5ce572199b58e5862f277342edbfc4`.
- verification: artifact `13743869371`, `cd6012c306972bf25b4a26db14d95b6c8cc67ead63bf5259e732e1992607293c`.
- desktop: artifact `13743789369`, `c49c9d8ba2b3526b66d108b653a3c1e69b3a120c7a65edc270eee4fc278a2dc3`.
- native-windows: artifact `13743963447`, `145f827ca945baeeb0ff1569cb4f33709083e3b87523653c8adc25845217a35f`.
- android: artifact `13745755318`, `32801ddacb6df68695510571027f712cb9d934e1c13524e66ff2cb6ddc3f1249`.
- android-debug: artifact `13744648829`, `205ead1ce41b03e7bf40054d64c0611704ec0dc04bee4558442669b5ec894667`.
- direct-linux: artifact `13745052651`, `e976103903096035ea32b7915623c7a10ba1d76ab601d10b709c3d000f3c7226`.
- direct-windows: artifact `13745007084`, `ba938ccffe9694f70fd4267c0676561b136cb9d42b325563d126832fe0aecf23`.
- layout: artifact `13744421067`, `22785cf60fb8656ee3e05c9ae0a5ca3041aa61431b77241fefd7ee2162181f65`.

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


Retained archives for `82aaf19` / run `42770728559` (SHA-256):

- selection: artifact `13741671633`, `8a41034ff9003120eacaf91ee354cbe92dc219774417cc502ac78d57f53411e9`.
- policy: artifact `13741378329`, `5f3d1bbc3928c48d1e107af1cee6b344158e751eadb45ee2bb0af47817f10009`.
- verification: artifact `13741958363`, `bc5013a46e717932a0cbf31672af30c197a1d587b201b500d8fddd368613901f`.
- desktop: artifact `13742450724`, `456929223f30b372ff7b244f313d26a143f00ba17b010ff647f5b3fa1f337a8e`.
- native-windows: artifact `13741782526`, `a2aa563c05157398a14dcb39495fdda3dc2c6286a6b5147ec554c27191555e0b`.
- android: artifact `13742507312`, `da1008720b4925de951524be1f1ea2de13be87f27d78cc0c908088a1e4f99e1a`.
- android-debug: artifact `13742397862`, `8a9ae8cb4e5d89ef48038c92d3222851cbdea10c5d184548b370df592c2137bd`.
- direct-linux: artifact `13742582831`, `f98e3d6561e464fff33d231b6203d920b3ebcd9fc29450172ba43f62309b8978`.
- direct-windows: artifact `13742279671`, `eee3329ec938a2b2cce1919cd07c49890b4ff5bbf249e9363e79ba9017f71722`.
- layout: artifact `13741892339`, `b7dd0fdfc890b90e66b092d9c8b1a3d5e385a0396175ce58c2956505631d4c5c`.
- native-interop-android: artifact `13743065129`, `14fdf242cabd3021b299acc88be2a5708e9be04860761a3a514943585e537b04`.
- native-interop-windows: artifact `13742706415`, `76039d0dcf61597d7b9a5d323f60eda74bf3fb2ca7267b163d231a0c582aec06`.

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
