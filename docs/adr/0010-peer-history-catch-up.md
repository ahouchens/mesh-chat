# ADR 0010: Bounded authenticated peer history catch-up

Status: accepted for workspace protocol v1, increment 11.

## Decision

History catch-up is an explicitly requested, peer-to-peer transfer of exact
canonical workspace events already retained by an authorized endpoint. It is
not synchronization with a server and is not evidence of globally complete
history. The LXMF sender of a response is only a forwarder: every embedded
event, control, and checkpoint retains its original canonical bytes and inner
signature and passes the ordinary acceptance/materialization pipeline.

The three additive signed document families are canonical JSON (UTF-8, sorted
keys, compact separators) and reject unknown or missing fields:

```text
workspace_event_checkpoint = {
  v, type, workspace_id, checkpoint_id, author_member_id,
  author_device_id, manifest_digest,
  streams: [{conversation_id, channel_digest, high_water, head_digest}],
  created_at, signature
}

workspace_history_request = {
  v, type, workspace_id, request_id, requester_member_id,
  requester_device_id, manifest_digest, nonce, replay_key,
  scope: {kind, conversation_id, channel_digest, participant_member_ids},
  streams: [{author_device_id, known_high_water, retained_floor,
             head_digest, seen_ranges, gaps, request_ranges}],
  event_limit, byte_limit, continuation, created_at, expires_at, signature
}

workspace_history_response = {
  v, type, workspace_id, response_id, request_id, request_digest,
  requester_member_id, requester_device_id, request_nonce,
  request_replay_key, responder_member_id, responder_device_id,
  scope, event_limit, byte_limit, expires_at, page_index,
  previous_response_digest,
  streams: [{author_device_id, high_water, head_digest, retained_floor,
             available_ranges, gaps}],
  controls: [{kind, document}], checkpoints: [document], events: [document],
  event_count, document_bytes, continuation, complete, created_at, signature
}
```

IDs are UUIDs, digests and continuation tokens are lower-case SHA-256 hex,
nonces are exactly 32 random bytes encoded as unpadded URL-safe base64, and
ranges are sorted inclusive integer pairs with no overlap. Direct-message
scope requires exactly two sorted participants and its deterministic
conversation UUID. Channel scope binds the exact current channel digest and
has no participant list.

## Frozen bounds

- At most 32 streams per request/checkpoint.
- At most 64 ranges across one request and at most 64 ranges in each bounded
  response representation.
- At most 32 canonical events, 32 prerequisite controls, and 32 checkpoints in
  one response.
- The requested response-byte limit is 4 KiB through 128 KiB; the complete
  signed response and the separately counted embedded document bytes are both
  checked. Count or byte disagreement rejects the response.
- A request lives at most 15 minutes. A continuation is single-use, expires
  with the request, and is bound to requester member/device, native source,
  exact scope, streams, limits, preceding response digest, and page index.
- Response construction performs at most 256 direct sequence probes per page.
- There are at most two active jobs per workspace and four per local profile.
  Gap pages return at most 64 entries.
- Existing live delivery still expires after seven days. Catch-up neither
  extends nor reuses a live delivery leg.

These are protocol/implementation ceilings, not availability guarantees.
Advertised heads, retained floors, ranges, and gaps are signed peer claims;
they never prove the peer possesses every preceding body.

## Disclosure and checkpoints

Public history may be disclosed only to a currently active workspace member.
Private history additionally requires current membership and an unbroken
channel-control chain in which the requester is present at every version from
the event era through the current admission era. Removal followed by
re-admission therefore does not bridge the excluded era. Direct history is
available only when requester and responder are the exact two signed
participants. Owner, future administrator, or channel-manager status does not
grant third-party DM access. Former, removed, left, closed, locally removed,
or fork-suspended endpoints receive no new history.

A checkpoint is signed while its author device is active and identifies the
canonical digest at a per-conversation high-water mark. Future workspace or
private-channel removal controls may commit its digest. A response can use an
inactive-author checkpoint only when the applicable current removal control
commits that exact digest, scope and channel kind match, and the supplied event
chain walks backward byte-for-byte through `previous_event_digest` from the
checkpoint head. Public streams use the workspace-manifest commitment;
private streams use the current channel-manifest commitment plus the exact
admission-era rule. V1 deliberately has no third-party DM checkpoint rule.
Missing, stale, conflicting, wrong-scope, uncommitted, or discontinuous
anchors create a bounded permanent gap; they do not transfer trust from the
forwarding peer.

## Validation, replay, and crash behavior

The responder authenticates the current requester and LXMF source before any
scope lookup or response construction. Unauthorized requests return no
existence-dependent response. Serving uses opaque direct stream/sequence
lookups, retained floors, and exact event records; it does not enumerate an
event, message, delivery, or history kind. Private/DM authorization is checked
again for every candidate body.

The receiver first verifies the response signature and every request binding,
then prerequisite controls and checkpoints, then passes events to the normal
canonical verifier. That path enforces author signatures, historical
manifest/channel authority, event UUID, stream sequence, predecessor digest,
mutation revision and target, thread root, audience, equivocation, tombstone,
retention and search-derived state. Controls that cannot yet validate leave
dependent events in the existing bounded encrypted inert queue. Durable
persistence precedes application acknowledgement.

Requests, response IDs, and continuations have independently sealed replay
records. Repeating a response cannot duplicate materialization. Jobs, current
request, previous response digest, peer index, continuation, progress,
uncertainty, retry expiry and failure are sealed and restart-safe. Cancellation
stops local work and an outstanding local leg; it does not delete remote data.
Retention and confirmed workspace erasure remove jobs, request/response caches,
replay/continuation records, checkpoints and peer coverage. SQLite-visible IDs
are HMAC-derived and expose only generic kinds, ciphertext sizes/counts and
access timing.

Multiple peers are attempted in deterministic bounded order. Each signed peer
head is compared with accepted local high-water state. Exhaustion can yield
`complete_known` only within all heads actually signed during the job;
otherwise it yields `peer_limited`, locally pruned ranges or permanent gaps.
The UI always states that another eligible peer may possess unknown history.
A workspace or channel fork suspends the affected job rather than choosing a
branch.

## Compatibility and tradeoffs

All history kinds are additive. Older peers ignore unsupported kinds and
ordinary event bytes, live fan-out, Personal chats, private groups, the frozen
0.2.9 sidecar contract, and the local search format do not change. A peer may
withhold data, lie about availability, disappear, or have pruned a body;
signed uncertainty is preferable to a false completeness claim. Cooperative
deletion cannot erase copies retained by another authorized or compromised
endpoint, and a compromised unlocked endpoint can disclose everything it is
authorized to read.

## Release-minimum benchmark gates

For the named Windows 10 release-minimum profile (Intel Family 6 Model 158,
17,019,686,912 bytes physical memory), the maintained 50,000-event fixture and
30-sample protocol series must satisfy:

- signed request construction plus validation p95 below 100 ms;
- bounded 32-event response construction p95 below 250 ms;
- response signature/binding validation p95 below 250 ms;
- first response verification and durable commit below 2,000 ms;
- end-to-end 32-event catch-up, including continuation, below 3,000 ms;
- restart/resume below 500 ms; and
- duplicate response rejection and private/DM denial below 250 ms.

The evidence must also assert exact canonical-byte equality, replay rejection,
restart durability, private/DM denial, bounded transfer size, eight synthetic
members, 32 channel-control chains, and honest completion wording. These are
release-profile gates, not device-independent latency promises. Existing
startup, paging, search and route-independent send targets remain unchanged.
