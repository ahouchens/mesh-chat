// Real Chromium media peer for the installed Windows call scenario. The page
// has no Core credentials; only the ordinary public SDK app handles signaling.
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const START_MS = 20_000;
const COMMAND_MS = 25_000;
const MAX_SDP = 128 * 1024;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// These functions run in the isolated browser page, not in the Node app.
export async function browserAnswer(offer, ice) {
  if (globalThis.__meshCallPeer || !navigator.mediaDevices?.getUserMedia ||
      typeof RTCPeerConnection !== "function") throw new Error("media_unavailable");
  let stream;
  let pc;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    if (stream.getAudioTracks().length !== 1 || stream.getAudioTracks()[0].readyState !== "live") {
      throw new Error("capture_unavailable");
    }
    pc = new RTCPeerConnection({ iceServers: ice.iceServers,
      iceTransportPolicy: ice.iceTransportPolicy });
    pc.ontrack = (event) => { globalThis.__meshCallRemoteTrack = event.track; };
    await pc.setRemoteDescription({ type: "offer", sdp: offer });
    for (const track of stream.getTracks()) pc.addTrack(track, stream);
    await pc.setLocalDescription(await pc.createAnswer());
    if (pc.iceGatheringState !== "complete") {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("ice_gather_timeout")), 18_000);
        const changed = () => {
          if (pc.iceGatheringState !== "complete") return;
          clearTimeout(timer);
          pc.removeEventListener("icegatheringstatechange", changed);
          resolve();
        };
        pc.addEventListener("icegatheringstatechange", changed);
        changed();
      });
    }
    const sdp = pc.localDescription?.sdp;
    const fingerprint = sdp?.split(/\r?\n/).find((line) => line.startsWith("a=fingerprint:"))
      ?.slice("a=fingerprint:".length).trim();
    if (!sdp || !fingerprint || !/(?:^|\r?\n)a=candidate:/.test(sdp)) {
      throw new Error("answer_incomplete");
    }
    globalThis.__meshCallPeer = { pc, stream };
    return { sdp, fingerprint, captured: true };
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    pc?.close();
    throw error;
  }
}

export async function browserObserve() {
  const owned = globalThis.__meshCallPeer;
  if (!owned) throw new Error("peer_unavailable");
  const { pc, stream } = owned;
  const stats = await pc.getStats();
  let outboundPackets = 0;
  let inboundPackets = 0;
  let selectedPair = false;
  for (const row of stats.values()) {
    if (row.type === "outbound-rtp" && row.kind === "audio") outboundPackets += row.packetsSent || 0;
    if (row.type === "inbound-rtp" && row.kind === "audio") inboundPackets += row.packetsReceived || 0;
    if (row.type === "candidate-pair" && row.state === "succeeded" && (row.selected || row.nominated)) {
      selectedPair = true;
    }
    if (row.type === "transport" && row.selectedCandidatePairId) {
      const pair = stats.get(row.selectedCandidatePairId);
      if (pair?.state === "succeeded") selectedPair = true;
    }
  }
  return { connected: pc.connectionState === "connected", selectedPair,
    captured: stream.getAudioTracks().length === 1 && stream.getAudioTracks()[0].readyState === "live",
    remoteAudio: globalThis.__meshCallRemoteTrack?.kind === "audio" &&
      globalThis.__meshCallRemoteTrack.readyState === "live",
    outboundPackets, inboundPackets };
}

export function browserStop() {
  const owned = globalThis.__meshCallPeer;
  globalThis.__meshCallPeer = undefined;
  globalThis.__meshCallRemoteTrack = undefined;
  if (!owned) return { stopped: true };
  const tracks = owned.stream.getTracks();
  tracks.forEach((track) => track.stop());
  owned.pc.close();
  return { stopped: tracks.every((track) => track.readyState === "ended") &&
    owned.pc.signalingState === "closed" };
}

function bounded(value, limit, code) {
  if (typeof value !== "string" || !value || Buffer.byteLength(value) > limit) throw new Error(code);
  return value;
}

function deadline(promise, ms, code) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(code)), ms);
  })]).finally(() => clearTimeout(timer));
}

export class BrowserMedia {
  constructor(executable, pagePath) {
    this.executable = executable;
    this.pageUrl = pathToFileURL(pagePath).href;
    this.pending = new Map();
    this.nextId = 1;
  }

  async start() {
    if (this.child || this.directory) throw new Error("browser_already_started");
    this.directory = await mkdtemp(join(tmpdir(), "mesh-call-peer-"));
    const child = spawn(this.executable, ["--headless=new", "--no-first-run", "--disable-extensions",
      "--disable-gpu", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=0",
      `--user-data-dir=${this.directory}`, this.pageUrl],
    { stdio: "ignore", windowsHide: true });
    this.child = child;
    child.once("error", () => { this.exited = true; });
    child.once("close", () => { this.exited = true; });
    const until = Date.now() + START_MS;
    let port;
    while (Date.now() < until && !this.exited) {
      try {
        const raw = await readFile(join(this.directory, "DevToolsActivePort"), "utf8");
        const lines = raw.split(/\r?\n/);
        if (raw.length <= 128 && /^[1-9][0-9]{3,4}$/.test(lines[0]) &&
            Number(lines[0]) <= 65535 && /^\/devtools\/browser\/[A-Za-z0-9-]{1,80}$/.test(lines[1])) {
          port = Number(lines[0]);
          break;
        }
      } catch { /* The owned browser is starting. */ }
      await pause(100);
    }
    if (!port) throw new Error("browser_start_unavailable");
    let target;
    while (Date.now() < until && !this.exited) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1000) });
        if (!response.ok || Number(response.headers.get("content-length")) > 65536) throw new Error();
        const rows = await response.json();
        if (!Array.isArray(rows) || rows.length > 32) throw new Error();
        target = rows.find((row) => row?.type === "page" && row.url === this.pageUrl);
        if (target) break;
      } catch { /* Target discovery is bounded by the same start deadline. */ }
      await pause(100);
    }
    if (!target || typeof target.webSocketDebuggerUrl !== "string") throw new Error("browser_page_unavailable");
    const endpoint = new URL(target.webSocketDebuggerUrl);
    if (endpoint.protocol !== "ws:" || !["localhost", "127.0.0.1"].includes(endpoint.hostname)
        || endpoint.port !== String(port) || !/^\/devtools\/page\/[A-Za-z0-9_-]{1,128}$/.test(endpoint.pathname)
        || endpoint.search || endpoint.hash || endpoint.username || endpoint.password) {
      throw new Error("browser_socket_invalid");
    }
    this.socket = new WebSocket(`ws://127.0.0.1:${port}${endpoint.pathname}`);
    this.socket.addEventListener("message", (event) => {
      let frame;
      try { frame = JSON.parse(String(event.data)); } catch { return; }
      const pending = this.pending.get(frame.id);
      if (!pending) return;
      this.pending.delete(frame.id);
      if (frame.error) pending.reject(new Error("browser_command_failed"));
      else pending.resolve(frame.result);
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("browser_socket_closed"));
      this.pending.clear();
    });
    await deadline(new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", () => reject(new Error("browser_socket_failed")), { once: true });
    }), Math.max(1, until - Date.now()), "browser_socket_timeout");
    await this.command("Runtime.enable");
  }

  async command(method, params = {}) {
    if (this.socket?.readyState !== WebSocket.OPEN) throw new Error("browser_socket_closed");
    const id = this.nextId++;
    const response = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.socket.send(JSON.stringify({ id, method, params }));
    try { return await deadline(response, COMMAND_MS, "browser_command_timeout"); }
    finally { this.pending.delete(id); }
  }

  async evaluate(fn, ...args) {
    const expression = `(${fn.toString()})(${args.map((arg) => JSON.stringify(arg)).join(",")})`;
    const result = await this.command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result?.exceptionDetails || !result?.result || result.result.type === "undefined") {
      throw new Error("browser_media_failed");
    }
    return result.result.value;
  }

  async answer(offer, ice) {
    bounded(offer, MAX_SDP, "offer_invalid");
    if (!ice || typeof ice !== "object" || !Array.isArray(ice.iceServers)
        || !["relay", "all"].includes(ice.iceTransportPolicy)) throw new Error("ice_invalid");
    const result = await this.evaluate(browserAnswer, offer, ice);
    bounded(result?.sdp, MAX_SDP, "answer_invalid");
    bounded(result?.fingerprint, 128, "fingerprint_invalid");
    if (result.captured !== true) throw new Error("capture_unavailable");
    return result;
  }

  async observe() {
    const value = await this.evaluate(browserObserve);
    if (!["connected", "selectedPair", "captured", "remoteAudio"].every((key) => typeof value?.[key] === "boolean")
        || !["outboundPackets", "inboundPackets"].every((key) => Number.isSafeInteger(value?.[key]) && value[key] >= 0)) {
      throw new Error("browser_stats_invalid");
    }
    return value;
  }

  async close() {
    let stopped = false;
    if (this.socket?.readyState === WebSocket.OPEN) {
      try { stopped = (await this.evaluate(browserStop))?.stopped === true; } catch { /* Preserve cleanup. */ }
      this.socket.close();
    }
    if (this.child && !this.exited) {
      this.child.kill();
      await deadline(new Promise((resolve) => this.child.once("close", resolve)), 5000,
        "browser_retirement_unconfirmed");
    }
    if (this.directory && this.exited) {
      await rm(this.directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
      this.directory = undefined;
    }
    return { stopped, browserRetired: this.exited === true, profileRemoved: !this.directory };
  }
}
