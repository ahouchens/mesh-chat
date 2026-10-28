# Encrypted Cloudflare signaling mailbox

**[Deploy your own mailbox](SELF_HOSTING.md)** — account setup, deployment,
client settings, verification, troubleshooting, upgrades, and shutdown.

This Worker exchanges encrypted connection setup documents so approved personal
contacts and authorized workspace peers can automatically renegotiate after a
network loss or restart. It does not carry chat messages, attachments, or media.
Both devices must run and have a usable direct or consented relay path.

The global mailbox is deployed at [https://mesh-chat-signal.webtechalex.workers.dev](https://mesh-chat-signal.webtechalex.workers.dev).
Its verified URL is the built-in default for fresh or unset service settings.
Saved custom URLs and explicit disabled choices remain unchanged.
See the [deployment and validation record](VALIDATION.md) for the version, hosted
checks, and remaining physical-device release qualification. Rebuilt clients are
required to receive this default; existing installed binaries are not updated
by deploying the Worker.

## Protocol

| Operation | Result |
| --- | --- |
| GET /health | `{"protocol":2,"writes_enabled":true}` (or false during maintenance) |
| PUT /v2/signal/<session>/request | Store encrypted reconnect request |
| PUT /v2/signal/<session>/offer | Store encrypted onboarding/reconnect offer |
| PUT /v2/signal/<session>/answer | Store encrypted onboarding/reconnect answer |
| GET /v2/signal/<session>/<role> | Return the encrypted envelope, or 404 if absent/expired |

Every signaling request needs an `X-Mesh-Token` capability. The first write pins
its SHA-256 hash; subsequent reads/writes require the same token. No tokenless
onboarding is supported. Legacy `/signal/...` requests return 410. Rotation
creates a new room, access token, and encryption secret through a new signed
peer capability; there is no in-place HTTP token rotation.

Bodies contain only `{"v":2,"ciphertext":"<base64url>"}`. The Python service
encrypts complete signed documents using the pinned Reticulum authenticated
encryption implementation and session/role-separated keys. Access tokens and
encryption secrets are independent: Cloudflare never receives the latter.
Peers decrypt and verify signatures, identities, consent, membership, attempt
bindings, expiry, and durable replay state. The Worker cannot grant trust.

Ten-minute expiry applies to each document, not the relationship. Version 3
personal and workspace reconnect capabilities remain valid until revoked,
subject to current contact/device/membership authorization. Existing v1/v2 peers
must update and exchange new capabilities over an authenticated path, or pair
once to migrate. Ordinary subsequent outages need no manual offer/answer.

## Bounds and privacy

- Three document slots per room; 48 KiB decrypted document / 68 KiB wire envelope.
- Independent ten-minute expiries and alarms; reads never extend them.
- Two fixed counters, updated without rewriting ciphertext on each poll.
- 30 writes / 120 reads per room per minute.
- Edge limits across rooms: 120 writes / 480 reads per source IP per minute.
  [Cloudflare limits](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
  are approximate and location-scoped, not worldwide accounting or a billing cap.
- 429 responses include Retry-After. Missing limiter bindings fail closed.
- Empty-room reads and rejected capabilities leave no persistent counters.
- Application logging/observability is disabled in the supplied configuration.
  Do not enable body/header/path logging or upload real invitation codes to logs.

The host still sees source IPs, room activity, timing, and ciphertext size.
Expiry is application availability/cleanup, not guaranteed erasure from
[provider recovery history](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/).
There is no claim of anonymity or protection against compromised endpoints.

## Quick deployment

Use Node 24 and run from the repository root:

```sh
node --test deploy/cloudflare-signal/worker.test.mjs
npx wrangler@4.154.0 login
npx wrangler@4.154.0 whoami
npx wrangler@4.154.0 deploy --dry-run --config deploy/cloudflare-signal/wrangler.toml
npx wrangler@4.154.0 deploy --config deploy/cloudflare-signal/wrangler.toml
```

Review the account and Worker name first. Preserve bindings and migration
history. Use the actual base URL Wrangler prints in both clients under
**Settings → Advanced → WebRTC calls → Signaling mailbox**. Keep an authenticated
connection open to exchange updated settings and enable the applicable
personal/workspace reconnect consent.

For incident write suspension, set `WRITES_ENABLED = "false"` in the config and
redeploy. GET and health remain available; writes return 503 with Retry-After.
Never roll back an encrypted service to plaintext.

## Verification

See [the validation record](VALIDATION.md) for completed checks and pending release gates.

See the [self-hosting guide](SELF_HOSTING.md) for real two-device tests and
[the specification](../../docs/SIGNAL_MAILBOX_SPEC.md) for release gates.

Local runtime smoke tests (two terminals, repository root):

```sh
npx wrangler@4.154.0 dev --local --ip 127.0.0.1 --port 8789 --config deploy/cloudflare-signal/wrangler.toml
```

```powershell
$env:MESH_CHAT_TEST_SIGNAL_URL = 'http://127.0.0.1:8789'
.venv/Scripts/python.exe -m pytest service/tests/test_signal_mailbox_http.py -q
.venv/Scripts/python.exe scripts/signal_mailbox_load.py --url http://127.0.0.1:8789 --minutes 30 --pairs 100
```

The opt-in HTTP test uses synthetic encrypted onboarding and personal/workspace
handshakes. The load script keeps 100 rooms active with maximum-size documents,
then stops writes for the final ten minutes to verify expiry. Reports contain
aggregate counts and latency, never credentials. Local tests do not establish
physical-device behavior, provider latency, or hosting cost.

After rebuilding the Windows service, verify the embedded default and live
encrypted exchange with two synthetic packaged profiles:

```powershell
.venv/Scripts/python.exe scripts/signal_mailbox_packaged_smoke.py --binary src-tauri/binaries/mesh-chat-service-x86_64-pc-windows-msvc.exe --expected-default https://mesh-chat-signal.webtechalex.workers.dev
```

This needs Windows protected storage and uses synthetic SDP; it does not
replace the physical-device test matrix.