/**
 * Real-browser reproduction of ICE failure during a manual answer exchange.
 *
 * Requires Node >=20 and Playwright (or PLAYWRIGHT_MODULE pointing at its package).
 * Run with an explicitly supplied TURN broker, which allocates real TURN relays:
 *   node experiments/webrtc-call/manual_answer_browser.mjs --broker <https-url>
 *
 * BROWSER_PATH selects a Chromium-family executable; otherwise uses Edge.
 * --delay-ms defaults to 45000; --grace-ms defaults to 120000.
 * --output optionally saves the redacted timeline as JSON.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    broker: { type: "string" },
    "delay-ms": { type: "string", default: "45000" },
    "grace-ms": { type: "string", default: "120000" },
    output: { type: "string" },
  },
});
assert(values.broker?.startsWith("https://"), "Supply --broker <https-url> explicitly.");
const delay = Number(values["delay-ms"]);
const grace = Number(values["grace-ms"]);
assert(Number.isFinite(delay) && delay >= 30000, "Delay must be at least 30000 ms.");
assert(Number.isFinite(grace) && grace > delay + 10000, "Grace must exceed delay by 10000 ms.");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({
  ...(process.env.BROWSER_PATH ? { executablePath: process.env.BROWSER_PATH } : { channel: "msedge" }),
  headless: true,
  args: ["--disable-background-timer-throttling"],
});

try {
  const broker = new URL(values.broker);
  broker.searchParams.set("ttl", "600");
  const response = await fetch(broker, { signal: AbortSignal.timeout(15000) });
  assert(response.ok, `TURN broker returned HTTP ${response.status}.`);
  const { iceServers } = await response.json();
  assert(Array.isArray(iceServers), "TURN broker did not return iceServers.");
  const trials = [
    { name: "immediate", delay: 0, keepAnswerer: false },
    { name: "delayed_close_on_failure", delay, keepAnswerer: false },
    { name: "delayed_preserve_answerer", delay, keepAnswerer: true },
  ];
  console.log(JSON.stringify({ browser: browser.version(), delayMs: delay, graceMs: grace }));
  const results = await Promise.all(trials.map(async (trial) => {
    const page = await browser.newPage();
    await page.exposeFunction("report", (entry) => {
      if (entry.phase === "sample") return;
      const summary = (peer) => ({
        side: peer.side, state: peer.state, ice: peer.ice, pairs: peer.pairs?.length,
        channel: peer.channel,
      });
      console.log(JSON.stringify({
        trial: trial.name, ms: entry.ms, phase: entry.phase,
        ...summary(entry), peers: entry.peers?.map(summary),
      }));
    });
    try {
      return await page.evaluate(async ({ trial, iceServers, grace }) => {
        const started = performance.now();
        const rows = [];
        const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const mark = async (phase, extra = {}) => {
          const entry = { ms: Math.round(performance.now() - started), phase, ...extra };
          rows.push(entry);
          await window.report(entry);
        };
        const config = { iceServers, iceTransportPolicy: "relay" };
        const offerer = new RTCPeerConnection(config);
        const answerer = new RTCPeerConnection(config);
        const localChannel = offerer.createDataChannel("reticulum", { ordered: true });
        let remoteChannel;
        let roundTrip = false;
        let timer;
        const payload = "manual-answer-recovery";
        localChannel.onopen = () => {
          void mark("channel-open", { side: "offer" });
          localChannel.send(payload);
        };
        localChannel.onmessage = (event) => { roundTrip = event.data === payload; };
        answerer.ondatachannel = (event) => {
          remoteChannel = event.channel;
          remoteChannel.onopen = () => {
            clearTimeout(timer);
            void mark("channel-open", { side: "answer" });
          };
          remoteChannel.onmessage = (message) => remoteChannel.send(message.data);
        };
        const snapshot = async (pc, side) => {
          const stats = await pc.getStats();
          const candidates = [], pairs = [], transports = [];
          stats.forEach((stat) => {
            if (["local-candidate", "remote-candidate"].includes(stat.type)) {
              candidates.push({ type: stat.type, candidateType: stat.candidateType,
                protocol: stat.protocol, relayProtocol: stat.relayProtocol });
            } else if (stat.type === "candidate-pair") {
              pairs.push({ state: stat.state, nominated: stat.nominated,
                requestsSent: stat.requestsSent, responsesReceived: stat.responsesReceived,
                requestsReceived: stat.requestsReceived, responsesSent: stat.responsesSent });
            } else if (stat.type === "transport") {
              transports.push({ dtlsState: stat.dtlsState, iceRole: stat.iceRole,
                bytesSent: stat.bytesSent, bytesReceived: stat.bytesReceived,
                selected: Boolean(stat.selectedCandidatePairId) });
            }
          });
          return { side, state: pc.connectionState, ice: pc.iceConnectionState,
            gather: pc.iceGatheringState, candidates, pairs, transports,
            channel: (side === "offer" ? localChannel : remoteChannel)?.readyState ?? null };
        };
        const peers = () => Promise.all([
          snapshot(offerer, "offer"), snapshot(answerer, "answer"),
        ]);
        for (const [side, pc] of [["offer", offerer], ["answer", answerer]]) {
          pc.oniceconnectionstatechange = () => { void mark("ice-state", { side, state: pc.iceConnectionState }); };
          pc.onconnectionstatechange = async () => {
            const failed = pc.connectionState === "failed";
            await mark("connection-state", await snapshot(pc, side));
            if (failed && !(trial.keepAnswerer && side === "answer")) {
              pc.close();
              await mark("close-on-failure", { side });
            }
          };
        }
        const gathered = async (pc) => {
          const deadline = performance.now() + 15000;
          while (pc.iceGatheringState !== "complete" && performance.now() < deadline) await pause(50);
          if (pc.iceGatheringState !== "complete") throw new Error("ICE gathering timed out.");
        };
        const complete = (sdp) => sdp.includes("a=end-of-candidates")
          ? sdp : `${sdp.trimEnd()}\r\na=end-of-candidates\r\n`;
        const count = (sdp) => (sdp.match(/^a=candidate:/gm) || []).length;
        await offerer.setLocalDescription(await offerer.createOffer());
        await gathered(offerer);
        const offer = { type: "offer", sdp: complete(offerer.localDescription.sdp) };
        await answerer.setRemoteDescription(offer);
        if (trial.keepAnswerer) {
          timer = setTimeout(() => {
            answerer.close();
            void mark("answer-deadline");
          }, grace);
        }
        await answerer.setLocalDescription(await answerer.createAnswer());
        await gathered(answerer);
        const answer = { type: "answer", sdp: complete(answerer.localDescription.sdp) };
        await mark("answer-ready", { offerCandidates: count(offer.sdp), answerCandidates: count(answer.sdp) });
        const interval = setInterval(async () => { await mark("sample", { peers: await peers() }); }, 5000);
        try {
          await pause(trial.delay);
          await mark("apply-answer");
          await offerer.setRemoteDescription(answer);
          const deadline = performance.now() + 40000;
          while (!roundTrip && performance.now() < deadline) {
            if ([offerer, answerer].every((pc) => pc.connectionState === "closed")) break;
            await pause(50);
          }
          await mark("final", { peers: await peers(), roundTrip });
          return { trial, roundTrip, rows };
        } finally {
          clearInterval(interval);
          clearTimeout(timer);
          offerer.close();
          answerer.close();
        }
      }, { trial, iceServers, grace });
    } finally {
      await page.close();
    }
  }));
  if (values.output) await writeFile(values.output, JSON.stringify(results, null, 2));
  const [immediate, oldBehavior, preserved] = results;
  assert(immediate.roundTrip, "Immediate control did not connect; delay comparison is inconclusive.");
  assert(!oldBehavior.roundTrip, "Old behavior unexpectedly connected; increase --delay-ms.");
  assert(oldBehavior.rows.some((row) => row.phase === "connection-state" && row.side === "answer" && row.state === "failed"),
    "Old behavior did not reach an answerer ICE failure.");
  assert(preserved.rows.some((row) => row.phase === "connection-state" && row.side === "answer" && row.state === "failed"),
    "Preserved answerer did not reach an initial ICE failure; increase --delay-ms.");
  assert(preserved.rows.some((row) => row.phase === "sample" && row.peers.some((peer) => peer.side === "answer" && peer.pairs.length > 0)),
    "No live candidate pairs were captured before the answerer timed out.");
  assert(preserved.rows.some((row) => row.phase === "connection-state" && row.side === "answer" && row.state === "failed" && row.pairs.length === 0),
    "This browser did not reproduce the empty-pair failure snapshot.");
  assert(preserved.roundTrip, "Preserving the answerer did not recover after the delayed answer.");
  console.log("PASS: immediate exchange succeeds; delayed close fails; preserved answerer recovers and echoes data.");
} finally {
  await browser.close();
}
