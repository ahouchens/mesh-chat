# Reticulum-first connection specification

Status: design proposal for review. This document changes connection **policy
and UI**, not the signed invitation/join wire formats.

## 1. Goal

Make an existing Reticulum path the default and primary way two people connect,
for both:

- a 1:1 conversation (personal invitation → contact request → approval → chat);
- a workspace (workspace invitation → signed join request → owner approval →
  membership, receipt, and messages).

A direct Internet connection remains available as an explicit optimization, not
as the default gate that decides whether a person can connect.

The user-visible promise changes from:

> “Connect directly or fail.”

to:

> “Save the signed request and deliver it over Mesh. Improve to a direct path
> only if you want to and the network supports it.”

## 2. Current behavior

The service already has the durable primitives:

- `create_invitation(connection_mode=None)` produces a plain signed v1 personal
  invitation. The renderer’s `NewChatDialog` defaults to `participant` instead.
- `create_workspace_invitation_command(connection_mode=None)` produces a plain
  signed v1 workspace invitation. `WorkspaceInviteDialog` defaults to
  `guided`, which currently maps to `email`.
- `accept_invitation` saves the contact request and queues LXMF delivery.
- `submit_workspace_join` saves the workspace join request and queues delivery.
- `connection_help`, `connection_results`, `workspaceJoinStatus`, and LXMF
  delivery states already expose path, propagation, endpoint, approval, and
  receipt evidence.

The gap is that the UI defaults to direct hosting and presents a missing direct
path as a connection failure, even when the signed request is safely queued for
Reticulum delivery.

## 3. Definitions

- **Mesh route** — any currently usable Reticulum path to the destination:
  same-LAN, direct TCP, transport node, or an approved propagation/access point
  already configured on this device. A route may appear later; the request is
  durable.
- **Request saved** — the signed contact or workspace join request is committed
  locally and will retry over available routes until approval, expiry, or a
  terminal state.
- **Transport delivered** — the packet reached the recipient endpoint or an
  approved propagation node. This is not approval or a human read receipt.
- **Approved** — the owner approved the contact or workspace request. This is
  not a claim that a direct path exists.
- **Direct path** — an authenticated direct connection prepared by
  `DirectConnectionSetup` or a connection reply. It is optional.
- **Improve connection** — an explicit user action that tries a direct path
  while preserving the saved Mesh request.

## 4. Decisions

1. **Default mode is `mesh`** for new personal and workspace invitations.
2. `participant`, `email`, `nearby`, and `remote:<profile>` remain available
   under **Other connection options**. They are not removed.
3. A new personal invitation with mode `mesh` is plain v1. It creates no
   participant host, listener, firewall rule, or temporary access credential.
4. A new workspace invitation with mode `mesh` is plain v1. It creates no
   participant host or temporary access credential.
5. The direct wizard is not the first step for a normal invitation. It is
   reached by:
   - pasting a `mesh-direct:` document, or
   - explicitly choosing **Improve connection** / **Direct connection**.
6. The UI must not show a direct-path failure as a connection failure when a
   Mesh request is saved and retrying.
7. **Improve connection** never replaces, clears, or re-signs the saved request.
   It adds an optional path; the durable request remains authoritative.
8. No silent host, relay, access point, or propagation node is selected. The
   existing explicit-consent rules remain.
9. No protocol change is required for `mesh` mode. The signed v1 invitation,
   join request, approval, receipt, replay, and expiry paths remain unchanged.

## 5. Connection modes

| Mode | UI label | What it does | Default |
| --- | --- | --- | --- |
| `mesh` | **Over Mesh (recommended)** | Plain signed v1 invitation; save and queue over existing Reticulum paths | Personal and workspace |
| `nearby` | Same network only | Plain v1 with same-LAN preference; no Internet claim | Advanced |
| `participant` | Advanced: direct hosting | Temporary participant-hosted access credential | Advanced |
| `manual` | Advanced: manual forwarding | Participant hosting through a user-supplied external endpoint | Advanced |
| `email` | Email-assisted direct | Email-ready bootstrap + optional return reply | Advanced |
| `remote:<id>` | Approved access point | Explicitly selected, named access point | Advanced |

The `mesh` mode must not automatically fall back to `participant`, `email`, or
`remote`. If no route exists, the request waits and the UI says so.

## 6. Personal 1:1 flow

### 6.1 Create invitation

1. Open **Start a chat → Invite**.
2. The primary action is **Create Mesh invitation** (mode `mesh`).
3. The service calls `create_invitation(connection_mode=None)` and returns the
   plain v1 document.
4. The dialog shows:
   - “Signed invitation ready. Send it with any sharing tool.”
   - “The other person’s request will be saved and sent over Mesh. A route may
     take time; you can keep Mesh Chat open or reopen it later.”
   - No “Prepared — waiting for recipient verification” direct-hosting status.
5. Advanced options remain under **Other connection options**.

### 6.2 Accept invitation

1. The recipient imports the invitation.
2. Preview verifies signature, expiry, single-use, and identity.
3. The recipient chooses **Save and send request**.
4. The service commits the contact with `trust = awaiting_consent` and queues
   the signed contact request.
5. The UI shows a state-specific panel:
   - `queued` / `waiting_for_keys` / `sending`: “Request saved. Trying to reach
     the other device over Mesh.”
   - `stored_for_delivery`: “Request stored at an approved offline node.
     Delivery is not approval.”
   - `received_by_endpoint` / `delivered`: “Request reached the other device.
     Waiting for approval.”
   - approved: “Contact approved.”
6. The primary action is **Continue** (dismiss), not **Retry direct
   connection**.

### 6.3 Approve and chat

1. The owner sees the pending contact request with the exact fingerprint.
2. The owner approves or declines. The approval is a signed control.
3. Messages queue over LXMF and retry. Message status uses the existing
   transport/endpoint/receipt states.
4. **Improve connection** is available from the contact/conversation screen
   after a request is saved or approved. It opens the existing connection-reply /
   direct flow and never replaces the contact request.

## 7. Workspace flow

### 7.1 Create workspace invitation

1. Open **Workspace → Invite people**.
2. The primary action is **Create Mesh invitation** (mode `mesh`).
3. The service calls `create_workspace_invitation_command(connection_mode=None)`
   and returns the plain v1 `MESHWORKSPACE` document.
4. The dialog shows:
   - “Signed workspace invitation ready.”
   - “The join request will be saved and sent over Mesh. The owner approves it
     when it arrives. Keep the workspace open or reopen later.”
   - No participant-hosted “keep this owner device online” claim.
5. Advanced options remain under **Other connection options**.

### 7.2 Join workspace

1. The joiner imports the invitation in **Join a workspace**.
2. Preview verifies the genesis, manifest, authority, expiry, and saved-request
   state.
3. The joiner chooses **Save and send join request**.
4. `submit_workspace_join` commits the pending workspace and queues the signed
   join request.
5. The UI shows:
   - queued/sending: “Join request saved. Trying to reach the owner over Mesh.”
   - stored: “Join request stored at an approved offline node.”
   - received by endpoint: “Join request reached the owner. Waiting for
     approval.”
   - approved: “Workspace approved. Open it to continue.”
6. If the request is already saved, **Open saved workspace** / **Continue saved
   request** is primary. A different invitation still cannot replace the saved
   request.

### 7.3 Owner approval and receipt

1. The owner sees the pending workspace join request with its fingerprint.
2. The owner approves; the signed manifest and join receipt are published.
3. The joiner receives the receipt over Mesh, then the workspace becomes active.
4. Channels and messages use normal LXMF delivery. Offline propagation remains
   an explicit per-device approval.
5. **Improve connection** may be offered after the request is saved or the
   workspace is active. It opens the direct setup wizard and preserves the join
   request, delivery, receipt, and membership.

## 8. UI changes

### 8.1 Entry points

- **Start a chat** primary button: **Create Mesh invitation**.
- **Workspace → Invite people** primary button: **Create Mesh invitation**.
- **Join a workspace** and the workspace switcher **Join or connect** open the
  durable join dialog first.
- A pasted `mesh-direct:` document still opens `DirectConnectionSetup`
  directly.
- **Other connection options** contains direct hosting, email-assisted,
  same-network, and approved access points.

### 8.2 Status model

Introduce a shared renderer model, derived from existing service fields:

```ts
type ConnectionPath = "mesh" | "direct" | "none";
type ConnectionPhase =
  | "invitation_ready"
  | "request_saved"
  | "sending"
  | "stored"
  | "reached"
  | "approval_pending"
  | "approved"
  | "expired"
  | "failed";

type ConnectionStatus = {
  purpose: "personal" | "workspace";
  mode: "mesh" | "nearby" | "participant" | "manual" | "email" | "remote";
  phase: ConnectionPhase;
  path: ConnectionPath;
  propagation: "unused" | "approved_unavailable" | "stored";
  can_retry_mesh: boolean;
  can_improve: boolean;
  direct_available: boolean;
};
```

Phase mapping:

| Service evidence | Phase | User copy |
| --- | --- | --- |
| Invitation created | `invitation_ready` | “Signed invitation ready” |
| Local request committed, no route | `request_saved` | “Saved; will send when a Mesh route is available” |
| Delivery queued/sending | `sending` | “Trying to reach the other device over Mesh” |
| Stored at propagation node | `stored` | “Stored for delivery; this is not approval” |
| Endpoint received | `reached` | “Reached the other device; waiting for approval” |
| Owner approval pending | `approval_pending` | “Waiting for approval” |
| Approved / receipt verified | `approved` | “Approved” |
| Expired terminal request | `expired` | “Expired; the saved request is kept for review” |
| Permanent failure | `failed` | “Delivery failed; the saved request is kept” |

`direct_available` is advisory only. It must not turn a Mesh success into a
failure or block approval.

### 8.3 Improve connection

The secondary action appears on a saved/pending/approved contact or workspace:

- label: **Improve connection**;
- explanation: “Try a direct path for lower latency. Your saved Mesh request
  and approval are unchanged.”;
- opens the existing direct setup or connection-reply flow;
- on failure, returns to the Mesh status; it does not surface a generic
  connection failure;
- on success, shows both paths and lets the user prefer direct for this session.

## 9. Service/API changes

No wire-format changes. Add an explicit `mesh` mode and a path-status surface.

### 9.1 Connection mode

- Accept `connection_mode="mesh"` in:
  - `create_invitation` (alias for `None`, plain v1);
  - `create_workspace_invitation_command` (alias for `None`, plain v1).
- Reject unknown modes as today.
- Return `connection_mode: "mesh"` and `host_session_id: null` for mesh
  invitations.
- The renderer sends `connection_mode: "mesh"` explicitly for clarity.

### 9.2 Path/status surface

Add or extend a read-only command that returns the shared `ConnectionStatus` for
a contact or workspace:

- personal: extend `connection_help` with `phase`, `path`, `propagation`,
  `can_improve`, and the delivery state of the contact request;
- workspace: reuse `workspaceJoinStatus` fields and add the same normalized
  fields;
- no addresses, propagation identifiers beyond existing allowlists, or
  invitation text in diagnostics.

This is a renderer-facing summary only. It must not change delivery state.

### 9.3 No implicit direct fallback

`accept_invitation` and `submit_workspace_join` must not create a participant
host, access credential, listener, firewall rule, or direct setup in `mesh`
mode. If the user selects **Improve connection**, the existing direct code paths
run under their current consent rules.

## 10. Diagnostics and privacy

- Record the selected mode (`mesh`/advanced) and the observed phase/path.
- Record whether a propagation node stored the request, without its address.
- Keep `Copy diagnostics` free of addresses, invitation contents, fingerprints
  beyond existing allowlists, and message content.
- Do not label “stored,” “endpoint received,” or “approved” as connected.
- No automatic upload or telemetry.

## 11. Security invariants

1. The signed invitation, contact request, workspace join, approval, receipt,
   replay, single-use, and expiry rules are unchanged.
2. A saved request is never silently replaced by a different invitation or by
   **Improve connection**.
3. No silent direct host, relay, access point, or propagation node.
4. `mesh` mode does not add a third-party service. It uses the user’s existing
   Reticulum configuration.
5. Direct setup remains opt-in and its existing identity/signature checks remain.
6. The UI must not claim reachability, delivery, or approval without the
   corresponding service evidence.

## 12. Migration and compatibility

- Existing participant/email/direct invitations remain readable and keep their
  original flow.
- Existing saved pending requests remain valid; no clearing or replacement.
- Existing direct setup state remains available.
- New invitations created after the change default to `mesh`.
- No database migration is required beyond new optional status fields.
- The version should increment for the next test build, but no protocol version
  changes.

## 13. Acceptance criteria

1. A personal invitation created with default settings is plain v1, has no
   participant host/session, and previews successfully on another profile.
2. Accepting it saves a contact request and queues LXMF delivery without
   requiring a direct path.
3. The 1:1 UI shows saved/sending/stored/reached/approval phases and never
   reports a direct-path failure as the connection result.
4. A workspace invitation created with default settings is plain v1, has no
   participant host, and previews successfully.
5. Joining it saves the workspace request and queues delivery; owner approval
   and receipt still work; channels appear after approval.
6. The workspace UI shows the same delivery phases and preserves the saved
   request.
7. **Improve connection** opens the existing direct flow and does not replace or
   clear the contact/workspace request.
8. Existing participant, email, nearby, remote, and direct flows still work.
9. Backend tests cover `mesh` mode equivalence to `None`, no host creation,
   queued delivery, approval/receipt, and saved-request preservation.
10. Frontend tests cover default labels, advanced options, phase copy, and the
    absence of a direct failure banner for a queued Mesh request.
11. Android/Windows layout tests cover the new labels and buttons.
12. `Copy diagnostics` remains address- and invitation-free.

## 14. Out of scope

- Changing Reticulum/LXMF wire behavior or propagation-node protocol.
- Automatic direct fallback or automatic access-point selection.
- A relay/STUN/TURN service.
- Guaranteed delivery latency or online presence.
- Replacing the existing direct setup wizard.

## 15. Open questions

1. Should `mesh` be the only default, or should the app remember a per-contact
   preference for direct when the user chose **Improve connection**?
2. Should **Improve connection** be shown immediately after request save, or
   only after the request reaches the owner / is approved?
3. Should the plain v1 invitation include a short “Mesh route” explanation in
   the shared text, or keep the text minimal and explain it in the app?
4. Should stored-at-propagation-node be a visible warning for 1:1 requests, or
   only an advanced status?
