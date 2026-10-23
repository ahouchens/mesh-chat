import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startPeerTrace } from "./webrtc-trace";

function fakePeer() {
  return Object.assign(new EventTarget(), {
    connectionState: "new",
    iceConnectionState: "new",
    iceGatheringState: "new",
    signalingState: "stable",
    getStats: vi.fn().mockResolvedValue(new Map()),
  }) as unknown as RTCPeerConnection & { getStats: ReturnType<typeof vi.fn> };
}

function emit(pc: RTCPeerConnection, type: string, properties: Record<string, unknown> = {}) {
  pc.dispatchEvent(Object.assign(new Event(type), properties));
}

describe("peer trace", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("retains earlier pairing evidence after pairs disappear, within a fixed bound", async () => {
    const pc = fakePeer();
    pc.getStats.mockResolvedValueOnce(new Map<string, unknown>([
      ["pair", { type: "candidate-pair", state: "in-progress", requestsSent: 7, responsesReceived: 0 }],
      ["remote", { type: "remote-candidate", address: "192.0.2.50" }],
    ]));
    const trace = startPeerTrace(pc);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    for (let i = 0; i < 150; i++) trace.record("waiting-for-answer");
    await vi.advanceTimersByTimeAsync(1000);

    const records = trace.snapshot();
    expect(records).toHaveLength(100);
    expect(records[0].event).toBe("created");
    expect(records.find((entry) => entry.stats?.pairs === 1)?.stats).toEqual({
      pairs: 1, remoteCandidates: 1, pairStates: { "in-progress": 1 }, requestsSent: 7, responsesReceived: 0,
    });
    expect(records.at(-1)?.stats?.pairs).toBe(0);
    expect(JSON.stringify(records)).not.toContain("192.0.2.50");
    trace.stop();
  });

  it("removes timers and event listeners and ignores pending stats after stop", async () => {
    const pc = fakePeer();
    let complete!: (report: Map<string, unknown>) => void;
    pc.getStats.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    const trace = startPeerTrace(pc);
    expect(vi.getTimerCount()).toBe(1);
    trace.stop();
    trace.stop();
    const before = trace.snapshot();
    complete(new Map([["pair", { type: "candidate-pair", state: "succeeded" }]]));
    emit(pc, "iceconnectionstatechange");
    emit(pc, "icecandidate", { candidate: { type: "relay" } });
    emit(pc, "icecandidateerror", { errorCode: 701, url: "turn:example.com" });
    trace.record("ignored");
    await vi.advanceTimersByTimeAsync(5000);
    expect(vi.getTimerCount()).toBe(0);
    expect(pc.getStats).toHaveBeenCalledTimes(1);
    expect(trace.snapshot()).toEqual(before);
  });

  it("records redacted ICE events and state samples without raw candidate or error data", async () => {
    const pc = fakePeer();
    const trace = startPeerTrace(pc);
    await vi.advanceTimersByTimeAsync(0);
    emit(pc, "icecandidate", { candidate: { type: "relay", candidate: "private-candidate", address: "192.168.1.2" } });
    emit(pc, "icecandidate", { candidate: null });
    emit(pc, "icecandidateerror", {
      errorCode: 701, url: "turn:user:password@relay.example:3478?transport=udp",
      address: "192.168.1.2", errorText: "credential: hidden-secret",
    });
    Object.assign(pc, { iceConnectionState: "checking" });
    emit(pc, "iceconnectionstatechange");
    await vi.advanceTimersByTimeAsync(0);
    const records = trace.snapshot();
    expect(records.find((entry) => entry.event === "icecandidate")).toMatchObject({ candidateType: "relay" });
    expect(records.some((entry) => entry.event === "icecandidate-complete")).toBe(true);
    expect(records.find((entry) => entry.event === "icecandidateerror")).toMatchObject({
      errorCode: 701, url: "turn:relay.example:3478?transport=udp",
    });
    expect(records.find((entry) => entry.event === "iceconnectionstatechange")).toMatchObject({ iceConnectionState: "checking" });
    expect(JSON.stringify(records)).not.toMatch(/private-candidate|192\.168|hidden-secret|password|user:/);
    trace.stop();
  });

  it("catches stats failures and keeps snapshots independent from later mutations", async () => {
    const pc = fakePeer();
    pc.getStats.mockRejectedValueOnce(new Error("private-secret"));
    const trace = startPeerTrace(pc);
    await vi.advanceTimersByTimeAsync(0);
    const before = trace.snapshot();
    expect(before.at(-1)?.event).toBe("stats-unavailable");
    await vi.advanceTimersByTimeAsync(1000);
    const current = trace.snapshot();
    current.at(-1)!.stats!.pairStates.failed = 99;
    expect(trace.snapshot().at(-1)?.stats?.pairStates).toEqual({});
    expect(before).toHaveLength(2);
    expect(JSON.stringify(trace.snapshot())).not.toContain("private-secret");
    trace.stop();
  });
});
