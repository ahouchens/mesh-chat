# Windows and mobile-carrier acceptance

Status: **matching 0.2.63 / Android 2063 packages built and hash-verified**. Full native qualification passed on Windows and Linux, with Android native compilation also passing; see the [evidence record](DIRECT_CONNECTIVITY_TRAVERSAL_EVIDENCE.md). This is the matching pair for the controlled physical acceptance test, not a public-release approval. Preserve app data. Independent protocol review and actual device acceptance remain open.

[Build run](https://github.com/ahouchens/mesh-chat/actions/runs/39168607399) passed full verification, Windows packaging/embedded native checks and signed Android packaging. Application commit: `34d9927f76d27c037e5a2d727bb75167fff3c8e0`. Windows/Linux old-fails/new-passes recovery regressions and all ten Windows repetition trials passed. Do not substitute a superseded version.

| Platform | Matching artifact | Archive SHA-256 |
| --- | --- | --- |
| Windows | [mesh-chat-0.2.63-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39168607399/artifacts/12151891183) | `b424d0ffd343f452e48cb79492a30a24fc5289a05cdb587d1c0ed8c65f6f8716` |
| Android | [mesh-chat-0.2.63-android-arm64](https://github.com/ahouchens/mesh-chat/actions/runs/39168607399/artifacts/12151726555) | `e7952764d9a6caa119c55c9ecd80e4c25b4fe5597d4257145503ad280c2b2445` |

The Windows archive, manifest and all five packaged files were hash-checked.
NSIS installer SHA-256: `9147e7836e974026bfb0c749918ffd2069c10ac40245943c08528ae7ea63f348`.
MSI SHA-256: `55a22b9e44b76c06ffbe87cbebc2ed4b4e0d5825f3a66c7567e947e540d0c270`.
Android APK SHA-256: `a1c3e7223ee60213629b5b3c1618bd9c610c7d1aa8dd521c6d8415fc319d1c25`.
Its manifest is 0.2.63 / 2063 with release signing; the current manifest pointer and both APK copies were also verified. Nothing was installed or executed locally.

## Guided test

1. Install the matching new build on **both Windows and Android**. In Settings,
   confirm **Mesh Chat version 0.2.63** and copy version details on each device.
   Preserve existing app data; do not clear the profile to work around a failure.
2. Leave Windows on the home router. Turn Android Wi-Fi off and confirm mobile
   data is active. Keep both Mesh Chat apps unlocked and open.
3. On Windows, open the workspace, choose **Invite**, then **Prepare invitation**.
   Follow the check-this-device step. A prepared address is not yet verified.
   If checks need repair, follow the displayed action and Retry checks.
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

## Wizard-specific acceptance

- With no route, verify sharing/QR/raw text is withheld; restore the same device's
  Internet connection and Retry checks without creating a new invitation.
- If only one device has an address, follow the exchange. If both lack candidates,
  stop at the explicit explanation; no final-copy/wait loop should be offered.
- Change networks during setup: old sharing must disappear after the next check.
- A prepared mapping must say unverified. Only an authenticated intended peer
  connection may say verified; a timeout must not claim firewall/UDP blocking.
- Copy diagnostics immediately from any wizard step, including failures. Check
  clipboard-denial fallback, large text, Back and Cancel on both platforms.
