# Direct connectivity Phase 2 evidence

Status: **open**. No production or physical-device completion is claimed.

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

The production-controller source pipeline passes three cases: cancellation,
suspension and revocation after admission. Each uses real protected services and
isolated RNS/LXMF processes, verifies signed join acknowledgment, approval, fresh
admitted credentials, channel bootstrap, bidirectional messages and endpoint
receipts, then checks native-handle/interface retirement. Its native I/O is a
bounded in-memory pipe simulation; this is not QUIC or physical reachability
evidence. The complete local non-integration checkpoint passed 750 tests with
7 environment-dependent skips; subsequent focused validation passed 79 tests.
Current renderer, native-role and combined package changes await exact-commit CI.

- Exact-commit renderer/native/Windows/Android package qualification of the integrated flow.
- Qualification of public IPv4/IPv6 and UDP mappings tied to native ownership.
- Physical delayed-email recovery, unhosted replies and existing TCP fallback.
- Supported Windows/Android topology execution and physical same-socket evidence.

Phase 1 evidence remains tied to its separately recorded implementation commit.
