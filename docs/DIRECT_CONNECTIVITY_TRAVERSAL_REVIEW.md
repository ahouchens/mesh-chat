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
passed five fresh processes per scenario with unchanged assertions. All ten
JUnit records were checked and had no failures or errors. A later passing
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

## Recovery follow-up: 0.2.61

The proposed unequal role-period change was rejected and removed because its
regression passed against the previous code. The actual follow-up retries TLS
connections that close or fail before completing the encrypted capsule exchange.
It keeps the same overall monotonic attempt deadline and iteration budget, closes
the incomplete connection, and exposes neither service evidence nor application
traffic from it. Once a capsule is received, existing certificate binding and
mutual service authorization remain mandatory. Invalid authority is not retried
as successful authentication.

The new native regression closes a first TLS connection before capsule exchange,
then requires the fresh peer certificate, rejection of early data, mutual service
approval and successful packet delivery. The old code fails and the fix passes
on both Windows and Linux in run `39165009599`, commit
`ed25af6fcb8f13d423ffd2d71478d7037b11746e`. Existing delayed-listener red/green
coverage also passes. Full pipeline reliability, independent protocol review and
physical acceptance remain separate gates.

## Pause ownership follow-up: 0.2.62

A second concrete race was reproduced in a source test: pause could return while
a native allocation was hidden inside candidate discovery. A private pending
ownership wrapper now publishes each native handle under the same lock that
retires the attempt token. Native allocation and close are serialized with
cancellation; router discovery remains outside that lock. The completed
preparation replaces the pending wrapper only while the attempt token is current.
A retired worker cannot allocate again or remove a newer worker's ownership.
Export treats the pending wrapper as preparing, never as a shareable document.

The regression fails before the fix with a remaining native handle and passes
afterward while holding the public service dispatch lock and leaving discovery
blocked. All 75 focused recovery/candidate/runtime/packet tests passed. Full native
qualification and matching packages remain required.
