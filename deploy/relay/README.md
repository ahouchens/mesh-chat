# Mesh Chat relay (least-friction TURN)

> **Deployment model:** this is a manual VPS installer. The Mesh Chat release
> workflow publishes desktop/Android artifacts only; it does **not** provision
> or host a relay. GitHub-hosted runners are ephemeral and cannot serve TURN.
> Automatic relay deployment would need a chosen VPS/cloud account, a stable
> public IP, and deployment secrets.

One Ubuntu/Debian VPS, no domain, no TLS certificate, one command.

This runs **coturn** on:

- `3478/tcp` and `3478/udp` — standard TURN;
- `443/tcp` and `443/udp` — alternate TURN for restrictive networks;
- `49160–49300/udp` — relay allocations.

Both devices connect **outbound** to the relay, so CGNAT, router client
isolation, and Windows inbound firewall rules no longer block the WebRTC path.

## Requirements

- A VPS with a public IPv4 address.
- Ubuntu 22.04/24.04 or Debian 12.
- Root access.
- About 1 vCPU / 1 GB RAM for small groups.
- Ports `3478`, `443`, and `49160–49300` open in the cloud security group.
- No web server already using TCP/UDP 443.

## Deploy

From a clone of this repository:

```bash
sudo ./deploy/relay/install.sh
```

Or, with only curl:

```bash
curl -fsSL https://raw.githubusercontent.com/ahouchens/mesh-chat/main/deploy/relay/install.sh | sudo bash
```

Or non-interactively:

```bash
sudo PUBLIC_IP=203.0.113.10 ./deploy/relay/install.sh
```

The script:

1. installs Docker if needed;
2. detects the public and private IPv4 addresses;
3. generates a random TURN password;
4. writes `/opt/mesh-chat-relay/.env` with mode `600`;
5. starts coturn with host networking and restarts it automatically;
6. opens the ports in `ufw` if `ufw` is active;
7. prints the TURN URL, username, and password.

## Configure Mesh Chat

On **both** devices:

1. Open **Settings → WebRTC calls**.
2. Set **TURN server** to the printed TCP URL:

   ```text
   turn:203.0.113.10:443?transport=tcp
   ```

3. Enter the printed username and password.
4. Leave relay-only off unless you specifically want to force the relay.

The app now accepts the `?transport=tcp` suffix. Prefer TCP 443 because it
passes through most firewalls and client-isolated networks. Use the UDP URL
only when TCP 443 is unavailable.

## Verify

On the VPS:

```bash
cd /opt/mesh-chat-relay
docker compose ps
docker compose logs --tail 50
```

Successful startup includes `Coturn server started` and a relay listener on
`3478` and `443`. From a device, a WebRTC connection should report
**Relayed** rather than failing at ICE.

## Rotate credentials

From the repository clone:

```bash
sudo TURN_PASSWORD="$(openssl rand -hex 16)" ./deploy/relay/install.sh
```

The installer rewrites `/opt/mesh-chat-relay/.env` and restarts the relay.
Then update both Mesh Chat devices.

## Capacity

Each relayed session uses roughly twice the call bitrate. A 1 TB/month VPS is
enough for many hours of audio and a smaller amount of video. Increase
`RELAY_PORT_MIN`/`RELAY_PORT_MAX` for more concurrent allocations.

## Privacy

TURN relays see connection metadata, IP addresses, and encrypted WebRTC
traffic. Mesh Chat's messages and media remain end-to-end encrypted; the relay
operator cannot read them. Run your own relay if that metadata matters.

## Why no TLS by default

`turns:` needs a DNS name and a publicly trusted certificate. That adds a
domain, ACME client, renewal, and port coordination. Plain TURN over TCP 443
works through most networks and is the least-friction first step.

If your network blocks non-TLS TCP 443, add a domain and a real certificate,
then use `turns:relay.example.org:5349`. Do not use a self-signed certificate
for `turns:`.

## Troubleshooting

- **Container exits immediately** — port 443 is probably occupied. Set
  `TURN_ALT_PORT=8443` and open that port instead.
- **No relay allocations** — check the cloud security group, not just `ufw`.
- **Works on one network but not another** — try the TCP 443 URL; some
  networks block UDP.
- **Credentials rejected** — re-run the installer or inspect
  `/opt/mesh-chat-relay/.env`; `.env` changes require `docker compose up -d`.
- **Public IP changed** — re-run with `PUBLIC_IP=...`.
- **TURN test still fails** — the relay is reachable only if both devices can
  make outbound TCP 443 to it.
