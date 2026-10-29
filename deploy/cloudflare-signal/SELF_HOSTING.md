# Host your own signaling mailbox on Cloudflare

Deploy this directory's Worker to **your Cloudflare account**, then select its
URL in Mesh Chat. Using a custom mailbox does not require rebuilding the app.

**Current status:** encrypted `/v2/signal` and durable personal/workspace
reconnect are implemented. The shared mailbox is deployed at
[https://mesh-chat-signal.webtechalex.workers.dev](https://mesh-chat-signal.webtechalex.workers.dev) and configured as the built-in
default for rebuilt clients. Local and hosted protocol checks have passed; the
physical-device release matrix remains pending.
See the [mailbox specification](../../docs/SIGNAL_MAILBOX_SPEC.md).

## 1. Prerequisites

- A repository checkout and terminal at its root.
- Node.js compatible with Wrangler and npm/npx. Use a supported Node 24
  installation for these instructions; check `node --version` if tests fail.
- A Cloudflare account permitted to deploy Workers and Durable Objects.
  SQLite-backed Durable Objects are available on Free and Paid plans with
  different quotas. Review current [Durable Object pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/)
  and [Worker pricing](https://developers.cloudflare.com/workers/platform/pricing/).
- Two compatible Mesh Chat clients for reconnect verification.

No purchased domain, KV namespace, separate database server, TURN API key, or
client encryption key is needed to deploy the mailbox. TURN is a separate
traffic relay; a working mailbox alone does not guarantee NAT traversal.

## 2. Test and authenticate

Run each command from the repository root. They work in PowerShell when
Node/npm are on PATH.

```sh
node --test deploy/cloudflare-signal/worker.test.mjs
npx wrangler@4.154.0 --version
npx wrangler@4.154.0 login
npx wrangler@4.154.0 whoami
```

Login opens browser authorization. Confirm `whoami` shows the intended account.
For multiple accounts, set `account_id` in your deployment copy of
`deploy/cloudflare-signal/wrangler.toml`. An account ID is not an API token.

Interactive deployment uses browser login. For CI, supply a target-account API
token with the required Worker/Durable Object deployment permissions through
the CI secret store as `CLOUDFLARE_API_TOKEN`. Never commit it or package it in
the client. See [Wrangler login](https://developers.cloudflare.com/workers/wrangler/commands/general/#login)
and [configuration](https://developers.cloudflare.com/workers/wrangler/configuration/).

## 3. Configure and deploy

Review `deploy/cloudflare-signal/wrangler.toml`:

- Choose a Worker `name` unique within your account, such as
  `my-mesh-chat-signal`. Deploying the same name updates that Worker.
- Keep `main = "worker.js"` and `workers_dev = true`.
- Preserve the `SIGNALS` binding, `SignalRoom` class, and migration entries.
  Wrangler provisions the SQLite-backed namespace. Do not invent namespace IDs
  or remove/reuse migration tags when upgrading.
- Preserve `WRITE_LIMITER` and `READ_LIMITER`: 120 writes / 480 reads per minute
  per source IP at the edge. Their namespace IDs must be unique among unrelated
  rate-limit bindings in your account; change `1001`/`1002` if already used.
- Keep `[observability] enabled = false`. Do not add request, token, or body
  logging. The Worker needs no encryption secret: those belong on the clients.
- Keep `WRITES_ENABLED = "true"` for normal operation. Set it to `"false"` and
  redeploy for incident write suspension; health and reads stay available.

```sh
npx wrangler@4.154.0 deploy --dry-run --config deploy/cloudflare-signal/wrangler.toml
npx wrangler@4.154.0 deploy --config deploy/cloudflare-signal/wrangler.toml
```

If the account has no workers.dev subdomain, follow Cloudflare's setup prompt
or configure it under Workers & Pages. Record the actual HTTPS URL and version
printed by Wrangler. The URL will resemble this placeholder:

```text
https://my-mesh-chat-signal.<your-subdomain>.workers.dev
```

Use the printed base URL with no `/signal`, `/v2/signal`, room, token, or
`/credentials` suffix. A custom domain is optional; configure it as a Worker
domain/route, not just a DNS record pointing to an example address.

## 4. Configure clients

1. On each client, open **Settings → Advanced → WebRTC calls** and set
   **Signaling mailbox** to your deployed HTTPS base URL.
2. Keep an authenticated connection open while the clients exchange updated
   signed reconnect capabilities. If no connection path remains, manually pair
   once to bootstrap the exchange.
3. Confirm personal automatic reconnect is enabled. New personal contacts
   enable it by default; saved disabled choices remain disabled.
4. For workspaces, enable the separate workspace reconnect consent and verify
   both devices are active authorized members. Changing a mailbox URL alone
   does not enable workspace reconnect or grant membership.
5. Confirm both sides report ready before disconnecting them for testing.

Normal self-hosting uses the settings UI. `MESH_CHAT_DEFAULT_SIGNAL_MAILBOX` is
a service-startup default for unsaved settings; setting it only in a packaging
shell does not embed it in an installer. No global app default needs changing.

## 5. Verify recovery

Use test identities and synthetic data. Test personal and workspace peer
connections separately:

1. Send a message and receive its delivery receipt in each direction.
2. Interrupt connectivity on one device, restore it, and check automatic
   renegotiation without another manual offer/answer exchange.
3. Close and reopen both apps; repeat with one reopening later.
4. Leave a peer offline beyond the ten-minute document TTL and check recovery
   plus messages/receipts again.

Also test beyond the old workspace reconnect expiry and verify that legacy
`/signal/...` submissions return 410. A GET to `<base-url>/health` must return
`{"protocol":2,"writes_enabled":true}`. The bare base URL still returns 404.
Health and unit tests do not prove device recovery; record the device results
separately. Do not put tokens in diagnostic URLs or submit real signaling to
public request inspectors.

For synthetic HTTP verification from this checkout, set
`MESH_CHAT_TEST_SIGNAL_URL` to the owned staging HTTPS base URL, then run:

```sh
python -m pytest service/tests/test_signal_mailbox_http.py -q
python scripts/signal_mailbox_load.py --url https://YOUR-WORKER.workers.dev --minutes 30 --pairs 100
```

Use the repository virtual environment with its service requirements installed.
In PowerShell, set the test variable with
`$env:MESH_CHAT_TEST_SIGNAL_URL = 'https://YOUR-WORKER.workers.dev'`.
On POSIX shells use `export MESH_CHAT_TEST_SIGNAL_URL='https://YOUR-WORKER.workers.dev'`.
Replace the placeholder with your actual deployment. The load test sends
synthetic maximum-size ciphertext, stays below single-IP request budgets, and
stops writes during the final ten minutes to check expiry. Its aggregate report
is `dist/reports/signal-mailbox-load.json`. Review provider usage and cost as well.
This test does not send chat traffic or allocate WebRTC connections.

The [README](README.md#verification) also explains how to run these tests against
Cloudflare's local runtime without deploying.

## 6. Troubleshooting and operation

| Symptom | Check |
| --- | --- |
| Wrangler account/auth error | Run `whoami`; select the correct account and verify permissions. |
| Binding/migration error | Match code and config releases; preserve migrations and the `SIGNALS` binding. |
| Base URL returns `404` | Expected: there is no homepage. Use `/health` for protocol availability. |
| Missing document | The peer may not have published or TTL elapsed; retry a fresh attempt. |
| `401`/`403` | Check matching capabilities and recent URL/token changes; do not bypass authentication. |
| `429` | Honor Retry-After. Edge IP limits span rooms; room limits also apply. |
| `410` | Upgrade both clients; plaintext signaling is not supported. |
| `503` | Check write-disable and required limiter bindings in the deployed config. |
| `413` | Document exceeds the release's limit; do not remove the bound. |
| Manual reconnect required | Check settings, reciprocal consent, exchanged capabilities, client versions, and membership. |
| Signaling works but connection fails | Check network/firewall reachability and separately consented TURN. |

Monitor aggregate requests, errors, storage, and billing in Cloudflare. Review
usage notifications and quotas; rate limits are not a guaranteed spending cap.
Do not enable logging of bodies, token headers, full paths, or identities.
The edge limits are approximate and scoped to Cloudflare locations; they are
not an exact global quota or spending cap. Validate usage against your account's
plan before a public rollout.

TTL is application expiry, not immediate erasure from provider recovery history.
See [Cloudflare storage and recovery](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/).

## 7. Upgrade, migrate, or shut down

- Record source revision, Wrangler version, account, Worker name, URL, and
  deployment version after testing. Keep credentials out of that record.
- Test upgrades in a separately named staging Worker and namespace. Check
  protocol/client compatibility and run the recovery checks, then deploy to
  production with the release's matching migration history.
- Use Cloudflare deployment/version controls for rollback only after checking
  migration compatibility. Never roll an encrypted mailbox back to plaintext.
- When changing URLs, keep the old endpoint or another authenticated path
  working until peers exchange new capabilities. No directory redirects offline
  peers to a moved mailbox automatically.
- Before deleting a Worker or namespace, configure another mailbox or disable
  mailbox reconnect in clients. Existing live transports can continue; future
  recovery through the removed endpoint will fail. This does not delete chat
  history or revoke contact/workspace membership.

Before a public release, follow this guide from a clean checkout in a separate
Cloudflare deployment with two packaged clients. Record the deployed URL/version,
health response, client versions, reconnect results, and hosting usage. Local
runtime success alone does not satisfy that release gate.
