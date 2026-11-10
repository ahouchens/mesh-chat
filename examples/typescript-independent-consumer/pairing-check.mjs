// Two normally installed application hosts, public SDK only. No private fixture.
import { CoreClient, CoreError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { setTimeout as pause } from "node:timers/promises";
import { launchRuntime, launchRefusedRuntime } from "./runtime.mjs";
import { freshRelaySettings } from "./relay-settings.mjs";
import { ERROR_CODES, pairingDiagnostics, probePairingFailure } from "./pairing-diagnostics.mjs";
import { connectionMessagingReady } from "./connection-readiness.mjs";

let phase = "arguments";
const diagnostics = pairingDiagnostics();
let deadline;
let failureDeadlineExhausted = false;
let primaryFailure;
let localDeadlineFailure;
function workDeadline(origin) {
  const error = new Error("public_pairing_deadline");
  localDeadlineFailure = { error, origin };
  return error;
}
function freezeFailure(error, origin) {
  if (primaryFailure) return;
  const code = error instanceof CoreError && ERROR_CODES.has(error.code) ? error.code : "unavailable";
  const selected = origin ?? (localDeadlineFailure && localDeadlineFailure.error === error ? localDeadlineFailure.origin
    : error instanceof CoreError && ERROR_CODES.has(error.code) ? "core_error" : "unknown");
  failureDeadlineExhausted = Date.now() >= deadline;
  diagnostics.freezeFailure(selected);
  primaryFailure = { error, phase, code };
}
function budget() {
  const value = Math.min(30000, deadline - Date.now());
  if (value <= 0) throw workDeadline("budget_deadline");
  return value;
}
async function request(peer, operation, params) {
  return peer.client.request(operation, params, { timeoutMs: budget() });
}
async function attach(peer, retrySlot = false) {
  const attachDeadline = retrySlot ? Math.min(deadline, Date.now() + 10000) : deadline;
  while (true) {
    let transport;
    try {
      transport = await connectNamedPipe(peer.runtime.pipe, Math.min(10000, budget(), attachDeadline - Date.now()));
      peer.transports.add(transport);
      const client = await CoreClient.open(transport, { requestTimeoutMs: Math.min(budget(), attachDeadline - Date.now()) });
      peer.clients.add(client);
      if (client.capabilities.profiles.length !== 1 || client.capabilities.operations.includes("native.command")) throw new Error();
      return client;
    } catch (error) {
      transport?.close();
      if (!retrySlot || !(error instanceof CoreError) || error.code !== "resource_exhausted"
          || Date.now() + 100 >= attachDeadline) throw error;
      await pause(100); // Bounded attachment to a just-freed session slot, never connection policy.
    }
  }
}
function closeClient(peer, client) {
  client.close();
  peer.clients.delete(client);
}
async function retire(peer) {
  if (peer.retired || !peer.runtime) return;
  let detachFailed = false;
  const facts = peer.cleanup;
  facts.attempts++;
  for (const endpoint of [...peer.clients, ...peer.transports]) {
    try { endpoint.close(); } catch { detachFailed = true; }
  }
  facts.detach = detachFailed ? "failed" : "ok";
  facts.budget_ms = Math.max(0, Math.min(30000, deadline - Date.now()));
  try {
    const completion = await peer.runtime.stop(facts.budget_ms);
    if (completion?.stopped !== true || completion.exit_code !== (peer.rejected ? 2 : 0)
        || (peer.rejected && (completion.refused !== true || completion.error !== "unavailable"))) throw new Error("retirement_incomplete");
    facts.stop = "completed";
  } catch (error) {
    facts.stop = "failed";
    throw error;
  }
  peer.retired = true;
  facts.retired = !detachFailed;
  if (detachFailed) throw new Error("client_detach_incomplete");
}
async function wait(read) {
  while (Date.now() < deadline) {
    const value = await read();
    if (value) return value;
    await pause(100);
  }
  throw workDeadline("wait_deadline");
}
function own(owned, peer) {
  peer.incarnation = owned.filter(item => item.role === peer.role).length + 1;
  owned.push(peer);
}
function retainRuntime(peer, runtime) {
  peer.runtime = runtime;
  peer.cleanup ??= diagnostics.owned(peer.role, peer.incarnation);
}
function one(rows, predicate) {
  const matches = rows.filter(predicate);
  if (matches.length > 1) throw new Error("unexpected_public_records");
  return matches[0];
}
async function snapshot(peer) {
  const value = await request(peer, "application.snapshot", {});
  diagnostics.snapshot(peer.role, value, peer.expectedDestination);
  return value;
}
async function create(executable, directory, name, role, owned) {
  const peer = { runtime: null, client: null, role, directory, clients: new Set(), transports: new Set() };
  own(owned, peer); // Retain lifetime even if startup or SDK negotiation fails.
  retainRuntime(peer, await launchRuntime(executable, directory,
    { timeoutMs: budget(), onOwned: runtime => { retainRuntime(peer, runtime); } }));
  peer.client = await attach(peer);
  const client = peer.client;
  if (client.capabilities.profiles.length !== 1 || client.capabilities.operations.includes("native.command")) throw new Error();
  const empty = await snapshot(peer);
  if (empty.profile !== null || empty.contacts.length || empty.messages.length) throw new Error();
  await client.request("profile.create", { display_name: name }, { idempotencyKey: randomUUID() });
  const caps = await client.request("runtime.capabilities", {});
  if (caps.profiles.length !== 1) throw new Error();
  peer.profile = caps.profiles[0];
  peer.operations = [...client.capabilities.operations].sort();
  peer.displayName = name;
  const identity = await client.request("profile.query", { profile: peer.profile });
  peer.destination = identity.destination;
  const fresh = await snapshot(peer);
  if (fresh.contacts.length || fresh.messages.length) throw new Error();
  await client.request("settings.update", { profile: peer.profile,
    settings: { nearby_discovery: false, lan_fallback: false, help_route: false } });
  const settings = (await client.request("settings.query", { profile: peer.profile })).settings;
  if (["nearby_discovery", "lan_fallback", "help_route"].some(key => settings[key] !== false)) throw new Error();
  const calls = (await client.request("call.settings_query", { profile: peer.profile })).settings;
  await client.request("call.settings_update", { profile: peer.profile,
    settings: freshRelaySettings(calls) });
  const applied = (await client.request("call.settings_query", { profile: peer.profile })).settings;
  if (applied.turn_broker_consent !== true || applied.relay_only !== true) throw new Error();
  return peer;
}
async function state(peer) {
  const value = await peer.client.pairingQuery(peer.profile, peer.pairing);
  diagnostics.pairing(peer.role, value);
  if (["retired", "retiring"].includes(value.state)) throw new Error("pairing_retired");
  return value;
}
async function relationship(peer, other) {
  return wait(async () => {
    const contacts = (await snapshot(peer)).contacts;
    if (contacts.length > 1) throw new Error();
    return one(contacts, contact => ["approved", "verified"].includes(contact.trust)
      && contact.destination_hash === other.destination);
  });
}
async function messagingReady(peer) {
  return wait(async () => {
    const profile = await peer.client.request("profile.query", { profile: peer.profile });
    let ready = 0;
    let checked = 0;
    diagnostics.connections(peer.role, profile.connections.length, checked, ready);
    for (const connection of profile.connections) {
      if (Date.now() >= deadline) throw new Error("public_pairing_deadline");
      if (await connectionMessagingReady(peer.client, peer.profile, connection)) ready++;
      diagnostics.connections(peer.role, profile.connections.length, ++checked, ready);
    }
    if (ready > 1) throw new Error("unexpected_ready_connections");
    return ready === 1;
  });
}
async function send(sender, receiver) {
  const text = "independent-public-receipt:" + randomUUID();
  const key = randomUUID();
  const first = await sender.client.enqueue(sender.profile, sender.contact.core_handle, text, key);
  const repeated = await sender.client.enqueue(sender.profile, sender.contact.core_handle, text, key);
  if (first.accepted !== true || repeated.message !== first.message) throw new Error();
  await wait(async () => (await sender.client.request("message.query", {
    profile: sender.profile, message: first.message })).state === "delivered");
  await wait(async () => (await snapshot(receiver)).messages.some(message =>
    message.kind === "chat" && message.direction === "inbound" && message.text === text));
  for (const [peer, direction] of [[sender, "outbound"], [receiver, "inbound"]]) {
    const records = (await snapshot(peer)).messages.filter(message =>
      message.kind === "chat" && message.direction === direction && message.text === text);
    if (records.length !== 1) throw new Error();
  }
  return { message: first.message, text };
}

const PENDING = new Set(["waiting_for_keys", "queued", "sending", "stored_for_delivery"]);
function enqueueWork(client, peer, work, text = work.text) {
  return client.request("message.enqueue", { profile: peer.profile, recipient: peer.contact.core_handle, kind: "text", text },
    { idempotencyKey: work.key, timeoutMs: budget() });
}
async function sameState(peer, client, receipt, inboundText) {
  const caps = await client.request("runtime.capabilities", {}, { timeoutMs: budget() });
  if (caps.profiles.length !== 1 || caps.profiles[0] !== peer.profile || caps.operations.includes("native.command")
      || JSON.stringify([...caps.operations].sort()) !== JSON.stringify(peer.operations)) throw new Error();
  const profile = await client.request("profile.query", { profile: peer.profile }, { timeoutMs: budget() });
  const view = await client.request("application.snapshot", {}, { timeoutMs: budget() });
  if (profile.destination !== peer.destination || view.profile?.destination_hash !== peer.destination
      || view.profile.display_name !== peer.displayName || view.contacts.length !== 1
      || !view.contacts.some(item => item.core_handle === peer.contact.core_handle
        && item.destination_hash === peer.expectedDestination && ["approved", "verified"].includes(item.trust))) throw new Error();
  for (const [text, direction] of [[receipt.text, "outbound"], [inboundText, "inbound"]]) {
    const rows = view.messages.filter(item => item.kind === "chat" && item.text === text && item.direction === direction);
    if (rows.length !== 1 || rows[0].contact_id !== peer.contact.id) throw new Error();
  }
  const message = await client.request("message.query", { profile: peer.profile, message: receipt.message }, { timeoutMs: budget() });
  if (message.message !== receipt.message || message.text !== receipt.text || message.recipient !== peer.contact.core_handle
      || message.state !== "delivered") throw new Error();
}
async function pending(peer, work) {
  const value = await request(peer, "message.query", { profile: peer.profile, message: work.message });
  const view = await snapshot(peer);
  const rows = view.messages.filter(item => item.kind === "chat" && item.direction === "outbound" && item.text === work.text);
  if (!PENDING.has(value.state) || value.message !== work.message || value.text !== work.text
      || value.recipient !== peer.contact.core_handle || rows.length !== 1 || !PENDING.has(rows[0].state)
      || rows[0].contact_id !== peer.contact.id
      || typeof rows[0].id !== "string" || (work.record !== undefined && rows[0].id !== work.record)) throw new Error();
  work.record = rows[0].id;
  return view;
}
function outboundIds(peer, view) {
  const ids = view.messages.filter(item => item.direction === "outbound" && item.contact_id === peer.contact.id)
    .map(item => item.id);
  if (ids.some(id => typeof id !== "string") || new Set(ids).size !== ids.length) throw new Error();
  return ids.sort();
}

async function sharedLifetime(executable, offerer, answerer, receipts, owned) {
  const checks = {};
  const original = offerer.client;
  diagnostics.enter("second_client_attach");
  const second = await attach(offerer);
  await sameState(offerer, original, receipts[0], receipts[1].text);
  await sameState(offerer, second, receipts[0], receipts[1].text);
  if (offerer.clients.size !== 2) throw new Error();
  checks.shared_host_sdk_sessions = offerer.clients.size;
  diagnostics.enter("client_detach_survivor");
  closeClient(offerer, original);
  offerer.client = second;
  await sameState(offerer, second, receipts[0], receipts[1].text);
  checks.closed_sdk_session_survivor_usable = true;
  diagnostics.enter("client_reattach");
  const replacement = await attach(offerer, true);
  await sameState(offerer, replacement, receipts[0], receipts[1].text);
  if (offerer.clients.size !== 2) throw new Error();
  checks.reattached_sdk_session_same_authorized_state = true;
  diagnostics.enter("competing_owner_refusal");
  const contender = { role: "contender", rejected: true, runtime: null, clients: new Set(), transports: new Set() };
  own(owned, contender);
  retainRuntime(contender, await launchRefusedRuntime(executable, offerer.directory,
    { timeoutMs: budget(), onOwned: runtime => { retainRuntime(contender, runtime); } }));
  await retire(contender);
  checks.concurrent_owner_refusals = 1;
  checks.rejected_owner_exits = 1;
  await sameState(offerer, second, receipts[0], receipts[1].text);
  await sameState(offerer, replacement, receipts[0], receipts[1].text);
  diagnostics.enter("offline_receiver_stop");
  await retire(answerer); // Positive stopped + exact child exit precede unique work generation.
  diagnostics.enter("pending_enqueue");
  const work = { text: "independent-pending:" + randomUUID(), key: randomUUID() };
  const first = await enqueueWork(second, offerer, work);
  if (first.accepted !== true || typeof first.message !== "string") throw new Error();
  work.message = first.message;
  await pending(offerer, work);
  const replay = await enqueueWork(replacement, offerer, work);
  if (replay.accepted !== true || replay.message !== work.message) throw new Error();
  await pending(offerer, work);
  checks.pending_message_before_owner_stop = true;
  diagnostics.enter("pending_owner_stop");
  await retire(offerer);
  diagnostics.enter("pending_owner_reopen");
  const reopened = { ...offerer, runtime: null, cleanup: null, client: null, clients: new Set(), transports: new Set(), retired: false, pairing: null };
  own(owned, reopened);
  retainRuntime(reopened, await launchRuntime(executable, offerer.directory,
    { timeoutMs: budget(), onOwned: runtime => { retainRuntime(reopened, runtime); } }));
  reopened.client = await attach(reopened);
  const reopenedSecond = await attach(reopened);
  await sameState(reopened, reopened.client, receipts[0], receipts[1].text);
  await sameState(reopened, reopenedSecond, receipts[0], receipts[1].text);
  const beforeReplay = outboundIds(reopened, await pending(reopened, work));
  checks.reopened_same_public_identity = true;
  checks.runtime_lock_reacquired = true;
  diagnostics.enter("original_key_replay");
  const restored = await enqueueWork(reopenedSecond, reopened, work);
  if (restored.accepted !== true || restored.message !== work.message) throw new Error();
  try {
    await enqueueWork(reopened.client, reopened, work, work.text + ":changed");
    throw new Error();
  } catch (error) {
    if (!(error instanceof CoreError) || error.code !== "idempotency_conflict") throw error;
  }
  const afterReplay = outboundIds(reopened, await pending(reopened, work));
  if (JSON.stringify(afterReplay) !== JSON.stringify(beforeReplay)) throw new Error();
  checks.reopened_original_message_and_key = true;
  return checks;
}

async function check(executable, directory) {
  const owned = [];
  diagnostics.start();
  deadline = Date.now() + 240000;
  let lifetime;
  try {
    phase = "fresh_profiles";
    diagnostics.enter("offerer_create");
    const offerer = await create(executable, join(directory, "offerer"), "Independent offerer", "offerer", owned);
    diagnostics.enter("answerer_create");
    const answerer = await create(executable, join(directory, "answerer"), "Independent answerer", "answerer", owned);
    diagnostics.enter("identity_distinct");
    if (!offerer.destination || offerer.destination === answerer.destination) throw new Error();
    offerer.expectedDestination = answerer.destination;
    answerer.expectedDestination = offerer.destination;
    phase = "public_pairing";
    diagnostics.enter("offer_begin");
    const begun = await offerer.client.pairingBegin(offerer.profile, "offer", randomUUID(), { allowDirectIpDisclosure: false });
    diagnostics.pairing("offerer", begun);
    offerer.pairing = begun.pairing;
    diagnostics.enter("offer_code_wait");
    const code = await wait(async () => (await state(offerer)).pairing_code);
    diagnostics.enter("answer_begin");
    const answered = await answerer.client.pairingBegin(answerer.profile, "answer", randomUUID(), {
      pairingCode: code, allowDirectIpDisclosure: false });
    diagnostics.pairing("answerer", answered);
    answerer.pairing = answered.pairing;
    phase = "explicit_approval";
    diagnostics.enter("invitation_wait");
    const invitation = await wait(async () => one((await snapshot(answerer)).contact_invitations,
      item => item.state === "pending"));
    diagnostics.enter("invitation_guard");
    if ((await snapshot(answerer)).contacts.length) throw new Error("approval_was_implicit");
    diagnostics.enter("invitation_accept");
    await answerer.client.request("contact.invitation", { profile: answerer.profile,
      action: "decide", invitation: invitation.id, accept: true });
    diagnostics.acceptanceReturned();
    diagnostics.enter("pending_request_wait");
    diagnostics.pendingWait(Date.now() >= deadline);
    const request = await wait(async () => {
      diagnostics.pendingAttempt();
      const value = await snapshot(offerer);
      diagnostics.pendingComplete();
      return one(value.contacts, item => item.trust === "pending_request" && item.destination_hash === answerer.destination);
    });
    diagnostics.enter("request_approve");
    await offerer.client.approve(offerer.profile, request.core_handle);
    diagnostics.enter("offerer_relationship_wait");
    offerer.contact = await relationship(offerer, answerer);
    diagnostics.enter("answerer_relationship_wait");
    answerer.contact = await relationship(answerer, offerer);
    diagnostics.enter("offerer_ready_wait");
    await messagingReady(offerer);
    diagnostics.enter("answerer_ready_wait");
    await messagingReady(answerer);
    phase = "transferred_cancellation";
    for (const peer of owned) {
      diagnostics.enter("transfer_wait");
      await wait(async () => (await state(peer)).state === "transferred");
      diagnostics.enter("transferred_cancel");
      const cancelled = await peer.client.pairingCancel(peer.profile, peer.pairing, randomUUID());
      if (cancelled.state !== "transferred" || cancelled.pairing_code !== null) throw new Error();
    }
    phase = "authenticated_receipts";
    diagnostics.enter("offerer_receipt");
    const sent = await send(offerer, answerer);
    diagnostics.enter("answerer_receipt");
    const received = await send(answerer, offerer);
    diagnostics.enter("offerer_ready_recheck");
    await messagingReady(offerer);
    diagnostics.enter("answerer_ready_recheck");
    await messagingReady(answerer);
    phase = "shared_host_lifetime";
    lifetime = await sharedLifetime(executable, offerer, answerer, [sent, received], owned);
  } catch (error) {
    freezeFailure(error);
    try { await probePairingFailure(owned, diagnostics); } catch { /* Diagnostic failure never replaces work failure. */ }
    throw error;
  } finally {
    const previous = phase;
    phase = "retirement";
    const exits = await Promise.allSettled(owned.map(retire));
    if (exits.some(result => result.status !== "fulfilled")) {
      if (!primaryFailure) {
        diagnostics.enter("retirement");
        const error = new Error("retirement_incomplete");
        freezeFailure(error, "cleanup_failure");
        throw error;
      }
    }
    phase = primaryFailure?.phase ?? previous;
  }
  return { fresh_profiles: 2, alternate_paths_disabled: true, direct_disclosure_consented: false,
    relay_only_requested: true, broker_consent: true,
    explicit_contact_decisions: 2, supervisor_transfers: 2, public_messaging_ready: 2,
    transferred_cancel_preserves_delivery: true,
    authenticated_receipts: 2, original_message_key_replay: true, single_inbound_and_outbound_records: true,
    ...lifetime, clean_host_exits: owned.filter(peer => !peer.rejected && peer.retired).length,
    owner_native_host_shutdown_acknowledgments: owned.filter(peer => !peer.rejected && peer.retired).length };
}
try {
  const args = process.argv.slice(2);
  if (args.length !== 4 || args[0] !== "--runtime" || args[2] !== "--data-directory") throw new Error();
  process.stdout.write(JSON.stringify(await check(args[1], args[3])) + "\n");
} catch (error) {
  const code = primaryFailure && primaryFailure.error === error ? primaryFailure.code
    : error instanceof CoreError && ERROR_CODES.has(error.code) ? error.code : "unavailable";
  process.stdout.write(JSON.stringify({ passed: false, phase, error_code: code,
    diagnostics: diagnostics.failure(failureDeadlineExhausted) }) + "\n");
  process.stderr.write("Independent public pairing check failed.\n");
  process.exitCode = 1;
}
