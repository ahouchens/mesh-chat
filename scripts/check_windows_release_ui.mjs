// Drive only visible released-app controls; read back through two read-only commands.
import { checkedConfig, checkedReadback, EVIDENCE_LEVEL, projectReadback } from "./windows_release_ui_contract.mjs";
import { boundedCdpFrame, closeBoundedSocket, completeAfterCleanup, readBoundedInput, withDeadline } from "./windows_release_ui_io.mjs";

const START_MS = 20_000;
const STEP_MS = 20_000;
const READBACK_MS = 12_000;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function boundedSocket(address, port) {
  try {
    const url = new URL(address);
    if (url.protocol !== "ws:" || !["localhost", "127.0.0.1"].includes(url.hostname)
        || url.port !== String(port) || url.username || url.password || url.search || url.hash
        || !/^\/devtools\/page\/[A-Za-z0-9_-]{1,128}$/.test(url.pathname)) return null;
    return `ws://127.0.0.1:${port}${url.pathname}`;
  } catch { return null; }
}

async function boundedTargets(response) {
  if (!response.ok || Number(response.headers.get("content-length")) > 65_536) {
    throw new Error("ui_target_invalid");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("ui_target_invalid");
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 65_536) {
      await reader.cancel();
      throw new Error("ui_target_invalid");
    }
    chunks.push(value);
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
}

// This function executes in the app page and returns only the center of one visible control.
function targetRect(kind, label, scope) {
  const norm = (value) => (value || "").replace(/\s+/g, " ").trim();
  const root = scope === "dialog" ? document.querySelector('[role="dialog"][aria-modal="true"]') : document;
  if (!root) return null;
  const rows = kind === "button"
    ? [...root.querySelectorAll("button")].filter((row) => norm(row.getAttribute("aria-label")) === label || norm(row.textContent) === label)
    : [...root.querySelectorAll("input,textarea")].filter((row) => {
        if (norm(row.getAttribute("aria-label")) === label) return true;
        const wrapper = row.closest("label");
        return wrapper && norm(wrapper.querySelector("span")?.textContent || wrapper.textContent) === label;
      });
  const eligible = rows.map((row) => {
    if (row.disabled || row.readOnly) return null;
    const box = row.getBoundingClientRect();
    const style = getComputedStyle(row);
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (box.width < 2 || box.height < 2 || style.display === "none" || style.visibility !== "visible"
        || !hit || !(row === hit || row.contains(hit))) return null;
    return { x, y };
  }).filter(Boolean);
  return eligible.length === 1 ? eligible[0] : null;
}

class Gui {
  pending = new Map();
  nextId = 1;

  async open(port, config) {
    const until = Date.now() + START_MS;
    let address;
    while (Date.now() < until) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`,
          { signal: AbortSignal.timeout(1_000) });
        const rows = await boundedTargets(response);
        if (!Array.isArray(rows) || rows.length > 128) throw new Error("ui_target_invalid");
        const matches = rows.filter((row) => {
          if (row?.type !== "page" || !boundedSocket(row.webSocketDebuggerUrl, port)) return false;
          try {
            const url = new URL(row.url);
            return (url.protocol === "http:" && url.hostname === "tauri.localhost")
              || (url.protocol === "tauri:" && url.hostname === "localhost");
          } catch { return false; }
        });
        if (matches.length > 1) throw new Error("ui_target_ambiguous");
        address = matches[0] && boundedSocket(matches[0].webSocketDebuggerUrl, port);
        if (address) break;
      } catch { /* The exact app WebView may still be starting. */ }
      await pause(100);
    }
    if (!address) throw new Error("ui_target_unavailable");
    this.socket = new WebSocket(address);
    this.socket.addEventListener("message", (event) => {
      let frame;
      try { frame = boundedCdpFrame(event.data); }
      catch {
        this.protocolFailed = true;
        for (const pending of this.pending.values()) pending.reject(new Error("ui_cdp_frame_invalid"));
        this.pending.clear();
        try { this.socket.close(); } catch { /* Owning runner retains custody. */ }
        return;
      }
      const pending = this.pending.get(frame.id);
      if (!pending) return;
      this.pending.delete(frame.id);
      if (frame.error) pending.reject(new Error("ui_cdp_failed"));
      else pending.resolve(frame.result);
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("ui_socket_closed"));
      this.pending.clear();
    });
    let onOpen, onError;
    try {
      const opened = new Promise((resolve, reject) => {
        onOpen = resolve;
        onError = () => reject(new Error("ui_socket_failed"));
        this.socket.addEventListener("open", onOpen);
        this.socket.addEventListener("error", onError);
      });
      await withDeadline(opened, Math.max(1, until - Date.now()), "ui_socket_deadline");
    } finally {
      this.socket.removeEventListener("open", onOpen);
      this.socket.removeEventListener("error", onError);
    }
    await this.command("Runtime.enable");
    const identity = await this.evaluate(`window.__TAURI_INTERNALS__?.invoke('app_build_info').then(value => ({
      mounted: Boolean(document.querySelector('#root > *')) && document.title === 'Mesh Chat',
      source: value?.build_commit, version: value?.installed_version
    }))`, true);
    if (identity?.mounted !== true || identity.source !== config.expected_source
        || identity.version !== config.expected_version) throw new Error("ui_source_mismatch");
  }

  async command(method, params = {}) {
    if (this.protocolFailed || this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error("ui_socket_closed");
    }
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    try {
      this.socket.send(JSON.stringify({ id, method, params }));
      return await withDeadline(promise, STEP_MS, "ui_step_deadline");
    } finally { this.pending.delete(id); }
  }

  async evaluate(expression, awaitPromise = false) {
    const result = await this.command("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
    if (result?.exceptionDetails || !result?.result || result.result.type === "undefined") {
      throw new Error("ui_observation_failed");
    }
    return result.result.value;
  }

  async rect(kind, label, scope) {
    return this.evaluate(`(${targetRect.toString()})(${JSON.stringify(kind)},${JSON.stringify(label)},${JSON.stringify(scope)})`);
  }

  async waitRect(kind, label, scope) {
    const until = Date.now() + STEP_MS;
    while (Date.now() < until) {
      const rect = await this.rect(kind, label, scope);
      if (rect && Number.isFinite(rect.x) && Number.isFinite(rect.y)) return rect;
      await pause(100);
    }
    throw new Error("ui_control_unavailable");
  }

  async waitEither(first, second) {
    const until = Date.now() + STEP_MS;
    while (Date.now() < until) {
      if (await this.rect("button", first, "page")) return first;
      if (await this.rect("button", second, "page")) return second;
      await pause(100);
    }
    throw new Error("ui_control_unavailable");
  }

  async click(kind, label, scope) {
    const { x, y } = await this.waitRect(kind, label, scope);
    await this.command("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await this.command("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  }

  async fill(label, value, scope) {
    await this.click("field", label, scope);
    await this.command("Input.dispatchKeyEvent", { type: "keyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
    await this.command("Input.dispatchKeyEvent", { type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17 });
    await this.command("Input.insertText", { text: value });
  }

  async readback(markers) {
    const expression = `(async () => {
      const invoke = window.__TAURI_INTERNALS__?.invoke;
      if (typeof invoke !== 'function') throw new Error('ui_bridge_unavailable');
      const snapshot = await invoke('service_command', {command:'snapshot',payload:{}});
      const workspaces = snapshot?.workspaces?.filter(item => item?.name === ${JSON.stringify(markers.workspace_name)});
      if (workspaces?.length !== 1) throw new Error('ui_workspace_missing');
      const channels = snapshot?.workspace_channels?.filter(item => item?.workspace_id === workspaces[0].id && item.name === 'general');
      if (channels?.length !== 1) throw new Error('ui_channel_missing');
      const page = await invoke('service_command', {command:'list_workspace_messages',payload:{
        workspace_id:workspaces[0].id,channel_id:channels[0].id,cursor:null,limit:50}});
      return (${projectReadback.toString()})(snapshot,page,${JSON.stringify(markers)});
    })()`;
    return checkedReadback(await this.evaluate(expression, true));
  }

  async settledReadback(markers) {
    const until = Date.now() + READBACK_MS;
    while (Date.now() < until) {
      try { return await this.readback(markers); }
      catch { await pause(200); }
    }
    throw new Error("ui_readback_deadline");
  }

  async waitMessage(text) {
    const until = Date.now() + STEP_MS;
    const expression = `(() => [...document.querySelectorAll('section.workspace-conversation article.workspace-message')]
      .filter(row => row.textContent?.includes(${JSON.stringify(text)})).length === 1)()`;
    while (Date.now() < until) {
      if (await this.evaluate(expression)) return;
      await pause(100);
    }
    throw new Error("ui_message_not_visible");
  }

  async seed(markers) {
    const fresh = await this.evaluate(`window.__TAURI_INTERNALS__?.invoke('service_command',
      {command:'snapshot',payload:{}}).then(value => value?.profile == null
        && Array.isArray(value.workspaces) && value.workspaces.length === 0
        && Array.isArray(value.workspace_drafts) && value.workspace_drafts.length === 0)`, true);
    if (fresh !== true) throw new Error("ui_profile_not_fresh");
    await this.click("button", "Start a chat", "page");
    await this.fill("Display name", "R8 CI Owner", "page");
    await this.click("button", "Create my invite", "page");
    // Some onboarding flows show a final invitation page before the messenger.
    if (await this.waitEither("Create workspace", "Open Mesh Chat") === "Open Mesh Chat") {
      await this.click("button", "Open Mesh Chat", "page");
    }
    await this.click("button", "Create workspace", "page");
    await this.fill("Name", markers.workspace_name, "dialog");
    await this.click("button", "Create workspace", "dialog");
    await this.waitRect("field", "Message general", "page");
    await this.fill("Message general", markers.message_text, "page");
    await this.click("button", "Send workspace message", "page");
    await this.waitMessage(markers.message_text);
    await this.fill("Message general", markers.draft_text, "page");
    return this.settledReadback(markers);
  }

  async close() { return closeBoundedSocket(this.socket); }
}

async function inputConfig() {
  return checkedConfig(JSON.parse(await readBoundedInput(process.stdin)));
}

async function main() {
  const port = Number(process.argv[2]);
  if (!Number.isInteger(port) || port < 1_024 || port > 65_535 || process.argv.length !== 3) {
    throw new Error("ui_port_invalid");
  }
  const config = await inputConfig();
  const gui = new Gui();
  return completeAfterCleanup(async () => {
    await gui.open(port, config);
    const hashes = config.phase === "seed" ? await gui.seed(config)
      : await gui.settledReadback(config);
    return { v: 1, passed: true, evidence_level: EVIDENCE_LEVEL,
      source_commit: config.expected_source, installed_version: config.expected_version,
      phase: config.phase, hashes, native_upgrade_qualified: false,
      peer_receipt_qualified: false, schema_refusal_qualified: false,
      physical_device_identity_qualified: false };
  }, () => gui.close());
}

try {
  process.stdout.write(JSON.stringify(await main()) + "\n");
} catch {
  process.stdout.write(JSON.stringify({ v: 1, passed: false, evidence_level: EVIDENCE_LEVEL,
    failure_kind: "ui_contract_failed" }) + "\n");
  process.exitCode = 1;
}
