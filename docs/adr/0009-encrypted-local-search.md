# ADR 0009: Encrypted bounded local workspace search

Status: accepted for workspace protocol v1, increment 10.

## Decision

Workspace search is a local derived view over data already retained on one
device. It does not send a query, result, token, or search request to a peer.
The index is an authorization hint only: every candidate is opened from the
encrypted vault and rechecked against its canonical event, historical
entitlement, current workspace/channel/direct-message disclosure rule, local
hide and deletion state, thread root, and retention boundary before any text
or snippet is returned.

Normalization is frozen as Unicode NFKC, Unicode default case folding, then
NFC. Tokenization keeps Unicode letters and numbers, plus combining marks
attached to a preceding letter or number. Punctuation, symbols, separators,
controls, and whitespace are boundaries. Tokens shorter than 2 characters or
longer than 64 characters are omitted. Duplicate tokens collapse in
first-occurrence order. A query is exact-token AND search: it accepts 1–256
Unicode code points, at most 1,024 UTF-8 bytes, and one to eight retained
tokens. Prefix, substring, fuzzy, and remote expansion are not implemented.

Each token is addressed by an HMAC-derived opaque identifier scoped to the
workspace. Sealed token pages hold at most 100 opaque document references. A
sealed document contains only opaque token IDs and encrypted entity metadata;
the message, person, or channel presentation text remains in its authoritative
sealed record. One document indexes at most 512 unique tokens and one profile
retains at most 2,000,000 search references. A query selects the least common
exact token, opens at most eight shard pages and 256 candidates, and returns at
most 50 results (25 by default). The other query tokens are checked first
against opaque document token IDs and then against freshly tokenized decrypted
content.

Ordering is deterministic. Authorized message roots precede replies, followed
by people and channels. Messages and replies sort newest first and then by
event UUID; people and channels sort by their stable entity UUID. Pagination
is over that bounded candidate window, so reaching a shard or candidate limit
is reported as incomplete rather than implying complete global coverage.
All-result search includes both roots and replies; the Messages filter selects
roots, and Threads selects replies. Results carry an explicit reply flag and
root UUID so the renderer opens the exact conversation or thread.

Authenticated cursors contain no raw query. They bind the workspace, an opaque
normalized-query digest, an opaque scope digest, authorization generation,
retention generation, search generation, selected opaque token shard, shard
head, and result offset. A changed query, scope, access boundary, retention
boundary, index generation, shard, or MAC fails explicitly instead of mixing
result sets.

New messages and winning edits update message state and search records in the
same vault transaction. Edits remove obsolete references before adding the
winning text. Author deletion, local hide, and pruning deactivate the exact
document and remove its token references. Reaction-only mutations do not touch
message tokens. Directory changes replace current person names and visible
channel name/topic documents. Access checks remain authoritative even if a
crash or hostile stale index leaves a candidate reference behind. Confirmed
local workspace erasure includes every search state, catalog, document, and
shard record.

An existing 0.2.29 profile starts with a metadata-only directory migration and
truthful `rebuilding` status. Retained events are processed newest-first from
the sealed retention index in restart-safe transactions of at most 128 events.
The next retention page, offset, target, indexed count, and generation persist
before yielding. Ordinary startup does not enumerate event or message-state
tables, and search remains bounded while the UI states that results are
incomplete. Pruning and retention changes invalidate cursors; pruned-count and
bound state distinguish retained, indexing, pruned, and incomplete coverage.

## Leakage and consequences

SQLite can reveal generic record kinds, opaque keyed IDs, encrypted record
sizes, counts, update times, and access timing. A party holding the vault key
can compute tokens and decrypt the local history; this design does not protect
an unlocked compromised endpoint. Without that key, SQLite-visible fields and
cursors contain no query text, message text, person/channel name, raw
destination, or unhashed token. Repeated HMAC IDs expose equality only inside
the keyed local database, and independent profile keys prevent cross-profile
token correlation.

Exact-token search deliberately omits partial matching and may omit a token
outside the documented length, document-token, reference-growth, shard, or
candidate bounds. It may also be incomplete during migration or after local
history gaps. The UI must say so. Search never repairs missing peer history,
does not imply that another device has erased data, and does not broaden a
former member's, private-channel member's, or workspace-DM participant's
authority.
