// Application-owned host lifetime. Public Core traffic uses the SDK pipe only.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute, resolve } from "node:path";
import { TextDecoder } from "node:util";
import { ownerPairingObservation } from "./owner-pairing-diagnostic.mjs";

const STATUS_LIMIT = 4096;
const decoder = new TextDecoder("utf-8", { fatal: true });

// Exported for subprocess protocol checks; no host command or grant interface.
export function observeRuntime(child, pipe, timeoutMs = 30000, {pairingDiagnostics = false} = {}) {
  return observe(child, pipe, timeoutMs, false, pairingDiagnostics);
}

export function observeRuntimeRefusal(child, pipe, timeoutMs = 30000) {
  return observe(child, pipe, timeoutMs, true);
}

function observe(child, pipe, timeoutMs, refusal, pairingDiagnostics = false) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000) throw new Error("invalid_runtime_budget");
  if (typeof pairingDiagnostics !== "boolean") throw new Error("invalid_runtime_diagnostic_option");
  const observationDeadline = performance.now() + timeoutMs;
  let pending = Buffer.alloc(0), started = false, stopped = false, failed = false;
  let closing = false, exited = false, retiring = false, protocolError;
  let helperSequence = 0, pendingHelper = null, controlBusy = false;
  let accept, reject, complete;
  const ready = new Promise((yes, no) => { accept = yes; reject = no; });
  const closed = new Promise(yes => { complete = yes; });
  let diagnostic, diagnosticSeen = false, diagnosticComplete;
  const diagnosticReady = new Promise(resolve => { diagnosticComplete = resolve; });
  function fail() {
    if (protocolError) return;
    protocolError = new Error("app_owned_runtime_unavailable");
    pendingHelper?.reject(protocolError);
    pendingHelper = null;
    reject(protocolError);
    if (!closing) { closing = true; child.stdin.end(); }
  }
  const timer = setTimeout(fail, timeoutMs);
  ready.then(() => clearTimeout(timer), () => clearTimeout(timer));
  child.stdin.on("error", fail);
  child.stdout.on("error", fail);
  child.stderr.on("error", fail);
  child.on("error", fail);
  child.stderr.resume(); // Never forward upstream paths, payloads or key errors.
  child.stdout.on("data", chunk => {
    if (protocolError) return;
    try {
      let offset = 0;
      while (offset < chunk.length) {
        // Read at most the current header/body; no unbounded read-ahead buffer.
        const target = pending.length < 4 ? 4 : 4 + pending.readUInt32BE(0);
        const count = Math.min(target - pending.length, chunk.length - offset);
        pending = Buffer.concat([pending, chunk.subarray(offset, offset + count)]);
        offset += count;
        if (pending.length < 4) continue;
        const length = pending.readUInt32BE(0);
        if (length < 2 || length > STATUS_LIMIT) throw new Error();
        if (pending.length !== length + 4) continue;
        const value = JSON.parse(decoder.decode(pending.subarray(4)));
        pending = Buffer.alloc(0);
        if (!value || typeof value !== "object" || Array.isArray(value) || value.v !== 1 || stopped) throw new Error();
        if (value.type === "runtime_started" && !refusal && !started && !failed && !closing
            && value.pipe === pipe && Object.keys(value).sort().join() === "pipe,type,v") {
          if (performance.now() > observationDeadline) throw new Error();
          started = true;
          accept();
        } else if (value.type === "helper_registered" || value.type === "helper_removed") {
          const pendingRequest = pendingHelper;
          const keys = value.type === "helper_registered" ? "invitation,sequence,type,v" : "sequence,type,v";
          if (refusal || !started || closing || failed || !pendingRequest
              || performance.now() > pendingRequest.deadline
              || value.type !== pendingRequest.type || value.sequence !== pendingRequest.sequence
              || Object.keys(value).sort().join() !== keys
              || (value.type === "helper_registered" && (typeof value.invitation !== "string"
                || !/^[0-9a-f]{64}$/.test(value.invitation)))) throw new Error();
          pendingHelper = null;
          pendingRequest.resolve(value.type === "helper_registered" ? value.invitation : true);
        } else if (value.type === "runtime_pairing_diagnostics" && pairingDiagnostics && !refusal) {
          // Malformed optional diagnostics cannot grant authority or change lifecycle success.
          try {
            if (!started || !closing || retiring || diagnosticSeen
                || Object.keys(value).sort().join() !== "observation,type,v") throw new Error();
            diagnostic = {outcome:"received",observation:ownerPairingObservation(value.observation)};
          } catch { diagnostic = {outcome:"invalid_result"}; }
          diagnosticSeen = true;
          diagnosticComplete();
        } else if (value.type === "runtime_failed" && !failed && (!refusal || (!started && value.error === "unavailable"))
            && typeof value.error === "string" && /^[a-z_]{1,64}$/.test(value.error)
            && Object.keys(value).sort().join() === "error,type,v") {
          failed = true;
          if (refusal) { closing = true; child.stdin.end(); }
          else fail();
        } else if (value.type === "runtime_retiring" && (closing || failed)
            && (!refusal || (failed && !retiring))
            && Object.keys(value).sort().join() === "type,v") {
          retiring = true;
          closing = true;
        } else if (value.type === "runtime_stopped" && (closing || failed)
            && Object.keys(value).sort().join() === "type,v") {
          stopped = true;
        } else throw new Error();
      }
    } catch { fail(); }
  });
  child.on("close", code => {
    exited = true;
    if (pendingHelper || code !== (refusal ? 2 : 0) || pending.length || !stopped || (refusal ? !failed : !started)) fail();
    else if (!protocolError && refusal) {
      if (performance.now() > observationDeadline) fail();
      else accept();
    }
    complete();
    diagnosticComplete();
  });
  return {
    ready,
    async registerHelper(pid, timeoutMs = 5000) {
      return controlHelper("REGISTER/1", "helper_registered", pid, timeoutMs);
    },
    async removeHelper(pid, timeoutMs = 5000) {
      return controlHelper("REMOVE/1", "helper_removed", pid, timeoutMs);
    },
    async pairingDiagnostic(timeoutMs = 2000) {
      if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0 || timeoutMs > 2000) throw new Error("invalid_diagnostic_budget");
      if (!pairingDiagnostics || !closing) return {outcome:"not_received"};
      let timer;
      try {
        await Promise.race([diagnosticReady, new Promise(resolve => { timer = setTimeout(resolve, timeoutMs); })]);
      } finally { clearTimeout(timer); }
      return diagnostic ? structuredClone(diagnostic) : {outcome:"not_received"};
    },
    async stop(remainingMs = timeoutMs) {
      if (!Number.isSafeInteger(remainingMs) || remainingMs < 0 || remainingMs > 30000) throw new Error("invalid_runtime_budget");
      const alreadyExited = exited, retirementDeadline = performance.now() + remainingMs;
      if (!closing) { closing = true; child.stdin.end(); }
      if (pendingHelper) fail();
      let deadline;
      try {
        await Promise.race([closed, new Promise((_, no) => {
          deadline = setTimeout(() => no(new Error("app_owned_runtime_retirement_pending")), remainingMs);
        })]);
      } finally { clearTimeout(deadline); }
      if (!alreadyExited && performance.now() > retirementDeadline) throw new Error("app_owned_runtime_retirement_pending");
      if (!exited || !stopped || protocolError) throw new Error("app_owned_runtime_unavailable");
      return { stopped: true, exit_code: refusal ? 2 : 0, ...(refusal ? { refused: true, error: "unavailable" } : {}) };
    },
  };

  async function controlHelper(verb, type, pid, timeoutMs) {
    if (refusal || !started || failed || closing || exited || protocolError || controlBusy
        || !Number.isSafeInteger(pid) || pid < 1 || pid > 0xffffffff
        || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 5000
        || helperSequence === 0xffffffff) throw new Error("app_owned_helper_control_unavailable");
    const sequence = (++helperSequence).toString(16).padStart(8, "0");
    const line = `${verb} ${sequence} ${pid}\n`;
    if (Buffer.byteLength(line) > 40) throw new Error("app_owned_helper_control_unavailable");
    const deadline = performance.now() + timeoutMs;
    controlBusy = true;
    const response = new Promise((resolve, reject) => {
      pendingHelper = {type, sequence, deadline, resolve, reject};
    });
    response.catch(() => {});
    async function bounded(promise) {
      const remaining = Math.max(0, Math.floor(deadline - performance.now()));
      if (!remaining) throw new Error("app_owned_helper_control_deadline");
      let timer;
      try {
        return await Promise.race([promise, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("app_owned_helper_control_deadline")), remaining);
        })]);
      } finally { clearTimeout(timer); }
    }
    try {
      await bounded(new Promise((resolve, reject) => {
        child.stdin.write(line, error => error ? reject(new Error("app_owned_helper_control_write")) : resolve());
      }));
      const value = await bounded(response);
      if (protocolError || closing || failed || exited) throw new Error("app_owned_helper_control_failed");
      return value;
    } catch {
      fail();
      throw new Error("app_owned_helper_control_failed");
    } finally {
      if (pendingHelper?.sequence === sequence) pendingHelper = null;
      controlBusy = false;
    }
  }
}

function spawnRuntime(executable, dataDirectory, { timeoutMs = 30000, onOwned = () => {}, pairingDiagnostics = false } = {}, refusal = false) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000) throw new Error("invalid_runtime_budget");
  if (typeof pairingDiagnostics !== "boolean" || (refusal && pairingDiagnostics)) throw new Error("invalid_runtime_diagnostic_option");
  if (process.platform !== "win32" || !isAbsolute(executable) || !isAbsolute(dataDirectory)) {
    throw new Error("explicit_windows_runtime_and_data_required");
  }
  const pipe = `\\\\.\\pipe\\mesh-chat-independent-${randomUUID()}`;
  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !["MESH_CHAT_", "GITHUB_", "ACTIONS_", "INPUT_"].some(prefix => key.toUpperCase().startsWith(prefix))));
  Object.assign(environment, {
    MESH_CHAT_APP_DATA_DIRECTORY: resolve(dataDirectory),
    MESH_CHAT_CORE_API_PIPE: pipe,
    MESH_CHAT_CORE_API_CLIENT_IMAGE: process.execPath,
    MESH_CHAT_APP_PARENT_PID: String(process.pid),
  });
  // Proposed future host opt-in: MESH_CHAT_APP_PRIVATE_HELPER_ADMISSION=1.
  // Keep it unset until Python wiring acknowledges the private admission mode.
  if (pairingDiagnostics) environment.MESH_CHAT_APP_PAIRING_DIAGNOSTICS = "1";
  const child = spawn(resolve(executable), ["--app-owned-native"], {
    env: environment, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  const runtime = { pipe, ...observe(child, pipe, timeoutMs, refusal, pairingDiagnostics) };
  onOwned(runtime); // The launcher retains the exact child even if startup observation fails.
  return runtime;
}

export async function launchRuntime(executable, dataDirectory, options) {
  const runtime = spawnRuntime(executable, dataDirectory, options);
  try { await runtime.ready; }
  catch (error) {
    if (!options?.onOwned) {
      try { await runtime.stop(); } catch { /* Child retains cleanup custody. */ }
    }
    throw error;
  }
  return runtime;
}

export async function launchRefusedRuntime(executable, dataDirectory, options) {
  const runtime = spawnRuntime(executable, dataDirectory, options, true);
  await runtime.ready; // Failure marker alone never resolves this promise.
  const completion = await runtime.stop(0);
  return { ...runtime, completion };
}
