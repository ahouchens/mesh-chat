# Mesh Chat

Mesh Chat is a security-sensitive desktop and mobile messenger prototype built on the reference [Reticulum](https://reticulum.network/) and [LXMF](https://github.com/markqvist/LXMF) implementations. It has no account service, signaling service, key directory, analytics endpoint, hosted relay, or required always-on machine.

Messages use native individual LXMF delivery destinations. Reticulum owns paths and transport; LXMF owns direct and propagated delivery; Mesh Chat owns contact consent, encrypted local records, a durable logical outbox, deduplication, and application-level delivery receipts.

> This repository is not independently audited and is not yet suitable for sensitive operational use. See [TESTING.md](TESTING.md) for verified and unverified release gates.

## Desktop workspace increment 7

This source tree now implements the seventh bounded desktop workspace increment from
[WORKSPACE_SPEC.md](WORKSPACE_SPEC.md): create and switch up to 16 workspaces,
invite and approve up to seven additional people, and use up to 32 active public or private
channels including canonical `#general`. Workspace creation explains that the creating device is the authority,
messages are separately encrypted to member devices, and there is no hosted
workspace server. Multiple single-use invitations can remain pending,
expire, be revoked, or be approved independently. Later joiners receive the
complete missing signed-manifest chain while existing members receive only the
new epoch.

The People view exposes the complete eight-person directory. Members can
request a workspace display-name change or leave; owners can approve or decline
name requests, remove a member, update workspace metadata, and close the
workspace. Authority changes wait explicitly for the owner, but current members
continue to exchange channel messages directly while that device is offline.
Propagation-node use remains off until a person explicitly approves a node
address on that device. Local hide and exact-ID-confirmed local removal remain
separate actions.

Workspace messages are signed events and are loaded in bounded pages instead
of the startup snapshot. Sending returns after an atomic durable commit while a
background scheduler delivers signed controls and per-device event copies.
Delivery wording and expandable details distinguish people from devices and
pending, reached, partial, failed, expired, and cancelled legs from human read
state. Drafts and all workspace records remain encrypted in the
vault. Missing controls, pending predecessors, queue pressure, forks, closure,
leaving, and terminal local-removal states expose only their valid actions.
Workspace changes refresh a scoped bounded summary rather than the full app
snapshot, and an uncertain send retry reuses the same durable event and
operation identifiers.

Every active member can browse public channels retained by reachable authorized
peers. Discovery uses signed, bounded summary pages and signed chain fetches;
the directory says when convergence is incomplete. Channel creation and posting
follow the manifest's exact `all_members` or `owner_and_admins` policy, with the
latter treated as owner-only until admins ship. Managers can rename channels,
change topics, offer management to a named successor, and terminally archive;
the owner authority can sign an explicit recovery. Duplicate normalized names
remain distinct and use stable short-ID disambiguators. Subscriptions and unread
badges are local presentation state: unsubscribed public channels still receive
and retain authorized events, and reversed events wait for their controls.

Private channels have their own manager-signed roster chain. Only current
members receive the channel identifier, name, topic, roster, controls, events,
or delivery legs. Managers can add or remove active workspace members, transfer
management to a current channel member, and terminally archive. A newly added
member receives one current signed admission checkpoint and future events, not
the older roster chain or messages. A nonmanager can leave; the manager must
transfer before leaving. Owner recovery is available only when that owner is
already on the private roster, and a conflicting signed head pauses only that
channel.

Active workspace members can also start a one-to-one workspace DM from People
without creating or changing a global Contact. The conversation UUID is
deterministic for the workspace and exact two-member pair. Each event carries a
null channel digest and the complete sorted two-member audience, and it is
copied only to those participants' devices. Workspace-DM indexes, unread state,
drafts, paging, and local hide/reopen presentation are independent of Personal
chat. Hiding preserves encrypted local history; reopening from People restores
the same conversation. A learned removal makes that DM read-only and cancels
its unhanded delivery legs.

Workspace messages in public channels, private channels, and workspace DMs now
support author edits, author deletion tombstones, and member reactions. Every
mutation is a separately signed canonical event bound to the original message,
base revision, next revision, current authorization controls, and frozen
historical audience. Posting policy restricts new channel messages but does not
silence reactions or workspace DMs. Concurrent author revisions resolve by the
documented deterministic device/digest order and remain visibly marked until a
later revision resolves them. Two different values from one device at one
revision freeze further mutation with a security warning. Reactions retain one
independent active/inactive state per member and emoji, so removing one emoji
cannot resurrect it when delayed packets arrive. Mutation events advance the
author stream but never create duplicate timeline entries; derived state,
conflicts, tombstones, and reactions survive restart in the encrypted vault.

Structured workspace mentions now bind stable active member UUIDs in the signed
message or edit event. The picker is the only way to create that metadata;
typing or pasting `@name` remains ordinary text. Authorized mentions appear in
a separately paged Mentions inbox with encrypted local read positions, work in
subscribed and unsubscribed public channels, and can be muted per channel
without changing delivery or membership. Draft mention IDs and inbox pages are
sealed in the vault. Message edits can add or remove mentions, and the service
revalidates the local inbox and draft presentation against current workspace
membership, private-channel access, local hides, tombstones, and mute state.
Workspace mention state never creates a global Contact or a network-visible
read receipt.

Workspace messages can now open a one-level thread without changing the
canonical bytes of ordinary non-thread events. A reply signs the root event
UUID, stays in the root's exact public-channel, private-channel, or workspace-DM
audience, and can never become another root. The dedicated thread view keeps
the original message in context and provides bounded reply paging, structured
mentions, edits, deletion tombstones, reactions, an encrypted reply draft, and
an independent local unread high-water. The Threads activity view is a bounded
encrypted summary index; opening a thread advances only that thread's read
state. A mention inside a reply opens the thread directly. Every list, draft,
mutation, and cursor rechecks current membership, private-roster admission,
workspace-DM participants, channel state, local hides, and the root's retained
availability, so a roster gap cannot resurrect an older private thread.

This increment is deliberately desktop-only and capped at eight people
with one device each. It has no attachments, history backfill, search,
private or DM history catch-up, linked devices, or mobile UI
yet; those remain the later increments in the spec.

## Install Mesh Chat

**Current desktop workspace candidate: Mesh Chat 0.2.28.** Install it over the
existing app; do not uninstall Mesh Chat or clear its data first. The current
paired desktop/mobile install record remains 0.2.12 until workspace support reaches
the mobile UI and completes physical cross-device validation.

Mesh Chat must be packaged for the operating system where it will run. This
workspace contains Windows x64 and Android arm64 packaging flows. Check the
workspace Increment 8 record in [TESTING.md](TESTING.md) for the exact desktop
verification completed for 0.2.28, and the 0.2.12 record for current Android
artifacts. The macOS, Linux, and
iOS packaging paths are implemented, but their packages still need to be built
and tested on those operating systems.

### Android — sideload package path

The current Android target supports arm64 phones and tablets running Android 7
(API 24) or newer. The verified installable development APK is:

`dist/mobile/mesh-chat-0.2.12-android-arm64-debug.apk`

Version 0.2.0 introduced small private groups and private announcement
channels. Each group message remains inside Reticulum/LXMF and is sent as an
individually ratchet-encrypted copy to every other active member; there is no
shared group key or hosted group service. Version 0.2.1 introduced
application-confirmed group invitation delivery, visible delivery states,
bounded automatic retry, an
owner-controlled Retry action, and mobile invitation reliability fixes.
Version 0.2.2 improved desktop close and relaunch behavior, but a later live
test found that a busy PyInstaller service worker could still survive a close
and keep the encrypted profile lock. Version 0.2.3 fixes that remaining case
with a bounded close sequence, exact-PID process-tree cleanup, and a service
watchdog tied to the desktop parent. It also reports an occupied profile
accurately and lets the user retry invitation creation without closing the
dialog. Version 0.2.4 fixes a one-to-one approval regression that was exposed
by the private-group route work: accepting a phone could synchronously wait on
each signed reverse TCP route and exceed the desktop command deadline, while
the same approval flush could also submit its durable `CONTACT_ACCEPT` packet
twice. Reverse-route attachment now uses Reticulum's asynchronous TCP-client
startup path, and approval atomically records one retryable acceptance before a
single flush. The shared fix is included in both the Windows desktop packages
and Android APK. Version 0.2.5 fixes a first-message visibility regression:
on mobile, where the desktop's periodic snapshot timer is intentionally absent,
an older snapshot already in flight could hide a newly and durably sent
message. A successful send could also be described as unsent when only saved
draft cleanup failed, and a delayed callback from an older direct-message
attempt could retract newer delivery evidence. Mutations and service events
now queue a fresh snapshot after an older refresh, successful send and draft
cleanup are reported separately, and direct-message evidence is monotonic and
correlated to the current native handoff. Version 0.2.6 fixes the remaining
phone-to-computer first-message route failure. Reticulum can keep an earlier
equal-hop nearby-discovery path selected after the signed TCP client from an
invitation is online. This matters on phones that can open the invitation's
outbound TCP connection but cannot accept a reverse listener connection.
Mesh Chat now gives only that explicitly signed outbound TCP client the minimum
higher route preference and performs a short, targeted path refresh before a
direct LXMF handoff. The wildcard LAN listener is never preferred, peer
authentication still comes from the Reticulum destination identity and
recipient ratchet, and normal Reticulum routing remains the fallback if the
signed route does not answer. Version 0.2.6 also displays the durable result of
a mobile send immediately, coalesces rapid draft writes before they reach the
single Android worker, prevents duplicate submission, and prevents an IME
composition Enter event from sending incomplete text. Version 0.2.7 fixes the
desktop-reply failure found after a phone successfully sent the first direct
message. LXMF can invoke native delivery or inbound callbacks while retaining
its outbound-processing lock; those callbacks previously re-entered Mesh
Chat's command lock while the background retry worker could hold that command
lock and wait on LXMF. That lock inversion made a new desktop send exceed its
command deadline. Native callbacks now enter the service through a bounded
dispatcher outside LXMF's locks, the retry loop locks and yields one durable
record at a time, and
the encrypted idempotency journal is capped at 512 recent mutation responses
and eight days while read-only commands are not journaled. The phone-shaped
real-stack regression now sends phone to desktop first, then sends the desktop
reply over the same full-duplex connection and verifies both application
receipts and logical message IDs. Version 0.2.8 makes the interface fit both
Android system bars and smaller desktop windows, gives Android's native Back
button the expected in-app behavior, and keeps long conversation lists
independently scrollable. It also adds confirmed local conversation deletion:
the contact or group membership remains intact, and a deleted thread can be
restored from search without restoring its erased history. Version 0.2.9 adds
encrypted emoji reactions to direct chats, private groups, and announcement
channels. It introduced six quick reactions—👍, ❤️, 😂, 😮, 😢, and 🎉—and
the replace/remove behavior. Version 0.2.10 expands that control to a
searchable eight-category picker with 253 browsable choices and an emoji-keyboard
field accepting any of the 3,963 fully-qualified sequences in the pinned
Unicode Emoji 18.0 catalog. The generated catalog's provenance and license are
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Reactions travel only
through the same authenticated Reticulum/LXMF paths as messages; there is no
hosted reaction service or less-secure fallback. Version 0.2.11 makes those
reactions visually consistent across desktop and mobile by bundling local,
palette-optimized sprite sheets derived from Twemoji 17.0.3 at commit
`b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`. Local artwork covers all 253
picker choices and 3,944 of the 3,963 accepted Emoji 18 sequences. The 19 new
Emoji 18 sequences for which that pinned open artwork does not yet exist use a
deterministic neutral tile marked **18** and retain a catalog-derived accessible
name. Unicode—not an image identifier—remains the encrypted wire and storage
value. No CDN or runtime artwork request is used. Twemoji's CC BY 4.0
attribution appears in Settings and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Version 0.2.12 adds contact management on desktop and mobile: search saved
contacts, rename them locally, mark or remove fingerprint verification, block
and unblock messaging, open the conversation, or permanently delete the local
contact and direct-chat history. Deletion refuses contacts still referenced by
a pending group invitation, while existing group membership remains intact.
Install 0.2.12 on both participating devices to exchange and display expanded
reactions with the bundled presentation.
An older peer can continue ordinary chat but ignores the additive reaction
records it does not understand. The current release
retains the 0.1.7 conversation layout fix, the 0.1.6 direct local TCP
connection for networks where Reticulum's IPv6 multicast discovery does not
cross between the phone and computer, and the earlier connection-request,
Android runtime, scanner, and clipboard fixes.

If 0.1.3 returns to the Android home screen after submitting a display name,
do **not** clear app data. Install 0.2.12 directly over it. The package identity
and signing certificate are unchanged, so the saved profile is retained and
the corrected runtime can recover it.

> **Install 0.2.12 over 0.2.11 or an earlier release on every participating
> computer and phone. Do not uninstall
> either app or clear its data. Existing profiles, contacts, invitation
> relationships, direct chats, groups, and saved messages are retained. Group
> invitation confirmation and Retry were introduced in 0.2.1 and require
> 0.2.1 or later on each participating
> device. Existing contacts do not
> need a new invitation. If either device
> is upgrading from 0.1.5 or earlier, create a new invitation/QR code after both
> upgrades because older invitations do not contain the signed local connection
> hint.**

After upgrading, open **Settings** on every participating device and check the
version shown at the bottom. It must say **Mesh Chat 0.2.12** before accepting a
new one-to-one request or creating or retrying a group invitation. If one
device still shows 0.2.8 or an earlier
version, close Mesh Chat,
install the current package over the existing app, and reopen it without
clearing app data.

To install it without a computer:

1. Copy the APK to the Android phone, for example with a USB cable, cloud drive,
   or private file transfer.
2. Open the APK in the phone's Files app. If Android blocks it, follow the prompt
   to allow **Install unknown apps** for that Files app or browser only.
3. Tap **Install**, then open **Mesh Chat**.
4. Grant camera access when you choose to scan an invitation QR code, and
   allow local-network access if your OS asks for it.

For an attached phone with USB debugging enabled, install or replace it with:

```text
adb install -r dist/mobile/mesh-chat-0.2.12-android-arm64-debug.apk
```

Use the adjacent `.sha256` file to verify the 0.2.12 APK before transferring
it. The Android packaging metadata uses version name 0.2.12 and
version code 2012,
with minimum API 24, target API 36, and only the `arm64-v8a` native
architecture. Its verified size, hash, signature, embedded artwork, and package
inspection are recorded in the 0.2.12 table in [TESTING.md](TESTING.md); do not
substitute a hash from an older release. The development APK
uses an Android debug certificate for direct testing; it
is not a Play Store release. A published build needs a private release keystore
and should be distributed as an Android App Bundle.

The 0.2.7 source adds regressions for callback lock inversion, per-record retry
yielding, bounded command-journal retention, actionable desktop timeout errors,
and the complete phone-first/desktop-reply exchange. See [TESTING.md](TESTING.md)
for the recorded results. No automated result substitutes for a physical
Windows-to-Android retest of the exact 0.2.12 installer and APK, which remains a
release gate for sensitive use.

After first launch, create a display name. On the inviting device choose
**Start a chat** during onboarding, or **New chat** later. The full invitation
appears in a read-only box at the top, followed by Copy, Share, Save, and QR
options. On the other device choose **Join a chat** during onboarding, or
**New chat** > **Open an invite** later, then paste the invitation or scan the
QR code. Keep both apps open and on the same local network while they connect.
The joining device says **Trying to reach...** until the request has actually
reached the other endpoint; only then does it say that it is waiting for
acceptance. The inviting computer displays a foreground **Connection request**
with Accept and Decline, even if its invitation window is still open. The chat
does not open on both devices until the inviter chooses **Accept**.

An invitation exchanges identity information; it does not itself provide an
Internet route. Version 0.1.6 introduced Reticulum nearby discovery plus the
signed direct local connection from a newly generated invitation; version
0.2.12 retains that connection behavior, keeps reverse-route attachment
non-blocking during approval, and prefers the authenticated path learned over
the signed invitation client before handing a direct message to LXMF.
The direct fallback is enabled by default and can be changed under **Settings**
with **Use a direct local connection**. If the phone remains on **Trying to
reach...**, confirm that both devices use the same non-guest local network,
disable client/AP isolation on that network, allow Mesh Chat and local-network
traffic through the computer firewall, and keep both apps in the foreground.
Reticulum nearby discovery uses local IPv6 multicast; the direct fallback uses
an ordinary local TCP connection when that multicast path is unavailable.

### iPhone and iPad — build and sign on a Mac

The iOS client source and packaging flow are included, but an iOS app cannot be
built or signed on Windows or Linux. It must be built on macOS with the full
Xcode application and an Apple development team. The build embeds CPython,
Reticulum, and LXMF inside the app; it does not connect back to a desktop.

On a configured Mac, follow [Build Android and iOS](#build-android-and-ios).
For personal development, select the phone in Xcode and install the signed app
directly. For other users, upload the generated IPA to App Store Connect and
use TestFlight or the App Store. Copying an arbitrary IPA to an iPhone will not
work because iOS requires a matching signature and provisioning profile.

### Windows — installer package paths

Before installing, confirm that:

- You are using 64-bit Windows on an NTFS volume that supports EFS. Windows
  Home normally does not provide EFS, so the messaging service will fail closed
  there rather than store private RNS/LXMF state without protection.
- Microsoft Edge WebView2 is installed. It is normally already present on
  supported Windows 10 and Windows 11 systems.
- You trust the package source. The current development packages are not
  code-signed.

Choose one verified installer from the immutable release directory
`dist\desktop\releases\0.2.28\x86_64-pc-windows-msvc\bundle`:

- `nsis\Mesh Chat_0.2.28_x64-setup.exe` — normal interactive setup.
- `msi\Mesh Chat_0.2.28_x64_en-US.msi` — MSI package for Windows deployment
  tools or manual installation.

For a portable test without installing, run `mesh-chat.exe` with its sibling
`mesh-chat-service.exe` from
`dist\desktop\releases\0.2.28\x86_64-pc-windows-msvc`. Close every
older Mesh Chat process first because the single-instance guard will otherwise
return to the older window. Confirm **Mesh Chat 0.2.28** in Settings before
testing.

Do not use an older unversioned developer output merely because it is still at
`src-tauri\target\release\mesh-chat.exe`. A running build can keep that file and
its sidecar locked while a newer release is packaged elsewhere. The immutable
versioned `dist\desktop\releases` directory and its `manifest.json` are the
release authority; `dist\desktop\current.json` identifies the current set.

Verify a 0.2.28 installer against the SHA-256 value in the sibling
`manifest.json` and the 0.2.28 release record in [TESTING.md](TESTING.md).
`dist\desktop\current.json` records the current manifest hash. The recorded
older hashes do not apply to 0.2.28. These development packages are not
Authenticode-signed.

If an earlier Mesh Chat version is installed, close the running app and run the
0.2.28 desktop installer over the existing release. The current Android
companion remains 0.2.12 until workspace support reaches the mobile UI and completes
physical cross-device validation.
The package identities are unchanged, so existing profiles, contacts,
invitation relationships, and messages are retained; do not uninstall either
old app or clear its data first. Devices that were already connected on 0.1.6
can resume the same conversation without a new invitation. When upgrading from
0.1.5 or earlier, launch **Mesh Chat** from the Start menu, choose **New chat**,
and leave **Share an invite** selected. Use this newly generated invitation—do
not reuse a QR code or copied invitation created before 0.1.6. The dialog shows
the complete invitation in a read-only box at the top, with Copy, Share, Save,
expiry, and QR options below it. Leave that window open while the other person
joins: an incoming request appears above it with Accept and Decline.

Versions before 0.2.3 could leave a PyInstaller supervisor or worker running
after the window closed. That stale process could keep a valid EFS-encrypted
profile lock and was incorrectly shown as **Protected storage is unavailable**.
This condition did not remove encryption, write private data in plaintext, or
damage the profile. If the first 0.2.28 launch appears to do nothing, or an
older build shows that storage screen, restart Windows or use Task Manager to
end **Mesh Chat** and every `mesh-chat-service.exe` process, then install or
launch 0.2.28. Do not uninstall Mesh Chat or clear its data.

Version 0.2.3 gives profile-lock contention its own **profile is still in use**
message. On close, the desktop uses an independent deadline and terminates only
the recorded service PID tree—not processes selected by name—after the graceful
shutdown interval. The sidecar also watches its exact desktop parent PID and
exits if that parent disappears. Cleanup completes before the desktop exits, so
the same encrypted profile can be reopened immediately. A second launch still
forces a hidden window visible or recreates it from the application
configuration.

### macOS — build natively before installing

There is no verified macOS package in this repository yet. FileVault must be
active on the local volume containing the user's home directory, and Keychain
must be available. Build the package on the target Mac using the instructions
under [Build from source](#build-from-source).

The native build places the app bundle and, when the required Apple tooling is
available, a DMG under `src-tauri/target/release/bundle`. A distributable macOS
package should be code-signed and notarized. Install a trusted DMG by opening it
and dragging Mesh Chat into **Applications**.

### Linux — build for the target distribution

There is no verified Linux package in this repository yet. Before first run:

- The profile must reside on fscrypt, dm-crypt/LUKS, eCryptfs, gocryptfs, or
  CryFS-protected storage.
- A desktop Secret Service/keyring must be installed, running, and unlocked.
- WebKitGTK and the other Tauri runtime dependencies must be installed for the
  distribution.

Build on the target Linux distribution using [Build from source](#build-from-source).
Depending on the installed packaging tools, output appears under
`src-tauri/target/release/bundle` as an AppImage, Debian package, or RPM.

- AppImage: mark the file executable and run it.
- Debian/Ubuntu: install the generated `.deb` with the distribution's package
  installer.
- Fedora/RHEL/openSUSE: install the generated `.rpm` with the distribution's
  package installer.

### First launch

No Python installation, terminal, account, server address, or developer service
is required after installing a packaged build. Mesh Chat creates one local
identity, stores its device secret in the operating-system credential store,
and starts its bundled messaging service. On Android and iOS the service runs
inside the app process; desktop builds use the bundled sidecar. Grant
local-network access if the OS asks and LAN discovery is desired.

### Manage contacts

Choose the **Contacts** address-book control above the conversation list to
search saved contacts and review their trust state and security details. A
contact's name can be changed locally without changing the signed name from
their invitation. After comparing the displayed fingerprint through another
trusted channel, choose **Mark verified**; verification can be removed later.

Blocking pauses direct communication and can be undone without losing the
contact. **Delete contact** permanently erases the local direct conversation,
draft, delivery-control records, and contact entry. Existing active group
membership remains intact because groups retain their signed member identity
cards. A contact with a still-pending group invitation must first be removed
from that group invitation so an in-flight join cannot be silently broken.

### Delete a conversation from this device

Open a conversation and choose its trash control, then confirm **Delete**.
Mesh Chat permanently removes that conversation's local messages, saved draft,
and any chat payloads which are still waiting in this device's outbox. This is
a local privacy and list-cleanup action: it cannot recall a message already
handed to another device.

Deleting a direct conversation does not delete or block the approved contact.
Deleting a group conversation does not leave or close the group, change its
signed membership, or remove the cryptographic material needed for future
messages. The conversation stays out of the normal list until a fresh incoming
message arrives. To start it again yourself, choose **Show deleted** above the
conversation list (or search for the contact or group), then open the result.
Restoring the empty conversation does not restore its deleted history.

### React to a message

Open a conversation, then tap or click the smile-plus **Add reaction** control
on the message. Choose one of the six quick reactions, or select **More
emojis** to browse eight categories and search 253 common choices. To use any
other official emoji, paste it or enter it with the phone or computer's emoji
keyboard in **Use emoji keyboard**, then choose **Use emoji**. Mesh Chat
accepts one exact fully-qualified Unicode Emoji 18.0 sequence; it does not
silently repair malformed, text-style, or partial sequences. Reaction chips beneath the
message show the total for each emoji; your own reaction is highlighted.
Selecting a different emoji replaces your previous reaction, while selecting
your highlighted reaction again removes it.

Reactions work in direct chats and for active members of private groups.
Readers of an announcement channel may react even though only the owner can
post messages. Like the messages themselves, reaction updates are sent as
authenticated, individually encrypted Reticulum/LXMF traffic. They do not use
a central service, an analytics endpoint, or a fallback messaging protocol.
Both peers should run Mesh Chat 0.2.12 for the expanded set and the same local
artwork. Version 0.2.10 understands the expanded Unicode reactions but depends
on operating-system emoji fonts; version 0.2.9 interoperates for the original
six reactions but ignores other Emoji 18 choices; versions before 0.2.9 ignore
reactions. Ordinary chat continues in every case.

Version 0.2.11 renders reaction buttons, the picker, and reaction-count chips
from bundled palette-optimized Twemoji 17.0.3 sprite sheets pinned to commit
`b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`. The picker is fully covered
(253 of 253 choices), and local artwork covers 3,944 of the complete 3,963-entry
Emoji 18 catalog. For the 19 new Emoji 18 entries not yet present in that open
artwork release, Mesh Chat shows a stable neutral **18** tile and uses the
catalog name for accessibility. A missing or failed local image also stays on
the neutral tile instead of exposing an operating-system tofu glyph. These are
presentation rules only: the exact Unicode sequence remains the value counted,
encrypted, stored, and sent to peers.

All sprite sheets, their manifest, attribution, and license are inside the app.
Mesh Chat does not contact a Twemoji CDN—or any other artwork service—at
runtime. Settings displays **Emoji artwork: Twemoji (CC BY 4.0)**, with full
source and license details in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Private groups and announcement channels

Version 0.2.0 introduced the group controls described here. Version 0.2.1 introduced
confirmed invitation delivery, Retry, and mobile reliability improvements. A
previously downloaded installer or APK does not update itself; install the
0.2.12 artifact on every participating device before testing direct chats or
groups.

Use the same current Mesh Chat version on the owner device and every invited
device. A working one-to-one conversation does not prove that an older build
understands the newer signed group invitation and membership records. Upgrade
both devices before creating or retrying a group invitation; preserve the
installed app data when upgrading.

Mesh Chat supports small, invitation-only private groups and private
announcement channels. A group lets every member post. A channel uses the same
private delivery model but allows only its owner to post in the current release. The signed
protocol reserves an admin role for a future role-management interface, but
this release cannot assign it. Neither conversation type is
public or discoverable, and neither requires a group server. Group messages are
text-only in this release.

Before creating one, connect with and approve every person as an ordinary Mesh
Chat contact. Then:

1. Choose **New group**, then select **Private group** or
   **Announcement channel**.
2. Enter a **Name**, select approved contacts, and choose **Create group** or
   **Create channel**. The initial limit is eight people including you.
3. Each selected person receives a **Group invitation** and must choose
   **Accept invitation**. Before accepting, review the owner security details,
   current members, posting policy, and the notice that history starts when
   joining. An invitation does not add someone silently.
4. Wait for accepted members to appear in the signed membership list before
   relying on them as recipients.

Group invitations travel as ordinary encrypted Reticulum/LXMF deliveries.
There is no Mesh Chat server, Firebase/APNs push notification, or other central
service that can wake an unreachable phone. The invitation appears on the
recipient only after Mesh Chat is running, a Reticulum path is available, and
the recipient has stored and verified it. With the default local connection,
keep both apps open on the same non-guest network. In particular, keep Mesh
Chat in the foreground on Android while the invitation and acceptance travel:
Android may suspend the embedded messaging runtime after the app is
backgrounded. Also allow local-network traffic, remove battery restrictions
during testing, and check wireless client isolation and the computer firewall.

On the owner device, open **Members & security** to see the state beside each
invited person:

- **Invitation queued** means the encrypted invitation is safely in the local
  outbox, but there is not yet evidence of a usable recipient path.
- **Trying to find device** means Reticulum is still resolving a path or the
  recipient's current delivery keys are not yet available.
- **Sending invitation** means a delivery attempt is in progress; it is not
  proof that the recipient can review the invitation.
- **Stored securely for delivery** means an explicitly configured LXMF
  propagation node accepted the encrypted object. It does not mean the phone
  received it.
- **Reached device · confirming receipt** is endpoint-level evidence while
  Mesh Chat waits for its application receipt.
- **Invitation ready for review** means the recipient stored the verified
  invitation and returned that application receipt. It still does not mean the
  person accepted it.
- **Invitation expired** (shown as **invite expired** after cleanup) or
  **Invitation needs attention** is a terminal or actionable failure, not a
  successful delivery.

Mesh Chat retries pending invitation deliveries automatically with bounded
backoff while it is running. If an invitation is still pending and has not
expired, the owner can use the circular **Retry invitation** control beside
that person in **Members & security**. Retry starts an immediate attempt and
uses the contact's newest approved connection hints; it does not bypass
Reticulum, weaken identity checks, or create a cloud route. Put both devices in
the foreground on a usable network before pressing Retry. An expired signed
invitation cannot be revived by Retry.

The conversation header shows the member count and either **Everyone can
post** or **Only the owner can post**. Open **Members & security** to
review the signed membership epoch and member controls. Group delivery is
tracked for each intended recipient. Labels such as **Sending to 4**,
**Delivered to 3 of 4**, **1 pending**, **Partially delivered**, or
**Expired for 1** mean exactly that; one member's receipt is never presented as
delivery to the whole group.

The owner can use **Remove** for another active member or **Close group** to
publish a terminal signed membership version. Other members can use
**Leave group** to send the owner a signed request. The local device stops participating
immediately; removal from the shared roster becomes authoritative in the next
owner-signed membership version. Each destructive action requires inline
confirmation. This first interface does not yet change roles, rename an
existing group, or switch its posting policy after creation.

For privacy, a new member receives no earlier messages. Removing a member stops
future copies after devices learn the new signed membership version, but it
cannot erase messages already delivered. On a partitioned network this update
is eventual rather than instantaneous. Members can continue chatting while the
owner is offline, but joining and removal wait for the owner. The current
interface does not expose role, name, or posting-policy changes. Permanent loss
of the owner's identity freezes safe
membership changes, so create a replacement group if that happens.

Under the hood, one logical group message is sent as an individually signed and
ratchet-encrypted LXMF copy to every other active member. Mesh Chat does not use
a shared RNS group key, a transport outside Reticulum/LXMF, or a hosted group
relay. This
preserves the one-to-one security boundary but makes cost grow with membership,
which is why large or public channels are not supported. See
[ADR 0004](docs/adr/0004-private-groups-over-individual-lxmf.md) for the full
tradeoffs.

## What is implemented

- A reusable Python service pinned to RNS 1.5.5 and LXMF 1.2.0 on desktop,
  Android, and iOS.
- A bounded, versioned, length-prefixed stdin/stdout protocol with no localhost control server.
- Tauri-owned desktop sidecar lifecycle and embedded native mobile runtimes;
  vault secrets never enter the React renderer, process arguments, or
  environment.
- Signed, bounded invitation links/text/files/QR codes with identity-to-destination validation and optional TCP hints.
- Contact requests and explicit acceptance, identity-change suspension, blocking, and independent verification state.
- Durable encrypted contacts, history, drafts, outbox, command journal, deduplication, and receipt jobs.
- Direct and propagated LXMF adapters with recipient-ratchet requirements and accurate evidence mapping.
- Durable encrypted emoji reactions in direct chats, private groups, and
  announcement channels, with one replaceable/removable reaction per actor and
  compact per-message counts.
- Fully local emoji presentation using pinned, palette-optimized Twemoji
  sprite sheets for all 253 picker choices and 3,944 of 3,963 Emoji 18
  sequences, plus named neutral fallbacks for the remaining 19; no CDN or
  runtime artwork request.
- Small private groups and owner-only announcement channels using individual
  LXMF fan-out, explicit invitations, owner-signed membership epochs, and
  per-recipient receipts; no shared group destination or history backfill.
- Separate opt-in Reticulum transport and LXMF propagation roles.
- An accessible React interface for first launch, invitations, requests, conversations, connection help, search, and advanced roles.
- A four-process A→B→C→D real-stack topology harness with shared-instance and AutoInterface shortcuts disabled.

## Development status and platforms

The source and packaging flow targets Windows, macOS, Linux, Android, and iOS. Each native
build uses the platform credential store and refuses to start the messaging
service unless the complete RNS/LXMF workspace has verified at-rest protection:

| Platform | Required protected storage | Packaging status |
| --- | --- | --- |
| Windows | NTFS EFS; Mesh Chat enables and verifies inheritance on its profile directory | 0.2.28 x64 EXE, NSIS, and MSI built, hashed, and immutably published; the packaged sidecar topology passed, while a host-window walkthrough, in-place installation, and physical Windows↔Android testing remain pending |
| macOS | Active FileVault on the local user-data volume containing the app profile | Native build path implemented; macOS package test pending |
| Linux | fscrypt on the profile, dm-crypt/LUKS beneath its filesystem, or a recognized eCryptfs/gocryptfs/CryFS mount | Native build path implemented; distribution package tests pending |
| Android | App-private internal storage, Android Keystore-wrapped vault key, backups disabled | 0.2.12 arm64 debug APK built, hashed, v2-signature-verified, and inspected; physical installation and Windows↔Android testing remain pending because no device was attached |
| iOS/iPadOS | Complete file protection in the app container and a ThisDeviceOnly Keychain key | Native plugin and signed build path implemented; Mac/Xcode build and device test pending |

The app fails closed with actionable storage guidance when these conditions or
the native credential service are unavailable. Desktop sidecars must be built
on their target operating systems. Android can be built on Windows, macOS, or
Linux; Apple requires iOS builds and signing to run on macOS with Xcode.

## Build from source

Prerequisites:

- Node.js 20 or newer and pnpm 11.19.0
- Python 3.11–3.14
- Rust 1.77.2 or newer
- [Platform build prerequisites for Tauri 2](https://v2.tauri.app/start/prerequisites/)

Create and activate a virtual environment, then install the pinned service
dependencies. On macOS or Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r service/requirements-dev.lock
pnpm install --frozen-lockfile
```

On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\service\requirements-dev.lock
pnpm install --frozen-lockfile
```

Use the deterministic release driver for routine versioning and delivery:

```text
python scripts/release.py check
python scripts/release.py verify
python scripts/release.py version 0.2.13
python scripts/release.py build --platform all
```

`version` validates and synchronizes the npm, Tauri, Cargo, Cargo lock, Python,
and derived Android version metadata in one transaction. `build` runs the test
suite once, builds the selected desktop and/or Android artifacts, verifies their
manifests and hashes, and writes a machine-readable report below
`dist/reports/<version>`. A successful run needs no LLM orchestration; on a
failure, `dist/reports/latest.json` identifies the failed stage and its log.
`--skip-tests` is reserved for CI jobs which already tested the exact commit.

GitHub Actions runs the same commands: `CI` validates each pull request and
main-branch push, and `Release build` verifies a `vMAJOR.MINOR.PATCH` tag or
manually supplied version before building Windows and Android concurrently.
pnpm, pip, Cargo, and Gradle
caches are reused across runs. The workflows become active after this workspace
is committed and pushed to a GitHub remote.

The lower-level desktop command remains available for platform debugging:

```text
python scripts/build_desktop.py
```

Or run its two phases independently:

```text
python scripts/build_sidecar.py
pnpm desktop:build
```

Windows development helpers are also included:

```powershell
.\scripts\build-sidecar.ps1
.\scripts\desktop-build.cmd
```

Build outputs are written below `src-tauri/target/release/bundle`:

| Build host | Expected output |
| --- | --- |
| Windows | MSI and NSIS setup executable |
| macOS | `.app` bundle and DMG when DMG tooling is available |
| Linux | AppImage, `.deb`, and/or `.rpm`, depending on installed tooling |

The complete desktop build command also verifies that the executable version
and sibling sidecar belong to the same release, then publishes an immutable
copy below `dist/desktop/releases`. Release testing must use that versioned copy
or an installer extracted from the same verified set, never a pre-existing
unversioned Cargo output.

Development builds are not automatically signed. Follow Tauri's
[distribution guidance](https://v2.tauri.app/distribute/) before publishing a
package to other users.

## Build Android and iOS

Both mobile clients use the same React interface and Python messaging core as
desktop. The desktop executable sidecar is replaced by a native Tauri plugin:
Chaquopy embeds Python on Android, and a CPython XCFramework is embedded on iOS.

### Android build

Install Node.js 20+, pnpm 11, Python 3.13, Rust, Android Studio, Android SDK
Platform 36, Android Build Tools 36, and NDK 28.2.13676358. Set `JAVA_HOME` and
`ANDROID_HOME`/`ANDROID_SDK_ROOT` if Android Studio did not configure them, then
run:

```text
pnpm install --frozen-lockfile
python scripts/build_android.py
```

The script initializes the Tauri Android project when necessary, builds an
arm64 app, works around Windows systems where developer-mode symlinks are not
enabled, and writes the APK plus checksum to `dist/mobile`. The source of truth
is the immutable `dist/mobile/releases/<version>/android-arm64-debug` directory;
the top-level APK is a verified convenience alias recorded by `current.json`.

### iOS build

Use a Mac with the latest stable full Xcode installation, Node.js 20+, pnpm 11,
Python 3.13, and Rust. Add an Apple account in Xcode and configure a development
team for bundle identifier `com.meshchat.mobile`. The provisioning profile must
include the multicast networking entitlement used for nearby Reticulum peers.
Then run:

```sh
pnpm install --frozen-lockfile
python3 scripts/build_ios.py
```

The script downloads the pinned Python 3.13 iOS support XCFramework, verifies
its SHA-256 checksum, stages only platform-independent RNS/LXMF packages,
converts standard-library extension modules into signed iOS frameworks, and
runs `tauri ios build`. A successful signed build writes an IPA beneath
`src-tauri/gen/apple/build`. Apple signing and App Store validation remain
release gates and cannot be verified from a Windows build host.

Run focused verification:

```text
python scripts/test.py
```

Windows developers can equivalently run:

```powershell
.\scripts\test.ps1
```

The real topology harness is opt-in because it opens local TCP listeners and launches four processes:

```sh
MESH_CHAT_RUN_NETWORK_TESTS=1 python -m pytest service/tests/test_topology_harness.py -v
```

The equivalent PowerShell command is:

```powershell
$env:MESH_CHAT_RUN_NETWORK_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_topology_harness.py -v
```

The direct local fallback has a separate opt-in two-process harness. It turns
off automatic nearby discovery so signed TCP hints in both directions are the
only available paths. It times reverse-route approval, then exercises direct
chat and receipt, group invitation/join/message, and another direct message
after group activity:

```sh
MESH_CHAT_RUN_DIRECT_LAN_TESTS=1 python -m pytest service/tests/test_direct_lan_harness.py -v
```

The PowerShell equivalent is:

```powershell
$env:MESH_CHAT_RUN_DIRECT_LAN_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_direct_lan_harness.py -v
```

For the at-rest variant, also set
`MESH_CHAT_REQUIRE_PROTECTED_STORAGE=1`. That run must fail on unprotected
storage rather than weakening the requirement.

## Repository map

- `service/src/mesh_chat/` — reusable messaging, protocol, storage, invitation, and RNS/LXMF adapters
- `src-tauri/` — credential-store, sidecar lifecycle, deep-link, IPC validation, and CSP boundary
- `plugins/tauri-plugin-mesh-runtime/` — Android/iOS embedded Python bridge and native device key storage
- `src/` — React messenger interface; no private identity or vault access
- `service/tools/topology_harness.py` — isolated real-stack mesh probe
- `scripts/` — repeatable packaging and verification commands
- [ARCHITECTURE.md](ARCHITECTURE.md), [PROTOCOL.md](PROTOCOL.md), [THREAT_MODEL.md](THREAT_MODEL.md), [TESTING.md](TESTING.md) — security and integration record
- [WORKSPACE_SPEC.md](WORKSPACE_SPEC.md) — proposed multi-channel workspace product and implementation specification

No external runtime service is needed or contacted. Installation downloads and package distribution are outside the messaging path.
