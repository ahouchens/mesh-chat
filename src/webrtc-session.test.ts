import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeWebRTCSession,
  getWebRTCSession,
  getWebRTCSessionByKey,
  getWebRTCSessionCount,
  getWebRTCSessionForContact,
  getWebRTCSessions,
  setWebRTCSession,
  updateWebRTCSessionContact,
  type WebRTCSession,
} from "./webrtc-session";

function session(key: string, createdAt = 1): WebRTCSession {
  const bridge = { bridgeId: `bridge-${key}`, maxPacket: 500, close: vi.fn(async () => undefined) };
  const channel = { close: vi.fn() } as unknown as RTCDataChannel;
  const pc = { close: vi.fn() } as unknown as RTCPeerConnection;
  return {
    key,
    bridge,
    channel,
    pc,
    control: null,
    path: "direct",
    createdAt,
    approvalPending: false,
  };
}

describe("WebRTC session registry", () => {
  afterEach(async () => {
    await closeWebRTCSession();
  });

  it("keeps every peer transport alive and close only the requested session", async () => {
    const a = session("peer-a", 1);
    const b = session("peer-b", 2);
    setWebRTCSession(a);
    setWebRTCSession(b);

    expect(getWebRTCSessionCount()).toBe(2);
    expect(getWebRTCSessions().map((item) => item.key)).toEqual(["peer-a", "peer-b"]);
    expect(getWebRTCSession()?.key).toBe("peer-b");
    expect(a.bridge.close).not.toHaveBeenCalled();
    expect(b.bridge.close).not.toHaveBeenCalled();

    await closeWebRTCSession("peer-a");
    expect(a.bridge.close).toHaveBeenCalledTimes(1);
    expect(a.channel.close).toHaveBeenCalledTimes(1);
    expect(a.pc.close).toHaveBeenCalledTimes(1);
    expect(b.bridge.close).not.toHaveBeenCalled();
    expect(getWebRTCSessionByKey("peer-a")).toBeNull();
    expect(getWebRTCSession()?.key).toBe("peer-b");
    expect(getWebRTCSessionCount()).toBe(1);
  });

  it("binds contacts to one session and supports per-contact lookup", () => {
    const a = session("peer-a", 1);
    const b = session("peer-b", 2);
    setWebRTCSession(a);
    setWebRTCSession(b);
    updateWebRTCSessionContact("contact-a", "peer-a");
    expect(getWebRTCSessionForContact("contact-a")?.key).toBe("peer-a");
    expect(getWebRTCSessionForContact("contact-b")).toBeNull();
    expect(getWebRTCSession()?.key).toBe("peer-b");
  });

  it("closes all transports on a global disconnect even if one bridge close fails", async () => {
    const a = session("peer-a", 1);
    const b = session("peer-b", 2);
    (a.bridge.close as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("already gone"));
    setWebRTCSession(a);
    setWebRTCSession(b);
    await closeWebRTCSession();
    expect(a.pc.close).toHaveBeenCalledTimes(1);
    expect(b.pc.close).toHaveBeenCalledTimes(1);
    expect(getWebRTCSessionCount()).toBe(0);
    expect(getWebRTCSession()).toBeNull();
  });
});
