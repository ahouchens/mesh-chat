# Windows and mobile-carrier acceptance

Status: not executed. Candidate build: **0.2.52**, Android versionCode **2052**,
application commit `dec191bbea6c63967cfcf5073abd7acc052a3333`.
[Artifact build](https://github.com/ahouchens/mesh-chat/actions/runs/39154321087)
passed. Download the matching artifacts:

**Do not use 0.2.52 as the final acceptance build.** Its subsequent Windows
native qualification failed the unhosted-peer restart scenario. The recovery
fix and replacement version are undergoing qualification. The hashes below
identify the superseded artifacts for debugging, not a release recommendation.

| Platform | Artifact | SHA-256 of the GitHub artifact archive |
| --- | --- | --- |
| Windows | [mesh-chat-0.2.52-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39154321087/artifacts/12146378265) | `ec0048c33f2041ae0006ce043c06ac81db51a5dc6ac1921c24fd4b6090e0f1eb` |
| Android | [mesh-chat-0.2.52-android-arm64](https://github.com/ahouchens/mesh-chat/actions/runs/39154321087/artifacts/12146441968) | `2170e84161f418a287e415fb9b8953577a52cd90957732b0244bddca07c12cf2` |

These are GitHub's archive digests, not the inner installer/APK hashes. Keep the
packaging reports with the test record. The artifacts are test builds from the
implementation branch; native qualification and protocol review remain separate
gates, recorded in the acceptance ledger.

Downloaded archives matched GitHub's digests. Inner files were hashed locally
and matched their packaging manifests:

| File | SHA-256 |
| --- | --- |
| `Mesh Chat_0.2.52_x64-setup.exe` | `0d7899ac673a6d32c21543400d9fa38ad047c12e2cddb1a758b2b9d62132f6f6` |
| `Mesh Chat_0.2.52_x64_en-US.msi` | `5ee4e3206f5ee9270aaa30f3ff3c2515af09834e32b157c4b4453719e3b1b504` |
| `mesh-chat-0.2.52-android-arm64-release.apk` | `23fb5fba68be1447c8cdaf5784e6b4e767036e679209492ce0a60425440023bd` |

## Guided test

1. Install the matching new build on **both Windows and Android**. In Settings,
   confirm **Mesh Chat version 0.2.52** and copy version details on each device.
   Preserve existing app data; do not clear the profile to work around a failure.
2. Leave Windows on the home router. Turn Android Wi-Fi off and confirm mobile
   data is active. Keep both Mesh Chat apps unlocked and open.
3. On Windows, open the workspace, choose **Invite**, then **Prepare invitation**.
   Copy the current connection message and send it to the phone using the usual
   clipboard/file/message transfer method.
4. On Android, open **Join or connect** (the arrow entering a door in the workspace
   switcher), paste the complete message, choose **Check received message**, then
   **Prepare reply**. Copy its reply and send it back to Windows. Return to Mesh
   Chat promptly after using another app; Android's temporary sharing grace is
   45 seconds and does not survive process death.
5. On Windows, paste that reply into **Join or connect**, choose **Check received
   message**, then **Prepare connection message**. Send that current message to
   Android immediately; its countdown is shorter than the invitation lifetime.
6. On Android, paste the final message into **Join or connect**, check it, then
   choose **Connect**. Follow the displayed result on both devices.

Do not wait indefinitely for a Windows notification. **Request saved** means
only local persistence. **Connected** means the transport authenticated. A
signed owner receipt and the owner's approval are separate later events.

If neither device has a public address to share, record the exact unsupported
outcome. Repeated copying cannot discover a public mapping. Do not silently
change this test to same-Wi-Fi and call it a carrier success.

## If a connection succeeds

Check Windows workspace People for the incoming request, verify the requesting
device, and approve it. Confirm Android leaves the pending state. Send a new
message in each direction and check endpoint receipts on both devices. Then test
one app restart and an Android share-and-return cycle without creating another
invitation. Confirm the saved relationship and messages remain intact.

## Resume and collect evidence

If a dialog closes, use **Continue setup** in the pending workspace or beside
the active invitation in the owner's Invite dialog. A live saved message should
reappear. Expired or lost socket ownership should offer a refresh of the same
invitation, keeping the saved request. Do not substitute a different invitation
for the pending request.

After any failure, use **Copy diagnostics** on both devices. In Settings →
**Help and diagnostics**, copy the connection log and version details. If copying
is denied, select the fallback text or save the diagnostics file. Reopen the app
and verify the last failure is still available. Clear diagnostic history and
verify that workspaces, pending requests, identity and messages are unchanged.

Check every setup state on the phone with normal and large text: no horizontal
clipping, readable buttons, reachable next action and usable scrolling. Record
the coarse network type, installed build IDs, timing, outcome and copied reports.
Do not include invitation contents, private keys, addresses or message contents.

A truthful unsupported result is useful diagnostic evidence, but does not satisfy
the successful physical direct-connection criterion. Keep those outcomes separate.
