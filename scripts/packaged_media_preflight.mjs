// A deliberately narrow probe of the installed app's actual WebView2 engine.
// It never invokes private Core commands or substitutes browser media objects.
const [portText, timeoutText, expectedSource] = process.argv.slice(2);
const port = Number(portText);
const timeout = Number(timeoutText);
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
const appTarget = (target) => {
  if (target.type !== "page" || typeof target.webSocketDebuggerUrl !== "string") return false;
  try {
    const url = new URL(target.url);
    return (url.protocol === "http:" && url.hostname === "tauri.localhost") ||
      (url.protocol === "tauri:" && url.hostname === "localhost");
  } catch {
    return false;
  }
};

let target;
while (Date.now() < deadline) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1000) });
    if (response.ok) {
      const targets = await response.json();
      if (Array.isArray(targets)) target = targets.find(appTarget);
      if (target) break;
    }
  } catch {
    // WebView2 starts after the native app process.
  }
  await pause(200);
}
if (!target) throw new Error("app_webview_unavailable");

const socket = new WebSocket(target.webSocketDebuggerUrl);
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

try {
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
  const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  const value = result?.result?.value;
  const fields = ["appMounted", "tauriBridge", "mediaApi", "peerApi", "buildCommitMatches", "captured", "stopped"];
  if (result?.exceptionDetails || !value || fields.some((field) => typeof value[field] !== "boolean") ||
      Object.keys(value).length !== fields.length) throw new Error("invalid_media_probe");
  process.stdout.write(JSON.stringify(value) + "\n");
  if (fields.some((field) => !value[field])) process.exitCode = 1;
} finally {
  socket.close();
}
