import { afterEach, beforeEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn(), events: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
vi.mock("./api", async (original) => ({ ...await original<typeof import("./api")>(), onServiceEvent: host.events }));
import type { ServiceEvent } from "./api";
import { ProfileLifetime } from "./profile-lifetime";
import type { CoreEffectScope } from "./core-admission";
import { attachWebRTCBridge } from "./webrtc-onboarding";
import { maintainReconnectCapabilities, RECONNECT_CAPABILITIES_EVENT } from "./reconnect-control";
import { closeWebRTCSession, setWebRTCSession } from "./webrtc-session";
import { NativeReconnectPeer } from "./native-reconnect-peer";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function scope(lifetime: ProfileLifetime): CoreEffectScope {
  const generation = lifetime.capture();
  return { admit: (request) => lifetime.mutate(generation, request),
    admitCleanup: (request) => lifetime.mutate(generation, request, true), isCurrent: () => lifetime.isCurrent(generation) };
}
function channel() {
  return { readyState: "open", send: vi.fn(), close: vi.fn(), onmessage: null, onclose: null, onerror: null } as unknown as RTCDataChannel;
}
const commands = () => host.invoke.mock.calls.filter(([command]) => command === "core_api_request")
  .map(([, request]) => request.params.command);
const bridges: Awaited<ReturnType<typeof attachWebRTCBridge>>[] = [];
const attached = { bridge_id: "original-bridge", max_packet: 1064, state: "online" };
beforeEach(() => { host.invoke.mockResolvedValue(attached); host.events.mockResolvedValue(vi.fn()); });
afterEach(async () => {
  host.invoke.mockResolvedValue({});
  await Promise.all(bridges.splice(0).map((bridge) => bridge.close()));
  await closeWebRTCSession();
  vi.useRealTimers(); host.invoke.mockReset(); host.events.mockReset();
});
async function reopen(lifetime: ProfileLifetime) {
  const retired = lifetime.retire();
  await vi.advanceTimersByTimeAsync(1000);
  await retired; lifetime.finishOpening(lifetime.beginOpening());
}

it("does not attach after deferred event registration crosses profile retirement", async () => {
  const registration = deferred<() => void>();
  const stop = vi.fn(); host.events.mockReturnValue(registration.promise);
  const lifetime = new ProfileLifetime(); const data = channel();
  const pending = attachWebRTCBridge(data, { effects: scope(lifetime) });
  const rejected = expect(pending).rejects.toThrow(/closed/);
  await lifetime.retire(); lifetime.finishOpening(lifetime.beginOpening());
  registration.resolve(stop); await rejected;
  expect(stop).toHaveBeenCalledOnce(); expect(data.close).toHaveBeenCalledOnce();
  expect(commands()).toEqual([]);
});

it("drops deferred Blob packets and old outbound events after profile retirement", async () => {
  let listener!: (event: ServiceEvent) => void;
  host.events.mockImplementation(async (callback) => { listener = callback; return vi.fn(); });
  const lifetime = new ProfileLifetime(); const data = channel();
  const bridge = await attachWebRTCBridge(data, { effects: scope(lifetime) }); bridges.push(bridge);
  const bytes = deferred<ArrayBuffer>();
  class SlowBlob extends Blob { arrayBuffer() { return bytes.promise; } }
  data.onmessage?.call(data, new MessageEvent("message", { data: new SlowBlob(["packet"]) }));
  await lifetime.retire(); lifetime.finishOpening(lifetime.beginOpening());
  bytes.resolve(new Uint8Array([1]).buffer);
  listener({ event: "webrtc_packet", bridge_id: bridge.bridgeId, data: "AQ==" } as ServiceEvent);
  await Promise.resolve(); await bridge.close();
  expect(data.send).not.toHaveBeenCalled(); expect(data.close).toHaveBeenCalledOnce();
  expect(commands()).toEqual(["webrtc_attach"]);
});

it("blocks legacy attach fallback when its channel owner closes before the Core reply", async () => {
  const reply = deferred<unknown>(); host.invoke.mockReturnValue(reply.promise);
  const data = channel(); let current = true;
  const pending = attachWebRTCBridge(data, { isCurrent: () => current });
  const rejected = expect(pending).rejects.toMatchObject({ code: "profile_changed" });
  await vi.waitFor(() => expect(commands()).toEqual(["webrtc_attach"]));
  current = false; reply.reject("core_api_unavailable"); await rejected;
  expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
  expect(data.close).toHaveBeenCalledOnce();
});
it("closes local channels without sending old detach commands after a native host replacement", async () => {
  const lifetime = new ProfileLifetime(); const data = channel();
  const bridge = await attachWebRTCBridge(data, { effects: scope(lifetime) }); bridges.push(bridge);
  lifetime.register(lifetime.capture(), () => bridge.close());
  await lifetime.retire(false);
  expect(data.close).toHaveBeenCalledOnce(); expect(data.onmessage).toBeNull();
  expect(commands()).toEqual(["webrtc_attach"]);
});

it("never falls back or restores an old bridge after a health reply crosses reopening", async () => {
  vi.useFakeTimers(); const lifetime = new ProfileLifetime(); const data = channel();
  const bridge = await attachWebRTCBridge(data, { effects: scope(lifetime) }); bridges.push(bridge);
  const reply = deferred<unknown>(); host.invoke.mockReturnValue(reply.promise);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(commands()).toEqual(["webrtc_attach", "webrtc_attach"]);
  await reopen(lifetime); reply.reject("core_api_unavailable");
  await vi.advanceTimersByTimeAsync(30_000); await bridge.close();
  expect(commands()).toEqual(["webrtc_attach", "webrtc_attach"]);
  expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
});

it("does not dispatch capability changes, send late refreshes or store queued documents after retirement", async () => {
  vi.useFakeTimers(); const lifetime = new ProfileLifetime();
  const refresh = deferred<unknown>(); const store = deferred<unknown>();
  host.invoke.mockImplementation(async (_command, request) => request.params.command === "reconnect_capabilities_get" ? refresh.promise : store.promise);
  const control = channel(); const changed = vi.fn(); window.addEventListener(RECONNECT_CAPABILITIES_EVENT, changed);
  setWebRTCSession({ key: "original", effects: scope(lifetime), contactId: "contact", controlPurpose: "reconnect", control,
    channel: channel(), pc: { close: vi.fn() } as unknown as RTCPeerConnection,
    bridge: { bridgeId: "original", maxPacket: 1064, close: async () => undefined }, path: "unknown", createdAt: 1, approvalPending: false });
  maintainReconnectCapabilities();
  control.onmessage?.call(control, new MessageEvent("message", { data: JSON.stringify({ type: "connection_capabilities", document: "first" }) }));
  control.onmessage?.call(control, new MessageEvent("message", { data: JSON.stringify({ type: "connection_capabilities", document: "second" }) }));
  await vi.waitFor(() => expect(commands()).toEqual(["reconnect_capabilities_get", "reconnect_capabilities_store"]));
  await reopen(lifetime);
  refresh.resolve({ local_capabilities: "old-signed-document" }); store.resolve({ profile: { contact_id: "contact" } });
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  expect(changed).not.toHaveBeenCalled();
  expect(control.send).toHaveBeenCalledTimes(1); // Initial request only.
  expect(commands()).toEqual(["reconnect_capabilities_get", "reconnect_capabilities_store"]);
  window.removeEventListener(RECONNECT_CAPABILITIES_EVENT, changed);
});

it("does not mark a native peer attached when a healthy status arrives after retirement", async () => {
  vi.useFakeTimers(); const lifetime = new ProfileLifetime(); const reply = deferred<unknown>();
  host.invoke.mockReturnValue(reply.promise);
  const peer = NativeReconnectPeer.create({ iceServers: [], iceTransportPolicy: "all" }, "offer", undefined, scope(lifetime));
  const pending = peer.open(); const rejected = expect(pending).rejects.toMatchObject({ code: "profile_changed" });
  await vi.waitFor(() => expect(commands()).toEqual(["native_webrtc_stats"]));
  await reopen(lifetime); reply.resolve({ attached: true, data_channel_state: "open", ice_connection_state: "connected" });
  await rejected; expect(peer.isAttached()).toBe(false);
  expect(commands()).toEqual(["native_webrtc_stats"]);
});
