import type { Contact, ContactInvitation } from "./types";

export function ContactRequests({ invitations, approvals, waiting, busy, error, connectedPeers, onInvitation, onApproval }: {
  invitations: ContactInvitation[];
  approvals: Contact[];
  waiting: Contact[];
  busy: boolean;
  error: string;
  connectedPeers: string[];
  onInvitation: (invitation: ContactInvitation, accept: boolean) => void;
  onApproval: (contact: Contact, approve: boolean) => void;
}) {
  return <div className="form-stack contact-requests">
    <p className="muted">Review these whenever you’re ready. Closing this window keeps your requests here.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {invitations.length > 0 && <section aria-labelledby="contact-invitations-title">
      <h3 id="contact-invitations-title">Invitations to review</h3>
      {invitations.map((invitation) => {
        const expired = invitation.expired || invitation.expires_at * 1000 <= Date.now();
        const connected = invitation.native_connected || connectedPeers.includes(invitation.preview.destination_hash);
        return <article className="contact-request-item" key={invitation.id}>
          <h4>{invitation.preview.display_name}</h4>
          <p>Invited you to connect</p>
          <details><summary>Verify identity</summary><p className="contact-request-fingerprint">{invitation.preview.fingerprint}</p></details>
          {invitation.workspace && <p>Also requests to join <strong>{invitation.workspace.name}</strong> when you accept. The workspace owner must approve your join.</p>}
          <p className="muted">{expired ? "This invitation expired. Ask the other person for a new one." : connected ? "WebRTC is connected. Accept to send your contact request." : "The WebRTC connection is no longer active. You can accept now; reconnect with the other person to deliver your request."}</p>
          <div className="dialog-actions">
            <button className="button button--primary" disabled={busy || expired} onClick={() => onInvitation(invitation, true)}>{invitation.workspace ? "Accept contact and request to join" : "Accept contact"}</button>
            <button className="button button--secondary" disabled={busy} onClick={() => onInvitation(invitation, false)}>{expired ? "Dismiss" : "Decline"}</button>
          </div>
        </article>;
      })}
    </section>}
    {approvals.length > 0 && <section aria-labelledby="contact-approvals-title">
      <h3 id="contact-approvals-title">Requests to approve</h3>
      {approvals.map((contact) => <article className="contact-request-item" key={contact.id}>
        <h4>{contact.display_name}</h4><p>Wants to connect with you</p>
        <details><summary>Verify identity</summary><p className="contact-request-fingerprint">{contact.fingerprint}</p></details>
        <div className="dialog-actions"><button className="button button--primary" disabled={busy} onClick={() => onApproval(contact, true)}>Approve</button><button className="button button--secondary" disabled={busy} onClick={() => onApproval(contact, false)}>Decline</button></div>
      </article>)}
    </section>}
    {waiting.length > 0 && <section aria-labelledby="contact-waiting-title">
      <h3 id="contact-waiting-title">Waiting for approval</h3>
      {waiting.map((contact) => <article className="contact-request-item" key={contact.id}><h4>{contact.display_name}</h4><p>Your request is saved. Keep both devices connected so it can be delivered and approved.</p></article>)}
    </section>}
    {!invitations.length && !approvals.length && !waiting.length && <p>No contact requests right now.</p>}
  </div>;
}
