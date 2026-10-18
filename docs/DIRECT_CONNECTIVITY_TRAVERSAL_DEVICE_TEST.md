# Windows and mobile-carrier acceptance

Status: **not ready for physical acceptance yet**. Candidate **0.2.58**, Android
versionCode **2058**, application commit `0bf9623a9d4c01042793f63d3ffb1fd984443308`.
Use matching builds on both devices after qualification. Preserve app data.

[Build run](https://github.com/ahouchens/mesh-chat/actions/runs/39160414911): full
verification and Windows packaging passed. Android's first attempt failed
unpacking the NDK ZIP before compilation; an Android-only retry is running on
the same commit. Native recovery qualification is still open: a preceding run
failed Windows address-loss recovery. Independent review and physical tests remain
separate gates. Do not substitute any superseded build.

| Platform | Current artifact | Archive SHA-256 |
| --- | --- | --- |
| Windows | [mesh-chat-0.2.58-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39160414911/artifacts/12149000861) | `f96a01bf490a5a6a1b5a92ee68e9cf6b8c64565d10646e01d44d027e83c0cb36` |
| Android | Retry pending; no qualified APK yet | Pending |

The Windows archive, manifest and all five packaged files were hash-checked.
NSIS installer SHA-256: `57541794d875d7eb764d4ea9b20e866da18514e18513114f02b31c7643fbdba9`.
MSI SHA-256: `4f184472ea032cab49a8b7d2f7c98ed9fc156a013e81566f0b5031e1b9382464`.
Nothing was installed or executed locally. See the
[acceptance ledger](DIRECT_CONNECTIVITY_TRAVERSAL_EVIDENCE.md).

## Guided test

1. Install the matching new build on **both Windows and Android**. In Settings,
   confirm **Mesh Chat version 0.2.58** and copy version details on each device.
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
