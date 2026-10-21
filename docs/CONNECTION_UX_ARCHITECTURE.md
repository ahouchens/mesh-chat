# Connection and invitation UX architecture

Status: accepted direction; phased implementation. This spec supersedes the
separate WebRTC-onboarding UX while preserving the C5 transport and all
existing security invariants.

## 1. Problem

Mesh Chat currently exposes two overlapping flows:

1. the normal invitation flow (Invite/Join, connection modes, contact request,
   approval);
2. the WebRTC onboarding flow (create/join offer, paste answer, control-channel
   contact/workspace invitation).

The transport and the trust decision are separate products in the UI. Users
must understand offerer/joiner roles, manual SDP exchange, relay settings, and
then find a second approval prompt. This is technically functional but not a
coherent connection experience.

## 2. Principles

- One entry point: **Connect with someone**.
- Connection is a first-class object with state, transport, path, capabilities,
  and diagnostics.
- Transport and signaling are adapters, not UI flows.
- Direct paths are preferred; relay is a fallback.
- Relay use is consented inline, with metadata disclosure.
- The relay never approves contacts or workspace members.
- Invitations remain signed, single-use, expiring, and identity-bound.
- Contact/workspace approval remains explicit.
- No central message store.
- A failed connection never changes local trust, membership, or messages.

## 3. Domain model

```text
Connection
  id
  peer_identity (when known)
  purpose: contact | workspace
  transport: webrtc | direct_tcp | access_point | i2p | nearby
  signaling: qr | copy | reticulum | mailbox
  state: draft | signaling | connecting | connected | onboarding |
         awaiting_approval | approved | failed | closed
  path: direct | relayed | unknown
  capabilities: messages | calls | workspace
  relay: {id, operator, consented} | null
  created_at / expires_at
  diagnostics
```

The renderer holds the presentation state. Durable trust state remains in the
service/vault. A connection object can outlive the dialog and be shown in a
persistent card.

## 4. Architecture

```text
Connect with someone
        │
        ├── Purpose: contact | workspace
        ├── Role: invite | join
        ├── Transport adapter
        │     ├── nearby/direct TCP
        │     ├── WebRTC + TURN
        │     ├── Reticulum access point
        │     └── I2P
        ├── Signaling adapter
        │     ├── QR / copy / deep link
        │     ├── Reticulum
        │     └── optional community mailbox
        └── Trust
              ├── signed identity proof
              ├── contact request
              ├── workspace join
              └── owner approval
```

Transport adapters expose:

```text
createOffer() / acceptOffer()
connect()
close()
state()
path()
diagnostics()
controlChannel()   # optional authenticated bootstrap channel
```

Signaling adapters expose:

```text
publish(document) / receive(sessionId)
```

Manual QR/copy is a signaling adapter, not a special case in the transport UI.

## 5. UX flow

### Entry

Sidebar: one **Connect** action.

```text
Connect
  ○ Invite someone
  ○ I have an invitation
  ○ Nearby device
  ○ Advanced options
```

### Invite

```text
Who?
  Contact
  Workspace: [optional selector]

How?
  Automatic (if a signaling mailbox exists)
  Same network
  Direct over the Internet
  Community relay (fallback)
  Copy/QR

Review
  Fingerprint
  Relay/operator disclosure
  Expiry

Share / wait
  QR, copy, or automatic delivery
  Progress stepper: Waiting → Connecting → Connected → Approval

Approve
  “Alex wants to connect.”
  Fingerprint
  [Approve] [Decline]
```

The joiner sees the mirrored flow, not a separate WebRTC screen.

### Connection card

```text
Alex
Connected · Relayed via Cloudflare
[Details] [Disconnect]
```

If approval is pending, the card shows **Review contact request** rather than a
separate modal appearing somewhere else.

### Relay consent

Inline, before the transport is used:

```text
Direct connection failed.
Use the community relay?
Operator: ...
Sees: IP addresses, timing, encrypted traffic
Does not see: message plaintext
[Use relay] [Cancel]
```

The answer is stored as explicit relay consent, not inferred from a hidden
settings checkbox.

### Failure recovery

Every failure offers:

- Retry
- Create a fresh link
- Try relay
- Try access point
- Copy diagnostics

Do not dump the user back to a blank dialog.

## 6. Security invariants

- Offer/answer signatures bind Reticulum identity and DTLS fingerprint.
- Session IDs are single-use and expiring.
- The joiner reviews identity before accepting.
- The owner approves contact/workspace membership.
- Relay cannot approve anything.
- Control-channel onboarding messages are signed application documents.
- The control channel is authenticated by the signed offer/answer.
- TURN credentials stay server-side and short-lived.
- No SDP, credentials, IPs, or plaintext in diagnostics.
- Transport failure never mutates trust state.
- QR/copy documents remain canonical and replay-protected.

## 7. Phases

### Phase 1 — inline consent and approval acknowledgement

- Relay consent is shown in the WebRTC connection dialog, not only Settings.
- Joiner receives **approval acknowledged** over the authenticated control
  channel after the owner approves, instead of waiting indefinitely.
- Connection UI distinguishes “request created” from “request delivered.”

### Phase 2 — connection object and card

- Persistent connection object and card.
- Pending-request inbox/badge.
- State stepper and recovery actions.

### Phase 3 — unified wizard

- One Connect flow.
- WebRTC becomes a transport choice inside it.
- Contact/workspace purpose selected before transport.
- Remove the separate WebRTC sidebar flow.

### Phase 4 — signaling adapter

In progress:

- `deploy/cloudflare-signal` implements a 10-minute signed offer/answer
  mailbox using Cloudflare KV (48 KiB cap, random session ID, no messages);
- app-side settings/fetch integration is still pending.

- Optional community mailbox (Cloudflare Worker + Durable Object/KV).
- Short-lived opaque signed envelopes.
- Deep link/QR fallback.
- No central message store.

### Phase 5 — transport fallback

- Direct → TURN → access point fallback with explicit consent.
- Reconnect and resume.

## 8. Acceptance criteria

1. A user can connect without understanding offer/answer terminology.
2. Relay consent is visible in the flow before use.
3. The owner approval is one explicit action.
4. The joiner receives approval acknowledgement without polling or guessing.
5. Closing the connection dialog does not orphan the connection state.
6. Pending requests are visible outside transient modals.
7. A failed transport does not alter contact/workspace trust.
8. No route can bypass signed invitation verification or owner approval.
9. Diagnostics remain free of SDP, credentials, IPs, and plaintext.
10. WebRTC remains optional; direct LAN/TCP paths still work.
