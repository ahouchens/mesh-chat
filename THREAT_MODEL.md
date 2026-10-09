# Threat model

## Security goals

- No required application infrastructure or hidden public mesh connection.
- Chat text and sensitive application metadata remain confidential to endpoints across transport and propagation devices.
- A contact identity cannot be silently substituted after approval or verification.
- Local contacts, group membership and controls, messages, drafts, outbox work, receipts, identity and ratchet state are not persisted as plaintext.
- Network acknowledgments never overstate recipient application persistence.
- Group membership and posting authority cannot be changed without a valid,
  hash-linked owner-signed membership epoch, and one member's receipt never
  overstates delivery to the whole group.
- Workspace membership, policy and closure cannot change without a valid,
  hash-linked authority manifest; events cannot escape the audience frozen by
  their referenced manifest and channel control.
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
- Workspace record IDs and cursors are keyed opaque values. Message pages,
  mention pages, due-work shards, unread state, notification preferences,
  drafts, delivery legs and operation results are separately sealed. Startup
  summaries do not decrypt message or mention bodies. A stale authorization,
  preference, index or retention generation invalidates a cursor explicitly.
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
- Workspace cooperative message-history backfill, threads, search
  exchange, private history catch-up, direct
  message history catch-up, linked devices, authority transfer, and mobile
  workspace use. Increment 7 exposes only history already present locally;
  public discovery
  does not imply complete historical messages, and newly admitted private
  members receive future events only.
- NAT hole punching, mobile push, Bluetooth, LoRa, attachments, multi-device identity cloning, and cloud backup.

## Open security blockers

- Windows EFS has passed a native protected-workspace and packaged-sidecar run. The macOS FileVault and Linux fscrypt/dm-crypt adapters are implemented and fail closed, but still require native package, encrypted-volume, suspend/resume, and full-tree release-gate runs before those platform packages are labeled verified.
- Offline propagation, propagation-node redundancy, crash points inside upstream ratchet persistence, abuse limits, suspend/resume, and hostile-input fuzzing require release-gate runs described in [TESTING.md](TESTING.md).
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
