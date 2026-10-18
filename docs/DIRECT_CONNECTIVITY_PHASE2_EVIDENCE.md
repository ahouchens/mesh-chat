# Direct connectivity Phase 2 evidence

Status: **open**. No production or physical-device completion is claimed.

## Current qualification gates

The production email setup, private native IPC, isolated bootstrap, admitted
handoff and renderer flow are implemented. Latest implementation:
`200614ad31ec1ce16cd395701b7284bda3d67879`.
It includes protected desktop bootstrap storage and IPv6 Ready socket selection
for an unhosted owner. No release has
been published or device package installed by this work.

Exact-commit verification in
[run 39080404932](https://github.com/ahouchens/mesh-chat/actions/runs/39080404932)
passes 777 service tests (35 environment/native-only skips), 184 frontend tests
and the repository validation checks. This count includes the six source pipeline
cases. Both Windows desktop and signed Android ARM64 package jobs passed in that
run; release publication was skipped. Compilation is separate from physical execution.

| Phase 2 exit gate | Evidence | Remaining requirement |
| --- | --- | --- |
| Windows/Android connect in supported topologies | Shipping dispatcher + real QUIC pipeline passes on Windows/Linux at `200614a`; exact Windows/Android packages pass | Physical Windows↔Android run |
| Delayed email/stale candidates recover explicitly | Codec expiry, lost-socket/restart, uncached exports, UI refresh and native delayed-peer tests | Physical expired-document and suspended/restarted-phone exchange |
| Same-socket ownership | Native prepare/inspect/arm/activate; mapping tuple substitution tests; actual shipping-host pipeline preserves port/certificate | Successful guarded path on physical mapped/public network |
| Failed phone hosting does not prevent a reply | Empty-candidate signed round trip; six source pipeline cases across both-hosted/unhosted joiners; deterministic client role | Unhosted Android reply and successful connection to reachable Windows |
| IPv4/IPv6/mapping and existing TCP fallback | Protocol mapping tests, family/expiry rejection, existing-route queue and legacy topology coverage | Record available physical topology results and TCP fallback |

The tester confirmed an Android device and second network are available. Actual
execution remains pending. Follow the
[device checklist](DIRECT_CONNECTIVITY_PHASE2_DEVICE_TEST.md); record unavailable
topologies honestly and keep addresses/documents out of evidence summaries.

## Exact packages for device qualification

Built from `200614ad31ec1ce16cd395701b7284bda3d67879`, version 0.2.47:

- [Windows artifact 12118444662](https://github.com/ahouchens/mesh-chat/actions/runs/39080404932/artifacts/12118444662)
- [Android artifact 12119295311](https://github.com/ahouchens/mesh-chat/actions/runs/39080404932/artifacts/12119295311)

SHA-256 values below were independently computed from package streams inside the
CI archives without installing or executing them:

| File | SHA-256 |
| --- | --- |
| `Mesh Chat_0.2.47_x64-setup.exe` | `b35b13adcbc9d4247ce8e99f42fe9998b4d2c084b4aab28d2540722ffeb4a1e0` |
| `Mesh Chat_0.2.47_x64_en-US.msi` | `84b5a2796e3e6dceb280697c4def71ae77988f2e7dcc1ac53b35a88ffd213fb0` |
| `mesh-chat.exe` | `8e67a96f112de755e67cdc61ce96409961ee10e7bd11c05de8c4b8678905ec3d` |
| `mesh-chat-service.exe` | `9e7d7e29dc9259aa39ebb4ae06b166c48db7a991cab2ee546a2ff0e9f962b33a` |
| `mesh-chat-0.2.47-android-arm64-release.apk` | `7e508603fc043c01243fce104eeb99793b80b8c381231d41ff4aac6c2f613420` |

## Final implementation CI qualification

At `200614ad31ec1ce16cd395701b7284bda3d67879`,
[run 39080401782](https://github.com/ahouchens/mesh-chat/actions/runs/39080401782)
qualifies Windows/Linux and Android ARM64 compilation. Each desktop platform runs
205 service-boundary tests, 14 workspace-authority tests, 32 document/setup tests,
47 isolated-bootstrap/path/control tests, six source pipeline cases, 20 native
unit tests, one cross-language binding test, one shipping-dispatcher unit test,
25 legacy native topology cases and six production pipeline cases over real QUIC.
Both-hosted and unhosted-joiner cases cover cancellation, suspension and revocation.

The final Linux production pipeline observes zero external addresses, 1158
loopback address observations, 48 wildcard binds and 930 network sends in
[artifact 12119250318](https://github.com/ahouchens/mesh-chat/actions/runs/39080401782/artifacts/12119250318).
The separate legacy topology also observes zero external addresses, with 1272
loopback observations and 1048 sends in
[artifact 12119080991](https://github.com/ahouchens/mesh-chat/actions/runs/39080401782/artifacts/12119080991).
These reports cover controlled processes and descendants, not a physical router.

Earlier verification failures were an obsolete Android size-limit assertion and
an unsupported frontend matcher; both are corrected. The `76ae138` Windows
legacy topology run also timed out waiting five seconds for a rejected activation
response in its service-crash scenario; final exact-commit qualification passes
that scenario. No timeout was relaxed in that test. Superseded package runs were
cancelled to build the protected-storage/socket-family corrections.

## Earlier shipping-dispatcher integration checkpoint

At `ed6030dfa5cbe6179e586d95b8d08fe9bde35cb1`,
[run 39079842232](https://github.com/ahouchens/mesh-chat/actions/runs/39079842232)
passed Windows/Linux native qualification and Android ARM64 compilation. The
CI-only inherited-pipe executable imports the exact shipping `direct_native.rs`.
Three production pipeline cases exercise public commands, real QUIC/native
ownership, isolated RNS/LXMF, signed join acknowledgment, owner approval, fresh
admitted credentials, channel bootstrap, bidirectional messages/receipts, and
cancel/suspend/revocation cleanup. Linux observed zero external addresses, 587
loopback address observations and 473 network sends in
[artifact 12118711768](https://github.com/ahouchens/mesh-chat/actions/runs/39079842232/artifacts/12118711768).
The test adapter translates a synthetic public candidate to loopback, preserving
native port/certificate; it does not establish public reachability.

Later source qualification passes all six lifecycle/topology cases with one
admitted adapter deliberately delayed after transport authentication. At
`a8c1ae2`, 769 non-integration tests pass with 7 environment-dependent skips;
the subsequent IPv6 correction passes all 18 setup tests. Frontend verification
passed at `76ae138` in
[run 39080052749](https://github.com/ahouchens/mesh-chat/actions/runs/39080052749);
its superseded package builds were cancelled in favor of the storage-fixed build.

## Native host integration checkpoint

The app now links the transport crate and explicitly declares Rust 1.90 alongside
the mobile plugin. An eight-session native owner retains exact socket/key handles,
enforces preparation expiry and remaining attempt windows, and exposes only bounded
private operations. Each running direction has a 32-packet application queue.
Desktop frames have an independent service reader; Android uses a separate native
exchange and worker, not renderer event polling. Private replies are correlated,
bounded, fail closed on loss/timeout, and never forwarded to renderer events.
Shutdown and suspension retire native work. Late replies cannot revive it.

New tests cover correlation/reordering, late and duplicate replies, malformed and
oversized frames, capacity, EOF, blocked writes, timeout, suspension, lock-free
mobile response delivery, native expiry/cancellation and two native owned endpoints.
Windows and Android app package builds passed at
`9a75802958bba958213ade6483dff27ca40e3927` in
[run 39075783663](https://github.com/ahouchens/mesh-chat/actions/runs/39075783663).
This qualifies compilation, not physical operation or the remaining bootstrap adapter.
The first package run at `ab01342` (run 39075386841) passed verification but rejected
Rust 1.88: locked Tauri packages require 1.90 and UUID requires 1.89. App/plugin
builds now pin 1.90; the transport-only workflow retains its 1.88 compatibility check.

## Owner pending authorization

The protected service can lease its exact persisted, selected Offer/Answer chain,
including Ready when present. Registration revalidates the signed Answer and live
invitation. Polling checks current local authority, the saved chain and absence of
the selected identity from the workspace manifest. Admission, revocation, identity
loss, changed exchange, suspension, shutdown and monotonic expiry retire the lease.
An identical import cannot allocate a second lease for the invitation.

Source validation: 643 non-integration tests passed, 7 environment-dependent skips.
The source topology/controller suite passed 11 tests, with 14 native-only skips.
The five owner Ready lifecycle cases exercise real signed documents and admission,
restart, failed persistence, certificate substitution, duplicate leases and refresh.

The production bootstrap uses a separate narrow authority check: admission permits
at most 30 seconds of isolated admission-root and fresh-binding controls, never
ordinary workspace traffic. Both active devices and the exact saved chain are
rechecked. A signed announce on the fresh admitted path confirms that the remote
adapter is installed before the bootstrap carrier retires. The original strict
pending lease still retires at admission and remains covered by its prior tests.

## Bounded native candidate dialing

The native dialing operation consumes one endpoint, validates a maximum of eight
distinct numeric tuples, skips expired candidates, and attempts them sequentially
within a maximum 60-second monotonic window and each candidate's validity. Quinn
supplies standard QUIC handshakes with its existing five-second handshake timeout.
Cancellation, loss of the authority channel, exhaustion and caller abandonment
drop the endpoint. Success returns the same socket owner and authenticated path.
The later `3cf725f` increment keeps both roles available for delayed activation,
with at most 64 sequential attempts and paced retries inside that window. Its
[native CI run 39077564479](https://github.com/ahouchens/mesh-chat/actions/runs/39077564479)
passed. No address discovery or custom probes were added.

Native builds and execution are restricted to GitHub Actions. Qualification passed
for `ac9d9810d066bfb80618e05da2cb98d88f84f36d` in
[run 39073862971](https://github.com/ahouchens/mesh-chat/actions/runs/39073862971).
Windows and Linux each passed 158 service-boundary tests, 14 workspace/pending
authority tests, 16 native unit tests, one cross-language binding test and all
25 native topology/controller cases. Android ARM64 compilation passed.
Linux syscall observation of the full controlled topology and descendants recorded
zero external addresses, 1276 loopback observations and 1052 network sends.
The endpoint-free report is retained in
[artifact 12115859003](https://github.com/ahouchens/mesh-chat/actions/runs/39073862971/artifacts/12115859003).
These are isolated crate builds, not host app or plugin package builds, physical
Windows/Android execution or Internet traversal measurements.

## Production setup and remaining qualification

An isolated bootstrap engine now refuses an existing RNS interpreter, starts only
one non-routing packet adapter, and permits only join/receipt/admission-root and
fresh admitted-binding LXMF controls. A bounded desktop inherited-pipe supervisor and an Android non-exported
secondary-process service keep its RNS globals separate from normal app routes.
Sixteen source tests pass, including two real RNS/LXMF processes, pre-activation
packet rejection, ordinary/channel payload rejection, process failure and bounded
mobile serialization. The process boundary packages passed on Windows and Android
at `acdd868ca21fc5cc7aabc967d94674b8b53b7fb2` in
[run 39077271626](https://github.com/ahouchens/mesh-chat/actions/runs/39077271626).
The setup controller now attaches these processes through private native IPC.

The version-2 `mesh-direct:` document codec carries the original signed workspace
invitation and independently signed Offer/Answer/Ready chain. Parsing checks the
entire chain, canonical encoding, exact certificates, limits and expiry before any
membership change. The protected setup controller persists each document before
export, retains the Answer socket through Ready, replaces the owner's Offer socket,
allows an empty-candidate reply, and reports refresh after suspension/socket loss.
Explicit renderer commands and an email/file setup panel now expose preparation,
review, sharing, connection, cancellation and refresh states. Public responses
contain opaque document text and setup summaries, never native handles or packet
controls. Every setup command bypasses durable command-response caching so restart
cannot replay an export with dead socket ownership. An unhosted side is the client
when only its peer has a candidate; both-hosted peers retain identity ordering.
Focused document/setup/candidate validation passes 35 tests, including persistence
failures, certificate/chain substitution, delayed mail, concurrent capacity,
retirement during mapping and cleanup failure. Mapping lifetime also bounds the
native cleanup timer.

Candidate collection now prepares the native socket first, maps its exact source
interface and port with UDP, and re-inspects ownership after router work and before
document signing. Global IPv4/IPv6 and same-interface IPv6 pinholes are supported.
Cleanup covers mapping substitution, changed native tuples, expiry and failure.
No global candidate is fabricated when local mapping fails. Version-2 chains permit
empty candidate replies while preserving version-1 behavior and rejecting mixed
versions. The focused candidate/binding/Offer/exchange suite passes 118 tests.
These are source-level checks; router/device qualification remains.

The initial production-controller source pipeline passed three cases: cancellation,
suspension and revocation after admission. Each used real protected services and
isolated RNS/LXMF processes, verifies signed join acknowledgment, approval, fresh
admitted credentials, channel bootstrap, bidirectional messages and endpoint
receipts, then checks native-handle/interface retirement. Its native I/O is a
bounded in-memory pipe simulation; this is not QUIC or physical reachability
evidence. The complete local non-integration checkpoint passed 750 tests with
7 environment-dependent skips; subsequent focused validation passed 79 tests.
The later six-case and exact-commit native/package qualification is recorded above.

- Qualification of public IPv4/IPv6 and UDP mappings tied to native ownership.
- Physical delayed-email recovery, unhosted replies and existing TCP fallback.
- Supported Windows/Android topology execution and physical same-socket evidence.

Phase 1 evidence remains tied to its separately recorded implementation commit.
