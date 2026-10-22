# Optional Cloudflare signaling mailbox

This Worker removes manual WebRTC offer/answer copy/paste when both devices are
online. It is **not a message store** and does not carry chat traffic.

- `PUT /signal/<session>/offer` stores a signed offer for 10 minutes.
- `PUT /signal/<session>/answer` stores a signed answer for 10 minutes.
- `GET /signal/<session>/offer|answer` returns the signed document.
- Each session is a Durable Object with strongly consistent storage and an
  alarm that deletes expired documents.
- Documents are canonical signed JSON; the Worker checks type and size.

The relay/Worker still cannot approve contacts or read message plaintext.

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
- 10-minute TTL.
- 48 KiB document cap.
- No accounts, messages, contact records, or workspace history.
- Add Cloudflare rate limiting before public use.
- Do not log request bodies.
