// Synthetic SDK/host boundaries exercise the actual producer's failure output.
// This never starts Core, a native host, a pipe or a network connection.
import { registerHooks } from "node:module";
import { appendFileSync } from "node:fs";

const originalNow = Date.now;
const started = originalNow();
let expired = false;
let elapsed = 0;
Date.now = () => started + (expired ? 300000 : elapsed);
Object.defineProperty(performance, "now", {value: () => expired ? 300000 : elapsed});
const fault = process.env.PAIRING_DIAGNOSTIC_FAULT;
const probeMode = process.env.PAIRING_DIAGNOSTIC_PROBE;
const networkMode = process.env.PAIRING_DIAGNOSTIC_NETWORK;
function log(value) {
  if (process.env.PAIRING_DIAGNOSTIC_LOG) appendFileSync(process.env.PAIRING_DIAGNOSTIC_LOG, JSON.stringify(value) + "\n");
}
let accepted = false;
let approved = false;
let answered = false;
class CoreError extends Error {
  constructor(code) { super("PRIVATE_ERROR_TEXT"); this.code = code; }
}
const destination = role => "PRIVATE_DESTINATION_" + role;
const other = role => role === "offerer" ? "answerer" : "offerer";
function halt(name) { if (fault === name) expired = true; }
const stores = new Map();
const owners = new Map();
const incarnations = new Map();
const keys = new Map();
let sequence = 0;
function storeFor(role) {
  if (!stores.has(role)) stores.set(role, {created:false,messages:[],keys:new Map()});
  return stores.get(role);
}
function launch(_executable, directory, options = {}, rejected = false) {
  const role = directory.endsWith("offerer") ? "offerer" : "answerer";
  const incarnation = (incarnations.get(role) ?? 0) + (rejected ? 0 : 1);
  if (!rejected) incarnations.set(role, incarnation);
  const owner = {role,incarnation,alive:true,sessions:0,opened:0,store:storeFor(role),rejected};
  if (!rejected) owners.set(role, owner);
  log({event:rejected ? "contender_start" : "start",role,incarnation,timeout:options.timeoutMs});
  const runtime = {pipe:owner,stop:async remaining => {
    log({event:"stop",role:rejected ? "contender" : role,incarnation,remaining});
    if (probeMode === "retirement_failure" || (fault === "refused_alive" && rejected)
        || fault === "startup_observation_failure"
        || (fault === "final_exit_missing" && role === "offerer" && incarnation === 2)) throw new Error("PRIVATE_RETIREMENT_ERROR");
    if (!(fault === "receiver_not_exited" && role === "answerer")) owner.alive=false;
    log({event:"exited",role:rejected ? "contender" : role,incarnation,code:rejected ? 2 : 0});
    return {stopped:true,exit_code:rejected ? 2 : 0,...(rejected ? {refused:true,error:"unavailable"} : {})};
  }};
  options.onOwned?.(runtime);
  if (fault === "startup_observation_failure") return Promise.reject(new Error("PRIVATE_STARTUP_ERROR"));
  if (rejected && fault === "refused_alive") return Promise.reject(new Error("PRIVATE_REFUSAL_PENDING"));
  return Promise.resolve(runtime);
}
function enqueue(owner, recipient, text, key) {
  if (!owner.alive) throw new CoreError("unavailable");
  if (!keys.has(key)) keys.set(key, keys.size+1);
  const saved=owner.store.keys.get(key);
  const pending=text.startsWith("independent-pending:");
  log({event:"enqueue",role:owner.role,incarnation:owner.incarnation,key:keys.get(key),pending,changed:Boolean(saved && saved.text!==text)});
  if (saved) {
    if (saved.text!==text) {
      if (fault === "changed_payload_succeeds") return {accepted:true,message:saved.message};
      throw new CoreError("idempotency_conflict");
    }
    if (pending && fault === "replay_duplicate") owner.store.messages.push({...saved.record,id:"duplicate"});
    if (pending && fault === "replay_new_handle") return {accepted:true,message:"PRIVATE_REPLACEMENT_MESSAGE"};
    if (pending && owner.incarnation===2 && fault === "original_key_lost") throw new CoreError("idempotency_expired");
    return {accepted:true,message:saved.message};
  }
  const message="PRIVATE_MESSAGE_"+(++sequence);
  const delivered=owners.get(other(owner.role))?.alive === true;
  const record={id:message,contact_id:"PRIVATE_CONTACT_ID",kind:"chat",direction:"outbound",text,state:delivered ? "delivered" : "queued"};
  owner.store.messages.push(record);
  owner.store.keys.set(key,{message,text,recipient,record});
  if (delivered) storeFor(other(owner.role)).messages.push({...record,direction:"inbound"});
  if (pending && fault === "pending_budget_exhausted") elapsed=240001;
  return {accepted:true,message};
}
globalThis.__diagnosticFixture = {
  CoreError,
  launchRuntime: (...args) => launch(...args),
  launchRefusedRuntime: (...args) => launch(...args,true),
  connectNamedPipe: async owner => ({owner,close(){log({event:"transport_close",role:owner.role});}}),
  CoreClient: { open: async (transport, options) => {
    const owner=transport.owner, role=owner.role;
    owner.sessions++; owner.opened++;
    const session=owner.opened;
    log({event: "open", role, timeout: options?.requestTimeoutMs});
    if (fault === "initial_negotiation_failure") throw new CoreError("unavailable");
    if (fault === "second_client_failure" && role === "offerer" && session===2) throw new CoreError("unavailable");
    if (["slot_releases", "slot_never_releases"].includes(fault) && role === "offerer" && owner.incarnation===1 && session===3) {
      if (fault === "slot_never_releases") elapsed+=10000;
      throw new CoreError("resource_exhausted");
    }
    let closed=false;
    return {
      capabilities: { profiles: ["PRIVATE_PROFILE"], operations: [] }, close() {
        if (closed) return;
        closed=true;owner.sessions--;
        log({event:"close",role,incarnation:owner.incarnation,session});
        if (fault === "detach_stops_owner" && role === "offerer" && session===1) owner.alive=false;
      },
      async request(operation, _params, options) {
        log({event: "request", role, operation,incarnation:owner.incarnation,session,timeout:options?.timeoutMs});
        if (closed || !owner.alive) throw new CoreError("unavailable");
        if (operation === "peer.pairing_query") {
          log({event: "probe", role, timeout: options?.timeoutMs});
          if (probeMode === "reject") throw new CoreError("PRIVATE_PROBE_ERROR");
          if (probeMode === "invalid") return {state: "PRIVATE_STATE", expires_at: "PRIVATE_TIMESTAMP"};
          if (probeMode === "advance_clock") expired = true;
          return {state: "transferred", expires_at: started / 1000 - 1, pairing_code: "PRIVATE_CODE", sdp: "PRIVATE_SDP"};
        }
        if (operation === "runtime.capabilities") return { profiles: ["PRIVATE_PROFILE"], operations:
          fault === "extra_authority" && session===2 ? ["native.command"] :
            fault === "changed_operations" && session===2 ? ["runtime.stop"] : [] };
        if (operation === "profile.create") {
          if (fault === "pre_profile_absence") throw new CoreError("forbidden");
          owner.store.created = true; owner.store.name=_params.display_name; return {};
        }
        if (operation === "profile.query") return { destination:
          ((fault === "survivor_identity" && session===2) || (fault === "reopened_identity" && owner.incarnation===2)
            || (fault === "reattach_wrong_owner" && session===3)) ? "PRIVATE_OTHER_IDENTITY" : destination(role), connections: ["PRIVATE_CONNECTION"] };
        if (operation === "message.enqueue") {
          if (Object.keys(_params).sort().join() !== "kind,profile,recipient,text" || _params.kind !== "text"
              || typeof options?.idempotencyKey !== "string" || options.timeoutMs < 1 || options.timeoutMs > 30000) throw new CoreError("invalid_request");
          return enqueue(owner,_params.recipient,_params.text,options.idempotencyKey);
        }
        if (operation === "message.query") {
          const saved=[...owner.store.keys.values()].find(value=>value.message===_params.message);
          if (!saved) throw new CoreError("not_found");
          const pending=saved.text.startsWith("independent-pending:");
          return {message:(pending && owner.incarnation===2 && fault === "reopened_handle") ? "PRIVATE_OTHER_MESSAGE" : saved.message,
            text:saved.text,recipient:saved.recipient,state:pending && fault === "pending_terminal" ? "failed" : saved.record.state};
        }
        if (operation === "settings.update") return {};
        if (operation === "settings.query") return { settings: { nearby_discovery: false, lan_fallback: false, help_route: false } };
        if (operation === "call.settings_update") return {};
        if (operation === "call.settings_query") return { settings: { stun_urls: [], turn_url: null, turn_username: null,
          turn_configured: false, turn_broker_url: null, signal_mailbox_url: null, store_call_signaling: true,
          turn_broker_consent: true, relay_only: true } };
        if (operation === "application.snapshot") {
          if (fault === "create_failure") throw new CoreError("forbidden");
          if (accepted && role === "offerer") {
            log({event: "post_accept_snapshot", role});
            if (fault === "pending_read_reject") { elapsed = 1500; throw new CoreError("unavailable"); }
            if (fault === "pending_read_in_flight") return new Promise((_, reject) => setTimeout(() => {
              elapsed = 1500; reject(new CoreError("unavailable"));
            }, 10));
          }
          let contacts = [], invitations = [];
          if (answered && role === "answerer" && !accepted) {
            if (fault === "invitation_wait") halt(fault);
            else invitations = [{ id: "PRIVATE_INVITATION", state: "pending", token: "PRIVATE_TOKEN" }];
          }
          if (accepted) {
            let trust = approved ? "approved" : "pending_request";
            let target = destination(other(role));
            if (role === "offerer" && !approved && fault === "pending_request_wait") { target = "PRIVATE_UNEXPECTED"; halt(fault); }
            if (role === "offerer" && approved && fault === "offerer_relationship_wait") { target = "PRIVATE_UNEXPECTED"; halt(fault); }
            contacts = [{ id:"PRIVATE_CONTACT_ID",trust, destination_hash: target, core_handle: "PRIVATE_CONTACT", sdp: "PRIVATE_SDP" }];
          }
          const created=owner.store.created;
          if ((fault === "survivor_contact" && session===2) || (fault === "reopened_contact" && owner.incarnation===2)) contacts=[];
          let messages=owner.store.messages;
          if (fault === "survivor_message" && session===2) messages=[];
          if (fault === "pending_absent") messages=messages.filter(item=>!item.text.startsWith("independent-pending:"));
          let network = created ? {address: "PRIVATE_ADDRESS", urls: ["PRIVATE_URL"]} : null;
          let serviceError = null;
          if (created && networkMode === "missing") { network = null; serviceError = "network_start_failed"; }
          if (created && networkMode === "unavailable") serviceError = "network_interface_unavailable";
          if (created && networkMode === "unexpected_error") serviceError = "PRIVATE_ERROR";
          if (created && networkMode === "error_object") serviceError = {path: "PRIVATE_PATH"};
          if (created && networkMode === "invalid_string") network = "PRIVATE_ADDRESS";
          if (created && networkMode === "invalid_array") network = ["PRIVATE_ADDRESS"];
          return { profile: created ? { destination_hash:
            fault === "snapshot_profile" && session===2 ? "PRIVATE_OTHER_IDENTITY" : destination(role),display_name:owner.store.name } : null, network, service_error: serviceError,
            contacts, contact_invitations: invitations, messages };
        }
        if (operation === "contact.invitation") {
          if (fault === "invitation_accept") throw new CoreError("forbidden");
          if (fault === "unsafe_error") throw new CoreError("private_token");
          accepted = true;
          elapsed = fault === "late_accept" ? 240100 : 1000;
          log({event: "accept_returned", role});
          return {};
        }
        if (operation === "connection.snapshot") {
          const unavailable = fault === role + "_ready_wait";
          if (unavailable) halt(fault);
          return { observation: { messaging_ready: !unavailable }, token: "PRIVATE_TOKEN" };
        }
        throw new Error("Unexpected synthetic request");
      },
      async pairingBegin(_profile, kind) {
        if (kind === "answer") answered = true;
        return { pairing: "PRIVATE_PAIRING", state: kind === "offer" ? "reserved" : "awaiting_approval", pairing_code: null };
      },
      async pairingQuery() { return { state: approved ? "transferred" : "offer_ready", pairing_code: "PRIVATE_PAIRING_CODE" }; },
      async pairingCancel() { return {state:"transferred",pairing_code:null}; },
      async enqueue(_profile,recipient,text,key) { return enqueue(owner,recipient,text,key); },
      async approve() { approved = true; },
      async connectionSnapshot(profile, connection) {
        return this.request("connection.snapshot", { profile, connection });
      },
    };
  } },
};
const sources = {
  "@mesh-chat/core-client": "export const {CoreClient,CoreError}=globalThis.__diagnosticFixture;",
  "@mesh-chat/core-client/node": "export const {connectNamedPipe}=globalThis.__diagnosticFixture;",
  "./runtime.mjs": "export const {launchRuntime,launchRefusedRuntime}=globalThis.__diagnosticFixture;",
};
registerHooks({ resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(sources, specifier)) return {
    url: "data:text/javascript," + encodeURIComponent(sources[specifier]), shortCircuit: true,
  };
  return nextResolve(specifier, context);
} });
