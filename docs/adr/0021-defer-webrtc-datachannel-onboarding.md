# 0021: Defer the WebRTC DataChannel onboarding adapter

Status: superseded by ADR 0023 for the explicit C5 onboarding requirement. The
original deferral remains useful context for why no Reticulum-over-SCTP bridge
existed before 0.2.88.

## Context

The WebRTC specification originally proposed a DataChannel that carries
Reticulum/LXMF packets for onboarding. The intended problem was a first
connection when direct QUIC and other paths fail.

Two existing paths are better suited to onboarding:

- **TCP access point** — outbound TCP only, no local daemon, works on Windows
  and Android, and is already the supported remote-profile path.
- **I2P access point** — explicit consent and a local I2P router; useful when
  no public TCP endpoint exists.

The remaining DataChannel case is a browser client or a deployment that cannot
run either access point. Neither is a current requirement. Adding the adapter
would require a custom Reticulum interface, another framing/MTU layer,
additional consent UX, and a second traversal path while TCP access point
onboarding remains unqualified.

## Decision

1. Do not implement the WebRTC DataChannel onboarding adapter (C5) now.
2. Keep TCP access-point onboarding as the default, with direct/local and I2P
   as explicit alternatives.
3. Revisit C5 only if one of these is proven:
   - a browser client must join without a native access-point path;
   - a deployment cannot use a TCP access point or I2P;
   - a measured onboarding failure remains after both are available.
4. Calls remain the WebRTC priority. A future DataChannel must preserve the
   same signing, consent, identity, and membership rules.

## Consequences

- No Reticulum-over-SCTP code or packaging is added.
- The call surface and TCP onboarding can ship without a second traversal
  stack.
- C5 remains a documented, gated option rather than an implicit promise.
