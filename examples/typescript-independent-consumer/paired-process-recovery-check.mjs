// Explicit opt-in: existing public pairing followed by same-image process recovery.
import { randomUUID } from "node:crypto";
import { isAbsolute } from "node:path";
import { performance } from "node:perf_hooks";
import { pairingFailureSummary, runPairing } from "./pairing-check.mjs";
import { Helper, HelperCoreError } from "./public-process-helper.mjs";
import { launchRuntime } from "./runtime.mjs";

const SCOPE = "Installed public SDK Windows paired process recovery after explicit approval on one same-image caller; application-side discarded enqueue reply, pending replay and later single delivery; no cross-app caller isolation or full SC22/SC23/SC24 acceptance";
const TOTAL_MS = 360000;
const PENDING = new Set(["waiting_for_keys", "queued", "sending", "stored_for_delivery"]);
const FAILURE_CAUSES = new Set([
  "public_rows", "duplicate_public_record", "public_capabilities", "public_authority_changed",
  "message_page", "duplicate_outbound", "pending_record_changed", "owner_session_count",
  "helper_identity", "reply_not_discarded", "pending_not_reopened", "replay_handle_changed",
  "changed_payload_accepted", "duplicate_after_replay", "receipt_records_changed", "retirement_count",
  "paired_contract", "helper_deadline", "helper_closed", "helper_process_error", "helper_output",
  "helper_reply", "helper_output_closed", "helper_unavailable", "helper_frame_budget",
  "helper_write", "helper_request_pending", "helper_exit", "public_pairing_deadline",
  "pairing_retired", "retirement_incomplete", "client_detach_incomplete",
]);

function fixedCause(error) {
  if (error instanceof HelperCoreError) return "helper_core_error";
  return error instanceof Error && FAILURE_CAUSES.has(error.message) ? error.message : "unavailable";
}

function one(rows, predicate) {
  if (!Array.isArray(rows)) throw new Error("public_rows");
  const matches = rows.filter(predicate);
  if (matches.length > 1) throw new Error("duplicate_public_record");
  return matches[0];
}

async function authority(peer, read) {
  const caps = await read("runtime.capabilities", {});
  if (!Array.isArray(caps.profiles) || caps.profiles.length !== 1 || caps.profiles[0] !== peer.profile
      || !Array.isArray(caps.operations) || caps.operations.includes("native.command")) {
    throw new Error("public_capabilities");
  }
  const profile = await read("profile.query", { profile: peer.profile });
  const view = await read("application.snapshot", {});
  const contact = one(view.contacts, item => item.core_handle === peer.contact.core_handle
    && item.destination_hash === peer.expectedDestination
    && item.trust === peer.contact.trust);
  if (profile.destination !== peer.destination || view.profile?.destination_hash !== peer.destination
      || view.profile.display_name !== peer.displayName || view.contacts.length !== 1
      || contact?.id !== peer.contact.id) throw new Error("public_authority_changed");
  return view;
}

async function listed(peer, read, text) {
  const page = await read("message.list", { profile: peer.profile, cursor: null, limit: 128 });
  if (!Array.isArray(page.messages) || page.next_cursor !== null) throw new Error("message_page");
  const matching = page.messages.filter(item => item.kind === "text" && item.text === text);
  if (matching.length > 1) throw new Error("duplicate_outbound");
  return matching[0];
}

async function pending(peer, read, text, handle, recordId) {
  const row = await listed(peer, read, text);
  if (!row) return null;
  if (!PENDING.has(row.state) || row.recipient !== peer.contact.core_handle
      || typeof row.message !== "string" || (handle && row.message !== handle)) {
    throw new Error("pending_record_changed");
  }
  const query = await read("message.query", { profile: peer.profile, message: row.message });
  const view = await read("application.snapshot", {});
  const visible = one(view.messages, item => item.kind === "chat" && item.direction === "outbound"
    && item.text === text);
  if (query.message !== row.message || query.text !== text || query.recipient !== peer.contact.core_handle
      || !PENDING.has(query.state) || !visible || !PENDING.has(visible.state)
      || visible.contact_id !== peer.contact.id || typeof visible.id !== "string"
      || (recordId && visible.id !== recordId)) throw new Error("pending_record_changed");
  return { handle: row.message, recordId: visible.id };
}

async function reopen(previous, executable, api) {
  const peer = { ...previous, runtime: null, cleanup: null, client: null,
    clients: new Set(), transports: new Set(), retired: false, pairing: null };
  api.own(api.owned, peer);
  api.retainRuntime(peer, await launchRuntime(executable, previous.directory,
    { timeoutMs: api.budget(), onOwned: value => { api.retainRuntime(peer, value); } }));
  peer.client = await api.attach(peer);
  if (peer.clients.size !== 1) throw new Error("owner_session_count");
  return peer;
}

async function pairedProcessLifetime(executable, offerer, answerer, receipts, owned, api, stage) {
  const sender = offerer, receiver = answerer;
  const context = { ...api, owned };
  let first, second, senderReopened, receiverReopened;
  let firstPid, positiveHelpers = 0;
  const work = { text: "independent-process-pending:" + randomUUID(), key: randomUUID() };
  const params = { profile: sender.profile, recipient: sender.contact.core_handle, kind: "text", text: work.text };
  const parentRead = (peer) => (operation, fields) => peer.client.request(operation, fields,
    { timeoutMs: api.budget() });
  try {
    stage("initial_authority");
    if (sender.clients.size !== 1 || receiver.clients.size !== 1) throw new Error("owner_session_count");
    await authority(sender, parentRead(sender));
    await authority(receiver, parentRead(receiver));
    stage("receiver_stop");
    await api.retire(receiver); // The receiver is positively stopped before the unique enqueue.

    stage("first_helper");
    first = new Helper(sender.runtime.pipe);
    if (!first.identityValid || first.child.pid === process.pid) throw new Error("helper_identity");
    firstPid = first.child.pid;
    await authority(sender, (op, fields) => first.request(op, fields, performance.now() + api.budget()));
    if (sender.clients.size + 1 !== 2) throw new Error("owner_session_count");
    stage("enqueue_and_pending");
    await first.discardReply("message.enqueue", params, performance.now() + api.budget(), work.key);
    const observed = await api.wait(() => pending(sender, parentRead(sender), work.text));
    if (first.discardedReplies !== 1) throw new Error("reply_not_discarded");
    work.handle = observed.handle;
    work.recordId = observed.recordId;
    stage("first_helper_stop");
    await first.closeInput(performance.now() + api.budget());
    positiveHelpers++;
    first = null;
    await pending(sender, parentRead(sender), work.text, work.handle, work.recordId);

    stage("sender_stop");
    await api.retire(sender);
    stage("sender_reopen");
    senderReopened = await reopen(sender, executable, context);
    await authority(senderReopened, parentRead(senderReopened));
    await pending(senderReopened, parentRead(senderReopened), work.text, work.handle, work.recordId);

    stage("second_helper");
    second = new Helper(senderReopened.runtime.pipe);
    if (!second.identityValid || second.child.pid === firstPid) throw new Error("helper_identity");
    await authority(senderReopened,
      (op, fields) => second.request(op, fields, performance.now() + api.budget()));
    if (senderReopened.clients.size + 1 !== 2) throw new Error("owner_session_count");
    const before = await pending(senderReopened,
      (op, fields) => second.request(op, fields, performance.now() + api.budget()),
      work.text, work.handle, work.recordId);
    if (!before) throw new Error("pending_not_reopened");
    stage("replay_and_conflict");
    const replay = await second.request("message.enqueue", params, performance.now() + api.budget(), work.key);
    if (replay.accepted !== true || replay.message !== work.handle) throw new Error("replay_handle_changed");
    try {
      await second.request("message.enqueue", { ...params, text: work.text + ":changed" },
        performance.now() + api.budget(), work.key);
      throw new Error("changed_payload_accepted");
    } catch (error) {
      if (!(error instanceof HelperCoreError) || error.code !== "idempotency_conflict") throw error;
    }
    const after = await pending(senderReopened,
      (op, fields) => second.request(op, fields, performance.now() + api.budget()),
      work.text, work.handle, work.recordId);
    if (!after || after.handle !== before.handle || after.recordId !== before.recordId) {
      throw new Error("duplicate_after_replay");
    }
    stage("second_helper_stop");
    await second.closeInput(performance.now() + api.budget());
    positiveHelpers++;
    second = null;

    stage("receiver_reopen");
    receiverReopened = await reopen(receiver, executable, context);
    await authority(receiverReopened, parentRead(receiverReopened));
    stage("delivery_receipt");
    await api.wait(async () => {
      const result = await senderReopened.client.request("message.query",
        { profile: senderReopened.profile, message: work.handle }, { timeoutMs: api.budget() });
      return result.state === "delivered";
    });
    await api.wait(async () => one((await api.snapshot(receiverReopened)).messages, item =>
      item.kind === "chat" && item.direction === "inbound" && item.text === work.text));
    const inbound = (await api.snapshot(receiverReopened)).messages.filter(item =>
      item.kind === "chat" && item.direction === "inbound" && item.text === work.text);
    const outbound = (await api.snapshot(senderReopened)).messages.filter(item =>
      item.kind === "chat" && item.direction === "outbound" && item.text === work.text);
    if (inbound.length !== 1 || inbound[0].contact_id !== receiverReopened.contact.id
        || outbound.length !== 1 || outbound[0].id !== work.recordId
        || outbound[0].state !== "delivered") throw new Error("receipt_records_changed");
    stage("final_stop");
    await api.retire(receiverReopened);
    await api.retire(senderReopened);
    if (positiveHelpers !== 2 || owned.filter(peer => !peer.rejected && peer.retired).length !== 4) {
      throw new Error("retirement_count");
    }
    return { max_owner_sdk_sessions: 2, distinct_helper_processes: 2,
      discarded_application_reply: true, independent_pending_commit_observed: true,
      first_helper_positive_exit: true, owner_reopened_same_data: true,
      current_authority_preserved: true, same_key_original_handle: true,
      changed_payload_conflict: true, single_outbound_record: true,
      receiver_reopened: true, authenticated_delivery_receipt: true,
      single_inbound_record: true, positive_helper_exits: positiveHelpers };
  } finally {
    for (const helper of [first, second]) if (helper) await helper.dispose();
  }
}

async function main(args) {
  const started = performance.now();
  let phase = "arguments";
  let stage = "initial_pairing";
  try {
    if (args.length !== 4 || args[0] !== "--runtime" || args[2] !== "--data-directory"
        || process.platform !== "win32" || !isAbsolute(args[1]) || !isAbsolute(args[3])) {
      throw new Error("arguments");
    }
    phase = "paired_process_recovery";
    const paired = await runPairing(args[1], args[3], {
      afterPaired: (...values) => pairedProcessLifetime(...values, value => { stage = value; }),
      totalMs: TOTAL_MS,
    });
    stage = "success_contract";
    const duration = Math.floor(performance.now() - started);
    if (duration < 0 || duration >= TOTAL_MS || paired.fresh_profiles !== 2
        || paired.explicit_contact_decisions !== 2 || paired.authenticated_receipts !== 2
        || paired.clean_host_exits !== 4 || paired.owner_native_host_shutdown_acknowledgments !== 4) {
      throw new Error("paired_contract");
    }
    return { v: 1, passed: true, scope: SCOPE, checks: {
      approved_profiles: 2, authenticated_pre_recovery_receipts: 2,
      max_owner_sdk_sessions: paired.max_owner_sdk_sessions,
      distinct_helper_processes: paired.distinct_helper_processes,
      discarded_application_reply: paired.discarded_application_reply,
      independent_pending_commit_observed: paired.independent_pending_commit_observed,
      first_helper_positive_exit: paired.first_helper_positive_exit,
      owner_reopened_same_data: paired.owner_reopened_same_data,
      current_authority_preserved: paired.current_authority_preserved,
      same_key_original_handle: paired.same_key_original_handle,
      changed_payload_conflict: paired.changed_payload_conflict,
      single_outbound_record: paired.single_outbound_record,
      receiver_reopened: paired.receiver_reopened,
      authenticated_delivery_receipt: paired.authenticated_delivery_receipt,
      single_inbound_record: paired.single_inbound_record,
      positive_owner_exits: paired.clean_host_exits,
      positive_helper_exits: paired.positive_helper_exits,
    }, duration_ms: duration };
  } catch (error) {
    const pairing = stage === "initial_pairing" ? pairingFailureSummary(error) : null;
    return { v: 1, passed: false, scope: SCOPE, phase,
      stage: phase === "arguments" ? "arguments" : stage, cause: fixedCause(error),
      ...(pairing ? { pairing_failure: pairing } : {}),
      duration_ms: Math.min(TOTAL_MS, Math.max(0, Math.floor(performance.now() - started))) };
  }
}

const result = await main(process.argv.slice(2));
process.stdout.on("error", () => process.exit(1));
process.stdout.write(JSON.stringify(result) + "\n", () => process.exit(result.passed ? 0 : 1));
