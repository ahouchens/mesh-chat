# Implementation plan

1. Prove the reference stack: pin compatible RNS/LXMF versions, inspect delivery and ratchet behavior, isolate every Reticulum profile, and build a real multi-process harness.
2. Build the reusable service: bounded framed IPC, signed invitations, identity/contact validation, encrypted transactional persistence, durable outbox/receipts, accurate status mapping, and native LXMF direct/propagated delivery.
3. Build the desktop slice: a narrow Tauri process/credential boundary and an accessible React onboarding, invitation, request, conversation, connection-help, and advanced-settings experience.
4. Harden and verify: parser/persistence/IPC/status/crash tests, real-peer smoke tests, local-only packaging, security documentation, and explicit platform or human-test gaps.
5. Add small private groups and announcement channels without changing the
   reference-stack boundary: owner-signed hash-linked membership epochs,
   explicit targeted consent, one ratchet-encrypted LXMF copy and receipt per
   recipient, no history backfill, and truthful partial-delivery states. Keep
   the eight-member cap until the group-specific gates in `TESTING.md` pass.

The project remains a security-sensitive prototype until the full topology, packaging, usability, and independent-review gates in `TESTING.md` are complete.
