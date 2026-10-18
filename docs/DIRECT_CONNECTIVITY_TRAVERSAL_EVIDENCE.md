# Server-free traversal implementation evidence

Status: implementation and qualification in progress, 2026-10-18. This is not a
physical connectivity result or release approval. The detailed requirements are
in [the spec](DIRECT_CONNECTIVITY_TRAVERSAL_SPEC.md).

## Wizard increment: 0.2.58 / Android 2058

Preparation checks now precede every displayed sharing surface. The controller
checks current route identity, exact retained UDP ownership, candidate families,
mapping/lease evidence and available Windows profile evidence. No TCP rule is
used as UDP proof. An actual intended-peer native connection is required for
"verified". Polling uses connection_state and does not consume packets.

Both-empty is stopped at answer preparation before the UI shares the reply.
Unhosted one-sided exchanges remain allowed. Retry reuses the same invitation
and request, and a network change invalidates the old export. Diagnostics include
allowlisted route/socket/mapping/firewall facts. UDP firewall repair and manual
UDP mapping UI are not supported; the wizard says so explicitly.

52 targeted readiness/setup/candidate/diagnostic source tests passed locally.
42 browser layout cases passed at `4992904`; phone inspection led to moving
the primary action above diagnostics and collapsing technical evidence. The
0.2.56 packaging run was cancelled before promotion. Final frontend regressions
and 42 browser layout cases are submitted to Actions,
along with full native qualification and distinct Windows/Android builds.
Preceding 0.2.57 application commit: `b4a804b00a5467e4712df524bc39cafbe8576333`.
[TypeScript, wizard/diagnostic frontend regressions and all 42 layouts passed](https://github.com/ahouchens/mesh-chat/actions/runs/39159976026).
Artifact `connection-layout-evidence` ID `12148845444` was downloaded; 360px
normal and doubled-text screenshots were inspected after the action-first layout
change. [Windows/Linux recovery red/green passed](https://github.com/ahouchens/mesh-chat/actions/runs/39159975993).
[Full CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39159975995).
[native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39159976022)
is still running. [0.2.57 packaging](https://github.com/ahouchens/mesh-chat/actions/runs/39160105646)
was cancelled to add a regression-backed retry action when readiness checks are
unavailable. Version 0.2.58 / Android 2058 includes that correction; its final
qualification is pending. No installable wizard build is qualified yet.

The preceding 0.2.55 native run `39158158182` passed Linux and Android but failed
Windows `both_hosted-source-revocation` while waiting for channel discovery after
membership became active, before revocation itself. The current run must qualify
that path; do not describe the earlier run as passing or relax its assertions.

Physical mobile-carrier acceptance and independent review remain pending.

## Exact-commit evidence

- Current source version **0.2.55**, Android **2055**: fixes revocation cleanup
  while recovery has a pending handshake or all worker slots are occupied.
  Both new regressions fail against 0.2.54 and pass with the fix; 54 targeted
  recovery/candidate source tests pass. New build and full native qualification
  are pending. Do not use the superseded 0.2.54 artifacts for acceptance.

- Superseded application: **0.2.54**, Android **2054**,
  `11b2b1f0a099082933da92f4e5fc0a262fd3121c`.
  [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39156568048),
  [layout passed](https://github.com/ahouchens/mesh-chat/actions/runs/39156567932),
  [Windows/Linux native red/green regression passed](https://github.com/ahouchens/mesh-chat/actions/runs/39156568335).
  [Artifact build](https://github.com/ahouchens/mesh-chat/actions/runs/39156577823)
  passed verification, signed Android packaging and Windows installer packaging.
  Both archives were downloaded and their archive/inner-file hashes verified;
  see the [device checklist](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md).
  [Exact application native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39156568009)
  is running. The earlier recovery-fix commit `78397ffd7bb0744c948abd4f72ae81a993133d70`
  passed both Windows/Linux durable recovery pipelines in
  [this run](https://github.com/ahouchens/mesh-chat/actions/runs/39155888744),
  but its later Windows unhosted-joiner revocation scenario failed: one native
  session remained allocated. The scheduler skipped authority checks during
  pending work; 0.2.55 moves those checks ahead of capacity/pending guards.
  The active-owner resume fix has three passing source regressions and a native
  packet-queue regression; it reads native state without consuming DATAGRAMs.
- Superseded **0.2.52**, Android **2052**,
  `dec191bbea6c63967cfcf5073abd7acc052a3333`.
  [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39154322468),
  [18 browser layout cases passed](https://github.com/ahouchens/mesh-chat/actions/runs/39154322749)
  at 360/393/1280px with normal/doubled text and clipboard denial. Phone screenshots
  were downloaded and visually inspected. This is browser evidence, not Android
  lifecycle or human usability acceptance.
  [Windows/Android artifact build](https://github.com/ahouchens/mesh-chat/actions/runs/39154321087)
  passed all jobs and produced signed Android and Windows installer artifacts;
  [Latest native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39154322732)
  failed Windows `unhosted_restart` after eight passing scenarios; Linux recovery
  passed. Do not promote 0.2.52. Recovery's auxiliary-check/listening-round race
  was fixed at `78397ff`: the delayed-listener regression fails against the old
  code and passes against the fix on both platforms. Initial setup retains
  simultaneous checks; recovery checks use alternating dial rounds.
- `b01572d0232e3980751638b2e91ba9051272f60b`:
  [expanded NAT fixture passed](https://github.com/ahouchens/mesh-chat/actions/runs/39154080619),
  artifact `direct-nat-evidence` ID `12146297270`. All seven trials passed:
  three compatible NAT connections (1.264–1.267 seconds), passive negative
  control, UDP blocked on one/both sides, and destination-dependent mapping with
  a stale tuple (bounded failures at 10.234–10.254 seconds). Each successful
  trial carried packets both ways. These are isolated kernel topology results.
- `118329d17df022ff201b6693e137d2896f07cdd4`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39151505158).
  [Native run](https://github.com/ahouchens/mesh-chat/actions/runs/39151507296):
  all Windows, Linux and Android jobs passed.
- `e496b2e326ac38963428c16d787da9d2270f9d48`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39152705420).
  [Native run](https://github.com/ahouchens/mesh-chat/actions/runs/39152703505):
  Windows/Linux dispatcher tests, Android compile and Linux NAT fixture passed;
  the complete pipeline passed. This adds multiple route sockets.
- `12e25abbcfc6a4cdce42c115d8a11f3435655a04`: [CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39153126912).
  [Native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39153128711)
  passed. This bounds incoming checks across the entire socket group.

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
| A7 | Destination-dependent SNAT profile with a tuple learned for a different destination passed its expected bounded failure at `b01572d`. No universal NAT claim. |
| A8 | One-side/both-side UDP-block fixture passed at `b01572d`. This fixture does not prove TCP fallback; existing authorized TCP remains separate. |
| A9 | Existing mapping renewal, migration, address-loss and manual recovery-update regressions retained. Recovery now rotates eligible interfaces on bounded retries with a source regression; latest native pipeline pending. Multiple simultaneous recovery route sockets are not implemented. |
| A10 | Signed chain/replay tests retained; joiner and owner saved-message resume, expired/lost ownership and retry-ID regressions added. Latest UI run pending. |
| A11 | Existing restart/suspend recovery pipeline; Android 45-second share grace implemented. Actual sharing, process death, Doze and network switch device tests pending. |
| A12 | Existing authority/cancellation/queue tests plus group socket cancellation and shared bounds. Adversarial packet-rate qualification and independent protocol review pending. |
| A13 | Existing Linux network audit and isolated NAT topology; latest full audit pending. No runtime observer, rendezvous, relay or IP lookup added. |
| A14 | Pending physical Windows/home-router ↔ Android/mobile-carrier test on uniquely versioned artifacts. |
| A15 | Deterministic client outgoing/server incoming path and auxiliary closure tests; independent review of boundary races still required. |
| A16 | Default Invite invokes the guided controller; one outgoing item and shared import entry tested in frontend CI. Owner resume added in follow-up. Human end-to-end acceptance pending. |
| A17 | Eighteen browser layout cases passed at `dec191b`; 360/393px doubled-text screenshots inspected. Actual Android and human usability acceptance pending. |
| A18 | Allowlisted bounded diagnostics, real native check counters, candidate-source counts, offline/clipboard-denial tests. Receipt/approval are timestamped facts, never inferred from QUIC. |
| A19 | Visible Settings/diagnostic version, actual Android package metadata and native commit command implemented. Installed Windows/Android artifact matching pending. |
| A20 | Protected bounded history, last failure, storage retention and clear-preserves-request regressions. A real encrypted VaultStore close/reopen regression passed locally; physical app restart acceptance pending. |

## Release gates

Do not label the whole spec complete from the controlled NAT success. Remaining
work includes the latest native/artifact qualification,
independent protocol review, physical mobile usability/accessibility
checks, uniquely versioned Windows/Android artifacts and physical acceptance.
No merge or public release has been performed. Draft PR #1 holds the implementation.
The superseded 0.2.51 artifact workflow failed an existing administrator benchmark
timing threshold; the same commit's ordinary CI passed. The threshold was not
changed. The 0.2.52 release verification passed with that threshold intact.
