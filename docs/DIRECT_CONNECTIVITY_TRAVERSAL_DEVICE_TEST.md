# Windows and mobile-carrier acceptance

Status: physical test not executed. **Wait for 0.2.57 (Android 2057): build and
native qualification pending.** The 0.2.54 artifacts below are superseded due to
a revocation-cleanup defect and are retained only as historical evidence.

Superseded build: **0.2.54**, Android
versionCode **2054**, application commit `11b2b1f0a099082933da92f4e5fc0a262fd3121c`.
[Artifact build](https://github.com/ahouchens/mesh-chat/actions/runs/39156577823)
passed verification, signed Android packaging and Windows installer packaging.
Use matching builds on both devices. Version 0.2.52 is superseded because its
Windows unhosted-restart qualification failed; 0.2.53 was superseded by the
active-owner resume fix. The 0.2.54 recovery regression passes on Windows/Linux.

| Platform | Artifact | SHA-256 of GitHub artifact archive |
| --- | --- | --- |
| Android | [mesh-chat-0.2.54-android-arm64](https://github.com/ahouchens/mesh-chat/actions/runs/39156577823/artifacts/12147276639) | `27ec931661f7b0c13f78e78ec539f9a67eec68730de531615240653afbe01689` |
| Windows | [mesh-chat-0.2.54-windows-desktop](https://github.com/ahouchens/mesh-chat/actions/runs/39156577823/artifacts/12147476067) | `8c4ae021322f39907e197e485aaff462c603223f0db292e64a19822aaf78666b` |

Both downloaded archives matched GitHub's digests. All inner artifact files
also matched their packaging manifests, including these installers:

| File | SHA-256 |
| --- | --- |
| `mesh-chat-0.2.54-android-arm64-release.apk` | `2e37e7e5433bb3ed4987e1b4e596c67aa217fa734c05ed08a01a2f5686959d4b` |
| `Mesh Chat_0.2.54_x64-setup.exe` | `6af491de68bcda67a69de7b5027d082d3cf2eaba073ea3a12b4afd7e84de2495` |
| `Mesh Chat_0.2.54_x64_en-US.msi` | `a819c7cecc0549769565a74d7ddfa10d93527654f0ddc4ce8afaccc836fdede8` |

Keep the packaging reports with the test record. These are implementation-branch
test artifacts. Independent protocol review and physical qualification remain
separate gates; see the [acceptance ledger](DIRECT_CONNECTIVITY_TRAVERSAL_EVIDENCE.md).

## Guided test

1. Install the matching new build on **both Windows and Android**. In Settings,
   confirm **Mesh Chat version 0.2.57** and copy version details on each device.
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
