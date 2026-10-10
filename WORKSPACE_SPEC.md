# Workspace Feature Specification

Status: reviewed proposal

Last reviewed: 2026-10-06

Workspace adds a shared collaboration boundary to Mesh Chat: one member
directory, public and private channels, one-to-one workspace direct messages,
roles, local search, unread state, and a consistent invitation flow. It keeps
the existing security model. Every payload still travels through Reticulum and
LXMF as an individually addressed, recipient-ratchet-encrypted message. A
workspace is an authorization and organization layer, not a hosted server or a
shared group key.

The first beta is intended to be the primary asynchronous text chat for a
trusted team of two to eight people. It is not a drop-in Slack replacement. A
team must accept peer-dependent delivery and history, manual owner
administration, no hosted backup or push service, and no in-app file sharing.
Sixteen- and 32-member configurations remain release candidates until their
separate scale gates pass.

## Product scope

A successful beta lets a small team:

- create and switch between workspaces without creating cloud accounts;
- invite people who are not already approved contacts;
- organize text conversations into public and private channels;
- use one-to-one direct messages without changing global contact trust;
- use threads, mentions, reactions, edits, and deletion tombstones;
- search locally retained, authorized history; and
- see honest delivery, synchronization, and administrative states.

The default cooperative retention preference is 90 days. A device can find
only the history it retained or recovered from an authorized reachable peer.
No copy held by a central service exists to fill every gap.

Slack comparison points below were checked on 2026-10-06 and must be
revalidated before release because Slack can change its plan. Slack's free plan
advertises 90 days of searchable history, public and private channels, file
sharing, up to ten apps, and one-to-one audio and video meetings. Slack also
states that free-workspace data older than one year is permanently deleted on a
rolling basis. See Slack's [free plan overview](https://slack.com/pricing/free)
and [free workspace limits](https://slack.com/help/articles/115002422943-Usage-limits-for-free-workspaces).

| Capability | Workspace beta | Explicit limit or later work |
| --- | --- | --- |
| Public and private channels | Included | 32 active channels in beta; not marketed as unlimited |
| Channel messages | Included | Fan-out cost grows with active destinations |
| Direct messages | Included | One-to-one and workspace-scoped; use a private channel for more people |
| Threads, mentions, reactions, edits, and tombstones | Included | Remote deletion cannot erase plaintext already exposed |
| Searchable history | Included for locally available authorized records | Peer catch-up cannot guarantee a complete record |
| Data durability | Encrypted copies on member devices | No authoritative central copy, cloud backup, legal hold, or guaranteed recovery |
| Files and attachments | Not included | Links are text only; no automatic preview, fetch, upload, download, or proxy |
| Multiple devices | Included after the linked-device increment | Every device has a distinct identity; private identities are never cloned |
| Notifications | Local notifications while the embedded runtime is executing | No Firebase, APNs, or hosted push; suspended devices reconcile on resume |
| Owner recovery | Planned rotation and transfer are included | Permanent loss of the authority device freezes administration in v1 |
| Moderation and compliance | A member may hide content on that device | No remote administrative deletion, compliance export, or enforced retention |
| Calls, apps, bots, and workflows | Not included | Meeting links may be shared as ordinary text |
| Import and export | Not included | No Slack import, workspace backup, or compliance export in v1 |

## Product principles

- Preserve the existing trust boundary. Workspace data does not introduce an
  HTTP service, cloud account, shared workspace cipher, or raw
  `RNS.Destination.GROUP` fallback.
- Make authorization cryptographic. The service validates membership, roles,
  channel visibility, and posting policy from signed records rather than UI
  state.
- Separate a person from a device. A member has a stable workspace-scoped ID
  and one or more independently keyed devices.
- Commit locally before networking. A mutation is durable and idempotent before
  a background scheduler attempts any delivery.
- Report partial availability honestly. Delivery, administrative changes,
  channel discovery, and history recovery are eventual on a partitioned mesh.
- Keep workspace public content private from outsiders. A public channel is
  visible to active members of that workspace, not the wider network.
- Retain compatibility. Existing contacts, direct chats, private groups, and
  announcement channels continue to work unchanged.

## Core concepts and identifiers

**Workspace** is the top-level administration and discovery boundary. It has a
stable ID, a name of 1 to 64 normalized characters, an optional description of
up to 250 characters, policies, a membership chain, and one owner member.
Custom image icons are not part of v1. The UI derives initials and a local
color from the workspace ID.

**Member** is a person represented inside one workspace by a fresh random
member ID, a display name of 1 to 64 normalized characters, a role, a status,
and one or more device cards. Display names need not be unique. The interface
always has a stable short disambiguator available. Membership does not create
a global contact.

**Device card** binds one RNS public identity to its derived LXMF destination,
fingerprint inputs, connection hints, member ID, and creation time. The device
signs its card; a workspace manifest admits it. A self-signed card alone does
not prove that a new key belongs to an existing member.

**Owner member** is the sole member with the owner role. Human permissions are
assigned to this member, but manifest-writing power belongs to one specific
device.

**Owner authority device** is the one admitted device authorized to sign the
next workspace manifest. Other devices of the owner are ordinary member
devices until authority is deliberately rotated to one of them. The authority
device cannot be removed, disabled, or used to leave until a valid authority
rotation or ownership transfer commits. Losing it leaves existing chat usable
but freezes membership, roles, workspace policy, public-channel recovery,
ownership transfer, and closure.

**Public channel** is discoverable and readable by every active workspace
member. Messages are delivered to every active member device whether or not
that member subscribes. Subscription controls presentation, unread badges, and
notifications only. `#general` is created with the workspace, cannot be made
private, left, archived, or deleted, and is always subscribed.

**Private channel** has its own signed member chain. Its ID, name, topic,
roster, controls, and messages are sent only to members. A nonmember owner or
admin cannot discover, inspect, close, or recover it.

**Workspace direct message** is a one-to-one conversation between active
workspace members. It fans out to the recipient's devices and the sender's
other devices but remains separate from approved-contact conversations.

**Channel manager** is the single signer for a channel's metadata chain and,
for a private channel, its member chain. The creator starts as manager.
Management of an existing channel does not disappear when workspace policy
later restricts who may create new channels.

## User experience

### Create a workspace

The existing local identity remains a device identity. From the conversation
list, a user selects **Create workspace**, enters a name and optional
description, and reviews three facts:

1. This device becomes the first owner authority device.
2. Every public-channel message creates an encrypted delivery leg for every
   other active member device.
3. Delivery and history depend on reachable peers; approved propagation nodes
   can improve offline delivery but are not a hosted workspace service.

Creation atomically commits the genesis, epoch 1 manifest, owner member and
device card, `#general`, initial subscription, conversation index, and summary.
The UI shows the workspace only after that transaction succeeds.

The owner can later change the workspace name and description. The change is
part of the next manifest. A member can submit a signed display-name change;
the owner applies it in a later manifest. Names are presentation fields, never
authorization identifiers.

### Invite and join a member

The owner creates one single-use invitation per person. It expires after seven
days by default and never later than 30 days. It can be shown as a QR code when
the encoded value fits or copied as text or a URI. Calling it a file or an
attachment is deliberately avoided.

The signed invitation contains the workspace ID and genesis digest, name and
description preview, current owner and authority-device fingerprints, offered
manifest digest, member count, history and retention policy, connection hints,
a random nonce, expiry, and `use_limit = 1`. It also contains or references the
bounded authority-certificate chain needed to prove that the current signer
descends from genesis. The offered manifest is an authenticated ancestor
checkpoint for this new joiner, not a requirement that it remain the newest
epoch. Intervening valid manifest updates do not invalidate an unused invite.
Ownership transfer, closure, explicit revocation, expiry, or successful use
does invalidate it.

An invitation is a bearer request token, not proof of membership. The joining
installation generates a fresh workspace-scoped member ID and device card,
shows the workspace preview and owner fingerprint, and sends a signed join
request. The owner verifies the device fingerprint and approves or declines
the request. Approval atomically consumes the invitation nonce, publishes a
new manifest with a unique member ID, and creates required control deliveries.
Membership starts only after that manifest is validated. A join never approves
a global contact.

The unknown-source network exception is limited to `workspace_join`. Before
dispatch, the network re-derives the claimed LXMF destination from the exposed
public identity and independently verifies both the native packet signature
and the inner join signature. A valid packet creates only a bounded pending
workspace request. Every other workspace packet from an unknown source is
dropped.

### Navigate channels and people

The main shell adds a workspace switcher above the conversation list. Each
workspace contains:

- **Threads** and **Mentions**;
- subscribed public channels and visible private channels;
- one-to-one direct messages;
- **Browse channels** and **People** directories; and
- **Workspace settings** when the local role permits them.

Existing chats and groups stay in a separate **Personal** space. Switching a
workspace changes directories, search scope, unread counts, and conversation
lists without changing the device identity.

`#general` is subscribed for everyone. Creating a public channel subscribes
its creator; other members find it in **Browse channels**. Unsubscribed public
channels are still received and stored but do not create ordinary unread
badges. A structured direct mention still appears in **Mentions** unless the
member explicitly mutes mentions. Before operating-system notifications ship,
notification choices affect only in-app behavior.

Public-channel discovery is peer-assisted. While summary exchange is
incomplete, **Browse channels** says **Directory may be incomplete** rather
than claiming that one peer knows every channel.

### Create and manage channels

A channel has one display name of 1 to 80 normalized characters and an
optional topic of up to 250 characters. Comparisons use a documented normalized
key, but the random channel ID is authoritative. If a partition creates two
valid channels with the same comparison key, both remain valid and receive
stable short disambiguators until renamed.

Public channel records go to all active members. A signed manager transfer must
reference the exact current channel head and be accepted by the successor. If
the manager disappears, the owner authority device may issue an explicit
public-channel recovery transition referencing that head. This is not an
unsigned override. Conflicting valid records at one version suspend only that
channel. Archival is terminal in v1.

Private channel records go only to listed members. The manager must transfer
management before leaving or being deliberately removed. If the manager is
lost, membership and metadata changes freeze. Existing members may continue
chatting under the last valid chain or create a replacement. The owner may
recover a private channel only when the owner is already a current channel
member; safe recovery for a nonmember owner is deferred.

### Send and organize messages

Workspace messages support UTF-8 text up to 16 KiB, reactions, one-level
threads, structured mentions, edits, and author deletion tombstones. A thread
reply references one root; replies do not nest. Raw `@name` text is ordinary
text unless the composer inserts a stable member ID into the signed mention
list.

Any current device admitted for the author member may edit or delete that
member's message. Each mutation names its base event and carries a revision.
Concurrent revisions are retained and resolve deterministically by
`(revision, signer_device_destination, event_digest)`; the UI marks a conflict
until a later author revision selects or merges it. Different content signed by
one device at the same revision is equivocation and freezes mutation of that
message with a security warning. Reactions are one logical state per member and
emoji, not per device, and use the same deterministic revision rule.

Any member may hide a message locally. Workspace-wide moderation and remote
administrative deletion are outside v1. Dropping or pasting a file or image
shows **Attachments are not supported yet** and transmits no bytes. Ordinary
links remain plain links with no automatic preview or network fetch.

Delivery is shown at both levels, for example **Reached 12 of 18 people · 14
of 27 devices**. A person is reached when at least one active destination
acknowledges the event. The person is partial when another active destination
is pending or failed. An endpoint receipt is never labeled as a read receipt.

### Search and recover history

Search covers retained message text, threads, people, and channel names the
local member may access. The owner may choose 30, 90, 365 days, or indefinite
local retention. This is a cooperative application preference, not an
enforceable organization-wide deletion policy.

Every workspace event is signed once by its author before fan-out and stored in
that canonical form from the first increment. An authorized peer can later
forward the exact event without impersonating the author. Catch-up uses signed,
nonce-bound, expiring, count- and byte-bounded requests and responses. The UI
shows known coverage and permanent gaps. It never claims global completeness
beyond known signed per-author stream heads.

History disclosure follows this matrix:

| Conversation | Catch-up and retained access |
| --- | --- |
| Public channel | A currently active member may request available retained history, including pre-join history |
| Private channel | A current member may request only events from channel-manifest versions in which that member was included; no pre-admission backfill in v1 |
| One-to-one direct message | Either participant may request it; a newly admitted device for the same member may recover retained events |
| Left or removed member | No new catch-up or live delivery; previously delivered local data may remain as a read-only archive until retention or confirmed local erasure |

The receiver validates the author's historical permission under the event's
referenced controls and the requester's current conversation-specific
disclosure rule. A previously unseen event from an inactive author device is
rejected unless its digest was anchored by a pre-removal checkpoint allowed by
the history ADR. A missing anchor becomes an explicit permanent gap. Workspace
owners and admins gain no special access to direct-message history.

### Leaving removal and closure

The interface distinguishes these durable local states:

| State | Allowed behavior |
| --- | --- |
| `leaving` | Local sending stops immediately; a signed request waits for the owner manifest |
| `removed` | Network actions stop; cached authorized history is read-only |
| `closed` | The workspace is terminal and read-only |
| `forked` | All workspace-dependent sending and acceptance pause; diagnostics remain available |
| `locally_removed` | Encrypted local workspace records are erased after confirmation; re-entry requires a new invitation |

A nonowner can leave. The owner must transfer ownership before leaving. Closing
requires the owner authority device and creates a terminal manifest; no later
join, transfer, channel, message, or history transition is accepted. Leaving,
removal, and closure do not erase local history automatically. **Remove local
workspace data** is a separate destructive confirmation.

## Roles and policy values

There is one owner, zero or more admins, and ordinary members. Guest roles are
not included. Admins can handle ordinary channel work and submit owner-approval
requests, but only the authority device can publish a membership or role
manifest.

The protocol uses these exact policy values:

- `channel_creation`: `all_members | owner_and_admins`
- `posting`: `all_members | owner_and_admins`
- `invitation_requests`: `owner_only | owner_and_admins | all_members_request`

| Action | Owner | Admin | Member |
| --- | --- | --- | --- |
| Read and post in an authorized channel | Yes | Yes | Yes, subject to posting policy |
| Browse and subscribe to public channels | Yes | Yes | Yes |
| Create a channel | Yes | Yes | Subject to channel-creation policy |
| Manage a channel | When manager; public recovery through a signed transition | When manager | When manager |
| Recover a private channel | Only when already a current member | No special right | No special right |
| Create an invitation | Yes | Submit a request | Subject to invitation-request policy |
| Approve, remove, or change a role | Sign and publish | Submit a request | No |
| Change workspace metadata, retention, and policies | Sign and publish | No | Signed display-name request only |
| Rotate authority, transfer ownership, or close | Sign and publish | No | No |

The UI labels an unapplied request **Waiting for owner approval**. It never
presents a request as an effective membership change.

## Functional requirements

### Workspace lifecycle

- **WSP 001** Create genesis, epoch 1 manifest, owner member and authority
  device, `#general`, indexes, and local subscription in one transaction.
- **WSP 002** Support multiple workspaces per local profile and retain a
  Personal space for existing conversations.
- **WSP 003** Keep current direct-chat and group protocols byte-compatible.
- **WSP 004** Rotate owner authority and transfer ownership to one named
  admitted successor device through an accepted signed transition.
- **WSP 005** Treat conflicting valid workspace manifests or authority
  transitions as a security fork that pauses the workspace without choosing a
  branch.
- **WSP 006** Close a workspace only with a terminal signed manifest.
- **WSP 007** Expose leaving, removed, closed, forked, incomplete-sync, and
  locally removed states with only their permitted actions.
- **WSP 008** Require a durable renderer-generated `operation_id` for every
  mutation and commit its result atomically with domain changes.

### Membership and devices

- **WSP 010** Accept an out-of-band join without prior contact approval through
  the narrow verified unknown-source path.
- **WSP 011** Bind a join to the invitation nonce, genesis, workspace, offered
  manifest, fresh member ID, and device card.
- **WSP 012** Consume a single-use invitation and admit its member atomically in
  a later authority-signed manifest.
- **WSP 013** Enforce owner, admin, and member roles in the service.
- **WSP 014** Represent every device with a separate identity and destination;
  never copy private identity material.
- **WSP 015** Freeze each event's complete recipient-device set at commit and
  aggregate delivery without hiding failed devices.
- **WSP 016** Stop new delivery and reject previously unseen events from a
  removed device after removal is known, while documenting partition delay.
- **WSP 017** Identify exactly one owner authority device and prevent its
  removal until a valid rotation or transfer commits.
- **WSP 018** Link a device only with a one-time, expiring document
  countersigned by an admitted member device and the new device, followed by
  owner admission.
- **WSP 019** Support owner-signed workspace metadata changes and signed member
  display-name requests without using names as identifiers.

### Channels and conversations

- **WSP 020** Create mandatory public `#general` and keep it subscribed and
  unarchivable.
- **WSP 021** Support public and private channels, topics, terminal archive
  state, and the exact posting policy values.
- **WSP 022** Authorize public events from active workspace members and private
  events from active members of the referenced channel manifest.
- **WSP 023** Treat public subscription as local presentation state, not an
  access or delivery boundary.
- **WSP 024** Keep every private-channel identifier, control, roster, and event
  from nonmembers.
- **WSP 025** Support one-to-one workspace direct messages without changing
  global contact trust.
- **WSP 026** Keep channel and direct-message drafts local and encrypted.
- **WSP 027** Deliver or establish required control state before an event;
  quarantine a dependent event until its chain validates.
- **WSP 028** Discover public channels through bounded summary exchange and
  expose incomplete directories.
- **WSP 029** Use explicit signed channel transfer and recovery transitions;
  suspend a channel on a fork.

### Message history and search

- **WSP 030** Atomically commit a canonical event, derived state, frozen
  audience, delivery legs, index entry, and operation result before handoff.
- **WSP 031** Support reactions, one-level threads, structured mentions,
  author-member edits, and deletion tombstones.
- **WSP 032** Sign every canonical event before fan-out so an authorized peer
  can forward it without becoming its author.
- **WSP 033** Allocate one durable sequence for every event type in each
  device/conversation stream; deduplicate exact events and detect sequence or
  revision equivocation.
- **WSP 034** Offer bounded peer catch-up and expose ranges no authorized peer
  can provide.
- **WSP 035** Search retained local candidates only after rechecking historical
  entitlement and the current disclosure rule.
- **WSP 036** Apply retention to events, derived state, reactions, indexes,
  completed delivery legs, history jobs, and coverage data while retaining
  controls and tombstones as long as dependents require them.
- **WSP 037** Keep the seven-day live delivery expiry separate from the
  cooperative history window.
- **WSP 038** Apply the public, private, direct-message, and former-member
  disclosure matrix consistently to browse, search, and catch-up.
- **WSP 039** Track retained floors, known high-water marks, signed stream
  heads, and permanent gaps without promising a globally complete history.

### Reliability interface and platform behavior

- **WSP 040** Show accurate per-person and per-device delivery states and never
  label transport receipt as read.
- **WSP 041** Page workspace messages from the first increment; never place an
  entire workspace history in a startup snapshot.
- **WSP 042** Track encrypted local conversation, thread, and mention read state
  and support all, mentions-only, or muted notification preferences.
- **WSP 043** Provide actionable states for owner approval, missing controls,
  incomplete discovery or history, queue pressure, suspended mobile delivery,
  and forks.
- **WSP 044** Keep normal chat workflows independent of Reticulum expertise.
- **WSP 045** Present propagation-node recommendations separately and require
  local consent before changing approved network settings.
- **WSP 046** Return from send and control commands after the local transaction;
  perform bounded network handoff in a background scheduler.
- **WSP 047** Emit scoped, coalesced invalidations by workspace and conversation
  instead of refreshing a full application snapshot for each change.
- **WSP 048** Notify only while the platform runtime can execute and reconcile
  accurately after suspension without implying hosted push.
- **WSP 049** Erase local workspace data only through a separate confirmed
  action after leaving, removal, or closure.

## Protocol and authority model

Workspace traffic uses a new versioned custom application profile such as
`mesh-chat-workspace`. It does not change the current `mesh-chat` profile or
reinterpret group fields. Dispatch selects the custom type before parsing
profile-specific metadata. Unknown versions fail closed for that workspace and
do not break Personal conversations.

Canonical documents use UTF-8 JSON, sorted keys, compact separators, exact
field sets, base64url encodings, and domain-separated signatures. The enabling
ADR must freeze field schemas and encoded byte limits before implementation.
No single control document may exceed the current 16 KiB control boundary. If
the worst-case manifest does not fit, the protocol uses a signed root plus
bounded, counted, digest-addressed chunks; a chunk cannot grant authority by
itself and the manifest is inert until every chunk validates.

### Workspace identity

The creator generates a 32-byte random nonce. The stable ID is:

```text
workspace_id = first_16_bytes(
  SHA-256("mesh-chat:workspace:v1:" || creator_destination || nonce)
)
```

The receiver permanently pins the genesis digest on first validated import.
The creator destination is an immutable namespace anchor, not the current
owner authority. Ownership can therefore change without changing the ID, while
a disclosed nonce cannot be reused by another creator to construct the same
ID.

### Signed document families

| Document | Authority and purpose |
| --- | --- |
| `workspace_genesis` | Creator fixes ID inputs, genesis owner and authority device, metadata, and creation time |
| `workspace_manifest_root` and optional chunks | Authority device signs epoch, predecessor, authority device, members, devices, roles, policy, status, and removal checkpoints |
| `workspace_authority_transition` | Current authority offers a same-owner rotation or owner transfer; named successor device accepts before the final manifest |
| `workspace_device_card` | Device signs its member binding, public identity, derived destination, hints, and creation time |
| `workspace_device_link` | Existing admitted device and new device countersign member ID, current manifest, nonce, and expiry |
| `workspace_invite` | Authority device signs the one-use join token and bounded bootstrap proof |
| `workspace_join` | Joining device signs its fresh member request and device card against the invite |
| `workspace_leave_request` | Member device asks to leave at an exact manifest |
| `workspace_admin_request` | Admin or permitted member requests an invitation, removal, or role change without applying it |
| `workspace_channel_record` | Channel manager signs public metadata and archive transitions |
| `workspace_channel_manifest` | Private manager signs metadata, member set, and archive transitions |
| `workspace_channel_transfer` | Current manager and named successor accept transfer at the exact channel head |
| `workspace_channel_recovery` | Authority device recovers a public channel, or a private channel only when the owner is already a member |
| `workspace_channel_summary` | Active peer advertises bounded public channel IDs and head digests for anti-entropy |
| `workspace_control_ack` | Receiving device confirms that one exact workspace or channel control digest validated and became durable |
| `workspace_event` | Author device signs one message, edit, deletion, reaction, mention, or thread event |
| `workspace_event_checkpoint` | Author device signs known stream heads; the relevant removal control can anchor the checkpoint for safe later recovery |
| `workspace_history_request` | Eligible device signs nonce, exact scope, ranges, byte/event limit, and expiry |
| `workspace_history_response` | Authorized peer returns exact canonical events and continuation bound to the request nonce |
| `workspace_read_hint` | Linked device optionally signs encrypted local read-state hints; never a social receipt |

Each replayable document has an explicit replay key, expiry where applicable,
and count and byte bounds. The bootstrap bundle contains genesis, the offered
manifest root, and a hash-linked authority-certificate chain. It is trusted as
a checkpoint only by a new joiner after full verification and fingerprint
comparison. Existing members always extend their already validated chain. The
bundle has a total encoded limit fixed by the ADR; worst-case serialization,
including the maximum allowed number of authority transfers, must pass before
invitations ship.

### Manifest and channel chains

Workspace manifests form one authority-signed hash chain. A receiver applies
only the next expected epoch and holds a bounded number of future epochs inert
until predecessors arrive. Exactly one active owner member must contain the
named authority device. A valid authority transition names one successor
device, exact base manifest, nonce, and expiry; the successor accepts it before
the current authority signs the final changing manifest. Ownership transfer
also transfers or explicitly recovers management of `#general`.

Public and private channel records reference the exact workspace manifest that
authorized the operation. A delayed record under an obsolete epoch is not
silently reinterpreted after a role or membership change; the manager reissues
it against the current workspace state. Two valid records for the same channel
version suspend that channel. Two valid workspace or authority records for one
epoch suspend the whole workspace.

Canonical control records may be relayed byte-for-byte by authorized peers.
The outer LXMF source is the forwarder; the inner canonical signature identifies
the authority. The receiver validates the signer against the predecessor state
rather than equating authority with the native sender. A receipt acknowledges
the forwarding leg, not authorship.

### Canonical event envelope

Every message-related mutation uses one immutable `workspace_event` containing
at least:

- protocol version, workspace and conversation IDs, event ID, and event type;
- author member and device IDs;
- a durable per-device, per-conversation event sequence and previous event
  digest;
- workspace manifest digest and, where applicable, channel manifest digest;
- message or reaction target, base revision, thread root, and structured
  mention member IDs as applicable;
- exact payload and author-created time; and
- the author's domain-separated signature.

Sequences cover messages, edits, deletions, reactions, and thread replies, so a
gap detector does not miss mutations. Derived message and reaction state is
rebuildable from canonical events. The service stores original events rather
than duplicating their text into every delivery leg.

An author-signed checkpoint becomes a usable pre-removal anchor only when its
digest is committed by the relevant signed removal control: the workspace
manifest for a public stream or the private-channel manifest for a private
stream. The authority or manager may commit only a checkpoint it validated
before constructing that removal. V1 has no equivalent third-party anchor for
a direct message, so a device does not accept previously unseen DM events from
an inactive author. When the required anchor does not exist, the correct result
is a permanent gap rather than trust in the forwarding peer.

### Event acceptance and delivery changes

| Situation | Required behavior |
| --- | --- |
| New event arrives | Validate exact canonical form, author signature, sequence, historical workspace and channel permission, and current active author status before persistence |
| Private-channel event arrives | Also require the local member to remain entitled under the conversation disclosure rule |
| Unrelated workspace epoch advances | Keep queued legs for recipients who remain authorized; do not fail all older legs |
| A member or device joins | Never add it to the frozen audience of an already committed event; history catch-up is separate |
| A recipient is removed or loses private access | Cancel only that recipient's unhanded legs after the new control is known |
| An author is removed | Reject previously unseen events from that author unless a permitted pre-removal checkpoint anchors them; expose a gap |
| A required control is missing | Store the event in a bounded encrypted inert queue, request the chain, and withhold the application receipt until validation and durable persistence |
| A control or authority fork appears | Suspend the affected channel or entire workspace; never select a branch automatically |

A sender commits the audience under one exact control state. The scheduler
delivers missing controls first when its recipient-control acknowledgement
state is behind. Queue saturation drops the newest unvalidated dependent item
without an application receipt and exposes **Incomplete sync**. Initial queue
bounds appear under limits and may only be lowered by the protocol ADR.

## Local data and service boundary

All application content remains independently sealed in `VaultStore`. Record
IDs and SQLite-visible fields contain no workspace names, channel names,
member names, message text, or raw destination hashes.

The existing `list(kind)` path decrypts an entire record kind and is not
suitable for workspace paging or scheduling. Workspace v1 therefore requires
bounded sealed indexes from the first increment:

- a conversation head and linked pages of event references;
- derived message and reaction state records;
- sharded due-work buckets for the background scheduler;
- HMAC-keyed token shards for local search;
- summary records for startup, directories, unread state, and pending work;
- retained floor, high-water, seen-range, and gap records for each event stream;
  and
- a generation record for authorization and retention invalidation.

Index and page IDs are opaque keyed digests. An active conversation page has a
fixed maximum number and encoded size; when full it links to a sealed previous
page. Event, derived state, delivery legs, affected index pages, and the
operation result commit in one vault transaction. This design can use the
generic record table only if direct record lookup and bounded page updates meet
the benchmark. Otherwise an additive indexed schema needs a migration and a
metadata-leakage review before increment one.

Opaque page cursors bind the workspace, conversation or query, authorization
generation, retention generation, high-water mark, page, and offset under a
local MAC. A changed generation returns an explicit stale-cursor error instead
of silently mixing scopes.

### Data records

| Record kind | Purpose |
| --- | --- |
| `workspace` | Local summary, pinned genesis, current validated heads, policies, state, and local member |
| `workspace_manifest` | Canonical root, chunks, epoch, predecessor, authority, members, devices, policy, and status |
| `workspace_authority_transition` | Rotation or transfer offer, acceptance, result, and replay state |
| `workspace_invitation` | Nonce, offered checkpoint, expiry, revocation or consumption state, and signed document |
| `workspace_join_request` | Bounded pending member and device request |
| `workspace_device_link` | Countersigned link request and admission state |
| `workspace_channel` | Local channel summary, current head, manager, visibility, policy, and state |
| `workspace_channel_control` | Canonical public record, private manifest, transfer, or recovery transition |
| `workspace_event` | Immutable canonical event and author stream metadata |
| `workspace_message_state` | Rebuildable visible message revision, tombstone, and conflict state |
| `workspace_reaction_state` | Rebuildable per-member emoji state |
| `workspace_delivery` | Event reference, recipient member and device, state, attempt schedule, expiry, and failure code |
| `workspace_pending_event` | Bounded inert event awaiting controls or predecessor validation |
| `workspace_control_ack` | Per-destination known workspace and channel heads |
| `workspace_conversation_index` | Sealed bounded pages and high-water information |
| `workspace_subscription` | Local public-channel subscription and in-app preference |
| `workspace_notification_preference` | Conversation-wide local all, mentions-only, or muted preference |
| `workspace_read_state` | Local conversation, thread, and mention positions |
| `workspace_history_job` | Signed scope, ranges, continuation, coverage, gaps, limits, and expiry |
| `workspace_stream_coverage` | Retained floor, signed high-water, seen ranges, and permanent gaps |
| `workspace_search_index` | Encrypted HMAC token shard containing local retained event references |
| `workspace_due_work_index` | Sealed, sharded schedule of bounded network work |
| `workspace_draft` | Local encrypted draft by conversation |
| `workspace_operation` | Durable operation ID, input digest, outcome, and replay result |

Historical manifests and channel controls remain available at least as long as
any dependent event. Tombstones remain until at least the later of the
retention boundary and their durable receipt time plus the seven-day delivery
window. Pruning preserves coverage metadata so it does not create false missing
ranges. Final delivery legs are compacted or deleted on a schedule specified
by the storage ADR.

### Commands and events

Every mutation receives a renderer-generated durable `operation_id`, distinct
from the transport `request_id`. A retry with the same operation ID and input
digest returns the stored result. Reuse with different input is rejected. The
operation result or tombstone commits in the same transaction as the mutation.
A send also uses a renderer-stable logical event ID. Read-only list and search
commands do not enter the mutation journal.

The exact command allowlists include, as their increments arrive:

- workspace create, update, list, leave, close, local removal, authority
  rotation, and ownership transfer;
- invitation create and revoke, join submit, join approve or decline, member
  role or name update, member and device removal, device linking, and admin
  requests;
- channel create, update, archive, subscribe, manager transfer or public
  recovery, private member change, browse, and summary sync;
- event send, edit, delete, react, thread reply, and local hide;
- direct-message open or hide, draft update, read-state update, and notification
  preference; and
- bounded message list, directory list, search, history request, history job,
  delivery detail, and diagnostics commands.

Send and control commands return after durable enqueue. A background scheduler
performs network handoff with bounded concurrency, backpressure, and a sealed
due-work index, preventing large fan-outs from consuming the Tauri command
timeout. Signed route hints use a bounded LRU strategy; the implementation must
not assume that all workspace routes can remain active simultaneously.

The renderer receives bounded presentation models only. Service change events
contain the affected workspace, optional conversation, resource kind, and
generation. Events are coalesced. An overflow marker tells the renderer to
perform a bounded summary resync rather than requesting an unbounded global
snapshot.

## Limits and measurable targets

Initial limits are safety bounds, not claims of maximum protocol capacity.

| Item | Initial bound |
| --- | --- |
| Workspaces per local profile | 16 |
| Active members | 2 in increment one; 8 in beta; 16 and 32 are gated candidates |
| Devices per member | 1 until linked devices; then 3 |
| Active destinations | 8 before linking; up to 24 in beta after manifest-size and route tests; candidate tiers may allow up to 48 total |
| Active workspace destinations per profile | 96 |
| Active channels | 32 in beta, including `#general` |
| Private-channel members | No more than the currently enabled workspace member cap |
| Message text | 16 KiB UTF-8, subject to the canonical event envelope bound |
| Cooperative history preference | 90 days by default; 30, 365, or indefinite alternatives |
| Live delivery expiry | 7 days |
| Invitation | Single use; 7 days by default, 30 days maximum |
| Message page | 50 by default, 100 maximum |
| Search page | 50 maximum |
| Future workspace manifests | 8 inert records per workspace |
| Pending unknown-source joins | 32 per workspace and 4 per source fingerprint |
| Inert dependent events | 256 per workspace, 64 per sender, and 16 MiB per local profile |
| Pending delivery legs | 20,000 per workspace and 50,000 per local profile |
| Concurrent history jobs | 2 per workspace and 4 per profile |
| One history response | Bound by both event count and encoded bytes fixed in the history ADR |

The manifest-size gate serializes worst-case genesis, manifest root and chunks,
invitation and authority proof, transfer, device link, channel controls, event,
and history response. The advertised destination cap cannot exceed the largest
configuration that passes parser, IPC, QR-or-text invitation, and real-route
tests.

Performance evidence must name a reproducible hardware and OS profile before a
numeric result can pass. The benchmark data set contains 50,000 retained events
across eight members and 32 channels, linked-device delivery legs, edits,
reactions, tombstones, and realistic text sizes. It records cold and warm runs
and p95 over at least 30 samples. On that named release-minimum profile:

- the startup summary does not decrypt message bodies or scan all event or
  delivery records;
- the latest 50 messages load in under 500 ms after service readiness;
- desktop search returns its first page in under 2 seconds and mobile search in
  under 5 seconds;
- a send command commits and returns without waiting for route attempts; and
- restart restores pending work without duplication or a false delivered state.

Peak memory, vault growth, queue depth, battery use, bandwidth, and full fan-out
latency must be recorded with explicit pass limits before a candidate cap is
enabled. The spec deliberately does not invent those device-specific budgets.

## Security and failure behavior

Before invitations leave test builds, `THREAT_MODEL.md` must cover copied bearer
invitations, join floods, malicious history peers, multi-workspace device
linkability, admin and endpoint compromise, authority-device loss, transfer,
private-channel metadata, public fan-out correlation, route hints, and local
notification leakage.

The same device identity may be visible in more than one workspace. This can
let members correlate those memberships even though workspace content remains
encrypted. Eliminating that correlation would require per-workspace device
identities and is not promised by v1.

Validation covers exact fields, canonical encoding, all identity-to-destination
bindings, signatures, epochs, predecessor digests, roles, channel permission,
sequences, revisions, sizes, counts, expiry, replay keys, and retention before
persistence. Limits apply globally, per workspace, per authenticated actor, and
to unknown join sources.

Failure behavior is explicit:

- A workspace manifest or authority fork pauses all workspace-dependent sends,
  direct messages, history acceptance, membership, and channel transitions.
- A channel fork pauses that channel only.
- A missing predecessor creates bounded encrypted inert state and a chain
  request. No application receipt is sent before durable validation.
- Queue saturation drops the newest dependent item without a receipt and shows
  incomplete synchronization.
- A closed workspace accepts no later transition.
- Permanent authority-device loss freezes administration. The app offers
  diagnostics and creation of a replacement workspace, not an automatic branch
  choice.
- A currently authorized or compromised unlocked endpoint can retain all
  plaintext it receives. No UI claims guaranteed remote erasure.

Workspace and channel names must not appear in announces, logs, crash reports,
SQLite-visible IDs, or notification text when the user has enabled private
previews or the operating system requires them. Recommended propagation nodes
are never trusted automatically; the UI shows fingerprints and requires local
approval.

## Compatibility and migration

Existing private groups are not converted automatically. Their permanent-owner
IDs, eight-member cap, invitations, manifests, and history semantics remain
unchanged. A future **Create workspace from group** action may preselect members
and issue new invitations, but it creates a new workspace ID and does not copy
history without a separate explicit export design.

An older client safely ignores the new custom profile. Unsupported workspace
feature versions suspend only the affected workspace; they do not make
Personal conversations unavailable. Downgrading ignores newer sealed records
rather than deleting them. Authentication failure for existing vault material
continues to follow the project's global fail-closed policy.

The first increment needs a migration only if the sealed-page design cannot
meet bounded lookup and scheduler requirements using the generic table. Any
new SQLite-visible index receives a leakage review, upgrade and downgrade
tests, and crash-point tests before release.

## Iterative implementation plan

The plan uses narrow vertical increments. Each increment is useful within its
advertised scope and can ship behind a developer flag. A schema, parser,
service, or screen by itself is not an increment.

### Completion rule for every increment

An increment is complete only when:

1. A user can finish the advertised workflow on every platform enabled for
   that increment, including empty, loading, offline, validation, failure, and
   destructive-confirmation states.
2. The service validates bounded inputs, enforces authorization, commits before
   handoff, retries safely, reports receipts honestly, and recovers after a
   crash or restart.
3. Renderer and Tauri allowlists expose only the exact bounded commands and
   presentation models needed by that increment.
4. Protocol, service, renderer, crash-recovery, migration, and appropriate
   real-peer tests pass while existing Personal chats and groups remain green.
5. README, protocol profile, threat model, and testing evidence state the
   behavior and limits before the feature flag advances.

Mobile remains disabled until increment fifteen. Earlier increments need not
pretend to support a workflow on a platform where the feature is not yet
advertised.

### Enabling phase establishes safe foundations

This phase changes no user-visible behavior.

1. Write and approve three decisions: workspace authority and bootstrap,
   canonical event and history safety, and sealed paging plus asynchronous
   outbox storage.
2. Fix exact document schemas and worst-case byte/count bounds, including the
   chunked-manifest fallback.
3. Reserve the new custom profile and implement dispatch-before-parse plus the
   narrow verified unknown-source join path.
4. Add durable operation IDs, atomic batch mutation support, bounded sealed
   indexes, the background scheduler foundation, scoped invalidations, and
   workspace feature-version isolation.
5. Extract fan-out, retry, receipt, and aggregate-delivery helpers from group
   service without changing group behavior.
6. Split the minimum renderer routing, navigation, composer, and message-list
   modules needed for a workspace shell.

The phase is complete when all decisions and serialization fixtures are
checked in, no existing behavior changes, and the complete current test suite
passes.

### Increment 1 supports a two-person general channel

1. Create and switch workspaces, including atomic genesis, owner authority,
   one-device member shape, `#general`, summary, and indexes.
2. Create, import, verify, revoke, submit, approve, and decline one-use
   invitations through the new bootstrap path.
3. Store every message as a canonical inner-signed event with a durable stream
   sequence, immutable audience, derived state, bounded page entry, delivery
   legs, and operation result in one transaction.
4. Enqueue network work and return; let the bounded scheduler handle controls,
   route attempts, retry, expiry, and endpoint receipts.
5. Add basic local unread, a two-person People view, invite review, leave,
   owner-close, local hide, and confirmed local-removal flows.

This increment is complete when two fresh desktop installations can create two
workspaces, switch between them, join, chat, page messages, restart at each
commit boundary, retry the same operation without duplication, reject a file
drop, and close or leave through the UI. The cap is two active members and one
device per member.

### Increment 2 supports an eight-person general channel

1. Raise the cap to eight and support multiple pending, expiring, revoked, and
   concurrently approved invitations without staling unrelated invites.
2. Add the complete People directory, member leave and removal, display-name
   requests, workspace name and description updates, manifest catch-up, and
   propagation-node consent.
3. Aggregate public fan-out by person and device and expose pending, reached,
   partial, failed, expired, and cancelled legs.
4. Let members chat while the authority device is offline; administrative
   changes wait with an explicit status.

This increment is complete when an eight-peer topology operates `#general`
through partitions, restart, reconnect, one removal, and one metadata change
without an authorization bypass, lost committed event, or misleading receipt.

### Increment 3 adds public channels and per-channel unread

1. Create, browse, subscribe, unsubscribe, rename, change topic, transfer
   manager, recover, and terminally archive public channels.
2. Implement bounded public-channel summary exchange and signed-chain fetch;
   show incomplete discovery until reachable peers converge.
3. Enforce `channel_creation` and `posting` policies. Until admins exist,
   `owner_and_admins` means owner only.
4. Add per-channel unread defaults, stable duplicate-name disambiguation, and
   control-before-data delivery.

This increment is complete when an ordinary member discovers every public
channel retained by at least one reachable authorized peer, a permitted
manager completes the channel lifecycle, and forged or disallowed commands
fail in both UI and service.

### Increment 4 adds private channels

1. Create a channel whose identifier, metadata, roster, controls, and events
   reach only signed members.
2. Add and remove members through the manager chain. New members receive future
   events only until peer catch-up ships.
3. Transfer management; freeze metadata and membership if the manager is lost;
   permit owner recovery only when the owner is already a current member.
4. Add private archive, removal, fork, replacement-channel, and partition
   states.

This increment is complete when a mixed public and private workspace survives
partition and reconnect without exposing any private-channel identifier,
metadata, roster, or content to a nonmember.

### Increment 5 adds one-to-one direct messages

1. Open a DM from People without creating a global contact.
2. Keep IDs, authorization, drafts, indexes, unread state, and hidden/open
   presentation separate from Personal conversations.
3. Use the canonical event, scheduler, receipt, expiry, and paging foundation.
4. Stop new DMs after either participant's removal is known.

This increment is complete when two members can converse, hide the conversation
locally, reopen it from People, restart, and resume while global Contacts remain
unchanged.

### Increment 6 adds message editing reactions and deletion

1. Add canonical edit and deletion events with author-member authorization,
   base references, revisions, conflict state, and durable tombstones.
2. Add one logical reaction state per member and emoji with inactive
   tombstones.
3. Reject unauthorized, stale, equivocated, replayed, or no-longer-entitled
   mutations.

This increment is complete when delayed, duplicated, concurrent, and
out-of-order mutations converge on the same visible state after restart in
public channels, private channels, and DMs.

### Increment 7 adds structured mentions

1. Insert stable member IDs from a picker; raw text never creates a mention.
2. Add the Mentions inbox, mention-specific unread positions, and mention-mute
   behavior for subscribed and unsubscribed channels.
3. Revalidate mention visibility when membership or private-channel access
   changes.

This increment is complete when a user can find every authorized direct
mention, clear it, restart, and retain the same state without leaking mention
metadata to another member.

### Increment 8 adds one-level threads

1. Add a thread root reference, dedicated view, reply composer, and thread
   unread state. Replies never nest below another reply.
2. Apply edits, deletions, reactions, mentions, paging, and access changes to
   thread events.
3. Add **Threads** activity and correct root/reply behavior under delayed and
   out-of-order delivery.

This increment is complete when a user can open a mentioned thread, reply,
mark it read, restart, and recover the same convergent thread state.

Implementation status: completed in the desktop 0.2.28 candidate. Ordinary
non-thread canonical bytes remain unchanged; replies and their mutations bind
the signed root UUID. The encrypted implementation includes per-root pages,
draft/read state, a bounded Threads activity index, mentioned-thread
navigation, current-access and private re-admission checks, and metadata-only
startup summaries. Physical multi-device partition/reconnect, native-window
accessibility, packet capture, and protected-profile plaintext inspection
remain release gates rather than prerequisites for beginning Increment 9.

### Increment 9 adds retained local history and policy

1. Extend the bounded paging foundation to long retained histories, archived
   conversations, revisions, and tombstone views.
2. Implement owner-selectable 30, 90, 365 day, or indefinite cooperative
   retention and the generation changes that invalidate cursors and indexes.
3. Prune events, derived state, delivery detail, controls, and coverage safely
   without resurrecting content or manufacturing gaps.

This increment is complete when a 50,000-event seeded device pages, changes
retention, prunes, restarts, and continues chatting within the named benchmark
targets.

### Increment 10 adds local search

1. Build encrypted HMAC-keyed token shards incrementally from retained events.
2. Search messages, threads, people, and channel names with bounded cursors.
3. Decrypt candidates and recheck historical entitlement plus current
   disclosure before returning them; remove or rebuild shards after access or
   retention changes.

This increment is complete when search returns correct first pages within the
benchmark, excludes inaccessible and expired records, and never places
plaintext search material in SQLite-visible fields.

### Increment 11 adds peer history catch-up

1. Exchange signed stream heads and issue nonce-bound, expiring, byte- and
   event-bounded history requests over canonical events stored since increment
   one.
2. Forward exact events, mutations, tombstones, required controls, and
   continuations without changing authorship.
3. Enforce the disclosure matrix, inactive-author checkpoint rule, retained
   floors, and direct-message participant-only service.
4. Show progress, known coverage, peer-limited uncertainty, and permanent gaps.

This increment is complete when a device offline beyond the live-delivery
window recovers available authorized events that predate this increment, while
a private-channel nonmember and a DM nonparticipant learn nothing about those
conversations.

### Increment 12 adds administrators

1. Add admin roles and exact policy enums to manifests and service checks.
2. Let admins manage channels within policy and submit signed invitation,
   removal, and role-change requests for owner approval.
3. Show pending, approved, declined, stale, and superseded requests without
   presenting them as effective changes.

This increment is complete when admins perform daily channel operations while
the owner is offline and every membership or role change has one auditable
authority-approved result.

### Increment 13 adds authority continuity

1. Rotate authority between admitted devices of the same owner.
2. Transfer ownership through a current-authority offer, one named successor
   device's acceptance, and the final manifest; transfer or recover `#general`
   management at the same time.
3. Reject stale, replayed, partial, or conflicting transitions and explain the
   permanent-loss freeze and replacement-workspace path.
4. Bound and test the invitation bootstrap proof after multiple transfers.

This increment is complete when authority rotation and ownership transfer
survive a restart at every boundary, chat continues under the successor, and a
fork suspends safely instead of selecting a branch.

### Increment 14 adds linked desktop devices

1. Generate a new identity, countersigned one-time link document, and device
   card; admit it through a manifest without claiming the workspace invite as
   proof of an existing member ID.
2. Fan out channels and DMs to recipient devices and the sender's other
   devices, preserving person and device delivery detail.
3. Recover authorized canonical events and optionally sync encrypted read hints
   without copying identity material or creating social receipts.
4. Remove a lost device and reject it once removal is known; rotate authority
   first if it is the authority device.

This increment is complete when one member uses two desktop devices, replaces
one, and reaches convergent authorized history and delivery state without
sharing a private identity. The beta remains capped at three devices per member
and 24 destinations only if manifest and route gates pass.

### Increment 15 adds mobile lifecycle and notifications

1. Link mobile through the same device protocol and add native notification
   dependencies, permissions, denial states, and a service-to-native path that
   does not depend on renderer polling.
2. Notify for all, mentions only, or muted while the embedded runtime is able
   to execute; provide a local **Hide notification previews** option.
3. Reconcile controls, events, outbox work, and invalidation overflow after
   Android or iOS suspension and resume.
4. Explain delayed delivery without implying hosted push.

This increment is complete only on each advertised mobile platform after
physical suspend, resume, offline, reconnect, permission denial, private
preview, and restart tests produce correct notifications and delivery state.

### Release phase validates supported scale

This is a release decision, not another functional increment.

1. Run always-on deterministic service and crash tests, full-service 2- and
   8-peer RNS suites, and lab/package 16- and 32-peer topologies with direct,
   propagated, partitioned, and reconnecting routes.
2. Publish the named performance profile and pass limits for queue growth,
   storage, memory, battery, bandwidth, local commit, fan-out, restart, and
   synchronization.
3. Complete package extraction, protected-storage scans, migrations, upgrade
   and downgrade tests, and the exact physical platform matrix.
4. Run an eight-member internal pilot for 30 days and record missing workflows,
   permanent history gaps, delivery delay, and support burden.
5. Obtain an independent review of authority, bootstrap, history forwarding,
   private-channel privacy, and linked devices.

The release can describe the beta as a team's primary text workspace only if
the pilot has zero unauthorized disclosures, zero accepted events lost from
durable local storage, zero false delivered states, and convergence among
reachable peers within the documented retry window. The pilot must not require
another chat product for an in-scope text workflow. File, call, and integration
workflows are excluded rather than counted as failures. Candidate 16- and
32-member caps remain off unless their own evidence passes.

## Requirement traceability

The table names the first increment that delivers each requirement completely.
Foundations may appear earlier without changing that completion point.

| Requirement | First complete increment |
| --- | --- |
| WSP 001, 002, 005, 006, 007, 008 | Increment 1 |
| WSP 003 | Enabling phase |
| WSP 004 | Increment 13 |
| WSP 010, 011, 012, 014, 017 | Increment 1 |
| WSP 013 | Increment 12 |
| WSP 015, 016, 019 | Increment 2 |
| WSP 018 | Increment 14 |
| WSP 020 | Increment 1 |
| WSP 021, 022, 023, 028, 029 | Increment 3 for public behavior; Increment 4 for private behavior |
| WSP 024 | Increment 4 |
| WSP 025, 026 | Increment 5 |
| WSP 027 | Increment 1 |
| WSP 030, 032, 033, 037 | Increment 1 |
| WSP 031 | Increment 8 after mutations, mentions, and threads land in Increments 6 through 8 |
| WSP 034, 038, 039 | Increment 11 |
| WSP 035 | Increment 10 |
| WSP 036 | Increment 9 |
| WSP 040 | Increment 2 |
| WSP 041, 043, 044, 046, 047, 049 | Increment 1 |
| WSP 042 | Increment 15 after unread, mentions, and threads land earlier |
| WSP 045 | Increment 2 |
| WSP 048 | Increment 15 |

## Test and release gates

Protocol tests cover canonical encoding, exact fields, signatures, identity and
destination binding, invitation replay and concurrent use, authority proofs,
unknown-source rejection, skipped epochs, rollback, forks, role changes,
transfers, removal checkpoints, channel manager transitions, private exclusion,
sequence and revision equivocation, history continuations, oversize inputs, and
malicious forwarding.

Service tests cover atomic event and delivery creation, operation-id replay at
before-commit, after-commit-before-response, and after-response crash points,
background scheduler backpressure, targeted receipts, retry after restart,
control-before-data quarantine, cursor invalidation, retention, gap tracking,
search access, join bounds, old-client isolation, and no mutation of global
contact trust.

Topology tests include:

- owner offline while members chat in public and private channels;
- a member offline beyond seven days recovering available history;
- removal during a partition and conservative rejection after convergence;
- eight members with the maximum enabled linked-device fan-out;
- propagation-node loss and route-cache churn without false receipts;
- concurrent public-channel creation and manager fork;
- authority rotation and ownership transfer with delayed and replayed controls;
- a private history request from a nonmember and a DM request from a
  nonparticipant; and
- conditional 16- and 32-member tests with no impossible assumption that every
  member has three devices under a 48-destination total cap.

Renderer tests cover keyboard and screen-reader navigation, workspace
switching, bounded loading, unread and mention counts, channel discovery,
private invisibility, attachments-not-supported behavior, destructive
confirmation, partial delivery, stale cursors, queue pressure, history gaps,
owner waits, notification privacy, and fork suspension.

Workspace beta is ready only when:

1. A fresh team completes create and join without developer settings or prior
   contacts.
2. Public channels, private channels, one-to-one DMs, threads, mentions,
   reactions, edits, search, and available 90-day catch-up pass real-device
   tests.
3. Linked devices and notifications pass protected-storage, lifecycle, and
   restart tests on every advertised platform.
4. The eight-member pilot satisfies the measurable release outcomes.
5. Numeric performance, resource, manifest-size, route, and topology evidence
   supports every advertised cap.
6. Onboarding and README state the missing file sharing, hosted backup, calls,
   integrations, push delivery, owner-key recovery, and guaranteed remote
   deletion without hiding those limits in technical documentation.

## Deferred decisions

The following work requires its own protocol decision and release gates:

- all file and attachment sharing, including transfer, previews, shared blob
  storage, or CDN fallback;
- safe private-channel recovery by a workspace owner who is not a member;
- threshold or social recovery after permanent authority-device loss;
- multiwriter workspace membership or a shared administrative signing key;
- true guest roles and cross-workspace shared channels;
- globally ordered timelines or server-assigned positions;
- anonymous or publicly discoverable workspaces;
- bots, webhooks, and third-party app permissions;
- remote administrative deletion, legal hold, compliance export, workspace
  backup, and Slack import;
- audio and video calling;
- per-workspace device identities to reduce cross-workspace correlation; and
- sender-key or MLS fan-out optimization for larger workspaces.
