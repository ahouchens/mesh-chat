# Experimental Core API v1 design

These are experimental contracts, not a supported integration release. A protected
facade component implements capabilities, profile queries, connection observations,
peer queries, durable text enqueue and queries of messages enqueued by the same caller.
Host authentication, other mutations/events, SDKs and independent consumer
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
This component does not itself authenticate a Windows or Android IPC peer.

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
require a fresh scoped snapshot. Message/receipt event cursors are separately
durable, opaque and caller/profile-bound. The future subscribe/list handshake must
return a consistent snapshot and high watermark, then replay events after that
watermark. Expired cursors return `resync_required`; slow consumers cannot stall
connection control. Batches are limited to 128 records and one MiB.

Detach closes the client session, not the app-owned runtime or durable outbox.
Only `runtime.stop` with the runtime-owner grant requests shutdown. SDK recovery
reattaches to the existing host and resynchronizes observations; it never starts
a second peer reconnect policy or competing data-directory owner.

`error-v1.schema.json` provides bounded, stable errors without raw exception text.
A retry hint does not grant permission or bypass a cooldown. Public API major,
SDK/package version, internal IPC version and signed peer wire version remain
distinct. The support matrix is unfrozen until independent packaged consumers
pass M5; these documents make no historical compatibility promise.
