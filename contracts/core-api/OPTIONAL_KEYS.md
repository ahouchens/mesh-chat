# Optional caller-key extensions

API1.1 hosts may advertise `optional_keyed_operations`. The first implemented
entries are `group.create` and `group.message_enqueue`. Only concrete bound
preparation ports advertise them. Existing operation/parameter shapes remain;
the envelope additionally accepts an explicit caller `idempotency_key`.
Unkeyed legacy calls retain their existing repeatable behavior. SDK0.3 helpers
take an optional final key argument, require advertised support before sending
a keyed call, and never invent a key or fall back to an unkeyed mutation.

The capability includes three positive integer limits:
`optional_key_idempotency_seconds=604800`,
`optional_keys_per_caller_profile=4096`, and `optional_keys_per_vault=65536`.
Quota, primary group/message rows, recipient legs, hidden-conversation deletion,
the caller receipt and global `workspace_operation` intent/result commit in one
conditional transaction. Replays validate current profile/contact/group
membership/posting authority first. A conflicting operation or payload using the
same caller/profile key fails before preparation/crypto allocation. Original
receipt pointers are used; replay never creates another group, message, sender
sequence or recipient leg. It may wake an existing durable outbox job only.

Keyed acceptance does no peer transport I/O. Group creation returns the selected
current view of the original group. Keyed group sending preserves legacy
`sent:true` (local enqueue only), and adds `accepted:true`, a caller-scoped opaque
`message` reference, `accepted_at`, and `idempotency_expires_at`. These fields
prove historical local acceptance, not delivery or authenticated receipt. The
group message reference is currently an acceptance reference, not a direct
`message.query` handle. General first-class group history/query expansion remains
separate work.

Receipts store row references and hashes, never a second copy of message text.
Erased primary rows or expired receipts return `idempotency_expired`. Expired
key records remain bounded and are not silently evicted: an old key cannot
become fresh. Capacity rejects new identities; old live identities still replay.
No supported release, unbounded key lifetime or automatic maintenance policy is
declared by this experimental extension.

The remaining mutation audit stays open. In particular, other group mutations,
reaction/invitation parents, target-derived workspace removal IDs, connection
resource changes and legacy unkeyed calls do not acquire caller-key guarantees
merely because these two operations are advertised. Peer wire and private IPC
versions remain unchanged. Actual installed SDK0.2 legacy group calls and
installed SDK0.3 keyed calls are qualified separately against the concrete host.
