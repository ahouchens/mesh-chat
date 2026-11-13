# Experimental protected call-operation recovery

The API 1.1 component extension is available only when a trusted host supplies a
complete media retirement port to `bind_service_session/stream(call_retirement=...)`.
Ordinary bindings omit all three operations and continue the existing
`call.control` implementation for vaults that have never activated this extension.
After activation, an unbound host refuses call mutations with `resync_required`;
losing a provider cannot reopen the legacy route around durable ownership fences.
A placeholder retirement provider must never be
installed in production. Current packaged hosts do not bind this port; this is
component infrastructure, not completed renderer or native recovery.

`call.operation_list {profile}` returns `{profile, operations:[...]}`.
`call.operation_query {profile, operation}` returns `{profile, operation:{...}}`.
Both require current `read` permission. `call.operation_abandon` has the same
parameters, requires current `send` permission and an explicit caller-owned
envelope idempotency key. Every request rechecks caller grants and profile scope.
Handles are opaque and caller/profile scoped. A foreign handle cannot cancel a
call. No request field selects a host, owner incarnation, epoch or private key.

The selected operation shape contains `operation`, `call`, `runtime`, `action`,
`accepted_at`, `expires_at`, `expired`, `current_runtime`, `state`, `disposition`
and `replacement_safe`. It contains no SDP, ICE candidates, raw domain IDs,
caller replay keys or media handles. Dispositions are `live`,
`terminal_unretired`, `unknown_runtime`, `cleanup_pending` and `retired`.
Only `retired` yields `replacement_safe:true`. Signaling end, expiry,
`resync_required`, a missing media record or a different service epoch cannot
establish media retirement.

For bound hosts, a new acquisition's catalog row, call-state writes (only when
the existing signaling-storage preference enables them), signaling outbox,
quota and original global command receipt share one conditional vault commit.
Renderer memory is unnecessary to discover an accepted acquisition. Replaying
the original key never creates another call. Abandonment atomically fences the
call, records cleanup intent, removes superseded protocol outbox rows and queues
one cancellation signal if the peer remains approved. Already handed-off packets
are not recalled. Replays of abandonment use the original intent without another
hangup. Peer revocation allows cleanup but does not authorize a new signal.
The first protected acceptance raises the vault format floor to 2 in the same
transaction; the pinned API 0.2 format-1 reader refuses that vault before opening
the service. An acceptance rollback preserves format 1.

Bounds are advertised as `call_operations_per_caller_profile` (256),
`call_operations_per_vault` (4096), `call_operation_keys_per_caller_profile`
(4096), `call_operation_keys_per_vault` (65536) and
`call_operation_retention_seconds` (604800). Keys and catalog entries are retained
at capacity; new commands fail `resource_exhausted`, while accepted-key replay
remains available. Expiry is an observation requiring reconciliation, not an
eviction or permission to reconstruct media. This bounded component intentionally
does not implement indefinite retention, pagination or automatic pruning.

The trusted per-session port supplies an immutable, host-issued
`owner_incarnation` (16–128 URL-safe characters) and nonblocking
`request_retirement(ticket)`. The frozen `CallRetirementTicket` contains the
internal operation ID, call ID, service epoch, authenticated caller, internal
profile and the original media-owner incarnation captured at acceptance. It is
never serialized publicly. Return `None` while cleanup remains pending, or an
exact `CallRetirementAcknowledgment(ticket, retired=True)` after the original
owner's resources have drained. Boolean values, mismatched tickets and mere
signaling terminal states are rejected. The acknowledgment is then persisted
before the public result can permit replacement. The host must retain custody
across renderer/service replacement and reconcile pending durable intents after
restart; an unavailable old owner remains pending.

For asynchronous completion, trusted host code calls
`acknowledge_call_retirement(current_service, exact_acknowledgment)`. It rechecks
all six ticket fields against the protected row and the committed abandonment
intent, persists retirement by CAS and emits normal state invalidation. It can
complete an old-owner ticket against the replacement service's same vault. A
read-only renderer query then observes the durable result; no second cancellation
request is necessary. This function is not a request operation or native-command
allowlist entry.

For browser A/V, retirement includes stopping the exact owned MediaStream
tracks, closing its RTCPeerConnection, releasing audio ownership and draining or
invalidating pending getUserMedia acquisition so a late stream cannot escape
cleanup. Native data-channel retirement cannot substitute for browser-media
proof. Renderer acknowledgments require a host-issued challenge tied to the
authenticated caller/profile/renderer incarnation/operation; ordinary public
JSON cannot attest host retirement. C/B actual owner tracking, challenges,
restart custody and the trusted port implementation remain integration work.
Binding must also reconcile pre-extension calls and acquisitions begun before
an acceptance receipt exists; this catalog alone cannot prove those resources
absent. Unacknowledged renderer draft text and group/workspace atomic composers
are separate open work.

SDK helpers are `callOperationList/Query/Abandon` (TypeScript/Kotlin) and
`call_operation_list/query/abandon` (Python). They require API minor ≥1, all
three advertised operations and all five positive integer bounds before I/O.
They do not invent keys, retry automatically or capture media. An unknown
outcome keeps the original target/key until the authoritative disposition is
known; no new SDP or replacement call is authorized by a generic error.
