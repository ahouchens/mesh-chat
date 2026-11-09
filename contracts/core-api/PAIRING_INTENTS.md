# Experimental supervisor pairing intents

API 1.1 adds `peer.pairing_begin`, `peer.pairing_query` and
`peer.pairing_cancel`. All require current `approve` permission and a host-bound
profile. Begin and cancel require explicit caller envelope keys. The public
family is advertised only with a concrete shared-native actor/host and the
actor's durable-cancellation and terminal-checkpoint hooks. Current source work
is gated while C supplies those hooks; this document does not qualify native
traffic, an independent app host or SC21.

Begin parameters are `{profile,role:"offer"|"answer",pairing_code?,
allow_direct_ip_disclosure?}`. Offer must omit `pairing_code`; answer requires
1–2048 UTF-8 bytes of valid admission code for the configured mailbox. Disclosure
consent is an explicit boolean, default false; the existing actor selects relay
policy when consent is absent. Query/cancel parameters are `{profile,pairing}`.
The pairing handle is opaque and caller/profile scoped. Public JSON cannot
select caller identity, native operation UUIDs, resource leases, grants, SDP,
vault paths or keys.

Every successful result has exactly `{profile,pairing,state,expires_at,
pairing_code}`. The nullable code is shareable admission material, available
only in `offer_ready` and only to the authorized original caller/profile.
States are `reserved`, `offer_ready`, `awaiting_approval`, `transferred`,
`retiring` and `retired`. Transfer is onboarding custody transfer; it does not
claim an approved contact, authenticated message delivery or connection readiness.
Cancel after transfer preserves `transferred` and cannot reclaim the carrier.

Core atomically persists the canonical public key receipt, caller/profile index,
quota and active-intent pointer before invoking the actor. The actor's child
operation UUID is derived deterministically from the public operation UUID and
has its own existing durable admission-before-I/O receipt. Replaying the public
key resumes only this child. A failed return between either admission commit
cannot create a replacement. Receipts contain digests and selected references,
without copies of SDP or pairing secrets. Codes stay in the existing actor's
protected runtime context.

Cancellation records its exact target/key and a durable cancellation flag before
invoking the actor. Its trusted cancellation callback must fence asynchronous
work even if the API call never reaches the effect after a lost commit return.
The actor remains responsible for late allocation, physical cleanup and resource
transfer. Core never closes a native resource itself. A terminal callback from
actual acknowledged retirement/handoff checkpoints the selected terminal state
and clears only that intent's active pointer in one CAS. A failed checkpoint
cannot release the pointer or authorize replacement. A same-runtime public
mutation can also reconcile an already acknowledged terminal actor state.

Durable terminal observations remain queryable after reopen. An interrupted
nonterminal intent returns `resync_required`; a new runtime, absent context or
missing reply is not retirement proof. No automatic replacement key or native
reallocation is allowed. A caller that loses the begin reply replays its original
key and parameters. This family does not provide a catalog for callers that lose
all local intent keys; full renderer-restart recovery remains additional work.

The original absolute deadline is passed to child admission and never renewed
by retry. Expiry also makes the trusted stop callback true, while current grant
checks remain available for cleanup. If public reservation committed but child
admission never did, an expired same-runtime replay can acknowledge `retired`
from the absent child receipt under the dispatch lock. It cannot allocate any
native resource. An admitted child needs its actual terminal acknowledgment;
expiry alone reports `retiring`, without an admission code.

Bounds are advertised under `pairing_intents_per_runtime` (32 retained actor
intents), `pairing_active_intents` (1), `pairing_intent_seconds` (300),
`pairing_code_utf8_bytes` (2048), `pairing_key_idempotency_seconds` (604800),
`pairing_keys_per_caller_profile` (4096) and `pairing_keys_per_vault` (65536).
Receipts are retained at capacity; new keys fail `resource_exhausted`, and old
keys never become fresh by expiry/eviction. Actor expiry bounds the onboarding
intent; the code's underlying mailbox format is a separate existing protocol.
The first public intent raises the vault format floor to 2 atomically. The
pinned API 0.2 format-1 reader refuses it before service construction.

SDK helpers are:

- TypeScript: `pairingBegin(profile,role,key,{pairingCode?,allowDirectIpDisclosure?})`,
  `pairingQuery(profile,pairing)`, `pairingCancel(profile,pairing,key)`.
- Kotlin: `pairingBegin(profile,role,key,pairingCode?,allowDirectIpDisclosure=false)`,
  `pairingQuery(profile,pairing)`, `pairingCancel(profile,pairing,key)`.
- Python: `pairing_begin(profile,role,key,*,pairing_code=None,
  allow_direct_ip_disclosure=False)`, `pairing_query(profile,pairing)`,
  `pairing_cancel(profile,pairing,key)`.

Helpers require minor ≥1, all three operations and all seven positive integer
bounds before I/O. They preserve supplied keys and never retry, invent keys or
expose the private qualification/native-command port. Generic `request` remains
an explicit transport primitive; server authority and feature gates still apply.
