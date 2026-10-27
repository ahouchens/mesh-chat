import type { CallIceConfiguration } from "./types";
import type { WebRTCSessionPath } from "./webrtc-session";

/** Mark a gathered SDP as complete so the remote ICE agent need not wait for trickle. */
export function withEndOfCandidates(sdp: string): string {
  if (/(^|\r?\n)a=end-of-candidates(\r?\n|$)/.test(sdp)) return sdp;
  return `${sdp.replace(/\s*$/, "")}\r\na=end-of-candidates\r\n`;
}

/** Extract the single DTLS fingerprint a browser SDP carries. */
export function fingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) {
      return line.slice("a=fingerprint:".length).trim();
    }
  }
  throw new Error("The offer has no DTLS fingerprint.");
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function waitForCandidates(
  pc: RTCPeerConnection,
  timeoutMs = 15000,
): Promise<void> {
  if (pc.iceGatheringState === "complete" || pc.connectionState === "closed") return;
  await new Promise<void>((resolve) => {
    const finish = () => {
      window.clearTimeout(timeout);
      pc.removeEventListener("icegatheringstatechange", onChange);
      pc.removeEventListener("connectionstatechange", onChange);
      resolve();
    };
    const onChange = () => {
      if (pc.iceGatheringState === "complete" || pc.connectionState === "closed") finish();
    };
    const timeout = window.setTimeout(finish, timeoutMs);
    pc.addEventListener("icegatheringstatechange", onChange);
    pc.addEventListener("connectionstatechange", onChange);
    onChange();
  });
}

export async function connectionPath(
  pc: RTCPeerConnection,
): Promise<WebRTCSessionPath> {
  try {
    const stats = await pc.getStats();
    const candidates = new Map<string, string>();
    let selected = "";
    stats.forEach((report) => {
      const value = report as unknown as Record<string, unknown>;
      if (value.type === "local-candidate" || value.type === "remote-candidate") {
        candidates.set(String(value.id), String(value.candidateType ?? ""));
      }
      if (value.type === "transport" && value.selectedCandidatePairId) {
        selected = String(value.selectedCandidatePairId);
      }
      if (
        value.type === "candidate-pair" &&
        value.nominated === true &&
        value.state === "succeeded" &&
        !selected
      ) {
        selected = String(value.id);
      }
    });
    if (!selected) return "unknown";
    let relayed = false;
    stats.forEach((report) => {
      const value = report as unknown as Record<string, unknown>;
      if (value.type !== "candidate-pair" || String(value.id) !== selected) return;
      const local = candidates.get(String(value.localCandidateId));
      const remote = candidates.get(String(value.remoteCandidateId));
      if (local === "relay" || remote === "relay") relayed = true;
    });
    return relayed ? "relayed" : "direct";
  } catch {
    return "unknown";
  }
}

export async function waitForOpen(
  channel: RTCDataChannel,
  timeoutMs = 20000,
): Promise<void> {
  if (channel.readyState === "open") return;
  if (channel.readyState === "closed" || channel.readyState === "closing") {
    throw new Error("The DataChannel closed before it opened.");
  }
  await new Promise<void>((resolve, reject) => {
    const finish = (reason?: Error) => {
      window.clearTimeout(timeout);
      channel.removeEventListener("open", opened);
      channel.removeEventListener("error", failed);
      channel.removeEventListener("close", closed);
      if (reason) reject(reason); else resolve();
    };
    const opened = () => finish();
    const failed = () => finish(new Error("The DataChannel failed."));
    const closed = () => finish(new Error("The DataChannel closed before it opened."));
    const timeout = window.setTimeout(() => finish(new Error("The DataChannel did not open.")), timeoutMs);
    channel.addEventListener("open", opened);
    channel.addEventListener("error", failed);
    channel.addEventListener("close", closed);
  });
}

/** Remove any userinfo from an ICE URL without hiding its host or transport. */
export function redactIceUrl(value: unknown): string {
  if (typeof value !== "string") return "";
  const match = value.match(/^([a-z][a-z0-9+.-]*:)(.*)$/i);
  if (!match) return "";
  return `${match[1].toLowerCase()}${(match[2].split("@").pop() ?? "")}`;
}

function addressFamily(value: unknown): string {
  if (typeof value !== "string" || !value) return "unknown";
  if (value.includes(":")) return "ipv6";
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(value)) return "ipv4";
  return "hostname";
}

/** Count candidate properties in an SDP without emitting addresses. */
export function sdpCandidateSummary(sdp?: string): Record<string, unknown> {
  const lines = (sdp ?? "").split(/\r?\n/).filter((line) => line.startsWith("a=candidate:"));
  const types: Record<string, number> = {};
  const protocols: Record<string, number> = {};
  const families: Record<string, number> = {};
  const tcpTypes: Record<string, number> = {};
  for (const line of lines) {
    const tokens = line.trim().split(/\s+/);
    const protocol = (tokens[2] ?? "unknown").toLowerCase();
    const typeIndex = tokens.indexOf("typ");
    const type = typeIndex >= 0 ? (tokens[typeIndex + 1] ?? "unknown") : "unknown";
    const tcpTypeIndex = tokens.indexOf("tcptype");
    const tcpType = tcpTypeIndex >= 0 ? (tokens[tcpTypeIndex + 1] ?? "unknown") : undefined;
    types[type] = (types[type] ?? 0) + 1;
    protocols[protocol] = (protocols[protocol] ?? 0) + 1;
    const family = addressFamily(tokens[4]);
    families[family] = (families[family] ?? 0) + 1;
    if (tcpType) tcpTypes[tcpType] = (tcpTypes[tcpType] ?? 0) + 1;
  }
  return {
    count: lines.length,
    types,
    protocols,
    families,
    tcpTypes,
    endOfCandidates: (sdp ?? "").includes("a=end-of-candidates"),
  };
}

/** Describe SDP structure without exposing ICE passwords or fingerprints. */
export function sdpStructure(sdp?: string): Record<string, unknown> {
  const lines = (sdp ?? "").split(/\r?\n/);
  const values = (prefix: string) =>
    lines.filter((line) => line.startsWith(prefix)).map((line) => line.slice(prefix.length).trim());
  return {
    media: lines.filter((line) => line.startsWith("m=")),
    bundle: values("a=group:BUNDLE "),
    mids: values("a=mid:"),
    iceUfrags: values("a=ice-ufrag:"),
    icePwdLengths: values("a=ice-pwd:").map((value) => value.length),
    setup: values("a=setup:"),
    iceOptions: values("a=ice-options:"),
    endOfCandidates: lines.includes("a=end-of-candidates"),
  };
}

/** A redacted summary: counts, sanitized endpoint URLs, and booleans. */
export function summarizeIce(ice: CallIceConfiguration): Record<string, unknown> {
  const urls = ice.iceServers.flatMap((server) =>
    Array.isArray(server.urls) ? server.urls : [server.urls],
  );
  const lower = urls.map((url) => url.toLowerCase());
  return {
    transportPolicy: ice.iceTransportPolicy,
    stun: lower.filter((url) => url.startsWith("stun:") || url.startsWith("stuns:")).length,
    turn: lower.filter((url) => url.startsWith("turn:") || url.startsWith("turns:")).length,
    turns: lower.filter((url) => url.startsWith("turns:")).length,
    credentialPresent: ice.iceServers.some((server) => Boolean(server.credential)),
    urls: urls.map(redactIceUrl),
  };
}

function candidateDetails(value: Record<string, unknown>): Record<string, unknown> {
  return {
    id: String(value.id ?? ""),
    side: value.type === "local-candidate" ? "local" : "remote",
    candidateType: value.candidateType,
    protocol: value.protocol,
    relayProtocol: value.relayProtocol,
    addressFamily: addressFamily(value.address),
    port: value.port,
    networkType: value.networkType,
    url: redactIceUrl(value.url),
  };
}

/** Connection diagnostics without raw addresses, SDP bodies, or credentials. */
export async function peerDiagnostics(
  pc: RTCPeerConnection,
  phase: string,
  error: string,
  iceSummary: Record<string, unknown> | null,
): Promise<string> {
  const stats = await pc.getStats();
  const candidates = new Map<string, Record<string, unknown>>();
  const pairs: Array<Record<string, unknown>> = [];
  const transports: Array<Record<string, unknown>> = [];
  let selectedPairId = "";
  let dataChannel: Record<string, unknown> | null = null;
  let sctp: Record<string, unknown> | null = null;
  stats.forEach((report) => {
    const value = report as unknown as Record<string, unknown>;
    const type = value.type;
    if (type === "local-candidate" || type === "remote-candidate") {
      candidates.set(String(value.id), candidateDetails(value));
    } else if (type === "candidate-pair") {
      pairs.push({
        id: value.id,
        state: value.state,
        nominated: value.nominated,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
        requestsSent: value.requestsSent,
        responsesReceived: value.responsesReceived,
        localCandidateId: value.localCandidateId,
        remoteCandidateId: value.remoteCandidateId,
      });
    } else if (type === "transport") {
      if (value.selectedCandidatePairId) {
        selectedPairId = String(value.selectedCandidatePairId);
      }
      transports.push({
        state: value.state,
        dtlsState: value.dtlsState,
        iceRole: value.iceRole,
        dtlsRole: value.dtlsRole,
        selectedCandidatePairId: value.selectedCandidatePairId,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
      });
    } else if (type === "data-channel") {
      dataChannel = {
        state: value.state,
        messagesSent: value.messagesSent,
        messagesReceived: value.messagesReceived,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
      };
    } else if (type === "sctp-transport") {
      sctp = {
        state: value.state,
        messagesSent: value.messagesSent,
        messagesReceived: value.messagesReceived,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
      };
    }
  });
  for (const pair of pairs) {
    pair.local = candidates.get(String(pair.localCandidateId)) ?? null;
    pair.remote = candidates.get(String(pair.remoteCandidateId)) ?? null;
  }
  const selected =
    pairs.find((pair) => pair.id === selectedPairId) ??
    pairs.find((pair) => pair.nominated === true && pair.state === "succeeded") ??
    pairs.find((pair) => pair.state === "succeeded") ??
    null;
  const selectedPair = selected
    ? {
        state: selected.state,
        nominated: selected.nominated,
        bytesSent: selected.bytesSent,
        bytesReceived: selected.bytesReceived,
        local: selected.local ?? null,
        remote: selected.remote ?? null,
      }
    : null;
  return JSON.stringify(
    {
      timestamp: new Date().toISOString(),
      phase,
      error: error || undefined,
      environment: {
        userAgent: typeof navigator === "undefined" ? "unavailable" : navigator.userAgent,
        platform: typeof navigator === "undefined" ? "unavailable" : navigator.platform,
        language: typeof navigator === "undefined" ? "unavailable" : navigator.language,
      },
      signalingState: pc.signalingState,
      connectionState: pc.connectionState,
      iceConnectionState: pc.iceConnectionState,
      iceGatheringState: pc.iceGatheringState,
      canTrickleIceCandidates: pc.canTrickleIceCandidates,
      localDescriptionType: pc.localDescription?.type ?? null,
      remoteDescriptionType: pc.remoteDescription?.type ?? null,
      iceConfiguration: iceSummary,
      localSdp: {
        ...sdpCandidateSummary(pc.localDescription?.sdp),
        structure: sdpStructure(pc.localDescription?.sdp),
      },
      remoteSdp: {
        ...sdpCandidateSummary(pc.remoteDescription?.sdp),
        structure: sdpStructure(pc.remoteDescription?.sdp),
      },
      selectedPair,
      candidateTypes: [
        ...new Set(
          [...candidates.values()].map(
            (candidate) => `${candidate.side}:${candidate.candidateType}`,
          ),
        ),
      ],
      candidates: [...candidates.values()],
      pairs,
      pairStates: pairs.reduce<Record<string, number>>((counts, pair) => {
        const state = String(pair.state ?? "unknown");
        counts[state] = (counts[state] ?? 0) + 1;
        return counts;
      }, {}),
      transports,
      dataChannel,
      sctp,
    },
    null,
    2,
  );
}

/**
 * One fresh WebRTC transport for automatic reconnect.
 *
 * The service owns signaling and trust; this class only owns the peer
 * connection. Every reconnect creates a new instance: no SDP, ICE credential,
 * or DataChannel is reused from an earlier attempt.
 */
export class ReconnectPeer {
  readonly pc: RTCPeerConnection;
  control: RTCDataChannel | null = null;
  onControl: ((control: RTCDataChannel) => void) | null = null;
  private channel: RTCDataChannel | null = null;

  private constructor(
    pc: RTCPeerConnection,
    readonly role: "offer" | "answer",
  ) {
    this.pc = pc;
  }

  static create(
    ice: CallIceConfiguration,
    role: "offer" | "answer",
  ): ReconnectPeer {
    const pc = new RTCPeerConnection({
      iceServers: ice.iceServers,
      iceTransportPolicy: ice.iceTransportPolicy,
    });
    const peer = new ReconnectPeer(pc, role);
    if (role === "offer") {
      peer.channel = pc.createDataChannel("mesh-reticulum", { ordered: true });
      peer.channel.binaryType = "arraybuffer";
      peer.control = pc.createDataChannel("meshchat-reconnect", { ordered: true });
    } else {
      pc.ondatachannel = (event) => {
        if (event.channel.label === "meshchat-reconnect") {
          if (peer.control) event.channel.close();
          else {
            peer.control = event.channel;
            peer.onControl?.(event.channel);
          }
          return;
        }
        if (event.channel.label !== "mesh-reticulum" || peer.channel) {
          event.channel.close();
          return;
        }
        event.channel.binaryType = "arraybuffer";
        peer.channel = event.channel;
      };
    }
    return peer;
  }

  async createOffer(): Promise<string> {
    const offer = await this.pc.createOffer();
    await this.pc.setLocalDescription(offer);
    await waitForCandidates(this.pc);
    const sdp = this.pc.localDescription?.sdp;
    if (!sdp) throw new Error("Could not create the WebRTC reconnect offer.");
    return sdp;
  }

  async createAnswer(remoteOffer: string): Promise<string> {
    await this.pc.setRemoteDescription({ type: "offer", sdp: remoteOffer });
    const answer = await this.pc.createAnswer();
    await this.pc.setLocalDescription(answer);
    await waitForCandidates(this.pc);
    const sdp = this.pc.localDescription?.sdp;
    if (!sdp) throw new Error("Could not create the WebRTC reconnect answer.");
    return sdp;
  }

  async applyAnswer(remoteAnswer: string): Promise<void> {
    await this.pc.setRemoteDescription({ type: "answer", sdp: remoteAnswer });
  }

  async open(timeoutMs = 20000): Promise<RTCDataChannel> {
    const started = Date.now();
    while (!this.channel) {
      if (Date.now() - started > timeoutMs) {
        throw new Error("The reconnect DataChannel did not arrive.");
      }
      await sleep(50);
    }
    await waitForOpen(this.channel, timeoutMs);
    return this.channel;
  }

  path(): Promise<WebRTCSessionPath> {
    return connectionPath(this.pc);
  }

  close(): void {
    this.onControl = null;
    try {
      this.control?.close();
      this.channel?.close();
    } finally {
      this.pc.close();
    }
  }
}
