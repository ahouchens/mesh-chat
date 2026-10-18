# Traversal implementation review

Reviewed application: `0bf9623a9d4c01042793f63d3ffb1fd984443308`, version
0.2.58 / Android 2058. Review date: 2026-10-18.

This is an author-side source review, not independent protocol approval. F2 of
the [specification](DIRECT_CONNECTIVITY_TRAVERSAL_SPEC.md) requires independent
review of the smaller QUIC-only protocol. That gate remains open. No physical
reachability, carrier compatibility, or release approval follows from this record.

## Boundaries checked

| Boundary | Implementation and evidence |
| --- | --- |
| Preview versus connection | Signed-control preview performs validation without dialing or granting membership. Preparation and connection are separate public commands. Private native controls cannot be supplied through public setup payloads. |
| Candidate provenance | `direct_candidates.py` exports only inspected native-owned sockets, matching UDP mappings, and permitted public addresses. Mapping lifetime clips the preparation deadline. Additional route failure preserves an already usable route. There is no public observer or address-guessing service. |
| Initial authentication | `traversal.rs` and `paths.rs` use mutually pinned QUIC checks. Deterministic client-outgoing/server-incoming selection keeps auxiliary connections out of application delivery. Losing local endpoints close. The retained socket/key owns the advertised tuple. |
| Resource limits | Four local sockets per initial setup, eight profile sockets, eight remote candidates, shared incoming/check bounds, a global start pacer, bounded queues and monotonic deadlines constrain work. Handshake-start limits are not packet-rate limits; Quinn owns retransmission. Adversarial packet-rate qualification remains open. |
| Recovery authority | `recovery.rs` establishes TLS key possession before exchanging encrypted capsules. `direct_recovery.py` then validates current workspace authority, the actual TLS certificate and native authorization token before application delivery. Old invitation authority cannot authorize an admitted recovery. |
| Cancellation and revocation | `direct_runtime.py` checks registration epochs after authority callbacks. Packet pumps retain their resource reservation until their threads exit. Recovery checks authority before pending/full-worker shortcuts. Pending and saturated scheduler regressions cover the previously observed revocation leak. |
| Handoff | `direct_handoff.py` waits for the admitted peer's signed RNS announcement before retiring bootstrap. The isolated bootstrap carrier permits only join, receipt, manifest-root and direct-binding controls; channel discovery uses the admitted path. The source-admission timeout therefore is not evidence of channel controls being discarded from the bootstrap queue. |
| UX evidence | Prepared mappings are unverified. Readiness uses the native state accessor without draining packet queues, invalidates stale route/socket ownership and checks before sharing. A saved request, authenticated transport, signed receipt and membership approval remain separate states. |
| Diagnostics | `connection_diagnostics.py` allowlists enums, counts and timestamps on capture and export. Protected history is capped at 200 events/seven days, with bounded export. It does not export raw exception text, addresses, invitations, keys or user messages. Clear-history preserves application state. |

## Verification and unresolved observations

The exact application [full native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39160399603)
passed Windows and Linux setup/admission and durable recovery, Linux network/NAT
audits, and Android native compilation. The corresponding [build](https://github.com/ahouchens/mesh-chat/actions/runs/39160414911)
passed verification and both platform packages. Artifact integrity and the exact
installation pair are recorded in the [device checklist](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md).

A focused author-review rerun passed **102 source tests** across runtime leases,
packet pumps, recovery authorization, setup, readiness and diagnostics. Native
execution and frontend/package validation remain in GitHub Actions as required
by `TESTING.md`.

Two preceding Windows failures are retained as open reliability observations:
channel discovery after admission, and address-loss recovery at `native_wait`.
The latter has paired controlled-fixture port evidence added to failures. The
[Windows repetition workflow](https://github.com/ahouchens/mesh-chat/actions/runs/39163212934)
uses five fresh processes per scenario and unchanged assertions. A later passing
run is not a root-cause explanation for an earlier intermittent failure.

## Required reviewer and device follow-up

An independent reviewer should examine simultaneous check selection, cancellation
at nomination, stale recovery generations and late handshakes, authority loss
during replacement, and unauthenticated resource consumption. Record the reviewed
commit and findings before approving the protocol gate.

Physical acceptance must use both matching builds and the carrier/home-router
topology. Both-empty candidate sets must produce the explicit unsupported result;
manual document exchange cannot discover two unknown public tuples. Check copying
and sharing, background/return, process death, network changes, large text and
diagnostic persistence on actual devices. Do not replace that evidence with
loopback, synthetic candidates or a same-Wi-Fi result.

## Diagnostic follow-up

Version 0.2.59 adds the four blocking readiness states to retained last-failure
capture. Regression cases cover later success, history rollover and the valid
one-sided preparation state. All ten diagnostic tests pass. This changes no
transport or authorization behavior; matching package qualification is pending.
