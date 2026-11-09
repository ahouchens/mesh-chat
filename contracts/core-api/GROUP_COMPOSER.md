# Experimental atomic group composer (API 1.1)

Proposed bounded family: `group.composer_query`, `group.composer_update`,
`group.message_enqueue_draft`. The complete family and all positive
`group_composer_*` limits must be advertised before consumers use it.
This is a local durable acceptance contract, not peer delivery evidence.

All requests carry `profile` and `group` scoped opaque handles. Query accepts an
optional `send_revision`. Update requires `expected_revision` (null initially),
`text`, and the Core-issued `update_key` as the envelope `idempotency_key`.
Enqueue requires `draft_revision` and that exact revision as the envelope key;
it carries no text. Revisions and update keys are 64 lowercase hexadecimal
characters, authenticated to target kind, caller, profile, group and purpose.

Query returns exactly `{profile, group, revision, text, update_key, last_send,
send_lookup}`. Update returns `{applied_revision, changed, composer}`. Enqueue
returns `{profile, group, message, accepted: true, accepted_at,
idempotency_expires_at, draft_revision, draft_disposition, composer}`.
`draft_disposition` is `cleared` or `superseded`. `message` is the existing opaque
group acceptance reference; it does not enable direct `message.query`.

`last_send` is null, an accepted outcome, or an expired outcome. `send_lookup`
is null, an accepted outcome, or `{revision, status: "not_accepted"}`. Accepted
outcomes contain `{revision, status: "accepted", acceptance, text,
draft_disposition}`, where acceptance contains exactly `{profile, message,
accepted: true, accepted_at, idempotency_expires_at}`. Expired outcomes contain
`{revision, status: "expired", accepted_at, idempotency_expires_at}`. Explicit
lookup of an expired or erased acceptance returns `idempotency_expired`.

Query performs no writes. Updates use compare-and-set and preserve completed
update receipts, including no-op updates. Enqueue commits the exact composer
revision, prepared group message, sender sequence, recipient outbox legs,
bounded quota, global operation receipt, send receipt, clear/new revision and
last-send pointer in one conditional transaction. A retry returns the original
acceptance and current composer; it never overwrites a newer draft. Membership,
posting policy and current grants are checked before fresh work and replay.
All three operations require current `read`; update and enqueue also require
`send`, because their results include protected draft and acceptance text.
No peer or scheduling effect occurs before commit. A committed durable outbox
may be woken afterward.

Bounds: `group_composer_text_utf8_bytes=16384`,
`group_composers_per_caller_profile=256`, `group_composers_per_vault=4096`,
`group_composer_update_idempotency_seconds=3600`,
`group_composer_update_keys_per_caller_profile=8192`,
`group_composer_update_keys_per_vault=65536`,
`group_composer_send_idempotency_seconds=604800`,
`group_composer_send_keys_per_caller_profile=4096`,
`group_composer_send_keys_per_vault=65536`. Expired send keys remain consumed;
quota exhaustion refuses fresh sends rather than recycling an old revision.
Consumed update keys also remain bounded and consumed after expiry; exhausted
update capacity refuses fresh keys instead of forgetting prior outcomes.

Only a trusted host's existing private composer-migration flag may preview and
adopt shared `group_draft` text. Public legacy `group.draft_set` writes become
caller/profile/group scoped and never expose shared UI text. Initial migration
atomically deletes and permanently fences its old source; later legacy writes
cannot replace protected state, even before a new Core binding after reopen.
Group/draft erasure and membership termination clear protected text and rotate
revision/update credentials. A replay cannot resurrect erased content.

Required evidence before readiness: actual encrypted signed groups and framed
Core requests; CAS and transaction rollback; lost commit reply/reopen; newer
draft preservation; current authority and cross-caller/group rejection; source
erasure and legacy fences; bounded expiry/quota; installed Python and TypeScript
consumers. Independent UI/platform qualification remains separate.
