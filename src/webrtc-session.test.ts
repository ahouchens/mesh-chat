import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeWebRTCSession,
  getWebRTCSession,
  getWebRTCSessionByKey,
  getWebRTCSessionCount,
  getWebRTCSessionForContact,
  getWebRTCSessionWithControl,
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

  it("keeps reconnect control channels out of onboarding actions", () => {
    const onboarding = session("pairing", 1);
    onboarding.control = { readyState: "open", close: vi.fn() } as unknown as RTCDataChannel;
    const reconnect = session("restored", 2);
    reconnect.control = { readyState: "open", close: vi.fn() } as unknown as RTCDataChannel;
    reconnect.controlPurpose = "reconnect";
    setWebRTCSession(onboarding);
    setWebRTCSession(reconnect);
    expect(getWebRTCSessionWithControl()).toBe(onboarding);
    onboarding.control.close();
    Object.assign(onboarding.control, { readyState: "closed" });
    expect(getWebRTCSessionWithControl()).toBeNull();
  });

  it("preserves a replacement registered while another session is detaching", async () => {
    const a = session("peer-a", 1);
    const previous = session("peer-b", 2);
    const replacement = session("peer-b", 3);
    replacement.bridge = { ...replacement.bridge, bridgeId: "replacement-b" };
    let finishDetach!: () => void;
    a.bridge.close = vi.fn(() => new Promise<void>((resolve) => { finishDetach = resolve; }));
    setWebRTCSession(a);
    setWebRTCSession(previous);
    const closing = closeWebRTCSession();
    setWebRTCSession(replacement);
    finishDetach();
    await closing;

    expect(getWebRTCSessionByKey("peer-b")).toBe(replacement);
    expect(getWebRTCSession()).toBe(replacement);
    expect(previous.bridge.close).toHaveBeenCalledTimes(1);
    expect(previous.pc.close).toHaveBeenCalledTimes(1);
    expect(replacement.bridge.close).not.toHaveBeenCalled();
    expect(replacement.pc.close).not.toHaveBeenCalled();
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

  it("retires all transports synchronously even when a native detach is still pending", async () => {
    const a = session("onboarding:a", 1);
    const b = session("restored:b", 2);
    let finish!: () => void;
    a.bridge.close = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    setWebRTCSession(a);
    setWebRTCSession(b);
    const closing = closeWebRTCSession();
    expect(getWebRTCSessionCount()).toBe(0);
    expect(a.pc.close).toHaveBeenCalledTimes(1);
    expect(b.pc.close).toHaveBeenCalledTimes(1);
    expect(b.bridge.close).toHaveBeenCalledTimes(1);
    finish();
    await closing;
  });
});
