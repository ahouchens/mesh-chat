# Direct connectivity Phase 1 evidence

Status: final qualification pending. Scope: the roadmap's **protocol and adapter
proof with two controlled peers**. This is not a shipping direct-connectivity
release, public email bootstrap, Internet traversal, or physical-device evidence.

The exit criteria below are copied in scope from
[the roadmap](DIRECT_CONNECTIVITY_ROADMAP.md#implementation-roadmap). Phase 1
selects the transport and adapter and qualifies their controlled behavior. Native
host embedding, private production IPC, production bootstrap-context management,
candidate discovery and automatic recovery remain later implementation gates.

| Phase-1 requirement | Implementation and executable evidence |
| --- | --- |
| Specify bounds and identity binding | ADR 0018 defines canonical 16-KiB controls, depth/candidate limits, signed exact scopes and certificates, attempt/lifetime/queue bounds, client roles and conflict handling. `test_direct_binding.py`, `test_direct_offer.py`, `test_direct_exchange.py` cover malformed, forged, expired, misbound, replayed and conflicting controls, failed commits and restart. |
| Select the Rust library and preserve socket ownership | Locked Quinn/Rustls crate, Rust 1.88 CI, `BoundSocket` and non-cloneable `PreparedAttempt`; native tests preserve exact socket/key through authorization and Ready, reject stale attempts, and cancel/expire resources. |
| Ordinary LXMF messages, ratchets, receipts, joins and approval pass unchanged | `test_real_services_over_private_direct_packet_carrier` exercises real services/RNS/LXMF, signed application receipt before approval, admission, fresh admitted credentials, bidirectional messages, ratchets and endpoint receipts. It also covers revocation, service/native crash, suspension and encrypted-profile restart. |
| Peer-key mismatch fails safely | `substituted_peer_key_cannot_authenticate`, cross-language public-certificate binding proof and Python certificate/scope-substitution tests. RNS/vault private keys remain in Python; TLS private keys remain in Rust. |
| Engine death fails safely | Native connection-death test plus intentional native process kill in the real-service topology; packet loss/cancellation events do not depend on queue space. |
| Oversized packets fail safely | Native malicious authenticated-peer DATAGRAM test, oversized inherited-frame rejection, Python adapter/pump tests and bounded policy tracking. |
| Local injection fails safely | Native `separate_local_process_cannot_inject_native_packets` sends forged, QUIC-shaped and oversized UDP packets from an independent unprivileged Python process before and after TLS. Neither peer delivers them; valid bidirectional packets still pass. No packet/control network listener exists; anonymous pipes are private capabilities. Python tests separately reject foreign/stale session tokens and cross-peer destinations. |
| Baseline makes no external discovery calls | Linux runs the complete native topology suite beneath `strace -f`, including Python workers and Rust descendants. `direct_network_audit.py` rejects non-loopback Internet socket addresses even on failed syscalls, undecoded Internet addresses, raw network sockets and named local proxy connections. It requires observed packet traffic and produces an endpoint-free count artifact. This is observed controlled-run provenance, not a promise for every app configuration. |
| Pending isolation and resource bounds | Pending adapter activation fails with another interface or RNS routing enabled and retires if that changes. Tests enforce allowed bootstrap messages/destinations, packet/byte/rate ceilings, shared profile budgets, per-scope lease deduplication, and bounded cancellation even with full queues or blocked authority callbacks. The proof requires isolated non-routing service processes. |

## Qualification commands and platforms

- Local non-build validation: `.venv/Scripts/python.exe -m pytest service/tests -m "not integration" -q`.
- Local source topology: set `MESH_CHAT_RUN_DIRECT_FABRIC_TESTS=1`, then run
  `.venv/Scripts/python.exe -m pytest service/tests/test_direct_fabric_harness.py -q`.
- Native Windows/Linux and Android ARM64 compilation: the
  `direct-fabric-proof.yml` GitHub Actions workflow. No local native build is used.
- Linux provenance artifact: `direct-network-evidence.json`, published only after
  both the topology command and trace audit succeed. The trace is temporary;
  packet payloads and endpoint tuples are not published in the report.

Final tested commit/run and results will be recorded after CI completes. Earlier
service-owned packet runtime qualification passed at `b0f0962` in
[run 39043434010](https://github.com/ahouchens/mesh-chat/actions/runs/39043434010).

## Explicit remaining gates

Phase 2 still needs native app embedding/private IPC, owner pending lifecycle and
production isolated-bootstrap integration, public Offer/Answer/Ready import/export,
native-owned candidate collection/mapping and traversal, and tested direct-TCP
fallback. Phase 3 needs durable automatic relationships and recovery scheduling.
Phase 4 helpers are optional. Phase 5 requires physical Windows/Android lifecycle,
network topology, compatibility, security, usability and release qualification.
This evidence does not approve merging, publishing, installing or enabling the
experimental adapter by default.
