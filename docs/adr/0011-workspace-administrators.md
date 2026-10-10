# ADR 0011: Workspace administrators and owner-approved requests

Status: accepted for workspace protocol v1, increment 12.

## Decision

A workspace has exactly one active `owner` and zero or more active `admin` and
`member` roles. The authority device remains the owner's device. Administrators
are operational peers, not co-authorities: they may exercise a signed policy or
manage a channel whose manager key they hold, but only the authority device may
publish membership and role manifests.

The policy values are frozen as follows:

- `channel_creation`: `all_members | owner_and_admins`;
- `posting`: `all_members | owner_and_admins`; and
- `invitation_requests`:
  `owner_only | owner_and_admins | all_members_request`.

All active members may read channels to which their exact workspace and channel
controls admit them. Under `owner_and_admins`, an active owner or administrator
may create a channel or post; reactions continue to follow readership, not the
posting policy. A channel's signed manager alone may update, archive, change a
private roster, or offer its management. Administrator status confers no control
over another manager's channel. Public recovery remains owner-only; private
recovery still requires the owner to be in the signed roster. Neither owner nor
administrator status reveals an unlisted private channel or another pair's
workspace DM.

Only the owner may change workspace metadata, retention, policies, closure,
authority, or ownership. Increment 12 does not implement authority rotation or
ownership transfer. Members retain their display-name and leave workflows.

## Canonical document family

`workspace_admin_request` is canonical UTF-8 JSON with sorted keys, compact
separators, no unknown or missing fields, and an RNS identity signature over the
object without `signature`. It has two frozen phases. The request phase is:

```text
{
  v, type="workspace_admin_request", phase="request",
  workspace_id, request_id,
  request_kind="invitation"|"member_removal"|"role_change",
  base_manifest_epoch, base_manifest_digest,
  requester_member_id, requester_device_id,
  target_member_id, requested_role,
  note, replay_key, created_at, expires_at, signature
}
```

For `invitation`, target and requested role are null. For `member_removal`, the
target is one active nonowner and role is null. For `role_change`, the target is
one active nonowner and role is exactly `admin` or `member`; no-op changes are
invalid. The signer must be the named active device at the exact base manifest.
Invitation request authority follows the exact invitation policy. Removal and
role-change requests require owner or administrator. A request is audit input,
never authority or evidence of an effective change.

The decision phase is:

```text
{
  v, type="workspace_admin_request", phase="decision",
  workspace_id, request_id, request_digest, request_kind,
  base_manifest_epoch, base_manifest_digest,
  authority_member_id, authority_device_id,
  outcome="approved"|"declined",
  result_kind="invitation"|"manifest"|"no_change",
  result_digest, result_document,
  replay_key, created_at, signature
}
```

The signer must be the exact active owner authority device. A decline has
`no_change`, null result fields, and creates no invitation or manifest. Approval
of an invitation embeds one bounded, one-use authority-signed
`workspace_invite`; it does not admit a member. Approval of removal or role
change embeds the one resulting authority-signed manifest. The decision binds
the exact request UUID and digest, workspace, base epoch and digest, kind,
authority, result digest, and fresh replay key. The embedded result's canonical
bytes are revalidated. LXMF forwarding identity never replaces the inner
signer, and the native source must bind to that signer when received directly.

## Approval and manifest transitions

The owner revalidates current status, role, authority, policy, target and base
state at approval time. An approval performs exactly one enabled operation:

- create one invitation;
- deactivate one eligible active nonowner using the existing removal and
  inactive-author checkpoint rules; or
- change exactly one active nonowner between `member` and `admin`.

A role epoch preserves owner, authority device, membership status, metadata,
policy, retention, admission state, closure state, devices, and every other
member role. It cannot be combined with another mutation and cannot be a no-op.
Demotion takes effect immediately under the new manifest but does not invalidate
historical events or channel controls that were valid under their exact prior
manifest. Promotion or demotion does not change channel managers. A private
channel manager must be transferred through the existing signed offer and
successor acceptance before removal.

The owner may use the direct authority path for a single role change or removal;
the result is the same constrained manifest transition. Receiving such a
manifest before its supporting request or decision does not weaken ordinary
manifest validation.

## Lifecycle and crash behavior

- `pending`: a verified request has no authority decision and changes no
  effective role or membership.
- `approved`: one owner-signed decision identifies and embeds the exact
  invitation or manifest result.
- `declined`: one owner-signed `no_change` decision exists.
- `stale`: the signed base or current authorization can no longer be evaluated
  as requested.
- `superseded`: a committed authority transition already resolved the same
  target/effect.
- `expired`: the request lifetime elapsed before a decision committed.
- `cancelled`: the requester cancelled only before handoff; this is a local,
  non-authoritative terminal state.

Delivery, endpoint receipt, presentation, and request presence never imply
approval. Each request accepts at most one decision. Exact duplicate request or
decision delivery is idempotent; a different decision for the same request
fails closed as a security conflict. A committed decision wins over later
expiry. Manifest application deterministically marks incompatible outstanding
requests stale or superseded. Local dismissal hides a completed presentation
row but retains its canonical outcome until normal retention.

Request creation atomically commits the sealed request, operation result,
outbound legs, and due-work state. Owner approval or decline atomically commits
the decision, invitation/manifest result, audit state, result legs, and durable
operation result. Retries return the committed operation and cannot generate a
second result. Restart resumes bounded pending work. Workspace erasure removes
the request, decision, replay, inert, cursor/index and delivery records.

## Frozen bounds and local representation

- request: 4 KiB encoded; decision including result: 48 KiB encoded;
- note: 250 normalized Unicode characters;
- lifetime: at most seven days;
- pending: 128 per workspace, 512 total per profile, and 32 per authenticated
  requester/source;
- list page: 1 through 100 rows, default 50;
- future/inert decisions: 64 per profile; and
- request, decision and replay audit retention: 90 days after terminal expiry.

Worst-case non-ASCII notes, embedded invitations/manifests, encoded sizes,
unknown fields, noncanonical input and overflow are tested. Incoming, outgoing,
decision, state, retry, expiry, replay, delivery and bounded page indexes are
independently sealed. Record IDs and cursors are HMAC-derived and opaque; visible
SQLite kinds, ciphertext sizes/counts and timing reveal neither names, targets,
roles, destinations, invitation secrets nor canonical documents. Startup,
status, paging and scheduling use bounded indexes rather than whole-kind scans.

## Abuse and review safety

Every request and decision is hostile until canonical encoding, size, lifetime,
signature, device/member binding, native source, exact base, role/policy and
result binding validate. Removed, inactive, left, suspended or wrong-workspace
actors are rejected without protected-channel or DM existence-dependent lookup.
Floods stop at the per-source, workspace, profile and inert-decision bounds.
Owner review shows requester, action, target and a current-state warning before
confirmation; pending rows always retain the effective current role. Destructive
removal requires confirmation.

A compromised administrator can create/post where policy allows, operate only
channels it legitimately manages, and spam valid requests up to the bounds. It
cannot sign a manifest, change global policy, recover or discover an excluded
private channel, inspect third-party DMs, rotate authority, close the workspace,
or make a pending request effective. Partitions delay learning demotion/removal;
each receiver nevertheless enforces the newest verified controls it has and
converges conservatively when the new manifest arrives.

## Compatibility and downgrade behavior

The family and role transition are additive to protocol v1. Existing owner and
member manifests, event bytes, Personal chats, private groups, channels, DMs,
threads, mentions, mutations, reactions, retention, search and catch-up do not
change. An older peer may ignore the unsupported administrative document but
must never treat it as a manifest. If it cannot safely interpret a role-bearing
manifest, it suspends only that workspace; Personal traffic remains available.
The frozen 0.2.9 contract and immutable 0.2.31 behavior remain compatibility
gates.

## Release-minimum benchmark gates

On the named Windows 10 release-minimum profile (Intel Family 6 Model 158 and
17,019,686,912 bytes physical memory), the maintained 50,000-event fixture,
eight members, 32 channel-control chains, three encrypted profiles and at least
30 protocol samples must pass:

- request construction/validation p95 < 50 ms;
- owner-review page p95 < 100 ms;
- decision construction/validation p95 < 100 ms;
- role-manifest durable commit p95 < 250 ms;
- invitation approval p95 < 250 ms;
- owner-offline admin channel create/post p95 < 250 ms;
- duplicate/replay rejection p95 < 50 ms;
- stale/superseded resolution p95 < 100 ms;
- restart/resume < 2 seconds;
- end-to-end request, approval and result delivery < 5 seconds;
- peak Python allocation < 512 MiB, working set < 1.5 GiB, and each profile's
  vault growth < 64 MiB.

Evidence records OS, CPU, runtimes, memory, sizes, queues, routes, transactions,
first-visible/effective timings, vault growth, all terminal-state counts, replay,
conflict and private/DM confidentiality assertions. Existing startup, paging,
search, catch-up and route-independent send gates remain unchanged.

## Rejected alternatives and accepted tradeoffs

Shared authority keys, direct administrator manifest signing, multiple owners,
majority voting, threshold authority, hosted approval, trusted relays and
automatic private-channel recovery were rejected: each expands compromise or
availability trust and belongs outside Increment 12. Requests deliberately wait
for the single owner authority, so permanent owner-key loss remains unresolved
until Increment 13. Administrative convenience therefore improves daily
operation but does not improve authority availability. Cooperative deletion
cannot erase already received copies, and a compromised unlocked endpoint can
disclose everything it is currently authorized to read.
