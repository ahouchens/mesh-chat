# Windows and mobile-carrier acceptance

Status: **awaiting qualified 0.2.63 / Android 2063 packages**. The fifth Windows
address-loss repetition failed on 0.2.62; the exact native trace now has a targeted
server-first timing regression. The 0.2.62 packages below are historical evidence,
not the new acceptance pair. Preserve app data.

[Build run](https://github.com/ahouchens/mesh-chat/actions/runs/39167070427) passed
full verification, Windows packaging/embedded native checks and signed Android
packaging. Native old-fails/new-passes recovery regressions passed on Windows
and Linux. [Full native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39167069275)
is still running. Do not substitute a superseded version.

| Platform | Matching artifact | Archive SHA-256 |
| --- | --- | --- |
| Windows | [mesh-chat-0.2.62-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39167070427/artifacts/12151027377) | `7530a4bde0905e6bcd090d3e136eb925a8ae3d8ec1311cec63033025b983261d` |
| Android | [mesh-chat-0.2.62-android-arm64](https://github.com/ahouchens/mesh-chat/actions/runs/39167070427/artifacts/12151287537) | `4f8ae52f6bc94b55050ffefda2c908ddcefde66a2d078d3fcd669a11e665acf7` |

The Windows archive, manifest and all five packaged files were hash-checked.
NSIS installer SHA-256: `4e8224e75a6dfb617182a3c9fa6962c2b19531dbc95684a5663c1ca601bf3d9b`.
MSI SHA-256: `6319e95c1ba0e9f9531e2e682732ec3b6272852dd7cd3260a898a80a94870c6e`.
Android APK SHA-256: `3a5a17491dcae996fff7bd8072da36f0b1e94b5e1fe6e78805f46773e21172f1`.
Its manifest is 0.2.62 / 2062 with release signing. Nothing was installed or
executed locally. See the [acceptance ledger](DIRECT_CONNECTIVITY_TRAVERSAL_EVIDENCE.md).

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

After any failure, use **Copy diagnostics** on both devices. In Settings â†’
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
