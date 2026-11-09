import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));

import { CallDialog } from "./CallDialog";
import { CallRecoveryNotice } from "./CallRecoveryNotice";
import { callRecovery } from "./call-operation";

const sdp = "v=0\r\na=fingerprint:sha-256 AA:BB\r\na=candidate:1 1 udp 1 192.0.2.1 1234 typ host\r\n";
const stop = vi.fn();
const capture = vi.fn();
let losses: number;
let endLosses: number;
let calls: number;
let ends: number;
let delayStart: (() => Promise<void>) | null;
let rejectReplay: boolean;
const receipts = new Map<string, Record<string, unknown>>();
const mutations = () => host.invoke.mock.calls.filter(([command, request]) => command === "core_api_request" && request.operation === "call.control")
  .map(([, request]) => request as { params: Record<string, unknown>; idempotencyKey: string });

class Peer {
  static instances: Peer[] = [];
  constructor() { Peer.instances.push(this); }
  connectionState = "new";
  iceGatheringState = "complete";
  signalingState = "stable";
  localDescription: RTCSessionDescriptionInit | null = null;
  ontrack = null;
  onconnectionstatechange = null;
  createOffer = vi.fn(async () => ({ type: "offer", sdp }));
  createAnswer = vi.fn(async () => ({ type: "answer", sdp }));
  setLocalDescription = vi.fn(async (value: RTCSessionDescriptionInit) => { this.localDescription = value; });
  setRemoteDescription = vi.fn(async () => undefined);
  addTrack() {}
  getSenders() { return []; }
  getStats() { return Promise.resolve(new Map()); }
  close = vi.fn(() => { this.connectionState = "closed"; });
}

beforeEach(() => {
  losses = 1; endLosses = 0; calls = 0; ends = 0; delayStart = null; rejectReplay = false;
  receipts.clear(); Peer.instances = []; stop.mockReset(); capture.mockReset(); host.invoke.mockReset();
  capture.mockResolvedValue({ getTracks: () => [{ kind: "audio", stop }], getAudioTracks: () => [], getVideoTracks: () => [] });
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: capture } });
  vi.stubGlobal("RTCPeerConnection", Peer);
  host.invoke.mockImplementation(async (command: string, request: { operation: string; params: Record<string, unknown>; idempotencyKey: string }) => {
    if (command === "runtime_platform") return "desktop";
    if (command === "begin_call_audio") return { granted: true };
    if (command === "end_call_audio") return { active: false };
    if (command === "core_api_profile") return { profile: "original-profile" };
    if (request.operation === "call.ice_servers") return { ice: { iceServers: [], iceTransportPolicy: "all" } };
    if (request.operation === "application.snapshot") return { calls: [{ id: "one-call", core_handle: "scoped-call" }] };
    if (request.operation === "call.media_query") return { media: { id: "one-call", state: "dialing", remote_sdp: null } };
    if (request.operation !== "call.control") throw new Error("Unexpected Core request");
    const existing = receipts.get(request.idempotencyKey);
    if (existing) {
      if (rejectReplay) throw JSON.stringify({ code: "unavailable", outcome: "unknown" });
      return { result: existing };
    }
    const ending = request.params.action === "end";
    if (ending) ends += 1; else calls += 1;
    const result = { id: "one-call", contact_id: "contact", role: "caller", media: "audio", state: ending ? "ended" : "dialing", direction: "outbound" };
    receipts.set(request.idempotencyKey, result);
    if (!ending) await delayStart?.();
    if (ending ? endLosses-- > 0 : losses-- > 0) throw JSON.stringify({ code: "unavailable", outcome: "unknown", retry_after_ms: null });
    return { result };
  });
});

afterEach(async () => {
  cleanup(); rejectReplay = false; endLosses = 0;
  for (const session of callRecovery.getSnapshot()) await session.retry();
  await waitFor(() => expect(callRecovery.getSnapshot()).toHaveLength(0));
  vi.unstubAllGlobals();
});

function open() {
  const closed = vi.fn();
  const view = render(<CallDialog contact={{ id: "contact", display_name: "Taylor" }} onClose={closed} onChanged={async () => undefined} />);
  fireEvent.click(screen.getByRole("button", { name: "Audio call" }));
  return { ...view, closed };
}

it("resolves a committed start with the same ticket and original SDP without recapturing media", async () => {
  open();
  fireEvent.click(await screen.findByRole("button", { name: "Resolve previous call operation" }));
  await screen.findByText("Calling and waiting for an answer…");
  expect(calls).toBe(1);
  expect(mutations()[1]).toEqual(mutations()[0]);
  expect(capture).toHaveBeenCalledTimes(1);
  expect(Peer.instances).toHaveLength(1);
  expect(Peer.instances[0].createOffer).toHaveBeenCalledTimes(1);
  expect(stop).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(ends).toBe(1));
  expect(mutations()[2].params).toMatchObject({ action: "end", call_id: "one-call", reason: "cancelled" });
  expect(stop).toHaveBeenCalled();
});

it.each(["cancel", "unmount"])("resolves the uncertain start before exact cleanup on %s", async (action) => {
  const view = open();
  await screen.findByRole("button", { name: "Resolve previous call operation" });
  if (action === "unmount") view.unmount();
  else fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(ends).toBe(1));
  expect(calls).toBe(1);
  expect(mutations().map((request) => request.params.action)).toEqual(["start", "start", "end"]);
  expect(mutations()[1]).toEqual(mutations()[0]);
  expect(mutations()[2].params.call_id).toBe("one-call");
  expect(capture).toHaveBeenCalledTimes(1);
  expect(Peer.instances[0].createOffer).toHaveBeenCalledTimes(1);
  expect(stop).toHaveBeenCalled();
  expect(Peer.instances[0].close).toHaveBeenCalled();
});

it("cancels an in-flight start and resolves a later lost reply before ending it", async () => {
  let release!: () => void;
  delayStart = () => new Promise<void>((resolve) => { release = resolve; });
  const view = open();
  await waitFor(() => expect(calls).toBe(1));
  view.unmount();
  expect(stop).toHaveBeenCalled();
  release();
  await waitFor(() => expect(ends).toBe(1));
  expect(mutations()[1]).toEqual(mutations()[0]);
  expect(calls).toBe(1);
  expect(capture).toHaveBeenCalledTimes(1);
});

it("keeps unresolved cleanup visible after unmount for explicit same-ticket recovery", async () => {
  const view = open();
  await screen.findByRole("button", { name: "Resolve previous call operation" });
  rejectReplay = true;
  view.unmount();
  render(<CallRecoveryNotice />);
  const retry = await screen.findByRole("button", { name: "Retry call cleanup" });
  await waitFor(() => expect(retry).toHaveProperty("disabled", false));
  expect(ends).toBe(0);
  expect(stop).toHaveBeenCalled();
  rejectReplay = false;
  fireEvent.click(retry);
  await waitFor(() => expect(ends).toBe(1));
  expect(mutations()[1]).toEqual(mutations()[0]);
  expect(mutations()[2]).toEqual(mutations()[0]);
  expect(calls).toBe(1);
  expect(capture).toHaveBeenCalledTimes(1);
});
