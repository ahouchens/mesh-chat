# ADR 0006: Canonical workspace events and history safety

Status: accepted for workspace protocol v1; cooperative history is deferred.

## Decision

Workspace-visible content is an immutable, canonical, inner-signed event. In
increment 1 a workspace event is only a message and binds:

- workspace, conversation, and stable event UUIDs;
- author member and device UUIDs;
- a positive per-device stream sequence and previous-event digest;
- the exact manifest and channel-control digests that authorize it;
- the message payload, fixed empty mentions, and no thread root; and
- its creation time and author-device signature.

The canonical event envelope is at most 20 KiB and message text is at most
16 KiB UTF-8. Exact fields, type values, integer bounds, identities,
signatures, control digests, author membership, posting permission, stream
predecessor, and destination binding are verified before the event changes
visible state. One sequence cannot name two different events. A conflicting
valid event or manifest suspends the affected workspace instead of silently
choosing a branch.

The event's audience is frozen from the referenced signed controls when the
event and all recipient delivery legs commit. The scheduler sends missing
manifest and channel controls before dependent events. A receiver that lacks a
valid referenced control or predecessor holds the event inert in a bounded
encrypted queue; it does not display or acknowledge it as an application
message. Increment 1 caps inert dependent events at 256 and records explicit
incomplete-sync state when safe application cannot continue.

Local message visibility is derived state. Hiding records a local sealed marker
that suppresses the derived message but does not rewrite the signed event or
claim remote deletion. Unread position is local per conversation. Native endpoint
proof is displayed as endpoint receipt evidence and never as human read
evidence.

## History boundary

Increment 1 exchanges only live controls and live events; it does not provide
cooperative history or backfill. The vault nevertheless records per-stream
high-water, retained coverage, and predecessor information so future history
cannot turn an absent event into proof that no event existed. A future history
increment must add signed range requests and bounded responses, preserve
explicit permanent gaps, revalidate historical permission, and define
checkpoint eligibility before inactive-device events can be imported.

New members receive no earlier events by default. Workspace owners and admins
do not gain special access to direct-message history. Attachments, edits,
deletes, reactions, threads, private channels, search exchange, and history
sync remain separate increments rather than ambiguous event variants.

## Consequences

Event validation is independent of arrival order but not independent of its
signed authorization history. Historical controls must be retained for as long
as a dependent event is retained. Approximate UI ordering may differ between
peers; the per-author stream detects equivocation without pretending to be a
global sequencer.
