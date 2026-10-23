# Verified-contact workspace invitations

Status: implemented in 0.9.18.

## 1. Purpose

A workspace owner should not have to copy a `MESHWORKSPACE…` string into another
chat to invite someone they already know. The owner can select an approved or
verified Personal contact, send a normal single-use workspace invitation over
the existing direct contact route, and let the recipient review and join.

This is a **delivery shortcut**. It does not merge Personal trust with workspace
authority and it never adds a member automatically.

## 2. Invariants

1. **Contact trust is not workspace membership.** A verified contact is eligible
   to receive an invitation, not to be added.
2. **The invitation is the normal signed workspace invitation.** It is created
   by the owner authority, is single-use, expires, and is bound to the current
   offered manifest.
3. **The recipient explicitly reviews and accepts.** Receiving the prompt only
   stores a pending invitation; it does not create a join request.
4. **The join request is signed by the recipient device** and is approved by the
   owner or an eligible admin exactly as a pasted invitation.
5. **Membership changes only through the workspace manifest.** No contact path
   bypasses `workspace_join_request`, admission, or manifest verification.
6. **The sender must be an active approved/verified contact.** Unapproved,
   awaiting-consent, blocked, identity-changed, and unknown senders are ignored.
7. **Only the active workspace owner can send this invitation.** Admin invite
   delegation remains governed by the existing workspace policy.
8. **A device already active in the workspace is not re-invited.** The service
   rejects a contact whose destination is an active workspace device.

## 3. Flow

```text
Owner                         Service                         Recipient
  |                              |                                |
  | select verified contact      |                                |
  |----------------------------->|                                |
  |                              | create normal single-use invite|
  |                              | store invitation record        |
  |                              | send WORKSPACE_INVITE over     |
  |                              | the approved contact route     |
  |                              |------------------------------->|
  |                              |                                | verify contact trust
  |                              |                                | verify invitation signature
  |                              |                                | store pending prompt
  |                              |                                | show Review / Dismiss
  |                              |                                |
  |                              |<-------------------------------| Review workspace preview
  |                              |                                | explicit Join
  |                              |<-------------------------------| signed workspace join request
  | owner/admin approves join    |                                |
  |------------------------------>|                                |
  |                              | deliver signed manifest        |
  |                              |------------------------------->|
  |                              |                                | verify/apply manifest
```

## 4. Wire payload

- Message kind: `workspace_invite`
- App-protocol field: the signed invitation document in the existing
  `M_INVITATION` field.
- Text must be empty; this is a control message and is not rendered as a chat
  bubble.
- Maximum signed document size is the existing 16 KiB app-protocol invitation
  limit. A workspace invitation larger than that must use the copy/QR path. The
  limit is checked on both send and receive.
- The message is sent only to an approved or verified Personal contact using the
  ordinary direct LXMF path. No new relay, mailbox, or server is introduced.
- The recipient must be able to reach the sender's Reticulum destination; an
  active WebRTC DataChannel can carry the same packet when it is acting as a
  Reticulum interface.

## 5. Service API

### `invite_contact_to_workspace`

Request:

```json
{"workspace_id":"...", "contact_id":"...", "operation_id":"optional"}
```

Behavior:

1. Require an active workspace and the local owner role.
2. Require an approved or verified contact.
3. Reject a contact destination already active in the current manifest.
4. Create the normal signed workspace invitation (`connection_mode: contact`).
5. Queue one `workspace_invite` app message carrying the signed document.
6. Return the invitation, message ID, and initial message state.

The command does not wait for delivery and does not create a workspace join
request. Delivery failure leaves the invitation active until it expires or is
revoked.

### `dismiss_workspace_invitation_prompt`

Request:

```json
{"prompt_id":"..."}
```

Marks a received prompt dismissed. It does not revoke the underlying invitation
and does not affect the workspace.

## 6. Recipient state

Incoming prompts are stored as `workspace_contact_invite` records:

- prompt ID derived from the invitation nonce;
- workspace ID, name, description, owner fingerprint, member count, retention;
- expiry and raw signed invitation;
- sender contact ID and display name;
- pending/dismissed state.

The snapshot exposes only pending, unexpired prompts. Receiving the same
invitation again is idempotent. Receiving a different invitation creates a
different prompt. No prompt is created for an expired, malformed, unsigned, or
wrongly signed invitation.

Reviewing a prompt opens the existing workspace join dialog with the invitation
prefilled. The existing preview, consent, and join-signing path is unchanged. On
successful join submission, the prompt is dismissed.

## 7. UI

Workspace **Invite people** gains a **Verified contacts** section:

- lists approved/verified Personal contacts;
- excludes contacts whose destination is already an active workspace device;
- sends the invitation with one action;
- reports that the invitation was queued for the selected contact;
- explains that recipient review and owner/admin approval still apply.

The app shows a **Workspace invitation** banner for pending prompts with:

- sender, workspace name, and a review action;
- dismiss action;
- no automatic navigation or joining.

## 8. Failure handling

| Condition | Result |
|---|---|
| Contact awaiting consent/blocked/unknown | command rejected; no invitation sent |
| Contact is already an active workspace device | command rejected |
| Owner is not active / local role not owner | command rejected |
| Invitation document too large | validation error; use copy/QR |
| No route or message expiry | message remains queued/failed; invitation expires normally |
| Recipient invitation expired/tampered | prompt is not stored |
| Recipient dismisses prompt | prompt hidden; invitation remains valid until expiry |
| Recipient joins | existing signed join and approval flow |
| Workspace member removed later | existing removal and manifest rules apply |

## 9. Security and privacy

- The contact route already exposes message metadata to the same peers as a
  normal chat; this feature adds no server or operator.
- The signed invitation contains workspace genesis/manifest metadata, not
  message history. It reveals workspace name, description, owner fingerprint,
  member count, retention, and expiry to the selected contact—exactly what the
  existing invitation copy/QR path reveals.
- The sender cannot force membership. The joined device must still sign a join
  request and be approved.
- The recipient’s prompt is not a trust decision. It is a pending offer and is
  erased/marked dismissed without affecting contact trust.
- The app does not auto-approve a contact request, auto-accept a workspace
  invitation, or reuse a single-use invitation.

## 10. Acceptance criteria

- An owner can select a verified contact and send one signed invitation.
- The contact receives a prompt without a copy/paste step.
- The prompt preview matches the signed invitation and cannot be altered
  locally into membership.
- Join still produces the normal signed join request and owner/admin approval.
- A blocked/unapproved contact cannot be invited.
- An active workspace device cannot be invited again.
- Dismissing the prompt does not revoke or accept the invitation.
- Missing route/delivery failure does not add a member.
- Existing copy/QR/email/WebRTC invitation paths remain unchanged.

## 11. Tests

- App-protocol build/parse accepts `workspace_invite` only with a signed
  invitation and empty text.
- Invalid/oversized invitation fails closed.
- Owner invitation command requires owner role and approved/verified contact.
- Active-device contact is rejected.
- Recipient stores a pending prompt once and emits a receipt.
- Malformed/expired invitation creates no prompt.
- Dismiss hides the prompt without changing contact trust.
- Existing join request/manifest tests remain unchanged.
- Renderer test covers the verified-contact section and prompt banner.

Physical multi-device delivery remains part of the existing physical QA matrix.
