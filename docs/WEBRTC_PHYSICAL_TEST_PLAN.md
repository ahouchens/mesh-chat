# WebRTC physical-device test plan

Status: required before 1:1 calls are treated as release-qualified. The code and
CI artifacts exist; this plan needs real devices.

## Devices

- Two Windows x64 machines on different networks, each with a microphone and
  speakers/headset.
- One Windows x64 machine and one arm64 Android device on different networks.
- Optional third TURN relay with short-lived credentials.

Use the published Windows installer and Android APK for the same version.
Record the version, APK SHA-256, Windows installer SHA-256, OS versions, and
network type.

## A. Windows ↔ Windows

1. Pair two approved contacts using the normal invitation/TCP access-point
   onboarding path. Do not use WebRTC for onboarding.
2. Start an audio call from A. Verify B shows the incoming-call banner and
   **Accept/Decline**; no microphone starts before Accept.
3. Accept. Verify audio both ways, mute/unmute, hangup, and a clean ended state.
4. Repeat with video. Verify camera preview, camera on/off, remote video, and
   audio/video fallback.
5. Confirm the path badge shows **Direct** on LAN and **Relayed** when TURN is
   forced with `relay_only`.
6. Disconnect/reconnect the network during a call. Verify **Reconnecting** and
   a successful ICE restart without a new ring or approval.
7. Let an outgoing call ring unanswered. Verify it ends at 45 seconds and
   leaves no active call.
8. Make four calls within a minute. Verify the fourth is refused with the
   rate-limit message.

## B. Windows ↔ Android

1. Install the APK, grant microphone/camera at call time, and pair with an
   approved Windows contact.
2. Repeat audio and video answer/decline, mute, camera, and hangup.
3. Background the Android app during a call. Verify the foreground-service
   notification, audio continuity, and return-to-call.
4. Test audio focus: play music, start a call, verify music pauses/ducks and
   resumes after hangup.
5. Test speaker/earpiece/Bluetooth routing and screen lock.
6. Trigger an ICE restart by changing Wi-Fi to cellular. Verify reconnect
   without a new approval.
7. Verify the app does not request microphone/camera before the user accepts.

## C. TURN/relay

1. Configure STUN only. Verify a direct path is preferred.
2. Configure TURN and force relay-only. Verify the path badge says **Relayed**.
3. Remove TURN or use invalid credentials. Verify a clear failure and **Send
   message** fallback; no silent downgrade.
4. Confirm TURN credentials do not appear in logs, diagnostics, or snapshots.

## D. Failure and privacy

- Deny microphone/camera. Verify a clear recovery path and no call start.
- Decline an incoming call. Verify **Declined** and no contact/workspace change.
- Kill the app during a call. Verify the peer sees an ended call and the app
  restarts without a stuck active call.
- Verify no recording, transcript, or media file is created.
- Verify the foreground notification contains no caller content beyond what the
  user already sees on the lock screen.

## Acceptance evidence

For each scenario record:

- pass/fail;
- call direction and media;
- path: direct/relayed;
- OS and app version;
- APK/installer SHA-256;
- timestamp;
- screenshot or short recording of the call state and path badge;
- any error code and the recovery action.

Do not mark C1/C2/C3 qualified from CI or emulator results alone. A real
Windows↔Android call plus a real TURN-forced call is required.
