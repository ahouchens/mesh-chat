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
Exact increment commits and CI outcomes will be recorded after qualification.
