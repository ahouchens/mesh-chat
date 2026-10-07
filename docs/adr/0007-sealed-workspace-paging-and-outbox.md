# ADR 0007: Sealed workspace paging and asynchronous outbox

Status: accepted for workspace protocol v1, increment 1.

## Decision

All workspace application records remain independently authenticated and
encrypted by `VaultStore`. SQLite-visible record identifiers are HMAC-derived
opaque values; they do not contain workspace names, channel names, member
names, message text, or raw destinations. Workspace summaries, manifests,
channels, events, derived message state, delivery legs, page indexes, stream
coverage, unread state, drafts, pending controls, scheduler buckets, and
operation results are separate sealed records.

Startup returns bounded summaries and never decrypts message bodies or scans
delivery legs. Each conversation has a sealed head and bounded linked pages of
event references. The default page is 50 messages and callers cannot request
more than 100. An opaque local cursor is MAC-bound to the workspace,
conversation, authorization generation, retention generation, high-water mark,
page, and offset. Any generation mismatch produces an explicit stale-cursor
error.

Every mutation carries a renderer-generated durable `operation_id` distinct
from the IPC request identifier. The vault stores its input digest and result
in the same transaction as the domain mutation. Repeating the same ID and
input returns the stored result; reusing the ID for different input fails.
Message sends also carry a stable event UUID.

A send transaction commits the signed event, derived state, bounded page
update, complete frozen delivery set, due-work entries, stream coverage, and
operation result before returning. Network handoff is never performed inside
the renderer command. Sixty-four sealed due-work shards feed a background
scheduler with bounded batches, retry backoff, expiry, and control-before-data
priority. Restart reconstructs pending work from those shards without scanning
all workspace messages.

Delivery aggregation is materialized with the message state. It reports people
and devices separately; one device proof cannot imply delivery to every person
or device, and native endpoint proof cannot imply that a person read the
message.

## Consequences

The generic encrypted record table remains sufficient for increment 1 because
all hot reads are direct opaque lookups or bounded page/shard updates. Any
future query that requires decrypting an entire unbounded record kind must add
a bounded sealed index or an additive schema reviewed for metadata leakage.
Search, pruning, multi-device compaction, and cooperative history require their
later incremental gates.

