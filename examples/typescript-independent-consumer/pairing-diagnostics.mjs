// Bounded current observations; never retain public documents or handles.
export const SUBPHASES = new Set([
  "arguments", "offerer_create", "answerer_create", "identity_distinct",
  "offer_begin", "offer_code_wait", "answer_begin", "invitation_wait", "invitation_guard",
  "invitation_accept", "pending_request_wait", "request_approve", "offerer_relationship_wait",
  "answerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait", "transfer_wait",
  "transferred_cancel", "offerer_receipt", "answerer_receipt", "offerer_ready_recheck",
  "answerer_ready_recheck", "retirement",
  "second_client_attach", "client_detach_survivor", "client_reattach", "competing_owner_refusal",
  "offline_receiver_stop", "pending_enqueue", "pending_owner_stop", "pending_owner_reopen", "original_key_replay",
]);
const STATES = new Set(["reserved", "offer_ready", "awaiting_approval", "transferred", "retiring", "retired"]);
export const ERROR_CODES = new Set(["invalid_request", "incompatible_version", "negotiation_required",
  "unsupported_operation", "unauthenticated", "forbidden", "not_found", "locked", "conflict",
  "idempotency_conflict", "idempotency_expired", "resync_required", "resource_exhausted", "rate_limited", "unavailable", "internal"]);
const ROLES = new Set(["offerer", "answerer"]);
const SERVICE_ERRORS = new Set(["network_start_failed", "network_interface_unavailable"]);
const bound = value => Math.min(value, 256);
export const INVITATION_SAMPLE_OFFSETS_MS = Object.freeze([0, 1000, 5000, 20000, 90000]);
const INVITATION_SAMPLE_BUDGET_MS = 2000;
const INVITATION_WORK_RESERVE_MS = 100;
export const FAILURE_ORIGINS = new Set(["budget_deadline", "wait_deadline", "core_error", "cleanup_failure", "unknown"]);
export const ACTOR_ENUMS = {
  desired: new Set(["enabled", "stopped"]),
  execution: new Set(["available", "paused", "locked", "shutting_down"]),
  negotiation: new Set(["idle", "discover", "request", "wait_request", "wait_offer", "gather_offer",
    "gather_answer", "publish_offer", "publish_answer", "wait_answer", "apply_answer", "checking", "attach", "path", "inspect"]),
};
ACTOR_ENUMS.reason = new Set([...ACTOR_ENUMS.negotiation, "unknown", "ineligible", "ready", "pending",
  "health_unknown", "bridge_retry_wait", "blocked", "retry_wait", "network_unavailable", "signaling_unavailable",
  "carrier_lost", "phase_timeout", "transient", "rate_limited", "configuration", "invalid_document", "revoked",
  "unsupported", "internal", "invalid_adoption", "wrong_resource", "missing_observation", "invalid_pending",
  "unverified_resource", "missing_carrier", "context_changed", "observed", "poll_wait"]);
const record = value => value !== null && typeof value === "object" && !Array.isArray(value);

export function publicDiagnosticObservation(value, limit = 4) {
  // Current, unassociated actors: neither pairing identity nor first-cause history.
  if (!record(value) || typeof value.available !== "boolean" || !Array.isArray(value.connections)
      || ![1, 4].includes(limit) || value.connections.length > limit
      || !Number.isSafeInteger(value.total_connections) || value.total_connections < 0
      || value.connections.length !== Math.min(value.total_connections, limit) || typeof value.truncated !== "boolean"
      || value.truncated !== (value.total_connections > value.connections.length)
      || (value.runtime_failure !== null && typeof value.runtime_failure !== "string")
      || (!value.available && (value.total_connections !== 0 || value.runtime_failure !== null))) {
    return { query_outcome: "invalid_result" };
  }
  const connections = [];
  for (const row of value.connections) {
    if (!record(row) || !record(row.observation)) return { query_outcome: "invalid_result" };
    const selected = {};
    for (const [field, choices] of Object.entries(ACTOR_ENUMS)) {
      const item = row.observation[field];
      if (typeof item !== "string") return { query_outcome: "invalid_result" };
      selected[field] = choices.has(item) ? item : "unknown";
    }
    connections.push(selected);
  }
  return { query_outcome: "ok", available: value.available,
    runtime_failure: [null, "adapter_quarantined", "cleanup_failed"].includes(value.runtime_failure)
      ? value.runtime_failure : "unknown",
    total_connections: bound(value.total_connections), truncated: value.truncated, connections };
}

function pairingObservation(value, wallNow) {
  return STATES.has(value?.state) && Number.isFinite(value?.expires_at)
    ? {query_outcome: "ok", state: value.state, expired: value.expires_at <= wallNow() / 1000}
    : {query_outcome: "invalid_result"};
}

function compactActorObservation(value) {
  if (value.query_outcome !== "ok") return value;
  return {query_outcome: "ok", available: value.available, runtime_failure: value.runtime_failure,
    total_connections: value.total_connections, truncated: value.truncated,
    actor: value.total_connections === 1 ? value.connections[0] : null};
}

// At most two peers are queried concurrently; each peer's two public reads are sequential.
export function invitationWaitObserver(peers, diagnostics, wallNow = Date.now,
                                       monotonicNow = () => performance.now()) {
  if (peers.length !== 2 || new Set(peers.map(peer => peer.role)).size !== 2
      || peers.some(peer => !ROLES.has(peer.role))) throw new Error("invalid_observation_peers");
  const started = monotonicNow();
  let next = 0;
  let active = true;
  let inFlight;
  diagnostics.beginInvitationObservation();
  const failed = {pairing: {query_outcome: "failed"}, actor: {query_outcome: "failed"}};
  return {
    poll(invitations, workDeadline) {
      if (!active || inFlight) return;
      if (next >= INVITATION_SAMPLE_OFFSETS_MS.length) {
        diagnostics.invitationSamplesCapped();
        return;
      }
      const elapsed = Math.floor(monotonicNow() - started);
      if (elapsed < INVITATION_SAMPLE_OFFSETS_MS[next]
          || workDeadline - wallNow() <= INVITATION_SAMPLE_BUDGET_MS + INVITATION_WORK_RESERVE_MS) return;
      const marker = {offset_ms: Math.max(0, Math.min(elapsed, 600000)),
        pending_invitations: bound(invitations.filter(item => item.state === "pending").length),
        counts_capped: invitations.length > 256};
      next++;
      inFlight = marker;
      const sampleDeadline = monotonicNow() + INVITATION_SAMPLE_BUDGET_MS;
      const timeout = () => Math.floor(Math.min(sampleDeadline - monotonicNow(),
        workDeadline - wallNow() - INVITATION_WORK_RESERVE_MS));
      const observe = async peer => {
        let pairing = {query_outcome: "not_attempted"};
        let actor = {query_outcome: "not_attempted"};
        let remaining = timeout();
        if (active && remaining > 0) {
          try {
            pairing = pairingObservation(await peer.client.request("peer.pairing_query",
              {profile: peer.profile, pairing: peer.pairing}, {timeoutMs: remaining}), wallNow);
          } catch { pairing = {query_outcome: "failed"}; }
        }
        remaining = timeout();
        if (active && remaining > 0) {
          try {
            actor = compactActorObservation(publicDiagnosticObservation(await peer.client.request(
              "diagnostics.query", {profile: peer.profile, limit: 1}, {timeoutMs: remaining}), 1));
          } catch { actor = {query_outcome: "failed"}; }
        }
        return {pairing, actor};
      };
      void Promise.allSettled(peers.map(observe)).then(results => {
        if (!active || inFlight !== marker) return;
        const sample = {...marker, outcome: "complete"};
        peers.forEach((peer, index) => { sample[peer.role] = results[index].status === "fulfilled"
          ? results[index].value : failed; });
        diagnostics.invitationSample(sample);
        inFlight = undefined;
      }).catch(() => {
        if (!active || inFlight !== marker) return;
        try { diagnostics.invitationSample({...marker, outcome: "incomplete"}); } catch { /* Observation only. */ }
        inFlight = undefined;
      });
    },
    stop() {
      active = false;
      if (inFlight) {
        try { diagnostics.invitationSample({...inFlight, outcome: "incomplete"}); } catch { /* Observation only. */ }
        inFlight = undefined;
      }
    },
  };
}

export function pairingDiagnostics(monotonicNow = () => performance.now()) {
  let subphase = "arguments";
  let failureProbe;
  let publicDiagnostics;
  let failureOrigin = "unknown";
  let startedAt;
  let failureFrozen = false;
  const stageTiming = { offsets_ms: {}, clipped: false };
  let postAcceptReads;
  let invitationObservation;
  const peers = {};
  const cleanup = [];
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
      if (failureFrozen) return;
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
    beginInvitationObservation() {
      if (!failureFrozen && !invitationObservation) invitationObservation = {
        sample_budget: INVITATION_SAMPLE_OFFSETS_MS.length,
        sample_offsets_ms: [...INVITATION_SAMPLE_OFFSETS_MS], request_budget_ms: INVITATION_SAMPLE_BUDGET_MS,
        work_reserve_ms: INVITATION_WORK_RESERVE_MS, actor_limit: 1, samples: [], capped: false};
    },
    invitationSample(value) {
      if (!failureFrozen && invitationObservation && invitationObservation.samples.length < INVITATION_SAMPLE_OFFSETS_MS.length)
        invitationObservation.samples.push(structuredClone(value));
    },
    invitationSamplesCapped() { if (!failureFrozen && invitationObservation) invitationObservation.capped = true; },
    freezeFailure(origin = "unknown") {
      if (failureFrozen) return;
      if (!FAILURE_ORIGINS.has(origin)) throw new Error("invalid_failure_origin");
      mark("failure_observed");
      failureOrigin = origin;
      failureFrozen = true;
    },
    snapshot(role, value, expectedDestination) {
      if (failureFrozen) return;
      if (!Array.isArray(value?.contacts) || !Array.isArray(value?.contact_invitations)) return;
      const contacts = value.contacts;
      const invitations = value.contact_invitations;
      const pending = contacts.filter(item => item.trust === "pending_request");
      const approved = contacts.filter(item => ["approved", "verified"].includes(item.trust));
      const networkPresent = value.network !== null && typeof value.network === "object" && !Array.isArray(value.network);
      const validNetwork = value.network === null || networkPresent;
      peer(role).last_snapshot = {
        observed_subphase: subphase,
        network_present: networkPresent,
        service_error: validNetwork && (value.service_error === null || SERVICE_ERRORS.has(value.service_error))
          ? value.service_error : "unknown",
        contacts: bound(contacts.length), invitations: bound(invitations.length),
        pending_invitations: bound(invitations.filter(item => item.state === "pending").length),
        pending_requests: bound(pending.length), approved_contacts: bound(approved.length),
        matching_pending_request: Boolean(expectedDestination && pending.some(item => item.destination_hash === expectedDestination)),
        matching_approved_contact: Boolean(expectedDestination && approved.some(item => item.destination_hash === expectedDestination)),
        counts_capped: contacts.length > 256 || invitations.length > 256,
      };
    },
    pairing(role, value) {
      if (failureFrozen) return;
      peer(role).last_pairing = {
        state: STATES.has(value?.state) ? value.state : "unknown",
        code_present: typeof value?.pairing_code === "string" && value.pairing_code.length > 0,
      };
    },
    connections(role, total, checked, ready) {
      if (failureFrozen) return;
      peer(role).last_connections = {
        total: bound(total), checked: bound(checked), ready: bound(ready),
        counts_capped: total > 256 || checked > 256 || ready > 256,
      };
    },
    probe(value) { failureProbe = value; },
    publicProbe(value) { publicDiagnostics = value; },
    owned(role, incarnation) {
      if (!["offerer", "answerer", "contender"].includes(role) || !Number.isInteger(incarnation)
          || incarnation < 1 || incarnation > (role === "offerer" ? 2 : 1) || cleanup.length >= 4
          || cleanup.some(item => item.role === role && item.incarnation === incarnation)) throw new Error("invalid_cleanup_slot");
      const facts = { role, incarnation, attempts: 0, detach: "not_attempted", stop: "not_attempted", retired: false };
      cleanup.push(facts);
      return facts;
    },
    failure(deadlineExhausted = false) {
      return { subphase, deadline_exhausted: deadlineExhausted, failure_origin: failureOrigin,
        peers: structuredClone(peers), cleanup: structuredClone(cleanup),
        ...(startedAt !== undefined ? { stage_timing: structuredClone(stageTiming) } : {}),
        ...(postAcceptReads ? { post_accept_reads: structuredClone(postAcceptReads) } : {}),
        ...(invitationObservation ? { invitation_observation: structuredClone(invitationObservation) } : {}),
        ...(failureProbe !== undefined ? { failure_probe: structuredClone(failureProbe) } : {}),
        ...(publicDiagnostics !== undefined ? { public_diagnostics: structuredClone(publicDiagnostics) } : {}) };
    },
  };
}

export async function probePairingFailure(owned, diagnostics, monotonicNow = () => performance.now()) {
  const initialized = [];
  const roles = new Set();
  for (const peer of owned) {
    if (peer.retired || !ROLES.has(peer.role) || roles.has(peer.role) || !peer.client || !peer.profile || !peer.pairing) continue;
    initialized.push(peer);
    roles.add(peer.role);
    if (initialized.length === 2) break;
  }
  const probes = initialized.map(peer => ({peer, deadline: monotonicNow() + 2000}));
  const results = await Promise.allSettled(probes.map(async ({peer, deadline}) => {
    let pairing;
    try {
      const value = await peer.client.request("peer.pairing_query", {profile: peer.profile, pairing: peer.pairing}, {timeoutMs: 2000});
      pairing = STATES.has(value?.state) && Number.isFinite(value?.expires_at)
        ? {query_outcome: "ok", state: value.state, expired: value.expires_at <= Date.now() / 1000}
        : {query_outcome: "invalid_result"};
    } catch { pairing = {query_outcome: "failed"}; }
    const remaining = Math.floor(deadline - monotonicNow());
    let actors = {query_outcome: "not_attempted", reason: "deadline_exhausted"};
    if (Number.isSafeInteger(remaining) && remaining > 0 && remaining <= 2000) {
      try {
        actors = publicDiagnosticObservation(await peer.client.request("diagnostics.query",
          {profile: peer.profile, limit: 4}, {timeoutMs: remaining}));
      } catch { actors = {query_outcome: "failed"}; }
    }
    return {pairing, actors};
  }));
  diagnostics.probe(Object.fromEntries(initialized.map((peer, index) => [peer.role,
    results[index].status === "fulfilled" ? results[index].value.pairing : {query_outcome: "failed"}])));
  diagnostics.publicProbe(Object.fromEntries(initialized.map((peer, index) => [peer.role,
    results[index].status === "fulfilled" ? results[index].value.actors : {query_outcome: "failed"}])));
}
