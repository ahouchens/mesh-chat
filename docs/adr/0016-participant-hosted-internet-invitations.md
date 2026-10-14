# ADR 0016: Participant-hosted Internet invitations

Status: accepted for desktop and Android

## Context

Reticulum can route securely across whatever interfaces are available, but it does not create an Internet underlay between two arbitrary devices behind unrelated NATs. A shared Reticulum transport node solves that reachability problem because both clients dial outward, but it introduces an operator into the network path. Mesh Chat needs a default flow that matches the common mental model: share an invitation through email or another tool, keep the inviter online, and let the invitee connect directly when the participant's device and router permit it.

No server-free technique can guarantee this for every network. Public IPv6 may be firewalled; UPnP, NAT-PMP, or PCP may be absent; and CGNAT, symmetric NAT, enterprise policy, or mobile carrier policy may prevent inbound reachability. Without a rendezvous or external probe, the inviter also cannot prove the path from the invitee's network before the invitee tries it.

## Decision

The default Internet invitation attempts participant-hosted reachability only after an explicit prepare action. The inviter remains online. The service starts the real invitation-scoped TCP listener before advertising a port, reads the operating system's selected default routes, and finds public candidates using only local information:

1. directly assigned public IPv4 and stable globally routed IPv6 addresses on active Internet routes;
2. route-aware PCP with bounded retransmission and a cryptographically random nonce;
3. interface-bound UPnP IGD, including IGD2 any-port mapping and IPv6 firewall pinholes; then
4. route-aware NAT-PMP as a legacy fallback.

Mesh Chat does not contact STUN, TURN, rendezvous, signaling, account, public-IP discovery, or managed gateway services. Sharing applications carry invitation bytes only and gain no Mesh Chat role.

Every host session receives a new Reticulum IFAC network name/passphrase. A signed v3 envelope binds the complete existing v1 personal/workspace invitation, exact public candidates, credential, dates, purpose, and inviter/authority destination. The corresponding listener is separate from same-LAN fallback, is not a Reticulum transport or propagation node, and permits off-LAN attachment only through that invitation credential. Runtime interface configuration and encrypted vault records remain service-owned; the renderer receives sanitized state only.

The recipient's acceptance persists the verified access document under the exact contact or workspace scope before outbound interfaces are activated. There is no separate third-party-operator consent because the operator is the already verified inviter/authority shown in the invitation. All existing contact approval, workspace admission, signature, nonce, ratchet, replay, authorization, and receipt rules remain unchanged.

Connection Doctor reports only allowlisted phase/result/reason/action fields. It never returns raw exceptions, network addresses, router-control URLs, executable paths, credentials, or firewall internals to the renderer. An RFC1918 router WAN is described as upstream or double NAT; `100.64.0.0/10` is described as likely provider/shared NAT. A locally created mapping is `prepared_unverified`, never proof of external reachability.

Direct setup failure is explicit and never silently selects another entity. The user can choose manual participant-hosted TCP forwarding, nearby/private-network v1, or deliberately select an approved Remote Connection Profile v2. Manual setup retains the same authenticated listener, validates a participant-supplied public endpoint, requests no router credentials, and warns that its router rule cannot be removed automatically. Remote-profile operator disclosure and recipient consent remain mandatory. The existing advanced **Help route messages** and LXMF propagation controls stay separate from invitation hosting.

## Lifecycle and bounds

- At most eight participant host sessions may exist on one device.
- An access document contains one to three public endpoints and lasts at most 24 hours. IPv4 mapping expiry is limited to the router lease minus a safety margin; the default requested lease is two hours.
- Imported and hosted interface definitions are runtime-only settings and are not written into generic preferences.
- Host records contain mapping and IPv6-pinhole cleanup data. Active automatic leases renew before expiry. Stop, invitation revocation where applicable, expiry reconciliation, route/address change, router epoch reset, failure, and clean application shutdown detach listeners and request mapping or pinhole removal. A crash can leave a router lease until it expires.
- A Windows user may explicitly approve an elevated temporary inbound rule limited to the exact running sidecar executable, TCP listener port, and active firewall profile. The rule is removed with the host session; failure or declined elevation is reported instead of treated as success.
- Manual forwarding uses a stable temporary listener port and never stores router-administrator credentials. The person must remove the manually created router rule.
- Recipient access records are reference-scoped and expire automatically. Raw endpoints and IFAC credentials do not appear in ordinary snapshots, logs, notifications, or route labels.
- The listener has bounded connection/rate behavior. Possession of the short-lived invitation can permit a connection attempt but cannot satisfy Mesh Chat identity, authority, nonce, ratchet, message-signature, or membership checks.

## Consequences

The desktop-on-home-Wi-Fi to phone-on-carrier case works without a third party when the desktop has usable public reachability and its host/router firewalls permit the listener. The phone normally initiates an outbound connection, so its carrier NAT is not the inbound side of this topology. Direct reachability cannot be promised behind restrictive NAT/firewall topologies. The UI says the path is prepared—not independently verified—and changes to recipient connected only after the invitation-bound listener observes an authenticated client.

Invitation hosting is only reachability bootstrap to the inviter. It does not automatically relay arbitrary traffic or give every member of a multi-person workspace all-to-all Internet reachability. Those devices still need direct paths or an explicitly chosen Reticulum routing/access topology.

The design uses pinned Reticulum interface authentication and existing identity signatures; it adds no custom cryptographic primitive. It does add sensitive bearer material to v3 invitations, local-router control traffic, temporary inbound listeners, and cleanup state, all addressed in the threat model.

## Compatibility

v1 nearby/direct-private-network and v2 approved-access-point invitations remain accepted. v3 is additive and supported by desktop and Android native ingress, text, QR, deep links, and `.meshchat-invite` files. iOS remains outside this increment.
