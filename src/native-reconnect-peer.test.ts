import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const native = vi.hoisted(() => ({
  offer: vi.fn(),
  accept: vi.fn(),
  apply: vi.fn(),
  stats: vi.fn(),
  close: vi.fn(),
}));

vi.mock("./native-webrtc", () => ({
  NATIVE_RECONNECT_CHANNELS: [],
  nativeWebRTCOffer: native.offer,
  nativeWebRTCAccept: native.accept,
  nativeWebRTCApplyAnswer: native.apply,
  nativeWebRTCStats: native.stats,
  nativeWebRTCClose: native.close,
}));

import { NativeReconnectPeer } from "./native-reconnect-peer";
import type { CallIceConfiguration } from "./types";

const ice: CallIceConfiguration = {
  iceServers: [{ urls: "stun:example.test:3478" }],
  iceTransportPolicy: "all",
};

describe("NativeReconnectPeer", () => {
  afterEach(() => vi.useRealTimers());
  beforeEach(() => {
    native.offer.mockReset();
    native.accept.mockReset();
    native.apply.mockReset();
    native.stats.mockReset();
    native.close.mockReset();
    native.close.mockResolvedValue({});
  });

  it("uses the native offer/answer and waits for the Python attachment", async () => {
    native.offer.mockResolvedValue({ ok: true, sdp: "offer-sdp", fingerprint: "sha-256 AA" });
    native.accept.mockResolvedValue({ ok: true, sdp: "answer-sdp", fingerprint: "sha-256 BB" });
    native.apply.mockResolvedValue({ ok: true });
    native.stats
      .mockResolvedValueOnce({ attached: false })
      .mockResolvedValueOnce({ attached: true, channels: ["mesh-reticulum"], data_channel_state: "open", ice_connection_state: "connected" });

    const offerer = NativeReconnectPeer.create(ice, "offer");
    expect(await offerer.createOffer()).toBe("offer-sdp");
    await offerer.applyAnswer("remote-answer");
    expect(await offerer.open()).toMatchObject({ attached: true });
    expect(offerer.isAttached()).toBe(true);
    offerer.close();
    expect(native.close).toHaveBeenCalledWith(offerer.sessionId);

    const answerer = NativeReconnectPeer.create(ice, "answer", "profile-1");
    expect(await answerer.createAnswer("remote-offer")).toBe("answer-sdp");
    expect(native.accept).toHaveBeenCalledWith(
      answerer.sessionId,
      "remote-offer",
      ice,
      [],
      "profile-1",
    );
  });

  it("does not claim attachment when the native bridge never attaches", async () => {
    native.stats.mockResolvedValue({ attached: false });
    const peer = NativeReconnectPeer.create(ice, "offer");
    await expect(peer.open(50)).rejects.toThrow("did not attach");
    peer.close();
  });

  it.each([
    { attached: true, ice_connection_state: "failed", data_channel_state: "open" },
    { attached: true, ice_connection_state: "connected", data_channel_state: "closed" },
    { attached: false, ice_connection_state: "connected", data_channel_state: "open" },
  ])("retires a previously attached peer when current native health is %j", async (stats) => {
    native.stats.mockResolvedValue({ attached: true, ice_connection_state: "connected", data_channel_state: "open" });
    const peer = NativeReconnectPeer.create(ice, "offer");
    await peer.open();
    native.stats.mockResolvedValue(stats);
    await peer.refreshHealth();
    expect(peer.isAttached()).toBe(false);
    expect(native.close).toHaveBeenCalledWith(peer.sessionId);
  });

  it("preserves a temporary disconnection, resets on recovery and retires a persistent loss", async () => {
    vi.useFakeTimers();
    native.stats.mockResolvedValue({ attached: true, ice_connection_state: "connected", data_channel_state: "open" });
    const peer = NativeReconnectPeer.create(ice, "offer");
    await peer.open();
    native.stats.mockResolvedValue({ attached: true, ice_connection_state: "disconnected", data_channel_state: "open" });
    await peer.refreshHealth();
    await vi.advanceTimersByTimeAsync(9_000);
    await peer.refreshHealth();
    expect(peer.isAttached()).toBe(true);
    native.stats.mockResolvedValue({ attached: true, ice_connection_state: "connected", data_channel_state: "open" });
    await peer.refreshHealth();
    native.stats.mockResolvedValue({ attached: true, ice_connection_state: "disconnected", data_channel_state: "open" });
    await peer.refreshHealth();
    await vi.advanceTimersByTimeAsync(9_999);
    await peer.refreshHealth();
    expect(peer.isAttached()).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    await peer.refreshHealth();
    expect(peer.isAttached()).toBe(false);
  });
});
