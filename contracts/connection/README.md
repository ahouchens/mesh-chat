# Private connection contracts

These experimental contracts describe protected service observations and private
host bindings. They do not expose event submission to application clients.
The application API is defined separately in `../core-api/`.

`snapshot-v1.schema.json` describes the production projection consumed by Mesh
Chat. Its profile ID is an existing internal connection profile ID. The public
facade must replace internal IDs with caller-scoped opaque handles before
returning observations to independent clients. Runtime epoch and sequence detect
stale observations and gaps; an epoch change requires a fresh snapshot. Readiness
describes current transport/path evidence and never authenticates a receipt.

Producer tests reject undeclared fields, including SDP and resource handles.
Consumers must tolerate additive fields introduced by a negotiated compatible
minor revision. New required fields, changed meanings or incompatible enum values
require a new contract major version. This contract version is independent of
IPC framing, signed peer wire documents, and application release versions.

The current effect boundary is in-process and uses immutable model values. Only
the supervisor supplies operations containing runtime epoch, profile/device key,
generation, policy revision and sequence. A completion must match that operation.
Native allocations additionally bind a private service epoch and increasing
allocation number; adapter callbacks cannot substitute a public session ID.
Cancellation does not release creation reservations. Cleanup resolves the exact
allocated native resource, retains failed cleanup reservations, and cannot retire
another profile's resource. JSON shaped like these values is never trusted
evidence and is not accepted by the ordinary command dispatcher.

The private composition also supplies a `manual_carrier_authorized` domain fact.
The native service derives it from signed SDP, bound control profile and device
identities, current relationship/privacy authority, and a live exact resource.
The runtime and effect executor consume it only for adoption and maintenance of
that carrier. It cannot authorize new signaling, set automatic reconnect consent,
or survive carrier loss. It is absent from public profile responses and the
snapshot schema. The change is private and does not change either wire version.

Workspace transactions additionally use an in-process authority identifier
`("workspace", workspace_id)`. Its producer is the workspace persistence adapter;
its consumer is the connection runtime. It covers every device/profile in that
workspace, including profiles first discovered after a failed write. This is not
a JSON command or native event. Existing contact/profile identifiers and explicit
Stop fences remain independent. A successful matching transaction permits a new
domain scan; it does not itself grant a carrier lease.

## Experimental desktop transport frames v1

`DesktopTransportHost` produces inherited-pipe `desktop_transport` requests;
`DesktopTransportProtocol` consumes them in the trusted browser adapter.
Every request has exactly `v`, `type`, `epoch`, `id` and `request`. The epoch is
a fresh 32-character lowercase hexadecimal service identity. IDs are increasing
positive decimal strings, bounded to unsigned 64-bit values. The browser rejects
old epochs and non-increasing IDs before executing any operation. This is an
internal contract version, independent of snapshots and signed peer documents.

Operations are `createOffer(options)`, `acceptOffer(options, offer)`,
`applyAnswer(resource, answer)`, `inspect(resource)`, `inventory()`, `send(resource, packet)`,
`sendControl(resource, label, text)`, `close(resource)` and `reset`. Options contain
only `resource`, `ice` and `channels`. Resources name exact physical allocations;
packet values are canonical base64 for 1–1,064 bytes. The Python binding accepts
the bridge's native bytes and performs that encoding. No operation selects a
contact, changes consent, signs documents or supplies public caller authority.

Replies contain exactly `v`, `type: desktop_transport_reply`, `epoch`, `id`,
`ok` and `result`. Errors have `ok: false` and `result: null`; browser error text
is not propagated. Observation frames contain exactly `v`,
`type: desktop_transport_event`, `epoch`, `event`, `resource` and `data` and enter
the existing bounded native callback inbox. The sole pipe reader routes these
frames independently of ordinary dispatch and rejects unregistered transport
frames. Application commands cannot register this private receiver. A trusted
platform host can send the exact frame `{v: 1, type: desktop_transport_fault,
epoch}` when its registered window is lost. The Python reader consumes this
private fact, wakes pending requests and quarantines the adapter; old service
epochs cannot retire the current channel.

Frames are limited to 256 KiB, with stricter SDP/control/packet bounds at the
adapter. There are at most 16 outstanding requests and one private writer.
Requests expire after 30 seconds, including time waiting on a blocked writer;
browser operations have a 25-second deadline. Conflicting SDP operations on one
browser peer are rejected before
native dispatch while its current operation is pending; they are not queued or
retried by the adapter. Independent peers share the 16-operation limit. Exact
close/reset can interrupt pending work, and a rejected conflict cannot retire
the active allocation. The private error reply remains redacted. Unknown outcomes quarantine the
channel and enqueue reset after any in-flight write. Pending waiters fail,
old replies cannot revive them, and further admission is denied. Reset is not
proof of native disposal when the pipe is broken: the containing platform host
must independently retire lost bindings. The experimental Windows broker binds
the private command to an exact process PID, window label, fixed local URL and
random capability. The Tauri-injected window identity is checked before queue
access; failed caller authentication cannot drain or retire the legitimate host.
Reply batches have a 64-frame / 2 MiB budget and are validated before pending
requests are consumed. The browser pump has separate reply, lifecycle and packet
queues and only one outstanding normal IPC poll. Lost lifecycle admission or a
five-second stalled poll retires the host. These timers move private frames and
do not implement peer retry policy. Windows qualification and surviving-carrier
adoption remain required before this path can replace the renderer compatibility
runtime.

### Private carrier inventory v1

`native-carrier-inventory-v1.schema.json` describes the optional desktop
`inventory()` result. The browser driver produces it from actual peer objects;
the Python private host validates it. Rust routes the parameter-free operation
through the existing authenticated process/window binding. It is absent from
the application command allowlist and does not change signed peer documents.

An unpredictable adapter epoch distinguishes browser driver incarnations and
must stay fixed within a private service binding. At most 16 records identify
exact physical resources, local/remote description types and SHA-256 hashes,
ICE policy, channel states and unfinished native work. The existing 16-operation
budget also bounds inventory queries. Snapshots taken across resource reuse,
retirement, native operations or observed state changes fail rather than mixing
observations. A transient snapshot race does not quarantine healthy carriers;
malformed inventories or a changed adapter identity do quarantine the binding.

The digest hashes UTF-8 SDP after the existing normalization: split lines, drop
empty lines and exactly `a=end-of-candidates`, and join with LF without a trailing
newline. The shared vectors define browser/Python compatibility. No whitespace,
Unicode or SDP attribute normalization is otherwise allowed. Inventories contain
no SDP text, ICE credentials, peer identity or authorization claim. Consumers
also reject duplicate resource/channel identities, incompatible description
roles and contradictory packet channel state beyond the structural schema.

An inventory is a current mechanism observation, not permission to adopt or
evidence of messaging readiness. Current scope and intent checks, trusted service
rebinding and actual restart/receipt tests are still required before surviving-
carrier adoption can be enabled.

### Protected carrier checkpoint v1

The private desktop service adapter writes `native_carrier_recovery/current`
through the vault's atomic sealed-record update. Its private consumers are the
checkpoint, invalidation and startup reconciliation paths; there is no public
command. Up to 16 entries bind exact physical resources and adapter epochs to
profile/contact/workspace IDs, local/remote device IDs, peer destination, privacy
policy, SDP roles and description hashes. It stores neither SDP/credentials nor
connected/readiness claims. Unknown versions, shapes or duplicate resources fail
closed. Repeating an identical checkpoint is idempotent; rebinding an existing
resource to different evidence is rejected.

An unpredictable persisted revision fences checkpoint writes spanning Stop,
authority changes or retirement. Invalidation removes only matching records
while advancing that revision; subsequent authority writes cannot restore them.
The memory gate closes first, and persistence failures remain failures. Native
inventory collection happens outside the dispatch lock; current lease, binding,
host identity and revision are rechecked before persistence. The authenticated
host pins its adapter epoch, so a checkpoint from a new host discards obsolete
incarnation records. This bookkeeping does not authorize service rebinding or
extend signed capabilities.

The composition root runs one startup reconciliation before actor/profile work.
Native allocation stays closed during this pass. Current journal membership,
domain authority and owner fences are checked around native orphan retirement;
only exact, unambiguous bindings may be registered under fresh logical handles.
No profile is required to retire an orphan. Restored descriptions contain only
the protected hashes and privacy binding, and the normal supervisor must still
claim the carrier and authorize a new bridge. Native callbacks remain tied to
the original physical resource. Storage/adapter failures quarantine startup,
while ordinary rejected candidates are retired. Trusted platform rebinding and
actual service-restart qualification remain separate requirements.
