# Direct connectivity Phase 2 evidence

Status: **open**. No production or physical-device completion is claimed.

## Owner pending authorization

The protected service can lease its exact persisted, selected Offer/Answer chain,
including Ready when present. Registration revalidates the signed Answer and live
invitation. Polling checks current local authority, the saved chain and absence of
the selected identity from the workspace manifest. Admission, revocation, identity
loss, changed exchange, suspension, shutdown and monotonic expiry retire the lease.
An identical import cannot allocate a second lease for the invitation.

Source validation: 643 non-integration tests passed, 7 environment-dependent skips.
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

Native builds and execution are restricted to GitHub Actions. Exact commit/run
results will be recorded after qualification; source formatting alone is not
compilation evidence.

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
