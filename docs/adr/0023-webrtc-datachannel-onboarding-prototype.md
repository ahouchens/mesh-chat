# 0023: Begin C5 WebRTC DataChannel onboarding

Status: prototype started. Supersedes the blanket deferral in ADR 0021 for the
specific onboarding requirement requested by the product owner.

## Decision

1. Build a WebRTC DataChannel onboarding path alongside the existing TCP access
   point, LAN, and I2P invitation paths.
2. The first deliverable is a prototype that carries a signed invitation and a
   separately signed reply over a DataChannel, verified by both peers.
3. Do not expose the DataChannel path in the shipping UI until it can carry the
   application's Reticulum/LXMF packets or otherwise complete the existing
   workspace/contact admission flow with the same replay, consent, and
   membership semantics.
4. TCP access point remains the default onboarding path. Google STUN is the
   default ICE helper for calls, not a TURN relay.
5. A self-hosted coturn deployment is provided under `deploy/turn`; no public
   TURN endpoint or shared credential is shipped.

## Current prototype

`experiments/webrtc-call/datachannel_onboarding.py` proves:

- host-candidate DataChannel establishment;
- a signed personal invitation from owner to joiner;
- verification of the owner destination;
- a separately signed reply from joiner to owner;
- verification of the reply destination.

It does not yet bridge DataChannel bytes into the Python Reticulum interface or
expose an onboarding UI. That bridge is the next C5 increment.

## Consequences

- C5 is active again, but only as a prototype until the Reticulum bridge and
  admission flow exist.
- The shipping invitation flow is unchanged.
- The TURN deployment remains operator-controlled.
