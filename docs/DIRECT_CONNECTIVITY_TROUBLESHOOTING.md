# Direct Internet connection troubleshooting

Mesh Chat is direct-first: a new Internet invitation asks the sender's own device to host a short-lived, authenticated connection. There is no Mesh Chat account, rendezvous service, public-IP lookup, STUN/TURN service, managed relay, or silent transport operator. Email, Slack, Teams, QR, clipboard, and invitation files carry only the signed invitation.

The sender must keep Mesh Chat open and online while the invitation is active and while the recipient connects and is approved. `Prepared — waiting for recipient verification` means that a listener and candidate path were created locally. It is not proof that the path is reachable from the Internet. Only an authenticated recipient connection changes the state to `Recipient connected`.

## Start with Connection Doctor

Choose **Check direct Internet connection** before preparing an invitation. The checklist uses only local route, interface, router-protocol, listener, and firewall information. Its copy action omits public and local addresses, invitation credentials, router URLs, executable paths, and raw exception text.

Typical results and actions:

| Result | Meaning | Action |
| --- | --- | --- |
| No default route | This device has no selected Internet route | Connect to the Internet and retry |
| Global IPv6 available | The active Internet interface has a stable, non-deprecated global address | Prepare the invitation; allow its temporary TCP port through host/router firewalls if needed |
| PCP, UPnP, or NAT-PMP available | The selected default router appears to support a temporary mapping | Prepare the invitation; it remains unverified until the recipient connects |
| Upstream or double NAT detected | The router reports an RFC1918 WAN address | Bridge/passthrough the upstream modem/router or create a matching upstream rule |
| Provider/shared NAT likely | The router reports `100.64.0.0/10` shared address space | Ask the provider for reachable service, or use an explicitly approved participant-operated access point |
| Mapping blocked or unsupported | Router policy denied the request or does not support the protocol | Use manual TCP forwarding if the upstream path is controllable |
| Windows Firewall needs permission | The listener may need a narrow inbound rule | Use **Allow in Windows Firewall** and approve the operating-system elevation prompt |

Retry after changing a router, interface, VPN, firewall, or Windows network profile. A router reboot, mapping epoch reset, or public-address change invalidates the old prepared invitation; create and share a new one.

## How automatic paths work

Mesh Chat reads the operating system's active default routes. It does not guess a gateway from the first or last subnet address. UPnP discovery is sent from each selected active IPv4 interface, which prevents an unrelated VPN, Hyper-V, APIPA, or disconnected adapter from becoming the accidental discovery path.

Automatic IPv4 mapping is attempted in this order:

1. PCP, using a cryptographically random request nonce and bounded retransmission.
2. UPnP IGD, preferring IGD2 `AddAnyPortMapping` and retaining safe fault categories.
3. NAT-PMP as the legacy fallback, also with bounded retransmission.

A directly assigned public IPv4 needs no router mapping. Native IPv6 candidates come only from the active IPv6 default route and exclude link-local, ULA, deprecated, short-lived, or unstable candidates. When an IGD2 router advertises IPv6 firewall control, Mesh Chat requests, renews, and removes a narrow TCP pinhole. The host firewall can still block either address family.

Mappings and IPv6 pinholes are renewed while the invitation remains active and are removed on stop, revocation, expiry, failure, or clean shutdown. A crash can leave a short router lease until the router expires it.

## Windows Firewall

The explicit firewall action requests elevation from Windows and creates a temporary inbound rule for:

- the exact running Mesh Chat service executable;
- TCP only;
- the exact temporary listener port; and
- the currently active Windows Firewall profile or profiles.

Mesh Chat removes the temporary rule when hosting stops. It does not rely on a rule for an older executable path. If Windows cannot safely determine the active profile or elevation is declined, no success is reported. You can instead open **Windows Security → Firewall & network protection → Advanced settings → Inbound Rules** and create the same narrow program/port/profile rule, then remove it after the invitation ends.

## Manual TCP forwarding

Use **Set up manual port forwarding** only when automatic mapping is unavailable and you control the router path.

1. Mesh Chat starts an invitation-scoped authenticated listener and shows the local device name and stable temporary TCP port.
2. Reserve the device's DHCP lease if the router could later assign it a different local address.
3. In the router, forward one TCP external port to the shown device and temporary port.
4. Enter the router-reported public IPv4, a global IPv6 address, or a hostname you control, plus the external TCP port.
5. Create and share the signed manual v3 invitation, and keep Mesh Chat open.

Mesh Chat rejects private, shared, reserved, loopback, link-local, multicast, documentation, benchmarking, and otherwise unsafe endpoints. It never requests or stores router-administrator credentials. It cannot remove the router rule you created, so remove that rule yourself when the invitation is no longer needed.

If the router's WAN address is private, an upstream modem/router still needs a matching rule or bridge/passthrough mode. If the WAN address is in `100.64.0.0/10`, a manual rule on the home router normally cannot control the provider's upstream shared NAT. These signals are local evidence only; Mesh Chat does not claim that a topology is certainly carrier-grade or symmetric NAT without external observation.

## Why the recipient phone's carrier NAT is usually irrelevant

In the common desktop-on-home-Wi-Fi to phone-on-cellular flow, the phone initiates an outbound TCP connection to the sender. Mobile carrier NAT usually allows that outbound connection and its replies. The difficult side is the sender accepting an inbound connection through its router and firewalls. Carrier policy can still filter destinations or suspend the app, so this is not a guarantee.

## When direct hosting cannot work

No-server connectivity cannot be guaranteed when an ISP or enterprise firewall blocks inbound traffic, a provider/shared NAT cannot be configured, IPv6 inbound policy cannot be opened, or the router offers no usable mapping and cannot be manually configured. Nearby mode is explicit and works only on the same network; it will not work over cellular.

The Internet fallback is an explicitly named, approved, participant-operated Reticulum access point. Selecting it is a separate per-invitation choice, and the recipient separately consents. Its operator can observe connection metadata but cannot decrypt or forge valid Mesh Chat content. Mesh Chat never silently selects it.

## UPnP versus a manual rule

UPnP/PCP/NAT-PMP create a narrow, expiring mapping that Mesh Chat can renew and request to remove. Enabling a router-wide automatic mapping feature also lets other local software request mappings, so keep devices patched and do not enable it on an untrusted LAN solely for Mesh Chat.

A manual forward avoids automatic router control but is easy to leave behind, may break after a DHCP change, and remains exposed until you remove it. In both cases the invitation-specific IFAC credential and existing Mesh Chat identity/signature checks remain required; neither mapping method makes Internet exposure risk-free.
