import { redactIceUrl } from "./webrtc-peer";

export interface PeerTraceRecord {
  elapsedMs: number;
  event: string;
  connectionState: RTCPeerConnectionState;
  iceConnectionState: RTCIceConnectionState;
  iceGatheringState: RTCIceGatheringState;
  signalingState: RTCSignalingState;
  candidateType?: string;
  errorCode?: number;
  url?: string;
  stats?: {
    pairs: number;
    remoteCandidates: number;
    pairStates: Record<string, number>;
    requestsSent: number;
    responsesReceived: number;
  };
}

export interface PeerTrace {
  /** Record an application event label, never an SDP or error message. */
  record(event: string): void;
  snapshot(): readonly PeerTraceRecord[];
  stop(): void;
}

/** Preserve early ICE evidence: failed pairs can disappear from later getStats. */
export function startPeerTrace(pc: RTCPeerConnection): PeerTrace {
  const started = performance.now();
  const records: PeerTraceRecord[] = [];
  let firstPairSample: PeerTraceRecord | undefined;
  let stopped = false;
  let sampling = false;

  const append = (event: string, details: Partial<PeerTraceRecord> = {}) => {
    if (stopped) return;
    const entry: PeerTraceRecord = {
      elapsedMs: Math.round(performance.now() - started),
      event,
      connectionState: pc.connectionState,
      iceConnectionState: pc.iceConnectionState,
      iceGatheringState: pc.iceGatheringState,
      signalingState: pc.signalingState,
      ...details,
    };
    records.push(entry);
    if (!firstPairSample && entry.stats && entry.stats.pairs > 0) firstPairSample = entry;
    // Keep creation and the first proof of pairing even during a long exchange.
    if (records.length > 100) records.splice(records[1] === firstPairSample ? 2 : 1, 1);
  };

  const sample = async (event: string) => {
    if (stopped || sampling) return;
    sampling = true;
    try {
      const report = await pc.getStats();
      if (stopped) return;
      const stats: NonNullable<PeerTraceRecord["stats"]> = {
        pairs: 0,
        remoteCandidates: 0,
        pairStates: {},
        requestsSent: 0,
        responsesReceived: 0,
      };
      report.forEach((value) => {
        if (value.type === "remote-candidate") stats.remoteCandidates++;
        if (value.type !== "candidate-pair") return;
        stats.pairs++;
        const state = ["frozen", "waiting", "in-progress", "failed", "succeeded"].includes(value.state)
          ? String(value.state) : "unknown";
        stats.pairStates[state] = (stats.pairStates[state] ?? 0) + 1;
        if (typeof value.requestsSent === "number" && Number.isFinite(value.requestsSent)) {
          stats.requestsSent += value.requestsSent;
        }
        if (typeof value.responsesReceived === "number" && Number.isFinite(value.responsesReceived)) {
          stats.responsesReceived += value.responsesReceived;
        }
      });
      append(event, { stats });
    } catch {
      // getStats can fail during shutdown. Never retain browser error text.
      append("stats-unavailable");
    } finally {
      sampling = false;
    }
  };

  const record = (event: string) => {
    append(event);
    void sample(`${event}:stats`);
  };
  const stateEvents = [
    "connectionstatechange", "iceconnectionstatechange", "icegatheringstatechange", "signalingstatechange",
  ] as const;
  const onState = (event: Event) => record(event.type);
  const onCandidate = (event: RTCPeerConnectionIceEvent) => {
    const type = event.candidate?.type;
    append(event.candidate ? "icecandidate" : "icecandidate-complete", event.candidate ? {
      candidateType: ["host", "srflx", "relay", "prflx"].includes(type ?? "") ? type! : "unknown",
    } : {});
    void sample("icecandidate:stats");
  };
  const onCandidateError = (event: RTCPeerConnectionIceErrorEvent) => {
    append("icecandidateerror", {
      errorCode: Number.isFinite(event.errorCode) ? event.errorCode : undefined,
      url: redactIceUrl(event.url),
    });
    void sample("icecandidateerror:stats");
  };

  for (const event of stateEvents) pc.addEventListener(event, onState);
  pc.addEventListener("icecandidate", onCandidate);
  pc.addEventListener("icecandidateerror", onCandidateError);
  const interval = window.setInterval(() => { void sample("stats"); }, 1000);
  record("created");

  return {
    record,
    snapshot: () => records.map((entry) => ({
      ...entry,
      ...(entry.stats ? { stats: { ...entry.stats, pairStates: { ...entry.stats.pairStates } } } : {}),
    })),
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.clearInterval(interval);
      for (const event of stateEvents) pc.removeEventListener(event, onState);
      pc.removeEventListener("icecandidate", onCandidate);
      pc.removeEventListener("icecandidateerror", onCandidateError);
    },
  };
}
