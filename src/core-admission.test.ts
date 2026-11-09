import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { coreApiGroupDraftSet, coreApiWorkspaceDraftSet, coreApiSendGroupMessage, coreApiTimelineMutation,
  saveNetworkSettings, saveCallSettings, coreApiRemoteProfile, coreApiUpdatePeer, coreApiWorkspaceAdminRequest,
  coreApiWorkspaceMemberRole, coreApiCreateWorkspaceChannel, serviceCommand } from "./api";
import type { CoreRequestAdmission } from "./core-admission";
import { ProfileLifetime } from "./profile-lifetime";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((finish, fail) => { resolve = finish; reject = fail; });
  return { promise, resolve, reject };
}
afterEach(() => { host.invoke.mockReset(); vi.useRealTimers(); });

const mutations: Array<[string, (admit: CoreRequestAdmission) => Promise<unknown>]> = [
  ["group draft", (admit) => coreApiGroupDraftSet("group", "original text", admit)],
  ["workspace draft", (admit) => coreApiWorkspaceDraftSet("workspace", "conversation", "original text", "original-key", { mentions: ["member"] }, admit)],
  ["group enqueue", (admit) => coreApiSendGroupMessage("group", "original text", admit)],
  ["workspace read", (admit) => coreApiTimelineMutation("workspace", "workspace_read", { channel: "conversation", high_water: 7 }, "original-key", admit)],
  ["network settings", (admit) => saveNetworkSettings({ nearby_discovery: false }, admit)],
  ["call settings", (admit) => saveCallSettings({ turn_enabled: false }, admit)],
  ["propagation consent", (admit) => coreApiRemoteProfile("approve_propagation", { remote_profile_id: "remote" }, "original-key", admit)],
  ["admin decision", (admit) => coreApiWorkspaceAdminRequest("workspace", "request", "approve", "original-key", admit)],
  ["role change", (admit) => coreApiWorkspaceMemberRole("workspace", "member", "admin", "original-key", admit)],
];

it.each(mutations)("blocks %s when its profile lookup finishes after retirement and reopening", async (_name, invoke) => {
  const profile = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_profile" ? profile.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const request = invoke((submit) => lifetime.mutate(generation, submit));
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  profile.resolve({ profile: "original-profile" });
  await rejected;
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_profile"]);
});

it("preserves the original workspace draft payload and key at admitted transport invocation", async () => {
  host.invoke.mockResolvedValue({ profile: "original-profile" });
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  await coreApiWorkspaceDraftSet("workspace", "conversation", "original text", "original-key", {
    threadRoot: "root", mentions: ["member"],
  }, (submit) => lifetime.mutate(generation, submit));
  expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", {
    operation: "workspace.draft_set", params: { profile: "original-profile", workspace: "workspace", conversation: "conversation",
      text: "original text", thread_root: "root", mention_member_ids: ["member"] }, idempotencyKey: "original-key",
  });
});

it("blocks contact updates whose peer lookup finishes after retirement", async () => {
  const peer = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_peer_for_destination" ? peer.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const request = coreApiUpdatePeer("destination", "rename", "New name", (submit) => lifetime.mutate(generation, submit));
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await lifetime.retire();
  lifetime.finishOpening(lifetime.beginOpening());
  peer.resolve({ profile: "profile", peer: "peer" });
  await rejected;
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_peer_for_destination"]);
});

it("does not apply a channel topic when the earlier create reply arrives after retirement", async () => {
  const created = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_profile" ? { profile: "profile" } : created.promise);
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const request = coreApiCreateWorkspaceChannel("workspace", "name", "topic", "public", [], "original-key",
    (submit) => lifetime.mutate(generation, submit));
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  await vi.waitFor(() => expect(host.invoke).toHaveBeenCalledTimes(2));
  const retirement = lifetime.retire();
  created.resolve({ channel: "created-channel", name: "name" });
  await rejected;
  await retirement;
  expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_request")).toHaveLength(1);
});

it("does not reopen legacy admission when an old Core absence response arrives after retirement", async () => {
  vi.useFakeTimers();
  const primary = deferred<unknown>();
  host.invoke.mockImplementation(async (command) => command === "core_api_request" ? primary.promise : {});
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  const request = serviceCommand("reconcile_mobile_lifecycle", {}, (submit) => lifetime.mutate(generation, submit));
  const rejected = expect(request).rejects.toMatchObject({ code: "profile_changed" });
  const retirement = lifetime.retire();
  await vi.advanceTimersByTimeAsync(1000);
  await retirement;
  lifetime.finishOpening(lifetime.beginOpening());
  primary.reject("core_api_unavailable");
  await rejected;
  expect(host.invoke.mock.calls.filter(([command]) => command === "service_command")).toHaveLength(0);
});
