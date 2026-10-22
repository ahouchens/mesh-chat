# Workspace Connectivity and Reachability

Status: Phase 1 implemented in 0.9.3; Phase 2a implemented in 0.9.4; Phase 2b
implemented in 0.9.5; Phase 3 implemented in 0.9.6; Phase 4 implemented in
0.9.7; Phase 5 protocol primitives implemented in 0.9.8; service/UI planned for
0.9.9; later phases proposed.

## 1. Problem

Workspace membership is an authorization fact, not a network path. Admission
bootstraps the joiner to the owner/authority device. Ordinary channel, DM,
thread, mention, history and control events are then copied to every active
recipient device and require a usable Reticulum path between the sender and each
recipient. The owner is not automatically a relay, and a participant-hosted
invitation listener is not a general transport node.

That creates four user-visible gaps:

1. A workspace can be admitted but only partially connected. Some member pairs
   can exchange messages while others cannot.
2. Automatic reconnect is contact-scoped. Workspace-only devices have no
   reconnect profile, capability, or mailbox rendezvous.
3. There is no first-class per-member/per-device reachability view, so partial
   delivery is discovered only from individual message receipts.
4. Membership changes, policy, retention and ownership still require the one
   owner authority device to be online.

This is intentional peer-dependent architecture, not a hosted-room bug. The gap
is that reachability is neither visible nor actionable enough for a core
collaboration feature.

## 2. Goals

- Make per-device workspace reachability explicit without implying authority,
  presence, or a read receipt.
- Give users a bounded, explicit action to request missing Reticulum paths.
- Preserve the no-server, no-owner-relay, no-shared-key architecture.
- Keep every connectivity fact advisory. Only signed manifests, channel
  controls, events, and application receipts can change authorization or
  delivery state.
- Add later workspace-scoped recovery without turning the owner, a helper, or a
  relay into an authority.

## 3. Non-goals

- No hosted workspace relay, mailbox history, or always-on workspace server.
- No automatic owner relay, automatic Reticulum transport enabling, or hidden
  fallback.
- No automatic contact creation or membership merge.
- No claim that a known path means a human is present or has read a message.
- No files, calls, public discovery, multi-owner authority, or remote wipe in
  this increment.

## 4. Reachability model

Phase 1 derives advisory states from the current verified manifest and existing
per-device delivery evidence:

| State | Meaning |
| --- | --- |
| `local` | This device; no network path is needed. |
| `reachable` | Reticulum currently reports a path to the device destination. |
| `recently_reached` | No path is currently known, but an endpoint/application receipt was observed within the recent window. |
| `store_and_forward` | At least one delivery is held by an approved LXMF propagation node; this is not an endpoint or human receipt. |
| `queued` | Local outbox work exists but no path and no recent reachability evidence. |
| `unreachable` | The latest delivery failed/expired/cancelled and no path is known. |
| `unknown` | No path and no delivery evidence for this device yet. |

`route_kind` uses the existing safe route labels (`nearby`, `signed_direct`,
`remote`, `participant_direct`, `unavailable`). It never exposes endpoints,
IFAC credentials, TURN credentials, or public keys.

Delivery evidence is read from existing `workspace_delivery` records. A
`stored_for_delivery` proof is not converted into `delivered`. The UI must say
that workspaces are peer-dependent and that membership does not create a route.

## 5. Phase 1 — visible reachability (implemented)

### Service commands

`workspace_connectivity`

Input:

```json
{"workspace_id": "<workspace uuid>"}
```

Output:

```json
{
  "workspace_id": "<workspace uuid>",
  "generated_at": 1800000000.0,
  "summary": {
    "active_members": 3,
    "active_devices": 5,
    "reachable_devices": 3,
    "attention_devices": 2,
    "pending_deliveries": 4,
    "stored_deliveries": 1
  },
  "members": [
    {
      "id": "<member uuid>",
      "display_name": "Alex",
      "role": "owner",
      "status": "active",
      "devices": [
        {
          "id": "<device uuid>",
          "display_name": "Alex laptop",
          "is_local": false,
          "state": "reachable",
          "path_known": true,
          "route_kind": "nearby",
          "pending_deliveries": 0,
          "stored_deliveries": 0,
          "last_delivery_state": "delivered",
          "last_attempt_at": 1800000000.0,
          "last_reached_at": 1800000000.0
        }
      ]
    }
  ]
}
```

The command is read-only and never changes membership, trust, routes, settings,
or delivery state.

`workspace_request_paths`

Input is the same. It first computes the status, then calls the existing bounded
Reticulum path-request API for each active remote device whose path is not
currently known, and returns a freshly computed status. It does not probe
arbitrary addresses, open listeners, enable transport, or attach profiles. The
UI labels it **Request missing paths** and explains that Reticulum path discovery
is asynchronous.

### UI

The workspace **People and administration** dialog gains a **Connectivity**
section:

- summary counts: reachable devices / active devices, queued deliveries;
- one row per member device with a state badge, route label, pending count and
  last-reached time;
- a **Request missing paths** action that also refreshes the status; reopening
  the dialog refreshes it as well;
- explicit copy that membership is not a route, that the owner is not a relay,
  and that a propagation-node proof is not delivery.

### Privacy and authority

- Only active members in the current verified manifest are listed.
- No destinations beyond the already-public workspace member model, no endpoints,
  no public identities, no message text, and no credentials cross the boundary.
- The command requires an existing active workspace; it does not expose another
  profile's workspace.
- Connectivity output is not signed, not replicated, and never enters a
  manifest, channel, receipt, or delivery decision.

## 6. Phase 2 — shared workspace access recommendation

### Phase 2a — out-of-band recommendation (implemented in 0.9.4)

The owner authority device can turn an already-approved Remote Connection
Profile into a `MESHACCESS1:` **workspace access recommendation**. The document
is signed by the current workspace authority and binds:

- the workspace ID;
- the exact current manifest digest;
- the canonical remote profile (access endpoints and optional propagation node);
- creation and expiry times.

The service verifies the signature, profile, dates and canonical bytes before
use. An import is accepted only when the local workspace is active, the digest
matches the current manifest, the signer is the current authority destination,
and the local member is active. A stale manifest, old authority, expired
document, or tampered bytes fail closed.

Distribution is out-of-band: the owner copies or shares the complete text through
any channel already used for invitations. This deliberately avoids requiring a
working member path to deliver the access recommendation. Each member previews
the operator disclosure and must explicitly consent before the profile is
attached with workspace scope. Applying it does not grant membership, approve a
device, change authority, or make the owner a relay.

Commands:

- `create_workspace_access_recommendation` — active owner authority device only;
- `preview_workspace_access_recommendation` — verify against the current
  manifest and return a safe disclosure;
- `apply_workspace_access_recommendation` — require consent and attach the
  profile to the workspace scope.

The renderer exposes this as **Workspace settings → Workspace access point**:
owners select an approved profile and create/copy the recommendation; any active
member can paste, preview, consent, and attach one.

### Phase 2b — automatic delivery (implemented in 0.9.5)

The owner authority can queue the same signed recommendation to every active
workspace member device through the existing per-device workspace delivery
machinery (`send_workspace_access_recommendation`, wire kind
`workspace_access_recommendation`). The recommendation is one signed document,
not a per-device grant; delivery retries, expiry, and partial-delivery evidence
remain per device.

Recipients verify the authority signature and store only the signed document and
safe summary. They cannot attach it without the same preview and explicit
consent. The out-of-band Phase 2a path remains available when no member path
exists. Automatic delivery cannot make the owner a relay, grant membership, or
change transport policy.

Delivery to the local authority device is skipped. A stale recommendation remains
visible as stale and cannot be applied until the owner reissues it against the
current manifest.

### Phase 2c — automatic access (not planned)

Automatically attaching a profile or changing transport policy without explicit
local consent is out of scope. A recommendation is not a grant.

## 7. Phase 3 — workspace-scoped reconnect (implemented in 0.9.6)

Workspace-only devices can now participate in the same opt-in mailbox reconnect
protocol as Personal contacts without creating a contact.

- `MESHWSR1:` wraps an ordinary signed `connection_capabilities` document with
  the exact workspace ID, manifest digest, wrapper signer, and expiry. The
  wrapper and the inner capability must be signed by the same current active
  workspace device, and the inner `peer_destination` must be this device.
- Profiles are keyed by `workspace:<workspace>:<member>:<device>`, not by a
  contact. No contact, approval, manifest, or workspace authority is created or
  changed.
- The workspace toggle is **off by default**. Enabling it requires an explicit
  per-workspace consent for automatic reconnect and a separate direct-IP
  disclosure choice. The service creates one profile per active peer device,
  issues a fresh pair capability/token, and queues a
  `workspace_reconnect_capability` workspace control to each device.
- Each recipient verifies the wrapper against its current active membership,
  verifies the inner capability signer/destination, and stores the peer
  capability without changing its own consent. Both sides must enable the
  workspace before the renderer coordinator considers the profile ready.
- The existing coordinator, offer/answer documents, mailbox TTL/rate limits,
  replay cache, backoff, one-offer glare control, and two-attempt bound are
  reused. At every authorization jump the synthetic peer is rechecked against
  the current workspace manifest; removed devices/workspaces fail closed.
- `workspace_reconnect_status` and `workspace_reconnect_consent_set` expose the
  consent/summary; the renderer starts no peer connection before both sides
  consent and a mailbox session exists.

Known limits: reconnect runs only while the app is open and unlocked; there is
no takeover when the preferred device is offline; mailbox delivery requires a
configured `signal_mailbox_url`; no physical multi-device workspace reconnect
test has been performed.

## 8. Phase 4 — optional member helper (implemented in 0.9.7)

A reachable active workspace device can now carry **one signed connection
update** between two other active devices. This is the participant-assisted
recovery path from the roadmap, implemented without a hosted rendezvous.

- The helper feature is **off by default**. A member must explicitly opt in with
  `workspace_helper_consent_set` before this device will relay anything.
- The sender uses `relay_workspace_connection_update` with an established
  workspace/direct relationship ID and a selected active helper device. The
  service exports the sender's existing signed `mesh-recover:` update and wraps
  it in a bounded `workspace_connection_relay` control containing the workspace,
  origin device, audience device, and document.
- The first hop verifies the native source equals the claimed origin device and
  that origin/audience are current active devices. If the audience is this
  device, it applies the update through the existing DirectRecovery verifier.
  Otherwise, an opted-in helper queues the same wrapper to the audience only.
- A second helper receiving a wrapper whose native source is not the origin
  ignores it, so forwarding stops at one hop. The recipient applies the original
  signed document; the helper cannot forge or alter its audience, endpoints,
  membership, or receipts.
- Helpers see the connection-update document (endpoints and timing) inside their
  own encrypted delivery. They do not see chat, history, message receipts,
  workspace authority, or private keys, and they cannot approve membership.

UI: **Workspace settings → Direct connections → One-hop helper relay** exposes
the opt-in checkbox, a helper selector for the sender's own updates, and a
**Send via helper** action per established relationship. The manual copy/import
path remains available when no helper is reachable.

Limits: helper relay is manual per update, requires both endpoints to share a
reachable helper, and does not create a route by itself; the signed DirectRecovery
document must still be valid. No physical multi-device helper test was performed.

## 9. Phase 5 — owner-offline admission grants

The current model has one owner authority device, so an admin cannot safely sign
a membership manifest without a new protocol. Phase 5 adds **pre-authorized
admission grants** rather than sharing or replacing the owner authority:

- The owner signs one `workspace_admission_grant` while online, bound to the
  workspace, start manifest, a selected active **admin** member/device (with its
  signed device card), a 32-byte nonce, expiry up to seven days, and at most five
  admissions.
- The selected admin must countersign a `workspace_admission_acceptance` bound to
  the exact grant digest. The first delegated manifest carries both documents so
  every member can verify the admin knowingly accepted the role.
- Each admission is a full `workspace_manifest_delegated` v2 snapshot, signed by
  the accepted admin. It retains the owner as owner and the owner authority
  device, and adds exactly one active member. Existing members, roles, devices,
  policies, retention, name, description, status, and authority are unchanged.
- A grant is used in a chain: use 1 extends the grant's start manifest; use N
  extends the prior delegated manifest with the same grant. `grant_use` never
  exceeds `max_admissions`; reuse from a different base or grant is rejected.
- The admin may admit any currently pending join request with a valid signed
  invitation; it cannot add an arbitrary device card or pre-designate a member.
- Older clients reject the v2 document and show an update-required state. They
  never silently ignore a delegated admission.
- A competing owner manifest, grant reuse from another base, or a non-admission
  change freezes the workspace under the existing fork rules; the owner resolves
  it. The owner remains final and can end the grant by publishing a v1 manifest.
- All members see the grant, acceptance, use index, and each delegated admission.

### Phase 5.1 — protocol primitives (implemented in 0.9.8)

Implemented and tested, with no service/UI admission path enabled yet:

- `workspace_admission_grant` and `workspace_admission_acceptance` canonical
  signed documents with exact-field parsing, admin device-card binding, nonce,
  expiry, and tamper/signature failure tests.
- `workspace_manifest_delegated` v2 full-snapshot creation and verification:
  owner/authority retention, grant/acceptance validation, admin signature,
  chained `grant_use`, one-new-member admission-only diff, and rejection of
  policy/role/removal/name/authority changes.
- `VerifiedWorkspaceManifest` carries delegated signer/grant/use metadata.
- The app does not expose grant creation, acceptance, admission, or v2 delivery
  until the Phase 5.2 service/UI increment.

### Phase 5.2 — service/UI (planned)

Grant issuance/acceptance storage and visibility, admin admission of pending
joins, v2 wire delivery, owner-return/fork handling, revocation/expiry, UI, and
physical qualification. Until 5.2 ships, owner-offline joins remain queued and
the UI states the limitation.

## 10. Phase 6 — workspace DM calls

Reuse the existing 1:1 call signaling and media path with workspace participant
authorization instead of Personal contact approval. Calls remain 1:1; group
calls are a separate deferred design.

## 11. Phase 7 — WebRTC workspace invitation

The current workspace invite dialog has a `webrtc` code branch but no selectable
option and no dedicated invitation transfer. Either finish it end to end
(create, transfer over the active DataChannel, join, approval, tests) or remove
the branch so it is not mistaken for a supported path.

## 12. Acceptance criteria

Phase 1:

- only active manifest members/devices appear;
- a local device is labeled local and never counted as reachable;
- known paths report `reachable` and a safe route label;
- recent receipts without a path report `recently_reached`, not `delivered`;
- queued work with no path reports `queued`;
- propagation storage reports `store_and_forward`, never delivered;
- failed/expired/cancelled with no path reports `unreachable`;
- no delivery evidence reports `unknown`;
- path request targets only active remote devices and is bounded by manifest
  destinations;
- no membership, trust, route, settings, or delivery state changes;
- service and renderer tests pass, including a network-less/unknown case.

Later phases require their own protocol review and physical multi-device gates.

Phase 2a:

- only the active owner authority device can create a recommendation;
- the document binds the workspace, current manifest digest, canonical profile,
  and expiry, and fails on tamper, wrong signer, stale manifest, expiry, or
  inactive membership;
- no profile is attached before explicit local consent;
- attachment uses workspace scope and does not create a contact, approve a
  device, change authority, or make the owner a relay;
- out-of-band import works without a member path;
- automatic delivery queues only to active member devices, skips the local
  authority device, uses per-device retry/expiry evidence, and preserves the same
  preview/consent boundary on receipt;
- no delivery or path result is treated as consent or membership.

Phase 3:

- default workspace reconnect consent is off;
- enabling creates only workspace-scoped profiles; no contact records exist
  before or after;
- `MESHWSR1` wrapper and inner capability are both signed by the same current
  active device, target this device, and carry an unexpired mailbox session;
- the recipient stores peer capabilities without changing its own consent;
- both sides must enable before the coordinator considers a profile ready;
- active membership/device authorization is rechecked before offer/answer use;
- mailbox absent, peer absent, removed workspace/device, or missing consent
  produces an explicit non-ready state rather than a connection;
- no membership, trust, authority, or read state changes.

Phase 4:

- helper relaying is off by default and requires explicit local consent;
- sender must own the exported connection update and select a current active
  helper that is neither the local nor the audience device;
- the first hop binds the wrapper origin to the native source and active
  manifest devices;
- a helper forwards to the audience only; a wrapper whose native source is not
  the origin stops after one hop;
- the recipient applies the original signed DirectRecovery document, never a
  helper-modified substitute;
- helper visibility is limited to connection endpoints/timing, not chat,
  history, receipts, authority, or keys.

## 13. Known limits

- Phase 1 is diagnostic and an explicit path request; it does not create an
  all-to-all topology.
- Path discovery can fail behind CGNAT, restrictive firewalls, or with no shared
  route; the UI must say so instead of retrying forever.
- Delivery evidence is per device and can be stale; it is not presence.
- Android background suspension still defers requests and delivery.
- No physical multi-member workspace matrix has been run.
