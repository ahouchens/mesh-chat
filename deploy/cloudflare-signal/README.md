# Optional Cloudflare signaling mailbox

This Worker removes manual WebRTC offer/answer copy/paste when both devices are
online. It is **not a message store** and does not carry chat traffic.

- `PUT /signal/<session>/offer` stores a signed offer for 10 minutes.
- `PUT /signal/<session>/answer` stores a signed answer for 10 minutes.
- `GET /signal/<session>/offer|answer` returns the signed document.
- Documents are canonical signed JSON; the Worker only checks the session ID
  and size.
- KV TTL deletes both entries automatically.

The relay/Worker still cannot approve contacts or read message plaintext.

## Deploy

```bash
npx wrangler kv namespace create SIGNALS
# paste the returned id into wrangler.toml
npx wrangler deploy
```

The endpoint is:

```text
https://mesh-chat-signal.<subdomain>.workers.dev
```

Add it as the **signaling mailbox URL** in Mesh Chat settings when the UI
lands. Until then this is infrastructure only; the manual QR/copy path remains
the default.

## Security

- 128-bit random session IDs.
- 10-minute TTL.
- 48 KiB document cap.
- No accounts, messages, contact records, or workspace history.
- Add Cloudflare rate limiting before public use.
- Do not log request bodies.
