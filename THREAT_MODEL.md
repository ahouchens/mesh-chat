# Threat model

## Join receipt and direct-underlay gate

An LXMF proof is not durable application validation. The new join receipt is
signed by the exact invitation authority and bound to the original join digest,
delivery UUID, workspace and audience device/destination. Wrong sources,
signatures, attempts, audiences, versions and expired controls cannot change
approval-pending state. Request and receipt outbox commit together; a storage
failure cannot leave an acknowledgment for an unsaved request. Duplicate replies
reuse one logical delivery with bounded requeue timing. Admission still requires
the existing manifest; the receipt is never a human read receipt.

Canonical receipts and interrupted route-setup documents remain encrypted in
service storage and excluded from renderer snapshots. The renderer receives
only a verified-acknowledgment boolean in addition to existing delivery evidence.

The isolated QUIC proof is not activated in the app. It uses ephemeral TLS keys,
exact mutual certificate checks, no 0-RTT, packet/queue limits and no external
discovery. RNS key binding, bootstrap isolation, adapter injection resistance,
and physical traversal remain qualification requirements. Stock UDP `online`
means a local listener exists; local bytes reach RNS before downstream IFAC
validation. Engine health and remote liveness require separate evidence. See
[ADR 0018](docs/adr/0018-authenticated-direct-underlay.md).

## Participant-hosted Internet invitations

The default Internet flow introduces no third-party Mesh Chat or workspace entity. The inviter is both the authenticated invitation signer and temporary connection operator. Email, Slack, Teams, QR, clipboard, and file providers see or carry invitation data but receive no Reticulum role, contact trust, membership, message key, or routing authority.

- Router-control exposure: UPnP discovery is bound to selected active interfaces, SOAP is limited to bounded responses and same-router private/link-local IPv4 control URLs, and NAT-PMP/PCP use bounded retransmissions to configured default-route gateways. PCP nonces are cryptographically random. Mesh Chat requests only a short TCP mapping or IGD2 IPv6 firewall pinhole to its temporary listener. It never sends credentials to a public discovery service. A compromised local router already controls the participant's network and can redirect, observe, drop, or retain the mapping; IFAC and application signatures still prevent it from becoming the inviter or decrypting valid content.
- Invitation capability leakage: v3 contains public endpoints plus a temporary Reticulum IFAC network name/passphrase. Treat it as a short-lived bearer capability. Anyone obtaining it can attempt the temporary interface until expiry, but cannot pass Mesh Chat identity, invitation-nonce, workspace-authority, recipient-ratchet, or message-signature checks. Connection/rate/session bounds contain opportunistic probing. Revocation, stop, expiry, and clean app shutdown remove the listener and mapping; a crash or hostile router can leave the router lease until its short expiry.
- Reachability uncertainty: a router reporting a mapping or an operating system reporting global IPv6 is not independent proof that carrier/firewall policy permits the recipient. With no external probe, the recipient performs the first real check. Failure is shown and never triggers a silent third-party fallback.
- Diagnostic and firewall disclosure: Connection Doctor emits only enumerated phase/result/reason/action values. Renderer snapshots and copied summaries exclude public/local addresses, router URLs, invitation credentials, executable paths, rule names, and raw errors. The Windows firewall action requires explicit elevation and limits a temporary rule to the exact sidecar, TCP port, and active profile; it cannot prove an upstream path.
- Manual forwarding: the participant supplies a public endpoint but never router-administrator credentials. Public-address validation rejects private/shared/reserved and special-use destinations. Mesh Chat cannot remove a manual router rule, and an abandoned rule remains the participant's responsibility even though the invitation credential expires.
- Address and interface isolation: only validated public endpoints enter portable v3 content. Off-LAN listening is isolated from the ordinary LAN listener and requires the fresh IFAC credential. Runtime listener/client fields are excluded from generic settings serialization, logs, and renderer state; protected records contain the credential and cleanup material.
- Availability and metadata: direct hosting fails behind some provider/shared NAT, symmetric NAT, double NAT, enterprise networks, firewalls, and disabled mapping configurations. Local RFC1918 or `100.64.0.0/10` WAN evidence is reported conservatively and does not prove a specific NAT implementation. An ISP, local router, invitation-channel provider, and network observer may correlate endpoints, timing, sizes, and connection duration. This design does not claim anonymity, universal NAT traversal, push delivery, or operation while the inviter is offline.
- Role separation: opening an invitation listener does not enable Reticulum transport, LXMF propagation, or workspace-wide relaying. Those roles remain separate explicit controls. After admission, multi-member reachability still depends on direct participant paths or an explicitly chosen routing/access topology.

## Remote access points and imported profiles

Remote access adds an untrusted transport operator and attacker-controlled invitation input; it does not make the gateway an identity, membership authority, key directory, receipt, or source of message validity.

No third-party operator is introduced by default. Personal and workspace Internet invitation creation starts in participant-hosted v3 mode, with the inviter online and no shared transport profile. An access-point operator enters the network path only after the inviter explicitly selects an approved profile for that individual invitation and the recipient separately consents. Nearby/private-network v1 is a separate explicit fallback.

- Invitation-triggered SSRF and private-network scanning: preview performs no I/O. Imported literals and every DNS answer are classified before each connection, mixed safe/unsafe results fail closed, and Reticulum receives only the validated numeric address. Private destinations require a separately labeled advanced manual action.
- DNS rebinding: approval does not cache a hostname as proof. Each attempt resolves and validates again, and no second library hostname lookup is used for the connection.
- Profile tampering, scope confusion, replay, and retention: outer signatures bind the exact profile, exact inner digest, purpose, signer, and dates; signer cross-checks bind the inner authority; bounded encrypted reference records separate pending invitation, Personal contact, and workspace scopes. Revocation, rejection, expiry, removal, closure, and erasure release only their own scope.
- Route preference attacks: shared remote TCP interfaces use normal gravity and are not stored as signed direct hints. Nearby discovery and signed direct routes remain preferred. Outbox entries remain route-independent.
- Renderer and native ingress injection: service commands accept canonical profile or profile IDs, never arbitrary Reticulum config, filesystem paths, interfaces, or commands. Desktop and Android native handlers exact-parse supported outer families under fixed byte limits before renderer handoff. Unknown versions, fields, schemes, file types, and malformed UTF-8 fail closed.
- Malicious or compromised gateways: an operator can correlate source IPs, timing, sizes, duration, and routing identifiers; exhaust connections; selectively delay, duplicate, or drop packets; or disappear. Existing destination binding, identity signatures, workspace authority chains, recipient ratchets, replay protection, and application receipts prevent it from forging contacts, joins, manifests, messages, or receipts or decrypting valid content.
- Connection exhaustion and unknown-source joins: profile/endpoint/retry/path bounds, exponential backoff with jitter, existing unknown-source join size/rate/identity exception, invitation nonces, and owner approval contain work. The self-host example adds process/file/memory ceilings and recommends per-source and global firewall limits.
- Propagation misconduct: a node may withhold, prune, duplicate, delay, or falsely imply only that it accepted an object. Retrieval re-enters ordinary LXMF and Mesh Chat verification and deduplication. Storage, endpoint receipt, and application receipt are displayed separately. A recommended node is inert until separate consent and automatic peering is disabled.
- Leakage: raw endpoints, invitation content, destinations, identity material, and credentials stay out of ordinary renderer snapshots, conversation route labels, logs, notifications, Android intents, command-line arguments, and unencrypted application records. Sanitized diagnostics can still reveal that a profile exists and broad availability state.

Residual risks include traffic analysis, denial of service, gateway collusion, an operator retaining ciphertext or metadata, DNS resolver compromise that returns only attacker-controlled public addresses, compromised endpoints, and Android suspension delaying reconnection or propagation retrieval. First contact can require both apps to be open until path announcements and ratchets arrive. Remote access and propagation are not cloud push and do not guarantee background delivery.

## WebRTC signaling mailbox and automatic reconnect

The optional signaling mailbox is a new untrusted rendezvous operator. It can
observe and manipulate signaling; it is never an identity, membership authority,
delivery receipt, or message store. Automatic reconnect adds a second adversary
class: a peer or relay that presents stale, replayed, or misaddressed documents
and expects the app to allocate a transport or change trust.

- **Mailbox confidentiality and integrity.** Every reconnect document is
  canonical, signed, expiring, and bound to sender, recipient, device, attempt,
  session, and (for an answer) the offer digest. The operator sees signed
  envelopes, source IPs, and timing, but no message plaintext and no contact or
  workspace state it could forge.
- **Capability authentication.** Reconnect always requires a pair token sent as
  `X-Mesh-Token`. The Worker stores only its SHA-256 hash, pins it on the first
  authenticated write, rejects wrong or missing tokens, and accepts rotation
  only from the current holder. A leaked token permits rendezvous abuse for that
  pair, not contact approval or decryption.
- **Abuse limits.** Ten-minute sessions, a 48 KiB envelope cap, role/type
  matching, and per-token and per-client-IP read/write budgets bound storage and
  request floods. The Worker's alarm deletes expired documents and counters.
  Sessions remain tokenless only for the manual onboarding path; reconnect is
  never tokenless.
- **Consent, not approval.** Reconnect requires local and peer auto-reconnect
  consent, a separate direct-IP-disclosure decision, and an approved,
  non-blocked contact. It never creates or approves a contact, workspace member,
  or device, and never changes workspace authority.
- **Replay and expiry.** The replay cache is durable and sealed, one answer is
  accepted per offer digest, and expired or tampered documents are rejected
  before a peer connection exists. A restart does not clear replay state.
- **Transport isolation.** A blocked, deleted, or rejected peer is refused by the
  service before the renderer allocates an `RTCPeerConnection`. A transport,
  TURN, or mailbox failure never changes trust.
- **Local secrecy.** Reconnect never persists SDP, ICE credentials, DTLS keys, or
  chat plaintext, and none are logged. Call signaling records store the
  negotiated SDP and ICE candidates in the vault by default; the
  `store_call_signaling` setting can keep them in service memory only, at the
  cost of losing call history/restart state. The mailbox holds the signed
  offer/answer envelope, including its ephemeral SDP, only for the ten-minute
  TTL. Broker-issued TURN credentials stay in service memory; a manually
  configured TURN credential is sealed in call settings.
- **Reciprocal auto-answer.** A responder verifies that the request is from an
  approved contact with reciprocal consent before creating an offer. A capability
  received before its contact record is held without granting trust and promoted
  only after approval.
- **Focus and UI.** Reconnect never opens a modal, steals focus, or repeats a
  contact-approval prompt.

Residual risks: the mailbox operator and TURN relay can still observe signaling
or media IP addresses, timing, sizes, and which pair is attempting a connection;
they can selectively delay, drop, or replay envelopes within their validity
window. A leaked pair token allows denial of service against that pair's
rendezvous. Reconnect exists only while both apps are open and unlocked, so
absence of a connection is not proof that a peer is offline. There is no
background daemon, push notification, live session migration, or iOS background
execution.

## Security goals

- No required application infrastructure or hidden public mesh connection.
- Chat text and sensitive application metadata remain confidential to endpoints across transport and propagation devices.
- A contact identity cannot be silently substituted after approval or verification.
- Automatic reconnect requires reciprocal, explicitly recorded consent and never
  approves a contact, workspace member, or device.
- A reconnect, signaling, relay, or transport failure never changes contact,
  workspace, or device trust.
- Reconnect never persists SDP, ICE credentials, or DTLS keys locally or in
  logs; call signaling records store SDP/ICE only when `store_call_signaling` is
  enabled (the default), and broker-issued TURN credentials stay in memory.
- Local contacts, group membership and controls, messages, drafts, outbox work, receipts, identity and ratchet state are not persisted as plaintext.
- Network acknowledgments never overstate recipient application persistence.
- Group membership and posting authority cannot be changed without a valid,
  hash-linked owner-signed membership epoch, and one member's receipt never
  overstates delivery to the whole group.
- Workspace membership, policy and closure cannot change without a valid,
  hash-linked authority manifest; events cannot escape the audience frozen by
  their referenced manifest and channel control.
- An administrator request cannot become membership or role authority; one
  exact owner-authority decision and its embedded canonical result are required
  before an approved effect is presented as applied.
- A workspace mention cannot name an inactive or out-of-audience member, arise
  from raw display-name text, or retain local inbox visibility after the reader
  loses workspace or private-channel access.
- A reaction cannot claim another actor, cross a direct/group boundary, target
  another conversation, reveal old group content to a later member, or be
  restored by an older revision after replacement, removal, or local deletion.
- Malformed, oversized, replayed, unknown-source and mismatched traffic fails closed with bounded work.

## Adversaries considered

- A passive network observer on LAN or IP links.
- A curious or compromised intermediate Reticulum transport node.
- A curious LXMF propagation node storing recipient-encrypted objects.
- An unknown or blocked sender attempting spam, parsing attacks, replay, or identity confusion.
- A removed or unauthorized group participant replaying an old invitation,
  manifest, message, acceptance, or receipt.
- A compromised group owner signing conflicting membership manifests for one
  epoch. Mesh Chat detects and suspends on this equivocation; it cannot prevent
  a valid owner key from signing it.
- A compromised workspace authority or device signing conflicting controls or
  event-stream entries. Valid equivocation is detected and suspends use; a
  valid stolen key cannot be made honest by protocol validation.
- A malicious history peer probing protected scopes, advertising impossible
  heads, withholding ranges, replaying/swapping continuations or responses,
  substituting another workspace/conversation, amplifying a tiny request, or
  forwarding forged, noncanonical, stale, forked or unauthorized material.
- A compromised or spammy administrator creating policy-permitted channels and
  posts, abusing a legitimately managed channel, phishing owner review, or
  flooding, replaying, substituting and conflicting administrative requests.
- A compromised authorized endpoint legitimately retaining and later
  disclosing cooperative history. The protocol limits disclosure to current
  authority but cannot make an unlocked entitled endpoint forget plaintext.
- Another unprivileged local process attempting profile reuse or control-channel access.
- Accidental process or shell crashes during durable message transitions.

## Controls

- Native RNS/LXMF encryption and signatures; no custom cipher or routing layer.
- Ratchet-enforced individual destinations and explicit ratchet presence for every enabled send path.
- Verified invitation signature and public-identity/destination re-derivation.
- Explicit pending request, approved, verified, changed, and blocked trust states.
- Private inherited desktop pipes or an in-process native mobile bridge, length bounds, version negotiation, command allowlists, idempotency journal, and no renderer-selected path.
- Authenticated application records plus a native credential-store key and a verified platform-encrypted library workspace: AES-256-GCM on desktop; per-record-key RNS Token sealing on mobile.
- Full logical-ID deduplication across native retransmission and delivery-method changes.
- Reactions use an exact generated allowlist of the 3,963 fully-qualified
  Unicode Emoji 18.0 sequences and one encrypted state record per authenticated
  actor and target. Independent 16-codepoint and 64-byte limits run before the
  membership lookup; malformed, component-only, unqualified, adjacent, and
  invented joiner/tag sequences fail closed. Monotonic revisions and inactive
  tombstones make duplicate and out-of-order updates idempotent; the actor
  comes only from the validated native LXMF source, not reaction metadata.
- Direct reactions require the approved target contact and re-derived pairwise
  conversation. Group reactions require both current active membership and
  membership in the target message's signed historical audience. New members
  do not receive old-message reactions, removed members cannot update them,
  and active announcement-channel readers may react without gaining posting
  authority.
- Reactions that overtake their target enter an encrypted pending queue capped
  at 256 total and 32 per actor. Expiry, manifest, membership, and historical
  audience checks are repeated before application. Opaque deleted-target
  markers prevent a late packet from recreating erased message state.
- Small private groups use one individually signed and ratchet-encrypted LXMF
  copy per active recipient. They do not use a shared `RNS.Destination.GROUP`
  key, a custom group cipher, or a required group server.
- Group invitations require explicit identity-signed acceptance. Canonical
  owner-signed manifests bind the permanent group identifier, title, posting
  policy, member identity cards and roles to a monotonic epoch and the previous
  manifest hash. Invalid, stale, skipped, forked, or unauthorized state fails
  closed.
- Workspace traffic is isolated under `mesh-chat-workspace`. Its only
  unknown-source exception is a signed join whose native source, public
  identity, derived destination, device card, single-use invitation, expiry and
  offered checkpoint all verify. Pending joins are capped at 32 per workspace
  and four per source fingerprint.
- Workspace manifests, channels and author streams are hash-linked. Every
  event is inner-signed and binds the exact authorization controls and immutable
  audience. Missing controls or predecessors enter a bounded encrypted inert
  queue; rollback, skipped authority, and sequence reuse fail closed.
- Administrative requests bind the exact base manifest, requester device,
  single target/effect, lifetime and replay key. Owner decisions bind the exact
  request digest and embedded invitation/manifest result. Canonical byte limits,
  per-source/workspace/profile caps, bounded inert decisions and sealed replay
  records contain parsing work and spam. A conflicting result is a security
  error; delivery or endpoint receipt is never approval.
- Review presents requester, requested action, target and current-state warning.
  Pending rows retain the effective role, removal needs confirmation, and only
  the authority device can commit the one-member manifest transition. A stolen
  administrator key can exercise existing policy and channel-manager powers but
  cannot change metadata, retention, policy, closure, authority or ownership.
  It gains no recovery or discovery of excluded private channels and no access
  to another pair's DM or history.
- Administrative state and bounded cursors are separately sealed behind opaque
  HMAC identifiers. SQLite observation may reveal generic kinds, ciphertext
  sizes/counts and timing, but not workspace/member names, targets, roles,
  destinations, invitation secrets or canonical request content. Startup and
  paging use the bounded sealed indexes rather than whole-kind scans.
- Public-channel manager records, accepted transfers, and owner recoveries form
  independent signed chains. A valid same-version conflict suspends only that
  channel. Signed directory summaries are paged and bounded; signed fetches
  return bounded predecessor-ordered controls. Subscription never reduces the
  public-channel delivery audience or grants authority.
- Private-channel manifests bind the complete sorted roster to every head and
  are delivered only to that roster. Private events repeat the exact signed
  audience, and a receiver requires the event head to remain on the current
  channel chain with both receiver and author still entitled. Admission sends
  only the current signed checkpoint; predecessor metadata and messages are
  not backfilled. Removal cancels the excluded member's unhanded delivery legs.
  A nonmember owner has no discovery or recovery override.
- Workspace DMs are authorized by the exact two active members in the signed
  manifest rather than by global Contact trust. Their deterministic
  workspace-scoped UUID, null channel digest, exact sorted audience, author
  membership, and current two-party activity all verify before persistence.
  Only participant devices receive event legs or local summaries. Local hide
  does not delete encrypted history, and a known participant removal makes the
  retained DM read-only and cancels unhanded legs.
- Workspace edits and deletion require a current active device of the original
  author member; reactions require a current active member who remains in the
  target's historical and current audience. Mutation target, conversation,
  base revision, next revision, manifest, channel head, and frozen audience are
  signature-bound. Channel posting policy is deliberately not reaction or DM
  authority. Deterministic candidate ordering makes delayed and concurrent
  delivery converge, inactive reaction records prevent resurrection, and an
  author deletion remains a presentation tombstone. Distinct content from one
  device at one revision freezes mutation of the whole message and surfaces a
  security warning instead of silently choosing arrival order.
- Structured workspace mentions are sorted active member UUIDs inside the
  signed message or edit already delivered to the authorized conversation
  audience. Private-channel and DM verification rejects mention targets outside
  that exact audience; raw `@name` text creates no metadata. Only the mentioned
  member creates sealed local inbox pages. Mention cursors bind current
  manifest/channel authorization and mute state, and every listing rechecks
  current local membership, private roster access, channel state, hides,
  tombstones, and the active edited mention position. Read high-waters, mute
  preferences, and draft mention IDs never leave the device.
- Workspace thread replies sign one retained ordinary root UUID and repeat the
  root conversation's exact public, private-roster, or two-participant DM
  boundary. Roots cannot themselves be replies. Reply mutations repeat the
  same root, use the existing deterministic resolution rules, and cannot widen
  the historical audience. Missing or reversed roots, replies, controls, and
  mutations remain inert in the bounded pending queue until their signed
  dependencies validate.
- Thread indexes, read high-waters, drafts, cursors, and the capped 1,024-root
  activity map are sealed local records. Each access rechecks the current
  workspace state, root hide/existence, channel state, private roster and
  admission version, or exact DM participants. A removal/re-admission gap does
  not restore an older private root. Startup thread badges and draft filtering
  use encrypted bounded metadata and do not open message bodies or scan event
  and delivery collections.
- Workspace record IDs and cursors are keyed opaque values. Message pages,
  mention pages, due-work shards, unread state, notification preferences,
  drafts, delivery legs and operation results are separately sealed. Startup
  summaries do not decrypt message or mention bodies. A stale authorization,
  preference, index or retention generation invalidates a cursor explicitly.
- The signed 30/90/365-day or indefinite retention value is cooperative. It
  governs only each endpoint's encrypted local copy and cannot erase plaintext,
  screenshots, exports, swap, or backups controlled by another endpoint.
  Pruning is bounded and restart-safe; author-deletion state waits for both the
  history boundary and the independent seven-day live-delivery window.
- Pruned event IDs and stream positions retain sealed digest/high-water/floor/
  gap markers. A delayed duplicate, reversed mutation, or ID reuse therefore
  cannot resurrect a body or turn unavailable history into an apparently
  complete range. Historical manifests and channel controls remain while a
  retained dependent can reference them.
- Retained and archived reads repeat historical-entitlement and current-access
  checks. A former member's existing local copy is read-only and receives no
  new catch-up or live leg. Private removal/re-admission does not bridge eras,
  and workspace owner status never grants access to a two-member DM.
- Workspace search uses sealed HMAC-keyed exact-token pages and bounded opaque
  document references. Queries never leave the device. A search index is only
  a hint: at most eight shard pages and 256 candidates are decrypted, then the
  canonical historical entitlement, current private/DM boundary, thread root,
  hide, deletion, and retention checks run again before a 50-result maximum is
  presented. Authenticated cursors contain opaque query/scope digests rather
  than raw text and bind authorization, retention, and search generations.
- SQLite observers can still learn generic search-record kinds, ciphertext
  sizes, counts, update timing, and repeated access patterns. They do not see
  plaintext queries, tokens, messages, person/channel names, or destinations
  in record IDs or cursor bodies without the local vault key. An unlocked
  endpoint holding that key remains outside this protection.
- History requests authenticate requester identity and native source before a
  scope-dependent lookup. Exact public/private/DM disclosure is checked again
  for every retained body, suppressing existence-dependent responses to an
  unauthorized probe. Fresh nonce/replay keys, a 15-minute maximum lifetime,
  request digest binding, previous-page digests, one-use source-bound
  continuations, count/byte/range ceilings, direct sequence probes and global
  job caps limit replay, substitution and amplification.
- A response is forwarding evidence, never authorship. Inner canonical
  signatures, controls, sequences, predecessors, revisions, audiences and
  ordinary derived-state checks remain authoritative. Inactive-author public
  or private chains additionally require an exact checkpoint committed by the
  applicable signed removal control; missing/conflicting/wrong-era anchors
  become permanent gaps. V1 refuses third-party inactive-author DM recovery.
- Sealed opaque job, replay, continuation, checkpoint, response-cache and peer
  coverage records expose generic ciphertext size/count/timing to a local
  SQLite observer, but not raw scope, names, event IDs, destinations or text.
  A signed peer head is not treated as possession or global completeness.
- A workspace mutation and its durable operation result commit together. A
  message and its complete recipient set commit before asynchronous handoff;
  native endpoint proof is not presented as human read evidence.
- New members receive no old history by default. Removal stops future
  recipient copies after the new epoch is learned, and delivery remains a set
  of independently verified per-member outcomes.
- Separate routing/storage opt-ins, explicit propagation peers, bounded transfer/storage settings, and no automatic public gateways.
- Emoji images are presentation-only: reaction identity remains the exact
  validated Unicode value in encrypted storage and LXMF traffic. A generated
  lookup can return only bundled sprite paths and fixed coordinates; neither a
  peer nor stored message can supply an image URL.
- The palette-optimized Twemoji 17.0.3 assets are pinned to commit
  `b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`. Source tests verify the manifest,
  every sprite size/hash, all 253 picker mappings, the 3,944 covered Emoji 18
  mappings, and the 19-entry named fallback partition. Load failure stays on a
  deterministic neutral `18` tile and does not trigger a remote fetch or alter
  the Unicode reaction value.
- Local-only UI assets, restrictive CSP, no CDN or artwork network request, no
  remote navigation, no HTML message rendering, no updater, telemetry, or
  crash upload. Twemoji's CC BY 4.0 attribution is visible in Settings and the
  bundled third-party notices.
- Reaction state and reaction-only outbox work are committed atomically. Newer
  revisions remove superseded jobs before best-effort native cancellation;
  endpoint evidence retires optional reaction deliveries and bounded receipt
  jobs. Thus older payload-v1 peers may reject reaction kinds without causing
  ordinary chats to fail or seven days of reaction retries.

## Authority-continuity threats

- Compromise of the current authority permits valid malicious offers and other
  owner actions. It does not permit silent transfer: the exact successor must
  countersign, and the final manifest remains auditable. A coerced successor or
  compromised named successor can accept; out-of-band fingerprint review and
  the explicit destructive confirmation reduce phishing but cannot prove free
  consent.
- Offers, acceptances and results bind workspace, transition, base manifest,
  both identities/destinations, consequences, nonce, replay key and expiry.
  Cross-workspace grafts, successor substitution, replay and a successor-only
  premature manifest fail closed. Native direct sender and inner signer must
  agree; an authorized forwarder never becomes an author.
- A certificate chain starts at pinned genesis and validates each old-authority
  offer, successor acceptance, final cutover and required `#general` result.
  Missing, reordered, duplicated, truncated or conflicting steps are rejected.
  The verifier never obtains private-channel or third-party DM data as part of
  bootstrap.
- After cutover, the old device remains only an admitted ordinary device of the
  outgoing member and cannot sign a later manifest. Partition-delayed peers may
  continue under the last verified epoch, but converge only through the complete
  proof. Two valid manifests for one epoch or authority equivocation suspend the
  workspace; timestamps, first arrival, routes, majorities and local preference
  never select a branch.
- Sealed HMAC-addressed transition, replay, delivery and certificate records
  limit SQLite leakage to generic kinds, ciphertext sizes/counts and timing.
  An unlocked compromised endpoint can read everything that endpoint is
  authorized to read and can correlate its own operations.
- Permanent loss of the current authority key is different from continuity.
  It freezes authority-dependent administration while ordinary authorized chat
  can continue. Replacement-workspace guidance does not clone keys, vote,
  recover automatically, select a fork, or import unverified state.

## Linked-device threats

- A device link is a bearer bootstrap, but possession alone is insufficient.
  The offer is signed by an exact active device, the fresh endpoint
  countersigns with a new identity, and the owner authority must publish the
  exact one-card manifest delta. Expiry, one-use identifiers and sealed replay
  records bound interception and reuse; a user can still mistakenly hand a
  valid link to the wrong physical desktop.
- Private identity bytes never cross the link. Compromise of one desktop does
  not reveal another desktop's key, but every admitted endpoint receives the
  member's future authorized channel and DM traffic. A compromised sponsor can
  propose a device and a compromised authority can approve it; fingerprint
  review and visible owner approval cannot repair two already compromised
  endpoints.
- Removal is learned state, not instantaneous global revocation. Until a
  partitioned peer receives the signed manifest it may accept traffic under the
  prior epoch. Once learned, both native-source admission and event validation
  reject newly seen traffic from the removed device. Previously received
  plaintext and signed history cannot be remotely erased.
- The sole authority device cannot be removed through the device-removal path.
  It must first complete the countersigned authority rotation. Permanent loss
  remains unrecoverable and never enables a vote, copied key or administrator
  override.
- Optional read hints are sent only to other devices of the same member and are
  applied only when the exact canonical event head and digest match. They are
  local convenience metadata, not social read receipts. Packet timing may
  still reveal that encrypted same-member control traffic occurred.

## Metadata that remains observable

Depending on configured interfaces, observers may learn local discovery presence, destination identifiers, IP endpoints, packet size/timing, and route activity. Propagation nodes necessarily retain encrypted objects plus routing/queue metadata. Pairwise group fan-out creates correlated timing and volume that may approximate group activity or size. Signed member cards may disclose up to two validated direct TCP hints to authorized group participants; they are transported inside recipient-encrypted group controls, not published in announces. Mesh Chat does not claim anonymity.

## Outside the guarantee

- Malware, administrative access, or memory inspection on an unlocked endpoint.
- Plaintext visible on screen, accessibility APIs, clipboard contents after a user copies an invite, or all operating-system swap/crash-dump behavior.
- Delivery when no usable path/copy exists, recovery after all copies expire or
  are lost, or cryptographic erasure from a member that already received a
  message. Author deletion is a convergent UI tombstone, not a promise to erase
  the original signed ciphertext from every endpoint or backup.
- Reaction convergence after every entitled endpoint has discarded all copies,
  or across peers that do not implement the additive reaction kinds. Endpoint
  receipt can retire a reaction job even when an older peer ignored the
  application payload.
- Detection of a malicious actor sending two different reaction values with
  the same revision. Receivers use the first authenticated value they observe;
  a later higher revision restores convergence.
- Pictorial artwork for the 19 Unicode Emoji 18 sequences newer than the pinned
  Twemoji release. They remain valid, named reactions and use the neutral `18`
  tile until suitable open artwork is available; Mesh Chat does not claim that
  tile conveys the emoji's visual meaning without its accessible name.
- Authenticating a person's real-world identity without an independent fingerprint comparison.
- Confidentiality from a currently authorized group member or from a device
  compromised while that member is authorized.
- Instantaneous group removal or closure during a network partition, automatic recovery
  after permanent owner-key loss, a globally ordered group timeline, public or
  large channels, discoverable groups, anonymous membership, selective history
  sharing, or safe multi-owner membership editing.
- Guaranteed complete peer history on a newly linked device, remote search,
  automatic authority recovery, and mobile workspace use. Catch-up can recover only exact
  authorized bodies still retained by reachable peers. A peer can withhold,
  prune, disappear, or lie about its head; the result is uncertainty or gaps,
  not a global completeness claim. Search queries remain strictly local.
- Immediate administrator demotion or removal across a partition, prevention of
  mistaken owner/successor approval, or recovery after permanent
  owner-authority loss. Peers enforce the newest complete verified state they
  have and suspend rather than choosing an authority fork.
- NAT hole punching, mobile push, Bluetooth, LoRa, attachments, multi-device identity cloning, and cloud backup.

## Mobile notification and lifecycle threats

- Lock screens and OS history may retain previews. The sealed hide-preview
  option replaces all names/text before native handoff, but cannot recall an
  already displayed item or control OS history, screenshots, backups,
  accessibility services, or a compromised endpoint.
- Message text is hostile preview input. Service and native layers bound it and
  reject controls, bidi/format/surrogate abuse, newlines, HTML, and executable
  links. Native logs contain only stage and exception class.
- Permission phishing is limited by explicit user action and a persistent
  requested-state hint. Denial does not re-prompt; settings recovery is a
  separate action and the OS remains authoritative.
- Android substitution is constrained to exact
  `meshchat://notification/<64 lowercase hex>` routes. The opaque ID loads a
  sealed scope and current authorization; raw routing IDs never enter intents.
- Opaque IDs reduce structural leakage but remain locally correlatable by the
  OS or a compromised endpoint. No telemetry exports them.
- OS background limits and process death can delay work indefinitely. Mesh Chat
  makes no prompt-delivery claim and requests no foreground-service or battery
  exemption.
- A crash after durable event commit leaves one deduped work item. Retry and
  restart reuse it; the ledger prevents amplification.
- Catch-up, rebuild, duplicate, replay, malformed, forked, hidden,
  unauthorized, and removed-device events cannot enqueue. This prevents
  history/resume storms and forwarding-peer preview injection before canonical
  validation.
- Suspend/resume races fail closed: controls precede dependent events, opens
  re-authorize, due work is idempotent, overflow reconciles, and a fork is
  never auto-selected.
- FCM, APNs remote delivery, hosted notification servers, background relays,
  and telemetry remain excluded because they add metadata authorities.

## Direct email setup and native transport boundary

The version-2 email document is untrusted until the protected service verifies
the original invitation and complete signed Offer/Answer/Ready chain. Preview
performs no network I/O. Explicit preparation may contact the local router and
bind a native UDP socket; connection uses only signed public candidates.
Portable documents reveal candidate addresses to their recipients and the chosen
email/file channel. Ordinary status and diagnostics exclude those addresses.
An empty-candidate reply grants no reachability or membership.

Native keys, socket handles and packet operations never enter the renderer command
table. Desktop inherited frames and Android's private pump use capped messages,
bounded pending work and timeouts. Android bootstrap IPC is a non-exported service
with same-UID checks in a separate process. A timeout or lost owner retires work;
persisted documents cannot resurrect sockets after restart or suspension.
Desktop bootstrap RNS state is created beneath the verified protected profile,
not the system temporary directory; Android uses its private app cache. Parent
supervision removes the temporary state after the child exits, including failure.

The bootstrap interpreter has one non-routing interface and one selected peer.
Only join, receipt, admission-root and fresh-binding controls are permitted.
Admission opens at most a 30-second control transition with current authority
rechecked; ordinary traffic requires fresh admitted credentials and a separately
leased main-context adapter. The bootstrap ratchet cannot authorize ordinary
messages in the main RNS context. Received LXMF controls are checked again in
the parent service for signature, source, destination, scope and kind.

QUIC certificates are pinned to signed bindings. Ownership checks tie advertised
UDP mappings to the socket/key retained for activation. Failed mapping, stale
candidates, lost sockets and incompatible address families fail explicitly.
Standard QUIC retries are bounded. No public STUN/TURN, rendezvous, IP observer,
custom probe or relay is added. Shared NAT, firewalls and mobile suspension can
still prevent progress. This phase supplies short-lived setup paths, not persistent
automatic recovery or background availability. See the
[Phase 2 evidence record](docs/DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md).

## Open security blockers

- Windows EFS has passed a native protected-workspace and packaged-sidecar run. The macOS FileVault and Linux fscrypt/dm-crypt adapters are implemented and fail closed, but still require native package, encrypted-volume, suspend/resume, and full-tree release-gate runs before those platform packages are labeled verified.
- Offline propagation, propagation-node redundancy, crash points inside upstream ratchet persistence, abuse limits, suspend/resume, and hostile-input fuzzing require release-gate runs described in [TESTING.md](TESTING.md).
- Increment 15 automation and APK inspection do not replace an authorized
  disposable-device permission, suspension, process-death, upgrade,
  lock-screen/history, memory, battery, intent/log/SQLite leakage, and
  removal-during-suspension run. iOS also needs macOS/Xcode, signing, and
  equivalent physical evidence.
- Private groups and announcement channels require the group-specific release
  gates in [TESTING.md](TESTING.md), including physical multi-device fan-out,
  membership partition/removal, crash recovery, manifest-fork, and plaintext
  scans, before they are suitable for sensitive operational use.
- The integration has not received independent review. Dependency review does not constitute an application audit.
- The 0.2.11 source assets have automated integrity and coverage checks, but
  the final Windows and Android packages still require extraction/asset/license
  inspection and recorded hashes. The exact Android APK has not completed a
  physical-device LAN, suspend/resume, camera, battery, or upgrade test. The
  iOS source path requires a Mac/Xcode build, multicast-enabled provisioning
  profile, signed device run, and App Store validation.

## Durable admitted relationship evidence

Current membership is reloaded within the atomic replay/relationship mutation;
failed encryption or commit cannot leave one record advanced. Existing replay
floors survive initialization of the new record. Invitation scopes are rejected.
Stored public certificates and remote candidates do not authorize resurrecting
a native session. Historical route evidence is generation-bound and distinct
from present peer liveness and application receipts. Phase 3 now implements
rotated-key recovery under the additional boundary below; qualification status is
recorded separately in the Phase 3 evidence document.


### Recovery before transport-key authentication

The recovery ALPN deliberately proves TLS key possession before RNS authorization.
At that stage it exposes only bounded peer-encrypted control material: no RNS
adapter, application plaintext, packet forwarding, early data or session resumption.
Rustls verifies TLS 1.3 CertificateVerify; the protected service then verifies the
RNS signature, actual certificate hash, audience, device scope, freshness and current
membership, and commits the replay floor before native approval. Exporter tokens
are private and connection-specific. A copied binding cannot authenticate another
TLS key. Hostile provisional peers can consume only bounded connection/stream/queue
time and must reauthenticate after ownership loss.

Durable candidate hints do not prove reachability or continued router ownership.
A crash can leave a router lease until expiry; stored cleanup records do not justify
blind deletion of a tuple now used by another process. Every renewed mapping must
match the exact still-owned UDP socket. Cancellation and vault failure prevent
export/promotion, and old authenticated paths survive failed replacements.

Direct recovery does not solve two unknown addresses or filtered networks. Those
states retain membership and queued work and expose a fresh connection-update
exchange. They do not enable a relay or helper. Physical mobile battery, lifecycle
and router behavior still require the Phase 2/5 qualification gates.
# Server-free traversal and diagnostic boundaries

The traversal increment retains up to four exact route sockets per attempt and
eight sockets per native host. Multiple routes share one native-only ephemeral
key under the same signed session; no private key is exported. Service-verified
candidates constrain outgoing checks. The endpoint's mutual TLS and exact peer
certificate check precede bootstrap traffic. Auxiliary simultaneous checks must
never deliver DATAGRAMs to RNS, and cancellation must retire every group socket.
Standard QUIC anti-amplification remains in effect; handshake-start pacing is not
a claim that individual retransmitted packet counts equal the start count.

Diagnostic exports use allowlisted enums and bounded numbers, never raw errors,
invitation documents, endpoint addresses or identity material. The protected
vault retains the last failure and at most 200 recent events for seven days;
renderer exports are capped at 64 KiB. Clear diagnostic history deletes only that
record. Offline reports identify missing service/component data rather than
substituting source-tree metadata. Nothing is uploaded automatically.

See [ADR 0019](docs/adr/0019-server-free-traversal.md); its independent review and
physical qualification are still distinct from controlled native test results.
