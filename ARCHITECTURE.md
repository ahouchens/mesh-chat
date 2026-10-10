# Architecture

## Trust and process boundaries

| Component | Owns | Must not own |
| --- | --- | --- |
| React renderer | presentation, drafts in memory, validated public UI models | vault key, private identity, filesystem paths, process launch, arbitrary navigation |
| Tauri Rust shell | desktop sidecar lifecycle, mobile plugin bridge, app-owned data path, native credential entry, IPC validation, deep links | routing, message encryption, chat persistence |
| Android/iOS native plugin | embedded CPython lifecycle, app-private profile path, Keystore/Keychain access, platform network permissions | renderer data, contact policy, routing decisions |
| Python service | private identity, contact/group policy, durable state, Reticulum/LXMF integration | OS credential lookup, arbitrary commands, remote UI |
| Reticulum | paths, announces, interfaces, native transport forwarding | contact trust, chat history, durable-delivery claims |
| LXMF | message wire format, direct/propagated transfer, propagation storage/sync | accepted-conversation or group-membership policy, logical deduplication, application receipts |

The shell selects the profile path and retrieves or creates a 32-byte vault key in the native credential store. Desktop starts the packaged sidecar without arguments and sends both values in the first private stdin frame. Android and iOS call the same Python service through a narrow JSON boundary in a native Tauri plugin; the key remains in native code and the profile remains inside the app sandbox. The renderer can invoke only an allowlisted Rust command; Rust rejects oversized bodies, filesystem/control keys, and unknown operations.

The desktop sidecar reserves stdout for framed responses/events and discards detailed upstream log text. Mobile events use a bounded in-memory queue drained through the native plugin. There is no HTTP, WebSocket, TCP, named-pipe, or shared Reticulum control service.

## Networking lifecycle

1. The service writes an app-owned Reticulum configuration with `share_instance = No`, `discover_interfaces = No`, no public gateways, and only user-configured interfaces.
2. RNS is initialized inside the protected profile, then LXMF registers the standard `lxmf.delivery` individual destination.
3. Destination ratchets are enabled and enforced before the first announce.
4. An imported invitation is independently signature-checked and its destination is re-derived before its public identity is remembered by RNS.
5. Sending waits for acceptable recipient ratchet material. Direct messages use LXMF Links; propagated messages are permitted only when a configured approved propagation node exists and recipient ratchet encryption is confirmed before handoff.
6. A native direct proof becomes `received_by_endpoint`; a propagation upload proof becomes `stored_for_delivery`. Only an authenticated Mesh Chat receipt becomes `delivered`.

## Private groups and channels

Private groups do not introduce another transport or a shared group key. One
logical group message is committed with a child delivery for every other active
member and then fanned out through those members' individual, ratchet-enforced
LXMF destinations. Direct and propagated copies follow the same network policy
as one-to-one messages. Each child's authenticated application receipt updates
only that recipient's state; the UI derives an aggregate without treating one
receipt as group-wide delivery.

The group owner signs a hash-linked sequence of canonical membership manifests.
Members explicitly accept invitations, posting policy is enforced from the
signed manifest, and membership changes do not require the owner to relay chat
traffic. A non-owner leave is a signed request applied by the owner in the next
manifest, and a signed closed manifest is terminal. New members receive no old
history by default. See
[ADR 0004](docs/adr/0004-private-groups-over-individual-lxmf.md) for the scale,
ordering, removal, and owner-loss consequences.

## Desktop workspaces

The ninth workspace increment is an isolated desktop feature profile. It adds
canonical workspace authority, device, invitation, channel and event documents
under the `mesh-chat-workspace` custom type without changing Personal or private
group bytes. The React shell can switch between Personal and workspace views,
but all trust, manifest, paging, unread and delivery decisions remain inside
the Python service. Rust exposes only the named workspace commands on desktop
and returns `workspace_desktop_only` through the mobile bridge until the mobile
increment is implemented.

The service is split into three workspace boundaries:

- `workspace_protocol.py` freezes and verifies canonical signed documents;
- `workspace_wire.py` owns strict LXMF profile framing and dispatch isolation;
- `workspace_service.py` owns authority transitions, bounded indexes, paging,
  scheduler work, derived state, and presentation models.

An authority-signed, hash-linked manifest controls membership and policy;
independent manager chains control every public and private channel; an
author-device-signed event references both exact heads. Private controls bind a
sorted roster and private events bind that exact audience. Their identifier,
metadata, roster, controls, events and delivery legs are created only for
listed members. A transfer requires the current manager's offer and the named
successor's acceptance. Public recovery requires the owner authority signature;
private recovery additionally requires that owner already be on the signed
roster. The network adapter permits exactly one unknown-source
path: a verified join whose embedded identity and native source agree. Controls
are queued ahead of dependent events, so no event becomes visible merely
because it arrived before its authority data.

Workspace DMs reuse the canonical workspace event, stream, paging, receipt,
expiry, and due-work machinery without creating a channel control or a Personal
contact. Their conversation UUID is UUIDv5 over the workspace UUID and sorted
two-member pair. A signed DM event carries `channel_digest: null` and the exact
sorted two-member audience; verification requires the author and receiver to be
current active participants. Dedicated sealed `workspace_direct` summaries,
conversation indexes, read state, drafts, and local hidden state keep their
presentation independent from Personal. Learning either participant's removal
makes retained history read-only and cancels every unhanded leg for that DM.

Edits, author deletion, and reactions are canonical `workspace_event` records,
not mutable renderer commands or replacements for the signed original. The
service first verifies the mutation envelope and current controls, then resolves
the referenced message and repeats author-member, current-entitlement, and
historical-audience checks. Public, private, and DM mutations share the same
per-device sequence/predecessor stream as messages. They advance stream
coverage and receive ordinary per-device delivery legs, but do not add timeline
page entries.

`workspace_message_state` materializes the deterministic winning author
revision, durable deletion tombstone, conflict bit, and equivocation freeze.
`workspace_reaction_state` is independently keyed by target, member, and emoji,
so one member may retain several emojis and each inactive state remains a
tombstone. Candidate ordering is `(revision, signer destination, event digest)`;
a later revision clears a concurrent conflict, while distinct content from one
device at one revision freezes the whole message. These encrypted derived
records are updated in the same vault transaction as the canonical event,
stream head, outbox legs, due-work shards, and durable operation result.
Deleted plaintext is never returned in the public message model. Missing
targets or bases remain bounded and inert until their predecessors arrive.

Mentions are signed event metadata, not text parsing. A message or edit carries
a canonical sorted list of zero to eight active member UUIDs; the service
rejects a target outside the exact DM or private-channel audience. Public
channel targets must be active workspace members. Raw `@name` text has no
authority and does not enter the mention index. An edit's mention list is part
of deterministic mutation content, so concurrent mention changes converge and
same-device equivocation freezes them with the rest of the message.

Each device materializes only mentions of its local member in sealed bounded
`workspace_mention_index` pages. The active page entry is linked to the current
derived message revision so removal and re-addition cannot resurrect or
duplicate a stale inbox row. A separate sealed mention high-water supplies
unread state; sealed per-channel preferences suppress mention presentation for
both subscribed and unsubscribed public channels without changing delivery.
Listing and cursor validation re-check the current manifest, private roster,
channel state, local hide/tombstone state, and mute preference. Draft mention
IDs are local encrypted metadata and are filtered against the same current
authorization before entering a restart snapshot.
The workspace summary persists the derived mention unread count after each
workspace change, so ordinary startup snapshots do not decrypt message bodies;
profiles from the superseded preview builds are re-derived once on migration.

One-level workspace threads reuse the canonical workspace event stream. An
ordinary root retains the existing JSON-null `thread_root`, so its canonical
bytes do not change. A reply signs the root message UUID, and a mutation of a
reply repeats the same root UUID. The service resolves that UUID to a retained
ordinary message in the same workspace and conversation and rejects a root
that is itself a reply. Public-channel replies retain empty audience metadata;
private replies retain the exact signed roster; workspace-DM replies retain the
exact sorted two-member audience.

Reply bodies are materialized in sealed, per-root `workspace_thread_index`
pages instead of the ordinary conversation timeline. `workspace_thread`
stores the encrypted reply count, high-water, unread count, root authorization
metadata, and latest activity time. A capped `workspace_thread_activity_index`
contains at most 1,024 root IDs and metadata-only activity positions. Separate
sealed read and draft records are keyed by root. Thread and activity cursors
bind index high-water, retention generation, workspace authorization, channel
heads/rosters, and DM visibility. Explicit thread listing may decrypt the root
and requested reply page; ordinary startup snapshots read only the bounded
activity summaries and encrypted draft authorization metadata, never message
bodies or complete event/delivery collections.

Every thread entry point treats indexes as hints rather than grants. It
rechecks active workspace membership, root existence and local hide state,
channel state, current private roster, the root channel checkpoint and the
local member's latest admission version, or the exact current DM participants.
This same check gates reply creation, edits, tombstones, reactions, mentions,
read advancement, drafts, activity rows, and cursor continuation. Root/reply
events and their derived pages, unread state, drafts, delivery legs, and
idempotent result commit atomically; missing roots and predecessors remain in
the existing bounded pending queue until they can be verified.

Retained history adds sealed linked indexes for canonical retention order,
message revisions, deletion tombstones, and long conversation archives. The
authority owner signs one cooperative retention preference: 30, 90, or 365
days, or indefinite. It is explicitly a per-device history preference, not a
remote-deletion promise. Each policy change and each prune batch advances a
retention generation used by conversation, mention, thread, activity,
revision, and tombstone cursors; a mismatch returns `stale_cursor`.

The local scheduler prunes at most 1,000 indexed canonical events in one
transaction and persists its next page before yielding. Expired event and
derived bodies, completed delivery detail, operation results, due work, and
index references are removed together. Lightweight event-ID tombstones and
pruned stream markers preserve replay rejection, high-water, retained-floor,
seen-range, and permanent-gap meaning. Author deletion state waits for both the
history boundary and the independent seven-day live-delivery window. Historical
authority and channel controls are retained conservatively while dependents may
reference them. Former-member archives remain read-only, private re-admission
does not bridge roster eras, and owner status never grants workspace-DM access.

Latest-page reads open only bounded pages and use request-local verification
caches for repeated immutable manifests and channel controls. Reaction state is
addressed by exact opaque IDs materialized with each Increment 9 message.
Workspace startup still avoids message/event/delivery collections entirely.

Checkpoints are pinned to the genesis owner member, authority device, public
identity, and destination. The initial manifest also pins the genesis name and
description. Each later manifest performs exactly one enabled transition:
admit one member, deactivate one non-owner member, replace one member's
self-signed display-name device card, update workspace metadata, or close.
A same-epoch document is considered a fork only
after its signature and predecessor link validate against the pinned chain.
`#general` is likewise pinned to the epoch-one manifest and genesis authority.
Outside the narrow join path, the native sender must be an active workspace
device even when forwarding another member's signed control or event.

Up to eight people share as many as 32 active channels including `#general`.
Independent invitations may reference
the same older checkpoint; approval appends to the authority's current epoch,
delivers the missing ordered manifest and public-channel chains to the new
device, and sends only the successor epoch to current members. Public-channel
messages always fan out to every active device. Private-channel controls and
messages fan out only to the signed roster. Workspace DMs fan out only to the
two signed participants. Adding a member sends one current
signed admission checkpoint, not predecessor controls or messages, so
pre-admission names, topics and rosters are not disclosed. Removing a member
cancels only that member's unhanded channel legs; retained local history cannot
be revoked. A local public subscription affects
only sidebar presentation, unread state, and later notification policy.
Public message state materializes
per-device legs and derives per-person pending, reached, partial, failed,
expired, and cancelled aggregates without exposing destinations or public
identity material. Member-authored events do not depend on the authority being
online; metadata, membership, and name decisions do.

Workspace startup reads summaries, channels, invitations, join requests,
conversation and mention unread positions, and authorized encrypted drafts,
but no message bodies, mention bodies, or delivery-leg collections. Message
and mention lists use bounded linked pages with MAC-bound cursors.
Public-channel discovery exchanges signed, paged summaries and bounded chain
fetches. A directory remains explicitly incomplete until every tracked active
device has supplied a complete summary equal to local retained heads. Duplicate
normalized names remain separate channels and use their stable UUID-derived
short IDs in presentation. Reversed events stay encrypted and inert until the
referenced channel controls validate. A delayed private event remains
acceptable across later metadata heads only when its signed head is an ancestor
and both the local member and author remain on the current roster. Conflicting
signed heads suspend only the affected channel.
Mutations use durable operation IDs, and sends commit the event, audience,
delivery legs, page/index changes, due-work and result in one vault transaction
before the background scheduler touches LXMF. Workspace changes carry scoped
workspace/conversation/resource invalidations; the renderer coalesces them and
refreshes the bounded workspace summary rather than the full application
snapshot. See
[ADR 0005](docs/adr/0005-workspace-authority-and-bootstrap.md),
[ADR 0006](docs/adr/0006-workspace-events-and-history-safety.md),
[ADR 0007](docs/adr/0007-sealed-workspace-paging-and-outbox.md), and
[ADR 0008](docs/adr/0008-cooperative-retention-and-local-history.md).

## Message reactions

Reactions reuse the existing native LXMF trust, encryption, and routing paths;
they do not add a relay, shared key, custom cipher, or plaintext side channel.
The service derives the actor only from the validated native source, binds a
direct reaction to its approved pairwise conversation, and binds a group
reaction to both the current signed manifest and the target message's signed
historical audience. Group fan-out includes only identities that are both
currently active and entitled to the target message. Announcement-channel
posting restrictions do not prevent active readers from reacting.

The vault keeps one encrypted state record per scope, conversation or group,
message, and actor. That record contains one exact fully-qualified sequence
from the pinned Unicode Emoji 18.0 catalog, an active flag, and a monotonic
revision. The dependency-free generated index is identical on desktop and
mobile, contains 3,963 sequences, and applies 16-codepoint and 64-byte bounds
before membership lookup. An inactive record is a durable tombstone, so
out-of-order delivery cannot resurrect a replaced or removed reaction. Direct
and group domains use separate opaque identifiers. Snapshot aggregation keeps
the original six quick reactions first when present and orders every other
valid emoji deterministically.

Emoji presentation is deliberately separate from reaction identity. The
encrypted vault and LXMF payload continue to store and transmit the exact
Unicode sequence; peers never exchange an artwork URL, sprite coordinate, or
vendor-specific image identifier. In the renderer, a generated lookup maps
validated sequences only to local sprite coordinates. The 0.2.11 assets are
derived from Twemoji 17.0.3 at pinned commit
`b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`, resized to 48-pixel cells,
palette-optimized, and packed into one 253-entry curated picker sheet plus eight
general sheets. They cover every picker choice and 3,944 of the 3,963 accepted
Unicode Emoji 18.0 sequences.

Twemoji 17 predates 19 new Emoji 18 entries. Those exact sequences map to
catalog names and a deterministic neutral tile marked `18` until compatible
open artwork is available. The same neutral tile is shown while an image loads,
if a local asset fails, and in forced-colors mode; controls keep their complete
accessible reaction names. The lookup cannot produce a remote URL. Sprite
sheets, the integrity manifest, attribution, and the CC BY 4.0 graphics license
are bundled with the app, Settings identifies Twemoji and its license, and no
CDN or artwork network request is part of rendering.

A reaction can arrive before its message. The service durably queues a bounded
encrypted pending record, then applies or discards it in the same transaction
that commits the target message. Pending records are capped globally and per
actor, time-bounded, and rechecked against current and historical group
membership before use. Opaque deleted-target markers prevent delayed or
replayed reactions from restoring locally erased content.

## Persistence and crash consistency

`VaultStore` is an authenticated-encryption design over SQLite. Desktop records are sealed independently with AES-256-GCM, a fresh 96-bit nonce, and table/record identity as associated data. Mobile records derive a per-record key with HMAC-SHA-256 and use RNS's encrypt-then-MAC Token construction (AES-CBC plus HMAC-SHA-256); the master key is wrapped by Android Keystore or held as a ThisDeviceOnly iOS Keychain item. SQLite runs with `journal_mode=DELETE`, `synchronous=FULL`, `temp_store=MEMORY`, and `secure_delete=ON`. Rollback journals contain ciphertext values. The one plaintext schema version and opaque UUID keys do not include contact or conversation content.

The inbound message and its durable receipt job are committed in one transaction. Outbound records are committed before LXMF handoff. For groups, the logical message and complete set of recipient child deliveries are committed together before the first child is handed to LXMF. On restart, unconfirmed outbound work is reconciled back to the app queue; repeated logical IDs are deduplicated even if native LXMF IDs change.

A local reaction state change and its direct or per-recipient group delivery
records are also committed atomically. A later revision removes superseded
reaction-only delivery records in that transaction; cancellation of their
native attempts is best-effort cleanup after commit. Reaction deliveries and
their bounded receipt jobs are deleted after endpoint evidence instead of
becoming visible chat history. Older payload-v1 peers may reject the additive
reaction kinds, but the endpoint proof retires this optional work while normal
chat continues unchanged.

The profile is process-locked. Credential-store failure, record authentication failure, profile contention, IPC mismatch, and protected-workspace failure all stop safely.

## Library-owned files

RNS 1.5.5 and LXMF 1.2.0 expose file-oriented persistence for destination ratchets, learned outbound ratchets, known destinations, tickets, transient-ID caches, propagation peers, and stored messages. Before any database, RNS, or LXMF object is constructed, the storage adapter verifies the entire profile workspace: EFS inheritance on Windows, active FileVault on the local macOS user-data volume, fscrypt/dm-crypt/LUKS/a recognized encrypted-filesystem mount on Linux, or an app-private data-protected container selected by native mobile code. Android backup is disabled. iOS applies complete file protection to the profile directory. Unsupported or unprotected storage fails closed, so library-owned child files never silently fall back to an unprotected profile.

Inventoried persistent areas under `profile-v1/`:

- `mesh-chat.vault` and its transient rollback journal — only authenticated ciphertext records;
- `.profile.lock` — no secret content, inside the protected directory;
- `reticulum/config` — interface and role configuration, inside the protected directory;
- `reticulum/storage/**` — paths, known identities, learned ratchets, resources and caches;
- `network-state/lxmf/**` — local ratchets, ticket/cost caches, transient IDs, propagation state and recipient-encrypted message store.

The service does not export private identities to ordinary files, enable crash upload, or write application logs. Memory, swap, unlocked endpoints, and an OS compromise remain outside the at-rest claim.

## Role isolation

`Help route messages` maps only to Reticulum `enable_transport`. `Store encrypted messages for offline contacts` maps only to LXMF propagation enablement and a 100 MiB cache. Both default off and require a service restart. Propagation auto-peering is disabled; only explicit static approved peers are configured for synchronization.

## Decisions

- [ADR 0001: reference Reticulum and LXMF](docs/adr/0001-reference-stack.md)
- [ADR 0002: protected library workspace](docs/adr/0002-protected-workspace.md)
- [ADR 0003: inherited framed IPC](docs/adr/0003-framed-ipc.md)
- [ADR 0004: private groups over individual LXMF delivery](docs/adr/0004-private-groups-over-individual-lxmf.md)
- [ADR 0005: workspace authority and bootstrap](docs/adr/0005-workspace-authority-and-bootstrap.md)
- [ADR 0006: canonical workspace events and history safety](docs/adr/0006-workspace-events-and-history-safety.md)
- [ADR 0007: sealed workspace paging and asynchronous outbox](docs/adr/0007-sealed-workspace-paging-and-outbox.md)
- [ADR 0008: cooperative retention and retained local history](docs/adr/0008-cooperative-retention-and-local-history.md)
