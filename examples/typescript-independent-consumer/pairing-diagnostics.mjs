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

export function pairingDiagnostics(monotonicNow = () => performance.now()) {
  let subphase = "arguments";
  let failureProbe;
  let startedAt;
  let failureFrozen = false;
  const stageTiming = { offsets_ms: {}, clipped: false };
  let postAcceptReads;
  const peers = {};
  function mark(name) {
    if (startedAt === undefined || failureFrozen) return;
    const elapsed = Math.floor(monotonicNow() - startedAt);
    const clipped = Number.isFinite(elapsed) ? Math.max(0, Math.min(elapsed, 600000)) : 600000;
    stageTiming.clipped ||= clipped !== elapsed;
    stageTiming.offsets_ms[name] = clipped;
  }
  function count(name) {
    if (!postAcceptReads || failureFrozen) return;
    if (postAcceptReads[name] === 4096) postAcceptReads.clipped = true;
    else postAcceptReads[name]++;
  }
  function peer(role) {
    if (!ROLES.has(role)) throw new Error("invalid_diagnostic_role");
    return peers[role] ??= {};
  }
  return {
    start() { startedAt = monotonicNow(); },
    enter(value) {
      if (!SUBPHASES.has(value)) throw new Error("invalid_diagnostic_subphase");
      subphase = value;
      if (value === "invitation_accept") mark("invitation_accept_started");
    },
    acceptanceReturned() { mark("invitation_accept_returned"); },
    pendingWait(deadlineExhausted) {
      if (failureFrozen) return;
      mark("pending_request_wait_entered");
      postAcceptReads = { attempts: 0, completed: 0, clipped: false, deadline_exhausted_at_entry: deadlineExhausted };
    },
    pendingAttempt() { count("attempts"); },
    pendingComplete() { count("completed"); },
    freezeFailure() {
      mark("failure_observed");
      failureFrozen = true;
    },
    snapshot(role, value, expectedDestination) {
      if (!Array.isArray(value?.contacts) || !Array.isArray(value?.contact_invitations)) return;
      const contacts = value.contacts;
      const invitations = value.contact_invitations;
      const pending = contacts.filter(item => item.trust === "pending_request");
      const approved = contacts.filter(item => ["approved", "verified"].includes(item.trust));
      peer(role).last_snapshot = {
        observed_subphase: subphase,
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
    probe(value) { failureProbe = value; },
    failure(deadlineExhausted = false) {
      return { subphase, deadline_exhausted: deadlineExhausted, peers: structuredClone(peers),
        ...(startedAt !== undefined ? { stage_timing: structuredClone(stageTiming) } : {}),
        ...(postAcceptReads ? { post_accept_reads: structuredClone(postAcceptReads) } : {}),
        ...(failureProbe !== undefined ? { failure_probe: structuredClone(failureProbe) } : {}) };
    },
  };
}

export async function probePairingFailure(owned, diagnostics) {
  const initialized = [];
  const roles = new Set();
  for (const peer of owned) {
    if (!ROLES.has(peer.role) || roles.has(peer.role) || !peer.client || !peer.profile || !peer.pairing) continue;
    initialized.push(peer);
    roles.add(peer.role);
    if (initialized.length === 2) break;
  }
  const results = await Promise.allSettled(initialized.map(async peer => {
    const value = await peer.client.request("peer.pairing_query", {profile: peer.profile, pairing: peer.pairing}, {timeoutMs: 2000});
    if (!STATES.has(value?.state) || !Number.isFinite(value?.expires_at)) return {query_outcome: "invalid_result"};
    return {query_outcome: "ok", state: value.state, expired: value.expires_at <= Date.now() / 1000};
  }));
  diagnostics.probe(Object.fromEntries(initialized.map((peer, index) => [peer.role,
    results[index].status === "fulfilled" ? results[index].value : {query_outcome: "failed"}])));
}
