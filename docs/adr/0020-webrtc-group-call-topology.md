# 0020: WebRTC group-call topology

Status: proposed for the WebRTC call roadmap (C6). No group-call code is
implemented.

## Context

Mesh Chat already has 1:1 call signaling and a WebView media path. Workspace
calls are a later product question. The workspace limit is eight active people.
Two topologies are possible:

- **Full mesh:** every participant sends media directly to every other
  participant.
- **SFU:** a selective forwarding unit receives each stream and forwards it to
  the others.

A full mesh keeps media peer-to-peer and requires no media server, but upload
bandwidth and CPU grow with the square of the participant count. An SFU scales
better but is a third party, usually terminates DTLS/SRTP, and needs an
insertable-stream/MLS-style E2EE layer to avoid exposing plaintext media.

## Decision

1. Do not implement workspace/group calls before 1:1 audio and video pass their
   physical-device gates.
2. If group calls are added, start with **full mesh for 2–3 participants**,
   behind an explicit “Group call (experimental)” consent.
3. Do not add an SFU unless a concrete workspace requirement cannot be met by
   mesh and a privacy review approves an E2EE media design.
4. If an SFU is used, it must not receive plaintext media, must be separately
   consented to, and must never be required for 1:1 calls or messaging.
5. Workspace membership and call participation are separate: a call never
   changes membership, approval, or message delivery.

## Consequences

- Small workspace calls can remain server-free and peer-to-peer.
- Larger calls are explicitly unsupported rather than silently degraded.
- A future SFU remains an optional, separately reviewed project.
- The 1:1 call path stays the priority; group-call work does not block it.
