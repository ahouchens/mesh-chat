# Direct connectivity Phase 2 evidence

Status: **open**. No production or physical-device completion is claimed.

## Native host integration checkpoint

The app now links the transport crate and explicitly declares Rust 1.88 alongside
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
Host compilation and exact Windows/Android package results are pending CI; linking
source does not qualify the public setup flow or the remaining bootstrap adapter.

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

This private lease is not yet wired into the production bootstrap carrier. The
admission handoff must deliver the admission control without allowing workspace
traffic on pending credentials; simply cancelling the owner carrier at approval
would strand the joiner. The existing controlled harness does not qualify that
production handoff.

## Bounded native candidate dialing

The native dialing operation consumes one endpoint, validates a maximum of eight
distinct numeric tuples, skips expired candidates, and attempts them sequentially
within a maximum 60-second monotonic window and each candidate's validity. Quinn
supplies standard QUIC handshakes with its existing five-second handshake timeout.
Cancellation, loss of the authority channel, exhaustion and caller abandonment
drop the endpoint. Success returns the same socket owner and authenticated path.
The controlled packet bridge uses this operation for either deterministic client
role. No address discovery, custom probes, mapping or TCP policy was added.

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

## Remaining implementation and qualification

- Native host/plugin embedding, explicit toolchain adoption and package builds.
- Private production native/service IPC and isolated bootstrap contexts.
- Safe owner admission handoff and fresh admitted credentials.
- Public versioned Offer/Answer/Ready import/export and setup states, including
  authoring a reply when phone hosting fails.
- Public IPv4/IPv6 candidate collection and UDP mappings tied to native ownership.
- Coordinated traversal, explicit delayed-email recovery and direct TCP fallback.
- Supported Windows/Android topology execution and physical same-socket evidence.

Phase 1 evidence remains tied to its separately recorded implementation commit.
