import { beforeEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
import { openCoreGroupComposer, groupComposerRequests } from "./core-group-composer";
import { groupComposerCapabilities as caps, GroupComposerHostFixture } from "./test/group-composer-host";
let fixture: GroupComposerHostFixture;
beforeEach(() => {
  host.invoke.mockReset(); fixture = new GroupComposerHostFixture();
  host.invoke.mockImplementation(async (command, args) => command === "core_api_capabilities" ? caps : command === "core_api_profile" ? { profile: "profile" }
    : fixture.request(args.operation, args.params, args.idempotencyKey));
});
it("uses exact group scope and Core-issued keys, with no text or generated nonce in enqueue", async () => {
  const opened = (await openCoreGroupComposer("group"))!; const current = await opened.port.query();
  const update = await opened.port.update(current.revision, "Group text", current.update_key);
  await opened.port.enqueue(update.applied_revision);
  expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", { operation: "group.message_enqueue_draft", params: { profile: "profile", group: "group", draft_revision: update.applied_revision }, idempotencyKey: update.applied_revision });
  expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_request").map(([, args]) => args.operation)).toEqual(["group.composer_query", "group.composer_update", "group.message_enqueue_draft"]);
});
it.each(["operation", "limit", "minor"])("refuses an incomplete advertised %s contract without profile lookup", async (kind) => {
  const value = structuredClone(caps); if (kind === "operation") value.operations.pop();
  if (kind === "limit") value.limits.group_composer_send_keys_per_vault = 0;
  if (kind === "minor") value.api_minor = 0;
  host.invoke.mockResolvedValue(value);
  await expect(openCoreGroupComposer("group")).rejects.toMatchObject({ code: "unsupported_operation" });
  expect(host.invoke).toHaveBeenCalledOnce();
});
it("selects legacy only for a positively unadvertised family", async () => {
  host.invoke.mockResolvedValue({ ...caps, operations: ["group.message_enqueue"] });
  expect(await openCoreGroupComposer("group")).toBeNull(); expect(host.invoke).toHaveBeenCalledOnce();
});
it("preserves typed uncertainty without issuing a legacy request", async () => {
  host.invoke.mockRejectedValue(JSON.stringify({ code: "unavailable", retry_after_ms: 20 }));
  await expect(groupComposerRequests({ profile: "profile", group: "group" }, 16384).enqueue("a".repeat(64))).rejects.toMatchObject({ code: "unavailable", retry_after_ms: 20 });
  expect(host.invoke).toHaveBeenCalledOnce();
});
it("rejects a response for another group instead of adopting its text or keys", async () => {
  host.invoke.mockResolvedValue({ ...fixture.snapshot(), group: "other" });
  await expect(groupComposerRequests({ profile: "profile", group: "group" }, 16384).query()).rejects.toMatchObject({ code: "core_api_protocol" });
});
it("retains the bound group when the caller mutates the target object", async () => {
  const target = { profile: "profile", group: "group" }; const port = groupComposerRequests(target, 16384); target.group = "other";
  await port.query(); expect(host.invoke.mock.calls[0][1].params.group).toBe("group");
});
