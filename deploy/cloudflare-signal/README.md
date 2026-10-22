# Optional Cloudflare signaling mailbox

This Worker removes manual WebRTC offer/answer copy/paste when both devices are
online. It is **not a message store** and does not carry chat traffic.

- `PUT /signal/<session>/request` stores a signed reconnect request for 10 minutes.
- `PUT /signal/<session>/offer` stores a signed offer for 10 minutes.
- `PUT /signal/<session>/answer` stores a signed answer for 10 minutes.
- `GET /signal/<session>/request|offer|answer` returns the signed document.
- Each session is a Durable Object with strongly consistent storage and an
  alarm that deletes expired documents.
- Documents are canonical signed JSON; the Worker checks type and size.

The relay/Worker still cannot approve contacts or read message plaintext.

## Reconnect capabilities

Reconnect documents always require a pair capability token, sent in the
`X-Mesh-Token` header. The first authenticated write pins the SHA-256 hash of
that token in the Durable Object; later reads and writes must present the same
token or they are rejected with `401`. A token rotation is accepted only from
the current token holder:

```text
PUT /signal/<session>/offer
X-Mesh-Token: <current token>
X-Mesh-Token-New: <rotated token>
```

Tokenless rooms remain supported for the manual onboarding offer/answer flow,
but a room that has ever accepted a token is protected for both reads and
writes. Reconnect document types are rejected without a token even in a
tokenless room.

Budgets per 60 seconds: 30 writes and 120 reads per token; 120 writes and 480
reads per client IP. Exhaustion returns `429`. Sessions and counters expire
with the ten-minute alarm.

## Deploy

```bash
npx wrangler deploy
```

No KV namespace is required. The Worker creates one Durable Object per
signaling session. Wrangler creates the SQLite-backed class on first deploy.

The endpoint is:

```text
https://mesh-chat-signal.<subdomain>.workers.dev
```

Add it as the **Signaling mailbox** URL in Mesh Chat settings
(**Settings → WebRTC calls**). The manual QR/copy path remains available when
the mailbox is unset.

## Security

- 128-bit random session IDs.
- Pair capability tokens are unguessable and rotate with new signed
  capabilities; the Worker stores only their SHA-256 hash.
- 10-minute TTL.
- 48 KiB document cap.
- Request/offer/answer role and document-type matching.
- Per-token and per-client-IP rate limits.
- No accounts, messages, contact records, or workspace history.
- Do not log request bodies or token headers.

## Tests

```bash
node --test deploy/cloudflare-signal/worker.test.mjs
```
