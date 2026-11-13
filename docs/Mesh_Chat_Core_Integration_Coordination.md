# Core integration coordination — 2026-11-09

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

Harness integration `b71cb05` contains C's endpoint rules, exact cleanup and
verified bootstrap-helper overlap changes through `bd4d5c2`. Root's seven-file
interop run passes 1,386 cases, without skips. Next is full packaged native CI
with exact-source evidence; no fork/AAR changes or native acceptance are claimed.

Current assignment correction (2026-11-12): use controlled network-level
qualification as specified in §9.3/SC12, without modifying WebRTC. C implements
isolated UID/TURN-destination TCP/TLS rules and truthful evidence; B reviews
scope and immutable changes; D verifies emulator/control-network boundaries.
A's unpushed continuity prototype is held. Root removes the experimental fork
workflow/source, integrates reviewed harness changes, and resumes full native
qualification. The unique-socket gate was an extra harness assumption, not an
original product requirement. No passing native result or roadmap completion
is claimed by this correction; historical checkpoints follow.

Baseline: `435b497150e5f0d12cb1c5dc7b4602da7a66ec4c`.
Lead branch: `codex/mesh-core-integration-lead`.
This file records assignments and integration decisions, not passing evidence.

Current checkpoint: Wave 1 is accepted at `174728e`, pushed to the shared feature
branch. Full qualification run `42644737670` passed all five suite families and
the final gate; the lead independently rebuilt the aggregate from retained
reports. Exact evidence and limits are in the ledger. Wave 2 is activated below.
Existing human authorization covers continued implementation, integration and
worker follow-ups without another permission request.

The next bounded batch has integrated the independently reviewed exact-rule
cleanup component as `9b1baa388ef5abff8c1b7d8d57fa120528e8138c`. Its 851 affected
offline cases pass, and the lead's integrated rerun of the changed test file
passes all 51 cases. Counter failure now still reaches deletion of the stored
DROP rule; this does not change the socket matcher or resolve its ambiguity.
The isolated upstream selected-socket prototype (`91c8b35`) and its Linux C++
validation workflow (`8b2a468`) passed independent source review and are integrated
through `c8e3bbaccd18ccedaf8859b8ec009c6b57a793b5`. The combined affected suite
passes **869 offline cases**. Focused run `43161733290` against pinned WebRTC
source `73cb8180f7258ee292878d6edd05177f41883962` failed at `gn gen`, before C++
compilation, because depot_tools lacked its Python bootstrap marker. The next
step is the reviewed pinned-bootstrap fix and a fresh focused build/test run.
Separately, worker A is preparing a socket-generation/capture-time patch;
integration of that next native layer waits for the initial C++ prototype pass.
The workflow requires all eight touched C++ tests to exist and execute exactly
once, records patched source and binary hashes, and rejects skipped/unrun cases.
No custom AAR, JNI path, application dependency replacement or full native
acceptance follows from these component checks. Prototype source and approvals
are retained in `.test-tmp/reviewed-native-prototype-integration/`.

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

Earlier checkpoint history follows. At `a175ae5`, the feature branch was
`5ea2949`.
CI `42693457737` has three known failures, repaired locally: Windows empty
identity assertion (`e8f73e0`), separate Android instrumentation module compile
(`d23452c`) and exact CSS-selector/layout guards (`706df7f`). The exact repaired
UI boundary passes 664 Python plus ten rendered cases. D's public Windows
pairing producer is integrated with 287 focused passes, but requires an explicit
relay-only follow-up before dispatch: direct pairing gathering consent does not
grant persistent personal messaging consent. No private bypass is permitted.
C's standalone Android host plus catalog/startup safeguards `dfc47da` is
integrated, with 38 lead host checks and 26 actual-source JVM checks passing.
A's atomic group producer/SDK `76ed4fb` plus `306feb3`, B's group UI `86366d0`
and owner-retirement follow-up `839c076` are integrated. Eighty App/controller
checks pass after retirement integration. D first repairs the independent
group-operation vectors and real rendered fixture, then continues the
outside-checkout Android runtime-host consumer. Existing worker ownership and
human follow-up authorization remain in effect. No standalone AAR/device claim
follows from cached Kotlin compilation or Python/JVM components.

The shared checkpoint includes C's reviewed Android provider correction
`0bfb95d`. Separate protected catalog authority avoids reading the profile key
at locked startup; each OS credential confirmation uses its own AndroidX result
registration. The lead's exact SDK staging and 115 lifecycle/mobile-host checks
pass, including installed consumers. B may bind the actual Android credential
facade; Windows remains unsupported until its native provider exists. D adds the
three registry cases to required Android execution. Compilation and JVM checks
do not qualify successful OS credential interaction on a device.

Full CI `42683615511` completed with a failed gate at the earlier `21bb99c`
checkpoint. Policy, Windows packaged first-contact pairing, 649-Python/ten-App
boundary, 47 Android cases and both direct-transport platforms are independently
validated. Broad verification also passes. Windows native interoperability fails
because its controller used an invalid pipe namespace; Android then fails
rendezvous. Repair `19dcf00` is integrated at `1ba621c`, with all nine Windows
component cases passing. A fresh full run is required for the repaired controller
and all subsequently integrated production changes.

C's hooks and A's durable public pairing producer are integrated at `787b6aa`.
Exact SDK staging, 79 actual-actor/installed-consumer checks, 50 TypeScript SDK
tests and strict model/reducer typing pass. B's WebRTC call-site scope wiring
passes 61 focused checks. C's native disposal coordinator retains failed peer
and channel wrappers until exact acknowledgments; all 21 actual-source JVM
checks pass after integration at `0d4758e`. Actual Android execution is pending.
D's normal installed Windows bootstrap gate is integrated at `b4d3277`, with
162 focused checks passing. Its actual frozen/EFS producer remains CI-only;
these component results do not qualify SC21. The full local policy run at
`787b6aa` has 3,359 passes and nine failures: eight external-fixture inventory
path failures and one missing pairing-vector inventory. D's pairing vectors
are integrated; the inventory-root repair and complete rerun remain required.
B continues native profile UI and C the standalone Android host. The older
checkpoints below retain their chronology.

The inventory repairs and B's native profile controls are now integrated at
`5ea29493d0420896a8801169c78145e640fdc5dd`. Its exact SDK stage, complete policy
(3,379 passes, zero skips), App/Core boundary (664 Python plus ten rendered cases)
and nine Windows host components all pass. The lead pushed this checkpoint and
dispatched full CI `42693457737`; duplicate PR run `42693436511` was canceled.
Native profile UI retains explicit keys and rejects late credentials/results
after host replacement. Device credential execution, renderer-restart key
recovery and actual browser-media retirement remain unqualified. A/B review the
next bounded storage/ownership contracts; C continues the standalone Android host
and D the normal Windows installed-SDK pairing producer in separate checkpoints.

Current Wave 2 CI `42676194199` at `da81565` fails two synthetic run-context
fixtures and Windows first-time pairing (`approved_path`, both carriers absent).
The fixture repair is integrated and passes all 94 matrix checks under CI-like
context. C and D prioritize production handoff diagnosis and bounded probe
diagnostics before another full dispatch. Local `a899b85` passes the exact
640-Python/eight-rendered-App gate; `50474ec` adds independently installed public
SDK application staging, with nine focused passes. These do not establish SC21
traffic or packaged acceptance. A's call recovery must preserve ordinary
start/end/start behavior and require actual trusted retirement before replacing
uncertain media resources. B's group keys remain explicit and capability gated.

The run has finished with a failed overall gate. Both controlled direct-network
platforms pass independently validated 25/10/12-case inventories. Android's two
manual-readiness fixture failures are repaired by targeting the inner reconnect
executor (`3a122d4`); Kotlin explicit-key assertion and license packaging repairs
are integrated with host-gated call recovery (`5be412a`, `dee09a7`). The lead's
248 focused checks pass at `5556cc0`. D supplies complete recovery vectors and
failed-run reporting. C's Android provider batch `0b012c3` remains under review:
cold catalog initialization must not read the profile vault key before native
authentication. Windows first-time pairing diagnosis remains the CI priority.

Corrected checkpoint: complete policy at `6875b00` passes 3,251 cases without
skips; exact `efbddfa` boundary passes 649 Python plus ten rendered-App cases.
C's isolated pending-contact projection fix `0af2687` was cherry-picked as
`e7f6497` with attribution, leaving held provider ancestor `0b012c3` out. The lead
passes 31 actual native pairing/runtime checks, including two authenticated
receipts over the original carrier. Full packaged CI is next. A continues public
pairing, C fixes catalog-key/auth-result isolation and app-owned host composition,
B continues lifecycle/effect admission, and D continues independent consumers.

Wave 2 local checkpoint: `8950053` passes 420 Python and all eight rendered
boundary cases, including same-vault reopen and uncertain-send recovery. The
earlier full policy gate passed 2,630 cases at `6e97db5`. Composer storage,
migration fences, retained deferred cleanup and selected-path inspector code
are integrated. Full combined packaged qualification remains pending.

The next integrated checkpoint is `cabf71f`: standalone SDK staging (`7bc9fea`),
frozen runtime archive/material verification (`9844419`, `27f1236`), and trusted
profile lifecycle transitions (`da18ef3`). The lead's 154 combined lifecycle,
path, package-evidence and call-replay checks pass without skips. Python SDK
staging needs the pending temporary-source build correction before installed
consumer verification; the TypeScript isolated package check passed. B's retained
call-operation ticket is under review, including the incoming-call cleanup guard.
Private host bindings, key release after worker drain, pairing policy, upgrade
checks and actual cross-platform topology qualification remain active work.

Follow-up `7e7249a` is integrated at `f61d480`: temporary-source SDK builds,
private packaged inspector bindings and release of vault crypto references after
successful close. All 12 installed SDK cases pass on the combined source; the
broader run passes 70 cases with one existing Linux-only test skipped on Windows.
CI staging prerequisites are integrated at `d8d47ce` and exact-source staging
passes. Pairing handoff review and incoming-call profile/cleanup guards remain
pending before the next combined policy and packaged qualification run.

The combined policy checkpoint `538ba226` passes all 2,815 required tests without
skips and strict model/reducer typing. Call recovery and incoming profile guards
are integrated; exact UI boundary `7dd1034` passes 471 Python and eight rendered
cases. Subsequent `7b4dc3f` integrates reviewed upgrade fixtures and bounded peer
drivers; 37 focused cases pass. Concrete pairing composition, private profile
host admission, remaining mutation-key extensions and actual topology execution
remain active. Only Wave 1 has complete accepted packaged CI evidence.

Interim CI `42665862417` at `dcac85e` passed the independently reconstructed
2,871-case policy gate, but exposed Windows archive verification, Android test
dependency and stale frontend history assertion failures. B owns the narrow
`service/tests/test_frontend_layout.py` correction; D coordinates the Android
instrumentation repair with C's Gradle ownership. Archive repairs and B's pure
reaction/invitation hooks are integrated at `67ff95b` (225 focused passes, no
skips). A's runtime profile host remains under review for persisted-selection
versus active-vault authority. No new packaged acceptance is claimed.

Runtime host `08e29df` plus persisted-selection fence `fc7e5d9` are integrated
at `8ef8dd5`; source-bound SDK staging and 239 runtime/installed-consumer/upgrade
cases pass without skips. Selected-first compatibility `540d959` is integrated
at `d8869d0`, with four actual older-SDK two-slot cases passing. B now owns
src-only profile lifecycle facade/UI work coordinated with C's platform credential
bridge. A retains `call_manager.py` for protected unknown-call recovery after the
group mutation batch; C owns any required `service.py` glue. Caller operation
keys, consent and unresolved cleanup must survive these boundaries.

Combined `1e288ec` passes 3,108 required policy cases, zero skips, after D's
runtime-host vector correction. D's topology workflow/controller infrastructure
is integrated but held from acceptance until C's trusted supervisor pairing
entry replaces manual handshake orchestration and both platform initiator roles
are exercised. C now exclusively owns `core_api/qualification_host.py` and new
`test_native_pairing_host_port.py` for this narrow private route; ordinary public
SDK/native command authority is unchanged. C also corrects mobile shutdown
acknowledgment when a retiring service still holds its vault and removes the
Windows long-lived initialization-key reference. B's bounded UI lifetime barrier
must keep such pending shutdown outcomes uncertain, with a retry action.

The next checkpoint `ec967947` includes the reviewed private supervisor pairing
entry and truthful mobile retirement acknowledgment (76 lead checks pass),
unwired mobile profile host foundation (14 lead checks pass), and B's bounded
UI lifetime guards (700 frontend tests and the recorded worker boundary pass).
C continues actual platform provider/authentication wiring; B consumes that
contract when available. D migrates the topology controller to the private
supervisor entry and declares quick/full qualification selection. A continues
atomic optional group keys, then protected call-operation recovery. No new
packaged run or broader milestone acceptance is implied.

The complete policy checkpoint `a3a98ce` passes 3,178 tests, zero skips. Follow-up
`d4091fd` passes the exact 640-Python/eight-rendered-App boundary and 63 focused
mobile/group cases. It includes optional keyed group acceptance, supervisor
topology control, source-bound quick/full workloads, actual mobile Core routing
and group/workspace UI admission fences. The next full native CI checkpoint is
ready for dispatch; platform authentication remains pending and is not inferred
from OS boundary doubles.

The reviewed SC21 handoff is in `tests/core-ui-boundary/public-consumer-plan.md`.
A implements public pairing begin/query/cancel after protected call recovery;
begin and cancel both require caller keys. C owns new ordinary app-owned host
bootstrap/composition and Android runtime-host packaging, plus the necessary
`__main__.py` route. A retains `core_api/sidecar_host.py` and `pipe_endpoint.py`.
Existing Python/TypeScript consumer examples remain A-owned; D creates separate
independent consumer directories and their build/evidence scripts. The private
qualifier and seeded cross-UID fixtures cannot qualify SC21. B continues the
remaining asynchronous admission repairs while C completes the real native
credential facade. These are authorized implementation handoffs.

## Active Wave 2 handoff

B's `29d8159` is integrated into the shared `a3b6ebc` qualification
source. B removed only three unused internal renderer wrappers and their obsolete
mocks; active native/SDK/older-host compatibility is preserved. B passes 135
focused cases plus TypeScript; the lead independently passes 45 API/composer
cases. These results are separate from the platform run pinned to `733c38b`.

Plan 97 records the integrated hidden pending-profile recovery foundation. A owns
`core_api/runtime_host.py`, new private `core_api/profile_intents.py`, and their
producer tests: one sealed reservation/receipt authority, a caller/key alias in
the same transaction and existing quotas, common dispatch fencing, pure safe
observations, explicit original-intent retry and injected credential/origin
ports. C owns `native_profile_lifecycle.py` and its lifecycle tests, including
immutable exact request/completion types and pure `lookup_exact_completion`.
Completion lookup never advances effects, repairs the journal or infers success
from current catalog state. Unknown work cannot be overtaken or withdrawn.

The private capability stays unavailable without the complete trusted native
binding. Actual Rust/Kotlin/mobile attachment wiring is a later assignment:
dispatch must share the same atomic authority revoked by native page-load
Started; an asynchronously updated Python mirror is insufficient. Denial-only
credential cleanup accepts an already-revoked exact attachment. Only the newest
native cleanup and Core revocation acknowledgements can make a replacement
attachment ready. No public SDK expansion, automatic replay, host rebasing or
renderer-process-crash support is implied. B holds UI recovery changes. D's
19 independent real-Core/catalog cases pass; actual native attachment and
platform qualification remain separate. Workers hold production edits while
full CI runs; A/D perform the bounded cold-restart compatibility audit above.

All workers merge the current lead branch before edits. Source `174728e` is the
qualified baseline; subsequent lead-only documentation commits record that
evidence without being relabeled as separately tested source.

- A retains `contracts/core-api/**`, `service/src/mesh_chat/core_api/**`,
  `vault.py`, Core tests and `test_vault.py`. A owns `sdk/**`, the new standalone
  Python client and TypeScript/Python consumer examples, and SDK upgrade fixtures.
  The public Kotlin `CoreClient`, `CoreTransport`, `CoreExchangeTransport`, their
  two JVM tests and `IMeshCoreApi.aidl` transfer from the plugin tree to A for a
  move into `sdk/kotlin`; package and AIDL identities stay compatible. The SDK
  freeze is lifted for A only. A additionally owns `check_python_distribution.py`,
  `check_typescript_distribution.mjs`, `verify_kotlin_distribution.py` and
  `check_core_sdk_upgrade.py`. D retains other qualification orchestration.
- B retains `src/**` and background preference files. Implement the agreed
  Core-persisted composer contract and recovery flow, then cohesive UI/media
  cleanup. Preserve WebView2 calls and do not add renderer retry policy.
- C takes exclusive `service.py` ownership from A (both paths checked clean).
  C owns `mobile_bridge.py`, connection composition/runtime, native onboarding
  and WebRTC service/control, `native_windows_webrtc.py`, the new private path
  evidence adapter, Android `MeshRuntimePlugin.kt`/`NativeWebRtcHost.kt`, and
  the plugin's Gradle SDK dependency wiring. C owns their focused lifecycle,
  runtime, pending-carrier and path-evidence tests. Initial commits cover trusted
  bootstrap, profile-incarnation fences, approved carrier transfer and truthful
  selected-path diagnostics. Native pairing policy and full profile lifecycle
  follow within the existing authorization; exact additional paths are recorded
  before editing. A retains Core host bindings and vault semantics.
- D retains workflows, remaining qualification/build scripts, boundary tests,
  Android instrumentation and independent consumer tests. D adds independent
  composer restart/fault/caller tests, strict packaged source/artifact checks,
  real Windows–Android topology, selected-path negative controls, impairment and
  100-iteration authenticated-receipt/cold-start evidence. C supplies diagnostics;
  A supplies public contracts and staged SDKs. Missing infrastructure is reported
  concretely rather than replaced by simulation or Linux-only transport.

The agreed composer uses public API 1.1 with unchanged existing response shapes,
three additive operations, a stable send revision and a distinct rotating Core
update key. State and matching-draft enqueue commit in the encrypted vault.
Queries stay read-only; replay uses current authority and preserves newer text.
First use atomically raises the vault format floor to prevent older hosts from
bypassing migration fences. SDK 0.3 staging is experimental and unpublished;
baseline Python 0.2 is the actual service-carried client, not an invented older
standalone wheel. Full defaults/legacy-loop retirement remain gated on their
replacement's packaged/emulator qualification. No publication or physical-device
claim is authorized by this handoff.

C's additional C2 paths are assigned exclusively: connection `model.py`,
`reducer.py`, `ports.py`, `commands.py`, new `adapters/pairing.py` and
`test_pairing_runtime.py`; new `native_profile_lifecycle.py` and
`test_profile_runtime_lifecycle.py`. Existing C service/mobile/Android lifecycle
ownership continues, including the plugin's standalone `settings.gradle` wiring.
A retains Core host lifecycle/inspector bindings and vault semantics. Strict
model/reducer typechecking and qualification before default promotion remain
required. A separately audits mutations outside the prior 92 keyed-action
inventory and records domain-hook ownership needs before edits.

C additionally owns `connection/supervisor.py` for atomic pairing handoff and
stale-completion retirement fences. A additionally owns `group_service.py` and
new `test_group_operation_idempotency.py` for additive explicit-key mutation
support, preserving declared legacy request behavior. D independently verifies
the new capability and replay/authority contract after A supplies it.

B additionally owns `reactions.py`, `contact_invitations.py`, and new
`test_reaction_keyed_preparation.py` / `test_contact_invitation_keyed_preparation.py`
for prepared domain writes and post-commit effects coordinated with A's caller
receipt transaction. A additionally owns `direct_recovery.py` for import/export
resource intents. C retains `service.py`, reconnect and participant glue; current
pairing work stays first. No owner silently changes another owner's files.

## Historical Wave 1 ownership and gate

| Owner | Exclusive changes | Required outcome |
| --- | --- | --- |
| A | `contracts/core-api/`, `service/src/mesh_chat/core_api/`, existing Core contract/parser/session tests | Serialized requests agree with production parsing and session validation; mutation idempotency is durable and caller-scoped. |
| B | Application `src/` and its tests | Core parameter names survive serialization; ambiguous sends reuse their key; accepted sends cannot be restored after a refresh error; media remains in WebView2. |
| C | `src-tauri/src/`, runtime-plugin Rust, Android runtime/Binder implementation and host tests | Windows and Android expose working snapshot, profile, request and send routes with caller authority and correlated typed errors. Public Kotlin SDK files remain frozen. |
| D | Workflows, qualification scripts, new cross-boundary tests | Tests exercise serialized frontend/host traffic through the production parser/session or actual host, and required evidence cannot silently skip. |
| Lead | Roadmap, acceptance, ledger and this coordination file | Review and merge A, C, B, D in order; run combined checks; inspect exact-source CI artifacts. |

No owner edits another owner's file. Cross-owner requirements belong in worker
reports until assigned. Worktrees and their build caches stay separate. D owns
coordination of emulator/packaged verification resources; no concurrent local
emulator reservation is granted during bootstrap.

Wave 1 passes only when actual Windows and Android app paths load application
and workspace state and execute representative messaging, settings and call
control through Core. Native Windows transport replaces messaging only. WebView2
audio/video remains supported. Schema validation, simulated service ports and
legacy command mocks cannot alone satisfy this gate.

## Cross-owner interface requirements

1. A/B/D: `conversation` and `thread_root` remain Core contract fields. Conversion
   to legacy domain IDs occurs inside the protected adapter, never before a typed
   Core request reaches the production parser.
2. A/B/C/D: request idempotency keys must survive the host route unchanged. The
   parser and session must agree on accepted keys for all mutation operations.
3. B/D: distinguish uncertain enqueue outcomes from confirmed acceptance and
   subsequent snapshot failure. Retry the former with the same key and payload;
   the latter must not reinsert text into the composer or send again.
4. C/D: test the mobile entry points rather than passing Android via desktop-only
   mocks. Preserve Binder caller identity across executor dispatch.
5. D: full qualification must be explicitly dispatched for the integration head.
   The baseline workflow push filter does not include this feature branch;
   a successful push by itself does not establish a CI run.

## Remaining specification ownership inventory

Wave 2 assignments below are active after Wave 1 integration and qualification.
The handoff above records first-batch paths and the Kotlin ownership transfer.
Additional paths are assigned before edits; each worker keeps its exclusive scope.

| Owner | Remaining acceptance obligations |
| --- | --- |
| A | SDKs and independent distribution-only consumers; install/upgrade and preserved data; API/package compatibility and rejection; event replay/gap recovery; runtime ownership and multi-client consumer semantics (INV21–26, SC21–26, sections 6.5–6.7). |
| B | Remove UI compatibility/policy paths after qualified replacement; media teardown and pairing closure coexistence; supported UI through the same facade (INV17/22, SC17, section 3.3). |
| C | Supervisor promotion, native contact/workspace pairing, profile create/select/unlock/lock host lifecycle, exclusive runtime ownership, legacy policy retirement, all-mode foreground/background parity and exact-resource cleanup (INV01–19/22, SC01–19/26). |
| D | Packaged Windows/Android and WebView interoperability; selected ICE path with negative control; forced relay, UDP denial and rebinding; 150 ms RTT fault budgets; saturation and 100-iteration receipt/cold-start matrix; baseline timing and wire fixtures; mandatory exact-source CI evidence (SC01–26, INV20). |
| Lead | Reconcile all 26 invariants, all 26 scenarios and section 13 boundaries; document storage/export/uninstall, support windows and redistribution obligations with implementation owners; keep publication and physical evidence separate. |

## Evidence rules

Each integration batch records base/result SHA, changed files, command and test
counts, dependencies and limits. Historical manifests qualify only their named
source/artifacts. Unit/local, native component, emulator, packaged and workflow
evidence are distinct. No physical qualification is available. No release, tag,
publication, force push or main merge is authorized.

## Historical Wave 1 follow-up assignments and checkpoint

At `8a902a05b580408a4f1853904f8e6ade01f41d95`, the private native host port
separation and Android enqueue `kind: text` fix are integrated. Ordinary public
owner grants cannot advertise or invoke the native command port. The lead ran
211 contract, host and real Windows pipe cases with no failures or skips; strict
model/reducer typechecking also passed.

The complete required policy inventory at `d4945d0` executed 2,240 cases:
2,239 passed and one failed, with zero skips. The isolated contact worker test
reached recipient readiness but received no inbound invitation. A focused rerun
at `8a902a0` reproduced that failure (one pass, one failure). This is not passing
qualification evidence.

C now exclusively owns `service/src/mesh_chat/contact_bootstrap.py`,
`isolated_bootstrap.py`, `direct_bootstrap_process.py`,
`direct_bootstrap_worker.py` in that same directory, and
`service/tests/connection/test_contact_bootstrap.py` for this gate repair.
A owns the production `core_api/pipe_client.py` buffer correction exposed by D's
new real-transport tests. D owns
`service/tests/connection/test_matrix_evidence.py` and the reserved
`TypedCoreBridgeBoundaryTest.kt` instrumentation file. These assignments do not
activate Wave 2 or transfer the public SDK files.

For durable keyed mutations, A additionally owns `service.py`, `vault.py`,
`call_manager.py`, `workspace_service.py`, and `remote_service.py` under
`service/src/mesh_chat/`, plus `service/tests/test_vault.py`. Prefer prepared
domain writes and the existing `VaultStore.commit_operation` boundary. External
network/resource effects need committed intent and recovery; a vault transaction
cannot make those effects atomic. C's later lifecycle ownership excludes these
files until explicitly transferred.

Subsequent transfer: C exclusively owns `service/src/mesh_chat/remote_service.py`
and the new `service/tests/connection/test_remote_profile_idempotency.py` for
remote-profile keyed durability. A's worktree was verified clean before transfer.
A retains the Core adapter in `service_workspace_admin.py`, and wires the optional
domain `operation_id` argument supplied by C. Persisted runtime intent must use
current consent/settings during reconciliation; replay cannot restore revoked
approval or return cached connectivity as current state.

B resumes bounded Wave 1 onboarding work: stable profile-create keys and retry
handling. A supplies the trusted private bootstrap on an already-started empty
service, without widening ordinary public-owner grants. B's Core-owned composer
revision/CAS and atomic draft-bound enqueue proposal is the accepted Wave 2
design direction; implementation remains gated on Wave 1.

Further Wave 1 transfer: C exclusively owns
`service/src/mesh_chat/reconnect_service.py` and the new
`service/tests/connection/test_reconnect_prepared_mutations.py`, alongside its
remote-profile files. C prepares remote approval and reconnect device/profile
writes without storage or network effects. A retains `workspace_service.py`
and `service.py`, composes parent records and operation receipts into the atomic
commit, then reconciles current consent. D independently audits supported keyed
mutations and required host inventories. General Wave 2 remains inactive.

A additionally owns `service/src/mesh_chat/background_availability.py` for
keyed runtime preference changes and post-commit reconciliation. D's independent
signed-membership-removal replay regressions remain in its reserved
`test_ui_core_boundary*.py` files; A repairs the production authority ordering.

To parallelize the remaining bounded Wave 1 work, the lead verified A's
`background_availability.py` path clean, then transferred it exclusively to B,
with the new `service/tests/connection/test_background_preference_idempotency.py`.
A retains the Core runtime adapter. C additionally owns
`service/src/mesh_chat/participant_service.py` and the new
`service/tests/connection/test_participant_keyed_preparation.py` for route resource
reservation and prepared access replacement; A retains route parent operations
in `service.py`. These assignments do not activate general Wave 2.

Consent administration requires `approve` in addition to the existing `send`
grant for remote-profile create, approve/remove propagation and remove; workspace
access-recommendation apply/apply-by-ID; and workspace reconnect consent. Query,
test, retry and ordinary send actions retain their separate requirements. A owns
contract metadata and enforcement; D owns independent consumer denial, owner
success and revoked-grant replay checks, plus aggregate boundary evidence wiring.
