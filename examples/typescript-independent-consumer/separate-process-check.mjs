// Fresh-profile diagnostic: one normal owner and separate attach-only consumers.
import { CoreClient } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute } from "node:path";
import { TextDecoder } from "node:util";
import { launchRuntime } from "./runtime.mjs";

const SCOPE = "Installed Windows public SDK separate-process attach/detach and owner stop on one fresh profile; no pairing, pending work, receipts, wrong-image, cross-app isolation, Android or SC22/SC26 acceptance";
const MAX_FRAME = 256 * 1024;
const MAX_STDERR = 8192;
const TOTAL_MS = 180000;

function budget(deadline, limit = 30000) {
  const ms = Math.min(limit, deadline - Date.now());
  if (!Number.isSafeInteger(ms) || ms < 1) throw new Error("fixture_deadline");
  return ms;
}

function bounded(promise, ms) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("fixture_deadline")), ms);
  })]).finally(() => clearTimeout(timer));
}

function cleanEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !["MESH_", "GITHUB_", "ACTIONS_", "INPUT_"].some(prefix => key.toUpperCase().startsWith(prefix))
    && !["NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())));
}

class Helper {
  constructor(pipe) {
    this.child = spawn(process.execPath, ["consumer.mjs", "--pipe", pipe], {
      cwd: new URL(".", import.meta.url), env: cleanEnvironment(),
      stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    });
    this.identityValid = Number.isSafeInteger(this.child.pid)
      && this.child.pid > 0 && this.child.pid !== process.pid;
    this.sequence = 0;
    this.pending = null;
    this.stderrBytes = 0;
    this.outputFailure = false;
    this.exited = false;
    this.exit = new Promise(resolve => {
      this.child.once("close", (code, signal) => {
        this.exited = true;
        this.exitCode = code;
        this.exitSignal = signal;
        this.pending?.reject(new Error("helper_closed"));
        this.pending = null;
        resolve();
      });
    });
    this.child.once("error", () => {
      this.outputFailure = true;
      this.pending?.reject(new Error("helper_process_error"));
      this.pending = null;
    });
    this.child.stdin.on("error", () => {}); // A post-stop write is an expected closed transport.
    this.child.stderr.on("data", chunk => {
      this.stderrBytes += chunk.length;
      if (this.stderrBytes > MAX_STDERR) this.outputFailure = true;
    });
    let buffer = Buffer.alloc(0);
    this.child.stdout.on("data", chunk => {
      if (this.outputFailure || buffer.length + chunk.length > MAX_FRAME) {
        this.outputFailure = true;
        this.pending?.reject(new Error("helper_output"));
        this.pending = null;
        return;
      }
      buffer = Buffer.concat([buffer, chunk]);
      const end = buffer.indexOf(10);
      if (end < 0) return;
      if (end !== buffer.length - 1 || this.pending === null) {
        this.outputFailure = true;
        this.pending?.reject(new Error("helper_output"));
        this.pending = null;
        return;
      }
      const selected = this.pending;
      this.pending = null;
      const line = buffer;
      buffer = Buffer.alloc(0);
      try {
        const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line));
        if (value === null || typeof value !== "object" || Array.isArray(value)
            || value.id !== selected.id || value.ok !== true || value.result === null
            || typeof value.result !== "object" || Array.isArray(value.result)
            || Object.keys(value).sort().join() !== "id,ok,result") throw new Error();
        selected.resolve(value.result);
      } catch { selected.reject(new Error("helper_reply")); }
    });
    this.child.stdout.on("end", () => {
      if (buffer.length) this.outputFailure = true;
      this.pending?.reject(new Error("helper_output_closed"));
      this.pending = null;
    });
  }

  async request(operation, params, deadline) {
    if (this.pending || this.exited || this.outputFailure) throw new Error("helper_unavailable");
    const id = `helper:${++this.sequence}`;
    const frame = Buffer.from(JSON.stringify({ id, operation, params }) + "\n", "utf8");
    if (frame.length > MAX_FRAME) throw new Error("helper_frame_budget");
    const response = new Promise((resolve, reject) => { this.pending = { id, resolve, reject }; });
    response.catch(() => {}); // A failed write may precede the awaited response.
    try {
      await bounded(new Promise((resolve, reject) => {
        this.child.stdin.write(frame, error => error ? reject(new Error("helper_write")) : resolve());
      }), budget(deadline));
      return await bounded(response, budget(deadline));
    } finally {
      if (this.pending?.id === id) this.pending = null;
    }
  }

  async closeInput(deadline) {
    if (!this.child.stdin.destroyed) this.child.stdin.end();
    await bounded(this.exit, budget(deadline, 10000));
    if (this.exitCode !== 0 || this.exitSignal !== null || this.outputFailure || this.stderrBytes !== 0) {
      throw new Error("helper_exit");
    }
  }

  async dispose() {
    if (this.exited) return;
    try { this.child.stdin.end(); } catch {}
    try { await bounded(this.exit, 5000); } catch {
      if (!this.exited) {
        try { this.child.kill(); } catch {}
      }
      try { await bounded(this.exit, 5000); } catch {}
    }
  }
}

function sameState(value, profile, destination) {
  if (value?.profile?.destination_hash !== destination || value.profile.display_name !== "Separate process"
      || !Array.isArray(value.contacts) || value.contacts.length !== 0
      || !Array.isArray(value.messages) || value.messages.length !== 0
      || profile.destination !== destination) throw new Error("fresh_state_changed");
}

async function check(executable, dataDirectory) {
  const started = Date.now();
  const deadline = started + TOTAL_MS;
  let phase = "arguments", runtime, owner, helper, stopped = false;
  let detached = 0, attached = 0, firstHelperPid;
  try {
    if (process.platform !== "win32" || !isAbsolute(executable) || !isAbsolute(dataDirectory)) {
      throw new Error("fixture_arguments");
    }
    phase = "owner_start";
    runtime = await launchRuntime(executable, dataDirectory,
      { timeoutMs: budget(deadline), onOwned: value => { runtime = value; } });
    owner = await CoreClient.open(await connectNamedPipe(runtime.pipe, budget(deadline, 10000)),
      { requestTimeoutMs: budget(deadline) });
    const handles = owner.capabilities.profiles;
    if (!Array.isArray(handles) || handles.length !== 1 || typeof handles[0] !== "string"
        || !handles[0] || !Array.isArray(owner.capabilities.operations)
        || owner.capabilities.operations.includes("native.command")) {
      throw new Error("public_capabilities");
    }
    const empty = await owner.request("application.snapshot", {}, { timeoutMs: budget(deadline) });
    if (empty?.profile !== null || !Array.isArray(empty.contacts) || empty.contacts.length
        || !Array.isArray(empty.messages) || empty.messages.length) throw new Error("fresh_state");
    phase = "fresh_profile";
    await owner.request("profile.create", { display_name: "Separate process" },
      { idempotencyKey: randomUUID(), timeoutMs: budget(deadline) });
    const after = await owner.request("runtime.capabilities", {}, { timeoutMs: budget(deadline) });
    if (!Array.isArray(after.profiles) || after.profiles.length !== 1 || after.profiles[0] !== handles[0]
        || !Array.isArray(after.operations) || after.operations.includes("native.command")) {
      throw new Error("profile_handle_changed");
    }
    const profile = await owner.request("profile.query", { profile: handles[0] }, { timeoutMs: budget(deadline) });
    const destination = profile.destination;
    if (typeof destination !== "string" || !destination) throw new Error("fresh_identity");
    sameState(await owner.request("application.snapshot", {}, { timeoutMs: budget(deadline) }), profile, destination);

    phase = "first_helper_attach";
    helper = new Helper(runtime.pipe);
    if (!helper.identityValid) throw new Error("helper_process_identity");
    firstHelperPid = helper.child.pid;
    attached++;
    const firstCaps = await helper.request("runtime.capabilities", {}, deadline);
    if (!Array.isArray(firstCaps.profiles) || firstCaps.profiles.length !== 1
        || firstCaps.profiles[0] !== handles[0] || !Array.isArray(firstCaps.operations)
        || firstCaps.operations.includes("native.command")) throw new Error("helper_capabilities");
    sameState(await helper.request("application.snapshot", {}, deadline),
      await helper.request("profile.query", { profile: handles[0] }, deadline), destination);
    phase = "first_helper_detach";
    await helper.closeInput(deadline);
    detached++;
    helper = null;
    sameState(await owner.request("application.snapshot", {}, { timeoutMs: budget(deadline) }), profile, destination);

    phase = "replacement_helper_attach";
    helper = new Helper(runtime.pipe);
    if (!helper.identityValid || helper.child.pid === firstHelperPid) throw new Error("helper_process_identity");
    attached++;
    const replacementCaps = await helper.request("runtime.capabilities", {}, deadline);
    if (!Array.isArray(replacementCaps.profiles) || replacementCaps.profiles.length !== 1
        || replacementCaps.profiles[0] !== handles[0] || !Array.isArray(replacementCaps.operations)
        || replacementCaps.operations.includes("native.command")) throw new Error("helper_capabilities");
    sameState(await helper.request("application.snapshot", {}, deadline),
      await helper.request("profile.query", { profile: handles[0] }, deadline), destination);
    phase = "owner_stop";
    const completion = await runtime.stop(budget(deadline));
    if (completion?.stopped !== true || completion.exit_code !== 0) throw new Error("owner_retirement");
    stopped = true;
    phase = "helper_after_stop";
    let rejected = false;
    try { await helper.request("runtime.capabilities", {}, deadline); }
    catch { rejected = true; }
    if (!rejected) throw new Error("stopped_host_served_request");
    await bounded(helper.exit, budget(deadline, 10000));
    if (helper.exitCode !== 1 || helper.exitSignal !== null || helper.outputFailure
        || helper.stderrBytes > MAX_STDERR) throw new Error("helper_post_stop_exit");
    helper = null;
    return { v: 1, passed: true, scope: SCOPE, checks: {
      normal_owners: 1, distinct_helper_processes: attached, clean_helper_detaches: detached,
      owner_survived_detach: true, replacement_shared_fresh_state: true,
      positive_owner_stop: true, post_stop_helper_request_rejected: true,
      bounded_helper_exit: true,
    }, duration_ms: Math.min(Math.max(0, Date.now() - started), 240000) };
  } catch {
    return { v: 1, passed: false, scope: SCOPE, phase,
      duration_ms: Math.min(Math.max(0, Date.now() - started), 240000) };
  } finally {
    try { owner?.close(); } catch {}
    if (helper) {
      try { await helper.dispose(); } catch {}
    }
    if (runtime && !stopped) {
      try { await runtime.stop(Math.min(30000, Math.max(0, deadline - Date.now()))); }
      catch { /* Failure cleanup cannot create a passing result. */ }
    }
  }
}

const args = process.argv.slice(2);
const result = args.length === 4 && args[0] === "--runtime" && args[2] === "--data-directory"
  ? await check(args[1], args[3])
  : { v: 1, passed: false, scope: SCOPE, phase: "arguments", duration_ms: 0 };
process.stdout.on("error", () => process.exit(1));
try {
  await bounded(new Promise(resolve => process.stdout.write(JSON.stringify(result) + "\n", resolve)), 5000);
} catch { process.exit(1); }
process.exit(result.passed ? 0 : 1);
