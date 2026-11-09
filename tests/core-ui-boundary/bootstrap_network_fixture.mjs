// Synthetic SDK/host boundaries around the actual bootstrap producer; no Core,
// native host, storage protection, pipe or network is started by this fixture.
import { registerHooks } from "node:module";
import { appendFileSync } from "node:fs";

const mode = process.env.BOOTSTRAP_NETWORK_MODE;
const failedIncarnation = Number(process.env.BOOTSTRAP_NETWORK_INCARNATION);
let incarnation = -1;
let created = false;
let mutationKey;
const log = event => appendFileSync(process.env.BOOTSTRAP_NETWORK_LOG, JSON.stringify(event) + "\n");
class CoreError extends Error {
  constructor(code) { super("PRIVATE_ERROR_TEXT"); this.code = code; }
}
function snapshot() {
  // Reading network members is unnecessary and could expose addresses/errors.
  const network = Object.defineProperty({}, "address", { enumerable: true,
    get() { throw new Error("PRIVATE_NETWORK_MEMBER_READ"); } });
  const value = { profile: created ? { display_name: "Independent application" } : null,
    contacts: [], messages: [], network: created ? network : null, service_error: null };
  if (created && incarnation === failedIncarnation) {
    if (mode === "unavailable") value.service_error = "network_interface_unavailable";
    if (mode === "null") value.network = null;
    if (mode === "missing_network") delete value.network;
    if (mode === "string") value.network = "PRIVATE_ADDRESS";
    if (mode === "array") value.network = ["PRIVATE_ADDRESS"];
    if (mode === "boolean") value.network = false;
    if (mode === "number") value.network = 1;
    if (mode === "startup_failure") { value.network = null; value.service_error = "network_start_failed"; }
    if (mode === "failure_with_object") value.service_error = "network_start_failed";
    if (mode === "unknown_error") value.service_error = "PRIVATE_ERROR";
    if (mode === "object_error") value.service_error = { path: "PRIVATE_PATH" };
    if (mode === "array_error") value.service_error = ["PRIVATE_ERROR"];
    if (mode === "boolean_error") value.service_error = false;
    if (mode === "missing_error") delete value.service_error;
  }
  return value;
}
globalThis.__bootstrapFixture = {
  CoreError,
  launchRuntime: async () => {
    incarnation++;
    log({event: "start", incarnation});
    return {pipe: "fixture", stop: async () => log({event: "stop", incarnation})};
  },
  connectNamedPipe: async pipe => pipe,
  CoreClient: {open: async () => {
    log({event: "open", incarnation});
    return {
      capabilities: {profiles: ["PRIVATE_PROFILE"], operations: ["profile.create"]},
      close() { log({event: "close", incarnation}); },
      async request(operation, params, options) {
        log({event: "request", incarnation, operation});
        if (operation === "application.snapshot") return snapshot();
        if (operation === "runtime.capabilities") return {profiles: ["PRIVATE_PROFILE"]};
        if (operation === "profile.query") {
          if (!created) throw new CoreError("locked");
          return {display_name: "Independent application", destination: "PRIVATE_DESTINATION"};
        }
        if (operation === "profile.create") {
          if (!options?.idempotencyKey) throw new Error("Missing explicit mutation key");
          mutationKey ??= options.idempotencyKey;
          if (mutationKey !== options.idempotencyKey) throw new Error("Changed mutation key");
          if (params.display_name !== "Independent application") throw new CoreError("idempotency_conflict");
          created = true;
          return {profile: "PRIVATE_PROFILE"};
        }
        throw new Error("Unexpected synthetic request");
      },
    };
  }},
};
const sources = {
  "@mesh-chat/core-client": "export const {CoreClient,CoreError}=globalThis.__bootstrapFixture;",
  "@mesh-chat/core-client/node": "export const {connectNamedPipe}=globalThis.__bootstrapFixture;",
  "./runtime.mjs": "export const {launchRuntime}=globalThis.__bootstrapFixture;",
};
registerHooks({resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(sources, specifier)) return {
    url: "data:text/javascript," + encodeURIComponent(sources[specifier]), shortCircuit: true,
  };
  return nextResolve(specifier, context);
}});
