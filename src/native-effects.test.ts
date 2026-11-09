import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { nativeWebRTCOffer, closeNativeWebRTCSessions } from "./native-webrtc";
import { ProfileLifetime } from "./profile-lifetime";
import type { CoreEffectScope } from "./core-admission";

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
const ice = { iceServers: [], iceTransportPolicy: "all" as const };
const sdp = { ok: true, sdp: "original-sdp", fingerprint: "original-fingerprint" };
const nativeCommands = () => host.invoke.mock.calls.filter(([command]) => command === "core_api_request")
  .map(([, request]) => request.params.command);
afterEach(async () => { host.invoke.mockResolvedValue({}); await closeNativeWebRTCSessions(); host.invoke.mockReset(); vi.useRealTimers(); });

it("does not invoke native legacy fallback or late cleanup after the originating profile reopens", async () => {
  vi.useFakeTimers();
  const reply = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_request" ? reply.promise : {});
  const lifetime = new ProfileLifetime();
  const pending = nativeWebRTCOffer("original-session", ice, undefined, undefined, scope(lifetime));
  const rejected = expect(pending).rejects.toMatchObject({ code: "profile_changed" });
  await vi.waitFor(() => expect(nativeCommands()).toEqual(["native_webrtc_offer"]));
  const retirement = lifetime.retire();
  await vi.advanceTimersByTimeAsync(1000);
  await retirement;
  lifetime.finishOpening(lifetime.beginOpening());
  reply.reject("core_api_unavailable");
  await rejected;
  expect(nativeCommands()).toEqual(["native_webrtc_offer"]);
  expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
});

it("uses the original session scope for registry cleanup after retirement", async () => {
  host.invoke.mockResolvedValue(sdp);
  const lifetime = new ProfileLifetime();
  await nativeWebRTCOffer("original-session", ice, undefined, undefined, scope(lifetime));
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  await closeNativeWebRTCSessions();
  expect(nativeCommands()).toEqual(["native_webrtc_offer"]);
});

it("drains an admitted exact cleanup during the retirement grace period", async () => {
  const close = deferred<unknown>();
  host.invoke.mockImplementation(async (_command, request) => request.params.command === "native_webrtc_close" ? close.promise : sdp);
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  await nativeWebRTCOffer("original-session", ice, undefined, undefined, scope(lifetime));
  lifetime.register(generation, () => closeNativeWebRTCSessions());
  let retired = false;
  const retirement = lifetime.retire().then((result) => { retired = true; return result; });
  await vi.waitFor(() => expect(nativeCommands()).toContain("native_webrtc_close"));
  expect(retired).toBe(false);
  close.resolve({});
  await expect(retirement).resolves.toBe("drained");
  expect(nativeCommands()).toEqual(["native_webrtc_offer", "native_webrtc_close"]);
});

it("does not close a replacement registration when an older creation returns late", async () => {
  const first = deferred<unknown>();
  let offers = 0;
  host.invoke.mockImplementation(async (_command, request) => request.params.command === "native_webrtc_offer" && ++offers === 1 ? first.promise : sdp);
  const pending = nativeWebRTCOffer("reused-session", ice);
  const rejected = expect(pending).rejects.toThrow(/cancelled/);
  await nativeWebRTCOffer("reused-session", ice);
  first.resolve(sdp);
  await rejected;
  expect(nativeCommands()).toEqual(["native_webrtc_offer", "native_webrtc_offer"]);
  await closeNativeWebRTCSessions();
  expect(nativeCommands()).toEqual(["native_webrtc_offer", "native_webrtc_offer", "native_webrtc_close"]);
});
