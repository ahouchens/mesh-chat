# Experimental Core API v1 design

These are experimental contracts, not a supported integration release. A protected
facade component implements capabilities, profile queries, connection observations,
peer queries, durable text enqueue, scoped message snapshots and retained change
replay with durable consumer progress for messages enqueued by the same caller,
bounded enumeration of received inbound text, and bounded current-policy diagnostics.
Host authentication, remaining
mutations/event streams, SDKs and independent consumer
qualification remain required before M5. `operations-v1.json` deliberately lists
no host-accessible implemented operations; its separate component list records
the tested internal facade subset. A schema-valid request is not authorization and must
not be passed to the existing broad application command dispatcher.

The initial scope includes profile/identity ownership, explicit pairing and
approval, connection intent, text messages, event recovery and safe diagnostics.
Workspace administration, media calls, private adapter operations and arbitrary
filesystem access are separate interfaces. Additional message kinds require
explicit capabilities and schemas before clients can enqueue them.

## Trust and binding

The trusted application host authenticates callers before constructing a facade
session. The session holds its caller ID, operation permissions and allowed
profile scopes; none of those facts come from request JSON. Windows bootstrap
must bind a private IPC endpoint to the owning process/user with OS access
controls. Android bootstrap must bind the runtime to its owning application and
non-exported service. Localhost reachability is insufficient. Neither binding is
implemented by these schema files. The `core_api.composition.bind_service_session`
factory is private bootstrap code, absent from the renderer command table. It
accepts a host-bound grant callback, holds the service dispatch lock through
authorization, observation and the complete enqueue transaction, and rechecks
current grants on every request.
This component does not itself authenticate a Windows or Android IPC peer. A
private Windows named-pipe endpoint now exists beside it as component evidence:
its descriptor admits only SYSTEM and the current user, remote clients are
rejected, and the connecting executable must match a host-supplied allowlist
before a frame is read. A bounded number of concurrent local clients is served,
each with the host-supplied caller and permissions; idle sessions are closed so a
silent client cannot hold a slot. Android's Binder binding and packaged consumers
remain required.

Within the component, each session negotiates through `runtime.capabilities`.
Other operations before negotiation return `negotiation_required`; unimplemented
operations return `unsupported_operation`. Revoked caller identity invalidates
the session permanently. Permission or profile-scope revocation denies access
before domain reads. Caller/profile-bound HMAC handles expose no internal IDs and
remain stable for the same caller and vault. A new vault changes their namespace.
Sessions cannot silently switch caller identities. Detach only closes that session.
The successful observation contract is `observation-result-v1.schema.json`; it
selects fields explicitly, replaces internal profile/connection IDs with handles,
and cannot elevate transport readiness into a delivery receipt. Profiles and
connections are limited to 256 each; overflow fails instead of truncating results.
When the message port is bound, profile queries also return at most 256 opaque peer
handles. The private service adapter reads at most 257 contacts to detect overflow.
`peer.query` resolves a selected handle to display name, destination and trust,
without exposing identity records, signaling secrets or transport state.
It never scans message history to resolve a public handle. This component binds
one local profile per service. An unbound profile fails closed.

Every handle resolves within the authenticated caller's permitted profile scope.
A handle from another caller/profile must fail before any effect or database
write. A credential handle is an opaque, short-lived reference issued by trusted
bootstrap; it is not a vault key or a filesystem path. The public surface cannot
submit platform facts, native events, internal resource IDs or delivery receipts.
Permission names in the manifest are separate grants; `read` does not imply
`send`, `approve`, `connect`, or runtime ownership.

## Experimental stream framing

The private `bind_service_stream` factory wraps a host-authenticated session in
`FramedSession`. It is absent from the application command dispatcher. This adapter
is not an authentication mechanism, a socket listener or a public bootstrap API.
The host supplies private binary streams, authenticates their owning application,
and enforces access controls, I/O deadlines and connection/worker limits. A local
socket or an arbitrary caller-provided identity is not sufficient authority.

A frame is one UTF-8 JSON value followed by LF; CRLF is also accepted. Each frame,
including its delimiter, is at most 4,194,304 bytes. Requests are compact single-line
JSON; literal line breaks inside a string must be escaped. Responses use ASCII-safe
JSON escaping and one LF delimiter. No byte-order mark is accepted. The request
must still match its operation schema; a JSON array is not a batch of commands.

Before dispatch, the codec rejects duplicate object members at any depth, including
names made identical by Unicode escapes. It rejects invalid UTF-8, unpaired escaped
surrogates, non-finite numbers and integer literals outside the portable signed
range from -9,007,199,254,740,991 through 9,007,199,254,740,991. Requests may nest at
most 16 objects/arrays and contain at most 1,024 structural tokens (`{ } [ ] : ,`
outside strings). The structural check precedes JSON object allocation. Quoted
brackets, commas and escaped quotes do not consume this budget. Frame, depth and
structural-token limits are included in capability negotiation.

Malformed encoding or framing produces one bounded `invalid_request` response with
null correlation and permanently detaches the session. The adapter stops reading
that stream; it never drains untrusted trailing bytes to find another command.
A well-formed JSON request with a semantic error receives the facade's normal typed
response and can be corrected on the same session. An invalid or oversized server
response produces a selected `internal` error and detaches without exporting raw
exception text. Hosts close the underlying streams when serving ends.

The stream driver reads at most the frame budget plus one overflow-detection byte,
executes one request, and writes and flushes its complete response before reading
another. It retains no response queue and performs no domain retries. Short writes
are completed without repeating the command. EOF, partial frames, read errors and
write/flush errors detach the session. Blocking stream I/O occurs outside the
service dispatch lock. A caller losing a mutation response must reconnect through
its trusted host and resolve the unknown outcome with the original idempotency key;
closing the stream does not undo a committed message or stop the app-owned runtime.
This framing has component and in-memory stream evidence only. OS-authenticated
Windows/Android endpoints and packaged consumer interoperability remain unfinished.

## Request and outcome rules

Requests use `request-v1.schema.json`. Unknown request properties and operations
are rejected. All operations require version negotiation before mutation.
Request IDs correlate responses only. Mutation idempotency is scoped to caller,
profile, operation and key, with a payload digest; conflicting reuse fails.
The existing IPC frame limit remains four MiB. The facade must additionally
enforce the declared UTF-8 byte limits, because JSON Schema string lengths count
characters. Whitespace-only text is invalid at the domain boundary.

Enqueue succeeds only after the existing message/outbox transaction and its
idempotency record commit together. The result returns the durable logical
message handle, not a delivery claim. A timeout after dispatch leaves an unknown
outcome that is resolved by the original idempotency key or a scoped query.
The experimental component negotiates seven days of replay retention, 4,096 keys
per caller/profile and 65,536 keys per vault. Acceptance includes an absolute
`idempotency_expires_at`; `message-result-v1.schema.json` specifies acceptance and
query results. Keys and encrypted message indexes are retained for the vault's
lifetime, including after history deletion. They contain no duplicate message
text. Keys are never silently evicted or reusable: after retention or deletion of
the original message, replay returns `idempotency_expired`. Conflicting payloads
return `idempotency_conflict`. Tombstones count toward capacity, so saturation
returns `resource_exhausted` for new keys while existing unexpired keys remain
replayable. These conservative experimental quotas need a long-term storage
policy before M5; clients must not delete a vault or invent a new key to resolve
an uncertain outcome. No implicit retry after retention expiry is permitted in
an SDK. A query can still return a retained message after its enqueue key expires.

Message, encrypted idempotency receipt, caller-scoped query index, quota and
conversation visibility change commit atomically. Commit failure produces
`unavailable` without acceptance. Queue/observer hints happen afterward; a crash
before a hint is recovered by the ordinary durable outbox at startup. Enqueue
does not synchronously send on a transport or introduce another retry loop.
Request IDs have no effect on mutation identity. Digests and index IDs use keyed,
unambiguous encodings; caller IDs, keys and text are not stored in clear indexes.

Enqueue requires the current `send` grant and approved/verified contact trust,
including on replay. Query requires `read`, the same caller/profile, and current
contact approval. `observe` alone grants neither. Queries expose only the selected
message fields and return `not_found` after local deletion. A public caller cannot
choose a logical message ID, set delivery state, or submit a receipt. The ordinary
application's pending-consent workflow is unchanged; the experimental public
enqueue cannot create pending-contact chat.

Only an authenticated application receipt establishes `delivered`; endpoint
receipt and propagation storage keep their existing distinct meanings. An event
acknowledgment records local consumer progress and cannot alter peer delivery
state. Stop and revocation fence work immediately and report persistence failures
without claiming durability. Start/retry cannot bypass consent, cooldown, native
capacity or an explicit Stop that has not been superseded by a committed Start.

## Observation and recovery

Connection observations use runtime epoch and sequence; gaps or epoch changes
require a fresh scoped snapshot. The experimental message recovery component uses
`message.list` followed by `events.poll`. Its result contract is
`recovery-result-v1.schema.json`.

Start a snapshot with a null cursor. Follow each `next_cursor`, accumulating pages
until it is null. Only that final page supplies `events_cursor`, the high watermark
captured at the start of the snapshot. Poll from that cursor to obtain subsequent
changes. If messages change during pagination, or the contact-authority view
changes, the component returns `resync_required`; discard partial pages and start
a fresh snapshot. It never combines different revisions into a successful
snapshot. Changes committed after the completed snapshot appear in replay, closing
the query/subscribe race. This conservative pagination can require a fresh attempt
under sustained writes; it does not hold a vault lock across client requests.

Replay returns ordered, content-free `message.changed` and `message.removed`
notifications with stable caller-scoped event/message IDs. A changed event includes
the committed delivery state; it cannot turn endpoint evidence into application
delivery. Polling the same cursor may redeliver the same IDs. Consumers deduplicate
notifications and query retained messages when they need text. Local history
deletion produces a removal event without retaining duplicate text. Public replay covers the caller's own facade-enqueued outbound text messages and
the inbound chat messages of currently approved contacts; each event states its
direction, and an inbound event's handle is the same opaque handle that
`message.received` returns. Other message kinds and connection event streams are
still required for M5.

## Received messages

`message.received` pages the inbound chat messages an authorized profile already
accepted, oldest first. Its result contract is `received-result-v1.schema.json`.
A received message carries a caller-scoped opaque `message` handle, the `peer`
handle of its contact, the retained text, the committed delivery state and
`created_at`. It never returns an internal message or contact identifier, a native
message hash, conversation markers or signaling material. This is a read of
already-committed domain records: it performs no transport work, sends no receipt
and cannot promote one.

The service maintains a content-free index of inbound chat messages as a second
transaction-local projection. It commits in the same vault transaction as the
visible message and its receipt, so a reader never sees a message without its
position or a position without its message. The index retains only the message
identity, contact identity and creation time; text, receipts and native metadata
stay in the authoritative record and are read from it. Outbound messages, receipts
and every non-chat kind are not indexed, so this surface cannot enumerate another
direction or domain records. Deleting a message removes its index entry in the same
transaction.

Pagination uses an opaque cursor bound to caller, profile, purpose and the current
contact-authority view. Start with a null cursor and follow `next_cursor` while
`more` is true. Each page reflects the committed state of its messages; a message
whose state changed moves nowhere in the index. Revoking or blocking a contact, or
removing a profile, invalidates the cursor and returns `resync_required`; hidden
messages are omitted rather than partially reported. Cursors expire with the seven
day replay window, cannot be exchanged with snapshot or replay cursors, and cannot
be used by another caller. At most 128 indexes are scanned per request, and the
whole encoded page stays within one MiB.

This closes inbound text enumeration and its replay for the private facade
component. Other message kinds, connection intent commands, authenticated host
bindings and packaged consumers remain unfinished.

The service installs the domain journal before startup recovery and workers. Every
message mutation path uses one transaction-local storage projection, so the message
and its change record commit or roll back together, including batch writes and
history deletion. A source namespace may carry several independent projections; each
observes the same committed changes, sees no sibling's derived records, and any
failure aborts the whole transaction. Native-only metadata and unchanged public
message fields do not advance the stream. The vault depends on an injected
projection port; it contains no message or receipt policy. Domain delivery logic
remains authoritative.

The encrypted journal retains at most 2,048 changes per vault. Replay is limited
to seven days and available retained records. Opaque cursors use the existing vault
record cipher, are bound to caller/profile and purpose, and survive ordinary service
restart. They expire seven days after issuance. Retention overflow, expiry or changed
authority returns `resync_required`. A null poll cursor resumes the last durable
acknowledgment for the current caller/profile; without a valid retained checkpoint,
it requires a fresh snapshot. Old binaries without the journal and stream
format migrations are not qualified cursor-compatible runtimes.

After durably applying a completed snapshot or event page in its own application
state, a consumer sends `events.ack` with the final `events_cursor` or replay
`next_cursor` and an idempotency key. A partial snapshot cursor is not an event
position and cannot be acknowledged. Acceptance atomically commits the encrypted
caller/profile checkpoint, receipt and quota. The result selects `checkpoint`,
`acknowledged_at` and `expires_at`, with `acknowledged: true`. This records consumer
progress only; it writes no message, outbox or peer receipt. Polling is read-only:
it neither advances nor renews confirmed progress. Multiple sessions of one caller
share one checkpoint per profile, so independently progressing applications need
distinct trusted caller identities.

Acknowledgment identity uses the logical stream generation, authority and position,
not randomized cursor bytes. A reissued cursor for the same position resolves the
same key. A conflicting position with that key returns `idempotency_conflict`;
a new key for a position behind the current checkpoint returns `conflict`. Replaying
an older successful key returns its original acceptance without rewinding progress.
Current grants, profile availability, stream generation and contact authority are
rechecked even on an idempotent replay.

Checkpoints and successful acknowledgment receipts expire seven days after commit.
An original key may resolve a lost reply after its input token expires or its history
is overwritten, while the receipt remains live. That result proves the past write;
it does not promise the checkpoint is still resumable. A new write needs a live
cursor and retained history. `events.poll` with a null cursor reports
`resync_required` on an expired, revoked or overwritten checkpoint; a complete fresh
snapshot and a new acknowledgment repair that gap. After receipt expiry the old
key returns `idempotency_expired`, never a new acceptance. Tombstones are retained
for the vault lifetime, with separate acknowledgment quotas of 4,096 keys per
caller/profile and 65,536 per vault. Capacity returns `resource_exhausted` for new
keys without evicting existing ones. These quotas are experimental and remain
subject to the long-term storage-policy work before M5.

Each request scans at most 128 query indexes or journal entries (plus one index
lookahead), returns at most the requested 1–128 items, and stays within one MiB
including JSON escaping. Sparse caller scopes may yield empty intermediate pages;
continue while `next_cursor` is non-null or replay `more` is true. Index order is
opaque and is not a chronological ordering promise. Cursor tokens are bounded to
1,024 ASCII bytes and have a separate schema from object handles. Grant checks,
current profile availability and contact approval apply to every recovery request.
No polling operation mutates peer delivery state or adds a peer retry policy.

## Current policy diagnostics

`diagnostics.query` requires the dedicated `diagnose` permission and an authorized
profile after capability negotiation. `observe`, `read` and `send` do not imply
this grant. The private adapter checks current profile availability before reading
policy observations; identity, permission and profile revocation are rechecked on
every request. The result contract is `diagnostics-result-v1.schema.json`.

The query returns a capture timestamp, `available`, an allowlisted
`runtime_failure`, and selected connection observations using the same caller/profile
handles as `connection.snapshot`. `available` means shared-policy diagnostics exist;
it does not claim a working transport or delivery. A legacy-only runtime returns
`available: false`, an empty connection list and no failure claim. Known runtime
failures are `adapter_quarantined` and `cleanup_failed`; other string values become
`unknown`. Observations retain their runtime epoch and sequence, and cannot promote
transport readiness to a message receipt.

The required `limit` is 1–256. Results are selected in opaque handle order with
`total_connections` and explicit `truncated` metadata when the requested limit is
smaller than the bounded snapshot. There is no history cursor or pagination promise:
queries observe current policy, and callers needing all entries request 256. More
than 256 internal entries fails with `resource_exhausted` instead of hiding an
unbounded source. The entire encoded response stays within 256 KiB. These count
and byte bounds are negotiated in capabilities.

This query does not export the existing application-wide diagnostic history, which
lacks caller/profile ownership. It performs no vault writes, retention cleanup,
message scans, native inspection, signaling or lifecycle effects. It excludes
peer labels, addresses, raw native IDs, private documents and exception text.
Authenticated host bindings and packaged consumer qualification are still required
before this experimental component becomes a supported diagnostic API.

Detach closes the client session, not the app-owned runtime or durable outbox.
Only `runtime.stop` with the runtime-owner grant requests shutdown. SDK recovery
reattaches to the existing host and resynchronizes observations; it never starts
a second peer reconnect policy or competing data-directory owner.

`error-v1.schema.json` provides bounded, stable errors without raw exception text.
A retry hint does not grant permission or bypass a cooldown. Public API major,
SDK/package version, internal IPC version and signed peer wire version remain
distinct. The support matrix is unfrozen until independent packaged consumers
pass M5; these documents make no historical compatibility promise.
