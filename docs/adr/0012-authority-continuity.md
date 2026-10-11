# ADR 0012: Workspace authority continuity

Status: accepted for workspace protocol v1, increment 13.

## Decision

A workspace continues to have exactly one active owner member and exactly one
authority device belonging to that owner. Human ownership and the device that
may sign the next manifest are distinct fields. Increment 13 adds two and only
two transitions between devices already present in the exact base manifest:

- `same_owner_rotation` changes the authority device to another active device
  of the same owner and changes nothing else; and
- `ownership_transfer` changes the sole owner to one named active nonowner,
  makes one named device of that member the authority, and changes the outgoing
  owner to the `admin` or `member` role explicitly selected in the offer.

There is no device enrollment in this increment. Same-owner rotation is shown
only when a seeded or otherwise already admitted second owner device exists.
Linking, replacement, fan-out changes and lost-device removal remain Increment
14 work.

An offer and acceptance are inert consent records. The current authority signs
the offer, the exact successor device signs the acceptance, and the current
authority signs the final authority-changing manifest. Only durable application
of that final manifest changes effective authority. The successor signs all
later ordinary manifests; the old authority cannot do so. Historical manifests
and events remain checked with the authority present in their own signed era.

## Canonical documents

Canonical documents are compact sorted-key NFC UTF-8 JSON, reject unknown or
missing fields, and use the existing domain-separated RNS identity signature.
UUIDs are canonical lower-case strings; digests are lower-case SHA-256 hex;
destinations are re-derived 16-byte hashes encoded as lower-case hex; nonces are
32 random bytes encoded as unpadded URL-safe base64.

The offer phase is:

```text
workspace_authority_transition = {
  v=1, type="workspace_authority_transition", phase="offer",
  workspace_id, transition_id,
  transition_kind="same_owner_rotation"|"ownership_transfer",
  base_manifest_epoch, base_manifest_digest,
  current_owner_member_id, current_authority_device_id,
  current_authority_destination,
  successor_member_id, successor_device_id, successor_destination,
  outgoing_owner_role=null|"admin"|"member",
  general_channel_id, general_channel_head,
  general_disposition="unchanged"|"recover",
  nonce, replay_key, created_at, expires_at, signature
}
```

For same-owner rotation the outgoing role and both `#general` fields are null
and disposition is `unchanged`. For ownership transfer the outgoing role is
explicit, the exact active public `general` channel UUID and head are present,
and disposition is `recover`.

The acceptance phase is:

```text
workspace_authority_transition = {
  v=1, type="workspace_authority_transition", phase="acceptance",
  workspace_id, transition_id, transition_kind,
  base_manifest_epoch, base_manifest_digest,
  offer_digest, offer,
  current_owner_member_id, current_authority_device_id,
  successor_member_id, successor_device_id,
  general_channel_id, general_channel_head, general_disposition,
  replay_key, accepted_at, signature
}
```

It embeds the complete canonical offer and repeats every routing and consequence
field. Every repeated value must equal the offer byte-for-byte. Its signer is
the exact successor device at the base manifest. An LXMF forwarder never gains
authorship; direct delivery additionally binds the native source to the inner
signer. Authorized forwarding retains the original inner bytes.

Offers and acceptances are respectively capped at 8 KiB and 16 KiB. They live
for at most seven days. There are at most 32 pending transitions per workspace,
64 inert future controls per profile, and eight future manifests. Replay and
terminal audit records remain for 90 days. Exact duplicates are idempotent;
reuse of a transition ID, nonce, replay key, acceptance slot or result slot with
different canonical bytes is an authority conflict.

## Final manifest boundary

Legacy manifests are byte-for-byte unchanged. An authority-changing manifest
uses two additive fields:

```text
authority_transition_digest = SHA-256(canonical acceptance)
authority_signer_destination = predecessor authority destination
```

The manifest still names the resulting authority device and destination. Its
signature is verified with `authority_signer_destination`, which must be the
predecessor manifest's authority and an admitted device in the result. The
ordinary manifest path rejects either additive field and continues requiring
the same authority device and signer.

The authority path validates the exact predecessor, offer, acceptance, signer,
kind, base epoch/digest, identities, destinations, nonce, replay keys and
lifetime. It advances exactly one epoch and preserves the manifest hash chain.
It rejects any membership, device, status, metadata, retention, policy,
closure, checkpoint or unrelated-role change. Rotation preserves every role.
Transfer changes exactly the outgoing owner and successor roles and leaves one
active owner whose named device is the sole authority. A final document signed
only by the successor, signed by the old authority without acceptance, tied to
another offer, stale, expired, replayed or combined with another mutation is
invalid.

The complete final manifest and required `#general` result commit in one vault
transaction on the finalizing device. Remote final manifests remain inert
until the exact transition records and `#general` result are present. A crash
before that commit leaves the prior authority effective; a retry uses the same
durable operation result and canonical documents.

## `#general` continuity

Ownership transfer uses the existing authority-signed public-channel recovery
document at the exact signed `#general` head. It assigns management to the
successor device named in the accepted ownership offer. The manifest and
recovery are one local atomic outcome and are delivered as prerequisites plus
the final manifest. A receiver checks the old authority signature, exact base
manifest, channel UUID/head and successor before applying the final manifest.

No other public channel is transferred or recovered. Private channels are
never enumerated, disclosed or recovered by this workflow. Existing private
managers and all workspace-DM audiences remain unchanged. A channel-only fork
stays scoped to that channel, except a `#general` conflict that prevents proving
the ownership result leaves the authority transition incomplete and inert.

## Authority certificate chain and invitations

`authority_chain: []` remains the canonical value for workspaces whose
authority has never changed. Each later entry contains exactly:

```text
{
  base_manifest,
  offer,
  acceptance,
  final_manifest,
  general_result=null|workspace_channel_recovery
}
```

The verifier starts at the immutable genesis workspace ID, creator anchor,
genesis owner, original authority card and genesis digest. For each entry it
checks the current authority's base checkpoint, offer, successor acceptance,
old-authority final signature, resulting owner/authority, exact predecessor and
`#general` recovery. Steps must be ordered, unique and nontruncated. The offered
checkpoint and invitation signature must end at the final proven authority.
Existing members extend their locally validated chain; only a new joiner uses
an invitation checkpoint.

The frozen maximum is eight authority transitions and 256 KiB of decoded
bootstrap JSON. Parsing checks bytes and counts before signature work. Link/text
entry is capped at twice that encoded-input boundary. The UI renders a QR only
when the resulting link is at most 4096 characters; larger valid proofs remain
available as copy/share text. Reaching the transition or byte bound fails
honestly and directs the owner to create a replacement workspace; proofs are
never truncated.

Unused invitations survive same-owner rotation because ownership and the
admission grant do not change, but the invitation must still carry a proof
ending at the current invitation signer. Ownership transfer supersedes every
outstanding unused invitation. An old invitation cannot bypass the new owner.
Single-use nonce, expiry, revocation and offered-manifest validation remain.

## Persistence and lifecycle

Offers, acceptances, results, replay keys, audit summaries, certificate steps,
delivery legs and due work are separate sealed records addressed with local
HMAC-derived opaque IDs. SQLite-visible fields expose generic kinds, ciphertext
sizes/counts and timing, not raw member/device UUIDs, destinations, transition
kind, names, documents or private relationships. Startup and presentation use
bounded records; ordinary message history is never scanned.

Presentation states are `waiting_for_delivery`, `waiting_for_acceptance`,
`accepted_waiting_finalization`, `finalizing`, `applied`, `expired`, `stale`,
`superseded`, `cancelled`, `incomplete_control_state` and `forked`. Delivery is
not acceptance, and acceptance is not transfer. A committed result wins over
later wall-clock expiry. A newer incompatible manifest makes a pending result
stale. Local dismissal never changes canonical state.

## Forks and permanent loss

Two different valid manifests for one epoch, conflicting canonical offers or
acceptances for one transition ID, or conflicting consumed replay keys suspend
the workspace. No timestamp, arrival order, route, visibility majority or user
choice selects a branch. Workspace-dependent sends, history, DMs, membership,
administration, authority/channel transitions and closure pause; validated
local history and both conflicting records remain for diagnosis and export.
Personal traffic remains available.

Permanent loss of the current authority key is not recovery. The app can mark
authority-dependent administration permanently frozen while ordinary already
authorized chat continues. It explains creation of a replacement workspace and
fresh invitations. It does not clone keys, vote, recover from private channels,
copy secret identity material or silently import unverified state.

## Compatibility and tradeoffs

Old genesis, manifest and event bytes do not change. An old peer may ignore the
new wire kind, but a transition manifest is not a legacy manifest and cannot be
accepted as old-authority ordinary state. A peer unable to validate the proof
suspends only that workspace. Personal chats, private groups, public/private
channels, DMs, mutations, reactions, retention, search, history and the frozen
0.2.9, 0.2.31 and 0.2.32 contracts remain independent compatibility gates.

Rejected alternatives are shared or cloned authority keys, multiple owners,
administrator signing, voting, quorum/majority choice, threshold or social
recovery, hosted approval/recovery, trusted relays, automatic branch selection,
silent proof truncation and private-channel recovery by an excluded owner.
They either expand compromise authority, disclose protected relationships or
pretend an unavailable key can be recovered safely.

## Release-minimum benchmark gates

On the named Windows 10 minimum profile (Intel Family 6 Model 158 and
17,019,686,912 physical bytes), the 50,000-event/eight-member/32-channel fixture
and 30-sample protocol series must satisfy: offer and acceptance construction
plus validation p95 below 100 ms each; final construction/commit and application
p95 below 500 ms each; `#general` recovery p95 below 250 ms; maximum-depth chain
construction and fresh verification p95 below 2 seconds; duplicate, replay,
stale and expired rejection p95 below 100 ms; restart/resume below 2 seconds;
and end-to-end convergence plus one successor authority operation below 5
seconds. Peak Python allocation remains below 512 MiB, working set below 1.5
GiB and each participating vault grows by less than 64 MiB. Existing startup,
paging, search, catch-up, administration and route-independent send gates remain.
