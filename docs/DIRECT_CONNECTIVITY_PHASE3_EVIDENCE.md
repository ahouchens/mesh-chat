# Phase 3 persistent relationship recovery evidence

Status: **Phase 3 implementation and required automated qualification are complete** at `5ba2b4460c760d7184776679a691ffcdb8489d45`. All controlled recovery exit criteria pass on Windows and Linux; Windows/Android package builds pass at the same commit. Physical qualification is separate and remains pending.
Phase 2 physical Windows/Android qualification remains pending. The user
authorized Phase 3 development independently of that gate.

## Durable acceptance increment

Admitted workspace binding acceptance now atomically commits an encrypted
relationship record and the existing replay high-water mark. Current signed
membership and exact device identities are reloaded inside that transaction.
The record retains the signed binding, public certificate, exact audience/scope,
candidate validity and last authenticated route evidence. It contains no native
handle, local adapter port, private key or live socket state. Invitation binding
acceptance cannot create this record. Existing Phase 2 replay floors remain in
force when the relationship record is first created.

Native authentication followed by a verified peer RNS announce records historical
route success. It does not manufacture application receipts or claim present
liveness. Stale, expired and duplicate success callbacks cannot replace current
evidence. Failure to persist confirmation retires the admitted carrier.
Bootstrap retirement is independent of the opposite-direction admitted announce;
the confirmation wait now follows the admitted carrier's lifecycle.

## Criterion tracking

| Required capability | Completed implementation / automated evidence |
| --- | --- |
| Encrypted exact workspace/device relationship | Production atomic acceptance, current membership and identity checks; existing replay keys retained |
| Generations, validity, successful route, retry and cleanup state | Sealed recovery state; generation/backoff reservation before native effects; bounded crash cleanup evidence until lease expiry |
| Fresh sockets/keys and RNS reauthentication | Separate recovery ALPN; actual TLS certificate possession plus peer-encrypted RNS binding and current membership before DATAGRAM approval |
| Signed surviving-path updates and explicit no-route recovery | Workspace control, strict audience/scope import, owned-only opaque export and workspace settings UI implemented |
| Same-socket UDP lease renewal | Actual returned tuple/lease persisted before export; ownership/persistence/retirement failure regressions pass locally and in CI; physical router behavior remains unqualified |
| Startup/resume, cancellation, fair bounded retries | Runtime epoch/token isolation, four workers/active relationships, eight native slots, fair scheduling and contention rotation implemented |
| Replacement before old-path retirement | Native authorization, signed RNS confirmation and durable winner required; failures preserve old usable path; injected failures and simultaneous real-QUIC replacement pass |
| QUIC migration and reconnect fallback | Client rebind and server rejection native tests; route watcher and explicit fallback implemented |
| Honest per-peer states | Reconnecting/dormant/update-needed; recent native replies, authenticated peer announce and RNS readiness reported separately; receipts unchanged |
| Preserve membership, queued messages and receipts | All ten shipping-native recovery scenarios pass on Windows/Linux with unchanged admission, identities and queued logical IDs, signed join acknowledgments retained, bidirectional endpoint receipts and zero native/interface resources after pause |

## Validation

The relationship suite covers restart, rotated certificates, replay/conflicts,
concurrent acceptance, wrong identity/audience/scope, revoked membership, expiry,
invitation rejection, encryption/commit failure, prior replay-floor migration,
stale success callbacks, unsupported stored versions and ciphertext storage.
The production pipeline additionally checks committed admitted relationship and
authenticated RNS evidence on both sides after bidirectional message receipts.
The shipping-dispatcher real-QUIC CI matrix runs those same assertions.

Before this increment, GitHub REST reconfirmed both supplied Phase 2 runs as
successful at exactly `200614ad31ec1ce16cd395701b7284bda3d67879`:
[native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39080401782)
and [verification/packages](https://github.com/ahouchens/mesh-chat/actions/runs/39080404932).
These are baseline evidence, not Phase 3 qualification.

No release was published, artifact installed, or native build executed locally.

## Historical durable-acceptance increment evidence

Implementation: `fe4a45ca7247c501a4427f3f083ef0aacd7e7264`.

- Local non-integration suite: 788 passed, 7 environment-dependent skips,
  35 integration deselections. Local source production pipelines: all six passed.
- [Verification and package run 39082284816](https://github.com/ahouchens/mesh-chat/actions/runs/39082284816):
  795 service tests passed (35 environment/native-only skips); 184 frontend tests
  passed. Windows desktop and signed Android ARM64 package builds passed. The
  release-publication job was skipped.
- [Native run 39082265280](https://github.com/ahouchens/mesh-chat/actions/runs/39082265280):
  Windows/Linux native qualification and Android ARM64 compilation passed.
  Each desktop platform passed 205 service-boundary tests, 14 authority
  tests, 18 relationship tests, 32 document/setup tests, 47 bootstrap/path tests,
  six source pipelines, 20 native unit tests, one cross-language binding test,
  one shipping-dispatcher test, 25 native topology tests and six shipping-native
  production pipelines over real QUIC.
- Linux production network audit: zero external addresses, 1180 loopback
  observations, 48 wildcard binds and 952 sends in
  [artifact 12118933496](https://github.com/ahouchens/mesh-chat/actions/runs/39082265280/artifacts/12118933496).
  The separate legacy topology audit also found zero external addresses.

Package artifacts are compilation evidence only:
[Windows 12119187357](https://github.com/ahouchens/mesh-chat/actions/runs/39082284816/artifacts/12119187357)
and [Android 12119925407](https://github.com/ahouchens/mesh-chat/actions/runs/39082284816/artifacts/12119925407).
No physical result or Phase 3 recovery exit criterion is inferred from them.

The first local pipeline exposed asymmetric bootstrap retirement during admitted
announce confirmation. The fix waits on the admitted carrier independently and
retains the original timeout/assertions. All six subsequent source pipelines
passed. No timeout was increased or assertion weakened.


## Integrated recovery implementation and qualification history

The implementation now includes the protected recovery coordinator, workspace-only
binding v3, encrypted rotated-key channel, signed live/manual updates, renewal,
route-change handling, lifecycle reconciliation, cancellation and renderer controls.
The dedicated production harness uses independent service/native processes and
reopens encrypted profiles with test-only custodian keys. It tests one-sided and
simultaneous process death, unhosted restart, suspend/resume, concurrent replacement,
client/server route changes, blocked targets, lost hints and explicit updates.

Controlled failure injection uses synthetic public candidates translated to
loopback at the native test boundary. Blocking redirects both peers' dial targets
to an unused loopback port; address loss discards both local port preferences so
both peers move while retaining obsolete signed remote address hints. These are
controlled reachability failures, not claims about physical firewalls or routers.
The harness preserves ordinary signed join/application acknowledgment before the
single admission, then requires the same queued message IDs and LXMF endpoint
receipts after recovery. Recovery itself creates no application receipt.

The initial expanded CI run failed before traffic because a harness `name` argument
collided with the workspace payload. The next run exposed a diagnostic attempting
to inspect an activated Phase 2 handle. Both test harness faults were corrected;
production success predicates remain native recovery plus authenticated RNS evidence.
A single 100-second test bound covers the configured native attempt/retry window;
old Phase 2 connectivity is not accepted as completed persistent recovery.

Local full non-integration validation at `5ba2b4460c760d7184776679a691ffcdb8489d45`: 838 passed,
7 environment-dependent skips. Exact final CI results are recorded below.
The earlier successful native increment at `2298996` in
[run 39083931650](https://github.com/ahouchens/mesh-chat/actions/runs/39083931650)
qualifies the provisional native channel only, not these new end-to-end scenarios.

Expanded CI exposed two production lifecycle issues: startup had treated a
formerly connected socket's scheduled refresh as failure backoff, and RNS Links
could retain the retired carrier interface. Startup now schedules fresh ownership
promptly; carrier retirement tears down only its own Links and refreshes the peer
path. Recovery Link policy lasts for the bounded session rather than the old
five-minute setup window. Controlled Linux replacement and both client/server
route-change scenarios passed at `a47aa9c`; blocked-path restoration still failed
in that run. The next increment gives a saved local port bounded bind retries
while QUIC drains and tightens native ownership/arming expiry. These intermediate
results do not replace the required complete final matrix.

## Final recovery implementation verification

Implementation commit: `5ba2b4460c760d7184776679a691ffcdb8489d45`.

- Local non-integration tests: 838 passed, 7 environment-dependent skips and
  45 integration deselections. All six source production pipelines passed.
- [Verification/packages 39087493337](https://github.com/ahouchens/mesh-chat/actions/runs/39087493337):
  845 service tests passed, 45 environment/native-only skips; 190 frontend tests
  passed across 11 files. Windows desktop and signed Android ARM64 package builds
  passed. Release publication was skipped.
- [Native qualification 39087411424](https://github.com/ahouchens/mesh-chat/actions/runs/39087411424):
  Windows and Linux completed successfully; Android ARM64 compilation passed.
  Each desktop platform passed ten production recovery scenarios,
  207 service-boundary tests, 14 authority tests, 65 relationship/recovery tests,
  33 document/setup tests, 47 bootstrap/path tests, six source pipelines,
  24 native unit tests, one cross-language binding test, one shipping-dispatcher
  test, 25 native topology tests and six shipping-native production setup pipelines.
- Linux recovery syscall audit: zero external addresses, 4253 loopback address
  observations, 170 wildcard binds and 3527 sends across the controlled topology
  and all child processes, retained in
  [artifact 12122065171](https://github.com/ahouchens/mesh-chat/actions/runs/39087411424/artifacts/12122065171).
- The separate Linux legacy topology and production setup audits also found zero
  external addresses: [12121727140](https://github.com/ahouchens/mesh-chat/actions/runs/39087411424/artifacts/12121727140)
  (1267 loopback observations, 64 wildcard binds, 1043 sends) and
  [12121687753](https://github.com/ahouchens/mesh-chat/actions/runs/39087411424/artifacts/12121687753)
  (1896 loopback observations, 72 wildcard binds, 1578 sends).

Retained package archives (GitHub artifact SHA-256; compilation evidence only):

| Platform | Artifact | Archive SHA-256 |
| --- | --- | --- |
| Windows | [12120484918](https://github.com/ahouchens/mesh-chat/actions/runs/39087493337/artifacts/12120484918) | `c4b21b289f933fd8733872031d87b875aafa42b008c250a15d5b532eba6537ed` |
| Android ARM64 | [12121627094](https://github.com/ahouchens/mesh-chat/actions/runs/39087493337/artifacts/12121627094) | `a1c3869eb1d6e6bf0f225e2ef01eb73651141c2edacd43dff344a13404a70e1c` |
