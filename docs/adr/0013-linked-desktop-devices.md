# ADR 0013: Linked desktop devices

Status: accepted for workspace protocol v1, increment 14.

## Decision

One workspace member may admit up to three desktop devices without creating a
second person or copying private identity material. Every desktop creates its
own RNS identity, destination and signed `workspace_device_card`. The current
manifest remains the source of effective membership: a link offer or
acceptance is inert until the owner authority publishes the one-card manifest
delta.

An active device of the member signs a 15-minute, single-use link offer. The
offer carries the immutable genesis, current manifest and bounded authority
certificate chain so a fresh installation can authenticate the workspace,
member and sponsor without a workspace invitation. The new desktop signs an
acceptance containing that exact offer and its fresh self-signed device card.
The two signatures are the countersignature proof; neither signature grants
effective access by itself.

The new desktop sends the acceptance to the current authority. Unknown-source
admission is limited to this exact document family: the native LXMF source,
inner acceptance signer and new device-card destination must match. The owner
reviews the request and signs a manifest containing exactly the additional
card. Decline, expiry, replay, a stale base or a different device delta leaves
the prior manifest effective.

## Canonical documents

The offer is canonical sorted-key NFC UTF-8 JSON:

```text
workspace_device_link_offer = {
  v=1, type="workspace_device_link_offer", workspace_id, link_id,
  base_manifest_epoch, base_manifest_digest,
  member_id, sponsor_device_id, sponsor_destination,
  genesis, offered_manifest, authority_chain, bootstrap_manifests,
  nonce, replay_key, created_at, expires_at, use_limit=1, signature
}
```

Text forms use `MESHWORKSPACEDEVICE1:` and
`meshchat://workspace-device/`. Decoded link and acceptance documents are
bounded at 320 KiB; their embedded bootstrap remains subject to the existing
256 KiB authority-chain bound. `bootstrap_manifests` contains at most 64
strictly epoch-ordered historical manifest checkpoints, always including epoch
one when the offer is newer. It excludes the separately embedded current
manifest. Input text is bounded before decoding and signature work.

The fresh device countersigns:

```text
workspace_device_link = {
  v=1, type="workspace_device_link", workspace_id, link_id,
  offer_digest, offer, device_card, replay_key, accepted_at, signature
}
```

Every repeated identifier and digest must equal the embedded offer. The device
card must name the offer's existing member, use that member's current display
name, contain a new UUID and destination, and validate with the acceptance
signer. Acceptance must occur inside the offer window.

A member removes a lost nonauthority endpoint with:

```text
workspace_device_removal = {
  v=1, type="workspace_device_removal", workspace_id, removal_id,
  base_manifest_epoch, base_manifest_digest, member_id,
  actor_device_id, target_device_id, replay_key,
  created_at, expires_at, signature
}
```

The actor and target must be distinct active devices of the same member and at
least one device must remain. The current authority device cannot be removed;
the owner must first complete the Increment 13 authority-rotation protocol.

## Manifest boundary

Legacy manifests remain byte-for-byte unchanged. A device-changing manifest
adds only:

```text
device_transition_digest = SHA-256(canonical acceptance or removal)
```

It is signed by the existing authority and advances exactly one epoch. The
device-transition verifier requires the exact predecessor and certificate and
allows exactly one appended card or one removed nonauthority card. Membership,
roles, statuses, authority, metadata, policy, retention, closure and removal
checkpoints must be identical. Ordinary and authority-transition verifiers
reject `device_transition_digest`; the device verifier rejects either
authority-transition field. A final manifest received before its certificate
is retained inert in the bounded pending-control queue.

Historical manifest parsing retains its prepared wider per-member device-array
bound. New enrollment is capped at three devices per member and 24 active
destinations per workspace. This preserves verification of historical bytes
without exposing a path around the Increment 14 product cap.

## Fan-out, recovery and removal

At event commit the sender freezes the complete recipient-device set from the
effective manifest, including the sender's other devices. Channels and DMs use
the same rule. One durable delivery leg exists per destination. Person-level
summary is derived from those legs and never hides a failed, expired or
cancelled device. Transport receipt remains delivery evidence, not a read
receipt.

Admission delivers the transition certificate, resulting manifest and the
smallest independently admissible suffix of every locally retained public or
member-authorized private channel-control chain. The offer binds the distinct
historical manifests those controls need. They remain inert on the fresh
endpoint until the authority's final device manifest endorses the exact offer;
same-epoch conflicts suspend the workspace. This preserves epoch-one
`#general` verification even when linking occurs much later without sending
unrelated predecessor controls. The endpoint then uses the existing bounded
signed history protocol to recover canonical events. It never imports another
device's private identity, drafts, local hides or unverified local state.

Removal cancels queued legs only for the removed destination and preserves the
other devices and person-level audit. Once a receiver knows the removal
manifest, native source admission and event verification both reject newly
seen traffic from that device. A partitioned peer may accept traffic until the
signed removal reaches it; no centralized revocation service is claimed. The
removed installation enters terminal `device_removed` state and may erase its
sealed local workspace data explicitly.

## Optional read hints

`workspace_read_hint` is opt-in per installation and signed by an admitted
device. It names the current manifest, same member/device, conversation, exact
head event and event digest. It is encrypted by ordinary LXMF delivery only to
the member's other admitted devices. A receiver applies it only when its own
canonical conversation head is that exact event; otherwise it ignores the
hint. Hints cannot infer positions across partial history, are not sent to
other members, create no chat item and never become social read receipts.

## Persistence, replay and compatibility

Link/removal documents, transition state and replay evidence are individually
sealed under HMAC-derived opaque vault IDs. At most 32 transitions are pending
per workspace and four from one source fingerprint. Exact duplicates are
idempotent. Reuse of a link/removal ID or replay key with different canonical
bytes is rejected; conflicting final manifests use the existing workspace-fork
rule.

Older peers ignore the new wire kinds and cannot validate a device-transition
manifest, so they fail closed for that workspace rather than weakening the
proof. Personal chats, groups and prior canonical event bytes are unchanged.
The beta remains desktop-only, at most eight people, three devices per person
and 24 active destinations.

## Rejected alternatives

Rejected designs include copying an identity or vault, treating several
desktops as one destination, admitting a card from a bearer link alone,
letting an administrator sign the final manifest, removing the authority key
without rotation, hiding failed device legs inside a delivered person summary,
and broadcasting read state as a social receipt. Each either expands key
compromise, weakens manifest authority or misstates delivery/privacy evidence.
