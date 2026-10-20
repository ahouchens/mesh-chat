# Cloudflare TURN credential broker

Cloudflare TURN keys cannot be used directly as WebRTC credentials. A backend
must exchange the TURN Key ID + API token for short-lived ICE servers.

This Worker is that backend. It keeps the API token server-side and returns
only Cloudflare's short-lived `iceServers` response.

## Deploy

```bash
cd deploy/cloudflare-turn
npx wrangler login
npx wrangler secret put TURN_KEY_ID
npx wrangler secret put TURN_KEY_API_TOKEN
npx wrangler deploy
```

Wrangler prints a URL such as:

```text
https://mesh-chat-turn.<your-subdomain>.workers.dev
```

The Mesh Chat broker URL is:

```text
https://mesh-chat-turn.<your-subdomain>.workers.dev/credentials
```

Set that URL in **Mesh Chat → Settings → WebRTC calls → Cloudflare TURN
credential broker**.

## How it works

- `GET /credentials?ttl=3600`
- calls
  `https://rtc.live.cloudflare.com/v1/turn/keys/<TURN_KEY_ID>/credentials/generate-ice-servers`
  with the API token;
- returns `{ "iceServers": [...] }`;
- responses are `Cache-Control: no-store`;
- TTL is clamped to 300–3600 seconds.

Mesh Chat refreshes the broker response before the one-hour credential expiry.

## Global default

To make this broker the default for every user, build the app with:

```bash
export MESH_CHAT_DEFAULT_TURN_BROKER="https://mesh-chat-turn.<your-subdomain>.workers.dev/credentials"
```

The user can still override or disable it in Settings. Do not ship the
Cloudflare TURN API token in the desktop or Android packages.

## Abuse controls

A public broker can mint credentials for anyone who can reach it. Configure
Cloudflare rate limiting / WAF rules for `/credentials` before announcing it
publicly, and set a Cloudflare TURN budget/alerts. The Worker intentionally
does not expose Cloudflare's upstream error body, account data, or the token.

For a community-only broker, put it behind Cloudflare Access or a private
route. The app currently sends no broker authentication header.

## Security

- `TURN_KEY_ID` and `TURN_KEY_API_TOKEN` are Worker secrets.
- The API token is never returned to the app.
- TURN credentials expire; Cloudflare can revoke them.
- TURN relays see IP addresses, timing, and encrypted DTLS/SRTP; not message or
  media plaintext.
