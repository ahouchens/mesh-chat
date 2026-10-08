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

The third workspace increment is an isolated desktop feature profile. It adds
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
independent manager chains control every public channel; an author-device-signed
event references both exact heads. A transfer requires the current manager's
offer and the named successor's acceptance, while public recovery requires the
owner authority signature. The network adapter permits exactly one unknown-source
path: a verified join whose embedded identity and native source agree. Controls
are queued ahead of dependent events, so no event becomes visible merely
because it arrived before its authority data.

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

Up to eight people share as many as 32 active public channels. Independent invitations may reference
the same older checkpoint; approval appends to the authority's current epoch,
delivers the missing ordered manifest and public-channel chains to the new
device, and sends only the successor epoch to current members. Public-channel
messages always fan out to every active device. A local subscription affects
only sidebar presentation, unread state, and later notification policy.
Public message state materializes
per-device legs and derives per-person pending, reached, partial, failed,
expired, and cancelled aggregates without exposing destinations or public
identity material. Member-authored events do not depend on the authority being
online; metadata, membership, and name decisions do.

Workspace startup reads summaries, channels, invitations, join requests,
unread positions, and encrypted drafts, but no message bodies or delivery-leg
collections. Message lists use bounded linked pages with MAC-bound cursors.
Public-channel discovery exchanges signed, paged summaries and bounded chain
fetches. A directory remains explicitly incomplete until every tracked active
device has supplied a complete summary equal to local retained heads. Duplicate
normalized names remain separate channels and use their stable UUID-derived
short IDs in presentation. Reversed events stay encrypted and inert until the
referenced channel controls validate.
Mutations use durable operation IDs, and sends commit the event, audience,
delivery legs, page/index changes, due-work and result in one vault transaction
before the background scheduler touches LXMF. Workspace changes carry scoped
workspace/conversation/resource invalidations; the renderer coalesces them and
refreshes the bounded workspace summary rather than the full application
snapshot. See
[ADR 0005](docs/adr/0005-workspace-authority-and-bootstrap.md),
[ADR 0006](docs/adr/0006-workspace-events-and-history-safety.md), and
[ADR 0007](docs/adr/0007-sealed-workspace-paging-and-outbox.md).

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
