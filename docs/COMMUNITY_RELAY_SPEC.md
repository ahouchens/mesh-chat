# Community relay specification

Status: design accepted; implementation blocked on a public default endpoint.
The relay is optional infrastructure, not a Mesh Chat authority.

## 1. Goals

- Give every user an easy Internet fallback when direct/LAN paths fail.
- Let a community operate its own relay, or select another approved relay.
- Keep direct paths preferred.
- Keep relay opt-in and explicitly consented.
- Never let a relay approve contacts, workspace members, or identities.
- Never introduce a central message store.
- Keep conversation and workspace content end-to-end encrypted.
- Survive relay failure without corrupting or erasing local state.

## 2. Roles in scope

Only these roles are in scope for the first release:

1. **TURN** — relays encrypted WebRTC/DTLS packets for an active session.
2. **Reticulum TCP access point** — routes Reticulum/LXMF packets when a
   direct path is unavailable.

Out of scope:

- LXMF propagation/store-and-forward;
- group-call SFU;
- message history storage;
- account or directory service;
- contact/workspace approval.

## 3. Default relay

The app can ship with a built-in **Mesh Chat community relay** descriptor so a
new user can opt in without finding a server. It is:

- visible during onboarding and in Settings;
- **not activated until the user consents**;
- disclosing that the operator sees IP addresses, timing, and encrypted
  traffic;
- replaceable or disableable;
- not used for workspace approval.

The built-in descriptor is distributed as signed static configuration. It
contains no TURN password in the app package; credentials are obtained per
session or per community.

The first implementation uses **Cloudflare TURN** through a credential broker
([`deploy/cloudflare-turn`](../deploy/cloudflare-turn/README.md)):

- the broker holds the TURN Key ID and API token as server-side secrets;
- Mesh Chat requests short-lived `iceServers` from the broker;
- users can override the broker URL or disable it in Settings;
- the broker URL is not a secret.

### Current blocker

A default descriptor needs a real broker endpoint URL and a Reticulum access
point host. No broker URL is configured in this source tree yet. A placeholder
endpoint would be dishonest and would fail for users.

## 4. Relay descriptor

```json
{
  "type": "community_relay",
  "version": 1,
  "relay_id": "mesh-chat-default",
  "name": "Mesh Chat Community Relay",
  "operator": "Mesh Chat project",
  "roles": ["turn", "reticulum_access_point"],
  "endpoints": {
    "turn": "turn:relay.example.org:443?transport=tcp",
    "reticulum": "tcp://relay.example.org:4242"
  },
  "consent": {
    "metadata_visible": true,
    "stores_messages": false
  },
  "created_at": 0,
  "expires_at": 0,
  "signature": "..."
}
```

Rules:

- The descriptor is signed by the operator identity.
- `roles` must be a subset of `turn` and `reticulum_access_point`.
- At least one endpoint is required.
- `stores_messages` must be `false`; a store role is a separate future design.
- The app validates signature, expiry, URL shape, and role/endpoint consistency.
- A descriptor cannot grant membership or approval authority.

## 5. Selection and consent

- Direct/LAN paths are attempted first.
- The user chooses **Use community relay** during onboarding or Settings.
- The consent sheet lists:
  - relay name and operator;
  - roles and endpoints;
  - metadata visibility;
  - no message storage;
  - expiry/removal.
- Consent is per relay, not a global blanket.
- Workspace owners may set a workspace relay policy, but each member still
  consents before traffic uses it.
- No silent downgrade from direct to relay.
- The active path is visible as **Direct** or **Relayed**.

## 6. Multiple relays and failover

- Store an ordered list of relay descriptors: built-in, community, custom.
- A user may disable any relay or add a custom one.
- Try the preferred relay; on failure, try the next consented relay.
- If all fail, report failure and leave contacts/workspaces/messages unchanged.
- Keep local message state authoritative; relay failure is a transport failure,
  not a data deletion event.
- Do not retry indefinitely in the background.

## 7. TURN credentials

- Cloudflare TURN credentials are short-lived `iceServers` returned by a
  credential broker.
- The long-term TURN Key ID and API token stay on the broker.
- Mesh Chat stores the broker URL, not the API token.
- v1 also supports a per-community static credential for self-hosted coturn.
- The built-in relay must not ship one shared global password in the app.
- Credentials are stored in the encrypted service record and released only to
  an active connection.
- No credentials in logs, diagnostics, QR codes, or invitation documents.

## 8. Reticulum access point

- The relay may expose a TCP access point for Reticulum traffic.
- It routes packets; it does not store messages.
- It cannot approve contacts or workspace members.
- The joiner consents to the access point before use.
- Multiple access points may be configured; direct paths remain preferred.
- Access point failure must not alter membership or message state.

## 9. Message flow

| Situation | Path | Relay sees |
|---|---|---|
| Same LAN, direct works | direct | nothing |
| Direct Internet TCP works | direct | nothing |
| WebRTC path needs NAT traversal | TURN | encrypted DTLS, metadata |
| No direct path, access point selected | Reticulum AP | encrypted packets, metadata |
| Relay unavailable | local failure state | nothing |
| Recipient offline | no delivery; no central store | nothing |

The relay does **not** carry every message for every user. It carries traffic
only when that path is selected and active.

## 10. UI

Settings → Connectivity → Relays:

- **Default community relay** — opt in/out, consent details.
- **My community relay** — add/edit/remove.
- **Custom relay** — URL/endpoints and credentials.
- **Test relay** — connect and report TURN/access-point reachability.
- **Active path** — direct/relayed, relay name, failure reason.

The WebRTC onboarding dialog should show the selected relay and a consent
checkbox before falling back to it.

## 11. Deployment and CI

- `deploy/relay` installs TURN + a Reticulum access point on one VPS.
- The release workflow publishes app artifacts only.
- Relay deployment is operator-controlled, not automatic on every release.
- The built-in descriptor is updated only after the endpoint passes a live
  TURN and Reticulum access-point test.
- CI may verify descriptor signatures and endpoint syntax, but must not
  auto-provision public infrastructure.

## 12. Acceptance criteria

1. A fresh install offers the default relay and explains its metadata exposure.
2. Declining the relay leaves the app fully usable on direct/LAN paths.
3. Accepting the relay makes Windows↔Android Internet onboarding work behind
   CGNAT/client isolation.
4. Direct paths are preferred when available.
5. A relay cannot approve a contact or workspace member.
6. Relay failure leaves local contacts, messages, and workspaces unchanged.
7. A custom relay and a second failover relay can be configured.
8. No central message store is created.
9. No plaintext, TURN credential, or SDP appears in diagnostics.
10. Conversation and workspace traffic remain end-to-end encrypted.
