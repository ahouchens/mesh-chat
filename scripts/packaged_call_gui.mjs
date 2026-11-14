// Drive the exact installed WebView2 page through user input. No Core mutation,
// service command, synthetic media object, or DOM click is issued here.
import { createInterface } from "node:readline";
import { targetRect, readView } from "./packaged_call_gui_dom.mjs";

const [portText, source] = process.argv.slice(2);
const port = Number(portText);
const START_MS = 20_000;
const COMMAND_MS = 20_000;
const MAX_FRAME = 16 * 1024;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function timeout(promise, ms) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("gui_deadline")), ms);
  })]).finally(() => clearTimeout(timer));
}

function socketAddress(address) {
  try {
    const url = new URL(address);
    if (url.protocol !== "ws:" || !["localhost", "127.0.0.1"].includes(url.hostname)
        || url.port !== String(port) || url.username || url.password || url.search || url.hash
        || !/^\/devtools\/page\/[A-Za-z0-9_-]{1,128}$/.test(url.pathname)) return null;
    return `ws://127.0.0.1:${port}${url.pathname}`;
  } catch { return null; }
}

async function boundedTargets(response) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("gui_target_body_missing");
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 65536) {
      void reader.cancel().catch(() => {});
      throw new Error("gui_target_body_limit");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

class Gui {
  pending = new Map();
  nextId = 1;

  async open() {
    const until = Date.now() + START_MS;
    let target;
    while (Date.now() < until) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`,
          { signal: AbortSignal.timeout(1000) });
        if (!response.ok || Number(response.headers.get("content-length")) > 65536) throw new Error();
        const rows = await boundedTargets(response);
        if (!Array.isArray(rows) || rows.length > 128) throw new Error();
        const matches = rows.filter((row) => {
          if (row?.type !== "page" || typeof row.url !== "string"
              || !socketAddress(row.webSocketDebuggerUrl)) return false;
          try {
            const url = new URL(row.url);
            return (url.protocol === "http:" && url.hostname === "tauri.localhost") ||
              (url.protocol === "tauri:" && url.hostname === "localhost");
          } catch { return false; }
        });
        if (matches.length > 1) throw new Error("app_target_ambiguous");
        target = matches[0];
        if (target) break;
      } catch { /* Exact app may still be starting. */ }
      await pause(100);
    }
    if (!target) throw new Error("app_webview_unavailable");
    this.socket = new WebSocket(socketAddress(target.webSocketDebuggerUrl));
    this.socket.addEventListener("message", (event) => {
      let frame;
      try { frame = JSON.parse(String(event.data)); } catch { return; }
      const pending = this.pending.get(frame.id);
      if (!pending) return;
      this.pending.delete(frame.id);
      if (frame.error) pending.reject(new Error("gui_command_failed"));
      else pending.resolve(frame.result);
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("gui_socket_closed"));
      this.pending.clear();
    });
    await timeout(new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", () => reject(new Error("gui_socket_failed")), { once: true });
    }), Math.max(1, until - Date.now()));
    await this.command("Runtime.enable");
    const identity = await this.command("Runtime.evaluate", { expression:
      `window.__TAURI_INTERNALS__?.invoke('app_build_info').then(value =>
        ({mounted: Boolean(document.querySelector('#root > *')) && document.title === 'Mesh Chat',
          source: value?.build_commit}))`, awaitPromise: true, returnByValue: true });
    if (identity?.result?.value?.mounted !== true || identity.result.value.source !== source) {
      throw new Error("installed_source_mismatch");
    }
  }

  async command(method, params = {}) {
    if (this.socket?.readyState !== WebSocket.OPEN) throw new Error("gui_socket_closed");
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.socket.send(JSON.stringify({ id, method, params }));
    try { return await timeout(promise, COMMAND_MS); }
    finally { this.pending.delete(id); }
  }

  async evaluate(fn, ...args) {
    const expression = `(${fn.toString()})(${args.map((arg) => JSON.stringify(arg)).join(",")})`;
    const result = await this.command("Runtime.evaluate", { expression, returnByValue: true });
    if (result?.exceptionDetails || !result?.result || result.result.type === "undefined") {
      throw new Error("gui_observation_failed");
    }
    return result.result.value;
  }

  async rect(kind, label, scope) {
    const value = await this.evaluate(targetRect, kind, label, scope);
    if (!value || !Number.isFinite(value.x) || !Number.isFinite(value.y)) throw new Error("gui_target_unavailable");
    return value;
  }

  async click(kind, label, scope) {
    const { x, y } = await this.rect(kind, label, scope);
    await this.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await this.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  }

  async fill(label, value, scope) {
    if (typeof value !== "string" || !value || Buffer.byteLength(value) > 4096) throw new Error("gui_text_invalid");
    await this.click("field", label, scope);
    await this.command("Input.dispatchKeyEvent", { type: "keyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17 });
    await this.command("Input.insertText", { text: value });
  }

  async close() { this.socket?.close(); }
}

const BUTTONS = new Set(["Join with WebRTC", "Create profile and continue", "Use the relay",
  "Review and create answer", "Accept contact", "Audio call", "Hang up", "Send message"]);
const FIELDS = new Set(["Display name", "Paste the signed WebRTC offer or mailbox code",
  "Message Independent peer"]);

async function main() {
  if (!Number.isInteger(port) || port < 1024 || port > 65535 || !/^[a-f0-9]{40}$/.test(source || "")) {
    throw new Error("gui_arguments_invalid");
  }
  const gui = new Gui();
  try {
    await gui.open();
    process.stdout.write('{"ready":true}\n');
    for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
      if (Buffer.byteLength(line) > MAX_FRAME) throw new Error("gui_frame_limit");
      const request = JSON.parse(line);
      if (!request || !Number.isSafeInteger(request.id) || request.id < 1) throw new Error("gui_request_invalid");
      let value;
      try {
        if (request.action === "click" && BUTTONS.has(request.label)
            && ["page", "dialog"].includes(request.scope)) {
          await gui.click("button", request.label, request.scope);
          value = { clicked: true };
        } else if (request.action === "close_call") {
          await gui.click("call_close", "Close", "dialog");
          value = { clicked: true };
        } else if (request.action === "close_onboarding") {
          const view = await gui.evaluate(readView);
          if (view.dialogTitle === null) value = { alreadyDismissed: true };
          else if (view.dialogTitle === "Connect with WebRTC") {
            await gui.click("onboarding_close", "Close", "dialog");
            value = { clicked: true };
          } else throw new Error("gui_target_unavailable");
        } else if (request.action === "open_peer" && request.label === "Independent peer") {
          await gui.click("peer", request.label, "page");
          value = { clicked: true };
        } else if (request.action === "call_peer" && request.label === "Call Independent peer") {
          await gui.click("button", request.label, "page");
          value = { clicked: true };
        } else if (request.action === "fill" && FIELDS.has(request.label)
            && ["page", "dialog"].includes(request.scope)) {
          await gui.fill(request.label, request.value, request.scope);
          value = { filled: true };
        } else if (request.action === "observe" &&
            (request.text === undefined || typeof request.text === "string" && Buffer.byteLength(request.text) <= 4096)) {
          value = await gui.evaluate(readView, request.text);
        } else throw new Error("gui_action_invalid");
        process.stdout.write(JSON.stringify({ id: request.id, ok: true, value }) + "\n");
      } catch (error) {
        process.stdout.write(JSON.stringify({ id: request.id, ok: false,
          error: /^[a-z_]+$/.test(error?.message || "") ? error.message : "gui_failed" }) + "\n");
      }
    }
  } finally { await gui.close(); }
}

main().catch(() => { process.stderr.write("packaged_call_gui_failed\n"); process.exitCode = 1; });
