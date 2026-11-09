import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { coreApiGroupDraftSet, coreApiWorkspaceDraftSet, coreApiSendGroupMessage, coreApiTimelineMutation } from "./api";
import type { CoreRequestAdmission } from "./core-admission";
import { ProfileLifetime } from "./profile-lifetime";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}
afterEach(() => host.invoke.mockReset());

const mutations: Array<[string, (admit: CoreRequestAdmission) => Promise<unknown>]> = [
  ["group draft", (admit) => coreApiGroupDraftSet("group", "original text", admit)],
  ["workspace draft", (admit) => coreApiWorkspaceDraftSet("workspace", "conversation", "original text", "original-key", { mentions: ["member"] }, admit)],
  ["group enqueue", (admit) => coreApiSendGroupMessage("group", "original text", admit)],
  ["workspace read", (admit) => coreApiTimelineMutation("workspace", "workspace_read", { channel: "conversation", high_water: 7 }, "original-key", admit)],
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
