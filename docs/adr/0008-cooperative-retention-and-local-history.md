# ADR 0008: Cooperative retention and retained local history

Status: accepted for workspace protocol v1, increment 9.

## Decision

Workspace history remains an encrypted local copy, not a remotely enforceable
archive. The authority owner may sign a cooperative preference of 30, 90, or
365 days, or indefinite retention; 90 days remains the default. A receiving
device applies that preference to its own vault, but the protocol cannot erase
plaintext, exports, screenshots, or backups already controlled by another
device.

Canonical events are appended to a sealed linked retention index whose pages
contain at most 100 references. Conversation, thread, mention, revision, and
deletion-tombstone views use separate sealed linked pages. SQLite-visible keys
are HMAC-derived opaque identifiers. Cursor payloads are authenticated and bind
the exact workspace authorization generation, retention generation, index
high-water, page, and offset. Policy transitions and successful prune batches
advance the retention generation; a continuation from an older generation
returns `stale_cursor` instead of combining histories.

Pruning is a restart-safe local job with at most 1,000 canonical events per
commit. It removes expired event bodies, derived message/reaction state,
completed delivery detail, operation results, due work, and page references.
It preserves historical authority and channel controls conservatively while
any retained content can reference them. Deletion tombstones and their target
state remain until the later of the history boundary and durable local receipt
plus the independent seven-day live-delivery window.

Pruned event UUIDs become small sealed retirement records, and stream sequence
records become content-free pruned markers. Per-stream heads retain signed
high-water, retained-floor, seen-range, and permanent-gap facts. Consequently,
a delayed duplicate is idempotent, conflicting bytes remain equivocation, a
deleted or edited body cannot reappear, and a page never describes unavailable
history as complete.

Indexes remain hints rather than grants. Every message, root, reply, edit,
reaction, mention, revision, and tombstone view rechecks both its historical
entitlement and current disclosure boundary. Former members may read only
content already retained and authorized on that device, as a read-only archive.
They receive no new live or catch-up delivery. Owners do not gain workspace-DM
history, and leaving then rejoining a private channel does not bridge roster
eras.

## Consequences

Ordinary startup continues to read bounded workspace/channel/draft summaries;
it does not open message bodies or enumerate event or delivery collections.
The latest-message path opens one bounded index page and at most the requested
message/event records, with request-local caches for repeated immutable
manifest and channel-control verification. New messages carry exact opaque
reaction-state IDs so retained reaction aggregation does not scan the reaction
table. Pre-Increment-9 messages retain a compatibility fallback when first
mutated.

SQLite does not automatically shrink after secure deletion. Pruning makes
pages reusable and exposes freelist growth; a future separately reviewed local
compaction operation may reclaim filesystem size. Increment 9 does not add
local search, peer history catch-up, or remotely enforceable deletion.
