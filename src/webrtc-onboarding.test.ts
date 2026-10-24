import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  onServiceEvent: vi.fn(),
}));

vi.mock("./api", () => ({
  serviceCommand: mocks.serviceCommand,
  onServiceEvent: mocks.onServiceEvent,
}));

const serviceCommand = mocks.serviceCommand;
const onServiceEvent = mocks.onServiceEvent;

import {
  attachWebRTCBridge,
  base64ToBytes,
  bytesToBase64,
  isWindowsWebRTCPlatform,
  shouldAutoCloseWebRTCOnboarding,
  webRTCWindowsChecklist,
} from "./webrtc-onboarding";

function fakeChannel() {
  const channel = {
    readyState: "open",
    binaryType: "blob",
    send: vi.fn(),
    close: vi.fn(),
    onmessage: null as ((event: MessageEvent) => void) | null,
    onclose: null as (() => void) | null,
    onerror: null as (() => void) | null,
  };
  return channel as unknown as RTCDataChannel & {
    send: ReturnType<typeof vi.fn>;
    close: ReturnType<typeof vi.fn>;
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function closeChannel(channel: RTCDataChannel) {
  Object.defineProperty(channel, "readyState", { value: "closed", configurable: true });
  channel.onclose?.call(channel, new Event("close"));
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("WebRTC DataChannel pump", () => {
  it("rejects and detaches when the channel closes during native attachment", async () => {
    const native = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    serviceCommand.mockImplementation(async (command: string) =>
      command === "webrtc_attach" ? native.promise : { state: "closed" });
    const channel = fakeChannel();
    const onClosed = vi.fn();
    const attaching = attachWebRTCBridge(channel, { onClosed });
    const rejected = expect(attaching).rejects.toThrow(/closed/);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach"));
    closeChannel(channel);
    native.resolve({ bridge_id: "closed-native", max_packet: 1064, state: "online" });
    await rejected;

    expect(serviceCommand.mock.calls.filter(([command]) => command === "webrtc_detach")).toEqual([
      ["webrtc_detach", { bridge_id: "closed-native" }],
    ]);
    expect(onClosed.mock.calls).toEqual([["closed-native"]]);
    expect(onServiceEvent).not.toHaveBeenCalled();
  });

  it("releases a subscription that finishes after the channel has closed", async () => {
    const subscription = deferred<() => void>();
    const unlisten = vi.fn();
    onServiceEvent.mockReturnValueOnce(subscription.promise);
    serviceCommand.mockImplementation(async (command: string) =>
      command === "webrtc_attach" ? { bridge_id: "closed-listener", max_packet: 1064, state: "online" } : {});
    const channel = fakeChannel();
    const onClosed = vi.fn();
    const attaching = attachWebRTCBridge(channel, { onClosed });
    const rejected = expect(attaching).rejects.toThrow(/closed/);
    await vi.waitFor(() => expect(onServiceEvent).toHaveBeenCalled());
    closeChannel(channel);
    subscription.resolve(unlisten);
    await rejected;

    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(serviceCommand.mock.calls.filter(([command]) => command === "webrtc_detach")).toHaveLength(1);
    expect(channel.onmessage).toBeNull();
  });

  it("detaches the native interface if subscribing fails", async () => {
    onServiceEvent.mockRejectedValueOnce(new Error("listener unavailable"));
    serviceCommand.mockImplementation(async (command: string) =>
      command === "webrtc_attach" ? { bridge_id: "failed-listener", max_packet: 1064, state: "online" } : {});
    const channel = fakeChannel();
    await expect(attachWebRTCBridge(channel)).rejects.toThrow("listener unavailable");
    expect(channel.close).toHaveBeenCalledTimes(1);
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: "failed-listener" });
  });

  it("releases a subscription if the reconnect attempt is cancelled before it completes", async () => {
    const subscription = deferred<() => void>();
    const unlisten = vi.fn();
    let current = true;
    onServiceEvent.mockReturnValueOnce(subscription.promise);
    serviceCommand.mockImplementation(async (command: string) =>
      command === "webrtc_attach" ? { bridge_id: "cancelled", max_packet: 1064, state: "online" } : {});
    const attaching = attachWebRTCBridge(fakeChannel(), { isCurrent: () => current });
    const rejected = expect(attaching).rejects.toThrow(/closed/);
    await vi.waitFor(() => expect(onServiceEvent).toHaveBeenCalled());
    current = false;
    subscription.resolve(unlisten);
    await rejected;
    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: "cancelled" });
  });

  it("round-trips base64 without corrupting bytes", () => {
    const bytes = new Uint8Array([0, 1, 2, 127, 128, 255]).buffer;
    expect(new Uint8Array(base64ToBytes(bytesToBase64(bytes)))).toEqual(
      new Uint8Array(bytes),
    );
  });

  it("pumps inbound packets to the service and outbound events to the channel", async () => {
    const listeners: Array<(event: unknown) => void> = [];
    onServiceEvent.mockImplementation(async (callback: (event: unknown) => void) => {
      listeners.push(callback);
      return () => undefined;
    });
    serviceCommand.mockImplementation(async (command: string) => {
      if (command === "webrtc_attach") return { bridge_id: "bridge", max_packet: 1064, state: "online" };
      if (command === "webrtc_packet") return { accepted: 2 };
      return { state: "closed" };
    });
    const channel = fakeChannel();
    const bridge = await attachWebRTCBridge(channel);

    channel.onmessage?.({ data: new Uint8Array([1, 2]).buffer } as MessageEvent);
    await vi.waitFor(() => {
      expect(serviceCommand).toHaveBeenCalledWith("webrtc_packet", {
        bridge_id: "bridge",
        data: "AQI=",
      });
    });

    listeners[0]?.({ event: "webrtc_packet", bridge_id: "bridge", data: "AwQ=" });
    expect(channel.send).toHaveBeenCalledTimes(1);
    expect(new Uint8Array(channel.send.mock.calls[0][0] as ArrayBuffer)).toEqual(
      new Uint8Array([3, 4]),
    );

    await bridge.close();
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: "bridge" });
  });

  it("rejects packets above the Reticulum MTU", async () => {
    onServiceEvent.mockResolvedValue(() => undefined);
    serviceCommand.mockImplementation(async (command: string) => {
      if (command === "webrtc_attach") return { bridge_id: "bridge", max_packet: 4, state: "online" };
      return { accepted: 5 };
    });
    const channel = fakeChannel();
    const onError = vi.fn();
    await attachWebRTCBridge(channel, { onError });

    channel.onmessage?.({ data: new Uint8Array([1, 2, 3, 4, 5]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(serviceCommand).not.toHaveBeenCalledWith("webrtc_packet", expect.anything());
  });
});

describe("WebRTC onboarding handoff", () => {
  it("closes once connected and the session is handed off", () => {
    expect(shouldAutoCloseWebRTCOnboarding("connected", "sent", true)).toBe(true);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "waiting-approval", true)).toBe(true);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "approved", true)).toBe(true);
  });

  it("keeps review, sending, errors, and unhanded sessions visible", () => {
    expect(shouldAutoCloseWebRTCOnboarding("connected", "preview", true)).toBe(false);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "sending", true)).toBe(false);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "error", true)).toBe(false);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "sent", false)).toBe(false);
    expect(shouldAutoCloseWebRTCOnboarding("waiting-answer", "sent", true)).toBe(false);
  });

  it("recognizes Windows and provides offer-specific firewall guidance", () => {
    expect(isWindowsWebRTCPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe(true);
    expect(isWindowsWebRTCPlatform("Mozilla/5.0 (Linux; Android 15)")).toBe(false);
    expect(webRTCWindowsChecklist("offer").join(" ")).toMatch(/msedgewebview2/);
    expect(webRTCWindowsChecklist("offer").join(" ")).toMatch(/create the offer on Android/);
    expect(webRTCWindowsChecklist("join").join(" ")).not.toMatch(/create the offer on Android/);
  });
});
