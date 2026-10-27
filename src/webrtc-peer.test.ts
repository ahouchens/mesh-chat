import { afterEach, describe, expect, it, vi } from "vitest";

import type { CallIceConfiguration } from "./types";
import {
  peerDiagnostics,
  redactIceUrl,
  sdpCandidateSummary,
  sdpStructure,
  summarizeIce,
  withEndOfCandidates,
  ReconnectPeer,
  waitForCandidates,
  waitForOpen,
} from "./webrtc-peer";

afterEach(() => vi.unstubAllGlobals());

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
  it("ends candidate gathering when the peer closes", async () => {
    const peer = Object.assign(new EventTarget(), { iceGatheringState: "gathering", connectionState: "connecting" });
    const waiting = waitForCandidates(peer as unknown as RTCPeerConnection, 60_000);
    peer.connectionState = "closed";
    peer.dispatchEvent(new Event("connectionstatechange"));
    await waiting;
  });

  it("rejects a channel that closes before opening without waiting for its timeout", async () => {
    const channel = Object.assign(new EventTarget(), { readyState: "connecting" });
    const waiting = waitForOpen(channel as unknown as RTCDataChannel, 60_000);
    const rejected = expect(waiting).rejects.toThrow("closed before it opened");
    channel.readyState = "closed";
    channel.dispatchEvent(new Event("close"));
    await rejected;
  });

  it("marks gathered SDP as complete exactly once", () => {
    const unmarked = localSdp.replace("\r\na=end-of-candidates", "");
    const marked = withEndOfCandidates(unmarked);
    expect(marked.trimEnd().endsWith("a=end-of-candidates")).toBe(true);
    expect(withEndOfCandidates(marked)).toBe(marked);
  });

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

  it("describes SDP structure without exposing the ICE password", () => {
    const structure = sdpStructure([
      "v=0",
      "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
      "a=mid:0",
      "a=ice-ufrag:localUfrag",
      "a=ice-pwd:super-secret-password",
      "a=setup:actpass",
      "a=ice-options:trickle",
      "a=group:BUNDLE 0",
    ].join("\r\n"));
    expect(structure).toMatchObject({
      media: ["m=application 9 UDP/DTLS/SCTP webrtc-datachannel"],
      bundle: ["0"],
      mids: ["0"],
      iceUfrags: ["localUfrag"],
      icePwdLengths: [21],
      setup: ["actpass"],
      iceOptions: ["trickle"],
      endOfCandidates: false,
    });
    expect(JSON.stringify(structure)).not.toContain("super-secret-password");
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

describe("reconnect transport channels", () => {
  function installPeer() {
    const channel = (label: string) => ({ label, readyState: "open", close: vi.fn(), binaryType: "blob" });
    const native = {
      createDataChannel: vi.fn((label: string) => channel(label)),
      ondatachannel: null as ((event: RTCDataChannelEvent) => void) | null,
      close: vi.fn(),
    };
    vi.stubGlobal("RTCPeerConnection", vi.fn(function () { return native; }));
    return { native, channel };
  }

  it("creates only the Reticulum and capability channels and closes both", () => {
    const { native } = installPeer();
    const peer = ReconnectPeer.create(ice, "offer");
    expect(native.createDataChannel.mock.calls.map(([label]) => label)).toEqual(["mesh-reticulum", "meshchat-reconnect"]);
    expect(peer.control?.label).toBe("meshchat-reconnect");
    peer.close();
    for (const created of native.createDataChannel.mock.results) expect(created.value.close).toHaveBeenCalledTimes(1);
    expect(native.close).toHaveBeenCalledTimes(1);
  });

  it("accepts a late capability channel once and rejects onboarding or duplicate channels", async () => {
    const { native, channel } = installPeer();
    const peer = ReconnectPeer.create(ice, "answer");
    const onControl = vi.fn();
    peer.onControl = onControl;
    const transport = channel("mesh-reticulum");
    const control = channel("meshchat-reconnect");
    const duplicate = channel("meshchat-reconnect");
    const onboarding = channel("meshchat-onboarding");
    const deliver = (value: ReturnType<typeof channel>) => native.ondatachannel?.({ channel: value } as unknown as RTCDataChannelEvent);
    deliver(transport);
    expect(await peer.open()).toBe(transport);
    deliver(control);
    deliver(duplicate);
    deliver(onboarding);
    expect(peer.control).toBe(control);
    expect(onControl).toHaveBeenCalledTimes(1);
    expect(onControl).toHaveBeenCalledWith(control);
    expect(duplicate.close).toHaveBeenCalledTimes(1);
    expect(onboarding.close).toHaveBeenCalledTimes(1);
    expect(control.close).not.toHaveBeenCalled();
  });
});
