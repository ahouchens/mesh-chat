# Default encrypted signaling mailbox

Status: encrypted Worker/client implementation is present and tested locally and
against the deployed global mailbox at [https://mesh-chat-signal.webtechalex.workers.dev](https://mesh-chat-signal.webtechalex.workers.dev).
The shared service default is configured for fresh/unset settings in rebuilt
clients. Physical-client qualification and distribution of updated desktop/mobile
installers remain pending. This is the authoritative mailbox specification;
older signed-only descriptions are superseded.

## Purpose and automatic recovery

Restore one-to-one and workspace peer connections automatically after network
loss, network changes, app restarts, and staggered returns online. Once paired
and authorized, users must not have to copy another offer or answer solely
because connectivity was lost or time passed offline. Clients automatically
exchange fresh offers/answers; they do not resume dead WebRTC sessions.

The ten-minute document TTL bounds a rendezvous attempt, not the underlying
relationship. Personal and workspace reconnect capabilities persist until
revoked, subject to contact, device, membership, and workspace authority checks.
Remove arbitrary workspace reconnect expiry as a cause of manual recovery.
Independent membership/grant expiry and revocation remain enforced: offline time
does not extend membership or authorize a removed device.

Recovery applies to each eligible workspace peer connection; the mailbox is not
a central workspace server. Both devices must eventually run and have a usable
network path. Existing lifecycle, reconnect, direct-IP, and TURN consent rules
remain enforced. The mailbox does not wake a stopped app, guarantee background
execution, replace TURN, or store chat traffic.

## Default and self-hosted configuration

- Deploy a shared Cloudflare Worker and embed its verified HTTPS base URL in
  the service configuration packaged for desktop and mobile.
- Apply it to fresh or unset settings. Preserve custom URLs, explicit disabled
  settings, and ambiguous legacy disabled choices.
- Provide Default, Custom, and Disabled settings plus a brief metadata
  disclosure. Mailbox configuration grants no contact or workspace authority.
- Keep `MESH_CHAT_DEFAULT_SIGNAL_MAILBOX` as a service runtime override for
  development. Setting it in a packaging shell alone does not embed a URL.
- Custom mailboxes implement the same encrypted protocol. Never silently fall
  back to the public mailbox when a custom endpoint fails.

## Encryption and interface changes

Add `GET` and `PUT /v2/signal/<session>/<request|offer|answer>`. Require a random
access token on every operation. The public deployment rejects legacy plaintext
signaling, and updated clients never downgrade.

Encrypt the complete signed document in the Python service. The outer envelope
contains only version `2` and base64url ciphertext. Reuse the pinned Reticulum
`RNS.Cryptography.Token` implementation with its 64-byte
AES-256-CBC/HMAC-SHA256 key format and library-generated random IVs. Derive
per-session, per-role keys through HKDF-SHA256 from an independent random
32-byte signaling secret, with canonical domain-separated context. Publish
interoperability test vectors with the implementation.

Keep encryption secrets independent of access tokens; never transmit them to
the mailbox. After decryption, retain signature, identity, recipient, device,
role, attempt, expiry, consent, and durable replay checks before allocating a
connection. The Worker validates outer shape and size, not encrypted document
types. The mailbox cannot approve contacts or grant membership.

Introduce version 3 reconnect capabilities containing the encrypted protocol
and signaling secret alongside the access capability. Exchange them over an
authenticated encrypted peer channel and store secrets in the sealed vault.
Support durable workspace reconnect capabilities subject to workspace authority.
Rotate access token, room, and encryption secret together when replacing a
capability.

Version onboarding codes/QR links to include the mailbox address, room, access
token, and encryption secret. Parse locally; send only routing, access token,
and ciphertext to the server. Treat invitations as bearer secrets, excluded
from logs and diagnostics. Service commands create/import pairing contexts;
cryptography stays in the service. Validate custom URLs before networking and
do not forward capabilities through HTTP redirects.

Old peers require an upgrade and new capability exchange over an existing
authenticated connection, or manual pairing once during migration. Report a
specific upgrade/manual-pairing state when encrypted capabilities are missing.
This migration exception must not become normal network-recovery behavior.

The operator cannot read signaling or conversation content but can observe
source IPs, room activity, timing, and ciphertext size. This does not provide
anonymity or protect compromised participant devices. Chat messages,
attachments, and call media never pass through the mailbox.

## Lightweight operation

- One Worker and one Durable Object per active room; bounded HTTP polling,
  without accounts, a directory, a message queue, or an always-running server.
- Three document slots per room, 48 KiB maximum decrypted document and 68 KiB
  wire envelope. Enforce the bound while reading uploads, including requests
  without Content-Length.
- Expire each document ten minutes after publication; reads never extend TTL.
  Schedule cleanup for the earliest outstanding expiry and remove all storage
  and alarms when empty. Missing-room reads and rejected requests must not
  leave persistent state. Bound counters under arbitrary-token floods.
- Strict room budgets: 30 writes and 120 reads per minute. Add Worker-level IP
  limits across rooms before Durable Object access: 120 writes and 480 reads
  per minute. Return and honor Retry-After. Cloudflare edge limits are
  approximate and location-scoped, not strict worldwide quotas.
- Preserve two concurrent reconnect attempts per client, five-second active
  polling, and bounded retry backoff. Stop polling established connections and
  suspend outside the permitted lifecycle. Relevant connectivity/resume events
  restart recovery after an attempt budget has been exhausted.
- Disable application logs/traces containing paths, headers, bodies, secrets,
  IPs, or identities; keep aggregate metrics. Add a protocol-availability health
  endpoint without room details and an incident write-disable control.
- Ten minutes is application-level availability/cleanup, not guaranteed
  physical erasure from provider backups. Historical ciphertext can remain in
  Cloudflare storage recovery; confidentiality depends on device-held secrets.

## Required Cloudflare deployment documentation

Maintain the dedicated [self-hosting guide](../deploy/cloudflare-signal/SELF_HOSTING.md)
and link it prominently from the [mailbox README](../deploy/cloudflare-signal/README.md).
A user must be able to deploy to their own account and configure two clients
without editing app code or using project-operator credentials.

The guide is a release deliverable and must document:

1. Supported Node/Wrangler versions, account/plan prerequisites, pricing links,
   and the difference between signaling and TURN.
2. Copyable commands from the repository root for tests, login, account
   verification, dry-run packaging, and deployment with the shipped config.
3. Worker naming, workers.dev setup, account selection, Durable Object bindings
   and migration history, rate-limit bindings, logging controls, and any server
   secrets. No endpoint encryption keys belong in Cloudflare.
4. Obtaining the actual base URL, configuring each client, enabling applicable
   consent, and exchanging capabilities while an authenticated path exists.
5. Two-client encrypted smoke tests for personal and workspace recovery,
   simultaneous/staggered restarts, and outages exceeding document TTL.
6. Health checks, expected errors, backoff, usage/cost monitoring, upgrades,
   rollback without plaintext downgrade, endpoint migration, and shutdown.
7. Explicit separation of current legacy behavior from planned encrypted
   behavior. Example URLs and unit tests are not proof of a deployed service.

Initially deploy the shared default to workers.dev in the project's existing
Cloudflare account. Record the actual URL and revision, keep deployment
credentials outside app packages, and verify before embedding the URL. Keep
the old endpoint or another authenticated path available during URL migration
so peers can exchange replacement capabilities.

## Validation and release gates

- Crypto: desktop/mobile interoperability, wrong secret, tampering, cross-room
  and cross-role substitution, replay, expiry, and redaction. Captured HTTP and
  stored objects must contain no identities, SDP, ICE credentials, or secrets.
- Worker: authentication, concurrent writes, size boundaries, chunked uploads,
  independent expiry during continued activity, empty-room floods, bounded
  counters, cleanup, and cross-room throttling.
- Settings: packaged fresh installations use the endpoint without environment
  variables; custom/disabled choices survive upgrades; old peers get an
  actionable state without plaintext fallback.
- Devices: encrypted onboarding and personal/workspace recovery on two packaged
  clients, network loss/change, simultaneous/staggered restarts, outages beyond
  ten minutes and the old workspace capability expiry, token rotation, removed
  members/devices, and mailbox outage/recovery. Verify messages and receipts in
  both directions, with no repeated manual exchange for ordinary recovery.
- Capacity: 30-minute staging run with 100 simultaneously reconnecting pairs,
  maximum-size documents and expiry cycles. Require bounded storage, successful
  cleanup, no unexplained failures, and a latency/operations/projected-cost report.
- Documentation: follow the self-hosting guide from a clean checkout in a
  separate Cloudflare deployment using two packaged clients. Verify account
  isolation, commands, bindings, configuration, and recovery instructions.

Before distributing updated installers, complete the physical-client release
matrix. Record unit, load, operator-setup, and physical-device evidence separately.
The Worker is deployed and the default is configured in source; this does not
claim updated installers have been distributed or physical tests have passed.

## Provider references

- [Cloudflare rate-limit behavior](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
- [Storage and recovery](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/)
- [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/)

## Encryption interoperability vector

Wire JSON has exactly `v` (integer 2) and `ciphertext` (unpadded canonical
base64url of Reticulum Token bytes: IV, padded AES-CBC ciphertext, HMAC-SHA256).
HKDF-SHA256 uses the decoded 32-byte secret as input, UTF-8 salt
`mesh-chat:signal:v2`, output length 64, and canonical compact JSON bytes of
`["mesh-chat:signal:v2", session, role]` as context. The first 32 derived bytes
are the HMAC key; the second 32 are the AES-256 key. Verify HMAC before decrypting.

Synthetic test values (the fixed IV is for this vector only; production always
uses a cryptographically random 16-byte IV):

```text
secret: AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8
session: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
role: offer
plaintext: mesh-chat signaling vector
IV hex: 000102030405060708090a0b0c0d0e0f
derived key hex: e03aaf996a667456f0ae9cadc7b6c4ae329c0a42dac8bfb090675b46b1536167e066311ce1999c928efb90753d94b7c703da06ec89b3fcaa9c34102ccb248d6e
ciphertext: AAECAwQFBgcICQoLDA0ODwhO9MYGHUzAqsG7rMbbDMyAEmTI7Ph1Z8Hq8q1euHYuXYcg8UH7RmaGppOoaA_UeKZ-gw2WqFXz2_kDIASwIj0
```

Version 3 connection capabilities retain the signed document's existing fields,
set `lifetime="until_revoked"` and `expires_at=0`, and add `protocol=2` and
`secret` to the mailbox object alongside `url`, `pair_token`, and `expires_at=0`.
They are exchanged only inside authenticated encrypted peer traffic.

Initial pairing codes use `MESHPAIR2.` followed by base64url UTF-8 JSON containing
`v=2`, `url`, `session`, `token`, `secret`, and `expires_at`. They expire after ten
minutes and are kept in service/renderer memory, never unsealed browser storage.
Locking the app clears renderer resume state and stopping the service clears
its pairing contexts.
A code for a different mailbox requires the user to configure that host first;
importing a link does not authorize requests to an arbitrary endpoint.
