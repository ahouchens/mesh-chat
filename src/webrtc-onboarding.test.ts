import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  attachWebRTCBridge as attachBridge,
  BRIDGE_HEALTH_INTERVAL_MS,
  base64ToBytes,
  bytesToBase64,
  isWindowsWebRTCPlatform,
  shouldAutoCloseWebRTCOnboarding,
  webRTCWindowsChecklist,
} from "./webrtc-onboarding";
import { closeWebRTCSession, setWebRTCSession } from "./webrtc-session";

const testBridges: Awaited<ReturnType<typeof attachBridge>>[] = [];
async function attachWebRTCBridge(...args: Parameters<typeof attachBridge>) {
  const bridge = await attachBridge(...args);
  testBridges.push(bridge);
  return bridge;
}

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

beforeEach(() => {
  serviceCommand.mockReset();
  onServiceEvent.mockReset();
  onServiceEvent.mockResolvedValue(() => undefined);
});

afterEach(async () => {
  await Promise.all(testBridges.splice(0).map((bridge) => bridge.close()));
  await closeWebRTCSession();
  vi.clearAllMocks();
});

describe("WebRTC DataChannel pump", () => {
  it("repairs an idle missing bridge without an exit event or incoming traffic and stops probing on close", async () => {
    vi.useFakeTimers();
    try {
      let available = true;
      let restorations = 0;
      serviceCommand.mockImplementation(async (command) => {
        if (command === "webrtc_attach") {
          if (!available) { restorations++; available = true; }
          return { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
        }
        return {};
      });
      const channel = fakeChannel();
      const bridge = await attachWebRTCBridge(channel, { peerDestination: () => "verified-peer" });
      available = false;
      await vi.advanceTimersByTimeAsync(BRIDGE_HEALTH_INTERVAL_MS);
      expect(restorations).toBe(1);
      expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach", { bridge_id: bridge.bridgeId, peer_destination: "verified-peer" });
      expect(channel.close).not.toHaveBeenCalled();
      await bridge.close();
      const calls = serviceCommand.mock.calls.length;
      await vi.advanceTimersByTimeAsync(3 * BRIDGE_HEALTH_INTERVAL_MS);
      expect(serviceCommand).toHaveBeenCalledTimes(calls);
    } finally { vi.useRealTimers(); }
  });
  it("restores a restarted service without replacing the open peer or its registry handle", async () => {
    let listener!: (event: any) => void;
    onServiceEvent.mockImplementation(async (callback) => { listener = callback; return () => undefined; });
    const restoring = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    const result = { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
    serviceCommand.mockImplementation(async (command, payload) => {
      if (command === "webrtc_attach") return payload ? restoring.promise : result;
      return {};
    });
    const channel = fakeChannel();
    const onError = vi.fn();
    const onClosed = vi.fn();
    const bridge = await attachWebRTCBridge(channel, { onError, onClosed });
    listener({ event: "service_error" });
    listener({ event: "service_error" });
    channel.onmessage?.({ data: new Uint8Array([3, 4]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach", { bridge_id: bridge.bridgeId }));
    expect(serviceCommand.mock.calls.filter(([command]) => command === "webrtc_attach")).toHaveLength(2);
    // Fresh announcements emitted inside attach must cross the existing pump.
    listener({ event: "webrtc_packet", bridge_id: bridge.bridgeId, data: "AQI=" });
    restoring.resolve(result);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_packet", { bridge_id: "stable-bridge", data: "AwQ=" }));
    expect(channel.send).toHaveBeenCalledOnce();
    expect(channel.close).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(onClosed).not.toHaveBeenCalled();
    await bridge.close();
  });

  it("recovers a missing bridge even when the service exit event was missed", async () => {
    let attached = true;
    serviceCommand.mockImplementation(async (command, payload) => {
      if (command === "webrtc_attach") {
        attached = true;
        return { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
      }
      if (command === "webrtc_packet" && !attached) throw { code: "webrtc_bridge_missing" };
      return payload;
    });
    const channel = fakeChannel();
    const onError = vi.fn();
    const bridge = await attachWebRTCBridge(channel, { onError });
    attached = false;
    channel.onmessage?.({ data: new Uint8Array([3, 4]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(serviceCommand.mock.calls.filter(([name]) => name === "webrtc_packet")).toHaveLength(2));
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach", { bridge_id: "stable-bridge" });
    expect(onError).not.toHaveBeenCalled();
    expect(channel.close).not.toHaveBeenCalled();
    await bridge.close();
  });

  it("keeps the carrier open under packet load during a slow service restart", async () => {
    let listener!: (event: any) => void;
    onServiceEvent.mockImplementation(async (callback) => { listener = callback; return () => undefined; });
    const restoring = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    const result = { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
    serviceCommand.mockImplementation(async (command, payload) => command === "webrtc_attach" ? payload ? restoring.promise : result : {});
    const channel = fakeChannel();
    const onError = vi.fn();
    const bridge = await attachWebRTCBridge(channel, { onError });
    listener({ event: "service_error" });
    for (let index = 0; index < 256; index++) {
      channel.onmessage?.({ data: new Uint8Array([3, 4]).buffer } as MessageEvent);
    }
    expect(channel.close).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    restoring.resolve(result);
    await vi.waitFor(() => expect(serviceCommand.mock.calls.filter(([name]) => name === "webrtc_packet")).toHaveLength(128));
    channel.onmessage?.({ data: new Uint8Array([5, 6]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_packet", { bridge_id: bridge.bridgeId, data: "BQY=" }));
    await bridge.close();
  });

  it("detaches a late restoration when the person closes the connection", async () => {
    let listener!: (event: any) => void;
    onServiceEvent.mockImplementation(async (callback) => { listener = callback; return () => undefined; });
    const restoring = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    const result = { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
    serviceCommand.mockImplementation(async (command, payload) => command === "webrtc_attach" ? payload ? restoring.promise : result : {});
    const channel = fakeChannel();
    const bridge = await attachWebRTCBridge(channel);
    listener({ event: "service_error" });
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach", { bridge_id: bridge.bridgeId }));
    const closing = bridge.close();
    restoring.resolve(result);
    await closing;
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: bridge.bridgeId });
    expect(channel.close).toHaveBeenCalledOnce();
  });

  it("retries a temporarily unavailable service and cancels retries when closed", async () => {
    vi.useFakeTimers();
    try {
      let listener!: (event: any) => void;
      onServiceEvent.mockImplementation(async (callback) => { listener = callback; return () => undefined; });
      let unavailable = true;
      serviceCommand.mockImplementation(async (command, payload) => {
        if (command === "webrtc_attach") {
          if (payload && unavailable) throw { code: "service_not_running" };
          return { bridge_id: "stable-bridge", max_packet: 1064, state: "online" };
        }
        return {};
      });
      const channel = fakeChannel();
      const bridge = await attachWebRTCBridge(channel);
      listener({ event: "service_error" });
      await vi.advanceTimersByTimeAsync(0);
      unavailable = false;
      await vi.advanceTimersByTimeAsync(3000);
      expect(serviceCommand.mock.calls.filter(([name]) => name === "webrtc_attach")).toHaveLength(3);
      unavailable = true;
      listener({ event: "service_error" });
      await vi.advanceTimersByTimeAsync(0);
      await bridge.close();
      const count = serviceCommand.mock.calls.length;
      await vi.advanceTimersByTimeAsync(9000);
      expect(serviceCommand).toHaveBeenCalledTimes(count);
    } finally { vi.useRealTimers(); }
  });

  it("keeps an open carrier usable after an error event and retires it on close", async () => {
    let listener!: (event: unknown) => void;
    onServiceEvent.mockImplementation(async (callback) => {
      listener = callback;
      return () => undefined;
    });
    serviceCommand.mockImplementation(async (command: string) => command === "webrtc_attach"
      ? { bridge_id: "error-carrier", max_packet: 1064, state: "online" } : {});
    const channel = fakeChannel();
    const onError = vi.fn();
    const bridge = await attachWebRTCBridge(channel, { onError });
    channel.onerror?.call(channel, new Event("error") as RTCErrorEvent);
    await Promise.resolve();
    expect(channel.close).not.toHaveBeenCalled();
    expect(serviceCommand.mock.calls.some(([command]) => command === "webrtc_detach")).toBe(false);
    listener({ event: "webrtc_packet", bridge_id: bridge.bridgeId, data: "AQI=" });
    channel.onmessage?.({ data: new Uint8Array([3, 4]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_packet", {
      bridge_id: bridge.bridgeId, data: "AwQ=",
    }));
    expect(channel.send).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledOnce();
    closeChannel(channel);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", {
      bridge_id: bridge.bridgeId,
    }));
  });

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
    expect(onServiceEvent).toHaveBeenCalledTimes(1);
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
    expect(onClosed).not.toHaveBeenCalled();
    expect(serviceCommand).not.toHaveBeenCalled();
    expect(channel.onmessage).toBeNull();
  });

  it("does not create a native interface if subscribing fails", async () => {
    onServiceEvent.mockRejectedValueOnce(new Error("listener unavailable"));
    serviceCommand.mockImplementation(async (command: string) =>
      command === "webrtc_attach" ? { bridge_id: "failed-listener", max_packet: 1064, state: "online" } : {});
    const channel = fakeChannel();
    await expect(attachWebRTCBridge(channel)).rejects.toThrow("listener unavailable");
    expect(channel.close).toHaveBeenCalledTimes(1);
    expect(serviceCommand).not.toHaveBeenCalled();
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
    expect(serviceCommand).not.toHaveBeenCalled();
  });

  it("preserves early packets in both directions while event registration and native attachment finish", async () => {
    const subscription = deferred<() => void>();
    const native = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    let listener!: (event: unknown) => void;
    onServiceEvent.mockImplementation((callback: (event: unknown) => void) => {
      listener = callback;
      return subscription.promise;
    });
    serviceCommand.mockImplementation(async (command: string) => command === "webrtc_attach" ? native.promise : {});
    const channel = fakeChannel();
    const attaching = attachWebRTCBridge(channel);
    channel.onmessage?.({ data: new Uint8Array([1, 2]).buffer } as MessageEvent);
    await vi.waitFor(() => expect(onServiceEvent).toHaveBeenCalled());
    expect(serviceCommand).not.toHaveBeenCalled();
    subscription.resolve(() => undefined);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach"));
    channel.onmessage?.({ data: new Uint8Array([3, 4]).buffer } as MessageEvent);
    listener({ event: "webrtc_packet", bridge_id: "other-bridge", data: "CQk=" });
    listener({ event: "webrtc_packet", bridge_id: "early-bridge", data: "BQY=" });
    expect(channel.send).not.toHaveBeenCalled();
    expect(serviceCommand.mock.calls.filter(([command]) => command === "webrtc_packet")).toEqual([]);
    native.resolve({ bridge_id: "early-bridge", max_packet: 1064, state: "online" });
    const bridge = await attaching;
    await vi.waitFor(() => expect(serviceCommand.mock.calls.filter(([command]) => command === "webrtc_packet")).toEqual([
      ["webrtc_packet", { bridge_id: "early-bridge", data: "AQI=" }],
      ["webrtc_packet", { bridge_id: "early-bridge", data: "AwQ=" }],
    ]));
    expect(channel.send).toHaveBeenCalledTimes(1);
    expect(new Uint8Array(channel.send.mock.calls[0][0] as ArrayBuffer)).toEqual(new Uint8Array([5, 6]));
    await bridge.close();
  });

  it("keeps existing peers' traffic out of a new bridge's startup queue", async () => {
    const listeners: Array<(event: unknown) => void> = [];
    onServiceEvent.mockImplementation(async (callback: (event: unknown) => void) => {
      listeners.push(callback);
      return () => undefined;
    });
    const native = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    let attaches = 0;
    serviceCommand.mockImplementation(async (command: string) => {
      if (command !== "webrtc_attach") return {};
      attaches += 1;
      return attaches === 1
        ? { bridge_id: "existing-peer", max_packet: 1064, state: "online" }
        : native.promise;
    });
    const existingChannel = fakeChannel();
    const existingBridge = await attachWebRTCBridge(existingChannel);
    setWebRTCSession({
      key: "existing-peer",
      bridge: existingBridge,
      channel: existingChannel,
      pc: { close: vi.fn() } as unknown as RTCPeerConnection,
      control: null,
      path: "direct",
      createdAt: 1,
      approvalPending: false,
    });
    const channel = fakeChannel();
    const onError = vi.fn();
    const attaching = attachWebRTCBridge(channel, { onError });
    await vi.waitFor(() => expect(attaches).toBe(2));
    for (let index = 0; index < 256; index++) {
      for (const listener of listeners) {
        listener({ event: "webrtc_packet", bridge_id: "existing-peer", data: "CQk=" });
      }
    }
    for (const listener of listeners) {
      listener({ event: "webrtc_packet", bridge_id: "new-peer", data: "AQI=" });
    }
    native.resolve({ bridge_id: "new-peer", max_packet: 1064, state: "online" });
    const bridge = await attaching;

    expect(onError).not.toHaveBeenCalled();
    expect(channel.close).not.toHaveBeenCalled();
    expect(existingChannel.close).not.toHaveBeenCalled();
    expect(existingChannel.send).toHaveBeenCalledTimes(256);
    expect(channel.send).toHaveBeenCalledTimes(1);
    expect(new Uint8Array(channel.send.mock.calls[0][0] as ArrayBuffer)).toEqual(new Uint8Array([1, 2]));
    await bridge.close();
  });

  it("discards buffered startup packets if the channel closes before native attachment returns", async () => {
    const native = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    let listener!: (event: unknown) => void;
    const unlisten = vi.fn();
    onServiceEvent.mockImplementation(async (callback: (event: unknown) => void) => { listener = callback; return unlisten; });
    serviceCommand.mockImplementation(async (command: string) => command === "webrtc_attach" ? native.promise : {});
    const channel = fakeChannel();
    const attaching = attachWebRTCBridge(channel);
    const rejected = expect(attaching).rejects.toThrow(/closed/);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach"));
    channel.onmessage?.({ data: new Uint8Array([1, 2]).buffer } as MessageEvent);
    listener({ event: "webrtc_packet", bridge_id: "retired", data: "AQI=" });
    closeChannel(channel);
    native.resolve({ bridge_id: "retired", max_packet: 1064, state: "online" });
    await rejected;
    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(channel.send).not.toHaveBeenCalled();
    expect(serviceCommand).not.toHaveBeenCalledWith("webrtc_packet", expect.anything());
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: "retired" });
  });

  it("bounds the startup packet queue and retires an overflowing attachment", async () => {
    const native = deferred<{ bridge_id: string; max_packet: number; state: string }>();
    serviceCommand.mockImplementation(async (command: string) => command === "webrtc_attach" ? native.promise : {});
    const channel = fakeChannel();
    const onError = vi.fn();
    const attaching = attachWebRTCBridge(channel, { onError });
    const rejected = expect(attaching).rejects.toThrow(/closed/);
    await vi.waitFor(() => expect(serviceCommand).toHaveBeenCalledWith("webrtc_attach"));
    for (let index = 0; index < 129; index++) channel.onmessage?.({ data: new Uint8Array([1]).buffer } as MessageEvent);
    native.resolve({ bridge_id: "overflow", max_packet: 1064, state: "online" });
    await rejected;
    expect(onError).toHaveBeenCalledTimes(1);
    expect(channel.close).toHaveBeenCalledTimes(1);
    expect(serviceCommand).not.toHaveBeenCalledWith("webrtc_packet", expect.anything());
    expect(serviceCommand).toHaveBeenCalledWith("webrtc_detach", { bridge_id: "overflow" });
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
    expect(shouldAutoCloseWebRTCOnboarding("connected", "idle", true)).toBe(false);
    expect(shouldAutoCloseWebRTCOnboarding("connected", "unknown", true)).toBe(false);
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
