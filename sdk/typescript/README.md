# Mesh Chat Core client (TypeScript)

Experimental client for the framed Mesh Chat Core API, major 1. It wraps the
versioned frame contract only: no authentication, runtime ownership, retry policy
or data directory. The package is private and unpublished; `0.x` versions may
change without notice and are not a redistribution promise until M5's packaged
consumers pass.

`CoreClient.open(transport)` negotiates capabilities once and refuses any
`api_major` other than 1 before issuing another command. Requests are serialized
because a host binding reads one frame at a time.

The envelope is LF-delimited JSON with a 4 MiB ceiling. Mutations carry the
caller-scoped idempotency key the host grants; convergent operations
(`connection.*`, `peer.approve`/`revoke`, pairing, workspace joins, runtime stop)
do not accept one.
