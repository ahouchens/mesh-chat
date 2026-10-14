# Self-hosted remote access point

This example runs a standard Reticulum TCP transport and, only when separately enabled, a standard LXMF propagation node. It has no MeshChat control API, accounts, contact list, workspace list, membership database, TLS terminator, or message-content logger. Clients connect outbound, so client-side inbound ports and router changes are unnecessary.

The example matches the application pins: RNS 1.5.5 and LXMF 1.2.0. Review upstream release notes and stage upgrades before changing either pin.

## Install

On a dedicated current Linux host:

```sh
sudo useradd --system --home /var/lib/meshchat-gateway --create-home --shell /usr/sbin/nologin meshchat-gateway
sudo python3 -m venv /opt/meshchat-gateway/venv
sudo /opt/meshchat-gateway/venv/bin/pip install -r /path/to/MeshChat/service/requirements.lock
sudo install -d -o root -g meshchat-gateway -m 0750 /etc/meshchat-gateway/reticulum /etc/meshchat-gateway/lxmd
sudo install -o root -g meshchat-gateway -m 0640 reticulum/config /etc/meshchat-gateway/reticulum/config
sudo install -o root -g meshchat-gateway -m 0640 lxmd/config /etc/meshchat-gateway/lxmd/config
sudo install -o root -g root -m 0644 meshchat-rnsd.service meshchat-lxmd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meshchat-rnsd.service
```

Enable `meshchat-lxmd.service` only if users want the separately consented offline-delivery option. Obtain its propagation destination from `lxmd --status`; distribute only the destination, never the node identity file.

## Firewall, DNS, and limits

Publish one stable A and/or AAAA name whose every answer is a public address for this host. MeshChat rejects a hostname when any selected answer is non-public. Open only TCP/4242 (or the chosen configured port). Keep SSH or management access on a separate restricted path.

The requirements file uses exact version pins, but it is not a hash-locked supply-chain manifest. Review the packages and obtain them from a trusted, pinned mirror before a production installation.

The following nftables fragment is an illustrative starting point for a dedicated host. Integrate it with the host's existing policy instead of loading a second base chain blindly:

```nft
table inet meshchat_gateway {
  chain input {
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    ct state established,related accept
    tcp dport 4242 ct state new meter meshchat_new {
      ip saddr limit rate 10/minute burst 5 packets
    } accept
    tcp dport 4242 drop
  }
}
```

Use the host firewall or upstream edge to cap concurrent connections per source and globally; exact connection-count syntax and support differ between nftables/kernel releases. A reverse proxy must not replace or translate the Reticulum protocol. Kernel/firewall limits are transport abuse controls only; they do not authenticate users.

On a dedicated network interface, apply an explicit egress bandwidth ceiling as well. For example, the following Linux traffic-control rule limits the whole `eth0` interface to 20 Mbit/s; replace the interface and capacity for the host, and do not apply a whole-interface rule to a shared management interface:

```sh
sudo tc qdisc replace dev eth0 root tbf rate 20mbit burst 256kb latency 100ms
```

Use provider ingress controls or an ingress qdisc for the matching inbound ceiling. Record these host-specific limits in operations documentation because they are intentionally outside the Reticulum protocol and this repository cannot choose a safe universal capacity.

Recommended starting bounds are 32 concurrent connections per source address, 10 new connections per minute with a small burst, a host-wide connection limit sized for the operator's community, and OS-level CPU/memory/file-descriptor limits. Test IPv6 separately; do not publish an AAAA record that is not reachable.

## Operations

- Logs: keep Reticulum/LXMF at the configured low verbosity. Do not enable packet dumps or message-content hooks. Retain only bounded service health and aggregate resource metrics.
- Backups: stop both units and back up `/var/lib/meshchat-gateway` encrypted. The LXMF identity and store are sensitive metadata. The Reticulum transport alone has no MeshChat contact or membership database.
- Recovery: restore the data directory with owner `meshchat-gateway`, permissions `0700`, then start `rnsd` before `lxmd`. Restoring a different LXMF identity changes the propagation destination and requires new explicit client approval.
- Upgrade: snapshot the encrypted data directory, create a new virtual environment from reviewed exact pins, run `rnsd --version` and `lxmd --version`, restart one service at a time, and test two isolated outbound clients before promoting it.
- Key protection: restrict `/var/lib/meshchat-gateway` to the service account, encrypt the host volume, exclude it from broad log/backup collectors, and do not pass keys or profiles through command-line arguments.
- Outage: clients retain durable outboxes, use bounded retry/failover, and can use nearby or signed direct routes when available. The gateway is never treated as delivery proof.

The propagation store is bounded to 512 MiB in the example. Pinned LXMF 1.2.0 also expires propagation messages after its standard 30-day `MESSAGE_EXPIRY`; it can prune earlier when the size ceiling is reached. Automatic propagation peering is disabled. `from_static_only` with no configured `static_peers` prevents peer-to-peer propagation syncs; client deposit/retrieval remains the intended use. Do not patch LXMF retention semantics in this deployment—stage an upstream upgrade if those semantics change.
