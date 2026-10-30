# Experimental Core API v1 design

These are M1 design contracts, not a supported integration release. The facade,
host authentication, complete result/event schemas, SDKs and independent consumer
qualification remain required before M5. `operations-v1.json` deliberately lists
no implemented operations. A schema-valid request is not authorization and must
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
implemented by these schema files.

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
Idempotency retention and expiry must be negotiated and specified in the complete
result contract before this operation can be advertised as implemented. No
implicit retry after retention expiry is permitted in an SDK.

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
