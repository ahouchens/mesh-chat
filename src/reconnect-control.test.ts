import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  getWebRTCSession: vi.fn(),
  getWebRTCSessions: vi.fn(),
}));

vi.mock("./api", () => ({ serviceCommand: mocks.serviceCommand }));
vi.mock("./webrtc-session", () => ({
  getWebRTCSession: mocks.getWebRTCSession,
  getWebRTCSessions: mocks.getWebRTCSessions,
}));

import {
  RECONNECT_CAPABILITIES_EVENT,
  sendReconnectCapabilities,
  storeReconnectCapabilities,
  maintainReconnectCapabilities,
  resendReconnectCapabilities,
  CAPABILITY_REFRESH_MS,
} from "./reconnect-control";

function controlChannel(readyState: RTCDataChannelState = "open") {
  return { readyState, send: vi.fn(), onmessage: null as ((event: MessageEvent) => void) | null };
}

beforeEach(() => {
  mocks.getWebRTCSession.mockReturnValue(null);
  mocks.getWebRTCSessions.mockImplementation(() => {
    const session = mocks.getWebRTCSession();
    return session ? [session] : [];
  });
  mocks.serviceCommand.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("reconnect capability exchange", () => {
  it("binds existing manual peers by verified destination before sharing upgraded capabilities", async () => {
    const control = controlChannel();
    const session = { peerDestination: "verified-peer", control, controlPurpose: "onboarding" };
    mocks.getWebRTCSession.mockReturnValue(session);
    mocks.serviceCommand.mockResolvedValue({ local_capabilities: "encrypted-upgrade" });
    maintainReconnectCapabilities([{ contact_id: "other", destination_hash: "other-peer" }]);
    expect(control.send).not.toHaveBeenCalled();
    maintainReconnectCapabilities([{ contact_id: "known", destination_hash: "verified-peer" }]);
    await vi.waitFor(() => expect(control.send).toHaveBeenCalledWith(JSON.stringify({ type: "connection_capabilities", document: "encrypted-upgrade" })));
    expect(session).toHaveProperty("contactId", "known");
    expect(mocks.serviceCommand).toHaveBeenCalledWith("reconnect_capabilities_get", { contact_id: "known" });
  });

  it("answers a manual peer's resend request even for unchanged capabilities and rate limits duplicates", async () => {
    const control = controlChannel();
    const session = { contactId: "known", peerDestination: "peer", control, controlPurpose: "onboarding" };
    mocks.getWebRTCSession.mockReturnValue(session);
    mocks.serviceCommand.mockResolvedValue({ local_capabilities: "same-document" });
    maintainReconnectCapabilities();
    await vi.waitFor(() => expect(control.send).toHaveBeenCalledTimes(1));
    await resendReconnectCapabilities(session as never);
    await resendReconnectCapabilities(session as never);
    expect(control.send).toHaveBeenCalledTimes(2);
    expect(control.onmessage).toBeNull();
  });

  it("resolves an unbound request only against the authenticated peer and ignores retired lookups", async () => {
    const control = controlChannel();
    const session = { peerDestination: "peer", control, controlPurpose: "onboarding" };
    mocks.getWebRTCSession.mockReturnValue(session);
    let resolve!: (value: unknown) => void;
    mocks.serviceCommand.mockReturnValue(new Promise((done) => { resolve = done; }));
    const pending = resendReconnectCapabilities(session as never);
    await resendReconnectCapabilities(session as never);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(1);
    mocks.getWebRTCSession.mockReturnValue(null);
    resolve({ profiles: [{ contact_id: "known", destination_hash: "peer" }] });
    await pending;
    expect(session).not.toHaveProperty("contactId");
    expect(control.send).not.toHaveBeenCalled();
  });

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

  it("finds an older open control for the requested peer without using another contact's channel", () => {
    const older = controlChannel();
    const other = controlChannel();
    mocks.getWebRTCSessions.mockReturnValue([
      { contactId: "contact-1", control: older, createdAt: 1 },
      { contactId: "contact-1", control: controlChannel("closed"), createdAt: 3 },
      { contactId: "contact-2", control: other, createdAt: 4 },
    ]);
    expect(sendReconnectCapabilities("signed", "contact-1")).toBe(true);
    expect(older.send).toHaveBeenCalledTimes(1);
    expect(other.send).not.toHaveBeenCalled();
  });

  it("refreshes a manual session periodically and only sends changed capabilities", async () => {
    vi.useFakeTimers();
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ contactId: "contact-1", control });
    let document = "signed-one";
    mocks.serviceCommand.mockImplementation(async () => ({ local_capabilities: document }));
    maintainReconnectCapabilities();
    maintainReconnectCapabilities();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(1);
    expect(control.send).toHaveBeenCalledTimes(1);
    expect(control.onmessage).toBeNull();

    await vi.advanceTimersByTimeAsync(CAPABILITY_REFRESH_MS);
    maintainReconnectCapabilities();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(2);
    expect(control.send).toHaveBeenCalledTimes(1);

    document = "signed-renewed";
    await vi.advanceTimersByTimeAsync(CAPABILITY_REFRESH_MS);
    maintainReconnectCapabilities();
    await vi.advanceTimersByTimeAsync(0);
    expect(control.send).toHaveBeenLastCalledWith(JSON.stringify({ type: "connection_capabilities", document }));
    expect(control.send).toHaveBeenCalledTimes(2);
  });

  it("binds reconnect control verification to its peer and rejects onboarding actions or oversized frames", async () => {
    vi.useFakeTimers();
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ contactId: "contact-1", control, controlPurpose: "reconnect" });
    mocks.serviceCommand.mockResolvedValue({ local_capabilities: "local", profile: { contact_id: "contact-1" } });
    maintainReconnectCapabilities();
    await vi.advanceTimersByTimeAsync(0);
    mocks.serviceCommand.mockClear();
    const receive = (data: unknown) => control.onmessage?.({ data } as MessageEvent);
    receive(JSON.stringify({ type: "invitation_approved", capabilities: "ignored" }));
    receive(JSON.stringify({ type: "connection_capabilities", document: "x".repeat(20_000) }));
    receive("not-json");
    receive(new ArrayBuffer(4));
    expect(mocks.serviceCommand).not.toHaveBeenCalled();
    receive(JSON.stringify({ type: "connection_capabilities", document: "peer-signed" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(1);
    expect(mocks.serviceCommand).toHaveBeenCalledWith("reconnect_capabilities_store", {
      document: "peer-signed", expected_contact_id: "contact-1",
    });
    receive(JSON.stringify({ type: "connection_capabilities", document: "peer-signed" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(1);
  });

  it("resends once after the remote receiver becomes ready without creating a request loop", async () => {
    vi.useFakeTimers();
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ contactId: "contact-1", control, controlPurpose: "reconnect" });
    mocks.serviceCommand.mockResolvedValue({ local_capabilities: "local" });
    maintainReconnectCapabilities();
    await vi.advanceTimersByTimeAsync(0);
    const request = { data: JSON.stringify({ type: "connection_capabilities_request" }) } as MessageEvent;
    control.onmessage?.(request);
    await vi.advanceTimersByTimeAsync(0);
    control.onmessage?.(request);
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(2);
    expect(control.send.mock.calls.map(([raw]) => JSON.parse(raw).type)).toEqual([
      "connection_capabilities_request", "connection_capabilities", "connection_capabilities",
    ]);
  });

  it("does not send a delayed refresh on a retired session or use personal capabilities for workspaces", async () => {
    vi.useFakeTimers();
    const control = controlChannel();
    mocks.getWebRTCSession.mockReturnValue({ contactId: "contact-1", control });
    let resolve!: (result: { local_capabilities: string }) => void;
    mocks.serviceCommand.mockReturnValue(new Promise((done) => { resolve = done; }));
    maintainReconnectCapabilities();
    mocks.getWebRTCSession.mockReturnValue({ contactId: "workspace:one", control });
    resolve({ local_capabilities: "must-not-send" });
    await vi.advanceTimersByTimeAsync(0);
    maintainReconnectCapabilities();
    expect(control.send).not.toHaveBeenCalled();
    expect(mocks.serviceCommand).toHaveBeenCalledTimes(1);
  });

  it("does not send a delayed capability after the same session is rebound to another contact", async () => {
    vi.useFakeTimers();
    const control = controlChannel();
    const session = { contactId: "contact-1", control };
    mocks.getWebRTCSession.mockReturnValue(session);
    let resolve!: (result: { local_capabilities: string }) => void;
    mocks.serviceCommand.mockReturnValue(new Promise((done) => { resolve = done; }));
    maintainReconnectCapabilities();
    session.contactId = "contact-2";
    resolve({ local_capabilities: "private-capability-for-contact-1" });
    await vi.advanceTimersByTimeAsync(0);
    expect(control.send).not.toHaveBeenCalled();
  });
});
