# DSH handoff prompt — finish automatic reconnect

You are continuing implementation in the Mesh Chat repository.

## Repository state

- Primary repo: `C:\Users\webte\Desktop\MeshProject\mesh-chat`
- Mirror repo: `C:\Users\webte\Documents\ChatGPT\Mesh P2P connected chat`
- Branch: `main`
- Current HEAD: `84a40f0` (`Accept reconnect documents in signaling mailbox`)
- Latest published release: `0.8.2`
- Do not reset, clear, or migrate app data.

Read these first:

1. `docs/AUTO_RECONNECT_SPEC.md`
2. `docs/CONNECTION_UX_ARCHITECTURE.md`
3. `src/WebRTCOnboarding.tsx`
4. `src/webrtc-session.ts`
5. `src/App.tsx` (Connect entry, connection card, approval handling)
6. `service/src/mesh_chat/reconnect.py`
7. `service/src/mesh_chat/webrtc_onboarding.py`
8. `service/src/mesh_chat/signal_mailbox.py`
9. `service/src/mesh_chat/service.py` (`signal_publish`, `signal_fetch`, settings)
10. `deploy/cloudflare-signal/worker.js`
11. `deploy/cloudflare-signal/wrangler.toml`
12. `TESTING.md`

## Product goal

Implement **automatic reconnect without a background daemon**.

Acceptance target:

> After both users have connected once, both apps are closed, and both are later opened with the Cloudflare signaling mailbox configured, Mesh Chat re-establishes a fresh WebRTC connection automatically, with no manual offer/answer copy/paste. Reconnect happens only when the app is open/unlocked. There is no claim of receiving or connecting while the app is closed.

Not in scope:

- background service/daemon;
- iOS background execution;
- push notifications;
- live session migration;
- central chat message storage;
- auto-approving new contacts/workspaces.

## Mandatory security invariants

- Invitations and reconnect documents remain signed, canonical, expiring, and replay-protected.
- Reconnect never creates or approves a contact, workspace member, or device.
- Reconnect never changes workspace authority.
- Auto-reconnect requires explicit, reciprocal consent.
- Direct IP disclosure is a separate consent from contact approval.
- Relay/mailbox operators cannot approve contacts or read plaintext.
- No SDP, ICE credential, DTLS key, or chat plaintext is persisted or logged.
- Blocked/revoked peers are rejected before creating an `RTCPeerConnection`.
- TURN credentials are fetched fresh and never persisted.
- A transport failure never mutates trust or membership state.

## What is already implemented

### Existing manual connection flow

- React WebRTC dialog with signed offer/answer, ICE, TURN consent, DataChannels.
- `WebRTCSession` in `src/webrtc-session.ts`:
  - `bridge`, `channel`, `pc`, `control`, `path`, `createdAt`,
    `approvalPending`.
- Reticulum bridge attach and announce after connection.
- Connection card with Direct/Relayed, pending approval, Review request,
  Diagnostics, Reconnect.
- Unified Connect entry; legacy sidebar New chat removed.
- Contact/workspace invitation and owner approval.

### Existing mailbox pairing

- `deploy/cloudflare-signal` Worker + Durable Object per session.
- Endpoint: `/signal/<session>/<role>` where role is `offer` or `answer`.
- 10-minute expiry via DO alarm, 48 KiB cap.
- Accepts onboarding and reconnect document types.
- Service setting `signal_mailbox_url` in call settings.
- Service commands `signal_publish` and `signal_fetch`.
- Rust allowlist includes both commands.
- Short-code/QR/deep-link pairing:
  - `meshchat://pair/<code>`;
  - `src/WebRTCOnboarding.tsx`;
  - `src/pairing-resume.ts` persists a joiner code for 10 minutes.

### Existing reconnect primitives

`service/src/mesh_chat/reconnect.py` currently implements:

- `create_connection_capabilities`
- `verify_connection_capabilities`
- `create_reconnect_request`
- `verify_reconnect_request`
- `create_reconnect_offer`
- `verify_reconnect_offer`
- `create_reconnect_answer`
- `verify_reconnect_answer`
- `preferred_initiator(local_device, remote_device)`
- `ReconnectReplayCache`

Documents bind sender, recipient, device ID, attempt ID, nonce, session ID,
SDP/fingerprint, offer digest, expiry, and signer identity.

Six reconnect tests pass in `service/tests/test_reconnect.py`.

## What is missing

### 1. Mailbox capability authentication and rate limiting

The Durable Object currently authorizes only by knowing the session string.
That is not sufficient for reconnect.

Implement:

- `pair_token` from `ConnectionCapabilities`;
- `X-Mesh-Token` request header (or equivalent);
- DO stores a SHA-256 token hash on first write and rejects mismatches;
- both read and write require the token;
- per-token and per-IP rate limits;
- optional compatibility path for existing onboarding sessions without a
  token, but reconnect must always use a token;
- tests for wrong/missing token and token rotation.

### 2. Attach capabilities to invitations

`create_invitation` and workspace invitation creation must return a signed
`ConnectionCapabilities` document or an equivalent field.

Persist per contact/device:

- device ID;
- peer destination;
- transports;
- mailbox URL;
- mailbox pair token;
- auto-reconnect consent;
- direct-IP-disclosure consent;
- relay-consent scope;
- issued/expiry.

Rules:

- existing contacts default auto-reconnect off;
- both sides must opt in;
- capability changes require a new signed document;
- tokens rotate;
- do not store plaintext tokens in logs.

### 3. Service API

Add commands, with Rust allowlist updates and tests:

```text
reconnect_profiles                 list saved reconnect profiles
reconnect_consent_set              per contact/device allow + IP disclosure
reconnect_capabilities_store       store verified capability document
reconnect_capabilities_get         fetch capability for contact/device
reconnect_replay_check             persist replay key and return accepted
reconnect_status                   current supervisor state
reconnect_start                    start one attempt
reconnect_stop                     cancel attempts
verify_reconnect_request           service verification bridge for UI
verify_reconnect_offer
verify_reconnect_answer
```

The frontend should not reimplement signature verification.

### 4. Reconnect coordinator

Because the WebView owns `RTCPeerConnection`, implement the coordinator in the
renderer (React/TypeScript), not the Python service. The service owns trust,
capabilities, mailbox HTTP, signatures, replay, and persistence.

Coordinator behavior:

- start after the app is unlocked and a profile exists;
- load contacts with reciprocal auto-reconnect consent;
- limit concurrent attempts (suggest 2);
- choose initiator with `preferred_initiator(local_device, remote_device)`;
- initiator:
  1. create signed request;
  2. publish `offer` role (or a request role if the Worker supports it);
  3. poll/fetch for answer;
  4. verify answer;
  5. create fresh `RTCPeerConnection`;
  6. set remote answer;
  7. attach bridge, reannounce, wait for path;
- responder:
  1. poll for request/offer;
  2. verify sender is an approved, non-revoked contact;
  3. create answer;
  4. publish;
  5. attach bridge.
- Retry with jittered backoff: 1s, 2s, 5s, 15s, 30s, 60s cap.
- Stop on cancel, block/revocation, consent removal, or expiry.
- Do not open a modal or steal focus.
- If no mailbox is configured: state `manual_required`.

Reuse WebRTC setup helpers from `WebRTCOnboarding.tsx`, but factor them into a
shared module rather than duplicating ICE/diagnostics logic.

### 5. Renderer/service handshake

If the coordinator is renderer-based, it still needs:

- service commands for capabilities/consent/replay/verification;
- mailbox publish/fetch with pair token;
- an event or command result containing the verified offer/answer;
- no raw SDP in logs.

Do not add a Python supervisor that pretends to own a WebView peer connection.

### 6. Mailbox token support in service

Extend `signal_publish` and `signal_fetch` with an optional token, sent as the
header expected by the Worker. Keep existing manual pairing working.

### 7. UI

Per contact/device:

- **Reconnect automatically** toggle;
- **Allow direct IP disclosure** toggle;
- status:
  - Waiting for peer
  - Reconnecting in Ns
  - Connected
  - Peer offline
  - Manual reconnect required
- actions: Retry now, Stop, Forget auto-reconnect.

No contact approval prompt on reconnect. No modal.

### 8. Reticulum after reconnect

After the new DataChannel opens:

- attach bridge;
- call `network.reannounce()`;
- delayed reannounces at 2s and 6s;
- wait for path before declaring messaging ready;
- distinguish path-not-found from timeout;
- verify `approvalPending` remains false for transport reconnect.

### 9. Tests

Add unit/integration coverage:

Service:

- capability persistence and default-off behavior;
- wrong/missing mailbox token;
- replay across restart;
- expired/tampered request/offer/answer;
- blocked/revoked contact rejection;
- consent combinations;
- deterministic initiator both orders.

Frontend:

- initiator publishes request/offer and accepts answer with fake mailbox;
- responder verifies request and publishes answer;
- both-start glare produces one session;
- no mailbox → manual-required;
- stop/cancel;
- status transitions;
- no modal focus theft.

Integration:

- two service instances with a fake/mock mailbox;
- app A starts first, B later;
- both start simultaneously;
- replay after restart;
- network switch;
- no mailbox.

Known unrelated failures: the full service suite has six pre-existing
`test_direct_setup_pipeline.py` workspace-admission failures, reproducible on
the 0.8.0 baseline. Do not claim the suite is green unless those are fixed.

### 10. Release

- bump version (suggest 0.9.0);
- update `README.md` and `TESTING.md`;
- run TypeScript, frontend tests, targeted service tests, build;
- tag and publish through CI;
- record artifact hashes;
- do not claim device testing that was not performed.

## Current test baseline

- `node node_modules/typescript/bin/tsc -b`
- `node scripts/run-frontend-tests.mjs` → **242 passed**
- `node scripts/run-frontend-build.mjs`
- Service reconnect tests: **6 passed**
- Full service suite: **1048 passed, 46 skipped, 6 pre-existing failures**
- Set a repo-local temp dir if pytest cannot write to `%TEMP%`:
  `TEMP=<repo>\.pytest-temp TMP=<repo>\.pytest-temp`

## Pitfalls

- Do not use PowerShell `Set-Content` on TS/TSX/MD; it can corrupt UTF-8.
  Use the edit/write tools or Python UTF-8.
- Do not persist SDP/ICE/DTLS state.
- Do not auto-connect every approved contact; only reciprocal opt-ins.
- Do not auto-answer without reciprocal consent.
- Do not treat a valid signature as authorization; check contact/workspace state.
- TURN alone cannot signal; the mailbox is the rendezvous.
- If no mailbox and no Reticulum path, auto reconnect is impossible; show
  manual-required.
- No background daemon: reconnect only while the app is open/unlocked.
- The app may be locked at startup; coordinator must wait for unlock.

## Definition of done

1. Both apps restart with mailbox configured and reciprocal consent.
2. App A starts, B starts later; both connect automatically.
3. Both start simultaneously; one offer, no glare.
4. No manual offer/answer copy/paste.
5. No new contact/workspace approval.
6. Replayed/expired/tampered documents rejected.
7. Blocked/revoked peer rejected before peer connection creation.
8. No mailbox → explicit manual-required state.
9. No SDP/credential/plaintext persistence or logs.
10. Tests, CI, and release evidence exist.

Work until those are true. Do not stop at another protocol stub.
