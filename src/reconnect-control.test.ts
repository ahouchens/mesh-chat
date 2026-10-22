import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  getWebRTCSession: vi.fn(),
}));

vi.mock("./api", () => ({ serviceCommand: mocks.serviceCommand }));
vi.mock("./webrtc-session", () => ({ getWebRTCSession: mocks.getWebRTCSession }));

import {
  RECONNECT_CAPABILITIES_EVENT,
  sendReconnectCapabilities,
  storeReconnectCapabilities,
} from "./reconnect-control";

function controlChannel(readyState: RTCDataChannelState = "open") {
  return { readyState, send: vi.fn() };
}

beforeEach(() => {
  mocks.getWebRTCSession.mockReturnValue(null);
  mocks.serviceCommand.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("reconnect capability exchange", () => {
  it("does nothing when there is no live control channel", () => {
    expect(sendReconnectCapabilities("signed")).toBe(false);
    mocks.getWebRTCSession.mockReturnValue({ control: controlChannel("closing") });
    expect(sendReconnectCapabilities("signed")).toBe(false);
  });

  it("sends the signed document over the authenticated control channel", () => {
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ control });
    expect(sendReconnectCapabilities("signed-document")).toBe(true);
    expect(control.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "connection_capabilities", document: "signed-document" }),
    );
  });

  it("never sends a contact's capability over another contact's channel", () => {
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ control, contactId: "contact-1" });
    expect(sendReconnectCapabilities("signed-document", "contact-2")).toBe(false);
    expect(control.send).not.toHaveBeenCalled();
    expect(sendReconnectCapabilities("signed-document", "contact-1")).toBe(true);
    expect(control.send).toHaveBeenCalledTimes(1);
    mocks.getWebRTCSession.mockReturnValue({ control });
    expect(sendReconnectCapabilities("signed-document", "contact-1")).toBe(false);
  });

  it("stores a verified capability and notifies the UI", async () => {
    mocks.serviceCommand.mockResolvedValue({ profile: {} });
    const listener = vi.fn();
    window.addEventListener(RECONNECT_CAPABILITIES_EVENT, listener);
    await storeReconnectCapabilities("peer-document");
    expect(mocks.serviceCommand).toHaveBeenCalledWith("reconnect_capabilities_store", {
      document: "peer-document",
    });
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(RECONNECT_CAPABILITIES_EVENT, listener);
  });

  it("does not store an empty document", async () => {
    await storeReconnectCapabilities("");
    expect(mocks.serviceCommand).not.toHaveBeenCalled();
  });
});
