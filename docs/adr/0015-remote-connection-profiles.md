# ADR 0015: Opt-in remote connection profiles

Status: accepted for desktop and Android

## Decision

MeshChat can store up to four explicitly approved Remote Connection Profiles in the encrypted service vault. A profile contains a normalized label, one or two operator-supplied public Reticulum TCP endpoints, an optional recommended LXMF propagation destination, bounded capabilities and dates, a stable SHA-256 identifier over its canonical content, consent and retry state, and reference-counted contact/workspace scopes.

Remote transport uses standard Reticulum `TCPClientInterface` instances. Both NATed clients make outbound connections to the same operator-supplied TCP transport node. The shared interface uses normal route gravity (`0`); it is separate from signed direct-peer hints and never receives their elevated route preference. Nearby discovery and signed direct local routes remain enabled and preferred when Reticulum selects them.

Optional offline delivery uses standard LXMF propagation. Import never approves a recommended propagation node. A second consent adds it to the bounded allowlist; automatic propagation peering remains disabled. Stored ciphertext is not an endpoint receipt or a human-read receipt. Recipient ratchets remain mandatory for direct and propagated packing, and MeshChat never falls back to base-key encryption.

Participant-hosted direct operation, defined by ADR 0016, is now the invitation default and does not require a remote access point. Nearby/private-network v1 remains explicit. The inviter or workspace-owner device remains online until the recipient reaches it and approval completes. Selecting an approved Remote Connection Profile is a deliberate per-invitation opt-in. Remote-profile operation requires an operator-supplied access point. This change does not provide a managed public MeshChat gateway; the first supported deployment is self-hosted or manually supplied.

## Invitations and consent

Existing `MESHCHAT1` and `MESHWORKSPACE1` bytes are unchanged. `MESHCHAT2` and `MESHWORKSPACE2` are signed outer envelopes containing the complete verified v1 invitation, its SHA-256 digest, the complete canonical profile, purpose, wrapper dates, signer destination, and signature. Verification cross-checks the outer signer with the personal identity or current workspace authority.

Parsing and preview are local-only. They perform no DNS lookup and attach no interface. Literal non-public addresses and local-only hostname suffixes are rejected during import. After explicit approval, MeshChat persists consent before activation, resolves every hostname, rejects the whole endpoint if any answer is private, loopback, link-local, multicast, unspecified, documentation, benchmarking, or reserved, and gives Reticulum a validated numeric address rather than the hostname. This prevents a second unvalidated lookup from creating a DNS-rebinding path. A separately labeled advanced manual flow can approve private endpoints with a warning.

Importing a workspace invitation scopes the profile to that workspace and does not create global Contact trust. Scope release is reference-counted so deleting one contact or workspace cannot detach a profile still used elsewhere.

## Availability and metadata

The initial first-contact exchange can require both applications to remain running until Reticulum announces and recipient ratchets have been learned. Android suspension or process death can delay delivery until MeshChat is reopened. Background execution is best effort and is never described as push delivery.

An access-point operator can observe source IP addresses, timing, packet sizes, connection duration, and Reticulum routing identifiers. It cannot decrypt or forge valid MeshChat identities, contact decisions, workspace authority documents, messages, or application receipts. A gateway is not an identity, membership authority, receipt, or source of message validity.

## Compatibility and bounds

- v1 personal and workspace invitations remain accepted for nearby/private-network use. The default Internet choice generates participant-hosted v3 when a public path can be prepared. Creating v2 requires explicit selection of an approved profile; merely configuring a profile never changes the invitation default.
- v2 is additive and fails closed on unknown versions, purposes, fields, sizes, dates, signer mismatch, digest mismatch, or signature failure.
- Limits are four active profiles, two TCP endpoints per profile, one propagation recommendation, a 64-character label, 253-character hosts, 1–65535 ports, a 4 KiB canonical profile, a 90-day maximum profile lifetime, and bounded scope/retry records.
- Desktop and Android use the same Python protocol, vault records, Reticulum identity, command surface, and delivery semantics. Android runs the clients inside the embedded native messaging runtime, not the WebView.
- iOS is unchanged and explicitly out of scope for this increment.

## Consequences

Profiles survive restart, retry with bounded exponential backoff and jitter, re-resolve after foreground/network recovery, fail over between the two configured endpoints, reannounce after a remote interface becomes usable, and request relevant scoped paths. The durable outbox remains route-independent and can fall back to ordinary Reticulum routing.

The implementation uses only the pinned RNS 1.5.5 and LXMF 1.2.0 stack. No custom cryptography, handshake, signaling channel, account, key directory, workspace server, push service, or hosted control API is introduced.
