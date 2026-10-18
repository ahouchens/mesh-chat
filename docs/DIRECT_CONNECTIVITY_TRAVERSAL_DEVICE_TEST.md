# Windows and mobile-carrier acceptance

Status: **awaiting qualified 0.2.62 / Android 2062 packages**. This adds the
regression-backed pause/allocation cleanup correction. The verified 0.2.61
artifacts below remain historical evidence, not the final acceptance pair.
Preserve app data. Independent review and physical acceptance remain release gates.

[Build run](https://github.com/ahouchens/mesh-chat/actions/runs/39165181059) passed
full verification, Windows packaging/embedded native checks and signed Android
packaging. The native old-fails/new-passes recovery regression passed on Windows
and Linux; five Windows address-loss repetitions and five source-admission
repetitions passed. [Full native qualification](https://github.com/ahouchens/mesh-chat/actions/runs/39165009596)
is still running. Do not substitute a superseded version.

| Platform | Matching artifact | Archive SHA-256 |
| --- | --- | --- |
| Windows | [mesh-chat-0.2.61-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39165181059/artifacts/12150896027) | `4b2021678b93cc070513ff72205f97694403a8c9340c389b8256fe5e03ce33b3` |
| Android | [mesh-chat-0.2.61-android-arm64](https://github.com/ahouchens/mesh-chat/actions/runs/39165181059/artifacts/12149649328) | `0a9139530a1d39fed672ff3eca5663e09c2dbe41eeebfb069dc742b984c25722` |

The Windows archive, manifest and all five packaged files were hash-checked.
NSIS installer SHA-256: `cdb65c661f559b962fc13a52dafbf1650bd410bf70e13874a65562bdcab7ceac`.
MSI SHA-256: `cde6b4cf52e36f4f5d6ad42147f6b1e95fea381df8b9948f159a7000d85d48f5`.
Android APK SHA-256: `f1f9a7ed0f6682228be566f0ad30a3d5d1419ab465d899cb7793c2010e500876`.
Both Android APK copies match; its manifest is 0.2.61 / 2061 with release signing.
Nothing was installed or executed locally. See the
[acceptance ledger](DIRECT_CONNECTIVITY_TRAVERSAL_EVIDENCE.md).

## Guided test

1. Install the matching new build on **both Windows and Android**. In Settings,
   confirm **Mesh Chat version 0.2.62** and copy version details on each device.
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
