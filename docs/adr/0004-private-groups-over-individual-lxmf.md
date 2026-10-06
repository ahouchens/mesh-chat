# ADR 0004: Build private groups over individual LXMF delivery

Status: accepted for small private groups; release verification pending.

Mesh Chat implements a group message as one logical application record fanned
out to each other active member through that member's normal individual
`lxmf.delivery` destination. Every copy retains native LXMF signing, native
Reticulum/LXMF encryption, the recipient-ratchet requirement, direct or
propagated delivery, and an independent application receipt. Reticulum remains
responsible for paths and transport, and LXMF remains responsible for message
serialization and delivery.

The app does not use `RNS.Destination.GROUP`. That primitive shares one
symmetric destination key and does not supply the invitation, consent,
membership, rekeying, removal, conflict, history, or per-recipient receipt
semantics required here. Mesh Chat also does not add a group cipher, sender-key
scheme, custom routing envelope, central group server, or owner message relay.
Pairwise fan-out costs one encrypted transfer per recipient, but it preserves
the project's existing and reviewed trust boundary.

## Membership authority

Each group has a permanent identifier derived from the owner's delivery
destination and a fresh 32-byte random nonce, anchored by an owner-signed
genesis document. The owner is a membership authority, not a server: members
can continue chatting while the owner is offline, but membership changes wait
for the owner. A canonical owner-signed manifest contains the group title,
posting policy, active or closed status, member identity cards and roles, a monotonically
increasing epoch, and the previous manifest hash.

An invitation is targeted, bounded, expiring, and delivered to an approved
contact. Joining requires a separate identity-signed acceptance bound to the
group, owner, invitation nonce, and offered manifest. An accepted member becomes
active only in a later owner-signed manifest. A group invitation does not grant
general direct-message trust, and a contact approval does not silently grant
group membership.

A non-owner leaves by signing a request bound to the exact current manifest;
the owner applies it with the next manifest. The owner can close the group with
a terminal signed `closed` manifest. Both operations converge like other
membership changes and do not erase already delivered content.

Receivers reject invalid signatures, an unknown group or sender, unauthorized
posting, a member not active in the referenced epoch, a stale or skipped epoch,
a broken previous-manifest link, replayed controls, and conflicting manifests.
Two valid owner-signed manifests for the same epoch are evidence of owner
equivocation; the group is suspended for explicit recovery instead of choosing
one silently.

## Privacy and removal

New members receive no earlier messages by default. A removed member receives
no copies addressed under later epochs, and messages that member sends under an
old epoch are rejected after the new manifest is learned. Removal cannot erase
plaintext or ciphertext already delivered to an authorized member.

In a partitioned, serverless network, removal is necessarily eventual. A member
that has not yet received the new manifest can temporarily operate under its
last valid epoch. The UI must distinguish a locally signed membership change
from a change acknowledged by the remaining endpoints and must not claim
instantaneous global revocation.

## Channels, scale, and delivery evidence

A private group uses the `members` posting policy. A private announcement
channel uses the same protocol with the `owner_admins` policy. The policy is
signed inside every manifest and enforced by every receiving endpoint; it is
not merely a UI permission. Version 0.2.0 has no role-assignment command, so
the announcement-channel interface is owner-only. The signed admin role is
reserved for a later, separately reviewed membership-management change.

The protocol and first user interface reject more than eight people including
the creator while fan-out, retry, route rotation, mobile lifecycle, and
low-bandwidth behavior are measured. Larger or public channels, discoverable
membership, anonymous membership, and a globally
ordered timeline are not part of this decision.

A group message has one logical identifier and a durable child delivery for
each other active member. The logical message and complete recipient set are
committed before the first LXMF handoff. Delivery is reported per recipient and
aggregated honestly, such as `Delivered to 5 of 7`, `2 pending`, or `Partially
delivered`. One endpoint receipt never means that everyone received the
message.

The owner is not a sequencer. Each sender supplies a monotonic sequence number,
which lets receivers detect one sequence being reused for a different message
without rejecting legitimate out-of-order arrival. Clients display an
approximate timestamp order. Concurrent or delayed messages may appear in
different orders on different devices.

## Consequences

- Security properties remain those of individual ratchet-enforced LXMF copies;
  propagation nodes store recipient-encrypted objects and are not group
  plaintext authorities.
- Work, bandwidth, stored delivery state, and receipts grow linearly with the
  number of recipients. This is an intentional small-group tradeoff.
- Traffic timing and fan-out volume can reveal that several encrypted transfers
  are related, and may approximate group activity or size.
- Owner loss freezes safe membership changes. Owner transfer would require a
  valid current-owner control; transfer, automatic election, and multi-writer
  membership are deferred.
- Selective history sharing, message edits, remote deletion, attachments,
  public channels, and a sender-key or MLS optimization require separate
  decisions and threat-model review.

An audited group-key protocol may be evaluated later if measured scale requires
it. It must not be approximated with a home-grown shared-key design or raw
`RNS.Destination.GROUP` usage.
