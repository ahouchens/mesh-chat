# Mesh Chat protocol profile

## Workspace join application receipt

`workspace_join_receipt` is an additive workspace LXMF control kind. Existing
v1–v4 invitation, join, manifest and connection-reply schemas remain unchanged.
Old peers reject the unknown control but retain their existing admission flow.
A new joiner with an old owner remains at unconfirmed/endpoint evidence until
the admitting manifest; native proof alone never means approval is pending.

The receipt is canonical sorted compact JSON, at most 2048 UTF-8 bytes, with
exact fields: `v` (integer 1), `type` (`workspace_join_receipt`), `workspace_id`,
`join_digest` (SHA-256 of the complete canonical signed join), `join_attempt_id`
(original durable delivery UUID), `audience_device_id`, `audience_destination`,
`authority_device_id`, `received_at`, `expires_at`, and `signature`. The authority
from the verified invitation signs the canonical object without `signature`
using the existing RNS signing primitive and URL-safe base64 encoding. No keys,
endpoints, approval or admitting manifest are included.

The joiner checks the native source and all fields against its saved join, then
verifies the signature with the invitation authority key. Expiry must equal the
invitation expiry; received time must be in the join/invitation window and use
the existing workspace timestamp tolerance (at most 24 hours ahead). A slightly
slower owner clock records at least the signed join's creation time. Previously verified evidence remains
durable. It grants neither membership nor a human read receipt.

Owner validation commits the request, one receipt delivery and due index
atomically. Duplicates cannot create additional requests or change the accepted
attempt UUID. After endpoint proof, a duplicate may requeue the same receipt at
most once per 30 seconds within its original deadline. The joiner retries its
same signed request under existing backoff until receipt, admission or expiry.
Unsent receipts are cancelled when the request/invitation becomes inactive.
Join delivery ends at the earlier of its seven-day window and invitation expiry.

The direct underlay design and hard limits are in
[ADR 0018](docs/adr/0018-authenticated-direct-underlay.md). The separately versioned
Phase 2 email exchange below uses `mesh-direct:` without changing these receipts.

## Compact QR transport v1

`MESHQR1:<base64url>` is a camera transport, not a new invitation or trust
protocol. The payload is the zlib/DEFLATE representation of one complete
canonical Mesh Chat invitation, workspace invitation, device link, connection
response, or route update. Base64url is emitted without padding. Decoding must
recover a recognized Mesh Chat document and then pass those signed bytes to the
existing family-specific parser and signature checks; decompression does not
approve an identity, contact, device, route, or workspace member.

The renderer emits a compact transport only when the ordinary signed document
would be too dense for a reliably scannable single QR. Short documents remain
raw for compatibility with older clients. Emitted `MESHQR1` values are at most
2,800 UTF-8 bytes, leaving headroom below a version-40 level-L QR's capacity.
Compressed input is syntax-bounded and decompressed output is capped at the
700 KiB native-ingress ceiling before the narrower personal, workspace,
device-link, response, or route limit is applied. Invalid base64url, malformed
DEFLATE, invalid UTF-8, unknown document families, and excess output fail
closed. This transport changes neither signed bytes nor invitation expiry,
single-use, revocation, authority, or replay semantics.

## Participant-hosted invitation envelopes v3

Version 3 is additive. `MESHCHAT3` and `MESHWORKSPACE3` carry a canonical `participant_invitation` envelope around the complete existing v1 invitation. The outer signature is made by the personal inviter or current workspace authority and binds every field below:

| Field | Meaning |
| --- | --- |
| `v`, `type`, `purpose` | Exact values `3`, `participant_invitation`, and `personal` or `workspace` |
| `inner`, `inner_digest` | Complete verified v1 string and SHA-256 of its exact UTF-8 bytes |
| `access` | Exact participant-access document described below |
| `created_at`, `expires_at` | Outer dates; expiry cannot exceed the inner invitation or access credential |
| `signer_destination` | Inviter/authority LXMF destination, cross-checked with both inner documents |
| `signature` | URL-safe base64 signature over all preceding canonical fields |

The exact participant-access document has version `1`, mode `participant_direct`, a content-derived SHA-256 `id`, the same `operator_destination`, one to three public `{host, port, path}` endpoints, fresh IFAC `network_name` and `passphrase` tokens, and creation/expiry times. `path` is one of `public_ipv4`, `public_ipv6`, `upnp`, `nat_pmp`, `pcp`, or `manual`. Maximum access lifetime is 24 hours; an automatic mapping or IPv6 firewall pinhole shortens the effective outer/workspace invitation expiry to the lease less a cleanup margin. Endpoints pass the same public-address validation used by imported remote profiles. Private, shared (`100.64.0.0/10`), loopback, link-local, multicast, unspecified, reserved, documentation, and benchmarking addresses fail closed.

The access credential authorizes only attachment to the inviter's temporary Reticulum interface; it is not a Mesh Chat identity, contact approval, workspace membership grant, transport-role grant, or message key. The envelope cross-binding prevents substituting another listener, operator, personal identity, or workspace authority. Unknown/extra fields, invalid types, noncanonical token encodings, duplicate endpoints, excessive size/lifetime, digest mismatch, expiry, identity mismatch, or signature failure are rejected before any socket is opened.

Preview is local and side-effect free. Accepting a verified v3 personal invitation stores the access document under the resulting contact scope before attaching outbound clients; workspace acceptance uses only the pending/workspace scope and never creates a Personal contact. No separate third-party-operator consent checkbox appears because the signed operator is the inviter already shown in the approval UI. Connection is still an explicit consequence of accepting the invitation. Candidate probes produce only indexed `connected`, `refused`, `timed_out`, `no_ipv6_route`, or `unresolved` presentation results; raw addresses and socket errors remain service-private. A TCP candidate result is troubleshooting evidence, while the host becomes recipient-verified only after its invitation-authenticated interface accepts the client.

Text forms use `MESHCHAT3:` or `MESHWORKSPACE3:` plus canonical URL-safe base64. Links retain `meshchat://invite/` and `meshchat://workspace/`; raw files contain the exact canonical envelope and may use `.meshchat-invite` (legacy `.meshchat` remains accepted). Personal v3 payloads are bounded to 32 KiB and workspace v3 payloads to the authority-bootstrap bound plus 8 KiB. Desktop and Android native ingress exact-parse the supported v1/v2/v3 families before renderer handoff.

v3 changes only reachability bootstrap. Automatic hosting reads selected default routes, starts the actual listener before creating the mapping, and prefers PCP, UPnP IGD, then NAT-PMP. Manual hosting reuses the same signed v3 structure and listener credential; `path: "manual"` does not carry router credentials or cleanup authority. After attachment, normal Reticulum paths, LXMF recipient ratchets, signed contact/workspace controls, replay protection, outbox behavior, and application receipts remain authoritative. A participant listener is not configured as a Reticulum transport instance or propagation node and does not route unrelated users.

## Email-ready invitation envelopes v4

Version 4 is additive. `MESHCHAT4` and `MESHWORKSPACE4` use the existing `meshchat://invite/` and `meshchat://workspace/` deep-link hosts and carry one canonical `email_invitation` document. The document wraps the complete canonical v1 invitation; it does not wrap v2 or v3 and does not change any v1 field or signature.

| Field | Required meaning |
| --- | --- |
| `v`, `type`, `purpose` | Exact values `4`, `email_invitation`, and `personal` or `workspace` |
| `inner` | Complete canonical, independently verified v1 invitation string |
| `inner_digest` | Lowercase SHA-256 of the exact UTF-8 `inner` bytes |
| `inviter_access` | `null` or a complete `participant_direct` access document owned by the v1 inviter/current workspace authority |
| `reply_challenge` | Base64url encoding of 32 random bytes |
| `created_at`, `expires_at` | Integer dates; expiry cannot exceed the inner invitation or optional access credential |
| `signer_destination` | Destination re-derived from the inner personal identity or current workspace authority |
| `signature` | That signer's signature over all preceding canonical fields |

Unknown fields, wrong types, non-canonical inner bytes, digest/challenge/signature mismatch, destination/authority mismatch, invalid access ownership, excessive size/nesting, and invalid or expired dates fail closed. Personal v4 input remains bounded by the personal participant-invitation limit; workspace v4 input remains bounded by the workspace participant-invitation limit. Preview is side-effect free. Acceptance is outbound-first: when `inviter_access` exists, the invitee persists it before attaching authenticated outbound TCP clients; without it, the invitee may still request an already-known Reticulum path. The invitee authors and durably queues the unchanged signed contact request or workspace join in either case. Creating a callback listener is an explicit role-reversal fallback, not a prerequisite for authoring the application request and not an automatic side effect of preview.

### Connection response v1

`MESHCONNECT1`, `meshchat://connect/<base64url>`, raw JSON, and `.meshchat-connect` carry a canonical `connection_response` document of at most 40 KiB:

| Field | Required meaning |
| --- | --- |
| `v`, `type`, `purpose` | Exact values `1`, `connection_response`, and the original `personal` or `workspace` purpose |
| `invitation_digest`, `reply_challenge`, `signer_destination` | Exact bindings copied from one still-active locally stored v4 invitation |
| `responder_public_identity`, `responder_destination` | Complete responder public identity and its re-derived Reticulum destination |
| `access` | Complete `participant_callback` access document owned by the responder destination |
| `created_at`, `expires_at` | Bounded dates no later than the original invitation or listener/mapping lease |
| `signature` | Responder signature over all preceding canonical fields |

The inviter must possess the original v4 record it created. Import atomically marks that record consumed and persists a `pending_invitation` route scope before any DNS, probe, or interface activation. A second import is rejected. The inviter then attaches an outbound authenticated TCP client to the responder-owned callback. Transport direction does not change application authorship: the invitee/responder authors and sends the unchanged signed contact request or workspace join over the resulting full-duplex Reticulum path; the workspace owner does not author the join. The response proves control of a callback listener and responder identity only: it never creates a Contact, verifies an identity, admits a workspace device, or changes a workspace manifest. The invitee-authored request and existing approval path remain authoritative.

An invitation with no `inviter_access` contains an identity and destination but no Internet socket endpoint. If neither participant can accept inbound traffic and no already-known nearby path or explicitly approved shared access point exists, neither outbound client has an endpoint to dial. Connection-response exchange alone cannot solve that dual-NAT topology because this protocol defines no rendezvous, simultaneous-open coordination, STUN/TURN service, or implicit relay.

### Scoped route update v1

`MESHROUTE1`, `meshchat://route/<base64url>`, raw JSON, and `.meshchat-route` carry a canonical `route_update` document of at most 24 KiB. It binds exact `scope_kind` (`contact` or `workspace_device`), `scope_id`, local `audience_destination`, issuer public identity and re-derived destination, positive 63-bit monotonic `generation`, one issuer-owned `participant_callback` access document, dates, and issuer signature.

An update is applicable only when the issuer is already the approved contact or an active admitted device in that exact workspace scope, the audience is this local identity, and the generation exceeds the last accepted generation for that issuer/scope. Application atomically stores the accepted generation and replacement scoped route before network activation. Unknown, cross-scope, stale, replayed, expired, removed-member, or identity-mismatched updates fail closed. Route updates never change verification, blocking, membership, authority, ratchets, message bytes, or receipts.

While an authenticated path remains usable, the issuer sends the same signed route-update document as the bounded `route_update` LXMF application-control kind before the callback access expires. The receiver still performs the complete portable-document verification and additionally binds the native source and pairwise conversation ID. If every path is unavailable, the document is shared out of band. On refresh or restart, automatic router mapping requests the previously assigned external port when available, but the new access document advertises only the port the router actually restored after the listener is active.

All v4/reply/route JSON documents use exact field sets, canonical UTF-8 JSON for signatures, a maximum nesting depth of six, and at most 192 parsed nodes. Native desktop and Android ingress apply family byte bounds and structural filtering before the Python verifier. Reticulum remains the routing/security layer; the added documents only distribute signed temporary interface credentials.

## Remote invitation envelopes v2

Version 2 is additive. Existing `MESHCHAT1` and `MESHWORKSPACE1` encodings and their canonical bytes are unchanged. v2 is emitted only after explicit per-invitation selection of an approved operator access point; merely configuring a profile does not override the direct-first v3 default. Remote-ready text, file, QR, and deep-link entry points carry one signed v2 outer envelope around the complete verified v1 string.

The canonical connection profile is versioned and exact-field parsed. It contains a normalized label, one or two bounded TCP endpoint objects, an optional 16-byte LXMF propagation destination, creation and expiry times with no more than a 90-day lifetime, and a bounded capability list. Its stable identifier is the SHA-256 digest of the canonical profile bytes. Runtime origin, consent, scopes, connection state, and retry state are protected local records and are not part of the portable profile identifier.

The `MESHCHAT2` and `MESHWORKSPACE2` canonical outer document binds the wrapper version and purpose, complete inner-v1 bytes, SHA-256 digest of those exact bytes, complete canonical profile, wrapper creation and expiry times, signer destination, and signature. The personal signer must equal the identity/destination verified inside the personal v1 invitation. The workspace signer must equal the current workspace authority verified by the inner invitation and authority proof. Any unknown or extra field, wrong type, excessive size/nesting, invalid date, digest mismatch, signer mismatch, identity/destination mismatch, or invalid signature fails closed before preview.

Native ingress applies outer bounds before handing data to the service: personal invitation payloads are at most 32 KiB, workspace invitation payloads are at most 600 KiB, and Android durable launch ingress is at most 700 KiB. The service then applies the narrower field, profile, invitation, and protocol limits. Desktop and Android accept the same text/file/deep-link forms and invoke the same service parser.

Preview is a pure verification operation. It cannot resolve DNS, attach an interface, request a path, or approve propagation. Approval stores a contact, workspace, or pending-invitation scope before interface activation. Workspace scope never creates a Personal contact. Existing invitation nonce consumption, revocation, expiry, replay, identity-change, owner review, manifest, membership, and per-device checks remain authoritative after unwrapping.

Imported endpoints must be public. Literal and resolved loopback, private, link-local, multicast, unspecified, reserved, documentation, and benchmarking addresses are rejected, as are local-only hostname suffixes. Before every attempt all DNS answers are revalidated; one unsafe answer rejects the entire endpoint, and only a validated numeric address is passed to Reticulum. Private endpoints exist only in an explicit advanced manual profile and are never authorized by imported invitation content.

Route selection does not change message bytes. Nearby and signed direct routes retain preference over a shared remote interface. Direct and propagated LXMF packing require the recipient ratchet; no v2 code permits base-key encryption. TCP connection, Reticulum path, ratchet, optional propagation storage, LXMF endpoint delivery, and authenticated Mesh Chat application receipt are distinct states.

Mesh Chat keeps the LXMF wire format, `lxmf.delivery` destination name, standard Content field, native source signature, and native encryption. It adds signed contact and group-control documents, a small LXMF custom-field map, and local IPC.

## Workspace access recommendation v1

A workspace access recommendation is an out-of-band, authority-signed document
prefixed `MESHACCESS1:` and encoded as unpadded base64url of canonical JSON. It
is not an invitation, membership grant, or workspace wire message.

Exact fields:

- `v` = `1`, `type` = `workspace_access_recommendation`;
- `workspace_id`: canonical workspace UUID;
- `manifest_digest`: 64 lowercase hex characters for the exact current manifest;
- `profile`: the complete canonical Remote Connection Profile object;
- `created_at`, `expires_at`: integer Unix seconds; lifetime is 1-30 days and
  never exceeds the profile expiry;
- `signer_public_key`: base64url RNS public key;
- `signature`: base64url signature over canonical JSON of every field except
  `signature`.

The verifier rejects unknown/extra fields, wrong version/type, invalid UUID or
digest, malformed or expired profile, future creation time, invalid lifetime,
invalid signature, or a signer that is not the current workspace authority. The
service additionally requires the local workspace to be active, the manifest
digest to equal the current local manifest, the signer destination to equal the
current authority destination, and the local member to be active.

Preview is network-free and returns a safe profile disclosure, never raw
endpoints. Import requires an explicit consent boolean and attaches the profile
with workspace scope; it does not create a contact, approve a device, change
membership or authority, enable Reticulum transport, or make the owner a relay.
A stale recommendation must be regenerated by the current owner authority.

The same document may be carried as a workspace control payload with wire kind
`workspace_access_recommendation` and queued once per active member device,
excluding the local authority device. The wire envelope is not an additional
grant: the receiver verifies the `MESHACCESS1` bytes, stores only the signed
document and safe summary, and still requires preview plus explicit consent
before attachment. Delivery retries and evidence remain per device; a delivery
result is not consent, membership, or a read receipt.

## Workspace reconnect capability v1

Workspace automatic reconnect is opt-in and does not create a Personal contact.
A `MESHWSR1:` wrapper carries an ordinary signed `connection_capabilities`
document plus the exact workspace binding. Fields:

- `v` = `1`, `type` = `workspace_reconnect_capability`;
- `workspace_id`: canonical workspace UUID;
- `manifest_digest`: 64 lowercase hex characters at issuance;
- `capability`: the exact signed `connection_capabilities` JSON string;
- `issued_at`, `expires_at`: integer Unix seconds, equal to the inner
  capability expiry;
- `signer_public_key`, `signature`: base64url RNS key and signature over
  canonical JSON without `signature`.

The verifier rejects wrong version/type/fields, invalid UUID/digest, malformed
or expired inner capability, expiry mismatch, bad signature, or a wrapper signer
different from the inner capability signer. The service additionally requires
the workspace to be active, the source device to be an active manifest device,
the inner `peer_destination` to be this device, and the source to be a different
device from the local one. Receipt stores the peer capability only; it never
changes local consent, membership, authority, or trust.

The wrapper is delivered as workspace control kind
`workspace_reconnect_capability` to each active peer device when the user enables
the workspace toggle. Both sides must enable and have a usable mailbox session
before the renderer coordinator starts. Profiles are keyed by
`workspace:<workspace>:<member>:<device>` and are revalidated against the current
manifest before request, offer, answer, and path actions. Removing the member,
device, or workspace makes the profile non-ready; it does not create a contact
or grant access.

## Workspace connection relay v1

A workspace member may opt in to relay one already-signed DirectRecovery
connection update between two active devices. The relay payload is workspace
control kind `workspace_connection_relay` with canonical JSON fields:

- `v` = `1`, `type` = `workspace_connection_relay`;
- `workspace_id`: canonical workspace UUID;
- `origin_device_id`, `audience_device_id`: active workspace device IDs;
- `document`: one exact `mesh-recover:` signed connection update, at most 16 KiB.

The sender must own the relationship/update and select an active helper that is
neither the local nor the audience device. The first hop requires the native
LXMF source to equal the origin device destination and both IDs to be current
active devices. If this device is the audience, it applies the original document
through DirectRecovery; otherwise it forwards the wrapper only when local helper
consent is enabled. A second helper sees a native source different from the
origin and ignores the wrapper, bounding delivery to one hop.

The helper never changes the signed document or supplies authority; the
recipient verifies signature, workspace scope, audience, expiry, and replay on
the original document. The helper can observe connection endpoints and timing
inside its own encrypted delivery, not chat, history, receipts, private keys, or
membership. Relaying is off by default and is a manual per-update action.

## Workspace admission grants v1 and delegated manifest v2

Phase 5 adds owner-offline admission without sharing the owner authority key.

`workspace_admission_grant` fields:

- `v` = `1`, `type` = `workspace_admission_grant`;
- `workspace_id`, `start_manifest_hash`;
- `admin_member_id`, `admin_device_id`, `admin_destination`, and the exact
  signed `admin_device_card`;
- `max_admissions` (1-5), `issued_at`, `expires_at` (at most seven days), and a
  32-byte `nonce`;
- `signer_public_key`, `signature` by the owner authority.

`workspace_admission_acceptance` binds the exact grant digest, workspace, admin
destination, acceptance time, admin public key, and signature. The admin device
must match the grant's card/destination.

A delegated admission is a full `workspace_manifest_delegated` v2 snapshot
carrying all v1-equivalent manifest fields plus `grant`, `grant_acceptance`,
`grant_use` (1-5), and `delegated_signer_destination`. The owner and authority
device remain unchanged; the admin signature is verified against the accepted
grant's admin card. Use 1 must extend the grant's start manifest; use N must
extend the prior delegated manifest with the same grant, and may not exceed
`max_admissions`. The only permitted change is exactly one new active non-owner
member; existing members/devices/roles/status and name, description, policies,
retention, and authority must be identical.

Pre-v2 clients reject the unknown document and expose an update-required state;
they do not ignore the admission silently. A competing owner manifest, grant
reuse from another base, or any non-admission change triggers the existing fork
freeze. The owner remains final and ends delegation by publishing a v1 manifest.

Workspace call signaling uses the existing signed call document as workspace
control kind workspace_call_signal, addressed to one active workspace device.
The call manager accepts the synthetic workspace peer only while the
workspace and both devices are active. No Personal contact is created.

0.9.8 implements these protocol primitives and verifiers only. Grant creation,
acceptance, v2 delivery, and admin admission UI are enabled in the Phase 5.2
service/UI increment.

An owner-return/revocation manifest is a v1 manifest with `delegation_end: true`
and no membership, policy, name, description, or retention change. It may extend
a delegated v2 head or a normal v1 head; publishing it invalidates the grant's
start hash and ends any grant chain at that head. It returns the workspace to a
normal owner-signed v1 head.

## Invitation v1

All entry points carry the same canonical UTF-8 JSON object:

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | integer | Exactly `1` |
| `label` | string | Claimed display label, 1–64 normalized characters |
| `public_identity` | base64url | Complete 64-byte RNS public identity |
| `destination` | lowercase hex | Derived `lxmf.delivery` destination hash |
| `created_at` / `expires_at` | integer | Bounded invitation validity |
| `hints` | array | At most eight validated public TCP host/port hints |
| `signature` | base64url | RNS identity signature over canonical JSON without this field |

The app accepts `meshchat://invite/<base64url>`, `MESHCHAT1:<base64url>`, or the raw JSON invitation file. The decoded input is capped at 16 KiB. Unknown fields, schemes, hint types, unsafe hosts, invalid dates, invalid signatures, and destination-binding mismatches are rejected before network configuration changes.

Network admission secrets are never invitation fields.

## LXMF application metadata v1

Text remains in LXMF Content. Mesh Chat uses upstream-reserved `FIELD_CUSTOM_TYPE` (`0xFB`) with `b"mesh-chat"` and `FIELD_CUSTOM_META` (`0xFD`) with this compact integer-key map:

| Key | Value |
| --- | --- |
| `1` | schema version `1` |
| `2` | `chat`, `reaction`, `receipt`, `contact_request`, `contact_accept`, `contact_decline`, `route_update`, `group_invite`, `group_accept`, `group_manifest`, `group_chat`, `group_reaction`, `group_receipt`, or `group_leave_request` |
| `3` | random 16-byte logical delivery UUID |
| `4` | deterministic 16-byte pairwise conversation UUID |
| `5` | authenticated application expiry timestamp |
| `6` | optional 16-byte receipt reference |
| `7` | signed invitation JSON, only for a contact request |
| `8` | group UUID, only for a group payload |
| `9` | nonnegative membership epoch, only for a group payload |
| `10` | 32-byte SHA-256 digest of the referenced group manifest |
| `11` | nonnegative per-sender sequence, only for `group_chat` |
| `12` | canonical signed JSON group document, only for group control kinds |
| `13` | common 16-byte group-operation UUID, required for `group_chat`, `group_reaction`, and `group_receipt` |
| `14` | 16-byte target chat-message UUID, only for `reaction` and `group_reaction` |
| `15` | one exact fully-qualified Unicode Emoji 18.0 sequence, at most 16 Unicode code points and 64 UTF-8 bytes |
| `16` | Boolean active state: `true` applies or replaces the actor's reaction; `false` is its tombstone |
| `17` | positive, monotonically increasing per-actor/per-target reaction revision |
| `18` | canonical signed route-update document, at most 24 KiB and only for `route_update` |

The conversation ID is the first 16 bytes of SHA-256 over a versioned domain separator and the two sorted LXMF delivery hashes. It is not a human or network address.

Messages are accepted only after native signature validation, exact local destination matching, schema validation, conversation re-derivation, expiry validation, and trust-policy checks. A one-to-one source must bind to an approved contact; an unknown source may create only a bounded pending contact request carrying a signed invitation and cannot enter a direct chat or trigger a receipt. A route update may also bind to an active admitted workspace device without creating a Personal contact. A group source must instead bind to an active identity card in the verified manifest for that group and epoch. Group-scoped authorization does not create an approved direct contact.

Group fields are additive to payload version 1; existing one-to-one payloads and
conversation IDs do not change. Group metadata on a non-group kind, a group
field on the wrong group kind, unknown metadata, a malformed UUID or manifest
digest, a negative or oversized integer, a group control document over 16 KiB,
text on a control message, or an empty group chat is rejected.

## Message reactions

Reactions are an additive extension of payload version 1. A direct `reaction`
has ordinary pairwise conversation metadata plus keys `14` through `17`. A
`group_reaction` additionally binds the current group UUID, membership epoch,
and manifest digest. Its key `13` is the common reaction-operation UUID shared
by that operation's separately addressed recipient copies; key `14` names the
group chat message being reacted to. Reaction payload Content is empty, and
receipt references, reaction fields on other kinds, unsupported emoji, zero or
oversized revisions, and malformed target UUIDs fail validation.

Reaction emoji are matched byte-for-byte against the 3,963 fully-qualified
sequences in the pinned Unicode Emoji 18.0 `emoji-test.txt` data. Mesh Chat
does not normalize or repair input: component-only, minimally-qualified,
unqualified, text-presentation, adjacent-emoji, malformed selector/modifier,
invented joiner, and invented tag sequences are rejected. The independent
16-codepoint and 64-byte limits are checked before catalog membership. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the data provenance and
license.

Each destination identity has at most one reaction state for a given message.
Applying a different emoji replaces that actor's earlier choice. Applying the
same emoji again removes it by publishing `active: false`; this tombstone and
its revision remain durable so delayed packets cannot restore an older state.
Only a strictly newer revision changes visible state. Duplicate or older
revisions are idempotently ignored and may still be acknowledged.

The actor is always the natively authenticated LXMF source destination, never
a value supplied by application metadata. A direct reaction is accepted only
from the approved or verified contact for the target message's re-derived
pairwise conversation. A group reaction requires the actor to be an active
member of the current manifest and to have belonged to the signed historical
manifest under which the target message was sent. Recipient fan-out is likewise
the intersection of current active membership and that historical audience.
Consequently, a later member cannot infer or react to an earlier message, and
a removed member cannot mutate it. The posting policy governs `group_chat`, not
reactions: active readers in an `owner_admins` announcement channel may react.

A valid reaction may overtake its target message. The receiver stores it as an
encrypted pending record and applies it atomically when the target commits.
Pending work is bounded to 256 records in total and 32 per authenticated actor,
expires with the reaction delivery window plus a 24-hour replay grace, and is
discarded when group epoch, manifest, active membership, or target audience no
longer match. Locally deleted targets have opaque durable discard markers;
late reactions are acknowledged where appropriate but cannot recreate the
message or its reaction state.

Local reaction state and its durable direct or per-recipient group outbox are
committed together before LXMF handoff. A newer local revision atomically
supersedes older reaction-only outbox work for that target, with native
cancellation attempted only after the vault mutation commits. Reaction jobs
and reaction receipts are removed after authenticated endpoint receipt (or an
application receipt), rather than retained as chat history. This also provides
safe compatibility with older payload-v1 peers: they can reject an unknown
reaction kind without affecting ordinary chat, while endpoint evidence stops
the sender from retrying the optional mutation for the full seven-day window.

## Private group profile

Mesh Chat sends a group message as separate native LXMF messages addressed to
the individual `lxmf.delivery` destination of every other active member. It
does not use `RNS.Destination.GROUP`, a shared group key, a custom cipher, or an
owner/server relay. Each recipient copy has its own logical delivery UUID in
key `3`; all copies share the group-message UUID in key `13`. This permits
deduplication and retry of one recipient without falsely merging another
recipient's delivery state.

A group has a permanent UUID derived as the first 16 bytes of
`SHA-256("mesh-chat:group:v1:" || owner_destination || nonce)`, where `nonce`
is 32 random bytes. Its owner-signed genesis anchors that nonce and owner. The
current state is an owner-signed canonical manifest with:

- the group UUID, owner identity and creation nonce;
- a normalized title, `active` or `closed` status, and the `members` or
  `owner_admins` posting policy;
- at most eight member identity cards and roles;
- a monotonically increasing epoch and the previous manifest digest; and
- an owner signature covering the complete canonical document without its
  signature member.

Group documents are UTF-8 JSON serialized with sorted keys, compact separators,
and no unknown fields. Each has `v: 1`, a `type`, and a base64url RNS signature
over every other field in the canonical object. The signed document types are:

| Type | Signed body |
| --- | --- |
| `group_member_card` | `group_id`, normalized `display_name`, complete `public_identity`, derived `destination`, zero to two validated TCP `hints`, `created_at` |
| `group_genesis` | `group_id`, 32-byte `nonce`, normalized `title`, `posting_policy`, signed `owner_card`, `created_at` |
| `group_manifest` | `group_id`, `epoch`, `previous_manifest_hash`, normalized `title`, `posting_policy`, `status`, `owner_destination`, sorted `members`, `created_at` |
| `group_invite` | `group_id`, `group_epoch`, `manifest_hash`, owner public identity and destination, targeted `invitee_destination`, embedded signed `genesis` and current `manifest`, 32-byte `nonce`, `created_at`, `expires_at` |
| `group_join` | `group_id`, `group_epoch`, `manifest_hash`, `invite_nonce`, signed `member_card`, `created_at` |
| `group_leave_request` | `group_id`, `group_epoch`, `manifest_hash`, signed `member_card`, matching `leaver_destination`, `created_at` |

Manifest entries contain a signed member card and exactly one of `owner`,
`admin`, or `member`. They are sorted by destination, contain no duplicate
destination, and contain exactly one owner whose destination matches the
manifest signer. Posting policy is exactly `members` or `owner_admins`; status
is exactly `active` or `closed`. Version 0.2.0 does not expose role assignment,
so an `owner_admins` channel is owner-only in its current user interface; the
signed `admin` role is reserved for a later role-management design.

Identity cards bind each member's complete RNS public identity to the derived
LXMF delivery destination. A receiver re-derives this binding and validates all
document signatures before changing durable group state.

`group_invite` is targeted to an approved contact and binds an invitation
nonce, expiry, group, owner, and offered manifest. `group_accept` contains the
invitee's identity-signed acceptance of those values. Acceptance is consent,
not membership by itself: the owner must publish a later `group_manifest` that
includes the member. A non-owner may send a member-signed
`group_leave_request` bound to the exact current manifest. It takes effect only
when the owner publishes the next manifest without that member. The owner
cannot leave without a separately designed ownership-transfer protocol.
The invitation verifier validates the embedded genesis and manifest, re-derives
their group and owner binding, matches the top-level epoch and digest, and for
epoch 1 requires the manifest's predecessor to be the genesis digest.

Manifest epochs form a single hash-linked chain. A receiver applies only the
expected next owner-signed epoch with the current digest as its predecessor.
A valid future epoch received before its predecessor is held inert until the
missing signed chain arrives; it cannot authorize messages while pending.
Rollback and invalid signatures fail closed. Two different valid
owner-signed manifests for the same group and epoch suspend group processing as
owner equivocation instead of selecting a branch silently, including when the
conflicting epoch is older than the receiver's current epoch.

An owner closes a group with the next manifest set to `closed`. A closed
manifest rejects posting, new invitations, joins, leave requests, and all later
manifest transitions. Closing converges like any other epoch and cannot erase
content already delivered.

The sender of `group_chat` must be active in the referenced manifest and must
have permission under its posting policy. The sender sequence is a durable
per-sender ordering and conflict key; it does not claim a globally serialized
group timeline. Messages may arrive out of order. A receiver may accept that
arrival order, but rejects an authenticated attempt to use one sender sequence
for two different common group-message UUIDs. The common UUID independently
deduplicates retransmitted recipient copies.

New members receive no messages from epochs before their admission by default.
A removed member is omitted from all later fan-out sets, and messages from that
member under an old epoch are rejected after the receiver learns the new
manifest. Because a partitioned member may not yet know the new epoch, removal
is eventual rather than instantaneous. Previously delivered content cannot be
revoked or remotely erased.

The message plus the complete recipient delivery set is committed atomically
before the first LXMF handoff. A `group_receipt` refers both to the recipient's
copy through key `6` and the common group-message UUID through key `13`.
Receipts are accepted only from the child delivery's intended member and update
only that member. Aggregate UI states are derived from every child; one receipt
never proves group-wide delivery.

## Workspace profile v1

Workspaces use a separate LXMF custom type, `b"mesh-chat-workspace"`. Existing
`b"mesh-chat"` traffic is byte-for-byte unchanged. Workspace Content is empty;
the strict custom metadata map contains only:

| Key | Value |
| --- | --- |
| `1` | schema version `1` |
| `2` | `workspace_join`, `workspace_manifest_root`, `workspace_channel_record`, `workspace_channel_manifest`, `workspace_channel_leave_request`, `workspace_channel_transfer_offer`, `workspace_channel_transfer`, `workspace_channel_recovery`, `workspace_channel_summary`, `workspace_channel_fetch`, `workspace_event`, `workspace_leave_request`, `workspace_display_name_request`, or `workspace_display_name_decision` |
| `3` | random 16-byte logical delivery UUID |
| `4` | 16-byte workspace UUID |
| `5` | authenticated application expiry timestamp |
| `6` | the canonical signed workspace document |

Unknown keys or kinds, nonempty Content, malformed identifiers, invalid expiry,
control documents over 16 KiB, and event documents over 20 KiB fail closed.
The authenticated wire expiry must be between receipt time and exactly seven
days after receipt; there is no grace interval outside that live-delivery
window.
Dispatch selects this profile before the Personal parser. An unknown native
source may submit only a fully verified `workspace_join`; every other workspace
kind requires a source device already authorized by the workspace manifest.

Workspace identifiers are the first 16 bytes of
`SHA-256("mesh-chat:workspace:v1:" || creator_destination || nonce)`, formatted
as an RFC 4122 UUID. All documents use sorted-key compact UTF-8 JSON, exact
field sets, NFC-normalized display strings, base64url without padding, and a
signature over the document without its `signature` member. The v1 signed
document types are:

| Type | Authority and purpose |
| --- | --- |
| `workspace_device_card` | A device binds workspace, member and device UUIDs, display name, complete public identity, derived destination, up to two route hints, and creation time. |
| `workspace_genesis` | The creator binds the workspace nonce, name, description, owner and initial authority device. |
| `workspace_manifest_root` | The authority binds an epoch, predecessor, policies, status, retention, members and devices. |
| `workspace_invite` | The authority offers a complete genesis/manifest checkpoint, bounded authority certificate chain, nonce, expiry, and single-use limit. An empty chain remains valid before the first authority change. |
| `workspace_authority_transition` | The current authority signs an exact-successor rotation/transfer offer; that successor signs an acceptance. The final manifest binds the acceptance digest. |
| `workspace_join` | A joining device binds its signed card to the invitation and offered checkpoint. |
| `workspace_channel_record` | The manager binds a versioned channel, predecessor, manifest, visibility, policy context, and archived state. |
| `workspace_channel_manifest` | A private-channel manager binds the version, predecessor, exact workspace manifest, metadata, sorted member roster, and terminal archive state. |
| `workspace_channel_leave_request` | A nonmanager private member asks the manager to remove that member at one exact private-channel head. |
| `workspace_channel_transfer_offer` | The current channel manager names one active successor device, the exact current channel head, the current workspace manifest, and an expiry; a private successor must already be on the roster. |
| `workspace_channel_transfer` | The named successor countersigns the complete manager offer; the resulting digest is the next channel head. |
| `workspace_channel_recovery` | The owner authority device explicitly assigns management at the exact current head; private recovery is valid only when that owner is already on the roster. |
| `workspace_channel_summary` | An active device signs one canonical page of public channel IDs, versions, and head digests for a sync session. |
| `workspace_channel_fetch` | An active device signs bounded channel/head requests and a maximum control count for one summary session. |
| `workspace_event` | An author binds a message or mutation to its workspace/conversation, author stream predecessor, exact manifest, payload, and either an exact channel control or a null channel digest plus the complete sorted two-member DM audience. Private channels bind a sorted audience that can only narrow the target message's historical roster. |
| `workspace_leave_request` | A non-owner binds a leave request to the exact current manifest. |
| `workspace_display_name_request` | An active device signs a replacement card that preserves its member, device, identity, and destination while requesting a new display name. |
| `workspace_display_name_decision` | The authority signs an approval or decline bound to the exact request and its base manifest. Approval is completed by the next manifest; decline is returned directly to the requester. |

Invitation entry points are `meshchat://workspace/<base64url>` and
`MESHWORKSPACE1:<base64url>`. Invitations are single-use and expire within 30
days. The offered checkpoint must retain the exact genesis owner member and
authority device card; a self-consistent manifest signed by another identity is
not a valid checkpoint. Increment 13 supports eight people and up to 32 active
public or private channels including `#general`. Normal admission still creates
one device per member; a seeded already admitted second owner device may be a
rotation successor, without adding Increment 14 enrollment.
It rejects attachments and does not exchange old message history. The authority is not a
message relay: each event is copied directly to every other authorized device
through its individual ratchet-enforced LXMF destination, regardless of that
device's local channel subscription.

Manifest epochs and channel versions are hash-linked. Events carry both exact
control digests plus a positive per-device sequence and previous-event digest.
Missing controls or stream predecessors leave an event inert; invalid
authority, rollback, reused sequence, or equivocation cannot authorize visible
state. A valid enabled manifest epoch admits one member, deactivates one
non-owner member, applies one self-signed display-name request, updates
workspace name/description, changes the exact public-channel creation/posting
policy pair, or closes without another change; combined or no-op epochs are
rejected. `owner_and_admins` is owner-only until admin roles are implemented.
Concurrent invitations are independent capabilities.
When an accepted invitation references an older checkpoint, every intervening
manifest is delivered before or alongside the admission epoch and receivers
apply the chain in order. The mandatory `#general` record is version one, public,
active, predecessor-free, bound to the epoch-one manifest, and managed by the
genesis owner authority. Control copies are scheduled ahead of dependent
events.

Every other public channel begins at version one under an exact manifest whose
creation policy authorizes its manager. Manager-signed metadata/archive records,
successor-accepted transfers, and authority-signed recoveries form one digest
chain. Two different valid digests at one channel version suspend that channel
without suspending its workspace. Archival is terminal; `#general` cannot be
renamed, unsubscribed, transferred independently, or archived. Channel-name
comparison uses NFC validation followed by NFKC case folding, but the random
channel UUID remains authoritative and duplicate comparison keys remain valid.

Discovery summaries contain at most 32 sorted entries per signed page and at
most 32 pages per session. A signed fetch names at most 32 channels and asks for
at most 64 canonical control records. Controls are returned in predecessor
order before the next summary pages. A device labels its directory incomplete
until it has complete, equal summary pages from every admitted device it is
tracking. Missing or reversed controls keep dependent events in the bounded
inert queue. Subscription and read positions are sealed local state;
unsubscribed public channels still receive and retain events but do not accrue
ordinary unread badges.

Private channels use the separate `workspace_channel_manifest` family so a
public directory record can never be reinterpreted as a private grant. Each
head contains one to eight sorted, unique, active workspace member IDs and must
include its manager. Only those members receive the head, offers, accepted
transfers, recoveries, events or pending delivery legs; private heads never
enter public summaries or fetch responses. A new member receives the current
manager-signed head as an admission checkpoint without predecessor controls or
events. Its first future event may therefore begin after a deliberate stream
gap, while events whose signed audience omits that member are rejected before
pending storage. Later heads extend normally; a safe version jump is accepted
only as a same-manager admission checkpoint. Same-version valid conflicts mark
that channel forked. A member removal cancels only that member's unhanded legs.
The manager cannot leave or be removed from the roster until management is
transferred, and archival remains terminal.

Workspace direct messages have no channel-control family. Their conversation ID
is UUIDv5 in the workspace UUID namespace over
`mesh-chat:workspace-direct:v1:` plus the two sorted member UUIDs. The canonical
event sets `channel_digest` to JSON null and carries exactly those two sorted,
unique, active member IDs in `audience_member_ids`; the author must be one of
them. A recipient accepts the event only while both participants are active in
its current manifest. Delivery fans out only to participant devices, local
hide/reopen state is not transmitted, and learning either participant's
removal cancels unhanded DM legs. There is no DM history backfill in this
increment, so an unseen event authored before a known removal is not admitted
after that removal.

### Workspace message mutations

An Increment 5 `message` with no structured mentions remains byte-for-byte
unchanged. Increment 6 added `edit`, `delete`, and `reaction` values for `event_type`.
Those event types add exactly `target_event_id`, `base_revision`, and
`revision`; `revision` must equal `base_revision + 1`. An edit payload contains
only nonempty bounded `text`, a delete payload is the empty object, and a
reaction payload contains exactly one validated Emoji 18 `emoji` and Boolean
`active` state. Increment 8 leaves `thread_root` JSON null for an ordinary
message or mutation and sets it to the canonical root event UUID for a reply or
any mutation of that reply. This preserves the exact canonical bytes and
signature of every pre-thread non-thread event.

An edit or delete is authorized only when the signer is a current active device
of the target message's author member. A reaction is authorized for any current
active member still entitled to the target. Channel posting policy applies only
to new messages: it does not prevent an entitled reader from reacting, and it
does not apply to workspace DMs. Public mutations carry no audience. A private
mutation can address only the intersection of the target's historical audience
and the current roster; a DM mutation repeats the exact current two-member
audience. A target outside the same workspace and conversation, a widened
audience, a removed signer, an unknown target, or a future base revision is
inert or rejected.

Message revisions begin at zero. Concurrent mutation candidates are retained
and the visible candidate is the maximum tuple
`(revision, signer_device_destination, event_digest)`. More than one distinct
value at the highest revision is exposed as a conflict until one later author
revision supersedes it. Two distinct values signed by the same device at the
same revision are equivocation and freeze all further mutation of that message.
An accepted author deletion is a durable tombstone and later edits cannot
restore its plaintext. Reaction state is keyed by workspace, target message,
member, and emoji; `active: false` is a durable inactive tombstone. Reaction
states use the same revision, deterministic winner, conflict, and equivocation
rules.

Mutation events consume the same per-device conversation sequence and
predecessor chain as messages, but never add an entry to the paged conversation
timeline. Their canonical event, stream coverage, derived message/reaction
state, recipient legs, due work, and idempotent operation result commit
atomically. Missing targets, controls, stream predecessors, or mutation bases
remain in the existing bounded encrypted pending queue and are retried when the
dependency arrives. Exact retransmissions are idempotent; delayed stale
candidates cannot overwrite a higher revision or resurrect a tombstone.

### Structured workspace mentions

Increment 7 activates the existing signed `mentions` field for `message` and
`edit` events. It is a canonical sorted, unique list of at most eight member
UUIDs; `delete` and `reaction` events still require the empty list. Every target
must be active in the event's exact manifest. A private-channel or DM target
must also occur in that event's frozen audience, so mention metadata cannot
widen delivery or disclose a member outside the conversation. A public-channel
target may be any active workspace member. Display names and raw `@name` text
are never interpreted as authority-bearing mention metadata.

The complete mention list is copied only with the already authorized signed
event. Each receiver materializes a local mention index only when its own
member UUID is present. Message edits replace both visible text and the signed
mention list under the existing revision, conflict, equivocation, audience and
current-entitlement rules. Removing a mention invalidates its old local index
position; re-adding it allocates a new position rather than reviving stale
unread state.

The Mentions inbox, its read high-water, channel mute preferences, and draft
mention IDs are encrypted local records and are never fanned out. Inbox cursors
bind the current manifest, channel heads and rosters, mute state, retention
generation, and index high-water. Listing re-checks current active membership,
private-channel access, channel state, message hide/tombstone state, and the
active mention position. Unsubscribing a public channel suppresses ordinary
unread state but not its authorized mentions; an explicit mention mute hides
them locally and invalidates older cursors. Marking mentions read does not send
a network receipt.

### One-level workspace threads

Increment 8 activates the existing signed `thread_root` field. A thread reply
is an otherwise ordinary `message` whose `thread_root` is a canonical UUID.
The referenced event must already verify as a retained ordinary message in the
same workspace and conversation, and its own `thread_root` must be null. A
reply can therefore never become a root. An `edit`, `delete`, or `reaction`
copies the target message's thread root, and verification rejects a mutation
whose root differs from its target.

The reply uses the root conversation's existing authorization without a new
audience mechanism. Public-channel replies carry the empty audience. Private
replies carry the exact signed channel roster and require the root checkpoint
to remain on the current channel chain at or after the receiver's latest
admission. Workspace-DM replies carry exactly the same sorted two active
participants as the root. A missing root, control, stream predecessor,
mutation target, or mutation base enters the existing bounded encrypted
pending queue. Once dependencies arrive, per-device sequence and predecessor
validation makes delayed, reversed, duplicated, and restarted processing
converge identically.

Thread replies do not enter the containing channel or DM timeline index. Each
device writes them to sealed per-root pages with a monotonic high-water. A
separate sealed summary stores reply count, unread count, root authorization
metadata, and latest reply time; a capped encrypted activity map retains the
1,024 most recently active roots. Thread cursors bind the root, reply or
activity high-water, retention generation, and a digest of current workspace,
channel-roster, channel-state, and DM-hide authorization. Every page rechecks
the root and current access before returning plaintext.

Thread unread state is a local sealed high-water and never produces a receipt.
Opening a thread marks only that thread read. Thread drafts, activity summaries,
indexes, and cursor state are local encrypted records. Startup exposes only the
persisted bounded workspace thread-unread summary and authorized draft text; it
does not decrypt roots/replies or scan the event and delivery collections.
Hiding a root suppresses the whole thread; hiding a reply suppresses only that
reply and adjusts its unread contribution. Removal, a private-roster gap,
channel leave, hidden workspace DM, missing retained data, or a retention
generation change cannot grant access through a stale index or cursor.

### Retained local history and cooperative retention

Increment 9 enables the manifest's signed `retention_days` transition. The
authority owner may select exactly 30, 90, or 365 days, or JSON null for
indefinite retention; 90 remains the default. The transition is one semantic
manifest change and cannot be combined with membership, metadata, posting,
channel-creation, or closure changes. A non-authority signature is invalid.
This field communicates a cooperative local-history preference and cannot
force another endpoint to delete plaintext or an export it already holds.

Every accepted canonical event enters a sealed retention-order page. Separate
sealed pages cover conversation roots, per-root replies, local mentions,
per-message revisions/reactions, and per-conversation deletion tombstones. A
cursor authenticates workspace and view identifiers, authorization generation,
retention generation, high-water, page, and offset. A changed generation is
`stale_cursor`; a requested retired event is `history_pruned`. No continuation
silently crosses a policy or pruning boundary.

Local pruning processes at most 1,000 canonical events per transaction and
persists a restart cursor. It removes expired event bodies, derived
message/reaction state, completed delivery detail, operation results, due work,
and page entries. Authority manifests and channel controls are retained while
any dependent event can reference them. An author-deletion tombstone and its
target survive until the later of the active history boundary and local durable
receipt plus seven days. The live-delivery expiry remains seven days under
every retention choice, including indefinite history.

Pruned sequence positions remain as content-free sealed coverage markers and
each retired event UUID retains its digest. Stream summaries keep signed
high-water, retained floor, seen ranges, and permanent gaps. These records
prevent delayed duplicates, reversed mutations, or a reused UUID from
resurrecting deleted/edited content, while page results distinguish complete,
locally pruned, and permanently unavailable history.

Every retained body is re-authorized when read. Active and archived public
channels require historical membership and the current workspace boundary;
private content additionally requires the exact historical roster and the
current admission era; a workspace DM remains visible only to its two signed
participants. Former members receive no new event or catch-up leg. Content
already retained and historically authorized may remain as a read-only local
archive until pruning or confirmed local erasure. Owner or future admin status
never grants access to another pair's workspace-DM history.

### Authenticated peer history catch-up

Increment 11 adds `workspace_event_checkpoint`, `workspace_history_request`,
and `workspace_history_response` under the existing workspace custom type. A
request signs a fresh 32-byte nonce, replay key, exact workspace/conversation
scope, requester member/device, current manifest, per-author known head,
retained floor, seen ranges, gaps and requested ranges, event/encoded-byte
limits, optional one-time continuation and an expiry no more than 15 minutes
away. A response repeats every binding, signs responder identity, page index,
previous response digest, peer heads/floors/available ranges/gaps, exact
prerequisite controls/checkpoints/events, explicit counts and bytes, optional
continuation and completion claim.

One response contains at most 32 events, 32 controls, 32 checkpoints and 128
KiB, and construction performs at most 256 direct sequence probes. At most 32
streams and 64 canonical ranges are accepted. Continuations bind the native
source, requester, scope, streams, limits and preceding response and are
single-use. Response IDs and request replay keys have sealed expiry records.
There are at most two jobs per workspace and four per profile.

Public bodies require a currently active workspace requester. Private bodies
require current membership and an unbroken membership chain back through the
event version, so removal and re-admission do not bridge eras. DM serving
requires requester and responder to be the exact two signed participants.
Controls validate before events; every event then follows the ordinary author
signature, stream/predecessor, mutation/thread/audience, tombstone, retention,
materialization and search-index path. A previously unseen inactive-author
public/private event additionally needs a supplied checkpoint whose exact
digest is committed by the applicable current removal control and whose event
chain reaches its signed head. V1 defines no third-party DM anchor. Failure
becomes a permanent gap, never forwarding-peer authority.

Signed peer heads are evidence only of what that peer claimed during the job.
They do not prove global existence, possession of every preceding body, or
future availability. `complete_known` therefore means complete only within the
heads actually signed by the exhausted peers. See
[ADR 0010](docs/adr/0010-peer-history-catch-up.md).

### Workspace authority continuity

An authority offer binds the exact workspace, transition UUID and kind, base
epoch/digest, current owner/authority member-device-destination tuple, successor
member-device-destination tuple, outgoing-owner role, `#general` head and
disposition, 32-byte nonce, replay UUID and a lifetime of at most seven days.
The acceptance embeds the canonical offer and repeats every identity, base and
`#general` consequence before the named successor signs it. Offers and
acceptances are inert. They are capped at 8 KiB and 16 KiB respectively.

An authority-changing manifest advances exactly one epoch, preserves the hash
chain, names the resulting authority, references the acceptance digest, and is
signed by the predecessor authority. Its additive signer-destination field is
invalid on an ordinary manifest. Rotation changes only the authority device.
Ownership transfer changes exactly the outgoing owner to its offered `admin` or
`member` role and the successor to `owner`; it also requires an old-authority
public-channel recovery at the exact `#general` head. Other membership, devices,
policies, metadata, retention, closure, public/private channels and DMs cannot
change in the same epoch.

Invitation `authority_chain` entries contain the exact base manifest, offer,
acceptance, final manifest and optional `#general` recovery. Verification begins
at genesis and rejects missing, reordered, duplicated, truncated, substituted
or wrong-signer steps. The final authority must sign the offered checkpoint and
invitation. Chains contain at most eight transitions and decoded bootstrap JSON
is capped at 256 KiB; reaching either limit requires a replacement workspace,
never proof truncation. Ownership transfer supersedes unused invitations;
same-owner rotation preserves their admission semantics only when the presented
invitation proves the current signer. See
[ADR 0012](docs/adr/0012-authority-continuity.md).

### Workspace administrators and authority requests

Increment 12 makes `owner`, `admin`, and `member` effective roles. There is
exactly one owner and the named owner device remains the sole manifest
authority. Channel creation and posting accept exactly `all_members` or
`owner_and_admins`; invitation requests accept exactly `owner_only`,
`owner_and_admins`, or `all_members_request`. Posting policy does not restrict
authorized reactions. Administrator status does not replace the independent
channel-manager signature and grants no private-channel discovery/recovery or
third-party workspace-DM access.

The canonical `workspace_admin_request` family has explicit `request` and
`decision` phases. A request signs its workspace/request/kind, exact base epoch
and digest, requester member/device, optional single nonowner target, optional
`admin|member` role, bounded note, replay key and seven-day-or-shorter lifetime.
A decision signs the exact request UUID and digest, base state, owner authority,
`approved|declined`, `invitation|manifest|no_change`, exact result digest and
embedded canonical result, replay key and creation time. Only the owner
authority can sign a decision or resulting manifest. Unknown fields,
noncanonical bytes, mismatched native/inner identities, stale bases, wrong
targets/roles/results, replays and conflicting decisions fail closed.

Requests are at most 4 KiB, decisions 48 KiB, and notes 250 characters. Pending
state is capped at 128 per workspace, 512 per profile and 32 per authenticated
requester/source; pages contain at most 100 rows and future/inert decisions at
most 64. Terminal audit and replay evidence remains sealed for 90 days. Exact
schemas, lifecycle, transitions and compatibility behavior are frozen in
[ADR 0011](docs/adr/0011-workspace-administrators.md).

### Encrypted local workspace search

Increment 10 adds no wire document, packet kind, peer request, or canonical
event field. Search is a local derived index over retained records and does not
change interoperability with peers that do not implement it.

Search text is normalized by Unicode NFKC, Unicode default case folding, then
NFC. Unicode letters and numbers form tokens; a combining mark remains attached
to a preceding letter or number; punctuation, symbols, separators, controls,
and whitespace end a token. Tokens outside 2–64 characters are omitted and
duplicates collapse in first-occurrence order. A query is 1–256 characters,
at most 1,024 UTF-8 bytes and eight retained tokens. Matching is exact-token
AND; prefix, substring, fuzzy, and remote matching are absent.

The vault derives every token, document, catalog, shard, and page identifier
with its local HMAC key. A token page holds at most 100 opaque document
references. Execution chooses the least common query token and opens at most
eight shard pages, 256 candidate documents, and 50 authorized presentation
results (25 by default). One document contributes at most 512 unique tokens and
the retained index stops at 2,000,000 references. Hitting any content, shard,
candidate, or growth bound returns explicit incomplete coverage.

Every candidate is reloaded from its authoritative sealed record, freshly
tokenized, and passed through historical manifest/channel entitlement plus the
current workspace state, private admission version, exact DM participants,
thread root, local hide, author deletion, and retention boundary. Search index
membership never grants access. Root results and reply results are distinct and
carry the exact conversation and thread-root identifiers needed for navigation.
Current permitted display names and visible channel name/topic records use the
same candidate rule; unsubscribed public channels remain searchable when their
records were locally retained.

A cursor MAC binds the workspace, opaque normalized-query and scope digests,
authorization generation, retention generation, search generation, opaque
token shard and head page, and result offset. It contains no raw query. Edits,
deletions, hides, pruning, access/directory changes, and retention transitions
remove references or make old cursors stale; reaction-only mutations do not
alter message-text tokens. Existing retained data rebuilds from the sealed
retention order in restart-safe transactions of at most 128 events. Until it
finishes, results report indexing rather than claiming retained completeness.

### Linked desktop devices

Increment 14 admits a fresh per-desktop identity to an existing member through
a countersigned, 15-minute, single-use `workspace_device_link_offer` and
`workspace_device_link` acceptance. The offer authenticates the workspace,
exact base manifest, member and existing sponsor device. It also binds at most
64 strictly ordered historical manifest checkpoints needed by the minimal
authorized channel-control admission suffix, including epoch one for
`#general` when linking after the initial epoch. The acceptance embeds that
offer and a fresh self-signed device card. Only the current authority's
next manifest makes the card effective. That manifest carries
`device_transition_digest` and may change exactly one device card while every
other membership, authority, metadata, policy and retention field remains
fixed. Ordinary and authority-transition verification reject this field.

`workspace_device_removal` is signed by another admitted device of the same
member and names the exact base and target. The authority device cannot be
removed until authority rotates. Known removal stops new delivery to that
destination, cancels its queued legs, and rejects newly seen events from it;
partitioned peers enforce removal when the signed manifest reaches them.

Channel and DM commits freeze all recipient devices, including the sender's
other desktops. Delivery remains one durable leg per destination with explicit
person/device detail. A new endpoint receives authorized controls and recovers
canonical events through bounded peer-history catch-up; identity material is
never copied. Optional encrypted `workspace_read_hint` controls go only to the
same member's other devices and apply only at an identical canonical head, so
they are not social read receipts. Exact schemas and lifecycle rules are frozen
in [ADR 0013](docs/adr/0013-linked-desktop-devices.md).

## Delivery evidence

| App state | Required evidence |
| --- | --- |
| `waiting_for_keys` | durable local ciphertext, but no acceptable recipient ratchet |
| `queued` | durable local record awaiting route/retry/consent |
| `sending` | handed to LXMF; recipient commit unconfirmed |
| `stored_for_delivery` | propagation node accepted recipient ciphertext |
| `received_by_endpoint` | native endpoint delivery proof |
| `delivered` | intended contact sent a valid encrypted receipt after committing the logical message |
| `expired` | seven-day application window ended |
| `failed` | non-transient validation, storage, or identity error |
| `cancelled` | the recipient left or was removed before that pending workspace leg completed |

Receipts are ordinary signed, end-to-end encrypted LXMF messages. They reference the original logical UUID, are persisted with the inbound message, are retried, are never themselves acknowledged, and are accepted only from the pending message's expected contact.

## Limits and modes

- Text: 16 KiB UTF-8.
- Delivery/deduplication window: seven days.
- Invitation: 16 KiB decoded.
- Canonical group control document: 16 KiB UTF-8.
- Group invitation lifetime: seven days by default, never more than 30 days.
- Group title and member display name: 1–64 normalized characters each.
- Signed connection hints per group member card: at most two validated TCP hints.
- Private group or announcement channel: at most eight people including the owner.
- Workspace: at most eight people, 32 active channels including `#general`, 32 entries per signed public-summary page, 32 pages per sync session, and 64 controls per signed public fetch response. Archived public channels are retained in the bounded 1,024-entry directory; private channels are never summarized publicly.
- Workspace local search: at most 256 query characters, 1,024 UTF-8 bytes, 8 exact tokens, 8 keyed shard pages, 256 candidates, and 50 results; rebuilds advance at most 128 retained events per transaction.
- Workspace history catch-up: 32 streams, 64 ranges, 32 events, 32 controls, 32 checkpoints, 128 KiB and 15 minutes per request; 256 sequence probes per response; 2 jobs per workspace and 4 per profile.
- Workspace administration: 4 KiB requests, 48 KiB decisions, 250-character notes, seven-day maximum lifetime, 128 pending requests per workspace, 512 administrative requests per profile, 32 pending per requester/source, 100 rows per page, 64 inert decisions, and 90-day replay/audit retention.
- Workspace authority continuity: 8 KiB offers, 16 KiB acceptances, seven-day maximum lifetime, 32 pending transitions per workspace, eight certificate steps, 256 KiB decoded invitation bootstrap, and 90-day replay/audit retention.
- Linked desktop devices: three admitted devices per member, 24 active workspace destinations, 15-minute one-use links, 320 KiB link/acceptance documents including at most 64 historical manifest checkpoints, 32 pending transitions per workspace, and four pending requests per source fingerprint.
- Mobile local notifications: no canonical protocol change; 128 sealed pending native IDs, 16 items per drain, 1,024 UTF-8 bytes per native item, 80-character title, 160-character body, a 64-hex opaque notification ID, and a 32-hex opaque grouping key.
- Pending reactions: at most 256 total and 32 per authenticated actor.
- IPC frame: 4 MiB; renderer-originated payload: 32 KiB, except the two desktop device-link preview/submission commands which accept at most 700 KiB of encoded bootstrap input.
- LXMF direct and propagated modes: enabled.
- LXMF opportunistic, paper, PLAIN and RNS GROUP private-chat/group fallbacks: not used.
- Propagation cache: 100 MiB.
- Automatic propagation peering: disabled.

RNS/LXMF versions are pinned in `service/requirements.lock`. Propagated packing is refused unless RNS has a current recipient ratchet, preventing the upstream base-identity-key fallback.

## Local notification and lifecycle messages

Notification decisions, OS permission hints, lifecycle transitions, and native
acknowledgments are device-local sealed state, not signed wire documents.
`native_notification_state`, `mobile_lifecycle_transition`,
`drain_native_notification_work`, and `acknowledge_native_notification` are
native-only commands excluded from the renderer allowlist. Renderer commands
may read state, change preferences, reconcile, and resolve an opaque target
through current authorization.

Mobile linking continues to serialize the exact Increment 14 offer,
acceptance, and authority manifest transition. No platform field or
notification preference enters canonical bytes, and 0.2.34 peers require no
compatibility branch.

## Direct mapping protocol distinction

Internal encrypted mapping records now carry `protocol: "tcp" | "udp"`.
Records without that field retain their historical TCP meaning. PCP and NAT-PMP
mapping creation, renewal and deletion preserve the selected transport; UPnP
mapping and IPv6-pinhole creation select it explicitly as well. A UDP mapping
cannot be exported through the legacy TCP invitation-endpoint helper. Existing
invitation schemas remain unchanged. The Phase 2 candidate collector binds the
native UDP socket first and maps that exact interface and port. Ownership is
rechecked before signing; mapping lifetime bounds the descriptor and cleanup.

Wire references: [NAT-PMP RFC 6886](https://www.rfc-editor.org/rfc/rfc6886.html#section-3.3)
and [PCP RFC 6887](https://www.rfc-editor.org/rfc/rfc6887.html#section-11).

## Direct Offer and version-2 email exchange

Phase 2 adds an explicit version 2 for direct Offers, bindings, Answers and Ready.
Version 2 permits zero public candidates: inability to host or discover a public
tuple must not prevent authoring a signed reply. It conveys no reachability claim.
Version 1 retains its one-to-eight candidate requirement and unchanged encoding.
Response envelope, binding and parent versions must all match; mixed-version
chains and implicit downgrades are rejected. Scope, signature, certificate,
validity and durable replay checks are unchanged. Public setup integration remains
separately qualified; creating a document does not activate a transport.

The experimental canonical `direct_offer` version 1 carries `scope`,
`issuer_public_identity`, `issuer_destination`, `certificate_sha256`, `alpn`,
`session_id`, `challenge`, `generation`, `candidates`, `issued_at`, `expires_at`
and `signature`, alongside `v` and `type`. There is no audience field. Scope is
an exact invitation digest and expiry; the expected authority comes from the
separately verified invitation. RNS signs the entire unsigned canonical object.
The 16 KiB/depth-eight parser rejects duplicate/unknown fields and non-integer
numbers. Transport validation shares direct-binding certificate, challenge,
generation, validity and global numeric candidate rules. Equal generation and
identical digest is idempotent; conflicting or lower generations fail.

Version 1 remains an internal controlled-proof codec. Version 2 is exported in
the wrapper below; verification alone does not attach an RNS interface or grant
membership.

Experimental `direct_answer` and `direct_ready` version 1 contain exactly `v`,
`type`, `parent_digest`, `binding` and `signature`. `parent_digest` is the SHA-256
of the exact signed canonical Offer or Answer respectively; `binding` is the
existing signed audience-bound descriptor. The binding issuer signs the entire
unsigned envelope. Full-chain verification checks all signatures and supplied
native certificates against independently supplied authority. Answer addresses
the Offer signer; Ready is signed by that owner, addresses the Answer signer,
and uses an owner generation greater than Offer's. Scope/challenge match and
child validity stays within parent validity. The envelope's generation/digest
provide replay evidence. Codec validation alone does not persist acceptance,
start attempt timers or prove continued socket ownership.

Private owner acceptance now stores the exact signed Offer and public certificate
in the encrypted pending negotiation. Answer acceptance reloads that Offer and
current invitation authority under the same transaction that pins the responder
and stores envelope/binding replay history. No imported caller-provided parent
replaces the saved Offer. The joiner privately persists its own verified Offer/Answer chain
and accepts Ready against that saved chain while rechecking pending-join authority
in the vault transaction. Replacing the Answer clears previous Ready evidence but
retains replay history. These durable records confer no socket ownership or live
readiness. The production controller retains the exact native Answer socket/key
through Ready re-arming; losing it requires a fresh exchange.

The public wrapper is canonical JSON with exactly `v: 2`,
`type: "direct_connection"`, `invitation`, `offer`, `answer`, and `ready`.
Each present stage has exactly `document` and lowercase-hex `certificate`;
absent Answer/Ready stages are null. The invitation is the original signed
workspace invitation, unchanged. `mesh-direct:` carries unpadded base64url of
these bytes; raw canonical JSON is also accepted. Decoded size is bounded at
768 KiB; public import framing is capped at 2 MiB. The entire chain, authority,
certificates, expiry and canonical encoding are verified before application.

Explicit public commands preview, prepare Offer/Answer/Ready, accept Ready,
connect, read status and cancel. They return opaque documents and summaries,
never private native handles, keys or packet controls. They bypass durable
command-response caching: a restarted process cannot replay a dead socket export.
Creating Answer saves the ordinary signed join request; admission still requires
the owner's normal approval. Both-empty candidate sets retain existing routes,
including previously signed TCP routes, and report an explicit fallback state.

Version 2 selects the unhosted peer as QUIC client when only one side has public
candidates; otherwise the smaller authenticated RNS destination is client.
Version 1's identity-order rule is unchanged. Only standard QUIC mechanisms are
used, with bounded attempts and signed lifetimes. No public observer, rendezvous,
STUN, TURN or relay is introduced.

Bootstrap RNS/LXMF runs in an isolated process and permits only join, join receipt,
admission root and `workspace_direct_binding` controls for the exact selected peer.
Admission permits a maximum 30-second control transition. Fresh native credentials
and current workspace-device bindings authorize the ordinary packet adapter;
a signed peer announce on that path confirms adapter installation before the old
bootstrap carrier retires. The `direct_admission` v2 control contains exactly
`v`, `type`, `binding`, and `certificate`, is capped at 64 KiB, and passes durable
binding acceptance. Transport authentication never substitutes for LXMF signature,
recipient ratchet, membership, replay or application-receipt checks.

## Durable admitted binding storage

Phase 3 groundwork preserves all invitation and direct-document wire schemas.
Workspace binding acceptance stores the signed public binding/certificate,
candidates/validity and exact identity/audience/device scope atomically with
the existing monotonic replay record. An imported binding is not live-route
evidence. Historical success requires native authentication and a validated
peer RNS announce, and cannot be written by a superseded generation. The
persistent reconnection/update exchange remains unimplemented.


## Admitted direct recovery (Phase 3)

Existing invitation and version-1/version-2 direct document schemas are unchanged.
A workspace-only binding version 3 selects `mesh-direct-recovery/1`, retaining the
exact canonical identity, audience, device-pair scope, generation, certificate hash,
numeric candidate and one-hour validity bounds. Its deterministic challenge hashes
canonical `{purpose, scope, issuer, audience}` with purpose equal to that ALPN;
current signed membership is the authority, never an expired invitation challenge.
The existing encrypted replay key spans transport versions and certificate rotation.

`mesh-recover:` wraps canonical `{v:1,type:"direct_recovery",binding,certificate}`.
The complete document is bounded to 16 KiB; the certificate is at most 4096 bytes.
`workspace_connection_update` carries it in the ordinary active-workspace control
envelope, with the source and envelope workspace checked against the inner binding.
The isolated pending bootstrap whitelist does not admit this control. Explicit
import requires the selected workspace and an already established relationship.

Provisional QUIC exchanges only a peer-RNS-encrypted signed binding (20 KiB maximum).
Both protected services bind the actual TLS leaf to current RNS membership and
persist replay acceptance before approving that connection's exporter token.
Only then may two approval streams complete and RNS DATAGRAMs cross. Attempts last
at most 60 seconds, service authorization at most 10 seconds, and sessions at most
one hour. Initial role ordering follows candidate availability and RNS destination;
bounded alternating standard dial/listen windows permit role reversal when only the
other endpoint's address remains known. No public observer or custom probe is used.

Recovery updates and successes are transport controls. They never create joins,
admissions, chat messages, delivery proofs or application receipts.
# Server-free traversal increment (implementation qualification pending)

The current connection implementation extends the signed version-2 candidate
list to a bounded group of retained native route sockets with a common native
certificate. The existing invitation, audience, generation, expiry and exact
certificate checks remain authoritative. Both endpoints may initiate standard
QUIC/TLS checks; only the deterministic client's outgoing connection and the
server's incoming connection can reach bootstrap traffic. Auxiliary connections
carry no RNS packets. There are no new unauthenticated UDP frames or observer
services. See [ADR 0019](docs/adr/0019-server-free-traversal.md) for bounds and
the remaining review and qualification gates. No-address discovery failures do
not become reachable merely because both peers can initiate checks.

# WebRTC signaling and reconnect documents (0.9.1)

These documents are separate from LXMF chat payloads. They are canonical signed
JSON, expire, and bind both identities. They are used only for WebRTC rendezvous
and capability discovery; a valid signature is never authorization to create a
contact, approve one, or change workspace authority.

## Connection capabilities

Type: `connection_capabilities`, version `1`. Exactly these fields:

```json
{
  "v": 1,
  "type": "connection_capabilities",
  "peer_destination": "<32-hex recipient>",
  "device_id": "<8-80 chars, [A-Za-z0-9._:-]>",
  "transports": ["webrtc"],
  "auto_reconnect": false,
  "allow_direct_ip_disclosure": false,
  "relay_consent_scope": "contact",
  "issued_at": 0,
  "expires_at": 0,
  "signer_public_key": "<base64url RNS public key>",
  "mailbox": {
    "url": "https://<worker>/",
    "pair_token": "<16-160 chars, [A-Za-z0-9_-]>",
    "expires_at": 0
  },
  "signature": "<base64url>"
}
```

- `peer_destination` is the recipient. The signer destination is derived from
  `signer_public_key` and must equal the contact destination.
- `transports` is a non-empty unique subset of `webrtc`, `direct_tcp`,
  `access_point`, and `i2p`. Current reconnect uses `webrtc`.
- `auto_reconnect` and `allow_direct_ip_disclosure` are independent booleans.
  They are the sender's own consent, never a grant to the receiver.
- `relay_consent_scope` is `contact`, `session`, or `workspace`.
- `expires_at` is at most seven days after `issued_at`; `mailbox.expires_at` is
  at most 30 days after issuance. A mailbox object needs all three fields.
- Existing contacts without a capability, or with `auto_reconnect: false`, cannot
  reconnect automatically. A consent or mailbox change requires a new signed
  document and rotates the pair token.

## Reconnect request

Type: `webrtc_reconnect_request`. The preferred (lexicographically lower device
ID) side publishes it.

```json
{
  "v": 1,
  "type": "webrtc_reconnect_request",
  "from": "<32-hex sender>",
  "to": "<32-hex recipient>",
  "device_id": "<sender device>",
  "attempt_id": "<16-80 chars>",
  "nonce": "<16-80 chars>",
  "issued_at": 0,
  "expires_at": 0,
  "signer_public_key": "<base64url>",
  "signature": "<base64url>"
}
```

`from` must equal the signer destination. Retries may repeat the same request;
the prober reuses one attempt ID and one signed request across retries.

## Reconnect offer

Type: `webrtc_reconnect_offer`. The request recipient creates it, so the request
and offer are signed by different devices.

```json
{
  "v": 1,
  "type": "webrtc_reconnect_offer",
  "from": "<request recipient>",
  "to": "<request sender>",
  "attempt_id": "<same as request>",
  "session_id": "<16-80 chars>",
  "sdp": "v=0...",
  "dtls_fingerprint": "sha-256 AA:...",
  "nonce": "<same as request>",
  "issued_at": 0,
  "expires_at": 0,
  "signer_public_key": "<base64url>",
  "signature": "<base64url>"
}
```

The SDP must be a WebRTC DataChannel offer, contain exactly one
`a=fingerprint:` line, and contain the declared fingerprint. Expiry is at most
the request expiry and one hour from issuance.

## Reconnect answer

Type: `webrtc_reconnect_answer`. The original requester creates it.

```json
{
  "v": 1,
  "type": "webrtc_reconnect_answer",
  "from": "<request sender>",
  "to": "<offer sender>",
  "attempt_id": "<same as offer>",
  "session_id": "<same as offer>",
  "offer_digest": "<sha256 of the exact offer document>",
  "sdp": "v=0...",
  "dtls_fingerprint": "sha-256 AA:...",
  "nonce": "<same as offer>",
  "issued_at": 0,
  "expires_at": 0,
  "signer_public_key": "<base64url>",
  "signature": "<base64url>"
}
```

Verification checks the attempt, session, and exact offer digest before the SDP.
One answer is accepted per offer digest; the durable replay record survives a
restart. Expiry is at most the offer expiry and one hour from issuance.

## Mailbox transport

The optional Worker exposes:

```text
PUT /signal/<session>/<role>    X-Mesh-Token: <pair token>
GET /signal/<session>/<role>    X-Mesh-Token: <pair token>
```

Roles are `request`, `offer`, and `answer`; each accepts only its document type.
The session is derived from the pair token (SHA-256, 40 hex characters), so the
operator cannot enumerate pairs from public destination hashes. The first
authenticated write pins the token hash; later reads and writes require it.
Rotation uses `X-Mesh-Token-New` from the current holder. Documents and counters
expire after ten minutes; the envelope cap is 48 KiB. Reconnect document types
are rejected without a token. Tokenless offer/answer remains available only for
manual onboarding.

## Authorization order

Before an `RTCPeerConnection` is created, the service and renderer check, in
order:

1. canonical shape, exact key set, signature, and signer-derived destination;
2. `from` equals the signer and `to` equals this device;
3. the signer is an existing contact and the contact is approved or verified,
   not blocked, deleted, or identity-changed;
4. the document is unexpired and the replay key is unused;
5. reciprocal auto-reconnect consent exists for the contact;
6. for an offer or answer, the attempt, session, and offer digest bind;
7. for a capability, the recipient matches this device.

Failure at any step is reported without creating a peer connection and without
changing contact, workspace, or device trust.
