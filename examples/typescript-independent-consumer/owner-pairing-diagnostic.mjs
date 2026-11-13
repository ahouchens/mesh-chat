// Trusted owner's one-shot observation; never a public Core capability or success proof.
const phases = new Set(["discover", "wait_offer", "gather_offer", "gather_answer", "publish_offer",
  "publish_answer", "wait_answer", "apply_answer", "checking", "unknown"]);
const events = new Set(["tick", "failed", "result", "adopted", "context_changed", "handoff_rejected", "unknown"]);
const reasons = new Set(["transient", "rate_limited", "configuration", "invalid_document", "revoked",
  "unsupported", "internal", "phase_timeout", "ineligible", "context_changed", "network_unavailable",
  "wrong_resource", "invalid_adoption", "invalid_handoff", "invalid_pending", "unverified_resource",
  "missing_handoff", "handoff_rejected", "unknown"]);
const states = new Set(["reserved", "offer_ready", "awaiting_approval", "transferred", "retiring", "retired"]);
const fields = (value, names) => value !== null && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join() === names.split(",").sort().join();

export function ownerPairingObservation(value) {
  if (!fields(value, "status,total_intents,intents") || !["observed", "unavailable"].includes(value.status)
      || !Number.isSafeInteger(value.total_intents) || value.total_intents < 0 || value.total_intents > 32
      || !Array.isArray(value.intents)) throw new Error("invalid_owner_diagnostic");
  if (value.status === "unavailable") {
    if (value.intents.length !== 0) throw new Error("invalid_owner_diagnostic");
    return {status:"unavailable",total_intents:value.total_intents,intents:[]};
  }
  if (value.total_intents !== 1 || value.intents.length !== 1) throw new Error("invalid_owner_diagnostic");
  const intent = value.intents[0];
  if (!fields(intent, "role,state,retirement") || !["offer", "answer"].includes(intent.role)
      || !states.has(intent.state)) throw new Error("invalid_owner_diagnostic");
  let retirement = null;
  if (intent.retirement !== null) {
    const cause = intent.retirement;
    if (!["retired", "retiring"].includes(intent.state) || !fields(cause, "phase,event,reason")
        || !phases.has(cause.phase) || !events.has(cause.event) || !reasons.has(cause.reason)) {
      throw new Error("invalid_owner_diagnostic");
    }
    retirement = {phase:cause.phase,event:cause.event,reason:cause.reason};
  }
  return {status:"observed",total_intents:1,intents:[{role:intent.role,state:intent.state,retirement}]};
}

export async function readOwnerPairingDiagnostic(peer) {
  let result;
  try { result = await peer.runtime.pairingDiagnostic(2000); }
  catch { return {outcome:"not_received"}; }
  try {
    if (result?.outcome === "received") {
      const observation = ownerPairingObservation(result.observation);
      if (observation.status === "observed"
          && observation.intents[0].role !== (peer.role === "offerer" ? "offer" : "answer")) {
        return {outcome:"invalid_result"};
      }
      return {outcome:"received",observation};
    }
    return {outcome:result?.outcome === "invalid_result" ? "invalid_result" : "not_received"};
  } catch { return {outcome:"invalid_result"}; }
}

export function collectOwnerPairingDiagnostics(owned) {
  const peers = owned.filter(peer => ["offerer", "answerer"].includes(peer.role)
    && peer.incarnation === 1 && peer.pairing && peer.runtime);
  if (peers.length > 2 || new Set(peers.map(peer => peer.role)).size !== peers.length) {
    throw new Error("invalid_owner_diagnostic_peers");
  }
  // Only the snapshot frozen before client detach is eligible; never read a late frame here.
  const results = peers.map(peer => [peer.role, peer.ownerDiagnostic ?? {outcome:"not_received"}]);
  return {scope:"trusted_owner_before_cleanup",budget_ms:2000,peers:Object.fromEntries(results)};
}
