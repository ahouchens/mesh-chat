# ADR 0005: Workspace authority and bootstrap

Status: accepted for workspace protocol v1, increment 1.

## Decision

A workspace is rooted in an authority identity, not a hosted service. Its UUID
is derived from `SHA-256("mesh-chat:workspace:v1:" || creator_destination ||
nonce)` and is anchored by a canonical, authority-signed genesis document. A
hash-linked authority-signed manifest is the only source of membership and
workspace-policy authority. Increment 1 permits two active members, one device
per member, one authority device, and one public `#general` channel.

Every device presents an identity-signed card binding a workspace UUID, member
UUID, device UUID, normalized display name, complete RNS public identity,
derived LXMF destination, at most two validated route hints, and creation
time. A receiver re-derives the destination from the public identity before
using the card. Manifest members are sorted, device and member identifiers are
unique, and exactly one active owner and authority device are required.

Bootstrap uses a signed, single-use invitation containing the complete signed
genesis and offered manifest checkpoint. It expires after at most 30 days and
is encoded as either `meshchat://workspace/<base64url>` or
`MESHWORKSPACE1:<base64url>`. A joiner verifies the complete checkpoint before
signing a join document that embeds both its device card and the invitation.
The owner consumes the invitation and publishes the next manifest atomically;
receiving or approving a join never grants general direct-message trust.

Workspace traffic uses a new LXMF custom type, `mesh-chat-workspace`, and a
strict versioned metadata map. Dispatch selects this profile before any legacy
`mesh-chat` parser is called. The only unknown-source exception is a
`workspace_join`: the outer native source, embedded signed device card,
identity-derived destination, invitation signature, workspace binding, expiry,
and native LXMF signature must all agree. All other unknown-source workspace
traffic is discarded.

Manifest epochs are monotonic and hash-linked. Skipped controls are inert;
rollback is rejected; two different valid authority-signed manifests for the
same epoch suspend the workspace as a fork. A non-owner leave is a signed
request applied by an authority manifest. An owner closes a workspace with a
terminal manifest and cannot leave until a separately designed ownership
transfer exists.

## Bounds and compatibility

Canonical control documents are compact sorted-key UTF-8 JSON with exact field
sets, URL-safe base64 without padding, NFC-normalized presentation strings, and
domain-separated signatures. A control document is at most 16 KiB. Increment
1's two-member manifest fits this boundary, so chunked manifests are not
enabled; raising the member/device cap requires the size gate and chunked-root
design from the workspace specification.

The existing `mesh-chat` profile, invitation formats, conversation IDs, and
group documents are unchanged. Unsupported workspace versions fail closed for
that workspace without affecting Personal conversations.

## Consequences

The owner is a membership authority but not a message relay or online server.
Membership changes wait for that authority, and owner-key loss freezes safe
changes. Removal and closure are eventually learned during partitions and
cannot erase content already received by an authorized endpoint.

