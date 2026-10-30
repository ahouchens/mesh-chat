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
