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

### B1. Pairing and repeated calls over one WebRTC connection

Use Android on cellular and Windows on Wi-Fi. Run once with a Windows offer
and Android answer, then again with an Android offer and Windows answer.
Leave the signaling mailbox unconfigured for this established-connection test.

1. Complete signed pairing and contact acceptance. Send a message each way and
   confirm delivery receipts before making any calls.
2. Without re-pairing, complete audio calls initiated by each device, then video
   calls initiated by each device. Verify two-way media. End audio calls from
   the caller and video calls from the recipient.
3. Send messages both ways during each call and after each hangup. Verify
   receipts and that the original messaging route remains available.
4. With Android background availability enabled and its ongoing notification
   visible, switch apps, lock the phone, send messages from Windows, then
   return to Mesh Chat. Confirm delivery and repeat an audio/video call.
5. If a step fails, capture Settings connection diagnostics from both devices
   before restarting or making another offer. Record whether the failure was
   before, during, or after a call and which device ended it.

### Automated regression coverage and limits

- `service/tests/test_webrtc_delivery.py` pairs real RNS/LXMF service processes
  over a packet relay, including Android-like 750 ms packet polling. It checks
  signed audio/video invitations and answers in both directions, cancellation,
  caller/recipient hangup, and two-way messages with receipts before, during,
  and after calls on the original bridges. It does not transport RTP.
- `src/App.test.tsx` runs repeated answered audio/video call dialogs with
  desktop and Android platform responses. It checks media permission timing,
  local/remote hangup, track and audio-focus cleanup, late callbacks from old
  calls, and preservation of the separate messaging session. Browser media and
  native APIs are mocked in these UI tests.
- `NativeWebRtcInteropTest` checks real native/Chromium data channels with both
  offer directions and four successive Chromium audio/video RTP sessions.
  Messaging is probed during and after each media session. Tracks are generated
  and both media peers run in the same WebView; this is engine coexistence
  coverage, not a complete Android-to-Windows call. Separate instrumentation
  covers foreground-service restoration and packet traffic with the activity
  stopped. The runner is `scripts/test_android_webrtc.sh`.

These layers complement the physical test above. They do not reproduce a
carrier's NAT, prolonged device sleep, hardware camera/microphone behavior, or
every Windows WebView/Android OS combination.

### Android sleep qualification (separate from short activity-stop coverage)

On a disposable test device, test battery optimization both enabled and exempt.
The Background availability screen must report the actual exemption and offer
system battery settings when restricted or unknown. Opening settings must not
silently change the background opt-in or claim a successful exemption.

Keep Windows awake throughout. Establish a fresh connection, exchange messages,
then leave Android unplugged, stationary and screen-off for at least 30 minutes.
Send messages from Windows during sleep; verify Android notifications and replies
after wake. Record direct/relay path and battery configuration. Also exercise
forced Doze using Android's documented `adb shell dumpsys deviceidle force-idle`
procedure on the test device; always restore it with
`adb shell dumpsys deviceidle unforce` afterwards. Run both restricted and exempt
cases. Network suspension is possible in the restricted case even with a
foreground service; don't count that case as proof of sleep delivery.

Capture diagnostics before restarting anything, then again after restarting the
background service. Compare `battery_optimization_exempt`, `device_idle`,
`power_save`, `service_history`, and `previous_process_exit` with the transport
events. Service history must retain the stop/start sequence. A process killed
without `onDestroy` may have no `destroyed` event; the previous exit is an OS
reason code and timestamp, not proof that Doze caused the exit. Restarting the
service must not be presented as restoring a lost peer connection. With no
signaling mailbox, re-establish the connection with a fresh invitation.

Automated instrumentation checks the power flags against Android APIs and that
service restart preserves its persisted history. It does not qualify prolonged
sleep or Samsung power management. Reference:
https://developer.android.com/training/monitoring-device-state/doze-standby

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
