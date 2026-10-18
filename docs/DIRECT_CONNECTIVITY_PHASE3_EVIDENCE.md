# Phase 3 persistent relationship recovery evidence

Status: implementation in progress; Phase 3 is **not complete**.
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

| Required capability | Current evidence / remaining work |
| --- | --- |
| Encrypted exact workspace/device relationship | Implemented in production acceptance; current membership and identity rechecked transactionally |
| Accepted generations, validity, successful route, retry and cleanup state | First three implemented; retry and cleanup state remain open |
| Fresh sockets/keys and RNS-based reauthentication after restart | Open; existing native TLS still needs an exchanged certificate pin |
| Signed updates over surviving paths and explicit no-route recovery | Atomic acceptance groundwork only; recovery protocol/controller/UI remain open |
| Same-socket UDP lease renewal | Open; existing preparation remains bounded by its original lease |
| Startup/resume, cancellation, fair bounded retries | Open for durable relationships |
| Authenticate replacements before retiring old paths | Open; this increment only preserves acceptance and authenticated historical evidence |
| Supported QUIC migration with reconnect fallback | Open |
| Honest per-peer recovery/liveness states | Open; no new connected/recovered claim is exposed |
| Preserve membership, queued messages and receipts during recovery | Existing setup pipeline retained; actual recovery scenarios remain open |

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

## Exact-commit automated evidence

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
