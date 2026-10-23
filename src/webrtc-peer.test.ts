import { describe, expect, it } from "vitest";

import type { CallIceConfiguration } from "./types";
import {
  peerDiagnostics,
  redactIceUrl,
  sdpCandidateSummary,
  summarizeIce,
} from "./webrtc-peer";

const ice = {
  iceServers: [
    { urls: ["stun:stun.cloudflare.com:3478"] },
    {
      urls: [
        "turn:user:pass@turn.example:3478?transport=udp",
        "turns:turn.example:5349?transport=tcp",
      ],
      username: "user",
      credential: "secret",
    },
  ],
  iceTransportPolicy: "relay",
} as unknown as CallIceConfiguration;

const localSdp = [
  "v=0",
  "a=candidate:1 1 udp 2122260223 192.0.2.10 50000 typ host generation 0",
  "a=candidate:2 1 udp 1686052607 2001:db8::10 50001 typ srflx raddr 0.0.0.0 rport 0",
  "a=candidate:3 1 tcp 1518280447 turn.example 443 typ relay raddr 0.0.0.0 rport 0 tcptype passive",
  "a=end-of-candidates",
].join("\r\n");

const remoteSdp = [
  "v=0",
  "a=candidate:4 1 udp 41885439 203.0.113.20 50002 typ relay raddr 0.0.0.0 rport 0",
].join("\r\n");

function fakePeer() {
  const reports = [
    {
      id: "pair-1",
      type: "candidate-pair",
      state: "succeeded",
      nominated: true,
      bytesSent: 10,
      bytesReceived: 20,
      requestsSent: 3,
      responsesReceived: 2,
      localCandidateId: "local-1",
      remoteCandidateId: "remote-1",
    },
    {
      id: "local-1",
      type: "local-candidate",
      candidateType: "relay",
      protocol: "udp",
      relayProtocol: "udp",
      address: "203.0.113.10",
      port: 50000,
      networkType: "wifi",
      url: "turn:user:pass@turn.example:3478?transport=udp",
    },
    {
      id: "remote-1",
      type: "remote-candidate",
      candidateType: "relay",
      protocol: "tcp",
      relayProtocol: "tcp",
      address: "2001:db8::20",
      port: 50002,
      networkType: "cellular",
      url: "turns:turn.example:5349?transport=tcp",
    },
    {
      id: "transport-1",
      type: "transport",
      state: "connected",
      dtlsState: "connected",
      iceRole: "controlling",
      dtlsRole: "client",
      selectedCandidatePairId: "pair-1",
      bytesSent: 10,
      bytesReceived: 20,
    },
    {
      id: "sctp-1",
      type: "sctp-transport",
      state: "connected",
      messagesSent: 1,
      messagesReceived: 1,
      bytesSent: 10,
      bytesReceived: 20,
    },
    {
      id: "channel-1",
      type: "data-channel",
      state: "open",
      messagesSent: 1,
      messagesReceived: 1,
      bytesSent: 10,
      bytesReceived: 20,
    },
  ];
  return {
    signalingState: "stable",
    connectionState: "connected",
    iceConnectionState: "connected",
    iceGatheringState: "complete",
    canTrickleIceCandidates: true,
    localDescription: { type: "offer", sdp: localSdp },
    remoteDescription: { type: "answer", sdp: remoteSdp },
    getStats: async () => ({
      forEach(callback: (report: Record<string, unknown>) => void) {
        for (const report of reports) callback(report);
      },
    }),
  } as unknown as RTCPeerConnection;
}

describe("WebRTC diagnostics", () => {
  it("redacts ICE credentials but keeps the endpoint and transport", () => {
    expect(redactIceUrl("turn:user:pass@turn.example:3478?transport=udp")).toBe(
      "turn:turn.example:3478?transport=udp",
    );
    expect(redactIceUrl("stun:stun.cloudflare.com:3478")).toBe(
      "stun:stun.cloudflare.com:3478",
    );
  });

  it("summarizes ICE without credentials", () => {
    const summary = summarizeIce(ice);
    expect(summary).toMatchObject({
      transportPolicy: "relay",
      stun: 1,
      turn: 2,
      turns: 1,
      credentialPresent: true,
    });
    expect(JSON.stringify(summary)).not.toContain("secret");
    expect(JSON.stringify(summary)).not.toContain("user:pass");
  });

  it("summarizes SDP candidate types, protocols, and address families", () => {
    expect(sdpCandidateSummary(localSdp)).toMatchObject({
      count: 3,
      types: { host: 1, srflx: 1, relay: 1 },
      protocols: { udp: 2, tcp: 1 },
      families: { ipv4: 1, ipv6: 1, hostname: 1 },
      tcpTypes: { passive: 1 },
      endOfCandidates: true,
    });
  });

  it("includes remote candidates, pair details, transports, and environment", async () => {
    const detail = JSON.parse(
      await peerDiagnostics(fakePeer(), "ice-failed", "path failed", summarizeIce(ice)),
    );
    expect(detail.remoteSdp).toMatchObject({ count: 1, types: { relay: 1 } });
    expect(detail.selectedPair).toMatchObject({
      state: "succeeded",
      local: { side: "local", candidateType: "relay", addressFamily: "ipv4" },
      remote: { side: "remote", candidateType: "relay", addressFamily: "ipv6" },
    });
    expect(detail.pairs).toHaveLength(1);
    expect(detail.transports).toHaveLength(1);
    expect(detail.sctp.state).toBe("connected");
    expect(detail.dataChannel.state).toBe("open");
    expect(detail.pairStates).toEqual({ succeeded: 1 });
    expect(detail.environment.platform).toBeTypeOf("string");
    expect(JSON.stringify(detail)).not.toContain("secret");
    expect(JSON.stringify(detail)).not.toContain("192.0.2.10");
    expect(JSON.stringify(detail)).not.toContain("user:pass");
  });
});
