// Last observations only: never query Core or retain public documents/handles.
export const SUBPHASES = new Set([
  "arguments", "offerer_create", "answerer_create", "identity_distinct",
  "offer_begin", "offer_code_wait", "answer_begin", "invitation_wait", "invitation_guard",
  "invitation_accept", "pending_request_wait", "request_approve", "offerer_relationship_wait",
  "answerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait", "transfer_wait",
  "transferred_cancel", "offerer_receipt", "answerer_receipt", "offerer_ready_recheck",
  "answerer_ready_recheck", "retirement",
]);
const STATES = new Set(["reserved", "offer_ready", "awaiting_approval", "transferred", "retiring", "retired"]);
export const ERROR_CODES = new Set(["invalid_request", "incompatible_version", "negotiation_required",
  "unsupported_operation", "unauthenticated", "forbidden", "not_found", "locked", "conflict",
  "idempotency_conflict", "idempotency_expired", "resync_required", "resource_exhausted", "rate_limited", "unavailable", "internal"]);
const ROLES = new Set(["offerer", "answerer"]);
const bound = value => Math.min(value, 256);

export function pairingDiagnostics() {
  let subphase = "arguments";
  const peers = {};
  function peer(role) {
    if (!ROLES.has(role)) throw new Error("invalid_diagnostic_role");
    return peers[role] ??= {};
  }
  return {
    enter(value) {
      if (!SUBPHASES.has(value)) throw new Error("invalid_diagnostic_subphase");
      subphase = value;
    },
    snapshot(role, value, expectedDestination) {
      if (!Array.isArray(value?.contacts) || !Array.isArray(value?.contact_invitations)) return;
      const contacts = value.contacts;
      const invitations = value.contact_invitations;
      const pending = contacts.filter(item => item.trust === "pending_request");
      const approved = contacts.filter(item => ["approved", "verified"].includes(item.trust));
      peer(role).last_snapshot = {
        contacts: bound(contacts.length), invitations: bound(invitations.length),
        pending_invitations: bound(invitations.filter(item => item.state === "pending").length),
        pending_requests: bound(pending.length), approved_contacts: bound(approved.length),
        matching_pending_request: Boolean(expectedDestination && pending.some(item => item.destination_hash === expectedDestination)),
        matching_approved_contact: Boolean(expectedDestination && approved.some(item => item.destination_hash === expectedDestination)),
        counts_capped: contacts.length > 256 || invitations.length > 256,
      };
    },
    pairing(role, value) {
      peer(role).last_pairing = {
        state: STATES.has(value?.state) ? value.state : "unknown",
        code_present: typeof value?.pairing_code === "string" && value.pairing_code.length > 0,
      };
    },
    connections(role, total, checked, ready) {
      peer(role).last_connections = {
        total: bound(total), checked: bound(checked), ready: bound(ready),
        counts_capped: total > 256 || checked > 256 || ready > 256,
      };
    },
    failure(deadlineExhausted = false) {
      return { subphase, deadline_exhausted: deadlineExhausted, peers: structuredClone(peers) };
    },
  };
}
