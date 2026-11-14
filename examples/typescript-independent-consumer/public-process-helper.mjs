// Bounded custody of one same-image, attach-only public SDK consumer process.
import { spawn } from "node:child_process";
import { TextDecoder } from "node:util";

const MAX_FRAME = 256 * 1024;
const MAX_STDERR = 8192;

function budget(deadline, limit = 30000) {
  const ms = Math.min(limit, Math.floor(deadline - performance.now()));
  if (!Number.isSafeInteger(ms) || ms < 1) throw new Error("helper_deadline");
  return ms;
}

function bounded(promise, ms) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("helper_deadline")), ms);
  })]).finally(() => clearTimeout(timer));
}

function cleanEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !["MESH_", "GITHUB_", "ACTIONS_", "INPUT_"].some(prefix => key.toUpperCase().startsWith(prefix))
    && !["NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())));
}

export class HelperCoreError extends Error {
  constructor(code) { super("helper_core_error"); this.code = code; }
}

export class Helper {
  constructor(pipe) {
    this.child = spawn(process.execPath, ["consumer.mjs", "--pipe", pipe], {
      cwd: new URL(".", import.meta.url), env: cleanEnvironment(),
      stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    });
    this.identityValid = Number.isSafeInteger(this.child.pid)
      && this.child.pid > 0 && this.child.pid !== process.pid;
    this.sequence = 0;
    this.attempts = 0;
    this.pending = null;
    this.discardedReplies = 0;
    this.stderrBytes = 0;
    this.stderr = Buffer.alloc(0);
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
    this.child.stdin.on("error", () => {}); // A post-stop write can meet a closed transport.
    this.child.stdout.on("error", () => { this.outputFailure = true; });
    this.child.stderr.on("error", () => { this.outputFailure = true; });
    this.child.stderr.on("data", chunk => {
      this.stderrBytes += chunk.length;
      if (this.stderrBytes > MAX_STDERR) this.outputFailure = true;
      else this.stderr = Buffer.concat([this.stderr, chunk]);
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
      if (selected.discard) {
        // Deliberately do not decode the application's enqueue reply. The
        // separate owner session must prove the durable effect independently.
        this.discardedReplies++;
        selected.resolve();
        return;
      }
      try {
        const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line));
        if (value === null || typeof value !== "object" || Array.isArray(value)
            || value.id !== selected.id || ![true, false].includes(value.ok)) throw new Error();
        if (value.ok) {
          if (value.result === null || typeof value.result !== "object" || Array.isArray(value.result)
              || Object.keys(value).sort().join() !== "id,ok,result") throw new Error();
          selected.resolve(value.result);
        } else {
          if (Object.keys(value).sort().join() !== "error,id,ok"
              || value.error === null || typeof value.error !== "object" || Array.isArray(value.error)
              || Object.keys(value.error).join() !== "code" || typeof value.error.code !== "string"
              || !/^[a-z_]{1,64}$/.test(value.error.code)) throw new Error();
          selected.reject(new HelperCoreError(value.error.code));
        }
      } catch { selected.reject(new Error("helper_reply")); }
    });
    this.child.stdout.on("end", () => {
      if (buffer.length) this.outputFailure = true;
      this.pending?.reject(new Error("helper_output_closed"));
      this.pending = null;
    });
  }

  canRequest() {
    return !this.pending && !this.exited && !this.outputFailure
      && this.child.exitCode === null && !this.child.stdin.destroyed;
  }

  async _send(operation, params, deadline, idempotencyKey, discard) {
    if (!this.canRequest()) throw new Error("helper_unavailable");
    const id = `helper:${++this.sequence}`;
    const frame = Buffer.from(JSON.stringify({ id, operation, params,
      ...(idempotencyKey === undefined ? {} : { idempotency_key: idempotencyKey }) }) + "\n", "utf8");
    if (frame.length > MAX_FRAME) throw new Error("helper_frame_budget");
    const response = new Promise((resolve, reject) => { this.pending = { id, discard, resolve, reject }; });
    response.catch(() => {}); // A failed write may precede the awaited response.
    try {
      await bounded(new Promise((resolve, reject) => {
        this.child.stdin.write(frame, error => {
          if (error) reject(new Error("helper_write"));
          else { this.attempts++; resolve(); }
        });
      }), budget(deadline));
      return await bounded(response, budget(deadline));
    } finally {
      if (this.pending?.id === id) this.pending = null;
    }
  }

  request(operation, params, deadline, idempotencyKey) {
    return this._send(operation, params, deadline, idempotencyKey, false);
  }

  discardReply(operation, params, deadline, idempotencyKey) {
    return this._send(operation, params, deadline, idempotencyKey, true);
  }

  async closeInput(deadline) {
    if (this.pending) throw new Error("helper_request_pending");
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
