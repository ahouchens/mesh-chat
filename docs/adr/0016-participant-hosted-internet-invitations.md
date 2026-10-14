# ADR 0016: Participant-hosted Internet invitations

Status: accepted for desktop and Android

## Context

Reticulum can route securely across whatever interfaces are available, but it does not create an Internet underlay between two arbitrary devices behind unrelated NATs. A shared Reticulum transport node solves that reachability problem because both clients dial outward, but it introduces an operator into the network path. Mesh Chat needs a default flow that matches the common mental model: share an invitation through email or another tool, keep the inviter online, and let the invitee connect directly when the participant's device and router permit it.

No server-free technique can guarantee this for every network. Public IPv6 may be firewalled; UPnP, NAT-PMP, or PCP may be absent; and CGNAT, symmetric NAT, enterprise policy, or mobile carrier policy may prevent inbound reachability. Without a rendezvous or external probe, the inviter also cannot prove the path from the invitee's network before the invitee tries it.

## Decision

The default Internet invitation attempts participant-hosted reachability. The inviter remains online. The service creates a fresh temporary TCP listener and finds public candidates using only local information:

1. globally routed IPv6 addresses reported by local interfaces;
2. a short local-router port mapping through UPnP IGD;
3. NAT-PMP; then
4. PCP.

Mesh Chat does not contact STUN, TURN, rendezvous, signaling, account, public-IP discovery, or managed gateway services. Sharing applications carry invitation bytes only and gain no Mesh Chat role.

Every host session receives a new Reticulum IFAC network name/passphrase. A signed v3 envelope binds the complete existing v1 personal/workspace invitation, exact public candidates, credential, dates, purpose, and inviter/authority destination. The corresponding listener is separate from same-LAN fallback, is not a Reticulum transport or propagation node, and permits off-LAN attachment only through that invitation credential. Runtime interface configuration and encrypted vault records remain service-owned; the renderer receives sanitized state only.

The recipient's acceptance persists the verified access document under the exact contact or workspace scope before outbound interfaces are activated. There is no separate third-party-operator consent because the operator is the already verified inviter/authority shown in the invitation. All existing contact approval, workspace admission, signature, nonce, ratchet, replay, authorization, and receipt rules remain unchanged.

Direct setup failure is explicit and never silently selects another entity. The user can choose nearby/private-network v1 or deliberately select an approved Remote Connection Profile v2. Remote-profile operator disclosure and recipient consent remain mandatory. The existing advanced **Help route messages** and LXMF propagation controls stay separate from invitation hosting.

## Lifecycle and bounds

- At most eight participant host sessions may exist on one device.
- An access document contains one to three public endpoints and lasts at most 24 hours. IPv4 mapping expiry is limited to the router lease minus a safety margin; the default requested lease is two hours.
- Imported and hosted interface definitions are runtime-only settings and are not written into generic preferences.
- Host records contain mapping cleanup data. Stop, invitation revocation where applicable, expiry reconciliation, and clean application shutdown detach listeners and request mapping removal. A crash can leave a router lease until it expires.
- Recipient access records are reference-scoped and expire automatically. Raw endpoints and IFAC credentials do not appear in ordinary snapshots, logs, notifications, or route labels.
- The listener has bounded connection/rate behavior. Possession of the short-lived invitation can permit a connection attempt but cannot satisfy Mesh Chat identity, authority, nonce, ratchet, message-signature, or membership checks.

## Consequences

The desktop-on-home-Wi-Fi to phone-on-carrier case works without a third party when the desktop has usable public IPv6 or its router grants a reachable mapping and the host firewall permits the listener. It cannot be promised behind restrictive NAT/firewall topologies. The UI says the path is prepared—not independently verified—and asks the inviter to keep Mesh Chat open while the recipient connects.

Invitation hosting is only reachability bootstrap to the inviter. It does not automatically relay arbitrary traffic or give every member of a multi-person workspace all-to-all Internet reachability. Those devices still need direct paths or an explicitly chosen Reticulum routing/access topology.

The design uses pinned Reticulum interface authentication and existing identity signatures; it adds no custom cryptographic primitive. It does add sensitive bearer material to v3 invitations, local-router control traffic, temporary inbound listeners, and cleanup state, all addressed in the threat model.

## Compatibility

v1 nearby/direct-private-network and v2 approved-access-point invitations remain accepted. v3 is additive and supported by desktop and Android native ingress, text, QR, deep links, and `.meshchat-invite` files. iOS remains outside this increment.
