import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  serviceCommand: vi.fn(),
  attachWebRTCBridge: vi.fn(),
  setWebRTCSession: vi.fn(),
  getWebRTCSessionByKey: vi.fn(),
  getWebRTCSessions: vi.fn(),
  updateWebRTCSessionContact: vi.fn(),
  updateWebRTCSessionApprovalPending: vi.fn(),
  onServiceEvent: vi.fn(),
  desktopServiceHealth: vi.fn(),
}));

vi.mock("./api", () => ({
  serviceCommand: mocks.serviceCommand,
  onServiceEvent: mocks.onServiceEvent,
  desktopServiceHealth: mocks.desktopServiceHealth,
}));
vi.mock("./webrtc-onboarding", async (importOriginal) => ({
  ...await importOriginal<typeof import("./webrtc-onboarding")>(),
  attachWebRTCBridge: mocks.attachWebRTCBridge,
}));
vi.mock("./webrtc-session", async (importOriginal) => ({
  ...await importOriginal<typeof import("./webrtc-session")>(),
  setWebRTCSession: mocks.setWebRTCSession,
  getWebRTCSessionByKey: mocks.getWebRTCSessionByKey,
  getWebRTCSessions: mocks.getWebRTCSessions,
  updateWebRTCSessionContact: mocks.updateWebRTCSessionContact,
  updateWebRTCSessionApprovalPending: mocks.updateWebRTCSessionApprovalPending,
}));

import { WebRTCOnboardingDialog, normalizeWebRTCOfferInput } from "./WebRTCOnboarding";
import RuntimeErrorBoundary from "./RuntimeErrorBoundary";

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

describe("WebRTC offer input", () => {
  it("accepts the pairing link copied from the Windows QR code", () => {
    expect(normalizeWebRTCOfferInput("  meshchat://pair/abc123  ")).toBe("abc123");
    expect(normalizeWebRTCOfferInput("abc123")).toBe("abc123");
    expect(normalizeWebRTCOfferInput(offerDocument)).toBe(offerDocument);
  });
});

describe("mailbox recovery", () => {
  it.each(["success", "error"])("ignores a stale mailbox %s after starting a new offer", async (outcome) => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    let resolve!: (value: unknown) => void;
    let reject!: (reason: unknown) => void;
    const fetched = new Promise((done, failed) => { resolve = done; reject = failed; });
    let offer = 0;
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "call_settings") return { signal_mailbox_url: "https://signal.example" };
      if (command === "signal_publish") return { session_id: `mailbox-${++offer}` };
      if (command === "signal_fetch") return fetched;
      return implementation?.(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Fetch answer" })); });
    expect((screen.getByRole("button", { name: "Fetching…" }) as HTMLButtonElement).disabled).toBe(true);
    const pc = FakePeer.instances[0];
    await act(async () => { pc.connectionState = "failed"; pc.onconnectionstatechange?.(); });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    await act(async () => {
      if (outcome === "success") resolve({ document: "old-answer" });
      else reject(new Error("old-fetch-error"));
    });
    expect((screen.getByLabelText("Paste their signed answer") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("old-fetch-error")).toBeNull();
    expect(screen.getByText("mailbox-2")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Fetch answer" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not overwrite an answer pasted while a mailbox fetch is pending", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    let resolve!: (value: unknown) => void;
    const fetched = new Promise((done) => { resolve = done; });
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "call_settings") return { signal_mailbox_url: "https://signal.example" };
      if (command === "signal_publish") return { session_id: "code" };
      if (command === "signal_fetch") return fetched;
      return implementation?.(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Fetch answer" })); });
    fireEvent.change(screen.getByLabelText("Paste their signed answer"), { target: { value: "manual-answer" } });
    await act(async () => { resolve({ document: "late-mailbox-answer" }); });
    expect((screen.getByLabelText("Paste their signed answer") as HTMLTextAreaElement).value).toBe("manual-answer");
  });
  it.each([true, false])("offers explicit default-mailbox recovery on Android (save succeeds: %s)", async (saveSucceeds) => {
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("navigator", { userAgent: "Android", clipboard });
    const code = "MESHPAIR2.private-pairing-code";
    const settings = { stun_urls: ["stun:example.test"], turn_url: null, turn_username: null,
      turn_broker_url: "https://relay.example.test", turn_broker_consent: true, relay_only: false,
      store_call_signaling: false, signal_mailbox_url: null, signal_mailbox_default_url: "https://signal.example.test" };
    let enabled = false;
    const run = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => {
      if (command === "call_settings") return settings;
      if (command === "signal_fetch") {
        if (!enabled) throw { code: "mailbox_not_configured" };
        return { document: offerDocument };
      }
      if (command === "update_call_settings") {
        if (!saveSucceeds) throw { code: "protected_storage_unavailable" };
        enabled = true;
        return { ...settings, signal_mailbox_url: settings.signal_mailbox_default_url };
      }
      return run(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: code } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(screen.getByRole("alert").textContent).toMatch(/mailbox is off/i);
    expect(mocks.serviceCommand.mock.calls.some(([name]) => name === "native_webrtc_accept")).toBe(false);
    expect(mocks.serviceCommand.mock.calls.some(([name]) => name === "update_call_settings")).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy diagnostics" })); });
    expect(JSON.parse(clipboard.writeText.mock.calls[0][0])).toMatchObject({ operation: "signal_fetch", error_code: "mailbox_not_configured", offer_verified: false });
    expect(clipboard.writeText.mock.calls[0][0]).not.toContain(code);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Use default mailbox" })); });
    expect(mocks.serviceCommand).toHaveBeenCalledWith("update_call_settings", {
      stun_urls: settings.stun_urls, turn_url: null, turn_username: null, turn_credential: null,
      turn_broker_url: settings.turn_broker_url, turn_broker_consent: true,
      signal_mailbox_url: settings.signal_mailbox_default_url, relay_only: false, store_call_signaling: false,
    });
    if (!saveSucceeds) {
      expect(screen.getByText(/mailbox setting could not be saved/i)).toBeTruthy();
      expect(mocks.serviceCommand.mock.calls.filter(([name]) => name === "signal_fetch")).toHaveLength(1);
      return;
    }
    expect((screen.getByLabelText("Paste the signed WebRTC offer or mailbox code") as HTMLTextAreaElement).value).toBe(code);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(mocks.serviceCommand.mock.calls.filter(([name]) => name === "native_webrtc_accept")).toHaveLength(1);
    expect(screen.getByLabelText("Signed WebRTC answer")).toBeTruthy();
  });

  it("does not call a mailbox fetch failure a signature error or replace a custom mailbox", async () => {
    vi.stubGlobal("navigator", { userAgent: "Android" });
    const run = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => {
      if (command === "call_settings") return { signal_mailbox_url: "https://custom.example.test", signal_mailbox_default_url: "https://default.example.test" };
      if (command === "signal_fetch") throw { code: "invalid_request" };
      return run(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: "MESHPAIR2.code" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(screen.getByRole("alert").textContent).toMatch(/both devices use the same mailbox/);
    expect(screen.queryByRole("button", { name: "Use default mailbox" })).toBeNull();
    expect(mocks.serviceCommand.mock.calls.some(([name]) => name === "native_webrtc_accept")).toBe(false);
  });
});

class FakeChannel extends EventTarget {
  readonly label: string;
  readyState: RTCDataChannelState = "connecting";
  binaryType: BinaryType = "blob";
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
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
  channels: FakeChannel[] = [];
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
    const channel = new FakeChannel(label);
    this.channels.push(channel);
    return channel as unknown as RTCDataChannel;
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

  openControlChannel(): FakeChannel {
    const channel = new FakeChannel("mesh-onboarding");
    channel.readyState = "open";
    this.ondatachannel?.({ channel: channel as unknown as RTCDataChannel });
    return channel;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-23T22:00:00Z"));
  vi.clearAllMocks();
  mocks.onServiceEvent.mockReset();
  mocks.onServiceEvent.mockResolvedValue(() => undefined);
  mocks.desktopServiceHealth.mockResolvedValue({ running: false, last_unexpected_exit: { reason: "terminated", exit_code: 3, signal: null, recorded_at: 1792792800 } });
  mocks.getWebRTCSessionByKey.mockReset();
  mocks.setWebRTCSession.mockReset();
  mocks.getWebRTCSessions.mockReturnValue([]);
  FakePeer.instances = [];
  finishGatheringImmediately = true;
  offerExpiresAt = Math.floor(Date.now() / 1000) + 600;
  vi.stubGlobal("RTCPeerConnection", FakePeer);
  vi.stubGlobal("navigator", { userAgent: "Windows NT 10.0" });
  mocks.attachWebRTCBridge.mockResolvedValue({ bridgeId: "bridge", close: vi.fn().mockResolvedValue(undefined) });
  mocks.serviceCommand.mockImplementation(async (command: string) => {
    if (command === "native_webrtc_offer" || command === "native_webrtc_accept") return { ok: true, sdp, fingerprint: "sha-256 AA:BB" };
    if (command === "native_webrtc_bind_onboarding") return { peer_destination: "peer" };
    if (command === "native_webrtc_stats") return { attached: false };
    if (command === "native_webrtc_close") return { state: "closed" };
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

async function join(onChanged: () => Promise<void> = async () => undefined) {
  const onConnected = vi.fn();
  const onClose = vi.fn();
  const view = render(<WebRTCOnboardingDialog onClose={onClose} onChanged={onChanged} onConnected={onConnected} />);
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
  it("keeps service failures copyable before a peer connection exists", async () => {
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("navigator", { userAgent: "Windows NT 10.0", clipboard });
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "call_ice_servers") throw new Error("service_not_running");
      return runCommand(command);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" }));
    });
    expect(FakePeer.instances).toHaveLength(0);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy diagnostics" }));
    });
    expect(JSON.parse(clipboard.writeText.mock.calls[0][0])).toEqual({
      phase: "offer-failed", message: "service_not_running", peer_connection: "not_created",
      desktop_service: { running: false, last_unexpected_exit: { reason: "terminated", exit_code: 3, signal: null, recorded_at: 1792792800 } },
    });
  });

  it.each(["offer", "answer"] as const)("keeps a candidate-rich %s copyable without crashing the renderer", async (kind) => {
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36", clipboard });
    const candidateSdp = sdp + Array.from({ length: 24 }, (_, index) =>
      `a=candidate:${index + 2} 1 udp 16777215 2001:db8::${index + 1} ${50001 + index} typ relay raddr :: rport 0 generation 0 network-cost 999\r\n`
    ).join("");
    const document = JSON.stringify({
      v: 1, type: `webrtc_onboarding_${kind}`, session_id: "session",
      sdp: candidateSdp, dtls_fingerprint: "sha-256 AA:BB",
      created_at: Math.floor(Date.now() / 1000), expires_at: offerExpiresAt,
      signer_public_key: "A".repeat(86), signature: "B".repeat(86),
      ...(kind === "answer" ? { offer_digest: "c".repeat(64) } : {}),
    });
    expect(new TextEncoder().encode(document).byteLength).toBeGreaterThan(2953);
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string) => command === `webrtc_onboarding_${kind}`
      ? { document, session_id: "session", expires_at: offerExpiresAt }
      : runCommand(command));
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const { container } = render(<RuntimeErrorBoundary><WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} /></RuntimeErrorBoundary>);
      await act(async () => undefined);
      if (kind === "answer") {
        fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
        fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
      }
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: kind === "answer" ? "Review and create answer" : "Create WebRTC invitation" }));
      });

      expect(screen.queryByRole("heading", { name: "Mesh Chat needs to reload" })).toBeNull();
      expect((screen.getByLabelText(`Signed WebRTC ${kind}`) as HTMLTextAreaElement).value).toBe(document);
      expect(screen.queryByRole("button", { name: "Show QR code" })).toBeNull();
      expect(container.querySelector(".webrtc-qr svg")).toBeNull();
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: `Copy ${kind}` }));
      });
      expect(clipboard.writeText).toHaveBeenCalledWith(document);
      expect(FakePeer.instances).toHaveLength(0);
      expect(mocks.serviceCommand).not.toHaveBeenCalledWith("native_webrtc_close", expect.anything());
    } finally {
      errors.mockRestore();
    }
  });

  it("only renders an answer QR code on request and lets the user hide it", async () => {
    const { container } = await join();
    expect(container.querySelector(".webrtc-qr svg")).toBeNull();
    expect(screen.getByRole("button", { name: "Show QR code" }).getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Show QR code" }));
    expect(container.querySelector(".webrtc-qr svg")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Hide QR code" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Hide QR code" }));
    expect(container.querySelector(".webrtc-qr svg")).toBeNull();
    expect((screen.getByLabelText("Signed WebRTC answer") as HTMLTextAreaElement).value).toBe(answerDocument);
  });

  it("keeps both offer and mailbox QR codes hidden until requested", async () => {
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string) => {
      if (command === "call_settings") return { turn_configured: true, signal_mailbox_url: "https://signal.example" };
      if (command === "signal_publish") return { session_id: "pairing-code" };
      return runCommand(command);
    });
    const { container } = render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" }));
    });

    expect(screen.getByRole("button", { name: "Copy offer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeTruthy();
    expect(container.querySelector(".webrtc-qr svg")).toBeNull();
    const qrButtons = screen.getAllByRole("button", { name: "Show QR code" });
    expect(qrButtons).toHaveLength(2);
    fireEvent.click(qrButtons[0]);
    expect(container.querySelectorAll(".remote-consent .webrtc-qr svg")).toHaveLength(1);
    fireEvent.click(qrButtons[1]);
    expect(container.querySelectorAll(".webrtc-qr svg")).toHaveLength(2);
  });

  it("uses a native transport and binds the signed offer on Android", async () => {
    vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36" });
    const view = render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(FakePeer.instances).toHaveLength(0);
    expect(mocks.serviceCommand).toHaveBeenCalledWith("native_webrtc_accept", expect.objectContaining({ offer_sdp: sdp }));
    expect(mocks.serviceCommand).toHaveBeenCalledWith("native_webrtc_bind_onboarding", expect.objectContaining({ offer_document: offerDocument }));
    expect((screen.getByLabelText("Signed WebRTC answer") as HTMLTextAreaElement).value).toBe(answerDocument);
    view.unmount();
    expect(mocks.serviceCommand).toHaveBeenCalledWith("native_webrtc_close", expect.anything());
  });

  it("does not call a verified offer incomplete when Android cannot create an answer", async () => {
    vi.stubGlobal("navigator", { userAgent: "Android" });
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => {
      if (command === "native_webrtc_accept") throw { code: "invalid_request" };
      return runCommand(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(screen.getByRole("alert").textContent).toMatch(/offer was verified.*could not create an answer/i);
    expect(screen.getByRole("alert").textContent).not.toMatch(/complete signed WebRTC offer|outer JSON braces/i);
  });

  it.each(["call_ice_servers", "native_webrtc_accept", "native_webrtc_bind_onboarding", "webrtc_onboarding_answer"])(
    "preserves Android's failing %s command when native stats are unavailable", async (failedCommand) => {
      const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
      vi.stubGlobal("navigator", { userAgent: "Android", clipboard });
      const runCommand = mocks.serviceCommand.getMockImplementation()!;
      mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => {
        if (command === failedCommand) throw { code: "invalid_request" };
        if (command === "native_webrtc_stats") throw { code: "native_unavailable" };
        return runCommand(command, payload);
      });
      render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} />);
      await act(async () => undefined);
      fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
      fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy diagnostics" })); });
      const report = JSON.parse(clipboard.writeText.mock.calls[0][0]);
      expect(report).toMatchObject({ phase: "offer-review-failed", operation: failedCommand,
        error_code: "invalid_request", offer_verified: true, native: true, native_stats: "unavailable" });
      expect(report).not.toHaveProperty("desktop_service");
      expect(report).not.toHaveProperty("peer_connection");
      expect(clipboard.writeText.mock.calls[0][0]).not.toContain(offerDocument);
      expect(mocks.desktopServiceHealth).not.toHaveBeenCalled();
    },
  );

  it("hands a connected native transport to the service when the dialog closes", async () => {
    vi.stubGlobal("navigator", { userAgent: "Android" });
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string) => command === "native_webrtc_stats"
      ? { attached: true } : runCommand(command));
    const onConnected = vi.fn();
    const view = render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => undefined} onConnected={onConnected} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(onConnected).toHaveBeenCalledWith("unknown");
    view.unmount();
    expect(mocks.serviceCommand).not.toHaveBeenCalledWith("native_webrtc_close", expect.anything());
  });

  it("keeps Android listening until a delayed contact invitation can be reviewed and accepted", async () => {
    vi.stubGlobal("navigator", { userAgent: "Android" });
    const unlisten = vi.fn();
    mocks.onServiceEvent.mockResolvedValue(unlisten);
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => {
      if (command === "native_webrtc_stats") return { attached: true };
      if (command === "receive_contact_invitation") return { id: "saved-invitation", state: "pending", preview: { display_name: "Alex", fingerprint: "verified-peer" }, workspace: null };
      if (command === "decide_contact_invitation") return { id: "contact-alex" };
      if (command === "native_webrtc_control") return { accepted: true };
      return runCommand(command, payload);
    });
    const onClose = vi.fn();
    const onChanged = vi.fn(async () => undefined);
    const view = render(<WebRTCOnboardingDialog onClose={onClose} onChanged={onChanged} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(screen.getByText("WebRTC path connected")).toBeTruthy();
    // The native path is open, but the inviter may still be creating its
    // signed contact document. It must survive the old 1.5-second timer.
    await advance(5_000);
    expect(onClose).not.toHaveBeenCalled();
    expect(unlisten).not.toHaveBeenCalled();
    expect(mocks.serviceCommand).not.toHaveBeenCalledWith("decide_contact_invitation", expect.anything());
    const sessionId = mocks.serviceCommand.mock.calls.find(([command]) => command === "native_webrtc_accept")![1].session_id;
    const receive = mocks.onServiceEvent.mock.calls[0][0];
    await act(async () => {
      receive({ type: "event", event: "webrtc_control", session_id: sessionId,
        label: "mesh-onboarding", data: JSON.stringify({ type: "contact_invitation", document: "signed-invitation" }) });
    });
    expect(screen.getByRole("button", { name: "Accept contact" })).toBeTruthy();
    await advance(5_000);
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Accept contact" })); });
    expect(mocks.serviceCommand).toHaveBeenCalledWith("decide_contact_invitation", { invitation_id: "saved-invitation", accept: true });
    expect(mocks.serviceCommand).toHaveBeenCalledWith("native_webrtc_control", {
      session_id: sessionId, label: "mesh-onboarding", text: JSON.stringify({ type: "invitation_accepted" }),
    });
    expect(screen.getByText(/Contact request sent/)).toBeTruthy();
    await advance(1_500);
    expect(onClose).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(mocks.serviceCommand).not.toHaveBeenCalledWith("native_webrtc_close", expect.anything());
  });

  it("adds a late control channel to the same registered onboarding session", async () => {
    const { pc } = await join();
    await act(async () => { pc.openIncomingChannel(); });
    const session = mocks.setWebRTCSession.mock.calls[0][0];
    expect(session.control).toBeNull();
    expect(session.peerDestination).toBe("peer");
    mocks.getWebRTCSessionByKey.mockReturnValue(session);

    let control!: FakeChannel;
    await act(async () => { control = pc.openControlChannel(); });

    expect(session.control).toBe(control);
    expect(mocks.getWebRTCSessionByKey).toHaveBeenCalledWith("onboarding:bridge");
    expect(mocks.setWebRTCSession).toHaveBeenLastCalledWith(session);
    expect(mocks.attachWebRTCBridge).toHaveBeenCalledTimes(1);
  });

  it("binds an accepted invitation to its own session using the verified capability", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const implementation = mocks.serviceCommand.getMockImplementation();
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "create_invitation") return { file: "signed-invitation" };
      if (command === "reconnect_capabilities_store") return { profile: { contact_id: "contact-alex" } };
      if (command === "verify_webrtc_onboarding_answer") return {
        document: answerDocument, session_id: "session", sdp,
        dtls_fingerprint: "sha-256 AA:BB", expires_at: offerExpiresAt,
        signer_destination: "verified-answer-peer",
      };
      return implementation?.(command, payload);
    });
    render(<WebRTCOnboardingDialog onClose={() => undefined} onChanged={async () => undefined} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create WebRTC invitation" })); });
    fireEvent.change(screen.getByLabelText("Paste their signed answer"), {
      target: { value: JSON.stringify({
        type: "webrtc_onboarding_answer", session_id: "session",
        offer_digest: createHash("sha256").update(offerDocument).digest("hex"),
      }) },
    });
    const pc = FakePeer.instances[0];
    // Real WebCrypto runs outside React's act queue and Vitest's fake timers.
    // A real DataChannel cannot open before the verified answer is applied.
    const remoteApplied = new Promise<void>((resolve) => {
      pc.setRemoteDescription.mockImplementationOnce(async (description) => {
        pc.remoteDescription = description;
        resolve();
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Connect" }));
      await remoteApplied;
    });
    await act(async () => {
      for (const channel of pc.channels) {
        channel.readyState = "open";
        channel.onopen?.();
        channel.dispatchEvent(new Event("open"));
      }
    });
    const control = pc.channels.find((channel) => channel.label === "mesh-onboarding")!;
    expect(mocks.setWebRTCSession.mock.calls[0][0].peerDestination).toBe("verified-answer-peer");
    await act(async () => {
      control.onmessage?.({ data: JSON.stringify({ type: "invitation_accepted", capabilities: "signed-reconnect-settings" }) });
    });

    expect(mocks.updateWebRTCSessionContact).toHaveBeenCalledWith("contact-alex", "onboarding:bridge");
    expect(mocks.updateWebRTCSessionApprovalPending).toHaveBeenCalledWith(true, "onboarding:bridge");
    const pendingUpdates = mocks.updateWebRTCSessionApprovalPending.mock.calls.length;
    await act(async () => {
      window.dispatchEvent(new CustomEvent("meshchat:approval", {
        detail: { approved: true, destination: "unrelated-peer" },
      }));
    });
    expect(mocks.updateWebRTCSessionApprovalPending).toHaveBeenCalledTimes(pendingUpdates);
    await act(async () => {
      window.dispatchEvent(new CustomEvent("meshchat:approval", {
        detail: { approved: true, destination: "verified-answer-peer" },
      }));
    });
    expect(mocks.updateWebRTCSessionApprovalPending).toHaveBeenLastCalledWith(false, "onboarding:bridge");
    await act(async () => {
      control.onmessage?.({ data: JSON.stringify({ type: "invitation_declined" }) });
    });
    expect(mocks.updateWebRTCSessionApprovalPending).toHaveBeenLastCalledWith(false, "onboarding:bridge");
  });

  it("answers Android capability requests on the desktop onboarding channel before and after dialog dismissal", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "reconnect_profiles") return { profiles: [{ contact_id: "known", destination_hash: "peer" }] };
      if (command === "reconnect_capabilities_get") return { local_capabilities: "encrypted-settings" };
      return implementation?.(command, payload);
    });
    const view = await join();
    let control!: FakeChannel;
    await act(async () => { control = view.pc.openControlChannel(); });
    // Android's control channel can open before the messaging bridge exists.
    await act(async () => { control.onmessage?.({ data: '{"type":"connection_capabilities_request"}' }); });
    mocks.setWebRTCSession.mockImplementation((session) => {
      mocks.getWebRTCSessionByKey.mockReturnValue(session);
      mocks.getWebRTCSessions.mockReturnValue([session]);
    });
    await act(async () => { view.pc.openIncomingChannel(); });
    expect(control.send).toHaveBeenCalledWith(JSON.stringify({ type: "connection_capabilities", document: "encrypted-settings" }));
    expect(mocks.getWebRTCSessions()[0].contactId).toBe("known");
    view.unmount();
    await advance(60_000);
    control.send.mockClear();
    await act(async () => { control.onmessage?.({ data: '{"type":"connection_capabilities_request"}' }); });
    expect(control.send).toHaveBeenCalledWith(JSON.stringify({ type: "connection_capabilities", document: "encrypted-settings" }));
    mocks.setWebRTCSession.mockReset();
  });

  it("checks refreshed capabilities against the contact bound to this channel", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "reconnect_capabilities_store") return { profile: { contact_id: "contact-alex" } };
      return implementation?.(command, payload);
    });
    const { pc } = await join();
    mocks.getWebRTCSessionByKey.mockReturnValue({ contactId: "contact-alex" });
    let control!: FakeChannel;
    await act(async () => {
      pc.openIncomingChannel();
      control = pc.openControlChannel();
    });
    await act(async () => {
      control.onmessage?.({ data: JSON.stringify({ type: "connection_capabilities", document: "fresh-settings" }) });
    });
    expect(mocks.serviceCommand).toHaveBeenCalledWith("reconnect_capabilities_store", {
      document: "fresh-settings", expected_contact_id: "contact-alex", expected_peer_destination: "peer",
    });
  });

  it("saves an invitation received after the connected browser dialog unmounts", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "receive_contact_invitation") return { id: "saved-invitation", state: "pending", preview: { display_name: "Alex", fingerprint: "fingerprint" }, workspace: null };
      return implementation?.(command, payload);
    });
    const view = await join();
    let control!: FakeChannel;
    await act(async () => {
      view.pc.openIncomingChannel();
      control = view.pc.openControlChannel();
    });
    view.unmount();
    await act(async () => {
      control.onmessage?.({ data: JSON.stringify({ type: "contact_invitation", document: "signed-invitation" }) });
    });
    expect(mocks.serviceCommand).toHaveBeenCalledWith("receive_contact_invitation", { document: "signed-invitation", peer_destination: "peer" });
    expect(mocks.serviceCommand).not.toHaveBeenCalledWith("decide_contact_invitation", expect.anything());
  });

  it.each([false, true])("preserves a connected browser transport when snapshot refresh fails (dialog closed: %s)", async (closed) => {
    let rejectRefresh!: (reason: Error) => void;
    const refresh = new Promise<void>((_, reject) => { rejectRefresh = reject; });
    const view = await join(() => refresh);
    let channel!: FakeChannel;
    await act(async () => { channel = view.pc.openIncomingChannel(); });
    expect(view.onConnected).toHaveBeenCalledOnce();
    if (closed) view.unmount();
    await act(async () => { rejectRefresh(new Error("temporary snapshot failure")); });
    const bridge = await mocks.attachWebRTCBridge.mock.results[0].value;
    expect(bridge.close).not.toHaveBeenCalled();
    expect(channel.close).not.toHaveBeenCalled();
    expect(view.pc.close).not.toHaveBeenCalled();
    if (!closed) expect(screen.queryByRole("alert")).toBeNull();
  });

  it("preserves a connected native answerer when its snapshot refresh fails", async () => {
    vi.stubGlobal("navigator", { userAgent: "Android" });
    const runCommand = mocks.serviceCommand.getMockImplementation()!;
    mocks.serviceCommand.mockImplementation(async (command: string, payload: unknown) => command === "native_webrtc_stats"
      ? { attached: true } : runCommand(command, payload));
    const onConnected = vi.fn();
    render(<WebRTCOnboardingDialog onClose={vi.fn()} onChanged={async () => { throw new Error("temporary snapshot failure"); }} onConnected={onConnected} />);
    await act(async () => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Join with WebRTC" }));
    fireEvent.change(screen.getByLabelText("Paste the signed WebRTC offer or mailbox code"), { target: { value: offerDocument } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Review and create answer" })); });
    expect(onConnected).toHaveBeenCalledOnce();
    expect(mocks.serviceCommand).not.toHaveBeenCalledWith("native_webrtc_close", expect.anything());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores an invitation preview that finishes after its control channel closes", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    let finishPreview!: (value: unknown) => void;
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "receive_contact_invitation") return new Promise((resolve) => { finishPreview = resolve; });
      return implementation?.(command, payload);
    });
    const { pc } = await join();
    let control!: FakeChannel;
    await act(async () => {
      pc.openIncomingChannel();
      control = pc.openControlChannel();
      control.onmessage?.({ data: JSON.stringify({ type: "contact_invitation", document: "signed-invitation" }) });
    });
    await act(async () => {
      control.close();
      finishPreview({ id: "saved-invitation", state: "pending", preview: { display_name: "Alex", fingerprint: "fingerprint" }, workspace: null });
    });
    expect(screen.queryByRole("button", { name: "Accept contact" })).toBeNull();
    expect(mocks.serviceCommand.mock.calls.some(([command]) => command === "decide_contact_invitation")).toBe(false);
  });

  it("shares the service's reconnect capability during contact acceptance without changing preferences", async () => {
    const implementation = mocks.serviceCommand.getMockImplementation();
    mocks.serviceCommand.mockImplementation(async (command: string, payload?: unknown) => {
      if (command === "receive_contact_invitation") return { id: "saved-invitation", state: "pending", preview: { display_name: "Alex", fingerprint: "fingerprint" }, workspace: null };
      if (command === "decide_contact_invitation") return { id: "contact-alex", reconnect_capabilities: "signed-reconnect-settings" };
      return implementation?.(command, payload);
    });
    const { pc } = await join();
    let control!: FakeChannel;
    await act(async () => {
      pc.openIncomingChannel();
      control = pc.openControlChannel();
      control.onmessage?.({ data: JSON.stringify({ type: "contact_invitation", document: "signed-invitation" }) });
    });
    expect(screen.getByText(/Automatic reconnect is enabled for new approved contacts/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Accept contact" }));
    });

    expect(mocks.serviceCommand).toHaveBeenCalledWith("decide_contact_invitation", { invitation_id: "saved-invitation", accept: true });
    expect(control.send).toHaveBeenCalledWith(JSON.stringify({
      type: "invitation_accepted", capabilities: "signed-reconnect-settings",
    }));
    expect(mocks.serviceCommand.mock.calls.some(([command]) => command === "reconnect_consent_set")).toBe(false);
    expect(screen.getByText(/Contact request sent. Waiting for the other person to approve it/)).toBeTruthy();
  });

  it("does not register a channel that closes while its path is being inspected", async () => {
    const { pc, onConnected } = await join();
    let resolveStats!: (value: Map<string, unknown>) => void;
    pc.getStats.mockImplementation(() => new Promise((resolve) => { resolveStats = resolve; }));
    let channel!: FakeChannel;
    await act(async () => { channel = pc.openIncomingChannel(); });
    expect(mocks.attachWebRTCBridge).toHaveBeenCalledTimes(1);
    await act(async () => {
      channel.close();
      resolveStats(new Map());
    });
    expect(mocks.setWebRTCSession).not.toHaveBeenCalled();
    expect(onConnected).not.toHaveBeenCalled();
    const bridge = await mocks.attachWebRTCBridge.mock.results[0].value;
    expect(bridge.close).toHaveBeenCalled();
    expect(pc.close).toHaveBeenCalled();
  });

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
    expect(screen.getByText(/reconnects quietly when both apps are open and unlocked/)).toBeTruthy();
    expect(screen.queryByText(/enable “Reconnect automatically”/)).toBeNull();
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
