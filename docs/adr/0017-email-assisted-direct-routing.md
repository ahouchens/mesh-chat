# ADR 0017: Email-assisted direct routing and role reversal

## Context

ADR 0016 lets an inviter expose a short-lived authenticated Reticulum TCP listener, but some home, mobile, and enterprise topologies prevent that device from accepting inbound traffic. The invitee may nevertheless have a usable public IPv6 path, router mapping, or manual forward. Sharing an invitation through email is common, but Mesh Chat must not require an email provider integration, rendezvous server, managed relay, account, or new cryptographic transport.

## Decision

Add an optional, additive v4 invitation envelope and two signed out-of-band document families. Email and other sharing applications remain opaque carriers.

The v4 envelope contains the complete unchanged v1 personal/workspace invitation, its exact SHA-256 digest, purpose, a random 32-byte reply challenge, dates, signer destination, and signature. It may contain one ordinary inviter-owned `participant_direct` access document; inability to create that access document does not prevent v4 creation.

An invitee can return a signed v1 connection response containing the invitation digest/challenge/signer binding, responder public identity and derived destination, and a responder-owned `participant_callback` access document. The inviter accepts a response only for an active v4 record it created. Consumption and encrypted pending-scope persistence are atomic and precede DNS resolution, endpoint probing, or Reticulum interface activation.

The response changes reachability only. The inviter must still send the existing signed contact request or workspace join, and the existing approval, authority, nonce, replay, identity, ratchet, and membership checks remain authoritative. Only receipt of that valid application request promotes the temporary route to a contact or workspace-device scope.

Approved peers can later exchange signed v1 route updates. Each update is bound to an exact contact/workspace-device scope, local audience destination, issuer identity/destination, monotonic generation, fresh callback access, dates, and signature. The receiver requires the issuer to remain authorized in that exact scope, rejects stale/replayed generations, atomically persists the generation and replacement before activation, and retires only the superseded scoped route. A still-live Reticulum path carries the same signed document automatically as a bounded LXMF control payload; otherwise the user exports it.

## Security and privacy boundaries

- Reticulum IFAC authentication, identity signatures, routing, and LXMF recipient-ratchet requirements are unchanged. No custom cryptographic primitive or message transport is introduced.
- A response or route update cannot create or verify a Contact, admit/reinstate a workspace device, change authority, bypass blocking, or act as a receipt.
- Exact field sets, identity/destination ownership, canonical signatures, invitation digest/challenge binding, audience/scope binding, expiry, size, depth, node count, and monotonic generation fail closed.
- Raw endpoint candidates, IFAC tokens, canonical documents, and identities remain in encrypted service records. Renderer state exposes only bounded status and presentation metadata.
- Preview is local and side-effect free. Import persistence occurs before network side effects. Replay and partial-crash recovery therefore converge on durable service state.
- The feature adds no email OAuth/API access, analytics, telemetry, public-IP discovery, STUN/TURN, rendezvous, signaling, managed gateway, relay, account, or key directory.

## Lifecycle and bounds

Connection responses are at most 40 KiB; route updates are at most 24 KiB. All new JSON documents have exact schemas, maximum depth six, and at most 192 nodes. Callback access uses the existing one-to-three safe public endpoint limit and 24-hour maximum, shortened to the listener mapping/pinhole lease and invitation expiry. Existing participant-host concurrency, bounded retry, renewal, route-change invalidation, shutdown, revocation, and scope-release cleanup apply.

On successful contact request or workspace join receipt, the consumed pending route is promoted to the durable approved scope. Before an active hosted credential expires, a usable authenticated path can carry a fresh route update automatically. Refresh and restart prefer the previous router-assigned external port, but publish success only after a real listener/mapping is restored and sign the actual returned endpoint. Contact deletion, workspace close, device removal, or membership loss releases only the affected route, host, and accepted-generation record. A fresh out-of-band route update can restore reachability without changing trust. If neither endpoint can host and no explicitly approved access point is configured, the direct flow honestly remains unavailable.

## Compatibility

v1 nearby invitations, v2 Remote Connection Profile envelopes, and v3 participant-hosted invitations remain byte-for-byte unchanged and accepted. v4 uses `MESHCHAT4`/`MESHWORKSPACE4`; replies use `MESHCONNECT1`; reconnect updates use `MESHROUTE1`. Desktop and Android accept equivalent bounded text, raw-file, and deep-link inputs. Older clients reject the new prefixes without weakening old formats.

## Consequences

The participant best able to accept inbound traffic can host the bootstrap path, allowing the original inviter to initiate the Reticulum connection after an out-of-band reply. This improves direct reachability without inserting a third party. It requires a second sharing round trip when role reversal is needed, the hosting participant to remain online through the ordinary approval flow, careful listener cleanup, and honest UI when no direct topology exists.
