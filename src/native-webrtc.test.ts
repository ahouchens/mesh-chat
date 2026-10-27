import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CallIceConfiguration } from "./types";

const mocks = vi.hoisted(() => ({ serviceCommand: vi.fn() }));

vi.mock("./api", () => ({ serviceCommand: mocks.serviceCommand }));

import {
  closeNativeWebRTCSessions,
  nativeWebRTCAccept,
  nativeWebRTCClose,
  nativeWebRTCOffer,
} from "./native-webrtc";

const ice: CallIceConfiguration = {
  iceServers: [{ urls: "stun:example.test:3478" }],
  iceTransportPolicy: "all",
};

describe("native WebRTC session registry", () => {
  beforeEach(async () => {
    mocks.serviceCommand.mockResolvedValue({});
    await closeNativeWebRTCSessions();
    mocks.serviceCommand.mockReset();
  });

  it.each([
    ["offer", "all"], ["answer", "all"], ["offer", "one"], ["answer", "one"],
  ])("retires a pending %s after closing %s sessions", async (role, scope) => {
    let complete!: (value: unknown) => void;
    mocks.serviceCommand.mockImplementation((command) => command === "native_webrtc_close"
      ? Promise.resolve({}) : new Promise((resolve) => { complete = resolve; }));
    const pending = role === "offer"
      ? nativeWebRTCOffer("pending-session", ice)
      : nativeWebRTCAccept("pending-session", "offer", ice);
    const cancelled = expect(pending).rejects.toThrow(/cancelled/);
    if (scope === "all") await closeNativeWebRTCSessions();
    else await nativeWebRTCClose("pending-session");
    complete({ ok: true, sdp: "late-sdp", fingerprint: "sha-256 AA" });
    await cancelled;
    expect(mocks.serviceCommand.mock.calls.filter(([command]) => command === "native_webrtc_close")).toHaveLength(2);
  });

  it("tracks offered sessions and closes them on an explicit teardown", async () => {
    mocks.serviceCommand.mockResolvedValueOnce({
      ok: true,
      sdp: "offer-sdp",
      fingerprint: "sha-256 AA",
    });
    await nativeWebRTCOffer("onboarding-offer-1", ice);
    mocks.serviceCommand.mockResolvedValueOnce({});

    await closeNativeWebRTCSessions();

    expect(mocks.serviceCommand).toHaveBeenNthCalledWith(1, "native_webrtc_offer", {
      session_id: "onboarding-offer-1",
      ice: { iceTransportPolicy: "all", iceServers: [{ urls: ["stun:example.test:3478"] }] },
      channels: [
        { label: "mesh-reticulum", binary: true, ordered: true },
        { label: "meshchat-reconnect", binary: false, ordered: true },
      ],
    });
    expect(mocks.serviceCommand).toHaveBeenNthCalledWith(2, "native_webrtc_close", {
      session_id: "onboarding-offer-1",
    });
  });

  it("tracks accepted sessions and forgets them when closed", async () => {
    mocks.serviceCommand.mockResolvedValueOnce({
      ok: true,
      sdp: "answer-sdp",
      fingerprint: "sha-256 BB",
    });
    await nativeWebRTCAccept("onboarding-answer-1", "remote-offer", ice);
    mocks.serviceCommand.mockResolvedValueOnce({});

    await nativeWebRTCClose("onboarding-answer-1");
    await closeNativeWebRTCSessions();

    expect(mocks.serviceCommand).toHaveBeenCalledTimes(2);
    expect(mocks.serviceCommand).toHaveBeenNthCalledWith(2, "native_webrtc_close", {
      session_id: "onboarding-answer-1",
    });
  });
});
