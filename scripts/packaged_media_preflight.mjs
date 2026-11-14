// A deliberately narrow probe of the installed app's actual WebView2 engine.
// It never invokes private Core commands or substitutes browser media objects.
const [portText, timeoutText, expectedSource] = process.argv.slice(2);
const port = Number(portText);
const timeout = Number(timeoutText);
let probeStage = "arguments";
const discovery = {
  endpoint_response_seen: false, endpoint_non_ok_seen: false,
  endpoint_invalid_json_seen: false, endpoint_non_array_seen: false,
  endpoint_response_over_limit_seen: false, endpoint_target_limit_seen: false,
  endpoint_malformed_list_seen: false,
  endpoint_list_seen: false, targets_capped: 0, pages_capped: 0,
  pages_with_socket_capped: 0, expected_origin_pages_capped: 0,
  https_tauri_origin_pages_capped: 0, socket_rejected_pages_capped: 0,
};
try {
if (!Number.isInteger(port) || port < 1024 || port > 65535 || !Number.isInteger(timeout) || timeout < 1000 || timeout > 60000 ||
    !/^[a-f0-9]{40}$/.test(expectedSource ?? "")) {
  throw new Error("invalid_probe_arguments");
}

const deadline = Date.now() + timeout;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const withinDeadline = async (operation) => {
  let timer;
  try {
    return await Promise.race([
      operation,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("devtools_deadline")), Math.max(1, deadline - Date.now()));
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
};
// WebView2 may advertise localhost; connect to the already probed IPv4 loopback endpoint.
const localDebuggerSocket = (address) => {
  try {
    const url = new URL(address);
    if (url.protocol !== "ws:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
        url.port !== String(port) || url.username || url.password || url.search || url.hash ||
        !/^\/devtools\/page\/[A-Za-z0-9_-]{1,128}$/.test(url.pathname)) return null;
    return `ws://127.0.0.1:${port}${url.pathname}`;
  } catch {
    return null;
  }
};
const appTarget = (target) => {
  if (target.type !== "page" || typeof target.webSocketDebuggerUrl !== "string") return false;
  try {
    const url = new URL(target.url);
    return ((url.protocol === "http:" && url.hostname === "tauri.localhost") ||
      (url.protocol === "tauri:" && url.hostname === "localhost")) &&
      localDebuggerSocket(target.webSocketDebuggerUrl) !== null;
  } catch {
    return false;
  }
};
const boundedTargetBody = async (response) => {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("target_body_unavailable");
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 65536) {
      discovery.endpoint_response_over_limit_seen = true;
      // Do not let a peer-controlled cancellation delay the discovery deadline.
      void reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(Buffer.from(value));
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks, size));
};
const admittedTargetList = (targets) => targets.length <= 128 && targets.every((target) =>
  target !== null && typeof target === "object" && !Array.isArray(target) &&
  typeof target.type === "string" && (target.type !== "page" ||
    (typeof target.url === "string" &&
      (target.webSocketDebuggerUrl === undefined || typeof target.webSocketDebuggerUrl === "string"))));
const capped = (count) => Math.min(32, count);
const observeTargets = (targets) => {
  discovery.targets_capped = Math.max(discovery.targets_capped, capped(targets.length));
  let pages = 0;
  let pagesWithSocket = 0;
  let expectedOriginPages = 0;
  let httpsTauriOriginPages = 0;
  let socketRejectedPages = 0;
  for (const target of targets) {
    if (target?.type !== "page") continue;
    pages++;
    if (typeof target.webSocketDebuggerUrl === "string") pagesWithSocket++;
    try {
      const url = new URL(target.url);
      if ((url.protocol === "http:" && url.hostname === "tauri.localhost") ||
          (url.protocol === "tauri:" && url.hostname === "localhost")) {
        expectedOriginPages++;
        if (typeof target.webSocketDebuggerUrl === "string" &&
            localDebuggerSocket(target.webSocketDebuggerUrl) === null) socketRejectedPages++;
      }
      if (url.protocol === "https:" && url.hostname === "tauri.localhost") httpsTauriOriginPages++;
    } catch { /* Only fixed counts are retained. */ }
  }
  discovery.pages_capped = Math.max(discovery.pages_capped, capped(pages));
  discovery.pages_with_socket_capped = Math.max(discovery.pages_with_socket_capped, capped(pagesWithSocket));
  discovery.expected_origin_pages_capped = Math.max(discovery.expected_origin_pages_capped, capped(expectedOriginPages));
  discovery.https_tauri_origin_pages_capped = Math.max(discovery.https_tauri_origin_pages_capped, capped(httpsTauriOriginPages));
  discovery.socket_rejected_pages_capped = Math.max(discovery.socket_rejected_pages_capped, capped(socketRejectedPages));
};

let target;
probeStage = "target_discovery";
while (Date.now() < deadline) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1000) });
    discovery.endpoint_response_seen = true;
    if (response.ok) {
      const body = await boundedTargetBody(response);
      if (body !== null) {
        let targets;
        try { targets = JSON.parse(body); }
        catch { discovery.endpoint_invalid_json_seen = true; throw new Error("invalid_target_json"); }
        if (Array.isArray(targets)) {
          discovery.endpoint_list_seen = true;
          if (targets.length > 128) discovery.endpoint_target_limit_seen = true;
          else if (!admittedTargetList(targets)) discovery.endpoint_malformed_list_seen = true;
          else {
            observeTargets(targets);
            target = targets.find(appTarget);
          }
        } else {
          discovery.endpoint_non_array_seen = true;
        }
        if (target) break;
      }
    } else {
      discovery.endpoint_non_ok_seen = true;
    }
  } catch {
    // WebView2 starts after the native app process.
  }
  await pause(200);
}
if (!target) throw new Error("app_webview_unavailable");

probeStage = "devtools_connect";
const socket = new WebSocket(localDebuggerSocket(target.webSocketDebuggerUrl));
try {
const pending = new Map();
let nextId = 1;
const connect = new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", () => reject(new Error("devtools_socket_failed")), { once: true });
});
await withinDeadline(connect);
socket.addEventListener("message", (event) => {
  let frame;
  try { frame = JSON.parse(String(event.data)); } catch { return; }
  if (!frame.id || !pending.has(frame.id)) return;
  const operation = pending.get(frame.id);
  pending.delete(frame.id);
  if (frame.error) operation.reject(new Error("devtools_command_failed"));
  else operation.resolve(frame.result);
});
const command = (method, params = {}) => {
  if (Date.now() >= deadline) return Promise.reject(new Error("devtools_deadline"));
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return withinDeadline(new Promise((resolve, reject) => pending.set(id, { resolve, reject })))
    .finally(() => pending.delete(id));
};

  probeStage = "runtime_enable";
  await command("Runtime.enable");
  const expression = `(() => new Promise(async (resolve) => {
    const until = Date.now() + 10000;
    while (!document.querySelector('#root > *') && Date.now() < until) {
      await new Promise(done => setTimeout(done, 100));
    }
    const appMounted = Boolean(document.querySelector('#root > *')) && document.title === 'Mesh Chat';
    const tauriBridge = typeof window.__TAURI_INTERNALS__?.invoke === 'function';
    const mediaApi = typeof navigator.mediaDevices?.getUserMedia === 'function';
    const peerApi = typeof RTCPeerConnection === 'function';
    let buildCommitMatches = false;
    if (tauriBridge) {
      try {
        const info = await window.__TAURI_INTERNALS__.invoke('app_build_info');
        buildCommitMatches = info?.build_commit === ${JSON.stringify(expectedSource)};
      } catch { /* A missing public build identity fails the probe. */ }
    }
    if (!appMounted || !tauriBridge || !mediaApi || !peerApi || !buildCommitMatches) {
      resolve({appMounted, tauriBridge, mediaApi, peerApi, buildCommitMatches, captured: false, stopped: false});
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
      const tracks = stream.getAudioTracks();
      const captured = tracks.length > 0 && tracks.every(track => track.readyState === 'live');
      const peer = new RTCPeerConnection();
      peer.close();
      tracks.forEach(track => track.stop());
      resolve({appMounted, tauriBridge, mediaApi, peerApi, buildCommitMatches, captured,
        stopped: tracks.length > 0 && tracks.every(track => track.readyState === 'ended') && peer.signalingState === 'closed'});
    } catch {
      stream?.getTracks().forEach(track => track.stop());
      resolve({appMounted, tauriBridge, mediaApi, peerApi, buildCommitMatches, captured: false, stopped: false});
    }
  }))()`;
  probeStage = "runtime_evaluate";
  const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  probeStage = "result_validation";
  const value = result?.result?.value;
  const fields = ["appMounted", "tauriBridge", "mediaApi", "peerApi", "buildCommitMatches", "captured", "stopped"];
  if (result?.exceptionDetails || !value || fields.some((field) => typeof value[field] !== "boolean") ||
      Object.keys(value).length !== fields.length) throw new Error("invalid_media_probe");
  process.stdout.write(JSON.stringify(value) + "\n");
  if (fields.some((field) => !value[field])) process.exitCode = 1;
} finally {
  socket.close();
}
} catch (error) {
  const known = new Set(["invalid_probe_arguments", "app_webview_unavailable", "devtools_deadline",
    "devtools_socket_failed", "devtools_command_failed", "invalid_media_probe"]);
  const code = known.has(error?.message) ? error.message : "unexpected";
  const failure = { stage: probeStage, code };
  if (probeStage === "target_discovery" && code === "app_webview_unavailable") failure.discovery = discovery;
  process.stderr.write("mesh_media_probe_failure_v1:" + JSON.stringify(failure) + "\n");
  process.exitCode = 1;
}
