# ADR 0019: Server-free coordinated direct connection

Status: implementation in progress; independent review and qualification pending.

## Decision

Keep the signed version-2 Offer/Answer/Ready authority and the exact native UDP
socket. No observer, rendezvous, relay, address guessing, or additional receiver
is permitted. An empty pair of public candidate sets remains a discovery failure.

Use standard mutually authenticated QUIC handshakes as connectivity checks. Both
endpoints may initiate checks; the existing deterministic role selects only the
client's outgoing connection and the server's incoming connection for application
traffic. The server's outgoing checks open compatible NAT filters. The client
accepts and retires these auxiliary authenticated connections without delivering
their DATAGRAMs. Thus simultaneous initiation cannot select two application paths.
This is a smaller QUIC-only mechanism, not ICE or a claim of ICE interoperability.

Quinn remains the sole receiver and handles transaction IDs, retransmission,
anti-amplification, TLS proof of the signed certificate, and connection closure.
Neither initial packets nor address observations confer membership. Only a fully
authenticated selected connection reaches the existing bootstrap authority.
An incoming authenticated connection already observes the intended peer's tuple;
it may be used on that connection, never exported as a general reachable address.

Checks are limited to eight verified numeric candidates, one outgoing handshake
at a time, 64 starts and a 60-second monotonic window further clamped to candidate
and authority expiry. A candidate receives at most 1.5 seconds per round, followed
by a minimum 500ms start interval; a silent candidate cannot starve alternatives.
Two pending incoming handshakes and existing queue bounds remain. This bounds
handshake starts, not individual QUIC packets: retransmissions remain Quinn-owned.
Packet-rate evidence and the existing profile resource gate must be qualified
before release. Authority loss, cancellation and deadline drop all temporary work.

Initial setup and admission replacement can retain up to four local route sockets
under one native-only certificate/key and signed session. The service inspects
every socket before exporting all candidate tuples. Native capacity counts sockets
(eight profile-wide), not just group handles. Family-compatible local/remote pairs
receive sequential slices; the deterministic client has only one outgoing attempt
at a time. Every local endpoint uses Quinn as its sole receiver. Losing route
endpoints close after the selected authenticated connection is established.
This extends the existing signed candidate-list contract without adding a new
public control format. Older version-1/version-2 inputs remain readable.

Recovery keeps its existing rotated-certificate/service-approval protocol and
role reversal, with two-sided outbound checks and shorter fair candidate slices.
Its single selected local socket and migration path are retained. Bounded retry
attempts rotate eligible interfaces after trying the saved interface, and reset
port hints when changing interfaces. Each replacement is signed through the
existing protocol. Simultaneous recovery socket groups are not implemented.

Android activity switching retains current socket ownership for a bounded
45-second background grace period. Returning cancels the suspension callback;
remaining away or destroying the activity retires ownership. This is not a
foreground-service or Doze execution guarantee. Process death still requires
fresh controls, and the UI never exports an expired or unowned saved reply.

## Evidence required

An isolated Linux network-namespace fixture must put both native hosts behind
source NAT and outbound-dependent UDP filters. Simulator-known tuples may enter
only the CI harness. The passive-server negative control must fail while the
coordinated version succeeds using the same native ports. Loopback is not NAT
evidence. Physical Windows/home-router to Android/carrier remains a separate gate.

## Incremental checklist

| Feature | Existing implementation | Missing change and evidence |
| --- | --- | --- |
| F1 | `prepare_candidates`, mapping and ownership regressions | Multiple owned route sockets/provenance; A4/A6, retain single-stack regression |
| F2 | `traversal`, pinned TLS, `Host.activate_with_role` | Two-sided checks, fair deadlines, deterministic selection; A2/A3/A12/A15 |
| F3 | `DirectSetup`, durable exchange, expiry/replay tests | Recover saved exchange and clearer expiry; A10/A16 |
| F4 | `native_parameters`, existing TCP queue and receipts | Preserve and explain discovery versus check failure; A5/A8 |
| F5 | `DirectRecovery`, renewal, migration and lifecycle tests | Integrate coordinated checks and route alternatives; A9/A11 |
| F6 | `DirectConnectionSetup`, `WorkspaceInviteDialog` | One outgoing item/import surface and pending resume; A16/A17 |
| F7 | Older diagnostic copy, protected vault | Bounded allowlisted history and offline copy/fallback; A18/A20 |
| F8 | Package version footer and release version script | Visible version and actual component/build metadata; A19 |

Do not mark a row complete from this checklist. Record exact CI commits and open
gates in the implementation evidence. In particular, this decision alone does
not implement multiple route sockets or prove two unknown tuples discoverable.

## References

- [Quinn endpoint ownership](https://docs.rs/quinn/0.11.12/quinn/struct.Endpoint.html)
- [QUIC transport and address validation](https://www.rfc-editor.org/rfc/rfc9000.html)
- [Specification](../DIRECT_CONNECTIVITY_TRAVERSAL_SPEC.md)
