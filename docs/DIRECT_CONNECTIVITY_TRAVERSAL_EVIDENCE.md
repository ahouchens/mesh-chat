# Server-free traversal implementation evidence

Status: implementation and qualification in progress, 2026-10-18. This is not a
physical connectivity result or release approval. The detailed requirements are
in [the spec](DIRECT_CONNECTIVITY_TRAVERSAL_SPEC.md).

## Exact-commit evidence

- `118329d17df022ff201b6693e137d2896f07cdd4`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39151505158).
  [Native run](https://github.com/ahouchens/mesh-chat/actions/runs/39151507296):
  Linux full job passed, Android compile passed, Windows recovery passed and
  remaining Windows setup qualification was still running when this record was written.
- `e496b2e326ac38963428c16d787da9d2270f9d48`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39152705420).
  [Native run](https://github.com/ahouchens/mesh-chat/actions/runs/39152703505):
  Windows/Linux dispatcher tests, Android compile and Linux NAT fixture passed;
  the complete pipeline is still being checked. This adds multiple route sockets.
- `12e25abbcfc6a4cdce42c115d8a11f3435655a04`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39153126912).
  [Native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39153128711)
  is pending. This bounds incoming checks across the entire socket group.

The NAT evidence artifact uses isolated Linux namespaces, SNAT and kernel
outbound-dependent filters. Three coordinated trials connected and carried
packets both ways; the same fixture with a passive server did not connect.
Simulator-known tuples are injected only into the harness. This proves neither
public address discovery nor behavior on every consumer or carrier NAT.

## Acceptance ledger

| Requirement | Evidence and remaining gate |
| --- | --- |
| A1 | Existing real-QUIC production setup/admission pipeline; latest full run and physical public-path qualification pending. |
| A2–A3 | Native NAT fixture passed at `118329d` and `e496b2e`; passive negative control failed as expected. |
| A4 | One-sided candidate/native accept tests and unhosted recovery pipeline; no general reachable address is inferred from an observed tuple. |
| A5 | Empty-candidate setup regressions preserve the request and do not activate native transport. |
| A6 | Multiple owned route sockets, silent-first-candidate native tests and mixed-family service tests added; latest native suite pending. |
| A7 | Destination-dependent SNAT profile with a tuple learned for a different destination added; bounded failure expected, CI pending. No universal NAT claim. |
| A8 | One-side/both-side UDP-block fixture added, awaiting CI. This fixture does not prove TCP fallback; existing authorized TCP remains separate. |
| A9 | Existing mapping renewal, migration, address-loss and manual recovery-update regressions retained. Recovery now rotates eligible interfaces on bounded retries with a source regression; latest native pipeline pending. Multiple simultaneous recovery route sockets are not implemented. |
| A10 | Signed chain/replay tests retained; joiner and owner saved-message resume, expired/lost ownership and retry-ID regressions added. Latest UI run pending. |
| A11 | Existing restart/suspend recovery pipeline; Android 45-second share grace implemented. Actual sharing, process death, Doze and network switch device tests pending. |
| A12 | Existing authority/cancellation/queue tests plus group socket cancellation and shared bounds. Adversarial packet-rate qualification and independent protocol review pending. |
| A13 | Existing Linux network audit and isolated NAT topology; latest full audit pending. No runtime observer, rendezvous, relay or IP lookup added. |
| A14 | Pending physical Windows/home-router ↔ Android/mobile-carrier test on uniquely versioned artifacts. |
| A15 | Deterministic client outgoing/server incoming path and auxiliary closure tests; independent review of boundary races still required. |
| A16 | Default Invite invokes the guided controller; one outgoing item and shared import entry tested in frontend CI. Owner resume added in follow-up. Human end-to-end acceptance pending. |
| A17 | Responsive wrapping styles added. 360/393px and large-text visual/device acceptance pending. |
| A18 | Allowlisted bounded diagnostics, real native check counters, candidate-source counts, offline/clipboard-denial tests. Receipt/approval are timestamped facts, never inferred from QUIC. |
| A19 | Visible Settings/diagnostic version, actual Android package metadata and native commit command implemented. Installed Windows/Android artifact matching pending. |
| A20 | Protected bounded history, last failure, storage retention and clear-preserves-request regressions; physical encrypted-profile restart acceptance pending. |

## Release gates

Do not label the whole spec complete from the controlled NAT success. Remaining
work includes the latest CI qualification, restrictive NAT coverage,
independent protocol review, mobile visual/accessibility
checks, uniquely versioned Windows/Android artifacts and physical acceptance.
No merge or release has been performed for this implementation branch.
