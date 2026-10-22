import type { CallIceConfiguration } from "./types";
import type { WebRTCSessionPath } from "./webrtc-session";

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
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    const timeout = window.setTimeout(resolve, timeoutMs);
    const onChange = () => {
      if (pc.iceGatheringState === "complete") {
        window.clearTimeout(timeout);
        pc.removeEventListener("icegatheringstatechange", onChange);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", onChange);
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
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new Error("The DataChannel did not open.")),
      timeoutMs,
    );
    channel.addEventListener(
      "open",
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
    channel.addEventListener(
      "error",
      () => {
        window.clearTimeout(timeout);
        reject(new Error("The DataChannel failed."));
      },
      { once: true },
    );
  });
}

/** A redacted summary: counts and booleans only, never credentials. */
export function summarizeIce(ice: CallIceConfiguration): Record<string, unknown> {
  const urls = ice.iceServers.flatMap((server) =>
    Array.isArray(server.urls) ? server.urls : [server.urls],
  );
  return {
    transportPolicy: ice.iceTransportPolicy,
    stun: urls.filter((url) => url.startsWith("stun:") || url.startsWith("stuns:")).length,
    turn: urls.filter((url) => url.startsWith("turn:") || url.startsWith("turns:")).length,
    credentialPresent: ice.iceServers.some((server) => Boolean(server.credential)),
  };
}

/** Connection diagnostics without SDP bodies, candidates, IPs, or credentials. */
export async function peerDiagnostics(
  pc: RTCPeerConnection,
  phase: string,
  error: string,
  iceSummary: Record<string, unknown> | null,
): Promise<string> {
  const stats = await pc.getStats();
  const candidates = new Map<string, Record<string, unknown>>();
  const pairs: Array<Record<string, unknown>> = [];
  let selectedPairId = "";
  let dataChannel: Record<string, unknown> | null = null;
  stats.forEach((report) => {
    const value = report as unknown as Record<string, unknown>;
    const type = value.type;
    if (type === "local-candidate" || type === "remote-candidate") {
      candidates.set(String(value.id), {
        side: type === "local-candidate" ? "local" : "remote",
        candidateType: value.candidateType,
        protocol: value.protocol,
        relayProtocol: value.relayProtocol,
        networkType: value.networkType,
      });
    } else if (type === "candidate-pair") {
      pairs.push({
        id: value.id,
        state: value.state,
        nominated: value.nominated,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
        localCandidateId: value.localCandidateId,
        remoteCandidateId: value.remoteCandidateId,
      });
    } else if (type === "transport" && value.selectedCandidatePairId) {
      selectedPairId = String(value.selectedCandidatePairId);
    } else if (type === "data-channel") {
      dataChannel = {
        state: value.state,
        messagesSent: value.messagesSent,
        messagesReceived: value.messagesReceived,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
      };
    }
  });
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
        local: candidates.get(String(selected.localCandidateId)) ?? null,
        remote: candidates.get(String(selected.remoteCandidateId)) ?? null,
      }
    : null;
  const countCandidates = (sdp?: string) => (sdp?.match(/^a=candidate:/gm) ?? []).length;
  return JSON.stringify(
    {
      timestamp: new Date().toISOString(),
      phase,
      error: error || undefined,
      connectionState: pc.connectionState,
      iceConnectionState: pc.iceConnectionState,
      iceGatheringState: pc.iceGatheringState,
      iceConfiguration: iceSummary,
      localSdpCandidates: countCandidates(pc.localDescription?.sdp),
      remoteSdpCandidates: countCandidates(pc.remoteDescription?.sdp),
      selectedPair,
      candidateTypes: [
        ...new Set(
          [...candidates.values()].map(
            (candidate) => `${candidate.side}:${candidate.candidateType}`,
          ),
        ),
      ],
      pairStates: pairs.reduce<Record<string, number>>((counts, pair) => {
        const state = String(pair.state ?? "unknown");
        counts[state] = (counts[state] ?? 0) + 1;
        return counts;
      }, {}),
      dataChannel,
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
    } else {
      pc.ondatachannel = (event) => {
        if (event.channel.label !== "mesh-reticulum") return;
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
    try {
      this.channel?.close();
    } finally {
      this.pc.close();
    }
  }
}
