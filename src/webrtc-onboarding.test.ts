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

import { attachWebRTCBridge, base64ToBytes, bytesToBase64 } from "./webrtc-onboarding";

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

afterEach(() => {
  vi.clearAllMocks();
});

describe("WebRTC DataChannel pump", () => {
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
