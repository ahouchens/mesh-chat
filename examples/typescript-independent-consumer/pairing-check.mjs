// Two normally installed application hosts, public SDK only. No private fixture.
import { CoreClient, CoreError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { setTimeout as pause } from "node:timers/promises";
import { launchRuntime } from "./runtime.mjs";

let phase = "arguments";
let deadline;
async function wait(read) {
  while (Date.now() < deadline) {
    const value = await read();
    if (value) return value;
    await pause(100);
  }
  throw new Error("public_pairing_deadline");
}
function one(rows, predicate) {
  const matches = rows.filter(predicate);
  if (matches.length > 1) throw new Error("unexpected_public_records");
  return matches[0];
}
async function snapshot(peer) { return peer.client.request("application.snapshot", {}); }
async function create(executable, directory, name, owned) {
  const runtime = await launchRuntime(executable, directory);
  const peer = { runtime, client: null };
  owned.push(peer); // Retain lifetime even if SDK negotiation fails.
  peer.client = await CoreClient.open(await connectNamedPipe(runtime.pipe), { requestTimeoutMs: 30000 });
  const client = peer.client;
  if (client.capabilities.profiles.length !== 1 || client.capabilities.operations.includes("native.command")) throw new Error();
  const empty = await snapshot(peer);
  if (empty.profile !== null || empty.contacts.length || empty.messages.length) throw new Error();
  await client.request("profile.create", { display_name: name }, { idempotencyKey: randomUUID() });
  const caps = await client.request("runtime.capabilities", {});
  if (caps.profiles.length !== 1) throw new Error();
  peer.profile = caps.profiles[0];
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
    settings: { ...calls, turn_broker_consent: true, relay_only: true } });
  const applied = (await client.request("call.settings_query", { profile: peer.profile })).settings;
  if (applied.turn_broker_consent !== true || applied.relay_only !== true) throw new Error();
  return peer;
}
async function state(peer) {
  const value = await peer.client.pairingQuery(peer.profile, peer.pairing);
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
    for (const connection of profile.connections) {
      if (Date.now() >= deadline) throw new Error("public_pairing_deadline");
      const value = await peer.client.request("connection.query", { profile: peer.profile, connection });
      if (value.observation.messaging_ready === true) ready++;
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
}

async function check(executable, directory) {
  const owned = [];
  deadline = Date.now() + 240000;
  try {
    phase = "fresh_profiles";
    const offerer = await create(executable, join(directory, "offerer"), "Independent offerer", owned);
    const answerer = await create(executable, join(directory, "answerer"), "Independent answerer", owned);
    if (!offerer.destination || offerer.destination === answerer.destination) throw new Error();
    phase = "public_pairing";
    const begun = await offerer.client.pairingBegin(offerer.profile, "offer", randomUUID(), { allowDirectIpDisclosure: false });
    offerer.pairing = begun.pairing;
    const code = await wait(async () => (await state(offerer)).pairing_code);
    answerer.pairing = (await answerer.client.pairingBegin(answerer.profile, "answer", randomUUID(), {
      pairingCode: code, allowDirectIpDisclosure: false })).pairing;
    phase = "explicit_approval";
    const invitation = await wait(async () => one((await snapshot(answerer)).contact_invitations,
      item => item.state === "pending"));
    if ((await snapshot(answerer)).contacts.length) throw new Error("approval_was_implicit");
    await answerer.client.request("contact.invitation", { profile: answerer.profile,
      action: "decide", invitation: invitation.id, accept: true });
    const request = await wait(async () => one((await snapshot(offerer)).contacts,
      item => item.trust === "pending_request" && item.destination_hash === answerer.destination));
    await offerer.client.approve(offerer.profile, request.core_handle);
    offerer.contact = await relationship(offerer, answerer);
    answerer.contact = await relationship(answerer, offerer);
    await messagingReady(offerer);
    await messagingReady(answerer);
    phase = "transferred_cancellation";
    for (const peer of owned) {
      await wait(async () => (await state(peer)).state === "transferred");
      const cancelled = await peer.client.pairingCancel(peer.profile, peer.pairing, randomUUID());
      if (cancelled.state !== "transferred" || cancelled.pairing_code !== null) throw new Error();
    }
    phase = "authenticated_receipts";
    await send(offerer, answerer);
    await send(answerer, offerer);
    await messagingReady(offerer);
    await messagingReady(answerer);
  } finally {
    const previous = phase;
    phase = "retirement";
    const exits = await Promise.allSettled(owned.map(async peer => {
      try { peer.client?.close(); }
      finally { await peer.runtime.stop(); }
    }));
    if (exits.some(result => result.status !== "fulfilled")) throw new Error("retirement_incomplete");
    phase = previous;
  }
  return { fresh_profiles: 2, alternate_paths_disabled: true, direct_disclosure_consented: false,
    relay_only_requested: true, broker_consent: true,
    explicit_contact_decisions: 2, supervisor_transfers: 2, public_messaging_ready: 2,
    transferred_cancel_preserves_delivery: true,
    authenticated_receipts: 2, original_message_key_replay: true, single_inbound_and_outbound_records: true,
    clean_host_exits: 2 };
}
try {
  const args = process.argv.slice(2);
  if (args.length !== 4 || args[0] !== "--runtime" || args[2] !== "--data-directory") throw new Error();
  process.stdout.write(JSON.stringify(await check(args[1], args[3])) + "\n");
} catch (error) {
  const code = error instanceof CoreError && /^[a-z_]{1,64}$/.test(error.code) ? error.code : "unavailable";
  process.stdout.write(JSON.stringify({ passed: false, phase, error_code: code }) + "\n");
  process.stderr.write("Independent public pairing check failed.\n");
  process.exitCode = 1;
}
