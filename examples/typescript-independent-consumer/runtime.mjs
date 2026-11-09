// Application-owned host lifetime. Public Core traffic uses the SDK pipe only.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute, resolve } from "node:path";
import { TextDecoder } from "node:util";

const STATUS_LIMIT = 4096;
const decoder = new TextDecoder("utf-8", { fatal: true });

// Exported for subprocess protocol checks; no host command or grant interface.
export function observeRuntime(child, pipe, timeoutMs = 30000) {
  let pending = Buffer.alloc(0), started = false, stopped = false, failed = false;
  let closing = false, exited = false, protocolError;
  let accept, reject, complete;
  const ready = new Promise((yes, no) => { accept = yes; reject = no; });
  const closed = new Promise(yes => { complete = yes; });
  function fail() {
    protocolError = new Error("app_owned_runtime_unavailable");
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
        if (value.type === "runtime_started" && !started && !failed && !closing
            && value.pipe === pipe && Object.keys(value).sort().join() === "pipe,type,v") {
          started = true;
          accept();
        } else if (value.type === "runtime_failed" && !failed
            && typeof value.error === "string" && /^[a-z_]{1,64}$/.test(value.error)
            && Object.keys(value).sort().join() === "error,type,v") {
          failed = true;
          fail();
        } else if (value.type === "runtime_retiring" && (closing || failed)
            && Object.keys(value).sort().join() === "type,v") {
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
    if (code !== 0 || pending.length || !stopped || !started) fail();
    complete();
  });
  return {
    ready,
    async stop() {
      if (!closing) { closing = true; child.stdin.end(); }
      let deadline;
      try {
        await Promise.race([closed, new Promise((_, no) => {
          deadline = setTimeout(() => no(new Error("app_owned_runtime_retirement_pending")), timeoutMs);
        })]);
      } finally { clearTimeout(deadline); }
      if (!exited || !stopped || protocolError) throw new Error("app_owned_runtime_unavailable");
    },
  };
}

export async function launchRuntime(executable, dataDirectory) {
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
  const child = spawn(resolve(executable), ["--app-owned-native"], {
    env: environment, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  const runtime = observeRuntime(child, pipe);
  try { await runtime.ready; }
  catch (error) {
    try { await runtime.stop(); } catch { /* Child retains cleanup custody. */ }
    throw error;
  }
  return { pipe, stop: runtime.stop };
}
