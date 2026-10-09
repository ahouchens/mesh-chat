# Mesh Chat protocol profile

Mesh Chat keeps the LXMF wire format, `lxmf.delivery` destination name, standard Content field, native source signature, and native encryption. It adds signed contact and group-control documents, a small LXMF custom-field map, and local IPC.

## Invitation v1

All entry points carry the same canonical UTF-8 JSON object:

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | integer | Exactly `1` |
| `label` | string | Claimed display label, 1–64 normalized characters |
| `public_identity` | base64url | Complete 64-byte RNS public identity |
| `destination` | lowercase hex | Derived `lxmf.delivery` destination hash |
| `created_at` / `expires_at` | integer | Bounded invitation validity |
| `hints` | array | At most eight validated public TCP host/port hints |
| `signature` | base64url | RNS identity signature over canonical JSON without this field |

The app accepts `meshchat://invite/<base64url>`, `MESHCHAT1:<base64url>`, or the raw JSON invitation file. The decoded input is capped at 16 KiB. Unknown fields, schemes, hint types, unsafe hosts, invalid dates, invalid signatures, and destination-binding mismatches are rejected before network configuration changes.

Network admission secrets are never invitation fields.

## LXMF application metadata v1

Text remains in LXMF Content. Mesh Chat uses upstream-reserved `FIELD_CUSTOM_TYPE` (`0xFB`) with `b"mesh-chat"` and `FIELD_CUSTOM_META` (`0xFD`) with this compact integer-key map:

| Key | Value |
| --- | --- |
| `1` | schema version `1` |
| `2` | `chat`, `reaction`, `receipt`, `contact_request`, `contact_accept`, `contact_decline`, `group_invite`, `group_accept`, `group_manifest`, `group_chat`, `group_reaction`, `group_receipt`, or `group_leave_request` |
| `3` | random 16-byte logical delivery UUID |
| `4` | deterministic 16-byte pairwise conversation UUID |
| `5` | authenticated application expiry timestamp |
| `6` | optional 16-byte receipt reference |
| `7` | signed invitation JSON, only for a contact request |
| `8` | group UUID, only for a group payload |
| `9` | nonnegative membership epoch, only for a group payload |
| `10` | 32-byte SHA-256 digest of the referenced group manifest |
| `11` | nonnegative per-sender sequence, only for `group_chat` |
| `12` | canonical signed JSON group document, only for group control kinds |
| `13` | common 16-byte group-operation UUID, required for `group_chat`, `group_reaction`, and `group_receipt` |
| `14` | 16-byte target chat-message UUID, only for `reaction` and `group_reaction` |
| `15` | one exact fully-qualified Unicode Emoji 18.0 sequence, at most 16 Unicode code points and 64 UTF-8 bytes |
| `16` | Boolean active state: `true` applies or replaces the actor's reaction; `false` is its tombstone |
| `17` | positive, monotonically increasing per-actor/per-target reaction revision |

The conversation ID is the first 16 bytes of SHA-256 over a versioned domain separator and the two sorted LXMF delivery hashes. It is not a human or network address.

Messages are accepted only after native signature validation, exact local destination matching, schema validation, conversation re-derivation, expiry validation, and trust-policy checks. A one-to-one source must bind to an approved contact; an unknown source may create only a bounded pending contact request carrying a signed invitation and cannot enter a direct chat or trigger a receipt. A group source must instead bind to an active identity card in the verified manifest for that group and epoch. Group-scoped authorization does not create an approved direct contact.

Group fields are additive to payload version 1; existing one-to-one payloads and
conversation IDs do not change. Group metadata on a non-group kind, a group
field on the wrong group kind, unknown metadata, a malformed UUID or manifest
digest, a negative or oversized integer, a group control document over 16 KiB,
text on a control message, or an empty group chat is rejected.

## Message reactions

Reactions are an additive extension of payload version 1. A direct `reaction`
has ordinary pairwise conversation metadata plus keys `14` through `17`. A
`group_reaction` additionally binds the current group UUID, membership epoch,
and manifest digest. Its key `13` is the common reaction-operation UUID shared
by that operation's separately addressed recipient copies; key `14` names the
group chat message being reacted to. Reaction payload Content is empty, and
receipt references, reaction fields on other kinds, unsupported emoji, zero or
oversized revisions, and malformed target UUIDs fail validation.

Reaction emoji are matched byte-for-byte against the 3,963 fully-qualified
sequences in the pinned Unicode Emoji 18.0 `emoji-test.txt` data. Mesh Chat
does not normalize or repair input: component-only, minimally-qualified,
unqualified, text-presentation, adjacent-emoji, malformed selector/modifier,
invented joiner, and invented tag sequences are rejected. The independent
16-codepoint and 64-byte limits are checked before catalog membership. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the data provenance and
license.

Each destination identity has at most one reaction state for a given message.
Applying a different emoji replaces that actor's earlier choice. Applying the
same emoji again removes it by publishing `active: false`; this tombstone and
its revision remain durable so delayed packets cannot restore an older state.
Only a strictly newer revision changes visible state. Duplicate or older
revisions are idempotently ignored and may still be acknowledged.

The actor is always the natively authenticated LXMF source destination, never
a value supplied by application metadata. A direct reaction is accepted only
from the approved or verified contact for the target message's re-derived
pairwise conversation. A group reaction requires the actor to be an active
member of the current manifest and to have belonged to the signed historical
manifest under which the target message was sent. Recipient fan-out is likewise
the intersection of current active membership and that historical audience.
Consequently, a later member cannot infer or react to an earlier message, and
a removed member cannot mutate it. The posting policy governs `group_chat`, not
reactions: active readers in an `owner_admins` announcement channel may react.

A valid reaction may overtake its target message. The receiver stores it as an
encrypted pending record and applies it atomically when the target commits.
Pending work is bounded to 256 records in total and 32 per authenticated actor,
expires with the reaction delivery window plus a 24-hour replay grace, and is
discarded when group epoch, manifest, active membership, or target audience no
longer match. Locally deleted targets have opaque durable discard markers;
late reactions are acknowledged where appropriate but cannot recreate the
message or its reaction state.

Local reaction state and its durable direct or per-recipient group outbox are
committed together before LXMF handoff. A newer local revision atomically
supersedes older reaction-only outbox work for that target, with native
cancellation attempted only after the vault mutation commits. Reaction jobs
and reaction receipts are removed after authenticated endpoint receipt (or an
application receipt), rather than retained as chat history. This also provides
safe compatibility with older payload-v1 peers: they can reject an unknown
reaction kind without affecting ordinary chat, while endpoint evidence stops
the sender from retrying the optional mutation for the full seven-day window.

## Private group profile

Mesh Chat sends a group message as separate native LXMF messages addressed to
the individual `lxmf.delivery` destination of every other active member. It
does not use `RNS.Destination.GROUP`, a shared group key, a custom cipher, or an
owner/server relay. Each recipient copy has its own logical delivery UUID in
key `3`; all copies share the group-message UUID in key `13`. This permits
deduplication and retry of one recipient without falsely merging another
recipient's delivery state.

A group has a permanent UUID derived as the first 16 bytes of
`SHA-256("mesh-chat:group:v1:" || owner_destination || nonce)`, where `nonce`
is 32 random bytes. Its owner-signed genesis anchors that nonce and owner. The
current state is an owner-signed canonical manifest with:

- the group UUID, owner identity and creation nonce;
- a normalized title, `active` or `closed` status, and the `members` or
  `owner_admins` posting policy;
- at most eight member identity cards and roles;
- a monotonically increasing epoch and the previous manifest digest; and
- an owner signature covering the complete canonical document without its
  signature member.

Group documents are UTF-8 JSON serialized with sorted keys, compact separators,
and no unknown fields. Each has `v: 1`, a `type`, and a base64url RNS signature
over every other field in the canonical object. The signed document types are:

| Type | Signed body |
| --- | --- |
| `group_member_card` | `group_id`, normalized `display_name`, complete `public_identity`, derived `destination`, zero to two validated TCP `hints`, `created_at` |
| `group_genesis` | `group_id`, 32-byte `nonce`, normalized `title`, `posting_policy`, signed `owner_card`, `created_at` |
| `group_manifest` | `group_id`, `epoch`, `previous_manifest_hash`, normalized `title`, `posting_policy`, `status`, `owner_destination`, sorted `members`, `created_at` |
| `group_invite` | `group_id`, `group_epoch`, `manifest_hash`, owner public identity and destination, targeted `invitee_destination`, embedded signed `genesis` and current `manifest`, 32-byte `nonce`, `created_at`, `expires_at` |
| `group_join` | `group_id`, `group_epoch`, `manifest_hash`, `invite_nonce`, signed `member_card`, `created_at` |
| `group_leave_request` | `group_id`, `group_epoch`, `manifest_hash`, signed `member_card`, matching `leaver_destination`, `created_at` |

Manifest entries contain a signed member card and exactly one of `owner`,
`admin`, or `member`. They are sorted by destination, contain no duplicate
destination, and contain exactly one owner whose destination matches the
manifest signer. Posting policy is exactly `members` or `owner_admins`; status
is exactly `active` or `closed`. Version 0.2.0 does not expose role assignment,
so an `owner_admins` channel is owner-only in its current user interface; the
signed `admin` role is reserved for a later role-management design.

Identity cards bind each member's complete RNS public identity to the derived
LXMF delivery destination. A receiver re-derives this binding and validates all
document signatures before changing durable group state.

`group_invite` is targeted to an approved contact and binds an invitation
nonce, expiry, group, owner, and offered manifest. `group_accept` contains the
invitee's identity-signed acceptance of those values. Acceptance is consent,
not membership by itself: the owner must publish a later `group_manifest` that
includes the member. A non-owner may send a member-signed
`group_leave_request` bound to the exact current manifest. It takes effect only
when the owner publishes the next manifest without that member. The owner
cannot leave without a separately designed ownership-transfer protocol.
The invitation verifier validates the embedded genesis and manifest, re-derives
their group and owner binding, matches the top-level epoch and digest, and for
epoch 1 requires the manifest's predecessor to be the genesis digest.

Manifest epochs form a single hash-linked chain. A receiver applies only the
expected next owner-signed epoch with the current digest as its predecessor.
A valid future epoch received before its predecessor is held inert until the
missing signed chain arrives; it cannot authorize messages while pending.
Rollback and invalid signatures fail closed. Two different valid
owner-signed manifests for the same group and epoch suspend group processing as
owner equivocation instead of selecting a branch silently, including when the
conflicting epoch is older than the receiver's current epoch.

An owner closes a group with the next manifest set to `closed`. A closed
manifest rejects posting, new invitations, joins, leave requests, and all later
manifest transitions. Closing converges like any other epoch and cannot erase
content already delivered.

The sender of `group_chat` must be active in the referenced manifest and must
have permission under its posting policy. The sender sequence is a durable
per-sender ordering and conflict key; it does not claim a globally serialized
group timeline. Messages may arrive out of order. A receiver may accept that
arrival order, but rejects an authenticated attempt to use one sender sequence
for two different common group-message UUIDs. The common UUID independently
deduplicates retransmitted recipient copies.

New members receive no messages from epochs before their admission by default.
A removed member is omitted from all later fan-out sets, and messages from that
member under an old epoch are rejected after the receiver learns the new
manifest. Because a partitioned member may not yet know the new epoch, removal
is eventual rather than instantaneous. Previously delivered content cannot be
revoked or remotely erased.

The message plus the complete recipient delivery set is committed atomically
before the first LXMF handoff. A `group_receipt` refers both to the recipient's
copy through key `6` and the common group-message UUID through key `13`.
Receipts are accepted only from the child delivery's intended member and update
only that member. Aggregate UI states are derived from every child; one receipt
never proves group-wide delivery.

## Workspace profile v1

Workspaces use a separate LXMF custom type, `b"mesh-chat-workspace"`. Existing
`b"mesh-chat"` traffic is byte-for-byte unchanged. Workspace Content is empty;
the strict custom metadata map contains only:

| Key | Value |
| --- | --- |
| `1` | schema version `1` |
| `2` | `workspace_join`, `workspace_manifest_root`, `workspace_channel_record`, `workspace_channel_manifest`, `workspace_channel_leave_request`, `workspace_channel_transfer_offer`, `workspace_channel_transfer`, `workspace_channel_recovery`, `workspace_channel_summary`, `workspace_channel_fetch`, `workspace_event`, `workspace_leave_request`, `workspace_display_name_request`, or `workspace_display_name_decision` |
| `3` | random 16-byte logical delivery UUID |
| `4` | 16-byte workspace UUID |
| `5` | authenticated application expiry timestamp |
| `6` | the canonical signed workspace document |

Unknown keys or kinds, nonempty Content, malformed identifiers, invalid expiry,
control documents over 16 KiB, and event documents over 20 KiB fail closed.
The authenticated wire expiry must be between receipt time and exactly seven
days after receipt; there is no grace interval outside that live-delivery
window.
Dispatch selects this profile before the Personal parser. An unknown native
source may submit only a fully verified `workspace_join`; every other workspace
kind requires a source device already authorized by the workspace manifest.

Workspace identifiers are the first 16 bytes of
`SHA-256("mesh-chat:workspace:v1:" || creator_destination || nonce)`, formatted
as an RFC 4122 UUID. All documents use sorted-key compact UTF-8 JSON, exact
field sets, NFC-normalized display strings, base64url without padding, and a
signature over the document without its `signature` member. The v1 signed
document types are:

| Type | Authority and purpose |
| --- | --- |
| `workspace_device_card` | A device binds workspace, member and device UUIDs, display name, complete public identity, derived destination, up to two route hints, and creation time. |
| `workspace_genesis` | The creator binds the workspace nonce, name, description, owner and initial authority device. |
| `workspace_manifest_root` | The authority binds an epoch, predecessor, policies, status, retention, members and devices. |
| `workspace_invite` | The authority offers a complete genesis/manifest checkpoint, empty authority chain, nonce, expiry, and single-use limit. |
| `workspace_join` | A joining device binds its signed card to the invitation and offered checkpoint. |
| `workspace_channel_record` | The manager binds a versioned channel, predecessor, manifest, visibility, policy context, and archived state. |
| `workspace_channel_manifest` | A private-channel manager binds the version, predecessor, exact workspace manifest, metadata, sorted member roster, and terminal archive state. |
| `workspace_channel_leave_request` | A nonmanager private member asks the manager to remove that member at one exact private-channel head. |
| `workspace_channel_transfer_offer` | The current channel manager names one active successor device, the exact current channel head, the current workspace manifest, and an expiry; a private successor must already be on the roster. |
| `workspace_channel_transfer` | The named successor countersigns the complete manager offer; the resulting digest is the next channel head. |
| `workspace_channel_recovery` | The owner authority device explicitly assigns management at the exact current head; private recovery is valid only when that owner is already on the roster. |
| `workspace_channel_summary` | An active device signs one canonical page of public channel IDs, versions, and head digests for a sync session. |
| `workspace_channel_fetch` | An active device signs bounded channel/head requests and a maximum control count for one summary session. |
| `workspace_event` | An author binds a message to its workspace/conversation, author stream predecessor, exact manifest, immutable payload, and either an exact channel control or a null channel digest plus the complete sorted two-member DM audience. Private channels repeat their complete sorted roster audience. |
| `workspace_leave_request` | A non-owner binds a leave request to the exact current manifest. |
| `workspace_display_name_request` | An active device signs a replacement card that preserves its member, device, identity, and destination while requesting a new display name. |
| `workspace_display_name_decision` | The authority signs an approval or decline bound to the exact request and its base manifest. Approval is completed by the next manifest; decline is returned directly to the requester. |

Invitation entry points are `meshchat://workspace/<base64url>` and
`MESHWORKSPACE1:<base64url>`. Invitations are single-use and expire within 30
days. The offered checkpoint must retain the exact genesis owner member and
authority device card; a self-consistent manifest signed by another identity is
not a valid checkpoint. Increment 5 supports eight people, one device per
member, and up to 32 active public or private channels including `#general`.
It rejects attachments and does not exchange old message history. The authority is not a
message relay: each event is copied directly to every other authorized device
through its individual ratchet-enforced LXMF destination, regardless of that
device's local channel subscription.

Manifest epochs and channel versions are hash-linked. Events carry both exact
control digests plus a positive per-device sequence and previous-event digest.
Missing controls or stream predecessors leave an event inert; invalid
authority, rollback, reused sequence, or equivocation cannot authorize visible
state. A valid enabled manifest epoch admits one member, deactivates one
non-owner member, applies one self-signed display-name request, updates
workspace name/description, changes the exact public-channel creation/posting
policy pair, or closes without another change; combined or no-op epochs are
rejected. `owner_and_admins` is owner-only until admin roles are implemented.
Concurrent invitations are independent capabilities.
When an accepted invitation references an older checkpoint, every intervening
manifest is delivered before or alongside the admission epoch and receivers
apply the chain in order. The mandatory `#general` record is version one, public,
active, predecessor-free, bound to the epoch-one manifest, and managed by the
genesis owner authority. Control copies are scheduled ahead of dependent
events.

Every other public channel begins at version one under an exact manifest whose
creation policy authorizes its manager. Manager-signed metadata/archive records,
successor-accepted transfers, and authority-signed recoveries form one digest
chain. Two different valid digests at one channel version suspend that channel
without suspending its workspace. Archival is terminal; `#general` cannot be
renamed, unsubscribed, transferred independently, or archived. Channel-name
comparison uses NFC validation followed by NFKC case folding, but the random
channel UUID remains authoritative and duplicate comparison keys remain valid.

Discovery summaries contain at most 32 sorted entries per signed page and at
most 32 pages per session. A signed fetch names at most 32 channels and asks for
at most 64 canonical control records. Controls are returned in predecessor
order before the next summary pages. A device labels its directory incomplete
until it has complete, equal summary pages from every admitted device it is
tracking. Missing or reversed controls keep dependent events in the bounded
inert queue. Subscription and read positions are sealed local state;
unsubscribed public channels still receive and retain events but do not accrue
ordinary unread badges.

Private channels use the separate `workspace_channel_manifest` family so a
public directory record can never be reinterpreted as a private grant. Each
head contains one to eight sorted, unique, active workspace member IDs and must
include its manager. Only those members receive the head, offers, accepted
transfers, recoveries, events or pending delivery legs; private heads never
enter public summaries or fetch responses. A new member receives the current
manager-signed head as an admission checkpoint without predecessor controls or
events. Its first future event may therefore begin after a deliberate stream
gap, while events whose signed audience omits that member are rejected before
pending storage. Later heads extend normally; a safe version jump is accepted
only as a same-manager admission checkpoint. Same-version valid conflicts mark
that channel forked. A member removal cancels only that member's unhanded legs.
The manager cannot leave or be removed from the roster until management is
transferred, and archival remains terminal.

Workspace direct messages have no channel-control family. Their conversation ID
is UUIDv5 in the workspace UUID namespace over
`mesh-chat:workspace-direct:v1:` plus the two sorted member UUIDs. The canonical
event sets `channel_digest` to JSON null and carries exactly those two sorted,
unique, active member IDs in `audience_member_ids`; the author must be one of
them. A recipient accepts the event only while both participants are active in
its current manifest. Delivery fans out only to participant devices, local
hide/reopen state is not transmitted, and learning either participant's
removal cancels unhanded DM legs. There is no DM history backfill in this
increment, so an unseen event authored before a known removal is not admitted
after that removal.

## Delivery evidence

| App state | Required evidence |
| --- | --- |
| `waiting_for_keys` | durable local ciphertext, but no acceptable recipient ratchet |
| `queued` | durable local record awaiting route/retry/consent |
| `sending` | handed to LXMF; recipient commit unconfirmed |
| `stored_for_delivery` | propagation node accepted recipient ciphertext |
| `received_by_endpoint` | native endpoint delivery proof |
| `delivered` | intended contact sent a valid encrypted receipt after committing the logical message |
| `expired` | seven-day application window ended |
| `failed` | non-transient validation, storage, or identity error |
| `cancelled` | the recipient left or was removed before that pending workspace leg completed |

Receipts are ordinary signed, end-to-end encrypted LXMF messages. They reference the original logical UUID, are persisted with the inbound message, are retried, are never themselves acknowledged, and are accepted only from the pending message's expected contact.

## Limits and modes

- Text: 16 KiB UTF-8.
- Delivery/deduplication window: seven days.
- Invitation: 16 KiB decoded.
- Canonical group control document: 16 KiB UTF-8.
- Group invitation lifetime: seven days by default, never more than 30 days.
- Group title and member display name: 1–64 normalized characters each.
- Signed connection hints per group member card: at most two validated TCP hints.
- Private group or announcement channel: at most eight people including the owner.
- Desktop workspace: at most eight people, 32 active channels including `#general`, 32 entries per signed public-summary page, 32 pages per sync session, and 64 controls per signed public fetch response. Archived public channels are retained in the bounded 1,024-entry directory; private channels are never summarized publicly.
- Pending reactions: at most 256 total and 32 per authenticated actor.
- IPC frame: 4 MiB; renderer-originated payload: 32 KiB.
- LXMF direct and propagated modes: enabled.
- LXMF opportunistic, paper, PLAIN and RNS GROUP private-chat/group fallbacks: not used.
- Propagation cache: 100 MiB.
- Automatic propagation peering: disabled.

RNS/LXMF versions are pinned in `service/requirements.lock`. Propagated packing is refused unless RNS has a current recipient ratchet, preventing the upstream base-identity-key fallback.
