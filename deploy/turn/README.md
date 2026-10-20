# Self-hosted TURN service

> **For a one-command deployment, use [`deploy/relay`](../relay/README.md).**
> It installs Docker, generates credentials, opens TCP/UDP 443, and supports
> the `?transport=tcp` URL form. This older directory is the manual coturn
> reference.

Mesh Chat does not operate a public TURN service. Google offers free **STUN**
(`stun:stun.l.google.com:19302`), which is the app default, but Google does not
offer a free public **TURN** relay. This directory provides a coturn deployment
you control.

## Why TURN is needed

STUN can discover a direct UDP path. It cannot relay when both peers are behind
symmetric NAT or carrier CGNAT. TURN relays encrypted DTLS/SRTP and can see
connection metadata, not decrypted media.

## Run

On a host with a public IPv4 address and Docker:

```sh
cd deploy/turn
# Edit turnserver.conf first: replace realm/user/secret and open the firewall.
docker compose up -d
docker compose logs -f coturn
```

Open these ports to the TURN host:

- `3478/tcp` and `3478/udp` — STUN/TURN
- `5349/tcp` and `5349/udp` — TURN over TLS, if configured
- `49160–49200/udp` — relay allocation range

For a quick test, the config uses a static `meshchat` user. For a public or
shared deployment, replace that with coturn's time-limited REST credentials and
enforce quotas. Never expose the example `CHANGE_ME` credential.

## Configure Mesh Chat

On both call participants:

1. **Settings → WebRTC calls**
2. Leave the default Google STUN or set your own STUN server.
3. Set the TURN URL, for example:

   ```text
   turn:turn.example.org:3478
   ```

   or `turns:turn.example.org:5349` with TLS.
4. Set the TURN username and credential.
5. Enable **Relay-only** only when testing forced relay. The call badge should
   show **Relayed via TURN**.

TURN credentials are stored in the encrypted service record and handed only to
an active call. They are not written to snapshots or normal diagnostics.

## Quotas and abuse

The TURN operator owns bandwidth, concurrency, and abuse limits. Mesh Chat
rate-limits outbound calls, but it cannot enforce a TURN server's quota. See
`docs/adr/0022-turn-quota-and-call-abuse-boundary.md`.

## Status

This is a deployment recipe, not a hosted service. No public TURN endpoint or
shared credential is shipped with Mesh Chat.
