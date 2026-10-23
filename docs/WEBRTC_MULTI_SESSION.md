# WebRTC multi-session model

Status: implemented in 0.9.21; device-key identity clarified in 0.9.22.

## 1. Problem

The Python service already supports one Reticulum bridge per WebRTC
DataChannel, but the renderer held a single global `activeSession`. Registering
peer B closed peer A's bridge, DataChannel, and RTCPeerConnection. The reconnect
coordinator also returned immediately when any session existed, so it could not
reconnect a second workspace peer while the first peer was connected.

## 2. Session registry

`src/webrtc-session.ts` now keeps a map:

- **Reconnect sessions** are keyed by `ReconnectProfile.id` (a peer/device
  identity), with `contactId` for capability routing.
- **Onboarding sessions** are keyed by `onboarding:<bridgeId>` until a contact
  is approved; the session is then bound to that contact.

Each registry entry owns its own:

- `WebRTCBridge`;
- `RTCDataChannel` and optional control channel;
- `RTCPeerConnection`;
- path, creation time, approval state, and contact binding.

Registering one session never closes another. `getWebRTCSession()` returns the
most recently registered session for legacy UI paths;
`getWebRTCSessionForContact()` and `getWebRTCSessionByKey()` provide targeted
lookup.

## 3. Cleanup

- `closeWebRTCSession(key)` closes exactly one session.
- `closeWebRTCSession()` closes every session, continuing cleanup when one
  bridge close throws.
- `removeWebRTCSession(key)` removes a session that has already closed.
- `attachWebRTCBridge` invokes `onClosed` after detaching the service bridge.
  Reconnect and onboarding wiring use it to remove their registry entry, so a
  dead DataChannel cannot leave a phantom active session.

## 4. Reconnect coordinator

`hasSession` is now profile/contact-aware. The coordinator:

- reconciles all profiles;
- skips only the profiles that already have a live session;
- continues attempting other profiles;
- keeps the two-attempt concurrency cap;
- closes the selected session on per-contact stop/retry;
- leaves independent connected sessions alive when another profile connects.

This preserves the one-attempt-per-peer rule while allowing simultaneous
independent WebRTC transports for different workspace members.

## 5. UI

The WebRTC banner reports the number of live paths. The disconnect action
closes all renderer sessions; per-contact reconnect stop closes only that
profile's session. The registry notifies the app shell so the banner count
updates when a channel closes independently.

## 6. Tests

- Registry test: registering A and B leaves both bridges open; closing A leaves
  B intact; global close cleans all even when one bridge close fails.
- Production wiring test: three `createReconnectDeps().attach()` calls register
  three sessions; `hasSession` is true for all; closing one leaves the other two.
- Coordinator test: a profile with an existing session is skipped while another
  profile still reconnects and attaches.
- Existing onboarding, reconnect, and App tests remain green.

## 7. Limitations

- The service still runs one Reticulum interface per bridge; this change does not
  create a multiplexed interface.
- Reconnect identity is the profile/device ID, not the contact ID. Multiple
  devices for one contact can therefore hold independent reconnect sessions.
  Contact-scoped capability lookup still chooses the newest matching control
  session.
- An onboarding session is keyed by bridge ID until it is bound to a contact, so
  an automatic reconnect profile may start a second session for the same device
  while onboarding is still open. The onboarding session remains independent
  rather than being silently replaced.
- Media calls remain 1:1; this is transport concurrency, not group calling.
- Physical multiple-peer qualification remains in the QA matrix.
