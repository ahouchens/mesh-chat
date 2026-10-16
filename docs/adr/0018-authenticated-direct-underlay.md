# ADR 0018: Authenticated direct underlay below Reticulum

Status: accepted for feasibility work; production activation is gated.
Date: 2026-10-16.

## Decision

Permit a native QUIC underlay to carry unchanged Reticulum packets. This
supersedes only ADR 0001's prohibition on an additional handshake **below RNS**.
Reticulum remains the routing/Link authority, LXMF remains the message protocol,
and the protected Python service remains the sole owner of identity, signatures,
authorization, durable state, and workspace admission. No new message cipher,
relay, discovery service, or public observer is authorized by this decision.

Rust owns ephemeral transport keys, native sockets, authenticated path checks,
bounded queues, and platform lifecycle handling. Python signs the binding of a
transport public key to its RNS identity without exporting the private identity
or vault key. React receives redacted evidence and available actions only.

The private packet adapter is a data interface. It is not a localhost control
service and does not relax ADR 0003. Never expose packet injection, canonical
bindings, transport keys, endpoint tuples, or socket operations to the renderer.

## Feasibility implementation

`experiments/direct-fabric` is an isolated, unpublished crate. It is deliberately
not a dependency of either native app. Its controlled-peer proof uses Quinn
0.11.12, Rustls 0.23.46 with ring, rcgen 0.13.2, and an independently committed
Cargo.lock. QUIC 0-RTT, TLS resumption, certificate compression, and application
streams are disabled. Mutual TLS plus exact leaf-certificate comparison binds
each connection to the one certificate supplied by the trusted test harness.
The cross-language integration test now asks the isolated Python binding proof
to sign and verify those exact public certificates before mutual TLS. Python
retains the RNS identities and Rust retains TLS private keys. This harness is
not the app control channel and does not establish workspace authority.

`service/src/mesh_chat/direct_binding.py` implements strict canonical binding
validation against explicitly supplied local authorization. It checks exact
scope, issuer and audience, certificate digest, ALPN, session, challenge,
bounded global numeric candidates, validity, signature, and generation conflicts.
`accept_binding` now loads the previous generation for the exact relationship
and commits acceptance while reloading authorization under the vault transaction.
Its protected caller must supply a current vault-backed authority loader; failed
validation, encryption or commit returns no acceptance. Record indexes are keyed
opaque IDs, and expired replay history is retained. This primitive does not grant
runtime activation. The service now reloads admitted workspace authority from
the current signed manifest, verifying active state and exact local/remote device
identities. The joiner also reloads pending authority from the saved signed join
and submitted invitation. It rejects missing/terminal records, expired invitations,
changed identities and mismatched authority destinations. The owner now persists
its challenge/deadline before accepting a signed binding, atomically pins one
responder and replay history, and rechecks current local authority and the active
invitation. Selection neither synthesizes a join nor admits a member. Expired
negotiations fail closed. A private explicit replacement transaction checks the old
challenge and current authority, changes only the challenge/deadline, and retains
selected-peer and replay records. Identical retries return the saved replacement;
conflicting retries and replacement of active attempts fail. Preparation retries
preserve the original challenge and deadline. Native lifecycle reconciliation must
still establish socket ownership before any future candidate advertisement. The pure initial Offer schema is now implemented in `direct_offer.py`; it has
no audience field, requires independently supplied invitation authority, and
shares canonical parsing and transport limits with direct bindings. Its generation
result is verification evidence only. Answer/Ready schemas, public import/export
integration and lifecycle reconciliation remain open. No binding
command or packet API is exposed to React. The initial unbound Offer uses a
separate pure codec; the binding verifier still requires an exact audience.

The proof owns one UDP socket throughout bind, connect, and packet transfer.
`BoundSocket` permits candidate preparation before peer authorization and is
consumed by `Peer::from_bound_socket`; it never closes/rebinds the advertised
port and exposes no socket clone or competing-reader API.
Only Quinn reads it. Native send admission serializes concurrent callers and
enforces a 128-item limit in addition to the byte budget. Quinn transmit counters
release item credits without adding delivery acknowledgments or retransmission. One DATAGRAM carries one packet; the accepted size is
1–516 bytes (RNS 1.5.5's 500-byte base MTU plus 16-byte IFAC, no application
encapsulation). A peer negotiating less is rejected. This proof does not enable
Reticulum's larger hardware MTUs. Item/byte queue limits are both tested.

Its GitHub workflow runs controlled peers on Linux and Windows and checks the
Android ARM64 target. No local native build or native test is part of this
change. A resolved dependency graph is not compilation or device evidence.

The dependency graph declares a maximum required Rust version of 1.88. The
proof workflow pins 1.88.0. The existing app still declares 1.77.2, so adopting
the proof in the app requires an explicit host/plugin toolchain update and
successful package builds. Do not quietly add this dependency to that host.

## Binding and resource contract

Canonical bindings use UTF-8 JSON with sorted keys, compact separators,
no duplicate keys, floats, non-finite numbers, or unknown fields, maximum depth
8. Verify canonical bytes before verifying the RNS signature. These are design
constraints for the remaining controls, not new accepted invitation prefixes; existing v1–v4 envelopes
and `MESHCONNECT1` retain their exact schemas.

Each binding must contain its independent integer protocol version, purpose,
scope, issuer RNS public identity and derived destination, exact audience (except
the initial offer), transport certificate/public-key digest, ALPN, random session
UUID, 32-byte challenge, monotonic generation, candidate list, issued time and
expiry. The entire unsigned canonical object is signed. TLS must prove control
of the bound key; neither the signature nor TLS grants membership. Certificates
are session-local. Restart/key rotation requires a fresh binding signed by the
same durable RNS identity and committed generation, not a new admission.

Scopes are either the exact invitation digest plus its authorization expiry,
or the exact workspace, issuer device, and audience device in the latest locally
verified manifest. Store the accepted generation and digest atomically before
network effects. Equal generation and equal digest is an idempotent replay;
equal generation with different bytes and lower generations are rejected.
An expired invitation cannot be revived by a candidate update.

| Resource | Initial hard limit |
| --- | --- |
| Connection control | 16 KiB; depth 8; 8 numeric-address candidates |
| Candidate/binding lifetime | 1 hour, further bounded by scope and actual lease |
| Attempt window | 60 monotonic seconds; 2 concurrent attempts per peer |
| Simultaneous attempts/sessions | 8 profile-wide; 1 selected pending session per invitation |
| Pre-validation checks | 2 checks/second/peer, 8/second/profile, 120/window/peer, at most 1200 bytes/check |
| Queues | 128 items and 64 KiB per peer; 512 KiB/profile |
| Pending bootstrap | 5 minutes maximum, 4096 packets and 2 MiB in each direction; 32 packets/second |
| Native handshake | 5 seconds; two pending incoming connections per isolated proof peer |
| Idle and upkeep | 15-second authenticated transport timeout; 5-second proof keepalive; mobile budget unqualified |
| Retry | 5-second base, exponential to 5 minutes, ±20% jitter; stop at scope expiry/cancel |

Bootstrap must allow only the expected peer's join/admission controls and
required RNS path/Link traffic. A path request must name an expected destination.
It must not enable unrelated forwarding even if another app interface enables
transport. Admission replaces pending credentials rather than extending them.

Offer selects the initial owner challenge. Answer binds that offer and the
joiner's identity/generation and starts the joiner's window. Importing Answer
starts the owner's window. Ready references that exact Answer and a fresh owner
generation; importing it re-arms only a still-owned joiner socket/generation.
Otherwise a fresh Answer is required. Document wall-clock validity and local
monotonic windows are distinct. Neither device infers email-delivery time.

Use the lexicographically smaller authenticated RNS destination as QUIC client
after both identities are known. Keep one winning session per scope and generation
pair; close duplicate successes only after the winner is authenticated. Do not
retire an existing usable path while a replacement is only a candidate. Explicit
authenticated checks and QUIC must share one receiver; no separate discovery
socket may supply an advertised tuple. The check framing remains a review gate,
not an ad-hoc packet prefix in this proof.

## Adapter gate and outstanding evidence

The installed stock UDPInterface sets `online` when its local listener starts,
and forwards incoming bytes to RNS without authenticating their local process
source. IFAC authentication is performed later by RNS. Its loopback listener can
therefore remain online without a native engine or remote peer. A regression
probe records these facts; they are not an IFAC bypass or release qualification.

Do not attach that interface in the shipping service until independent tests
cover IFAC injection/replay, cross-peer isolation, DoS bounds, engine failure,
and bootstrap isolation with transport enabled elsewhere. A constrained
`MeshDirectInterface` or isolated bootstrap context is required if these cannot
be enforced.

The socket-free prototype in `service/tools/direct_packet_adapter.py` uses a
private per-session token and a byte/item bounded queue instead of a loopback
listener. Engine loss and expiry retire the interface and discard queued data.
Pending mode enforces packet, byte, rate and five-minute budgets and refuses
activation or further packets if routing or another interface is present. This
requires a dedicated RNS context; it is not an adapter for the shipping shared
context. The proof's post-LXMF gate accepts only its bound source and workspace,
and only join/admission controls during pending bootstrap. Existing service
signature and admission checks still run after that gate.

`service/tools/direct_fabric_harness.py` has passed with a source-only inherited
queue carrier: actual join, signed acknowledgment before approval, admission,
fresh workspace-scoped bindings checked against the local manifest, bidirectional
LXMF messages, ratchet readiness, endpoint receipts, and carrier-death teardown.
It closes the pending carrier and creates fresh credentials after admission.
The proof uses transactional binding acceptance before activation, including a
private service workspace authority reload. Before carrier authorization the joiner
saves its signed join, and its pending authority loader verifies that durable state.
The owner prepares the durable challenge/deadline and selects the signed responder
through the private service transaction. The trusted harness carries the challenge
between peers; this is not an implemented public Offer/Answer/Ready exchange. Production activation/revocation reconciliation and crash recovery
remain unimplemented.

The GitHub-only `packet_bridge` example carries the same private frames over two
mutually authenticated native QUIC peers. Native TLS keys stay in Rust and RNS
keys stay in their respective Python service processes. Only public certificate
pins cross the inherited control pipe. The controller is a trusted test harness,
not an app IPC implementation. The native topology now passes on Windows and
Linux, and Android ARM64 cross-compilation passes in
[GitHub run 38854581893](https://github.com/ahouchens/mesh-chat/actions/runs/38854581893)
at `cbcf659`. These are controlled-peer results. Candidate values in binding fixtures are not
discovery or reachability evidence.

The proof now filters packets before they enter RNS. Only the exact local/peer
destinations and their path requests pass. Link IDs must derive from an observed
scoped Link request; packet proofs must match a recently observed packet in the
opposite direction. Tracking is bounded to 32 Links and 256 receipt hashes with
expiry, and replay does not extend entries. RNS still performs cryptographic
validation. This variant rejects IFAC-marked packets, routed headers and nonzero
hop counts; it does not pretend to decode IFAC before RNS. The end-to-end source
topology passes this filter. Retiring the isolated carrier tears down its RNS
Links before replacement.

One explicitly shared `ProfileBudget` caps adapter sessions at eight and their
aggregate queued bytes at 512 KiB; per-adapter limits remain 128 items/64 KiB.
Dequeuing and teardown release credits, including repeated teardown and failed
replacement activation. This accounts for adapter queues, not all native,
IPC and kernel buffers. Shared-context isolation, full pipeline resource
accounting and platform embedding remain production activation gates.

Phase 2–3 runtime activation, optional phase-4 helpers, and phase-5 release
qualification remain incomplete. The feasibility workflow passes on the tested
commit; it is not a packaged application test. Publishing/installing artifacts and physical
Windows/Android topology and battery evidence remain separate gates.

## References

- [Quinn endpoint and same-socket ownership](https://docs.rs/quinn/0.11.12/quinn/struct.Endpoint.html)
- [QUIC DATAGRAM requirements](https://www.rfc-editor.org/rfc/rfc9221.html#section-5)
- [Patched Quinn datagram accounting](https://rustsec.org/advisories/RUSTSEC-2026-0343.html)
- [Patched Rustls certificate decompression](https://rustsec.org/advisories/RUSTSEC-2026-0348.html)
