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
globalThis.__diagnosticFixture = {
  CoreError,
  launchRuntime: async (_executable, directory) => {
    const role = directory.endsWith("offerer") ? "offerer" : "answerer";
    return { pipe: role, stop: async () => {
      log({event: "stop", role});
      if (probeMode === "retirement_failure") throw new Error("PRIVATE_RETIREMENT_ERROR");
    } };
  },
  connectNamedPipe: async pipe => pipe,
  CoreClient: { open: async (role, options) => {
    log({event: "open", role, timeout: options?.requestTimeoutMs});
    let created = false;
    return {
      capabilities: { profiles: ["PRIVATE_PROFILE"], operations: [] }, close() {},
      async request(operation, _params, options) {
        log({event: "request", role, operation});
        if (operation === "peer.pairing_query") {
          log({event: "probe", role, timeout: options?.timeoutMs});
          if (probeMode === "reject") throw new CoreError("PRIVATE_PROBE_ERROR");
          if (probeMode === "invalid") return {state: "PRIVATE_STATE", expires_at: "PRIVATE_TIMESTAMP"};
          if (probeMode === "advance_clock") expired = true;
          return {state: "transferred", expires_at: started / 1000 - 1, pairing_code: "PRIVATE_CODE", sdp: "PRIVATE_SDP"};
        }
        if (operation === "runtime.capabilities") return { profiles: ["PRIVATE_PROFILE"] };
        if (operation === "profile.create") { created = true; return {}; }
        if (operation === "profile.query") return { destination: destination(role), connections: ["PRIVATE_CONNECTION"] };
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
            contacts = [{ trust, destination_hash: target, core_handle: "PRIVATE_CONTACT", sdp: "PRIVATE_SDP" }];
          }
          return { profile: created ? { destination: destination(role) } : null,
            contacts, contact_invitations: invitations, messages: [] };
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
      async pairingQuery() { return { state: "offer_ready", pairing_code: "PRIVATE_PAIRING_CODE" }; },
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
  "./runtime.mjs": "export const {launchRuntime}=globalThis.__diagnosticFixture;",
};
registerHooks({ resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(sources, specifier)) return {
    url: "data:text/javascript," + encodeURIComponent(sources[specifier]), shortCircuit: true,
  };
  return nextResolve(specifier, context);
} });
