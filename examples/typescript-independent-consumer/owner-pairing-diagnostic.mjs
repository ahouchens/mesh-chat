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

function gatherFailure(intent, retirement) {
  const value = intent.gather_failure;
  const offer = intent.role === "offer";
  const answer = intent.role === "answer";
  if ((!offer && !answer) || !["retiring", "retired"].includes(intent.state)
      || retirement?.phase !== (offer ? "gather_offer" : "gather_answer")) {
    throw new Error("invalid_owner_diagnostic");
  }
  const failed = retirement.event === "failed" && retirement.reason === "invalid_document";
  const deadline = retirement.event === "tick" && retirement.reason === "phase_timeout";
  const common = "as_of,worker,stage,stage_state,last_completed,queue_age,stage_age";
  if ((!failed && !deadline) || !fields(value, common + (failed ? ",exception_kind,native_code" : ""))
      || value.as_of !== (failed ? "failed_result" : "phase_deadline")
      || !["queued", "started", "completed", "unknown"].includes(value.worker)
      || !(offer ? ["not_started", "ice_config", "native_offer", "offer_sign", "complete", "unknown"]
        : ["not_started", "ice_config", "native_accept", "answer_sign", "bind_onboarding", "complete", "unknown"])
        .includes(value.stage)
      || !["entered", "completed", "unknown"].includes(value.stage_state)
      || !(offer ? ["none", "ice_config", "native_offer", "offer_sign", "unknown"]
        : ["none", "ice_config", "native_accept", "answer_sign", "bind_onboarding", "unknown"])
        .includes(value.last_completed)
      || ![value.queue_age, value.stage_age].every(age =>
        ["lt1s", "1to5s", "5to20s", "20to25s", "gte25s", "unknown"].includes(age))) {
    throw new Error("invalid_owner_diagnostic");
  }
  const result = {as_of:value.as_of,worker:value.worker,stage:value.stage,stage_state:value.stage_state,
    last_completed:value.last_completed,queue_age:value.queue_age,stage_age:value.stage_age};
  if (failed) {
    const codes = ["answer_failed", "network_monitor_failed", "session_closed", "disposal_timeout",
      "no_candidates", "missing_data_channel", "sdp_failed", "unknown"];
    const valid = value.exception_kind === "native_unavailable" ? codes.includes(value.native_code)
      : ["identity_mismatch", "validation_error"].includes(value.exception_kind) ? value.native_code === "not_applicable"
      : value.exception_kind === "unknown" && value.native_code === "unknown";
    if (!valid) throw new Error("invalid_owner_diagnostic");
    result.exception_kind = value.exception_kind;
    result.native_code = value.native_code;
  }
  return result;
}

function checkingObservation(intent, retirement) {
  const value = intent.checking_observation;
  if (!["retiring", "retired"].includes(intent.state)
      || retirement?.phase !== "checking" || retirement?.event !== "tick"
      || retirement?.reason !== "phase_timeout"
      || !fields(value, "as_of,resource,profile,ice,channel")
      || value.as_of !== "last_checking_poll"
      || !["current", "missing"].includes(value.resource)
      || !["not_checked", "unbound", "unavailable", "denied", "authorized"].includes(value.profile)
      || !["not_checked", "connected", "not_connected"].includes(value.ice)
      || !["not_checked", "open", "not_open"].includes(value.channel)) {
    throw new Error("invalid_owner_diagnostic");
  }
  const unchecked = value.ice === "not_checked" && value.channel === "not_checked";
  if ((value.resource === "missing") !== (value.profile === "not_checked")
      || (value.ice === "not_checked") !== (value.channel === "not_checked")
      || (["not_checked", "unbound", "unavailable"].includes(value.profile) && !unchecked)
      || (value.profile === "authorized" && unchecked)) {
    throw new Error("invalid_owner_diagnostic");
  }
  return {as_of:value.as_of,resource:value.resource,profile:value.profile,
    ice:value.ice,channel:value.channel};
}

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
  const hasGather = intent !== null && typeof intent === "object" && Object.hasOwn(intent, "gather_failure");
  const hasChecking = intent !== null && typeof intent === "object" && Object.hasOwn(intent, "checking_observation");
  if (!fields(intent, "role,state,retirement" + (hasGather ? ",gather_failure" : "")
      + (hasChecking ? ",checking_observation" : "")) || !["offer", "answer"].includes(intent.role)
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
  const projected = {role:intent.role,state:intent.state,retirement};
  if (hasGather) projected.gather_failure = gatherFailure(intent, retirement);
  if (hasChecking) projected.checking_observation = checkingObservation(intent, retirement);
  return {status:"observed",total_intents:1,intents:[projected]};
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
