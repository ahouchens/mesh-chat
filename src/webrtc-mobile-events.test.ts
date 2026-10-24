import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ServiceEvent } from "./api";

const native = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(async () => () => undefined),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: native.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: native.listen }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  getCurrent: vi.fn(async () => []),
  onOpenUrl: vi.fn(async () => () => undefined),
}));

function openChannel() {
  return {
    readyState: "open",
    binaryType: "blob",
    send: vi.fn(),
    close: vi.fn(),
    onmessage: null,
    onclose: null,
    onerror: null,
  } as unknown as RTCDataChannel & { send: ReturnType<typeof vi.fn> };
}

const cleanup: Array<() => void | Promise<void>> = [];

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  native.invoke.mockReset();
});

afterEach(async () => {
  for (const stop of cleanup.splice(0).reverse()) await stop();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Android service events with the real DataChannel bridge", () => {
  it.each(["ui-first", "bridge-first"])(
    "delivers packets and delivery-status updates through one native queue (%s)",
    async (order) => {
      const queue: ServiceEvent[] = [];
      native.invoke.mockImplementation(async (command: string, args?: { command: string }) => {
        if (command === "runtime_platform") return "android";
        // Android's poll is destructive: each batch can only be read once.
        if (command === "poll_mobile_events") return queue.splice(0);
        if (command === "service_command") {
          if (args?.command === "webrtc_attach") {
            return { bridge_id: "bridge", max_packet: 1064, state: "online" };
          }
          if (args?.command === "webrtc_packet") return { accepted: 3 };
          if (args?.command === "webrtc_detach") return { state: "closed" };
        }
        throw new Error(`Unexpected native command: ${command}`);
      });

      // Neither the public subscription API nor the bridge is mocked here.
      const { onServiceEvent } = await import("./api");
      const { attachWebRTCBridge } = await import("./webrtc-onboarding");
      const statuses: ServiceEvent[] = [];
      const subscribeUi = async () => {
        const stop = await onServiceEvent((event) => {
          if (event.event === "message_status") statuses.push(event);
        });
        cleanup.push(stop);
      };
      const channel = openChannel();
      if (order === "ui-first") await subscribeUi();
      const bridge = await attachWebRTCBridge(channel);
      cleanup.push(bridge.close);
      if (order === "bridge-first") await subscribeUi();

      const delivered: ServiceEvent = {
        type: "event", event: "message_status", message_id: "outgoing", state: "delivered",
      };
      queue.push(
        { type: "event", event: "webrtc_packet", bridge_id: "bridge", data: "AH//" },
        delivered,
        { type: "event", event: "webrtc_packet", bridge_id: "another-bridge", data: "AQI=" },
      );
      await vi.advanceTimersByTimeAsync(750);

      expect(queue).toEqual([]);
      expect(native.invoke.mock.calls.filter(([command]) => command === "poll_mobile_events")).toHaveLength(1);
      expect(channel.send).toHaveBeenCalledTimes(1);
      expect(new Uint8Array(channel.send.mock.calls[0][0] as ArrayBuffer)).toEqual(
        new Uint8Array([0, 127, 255]),
      );
      expect(statuses).toEqual([delivered]);

      // Packets arriving from the peer still take the real bridge's native command path.
      channel.onmessage?.call(channel, { data: new Uint8Array([255, 0, 128]).buffer } as MessageEvent);
      await vi.advanceTimersByTimeAsync(0);
      expect(native.invoke).toHaveBeenCalledWith("service_command", {
        command: "webrtc_packet", payload: { bridge_id: "bridge", data: "/wCA" },
      });

      await bridge.close();
      const afterClose = { ...delivered, message_id: "after-bridge-close" };
      queue.push(afterClose);
      await vi.advanceTimersByTimeAsync(750);
      expect(statuses).toEqual([delivered, afterClose]);
      expect(channel.send).toHaveBeenCalledTimes(1);
    },
  );
});
