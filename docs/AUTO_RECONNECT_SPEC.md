# Automatic reconnect and signaling capabilities

Status: implemented in 0.9.0 for the open-app, foreground case. The renderer
coordinator, signed capabilities, per-contact consent, mailbox capability
tokens, durable replay state, and the per-contact UI are in place. There is no
background daemon, push notification, live session migration, or iOS
background execution; reconnect only runs while the app is open and unlocked.
See [implementation status](#18-implementation-status-090) for what is and is
not covered.

## 1. Purpose

Define how Mesh Chat re-establishes a connection after one or both apps have
been closed, without weakening the trust model or pretending a dead WebRTC
session can be resumed.

## 2. Non-goal: resuming a dead peer connection

A closed process loses:

- the `RTCPeerConnection`;
- ICE username/password and candidate pairs;
- DTLS keys and fingerprints;
- SCTP/DataChannel state;
- the Reticulum bridge attached to that DataChannel.

Reconnect therefore means **negotiating a fresh transport**, not restoring the
old one. No SDP, ICE credential, or DTLS key is persisted for reuse.

## 3. Hard constraint: an independent rendezvous

Automatic reconnect is possible only when both peers have a signaling path that
does **not** depend on the connection being re-established.

Valid rendezvous paths:

1. an existing Reticulum/LXMF path;
2. an explicitly configured community signaling mailbox;
3. an always-on Reticulum access point or TCP endpoint;
4. a live process that never died (desktop tray, Android foreground service).

If none exists, the only correct behavior is a clear manual reconnect. The app
must not spin indefinitely or imply that reconnection is imminent.

This is the central constraint the earlier design missed: WebRTC was introduced
for peers with no Reticulum path, so LXMF alone cannot be the reconnect
fallback.

## 4. Capability discovery

Before a connection dies, both sides must know how to find each other again.
Every signed contact invitation carries a `ConnectionCapabilities` document.

```json
{
  "v": 1,
  "type": "connection_capabilities",
  "peer_destination": "...",
  "device_id": "...",
  "protocol": 1,
  "transports": ["webrtc", "direct_tcp", "access_point", "i2p"],
  "mailbox": {
    "url": "https://...",
    "pair_token": "...",
    "expires_at": 0
  },
  "auto_reconnect": true,
  "allow_direct_ip_disclosure": true,
  "relay_consent_scope": "contact",
  "issued_at": 0,
  "signature": "..."
}
```

Rules:

- `pair_token` is an unguessable, rotating rendezvous capability, not the public
  destination hash.
- Capabilities are signed by the contact identity and verified before storage.
- A changed mailbox URL or token requires a new signed capability document.
- Existing contacts without capabilities default to **auto-reconnect off**.
- Device-level and member-level identities are distinct; reconnect targets a
  device, not only a contact.

## 5. Consent model

Contact approval is not consent to reconnect. Add independent, explicit consent:

```text
allow_auto_reconnect       per contact, default off
allow_direct_ip_disclosure per contact
relay_consent_scope        contact | session | workspace
max_attempts               bounded
quiet_hours                optional
```

Rules:

- Reconnect never creates or approves a contact or workspace member.
- Reconnect never changes workspace authority.
- A blocked, revoked, or removed peer is rejected before creating a peer
  connection.
- The responder must also opt in; otherwise it may receive a request but must
  not auto-answer.
- Relay consent must be re-used only within its declared scope and lifetime.
- TURN credentials are fetched fresh; they are never persisted.

## 6. State machine and glare

Use request/offer/answer, not a bare offer.

```text
IDLE
  -> PROBE_SENT
  -> OFFER_SENT
  -> ANSWER_RECEIVED
  -> CONNECTING
  -> CONNECTED
  -> RETRY_WAIT
  -> STOPPED / MANUAL_REQUIRED
```

Glare control:

- The preferred initiator is the lexicographically lower **device** identity.
- Only the preferred device publishes a signed `reconnect_request`. The other
  side never probes, so simultaneous starts produce one request and one offer.
- The request's recipient creates the WebRTC offer and publishes it; the
  preferred device answers and publishes the answer. This follows the signed
  document bindings in `reconnect.py`, where `create_reconnect_offer` must be
  signed by the request recipient.
- If the preferred device is offline, its request never arrives. The other side
  stays in **Waiting for peer** and does not invent an offer or spin a second
  session; the UI reports peer-offline/manual rather than claiming imminent
  success. There is no initiator takeover in 0.9.0.
- Every attempt has an idempotency key. Retries may repeat a request; replay of
  a completed offer/answer is rejected after acceptance.
- One active attempt per peer/device at a time.

## 7. Protocol documents

All documents are canonical signed JSON, expiring, and bound to both
identities.

### 7.1 `reconnect_request`

```json
{
  "v": 1,
  "type": "webrtc_reconnect_request",
  "from": "...",
  "to": "...",
  "device_id": "...",
  "attempt_id": "...",
  "nonce": "...",
  "expires_at": 0,
  "signature": "..."
}
```

### 7.2 `reconnect_offer`

```json
{
  "v": 1,
  "type": "webrtc_reconnect_offer",
  "from": "...",
  "to": "...",
  "attempt_id": "...",
  "session_id": "...",
  "nonce": "...",
  "expires_at": 0,
  "sdp": "...",
  "dtls_fingerprint": "...",
  "signature": "..."
}
```

### 7.3 `reconnect_answer`

Same binding as the offer, with `type: "webrtc_reconnect_answer"` and the answer
SDP/DTLS fingerprint.

### 7.4 Presence

Presence is optional and separate from connection approval. It must be
capability-addressed, coarse, and TTL-bound. Do not expose public destination
hashes or exact online times to the mailbox operator.

## 8. Supervisor and process ownership

The current `WebRTCSession` lives in renderer memory. A Python/Rust supervisor
cannot keep a WebView peer connection alive after the renderer exits.

Define lifecycle explicitly:

- **Desktop quit:** no automatic reconnect until next launch.
- **Desktop close-to-tray:** keep the bridge and supervisor running.
- **Android foreground service:** persistent notification, reconnect allowed.
- **Android normal suspension/process death:** reconnect only when the app is
  reopened.
- **iOS:** foreground-only reconnect; no persistent socket guarantee.

The supervisor owns profiles, retries, and signaling. The renderer owns the
`RTCPeerConnection`. On startup the supervisor asks the renderer to create a
fresh peer connection after signaling succeeds.

## 9. Mailbox requirements

The existing KV mailbox is a pairing prototype, not a reconnect service.

Required for reconnect:

- Durable Object or WebSocket for low-latency, strongly consistent delivery;
- per-pair rotating capability tokens;
- publish authentication or capability-bound writes;
- per-token and per-IP rate limits;
- document TTL with a configurable reconnect window;
- duplicate/idempotent delivery;
- no plaintext, no contact graph, no long-term presence history;
- no enumeration via public destination hashes;
- operator metadata disclosure in the UI;
- graceful degradation to polling, with visible latency.

KV-only polling may remain a fallback, but not the primary reconnect path.

## 10. Reticulum path handling

After reattaching a WebRTC bridge:

- reannounce the interface;
- wait for a path/ratchet before sending the reconnect document;
- retry `path not found` separately from network timeout;
- do not mark the contact offline because one path attempt failed;
- record whether delivery was opportunistic or propagated.

## 11. Scope and resource limits

Do not reconnect every approved contact.

- Only contacts with `allow_auto_reconnect`.
- Prefer recently active conversations.
- Cap concurrent attempts (suggest 2).
- Exponential backoff with jitter: 1s, 2s, 5s, 15s, 30s, 60s cap.
- Stop after a bounded attempt budget or when the user stops.
- Respect battery/network constraints; suspend when offline.

## 12. Security and replay

- Verify signature, both identities, device binding, expiry, and nonce before
  creating a peer connection.
- Persist a replay cache across restarts.
- Use short expiry plus a small clock-skew grace window; never trust wall-clock
  equality.
- Reject blocked/revoked peers before resource allocation.
- Rate-limit inbound requests per identity and globally.
- Never log SDP, credentials, IPs, or plaintext.
- Relay/mailbox cannot approve contacts or read messages.
- Auto-answer is allowed only with reciprocal consent.

## 13. UX

- Per-contact toggle: **Reconnect automatically**.
- Status card states: `Waiting for peer`, `Reconnecting in 5s`, `Connected`,
  `Peer offline`, `Manual reconnect required`.
- Actions: **Retry now**, **Stop**, **Forget auto-reconnect**.
- Do not open a modal dialog or steal focus on reconnect.
- Do not re-ask for contact approval; ask once for auto-connect consent.
- Distinguish transport failure from trust failure.
- If no rendezvous exists, say so plainly.

## 14. Test plan

Automated:

1. both peers restart, one opens first, second later → connected;
2. both restart simultaneously → exactly one offer, no glare;
3. preferred initiator offline → responder takes over after timeout;
4. only one peer has a mailbox → explicit manual-required state;
5. mailbox KV lag/duplicate delivery → idempotent handling;
6. replay across restart → rejected;
7. clock skew and expired documents → bounded grace;
8. blocked/revoked peer request → rejected before PC creation;
9. relay consent expired → prompt or direct-only attempt;
10. mailbox token rotation and URL change;
11. user disables auto-reconnect mid-attempt;
12. app killed during offer/answer → no stale session accepted;
13. network switch Wi-Fi ↔ cellular → reconnect with backoff;
14. Reticulum path missing then appearing → delayed success;
15. multiple devices for one contact;
16. workspace membership revoked while offline;
17. spam flood against mailbox capability;
18. battery/backoff and attempt cap;
19. no signaling path at all → manual state.

Manual/device:

- Android process death and foreground service;
- desktop tray vs quit;
- iOS foreground/background;
- physical NAT/TURN path;
- relay outage.

## 15. Phases

### Phase A — capabilities and consent

Implemented primitives:

- signed `ConnectionCapabilities` creation and verification;
- transport list, mailbox capability, consent flags, scope, and expiry;
- replay cache and deterministic initiator helper;
- service tests for signing, tampering, wrong signer, invalid mailbox/expiry,
  glare preference, and replay.

Still open:

- attach capabilities to real invitations;
- persist auto-reconnect and IP-disclosure consent per contact/device;
- default existing contacts to off.

### Phase B — Reticulum reconnect

Implemented protocol primitives:

- signed `webrtc_reconnect_request`, `webrtc_reconnect_offer`, and
  `webrtc_reconnect_answer`;
- sender/recipient binding, attempt/session binding, offer-digest binding,
  SDP/DTLS validation, expiry, and signature verification;
- tests for round trip, wrong-offer rejection, tamper/wrong-signer, glare, and
  replay.

Still open:

- supervisor state machine;
- Reticulum delivery and path retry;
- persisted replay cache;
- service commands and UI integration;
- tests 1–3 and 14.

### Phase C — mailbox reconnect

- Durable Object/WebSocket mailbox with rotating tokens and rate limits.
- Presence optional.
- Tests 4–6, 10, 17.

### Phase D — lifecycle

- Desktop tray policy.
- Android foreground service.
- Resume/reconnect on foreground.
- Tests 12, 13, 18, device tests.

### Phase E — UX and cleanup

- Status card, consent toggles, manual-required messaging.
- Remove the current “Reconnect opens the manual dialog” behavior.
- Release evidence.

## 16. Acceptance criteria

1. A previously approved contact with reciprocal auto-reconnect consent and a
   working rendezvous reconnects without manual offer/answer exchange.
2. A peer with no rendezvous is told to reconnect manually; the app does not
   loop or imply success.
3. No reconnect path bypasses contact/workspace authorization.
4. No SDP, ICE credential, DTLS key, or plaintext is persisted or logged.
5. Simultaneous restarts do not create duplicate sessions.
6. Replayed or expired documents are rejected, including after restart.
7. The mailbox cannot enumerate contacts from public destination hashes.
8. Auto-answer requires reciprocal consent; otherwise the request is refused.
9. Transport failure does not change contact/workspace state.
10. Desktop/Android lifecycle behavior matches the documented policy.

## 17. Open decisions

- Whether the default is auto-reconnect on or off for new contacts.
- Maximum mailbox reconnect window and retention.
- Whether presence is offered at all.
- Whether desktop close-to-tray is the default.
- Whether Android foreground service is opt-in or default.
- Whether workspace contacts share capabilities or each device has its own.
- Durable Object provider and abuse budget.

## 18. Implementation status (0.9.0)

Implemented in this release:

- ConnectionCapabilities are attached to contact and workspace invitation
  results when the peer is already known, and are exchanged at invitation
  acceptance / owner approval otherwise.
- Per-contact consent is persisted with **auto-reconnect off by default** and a
  separate direct-IP-disclosure flag. A consent change issues a new signed
  capability; a mailbox change rotates the pair token.
- The service owns profiles, consent, signatures, replay state, mailbox
  publish/fetch, and verification bridges. The renderer owns the
  RTCPeerConnection.
- The renderer coordinator starts only while the unlocked Messenger shell is
  mounted, limits itself to two concurrent attempts, uses 1/2/5/15/30/60-second
  jittered backoff, and stops on consent removal, block/deletion, capability
  rejection, or user cancellation.
- The Cloudflare Worker enforces pair capability tokens (hashed at rest),
  request/offer/answer role and type matching, token rotation, and per-token and
  per-IP rate limits while keeping the tokenless manual onboarding path.
- After a reconnect the bridge is attached through webrtc_attach, which
  reannounces immediately and again after 2 and 6 seconds. The coordinator then
  polls Reticulum path status and distinguishes path_not_ready from

etwork_unavailable instead of declaring messaging ready at channel open.
- The contact panel exposes **Reconnect automatically**, **Allow direct IP
  disclosure**, a status line (Waiting for peer, Reconnecting in Ns,
  Connected, Peer offline, Manual reconnect required), and **Retry now**,
  **Stop**, and **Forget auto-reconnect**. No modal or contact-approval prompt is
  shown.

Explicit limits and non-goals in 0.9.0:

- Reconnect runs only while the app is open and unlocked. Locking the app tears
  the coordinator down. There is no background service, tray keep-alive, push
  notification, iOS background execution, or Android foreground service.
- A pending RTCPeerConnection is never migrated. Every reconnect negotiates a
  fresh transport and new DTLS keys.
- Consent delivery uses the authenticated WebRTC control channel. If the two
  devices are not connected when a toggle changes, the UI says the signed
  settings will be shared on the next live connection; there is no separate
  out-of-band capability message over LXMF.
- If the preferred device is offline, the other side stays in **Waiting for
  peer**; there is no probe takeover.
- Workspace authority and membership are never changed by reconnect. Workspace
  invitations carry capabilities only when a peer destination is supplied;
  otherwise the contact capability remains the transport-level consent object.
- No SDP, ICE credential, DTLS key, or chat plaintext is persisted locally or
  logged. The rendezvous mailbox necessarily holds the signed offer/answer
  envelope, including the ephemeral SDP it carries, for its ten-minute TTL; that
  is signaling state, not chat state, and it is never reused for a later
  connection.
- No physical-device, NAT/TURN, or iOS/Android lifecycle testing was performed
  for this change.
