import { describe, expect, it, vi, beforeEach } from "vitest";

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
      .mockResolvedValueOnce({ attached: true, channels: ["mesh-reticulum"] });

    const offerer = NativeReconnectPeer.create(ice, "offer");
    expect(await offerer.createOffer()).toBe("offer-sdp");
    await offerer.applyAnswer("remote-answer");
    expect(await offerer.open()).toMatchObject({ attached: true });
    expect(offerer.isAttached()).toBe(true);
    offerer.close();
    expect(native.close).toHaveBeenCalledWith(offerer.sessionId);

    const answerer = NativeReconnectPeer.create(ice, "answer");
    expect(await answerer.createAnswer("remote-offer")).toBe("answer-sdp");
    expect(native.accept).toHaveBeenCalledWith(
      answerer.sessionId,
      "remote-offer",
      ice,
      [],
    );
  });

  it("does not claim attachment when the native bridge never attaches", async () => {
    native.stats.mockResolvedValue({ attached: false });
    const peer = NativeReconnectPeer.create(ice, "offer");
    await expect(peer.open(50)).rejects.toThrow("did not attach");
    peer.close();
  });
});
