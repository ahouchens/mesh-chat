# Physical QA scenarios — 0.9.15

Status: **required, not yet executed.** CI, unit tests, renderer tests, and
simulated network tests do not satisfy these scenarios. No physical-device pass is
claimed for the features below.

This document lists the scenarios that still require real hardware and real
networks. It covers workspace connectivity phases 1–7, owner-offline admission,
workspace calls, WebRTC workspace invitations, Android behavior, packaging, and
the security/privacy checks that cannot be proven from CI alone.

Related documents:

- [Workspace connectivity spec](WORKSPACE_CONNECTIVITY_SPEC.md)
- [WebRTC call physical test plan](WEBRTC_PHYSICAL_TEST_PLAN.md)
- [Phase 2 Windows and Android device evidence](DIRECT_CONNECTIVITY_PHASE2_DEVICE_TEST.md)
- [Android parity](ANDROID_PARITY.md)

## 1. Test bed

Use published artifacts from the same version and record every hash before
testing.

| Role | Device | Network | Purpose |
|---|---|---|---|
| A | Windows x64 | Network 1 (home/office NAT) | Owner authority, grant issuer, call peer |
| B | Windows x64 or Android arm64 | Network 2 (different NAT/cellular) | Admin, member, call peer, joiner |
| C | Android arm64 | Network 3 (cellular/hotspot) | Joiner, helper, call peer |
| T | Optional TURN relay | Public | Relayed reconnect and call path |
| M | Optional signaling mailbox | Public | Automatic reconnect coordination |
| I | Optional I2P access point | Public | I2P invitation/access path |

Minimum for the full matrix: **two Windows machines and one Android device**, with
at least two independent networks. Some scenarios require all three devices
online; others require one device deliberately offline.

Record:

- app version and platform;
- Windows installer and Android APK SHA-256;
- Windows/Android OS version and device model;
- network type and whether CGNAT, IPv6, UDP, or TCP inbound is available;
- TURN/mailbox/I2P configuration and whether credentials are test-only;
- start/end timestamps and test workspace name;
- pass/fail and a short sanitized observation.

Do **not** record private keys, full invitation/join documents, TURN credentials,
IP addresses, message plaintext, or full logs containing them. Keep test
workspaces disposable.

## 2. Common preparation

1. Install the exact 0.9.15 Windows installer and Android APK. On Android confirm
   the APK is the debug-signed test artifact, not an upgrade identity.
2. Back up or use a clean test profile. Do not run destructive removal/fork tests
   against a real workspace.
3. Keep apps open and unlocked unless a scenario explicitly tests suspension,
   restart, or lock.
4. Confirm the workspace has an owner authority device and at least one active
   member device before starting.
5. Confirm both devices can exchange a normal workspace message and receipt before
   testing connectivity features. If baseline delivery fails, stop and record a
   baseline failure.
6. Use a fresh test workspace for admission and reconnect scenarios so previous
   grants, manifests, or mailbox state cannot contaminate the result.

## 3. Scenario index

| ID | Area | Devices | Priority |
|---|---|---|---|
| QA-01 | Baseline workspace join and bidirectional receipt | A + B | P0 |
| QA-02 | Three-device workspace fan-out | A + B + C | P0 |
| QA-03 | Connectivity panel and explicit path request | A + B | P1 |
| QA-04 | Access recommendation delivery and consent | A + B | P1 |
| QA-05 | Workspace reconnect consent off | A + B | P0 |
| QA-06 | Automatic reconnect after network change | A + B + M | P0 |
| QA-07 | One-sided/absent reconnect consent | A + B + M | P1 |
| QA-08 | Reconnect after restart, suspension, and membership removal | A + B + M | P0 |
| QA-09 | Reconnect with TURN-only path | A + B + M + T | P0 |
| QA-10 | Helper opt-in and helper-disabled behavior | A + B + C | P0 |
| QA-11 | One-hop helper relay between changed endpoints | A + B + C | P0 |
| QA-12 | Helper confidentiality and one-hop stop | A + B + C | P0 |
| QA-13 | Grant creation and admin acceptance | A + B | P0 |
| QA-14 | Owner-offline admin admission with v2 manifest | A + B + C | P0 |
| QA-15 | Owner return, normalization, and revocation | A + B + C | P0 |
| QA-16 | Grant expiry, use cap, and revocation blocking | A + B + C | P0 |
| QA-17 | Pre-v2/old-client behavior | A + old client | P1 |
| QA-18 | Signed-history fork handling (lab only) | A + B | P2 |
| QA-19 | Workspace DM audio/video call | A + B | P0 |
| QA-20 | Workspace call network change and TURN | A + B + T | P0 |
| QA-21 | Workspace call Android background/lock/permissions | A + Android | P0 |
| QA-22 | Workspace call decline/rate-limit/end states | A + B | P1 |
| QA-23 | WebRTC workspace invitation transfer | A + B | P0 |
| QA-24 | WebRTC invitation validation and no-trust-bypass | A + B | P0 |
| QA-25 | WebRTC invitation unavailable/expired/tampered | A + B | P1 |
| QA-26 | Android notifications and background suspension | Android + A | P0 |
| QA-27 | Android install, launch, and clean removal | Android | P1 |
| QA-28 | Windows install, launch, upgrade, and removal | Windows A | P1 |
| QA-29 | Privacy: no contact creation, no plaintext, no recording | A + B | P0 |
| QA-30 | Full three-device end-to-end pass | A + B + C + T + M | P0 |

Priorities: **P0 = release gate**, **P1 = required for qualification**, **P2 =
lab-only/security-hardening exercise**.

## 4. Scenario details

### QA-01 — Baseline workspace join and bidirectional receipt

1. On A create a workspace and a normal invitation.
2. On B import the invitation, review it, choose a display name, and submit the
   signed join.
3. On A verify the signed request shows the expected member/device/fingerprint and
   approve it.
4. On both devices verify `#general` loads, the member appears once, and the
   workspace state is active.
5. Send a message A→B and B→A. Verify both content and a recipient receipt in each
   direction.

**Pass:** both devices show active membership and bidirectional content/receipt.
**Fail:** any membership mismatch, missing receipt, duplicate member, or active
state without a verified join.

### QA-02 — Three-device workspace fan-out

1. Add B and C to the same workspace using separate invitations and owner
   approval.
2. Send a channel message from A. Verify B and C receive it and each receipt is
   represented separately.
3. Send from C. Verify A and B receive it.
4. Remove C from the workspace on A while B is online. Verify C becomes read-only
   or removed and cannot send new messages; verify B and A no longer accept C's
   new workspace traffic.

**Pass:** all active devices converge on the same manifest and no removed device
can send. **Fail:** stale member still active, missing receipt, or a removed
device accepted.

### QA-03 — Connectivity panel and explicit path request

1. Open **People → Connectivity** on A and B.
2. Verify each active remote device is listed once with a safe route label and a
   state that does not claim presence.
3. Trigger an explicit path request from A to B.
4. Record whether the path becomes reachable and whether a subsequent message is
   delivered.

**Pass:** the panel reports only current active devices and no local device, and a
failed path is reported as unavailable/queued rather than delivered. **Fail:**
presence claimed from delivery evidence, local device counted as reachable, or
membership/trust changed.

### QA-04 — Access recommendation delivery and consent

1. On A create a workspace access recommendation for B.
2. Verify B receives a preview but no profile is attached before B explicitly
   consents.
3. Apply it on B and verify no Personal contact is created and no workspace
   authority/membership changes.
4. Verify a stale, tampered, or expired recommendation is rejected.

**Pass:** delivery, preview, consent, and scope are all explicit. **Fail:** profile
attached automatically, contact created, or stale document accepted.

### QA-05 — Workspace reconnect consent off

1. Keep automatic reconnect off on both A and B.
2. Change B's network so the old route becomes unusable.
3. Wait beyond the reconnect interval and send a workspace message.

**Pass:** the app reports no automatic reconnect / consent required and queued
work remains explicit; no hidden connection is created. **Fail:** reconnect occurs
without both-side consent or a contact is created.

### QA-06 — Automatic reconnect after network change

1. Enable automatic reconnect on both A and B, with a working signaling mailbox.
2. Keep both apps open and unlocked.
3. Move B from Wi-Fi to cellular (or change NAT) so the old path fails.
4. Wait for the coordinator and send a message in each direction.

**Pass:** a fresh direct or TURN-relayed path is established without a new
contact, invitation, or manual approval; messages and receipts flow. **Fail:**
stuck "reconnecting", no path but delivered claimed, or new contact/approval.

### QA-07 — One-sided/absent reconnect consent

1. Enable reconnect on A only.
2. Repeat the network change.
3. Then disable the mailbox or make it unavailable and repeat.

**Pass:** the UI shows the explicit non-ready state (peer consent/mailbox absent)
and does not claim a connection. **Fail:** connection attempted or shown ready.

### QA-08 — Reconnect after restart, suspension, and membership removal

1. With reconnect enabled, restart both apps and verify reconnect resumes when
   both are unlocked.
2. Suspend the Android app, change network, then resume. Verify either a bounded
   reconnect or an explicit deferred state.
3. Remove B from the workspace on A. Verify B cannot reconnect or send and its
   profile becomes non-ready.
4. Remove the workspace or rotate consent on one side and verify the stale profile
   is rejected.

**Pass:** no stale authorization or silent contact creation. **Fail:** reconnect
after removal, stale profile used, or old token accepted.

### QA-09 — Reconnect with TURN-only path

1. Configure TURN and force relay-only on both devices.
2. Enable reconnect and change network.
3. Verify the path badge says **Relayed** and the call/message path works.
4. Remove TURN or use invalid credentials.

**Pass:** relayed path is explicit and a failed relay produces a clear error, not
a silent direct/delivered claim. **Fail:** credentials leak into diagnostics,
unlabeled relay, or silent downgrade.

### QA-10 — Helper opt-in and helper-disabled behavior

1. On a three-device workspace A (origin), B (helper), C (recipient), leave B's
   helper consent off.
2. Trigger a connection update from A to C through B.
3. Verify B does not relay while consent is off.
4. Enable B's helper consent and repeat.

**Pass:** no forwarding when off; forwarding only after explicit opt-in. **Fail:**
implicit relay, helper sees chat/history, or no explicit consent state.

### QA-11 — One-hop helper relay between changed endpoints

1. Establish A↔C and A↔B and B↔C workspace membership.
2. Break A↔C's direct path while B remains reachable.
3. On A select B as helper and send the signed connection update to C.
4. Verify C applies the original signed update and A↔C traffic resumes.
5. Verify B cannot modify/forge the update and the helper is not made a contact.

**Pass:** one-hop delivery, original signature/audience verified, no contact.
**Fail:** helper becomes relay for chat, more than one hop, or update accepted
without signature/audience validation.

### QA-12 — Helper confidentiality and one-hop stop

1. While B is the helper, inspect B's visible workspace state and logs for chat,
   history, receipts, membership, or keys.
2. Send a second helper-wrapped update whose native source is not the origin and
   verify B does not forward it.

**Pass:** B sees only connection endpoints/timing in its own encrypted delivery;
second hop is ignored. **Fail:** chat content visible to B, helper gets authority,
or forwarding chain continues.

### QA-13 — Grant creation and admin acceptance

1. On A (owner authority) make B an active admin.
2. Open **Workspace settings → Owner-offline admission grants**.
3. Select B's active admin device, confirm the v2-support statement, create a
   five-admission/seven-day grant.
4. Verify B receives the grant, accepts it, and A shows **Accepted**.
5. Verify no owner role/authority transfer and no Personal contact.

**Pass:** grant/acceptance signatures, device binding, visibility, and state.
**Fail:** grant possible without v2 confirmation, wrong admin/device, or authority
change.

### QA-14 — Owner-offline admin admission with v2 manifest

1. Create and accept the grant from QA-13.
2. Create a fresh invitation for C; submit C's signed join to A.
3. Close or shut down A's owner device (owner offline).
4. Verify B received the pending join/invitation and can approve it with the
   accepted grant.
5. Verify B's admission creates a v2 manifest; A (when back) and C apply it.
6. Verify C appears active, receives `#general`/channel controls, and can exchange
   messages with A and B.
7. Verify B's grant use count increments and further admissions are bounded.

**Pass:** v2 admission while owner offline, all devices converge, no owner
authority change. **Fail:** v1 fallback, arbitrary member/device, over-cap use,
inconsistent membership, or C cannot receive channel controls.

### QA-15 — Owner return, normalization, and revocation

1. After QA-14, bring A back online.
2. On A end the grant.
3. Verify A publishes the v1 `delegation_end` manifest, revokes the grant, and B
   shows **Revoked**.
4. Verify B can no longer approve joins from that grant.
5. Verify A/B/C retain the same membership and the workspace returns to a normal
   v1 head.
6. Verify a new owner-signed semantic change can extend the normalized head.

**Pass:** v1 normalization, revocation, no membership loss, no further use.
**Fail:** grant remains usable, v2 head never normalizes, or membership changes.

### QA-16 — Grant expiry, use cap, and revocation blocking

1. Create a grant with the shortest test lifetime and wait for expiry.
2. Attempt an admission with the expired grant.
3. Create a fresh grant with a low cap and exhaust it.
4. Revoke a grant and attempt one more admission.

**Pass:** expired/capped/revoked grants are rejected with explicit errors and no
manifest change. **Fail:** admission after expiry/cap/revocation.

### QA-17 — Pre-v2/old-client behavior

1. Install a pre-0.9.13 client in a separate test workspace under controlled
   conditions, or simulate an old manifest verifier.
2. Issue a delegated v2 admission.
3. Record exactly what the old client displays and whether it converges.

**Pass for the v2-aware client:** it applies the v2 manifest and the owner can
normalize later. **Expected limitation:** an already-installed pre-v2 client
cannot be retroactively taught to fail closed; it may reject/ignore the unknown
document. Do **not** mark this a full pass without recording the old client's
behavior and version.

### QA-18 — Signed-history fork handling (lab only)

This is destructive and must use a disposable workspace.

1. Create two conflicting signed histories on two devices with no network between
   them.
2. Reconnect both devices.
3. Verify the workspace freezes with the conflict type and local signed head.
4. Verify the settings panel offers conflict details/copy/local removal but does
   not choose a history automatically.
5. Verify messaging and admission are paused on both devices.

**Pass:** deterministic fail-closed freeze and clear operator diagnostics. **Fail:**
automatic merge, silent choice, or continued messaging.

### QA-19 — Workspace DM audio/video call

1. Pair A and B as active workspace members with an open workspace DM.
2. Start an audio call from A's workspace DM header.
3. Verify B sees an incoming workspace call with the workspace/member name; no
   microphone starts before accept.
4. Accept; verify audio both ways, mute/unmute, hangup, clean ended state.
5. Repeat with video; verify camera preview, camera on/off, remote video, and
   audio/video fallback.
6. Verify no Personal contact was created and the call remains scoped to the
   workspace DM.

**Pass:** bidirectional media and correct workspace identity. **Fail:** contact
creation, wrong peer, pre-accept capture, or no ended state.

### QA-20 — Workspace call network change and TURN

1. During a workspace call, change B's network and verify **Reconnecting** and a
   successful ICE restart without a new ring/approval.
2. Force TURN-only and repeat a call; verify the path badge says **Relayed**.
3. Remove/invalid TURN and verify a clear failure and fallback to messaging.

**Pass:** reconnect/relay works and is labeled. **Fail:** silent direct claim,
stuck call, or credential leak.

### QA-21 — Workspace call Android background/lock/permissions

1. Join an Android device as a workspace member and start a call with A.
2. Grant microphone/camera at call time; deny once and verify no call starts.
3. Background the app during a call; verify foreground-service notification,
   audio continuity, and return-to-call.
4. Lock the screen and verify audio and notification behavior.
5. Test audio focus (music pause/duck/resume) and speaker/earpiece/Bluetooth
   routing where available.

**Pass:** explicit permissions and continuity without content leakage. **Fail:**
pre-accept capture, missing call notification, or audio stuck after hangup.

### QA-22 — Workspace call decline/rate-limit/end states

1. Decline an incoming workspace call; verify **Declined** and no contact/workspace
   change.
2. Let an outgoing call ring unanswered; verify it ends at the configured timeout.
3. Make four calls within a minute; verify the rate-limit message.
4. Kill one app during a call; verify the peer sees ended and no stuck call.

**Pass:** all terminal states converge. **Fail:** stuck ringing/active call or
membership change.

### QA-23 — WebRTC workspace invitation transfer

1. Establish an active WebRTC session between A and B.
2. On A open **Invite people** and choose **WebRTC DataChannel (connected)**.
3. Create the invitation; verify A reports it was sent over the active DataChannel.
4. On B verify the standard join dialog opens prefilled; review the signed
   invitation and submit the join.
5. Approve B on A; verify active workspace membership and messages.

**Pass:** invitation arrives over the control channel and normal join/approval
still applies. **Fail:** no transfer, invitation trusted without signature, or
approval skipped.

### QA-24 — WebRTC invitation validation and no-trust-bypass

1. Send a valid WebRTC invitation; verify the peer previews the workspace and
   requires the normal signed join.
2. Send a tampered/invalid/expired document over the same control channel.
3. Send an invitation intended for another workspace/device.

**Pass:** only the valid document can be reviewed and joined; tampering/expiry/
wrong audience fails closed. **Fail:** transport arrival alone grants membership
or trust.

### QA-25 — WebRTC invitation unavailable/expired/tampered

1. With no active WebRTC session, verify the WebRTC option is not offered and
   cannot be forced through the UI.
2. Close the session during transfer; verify an explicit error and retry path.
3. Replay an old WebRTC invitation after the peer already joined.

**Pass:** explicit errors; no replay admission. **Fail:** silent success or
duplicate membership.

### QA-26 — Android notifications and background suspension

1. Send a workspace message and mention while Android is backgrounded.
2. Verify notification content matches the user's lock-screen privacy setting and
   does not include hidden/unauthorized content.
3. Suspend the app, change network, then resume. Verify pending work is deferred
   or processed with explicit status, not silently lost.
4. Repeat during a call and during reconnect.

**Pass:** notifications/privacy and bounded suspension behavior are observable.
**Fail:** unauthorized content in notification, lost work, or false delivered.

### QA-27 — Android install, launch, and clean removal

1. Clean install the debug APK.
2. Launch, create/lock/unlock the vault, and verify no crash/ANR.
3. Verify app-private data is removed on uninstall; no plaintext export remains.
4. Verify no production-signing or upgrade claim is made for the debug APK.

**Pass:** clean install/launch/removal. **Fail:** plaintext residue, stuck lock, or
debug-signed upgrade claims.

### QA-28 — Windows install, launch, upgrade, and removal

1. Install the 0.9.15 NSIS/MSI, launch the service sidecar, create/unlock the
   vault, and verify no missing DLL/sidecar.
2. Upgrade from the previous published version and verify workspace/vault data is
   preserved and no duplicate service process remains.
3. Uninstall; verify vault/data removal choice and no orphan service.

**Pass:** install/launch/upgrade/uninstall. **Fail:** orphan process, data loss, or
service failure.

### QA-29 — Privacy: no contact creation, no plaintext, no recording

1. After QA-04, QA-06, QA-10, QA-14, and QA-23, verify no Personal contact was
   created by any workspace-only path.
2. Inspect logs, diagnostics, crash output, and support bundles for message
   plaintext, SDP, TURN credentials, IPs, private keys, or full invitation
   documents.
3. Verify calls create no recording/transcript/media file.
4. Verify helper/admin/relay roles see only the documented metadata.

**Pass:** no contact creation and no secret/plaintext leakage. **Fail:** any
contact created, call recording, or secret in logs/diagnostics.

### QA-30 — Full three-device end-to-end pass

Run the P0 scenarios on the same test bed and version:

1. Baseline workspace QA-01/02.
2. Reconnect QA-05/06/08/09.
3. Helper QA-10/11/12.
4. Owner-offline QA-13/14/15/16.
5. Calls QA-19/20/21.
6. WebRTC invitation QA-23/24.
7. Privacy QA-29.

**Pass:** all P0 scenarios pass on at least Windows↔Windows and Windows↔Android
topologies, with exact hashes and sanitized evidence. A pass on only one topology
is partial evidence, not full qualification.

## 5. Acceptance gates

A physical qualification run is complete only when:

- the Windows installer and Android APK hashes match the published 0.9.15
  artifacts;
- all **P0** scenarios pass on at least one two-device Windows↔Windows topology
  and one Windows↔Android topology;
- owner-offline admission and WebRTC invitation each include a real third device
  or a real second endpoint as specified;
- reconnect and calls include at least one network change and one TURN-forced or
  explicit relay case;
- no P0 security/privacy failure remains open;
- every result records pass/fail, topology, device/OS, version/hash, timestamp,
  and a sanitized observation.

A scenario is **not** qualified by:

- CI, unit tests, renderer tests, or an emulator;
- loopback or two apps on one machine;
- importing a document without an actual remote device;
- a connecting badge without a message/receipt or media;
- a screenshot without the recorded device/network/version.

## 6. Evidence template

Copy this table per run.

| Field | Value |
|---|---|
| Run date/time | |
| App version | 0.9.15 |
| Windows installer SHA-256 | |
| Android APK SHA-256 | |
| Windows version/device A | |
| Windows/Android version/device B | |
| Android version/device C | |
| Network A / B / C | |
| TURN/mailbox/I2P | |
| Workspace ID (test only) | |

Per scenario:

| Scenario | Result | Evidence | Observation |
|---|---|---|---|
| QA-01 | pass/fail/blocked | screenshot/receipt | |
| QA-06 | | | |
| QA-11 | | | |
| QA-14 | | | |
| QA-15 | | | |
| QA-19 | | | |
| QA-23 | | | |
| QA-29 | | | |

## 7. Known limitations to record

These are known limitations, not automatic failures, but each must be recorded
with the tested version:

- The Android APK is **debug-signed**; it is not a production or upgrade identity.
- Group workspace calls are not supported; calls are 1:1.
- A signed-history fork is not automatically resolved; the workspace freezes and
  requires operator action.
- Already-installed pre-v2 clients cannot be retroactively made to fail closed;
  record the old-client behavior rather than claiming a pass.
- Android background suspension can defer workspace work; record the observed
  deferral/retry state.
- No hosted workspace relay, owner relay, or all-to-all topology is provided.
- TURN operators and helpers can observe the documented metadata, never message
  plaintext.
