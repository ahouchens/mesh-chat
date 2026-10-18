# Server-free traversal implementation evidence

Status: implemented candidate and current automated qualification passed, 2026-10-18. This is not a
physical connectivity result or release approval. The detailed requirements are
in [the spec](DIRECT_CONNECTIVITY_TRAVERSAL_SPEC.md).

## Current candidate: 0.2.63 / Android 2063

The fifth 0.2.62 Windows address-loss repetition failed in `39167069236` after
four passes. Artifact `12151740266` retains both native lifecycle traces. The
server began its final attempt at 1792358833.332 and the client at 1792358835.444:
matching fresh ports, but a 2.112-second server-first stagger and no completed
handshake for the full minute. This is the opposite start order from the earlier
non-reproducing client-first timing test.

The new native regression reproduces server-first/late-client startup. The
candidate uses 1500ms client / 2500ms server round slices so the role schedules
cannot remain locked together, retaining the 500ms pause, overall deadline,
check budget and membership gate. [Old-fails/new-passes qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39168424539) passed on Windows and Linux, including both earlier recovery regressions. Full CI and all 42 layout cases passed. Both platform packages in build `39168607399` passed and were hash-verified. All five address-loss and all five source-admission Windows trials passed in `39168424542`; both artifacts (`12151951927`, `12151725812`) were downloaded and all ten JUnit records checked. [Full native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39168424723) passed all Windows, Linux and Android jobs at `34d9927f76d27c037e5a2d727bb75167fff3c8e0`, including production setup/admission, durable recovery, real RNS/LXMF traffic and Linux network/NAT audits. Do not promote the 0.2.62 artifacts based on their successful builds.

The same regression workflow passed the controlled hostile-traffic profile on both platforms. Each native target received 500 unsupported-version QUIC packets (600,000 bytes) and returned 500 version-negotiation packets (27,500 bytes); no unauthorized application packets were exposed. A separate authenticated session still delivered in both directions, and target close completed below the five-second bound. Archives `12151985214` (Windows) and `12151249247` (Linux) were downloaded and SHA-256 verified. This is a defined loopback parser/amplification/isolation profile, not a universal packet-rate limit, NAT result or physical-device test.

Release verification for 0.2.63 passed 934 service tests (47 environment-specific skips), 215 frontend tests, and bundle validation. Verification artifact `12151493935` matched archive SHA-256 `a0ad045592b9c8c00004ff76ca2e2c1aca79bc83cfb310c81a5f05c167b94875`; its source record is the exact application commit `34d9927f76d27c037e5a2d727bb75167fff3c8e0`. Native tests excluded from that generic run are qualified in their separate workflows.

Current Linux native qualification passed all stages. Its seven-trial NAT artifact `12151329034` was downloaded and hash-verified: three compatible NAT connections delivered in both directions in 1.257-1.265 seconds; the passive negative control, UDP-blocked profiles and destination-dependent stale tuple failed as expected in 10.219-10.236 seconds. Candidate tuples are fixture ground truth, not production discovery. The network, recovery and setup audit artifacts (`12152475678`, `12152465004`, `12151309300`) were also hash-verified; each reports zero external addresses across the controlled topology and descendants.

## Historical qualification notes

The following version sections retain the status and evidence collected during development. Use the current-candidate section and acceptance ledger for the present recommendation; historical successful builds do not supersede later failing tests.

### Pause ownership correction: 0.2.62 / Android 2062

The earlier `39164119167` run failed Windows server-restart recovery at
`native_wait` and Linux server-restart cleanup with one native handle remaining
after pause. The capsule correction addresses premature native attempt failure;
a separate source regression now reproduces the pause allocation race.

Previously, a new native socket was not registered with recovery until router
candidate discovery completed. Pause could return during that gap. Pending
ownership now registers each local allocation atomically with cancellation,
before slow discovery. Pause closes that ownership immediately; a retired worker
cannot allocate again, and exporting during discovery returns preparing instead
of exposing stale details. Only native allocation/close share the cancellation
lock; router discovery does not hold the service dispatch lock.

The new test failed before the correction with handle 7 still allocated and
passes afterward. All 75 recovery, candidate, runtime and packet source tests
passed. [Build 39167070427](https://github.com/ahouchens/mesh-chat/actions/runs/39167070427)
passed full verification (934 service tests, 47 skipped; 215 frontend tests),
Windows packaging/embedded host checks and signed Android packaging. Both archives,
manifests and packaged files were hash-verified. Those packages are superseded by the current pair in the
[device checklist](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md). Verification
artifact `12151147432` matched SHA-256
`03b436ba2d2e9db1ac2bdf4e66edbb8ba8c91d88fc763377dc32df24d455196b`.
[Full native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39167069275)
is still running. The 0.2.61 packages below are historical evidence.

## Recovery capsule correction: 0.2.61 / Android 2061

Full Windows run `39163214793` reproduced address-loss failure despite the five
passing isolated repetitions. Both peers retained matching fresh port hints,
with `native_wait` failure on both sides. A proposed role-period change was
rejected: the staggered regression also passed the old code, so it did not prove
the hypothesis. Both the speculative production change and its red/green case
were removed. Existing role periods and regression assertions are retained.

A separate source finding passed native red/green qualification: a TLS
peer closing before encrypted capsule exchange terminated the entire recovery
attempt. The candidate retries that incomplete pre-authorization exchange within
the original deadline and start budget. It exposes no service evidence or data
until exchange succeeds and preserves the subsequent membership approval gate.
A regression retires one TLS peer, then requires a fresh peer to authenticate,
receive explicit service approval and deliver data within the same attempt.
[Windows and Linux red/green passed](https://github.com/ahouchens/mesh-chat/actions/runs/39165009599)
at `ed25af6fcb8f13d423ffd2d71478d7037b11746e`: the old implementation fails
the behavioral assertion and the fix passes, with the existing unhosted restart
regression retained. Full recovery qualification and matching builds passed for 0.2.61.
This does not yet prove that every preceding pipeline failure has the same cause.

The controlled native fixture now retains a bounded, credential-free trace of
prepare/recover/state-transition/authorization/close events to identify the failed
attempt lifecycle on both peers. This is CI evidence, not production logging.
0.2.59 packaging was cancelled; do not promote its artifacts. Its full verification
passed 933 service tests (47 skipped) and 215 frontend tests. The verified report
artifact `12149803730` has SHA-256
`084eb80f892e4a282d400836d6d6acbf10b2468cee3af11bde4dc36a3b3f621a`.
Those artifacts are superseded; use the current qualification status at the top of this record.

### Matching artifact and repetition results

[Build `39165181059`](https://github.com/ahouchens/mesh-chat/actions/runs/39165181059)
passed full verification (933 service tests, 47 skipped; 215 frontend tests),
Windows packaging/embedded native tests and signed Android packaging. Both
archives, manifests and inner files were verified. Those packages are superseded by the current pair in the [device checklist](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md). Verification artifact `12150362873` matched
SHA-256 `46ad61b2e08d7c20d99615e8fed5820e933c418a2cbd8b7542e983753a433a9b`.
[Windows repetition](https://github.com/ahouchens/mesh-chat/actions/runs/39165009612)
passed all five source-admission and all five address-loss trials. Address-loss
artifact `12150358580` was downloaded and each JUnit record checked.
The [full native pipeline](https://github.com/ahouchens/mesh-chat/actions/runs/39165009596)
passed all jobs. Independent review and physical acceptance remain open.

## Diagnostic follow-up: 0.2.59 / Android 2059

Readiness failures (no route, network changed, failed checks, and neither device
having an address) now update the retained last failure. Four regressions verify
that subsequent success and history rollover cannot discard that evidence; a
fifth verifies that one-sided preparation is not mislabeled as failure. All ten
diagnostic source tests passed. The 0.2.59 package run was superseded by 0.2.61.
The 0.2.58 results below remain exact-version evidence, not 0.2.59 qualification.

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

## Current qualification

Historical application: **0.2.58 / Android 2058**, commit
`0bf9623a9d4c01042793f63d3ffb1fd984443308`.

- [Full CI passed](https://github.com/ahouchens/mesh-chat/actions/runs/39160399832):
  928 service tests passed, 47 skipped; 215 frontend tests passed. TypeScript and
  the production web bundle passed. Verification artifact `12148577698` matched
  SHA-256 `1ee12b53fc38223e4cc1b51ad68e54a2e9ce5fe69312b16515136536837b218f`.
- [Full native qualification passed](https://github.com/ahouchens/mesh-chat/actions/runs/39160399603):
  Windows/Linux setup, admission, durable recovery and native dispatcher checks;
  Linux network/NAT audits and Android native compilation.
- [Wizard and 42 layout cases passed](https://github.com/ahouchens/mesh-chat/actions/runs/39160399583).
  Equivalent preceding 360px normal/doubled-text screenshots were inspected.
- [Both platform packages passed](https://github.com/ahouchens/mesh-chat/actions/runs/39160414911).
  Android's initial NDK ZIP download failed before compilation; its retry passed
  on the same commit. Both archives, manifests and packaged-file hashes were
  verified. Exact downloads are in the [device checklist](DIRECT_CONNECTIVITY_TRAVERSAL_DEVICE_TEST.md).
- Author-side boundary review and 102 focused source tests are recorded in the
  [review record](DIRECT_CONNECTIVITY_TRAVERSAL_REVIEW.md). Independent approval
  and physical acceptance remain open.

Two preceding Windows failures remain reliability observations, not silently
resolved by a later passing run: `39158158182` timed out waiting for channel
discovery after membership became active, before revocation; `39159976022`
failed address-loss recovery at `native_wait`. The focused
[Windows repetition run](https://github.com/ahouchens/mesh-chat/actions/runs/39163212934)
uses five fresh processes per scenario without relaxing assertions. Source
admission and address-loss recovery each passed all five. Downloaded JUnit
evidence confirms ten tests with no failures or errors (source artifact
`12149013640`, native address-loss artifact `12149836987`).
Paired test-only recovery evidence now records both peers on failure.

The reproduced recovery failures have regression-backed corrections and the current full native/repetition runs passed. Earlier failures remain recorded; finite CI runs are not a universal reliability guarantee.
No merge or public release has been performed. A passing controlled run is not
physical mobile-carrier evidence.

## Exact-commit evidence

- Superseded source version **0.2.55**, Android **2055**: fixes revocation cleanup
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
| A1 | Exact 0.2.63 real-QUIC production setup/admission passed; physical public-path qualification pending. |
| A2–A3 | Seven-trial native NAT fixture passed at `34d9927`, including three successful coordinated connections and a failing passive negative control. Exact timings and artifact are above. |
| A4 | One-sided candidate/native accept tests and unhosted recovery pipeline; no general reachable address is inferred from an observed tuple. |
| A5 | Empty-candidate setup regressions preserve the request and do not activate native transport. |
| A6 | Multiple owned route sockets, silent-first-candidate native tests and mixed-family service tests added; exact 0.2.63 native suite passed. |
| A7 | Destination-dependent SNAT profile with a tuple learned for a different destination passed its expected bounded failure at `34d9927`. No universal NAT claim. |
| A8 | One-side/both-side UDP-block fixture passed at `34d9927`. This fixture does not prove TCP fallback; existing authorized TCP remains separate. |
| A9 | Existing mapping renewal, migration, address-loss and manual recovery-update regressions retained. Recovery now rotates eligible interfaces on bounded retries with a source regression; 0.2.63 durable recovery passed on Windows/Linux and all five focused Windows address-loss repetitions passed. The server-first timing trace has an old-fails/new-passes native regression; earlier cleanup and incomplete-capsule failures have separate regression-backed fixes. Multiple simultaneous recovery route sockets are not implemented. |
| A10 | Signed chain/replay tests retained; joiner and owner saved-message resume, expired/lost ownership and retry-ID regressions added. Latest wizard TypeScript/frontend run passed at `34d9927`. |
| A11 | Existing restart/suspend recovery pipeline; Android 45-second share grace implemented. Actual sharing, process death, Doze and network switch device tests pending. |
| A12 | Existing authority/cancellation/queue tests plus group socket cancellation and shared bounds. The 500-packet unsupported-version profile passed on Windows/Linux at `34d9927`, with measured amplification, unauthorized-data rejection and separate-session isolation. Broader adversarial profiles and independent protocol review remain open. |
| A13 | Existing Linux network audit and isolated NAT topology; exact 0.2.63 Linux full audit passed; downloaded reports record zero external addresses. No runtime observer, rendezvous, relay or IP lookup added. |
| A14 | Pending physical Windows/home-router ↔ Android/mobile-carrier test on uniquely versioned artifacts. |
| A15 | Deterministic client outgoing/server incoming path and auxiliary closure tests; independent review of boundary races still required. |
| A16 | Default Invite invokes the guided controller; one outgoing item and shared import entry tested in frontend CI. Owner resume added in follow-up. Human end-to-end acceptance pending. |
| A17 | Forty-two browser layout cases passed at `34d9927`; Current 393px normal/doubled-text and 360px doubled-text screenshots were visually inspected; artifact `12151940099` was hash-verified and all 42 overflow records checked. Actual Android and human usability acceptance pending. |
| A18 | Allowlisted bounded diagnostics, real native check counters, candidate-source counts, offline/clipboard-denial tests. Receipt/approval are timestamped facts, never inferred from QUIC. |
| A19 | Visible Settings/diagnostic version, actual Android package metadata and native commit command implemented. Both 0.2.63 artifacts and manifests were hash-verified; installed-device metadata matching remains a physical check. |
| A20 | Protected bounded history, last failure, storage retention and clear-preserves-request regressions. A real encrypted VaultStore close/reopen regression passed locally; physical app restart acceptance pending. |

## Release gates

Do not label the whole spec complete from the controlled NAT success. Remaining
work includes independent protocol review, broader adversarial traffic qualification,
physical mobile usability/accessibility
checks and physical acceptance using the verified matching Windows/Android artifacts.
The reproduced recovery failures have regression-backed corrections and the current full native/repetition runs passed. Earlier failures remain recorded; finite CI runs are not a universal reliability guarantee.
No merge or public release has been performed. Draft PR #1 holds the implementation.
The superseded 0.2.51 artifact workflow failed an existing administrator benchmark
timing threshold; the same commit's ordinary CI passed. The threshold was not
changed. The 0.2.52 release verification passed with that threshold intact.


## Historical artifact verification: 0.2.58

Build `39160414911` passed verification, Windows packaging/embedded native checks,
and signed Android packaging after retrying the NDK download. Both archives and
inner installer/APK hashes were checked; the paired-device checklist records the
URLs and hashes. Application commit is `0bf9623a9d4c01042793f63d3ffb1fd984443308`,
version 0.2.58 / Android 2058. Nothing was installed or executed locally.
Exact-version native run `39160399603` passed all jobs, including durable recovery
and setup/admission on both Windows and Linux. This does not
erase the preceding intermittent Windows failures; independent review and
physical acceptance remain required before promotion.
