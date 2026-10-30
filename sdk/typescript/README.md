# Experimental TypeScript Core API client

This package is a thin, strict client for the private Mesh Chat Core API frame
contract. It is **experimental**: no supported Windows or Android host endpoint
exists yet, so an independent application cannot yet install this package and
reach a runtime. Do not treat it as a supported integration release.

## What it does

- Speaks the single-line UTF-8 JSON framing documented in
  `contracts/core-api/README.md`, including the four-MiB frame ceiling and the
  declared request/correlation grammar.
- Negotiates `runtime.capabilities` on `open()` and exposes the negotiated
  operations and limits.
- Serializes requests because the host binding reads one frame at a time, and
  matches each response to its own request ID.
- Maps stable error codes to a typed `CoreError` carrying the retry hint;
  malformed, oversized or uncorrelated frames become `ProtocolError`; a closed
  stream becomes `TransportClosedError`; a missed deadline becomes
  `TimeoutError` with an explicitly unknown outcome.
- Provides typed helpers for profile query, connection snapshot,
  `message.received`, durable enqueue, event polling, acknowledgment and
  diagnostics, and refuses out-of-bounds limits or a missing idempotency key
  before writing anything.
- Exposes a resynchronizing `CoreConsumer`: it walks every snapshot page,
  adopts the replay watermark, deduplicates redelivered event ids, clears its
  position on `resync_required` instead of skipping, and only acknowledges a
  position the caller confirms it applied. It never polls on a timer.
- Accepts an `AbortSignal`. Cancelling before dispatch writes nothing;
  cancelling a dispatched request reports an unknown outcome and never resends.

## What it does not do

- It does not authenticate a caller, open a socket, start or stop a runtime,
  own a data directory, or retry peer connections. Those are host and service
  responsibilities.
- It carries no peer retry policy, no native adapter and no private Python
  imports. It cannot grant consent or pair a peer.
- It is built and tested by general verification CI, but no package is published
  and no support matrix exists. Kotlin, parallel in-flight requests, automatic
  poll scheduling and cursor-expiry recovery beyond `resync_required` remain
  open.

## Usage

```ts
import { CoreClient } from "@mesh-chat/core-client";

// `transport` is supplied by a trusted host binding; this package never makes one.
const client = await CoreClient.open(transport);
const profile = client.capabilities.profiles[0];
const page = await client.received(profile, null, 64);
for (const message of page.messages) console.log(message.peer, message.text);
```

## Tests

From this directory, with the repository's Node and TypeScript available:

```sh
node ../../node_modules/typescript/bin/tsc -p .
node --test "dist/**/*.test.js"
```

Nineteen tests cover negotiation, request shapes, bounded limits, typed
failures, correlation, EOF, timeout and abort without resend, serialization
under concurrency, idempotency requirements, strict framing, snapshot
resynchronization, event deduplication, esync_required\ handling and
confirmation.
