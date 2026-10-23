import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  attachWebRTCBridge: vi.fn(),
  setWebRTCSession: vi.fn(),
}));

vi.mock("./api", () => ({ serviceCommand: mocks.serviceCommand }));
vi.mock("qrcode.react", () => ({ QRCodeSVG: () => null }));
vi.mock("./webrtc-onboarding", async (importOriginal) => ({
  ...await importOriginal<typeof import("./webrtc-onboarding")>(),
  attachWebRTCBridge: mocks.attachWebRTCBridge,
}));
vi.mock("./webrtc-session", async (importOriginal) => ({
  ...await importOriginal<typeof import("./webrtc-session")>(),
  setWebRTCSession: mocks.setWebRTCSession,
}));

import { WebRTCOnboardingDialog } from "./WebRTCOnboarding";

const sdp = [
  "v=0",
  "m=application 50000 UDP/DTLS/SCTP webrtc-datachannel",
  "a=mid:0",
  "a=ice-ufrag:test",
  "a=ice-pwd:abcdefghijklmnopqrstuvwx",
  "a=fingerprint:sha-256 AA:BB",
  "a=candidate:1 1 udp 16777215 192.0.2.1 50000 typ relay",
  "",
].join("\r\n");
const offerDocument = JSON.stringify({ type: "webrtc_onboarding_offer", session_id: "session" });
const answerDocument = JSON.stringify({ type: "webrtc_onboarding_answer", session_id: "session" });

class FakeChannel extends EventTarget {
  readonly label: string;
  readyState: RTCDataChannelState = "connecting";
  binaryType: BinaryType = "blob";
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = "closed"; });

  constructor(label: string) {
    super();
    this.label = label;
  }
}

let finishGatheringImmediately = true;
let offerExpiresAt = 0;

class FakePeer extends EventTarget {
  static instances: FakePeer[] = [];
  connectionState: RTCPeerConnectionState = "new";
  iceConnectionState: RTCIceConnectionState = "new";
  iceGatheringState: RTCIceGatheringState = "new";
  signalingState: RTCSignalingState = "stable";
  localDescription: RTCSessionDescriptionInit | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  onconnectionstatechange: (() => void) | null = null;
  oniceconnectionstatechange: (() => void) | null = null;
  ondatachannel: ((event: { channel: RTCDataChannel }) => void) | null = null;
  getStats = vi.fn(async () => new Map());
  createOffer = vi.fn(async () => ({ type: "offer" as const, sdp }));
  createAnswer = vi.fn(async () => ({ type: "answer" as const, sdp }));
  setRemoteDescription = vi.fn(async (description: RTCSessionDescriptionInit) => {
    this.remoteDescription = description;
  });
  setLocalDescription = vi.fn(async (description: RTCSessionDescriptionInit) => {
    this.localDescription = description;
    this.iceGatheringState = finishGatheringImmediately ? "complete" : "gathering";
  });
  close = vi.fn(() => {
    this.connectionState = "closed";
    this.signalingState = "closed";
  });

  constructor() {
    super();
    FakePeer.instances.push(this);
  }

  createDataChannel(label: string): RTCDataChannel {
    return new FakeChannel(label) as unknown as RTCDataChannel;
  }

  fail(): void {
    this.connectionState = "failed";
    this.iceConnectionState = "failed";
    this.onconnectionstatechange?.();
    this.oniceconnectionstatechange?.();
    this.dispatchEvent(new Event("connectionstatechange"));
    this.dispatchEvent(new Event("iceconnectionstatechange"));
  }

  openIncomingChannel(): FakeChannel {
    this.connectionState = "connected";
    this.iceConnectionState = "connected";
    this.onconnectionstatechange?.();
    this.oniceconnectionstatechange?.();
    const channel = new FakeChannel("mesh-reticulum");
    this.ondatachannel?.({ channel: channel as unknown as RTCDataChannel });
    channel.readyState = "open";
    channel.onopen?.();
    channel.dispatchEvent(new Event("open"));
    return channel;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-23T22:00:00Z"));
  vi.clearAllMocks();
  FakePeer.instances = [];
  finishGatheringImmediately = true;
  offerExpiresAt = Math.floor(Date.now() / 1000) + 600;
  vi.stubGlobal("RTCPeerConnection", FakePeer);
  mocks.attachWebRTCBridge.mockResolvedValue({ bridgeId: "bridge", close: vi.fn().mockResolvedValue(undefined) });
  mocks.serviceCommand.mockImplementation(async (command: string) => {
    if (command === "call_settings") return { turn_configured: true };
    if (command === "call_ice_servers") return {
      iceServers: [{ urls: "turn:relay.example:3478", username: "test", credential: "test" }],
      iceTransportPolicy: "relay",
    };
    if (command === "verify_webrtc_onboarding_offer") return {
      document: offerDocument,
      session_id: "session",
      sdp,
      dtls_fingerprint: "sha-256 AA:BB",
      expires_at: offerExpiresAt,
      signer_destination: "peer",
    };
    if (command === "webrtc_onboarding_answer") return {
      document: answerDocument, session_id: "session", expires_at: offerExpiresAt,
    };
    if (command === "webrtc_onboarding_offer") return {
      document: offerDocument, session_id: "session", expires_at: offerExpiresAt,
    };
    throw new Error(`Unexpected command: ${command}`);
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function join() {
  const onConnected = vi.fn();
  const onClose = vi.fn();
  const view = render(<WebRTCOnboardingDialog onClose={onClose} onChanged={async () => undefined} onConnected={onConnected} />);
  await act(async () => undefined);
  fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
  fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Review and create answer" }));
  });
  expect(FakePeer.instances).toHaveLength(1);
  return { ...view, pc: FakePeer.instances[0], onConnected, onClose };
}

async function advance(ms: number): Promise<void> {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

describe("manual WebRTC answer exchange", () => {
  it("keeps the answerer alive after initial ICE failure and attaches a late incoming channel", async () => {
    const { pc, onConnected, unmount } = await join();
    expect(screen.getByLabelText("Signed WebRTC answer")).toBeTruthy();
    await advance(35000);
    await act(async () => { pc.fail(); });

    expect(pc.close).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Signed WebRTC answer")).toBeTruthy();
    await advance(15000);
    await act(async () => {
      const channel = pc.openIncomingChannel();
      // Both the open event and the post-description ready-state check can
      // observe the same channel opening. Only one bridge may attach.
      channel.onopen?.();
    });

    expect(mocks.attachWebRTCBridge).toHaveBeenCalledTimes(1);
    expect(mocks.setWebRTCSession).toHaveBeenCalledTimes(1);
    expect(onConnected).toHaveBeenCalledTimes(1);
    expect(screen.getByText("WebRTC path connected")).toBeTruthy();
    await advance(120000);
    expect(pc.close).not.toHaveBeenCalled();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    expect(pc.close).not.toHaveBeenCalled();
  });

  it("also preserves the answerer if ICE fails during the 15-second gathering wait", async () => {
    finishGatheringImmediately = false;
    const { pc } = await join();
    expect(screen.queryByLabelText("Signed WebRTC answer")).toBeNull();
    await advance(10000);
    await act(async () => { pc.fail(); });
    expect(pc.close).not.toHaveBeenCalled();

    await advance(5000);
    expect(screen.getByLabelText("Signed WebRTC answer")).toBeTruthy();
    await act(async () => { pc.openIncomingChannel(); });
    expect(mocks.attachWebRTCBridge).toHaveBeenCalledTimes(1);
    expect(screen.getByText("WebRTC path connected")).toBeTruthy();
  });

  it("bounds the manual wait from offer application, including time spent gathering", async () => {
    finishGatheringImmediately = false;
    const { pc } = await join();
    await advance(15000);
    await act(async () => { pc.fail(); });
    await advance(104999);
    expect(pc.close).not.toHaveBeenCalled();

    await advance(1);
    expect(pc.close).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Signed WebRTC answer")).toBeNull();
    expect(screen.getByRole("alert").textContent).toMatch(/answer|offerer|exchange/i);
    expect(screen.getByRole("alert").textContent).not.toMatch(/network path failed/i);
  });

  it("caps the manual wait at the signed offer expiry", async () => {
    offerExpiresAt = Math.floor(Date.now() / 1000) + 45;
    const { pc } = await join();
    await act(async () => { pc.fail(); });
    await advance(44999);
    expect(pc.close).not.toHaveBeenCalled();
    await advance(1);
    expect(pc.close).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toMatch(/answer|offerer|exchange|expir/i);
  });

  it("still reports a genuine offerer ICE failure immediately", async () => {
    render(<WebRTCOnboardingDialog onClose={() => undefined} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    const pc = FakePeer.instances[0];
    expect(screen.getByLabelText("Signed WebRTC offer")).toBeTruthy();
    await act(async () => { pc.fail(); });
    expect(pc.close).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toMatch(/network path failed/i);
  });

  it("does not publish an answer after the dialog closes during gathering", async () => {
    finishGatheringImmediately = false;
    const { pc, unmount } = await join();
    unmount();
    expect(pc.close).toHaveBeenCalledTimes(1);
    await advance(15000);
    expect(mocks.serviceCommand.mock.calls.some(([command]) => command === "webrtc_onboarding_answer")).toBe(false);
    expect(mocks.setWebRTCSession).not.toHaveBeenCalled();
  });

  it("ignores a failed event from an earlier attempt after a retry", async () => {
    render(<WebRTCOnboardingDialog onClose={() => undefined} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    const previous = FakePeer.instances[0];
    const queuedFailure = previous.onconnectionstatechange;
    await act(async () => { previous.fail(); });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    const current = FakePeer.instances[1];

    previous.connectionState = "failed";
    await act(async () => { queuedFailure?.(); });
    expect(current.close).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Signed WebRTC offer")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
