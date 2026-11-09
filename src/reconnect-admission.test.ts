import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { createReconnectDeps } from "./reconnect-runtime";
import { ProfileLifetime } from "./profile-lifetime";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
afterEach(() => { host.invoke.mockReset(); vi.useRealTimers(); });

it.each(["start", "stop"] as const)("does not %s reconnect after its peer lookup outlives the profile", async (action) => {
  const target = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_peer_for_destination" ? target.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const deps = createReconnectDeps({ refresh: async () => undefined, admit: (submit) => lifetime.mutate(generation, submit) });
  const request = deps[action]("contact", "destination");
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  target.resolve({ profile: "original-profile", peer: "original-peer" });
  await rejected;
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_peer_for_destination"]);
});

it("does not enter a reconnect fallback after an old unavailable peer lookup completes", async () => {
  const target = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_peer_for_destination" ? target.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const deps = createReconnectDeps({ refresh: async () => undefined, admit: (submit) => lifetime.mutate(generation, submit) });
  const request = deps.start("contact", "destination");
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  target.reject("core_api_unavailable");
  await rejected;
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_peer_for_destination"]);
});

it("retains its originating admission when a reused options object changes after reopening", async () => {
  const target = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_peer_for_destination" ? target.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const options = { refresh: async () => undefined, admit: <T>(submit: () => Promise<T>) => lifetime.mutate(generation, submit) };
  const deps = createReconnectDeps(options);
  const request = deps.start("contact", "destination");
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  const current = lifetime.capture();
  options.admit = (submit) => lifetime.mutate(current, submit);
  target.resolve({ profile: "original-profile", peer: "original-peer" });
  await rejected;
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_peer_for_destination"]);
});

it("does not invoke a legacy reconnect fallback after the primary Core result outlives retirement", async () => {
  vi.useFakeTimers();
  const primary = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_request" ? primary.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const deps = createReconnectDeps({ refresh: async () => undefined, admit: (submit) => lifetime.mutate(generation, submit) });
  const request = deps.requestCreate("contact", "original-attempt");
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  const retirement = lifetime.retire();
  await vi.advanceTimersByTimeAsync(1000);
  await retirement;
  lifetime.finishOpening(lifetime.beginOpening());
  primary.reject("core_api_unavailable");
  await rejected;
  expect(host.invoke.mock.calls.filter(([command]) => command === "service_command")).toHaveLength(0);
});
