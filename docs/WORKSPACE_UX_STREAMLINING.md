# Workspace UX streamlining

Status: implemented in 0.9.19; defect fixes in 0.9.20.

## 1. Pending-joins inbox

The workspace sidebar now has a **Pending joins** action with a count across all
known join requests. It opens a review dialog containing:

- workspace name;
- applicant display name and short member ID;
- device fingerprint and destination;
- a role selector for owners;
- approve and decline actions.

The foreground join-request dialog also offers **Member** or **Administrator**
before approval. The admission is always a protocol-compatible member
manifest; when the owner selects Administrator, Mesh Chat immediately follows it
with a second owner-signed role-change manifest. This keeps pre-existing clients
compatible instead of introducing an admin-admission manifest they would reject.

Admission-grant admins cannot choose **Administrator**. They can only admit
members, and the role-change command remains owner-only, so a grant cannot
become a privilege-escalation path.

If the second role manifest fails, the member remains admitted as a member and
the UI reports that the administrator role change failed. This partial outcome
is explicit rather than being presented as a successful admin admission.

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

The owner's workspace view now shows a dismissible setup card above the selected
conversation:

1. Create the first channel.
2. Invite the first member.
3. Review member connectivity.

Each step links to the relevant existing action. Completion is derived from
current channel/member state; the connectivity step is marked locally when the
owner opens People. The checklist can be dismissed per workspace.

This is intentionally an inline workspace card, not another modal.

## Remaining follow-ups

- cross-workspace notification badges outside an open workspace;
- bulk approval for multiple join requests;
- persistent, server-side recording of the connectivity review step;
- per-invitation delivery history rather than the current live message state;
- accessibility pass over the new card grid and dialog controls.

Physical multi-device verification remains in the existing QA matrix.

## 0.9.20 defect fixes

- Administrator-at-approval is a protocol-compatible two-step transition: a normal member admission manifest followed immediately by an owner-signed role-change manifest. The member protocol never receives an admin admission it would reject.
- Pending join requests are exposed only to workspace owners and admins, not ordinary members.
- Contact invitation prompts are capped and expired/dismissed prompts are pruned.
- Contact invitations no longer reuse a caller operation ID across recipients; each send creates a fresh invitation.
- Invitation mode is persisted on the invitation record for the active-invitations list.
- The setup checklist safely handles unavailable local storage and is keyed per workspace.
- A full workspace now cannot issue another contact invitation.
