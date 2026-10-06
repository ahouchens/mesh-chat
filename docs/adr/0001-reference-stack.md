# ADR 0001: Use the reference Reticulum and LXMF stack

Status: accepted.

RNS 1.5.5 and LXMF 1.2.0 are pinned as a compatible pair. Reticulum owns paths, interfaces, Links and transport; LXMF owns message serialization, direct delivery and propagation. Mesh Chat does not add libp2p, a custom handshake, a routing envelope, or a replacement cryptographic primitive.

The application adds only consent, signed invitations, authenticated payload metadata, durable logical state and receipts. Missing upstream capabilities are integration blockers, not permission to invent a competing network stack.

