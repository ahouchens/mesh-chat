import { describe, expect, it } from "vitest";
import { CONNECTION_TRANSPORT_CHOICES, webRTCTransport } from "./connection-transport";
import type { WebRTCSession } from "./webrtc-session";

describe("connection transport choices", () => {
  it("exposes every supported transport with a label and description", () => {
    expect(CONNECTION_TRANSPORT_CHOICES.map((choice) => choice.kind)).toEqual([
      "direct_tcp",
      "access_point",
      "webrtc",
      "i2p",
    ]);
    for (const choice of CONNECTION_TRANSPORT_CHOICES) {
      expect(choice.label.length).toBeGreaterThan(0);
      expect(choice.description.length).toBeGreaterThan(0);
    }
  });

  it("closes every WebRTC resource through the transport boundary", async () => {
    const closed: string[] = [];
    const session = {
      bridge: { close: async () => { closed.push("bridge"); } },
      channel: { close: () => { closed.push("channel"); } },
      control: { close: () => { closed.push("control"); } },
      pc: { close: () => { closed.push("pc"); } },
      path: "relayed",
    } as unknown as WebRTCSession;

    const transport = webRTCTransport(session);
    expect(transport.kind).toBe("webrtc");
    expect(transport.path).toBe("relayed");
    await transport.close();
    expect(closed).toEqual(["bridge", "control", "channel", "pc"]);
  });
});
