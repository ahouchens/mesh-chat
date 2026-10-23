# Workspace UX streamlining

Status: implemented in 0.9.19.

## 1. Pending-joins inbox

The workspace sidebar now has a **Pending joins** action with a count across all
known join requests. It opens a review dialog containing:

- workspace name;
- applicant display name and short member ID;
- device fingerprint and destination;
- a role selector for owners;
- approve and decline actions.

The foreground join-request dialog also offers **Member** or **Administrator**
before approval. The role is applied in the signed admission manifest, so it is
not a second, unsigned local edit.

Admission-grant admins can only admit **members**. The backend rejects an
administrator role from a delegated admission, preventing a grant from becoming
a privilege-escalation path.

## 2. Explicit invitation chooser and delivery status

Workspace invitations no longer hide their path behind a single **Guided
connection** selector. The visible chooser offers:

- Automatic fallback (email-ready);
- Same network;
- Direct Internet;
- Email-assisted;
- WebRTC / TURN;
- I2P access point;
- Approved access point when one is configured.

The WebRTC card opens onboarding when no DataChannel is active. TURN remains
clearly described as a WebRTC relay, not a direct-hosting solution.

Active invitations now show:

- the connection mode;
- the verified-contact recipient, when applicable;
- the current delivery state and failure code;
- expiry;
- revoke.

Contact-mode invitations do not offer the direct-setup **Continue setup**
action, because they have no participant host.

## 3. Workspace setup checklist

The owner's empty-workspace view now shows a dismissible setup checklist:

1. Create the first channel.
2. Invite the first member.
3. Review member connectivity.

Each step links to the relevant existing action. Completion is derived from
current channel/member state; the connectivity step is marked locally when the
owner opens People. The checklist can be dismissed per workspace.

This is intentionally an inline empty-state card, not another modal.

## Remaining follow-ups

- cross-workspace notification badges outside an open workspace;
- bulk approval for multiple join requests;
- persistent, server-side recording of the connectivity review step;
- per-invitation delivery history rather than the current live message state;
- accessibility pass over the new card grid and dialog controls.

Physical multi-device verification remains in the existing QA matrix.
