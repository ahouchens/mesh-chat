import { afterEach, expect, it, vi } from "vitest";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import { prepareKeyedGroupCreation, prepareKeyedGroupSend, submitKeyedGroupCreation, submitKeyedGroupSend } from "./core-groups";
import { admitCoreRequest } from "./core-admission";
import { ProfileLifetime } from "./profile-lifetime";

const capabilities = {
  api_major: 1, api_minor: 1, operations: ["group.create", "group.message_enqueue"],
  optional_keyed_operations: ["group.create", "group.message_enqueue"],
  limits: { optional_key_idempotency_seconds: 604800, optional_keys_per_caller_profile: 4096, optional_keys_per_vault: 65536 },
};
const acceptance = { sent: true, accepted: true, message: "acceptance-reference", accepted_at: 1, idempotency_expires_at: 604801 };
afterEach(() => host.invoke.mockReset());

it("leaves an unadvertised legacy host without a keyed mutation or profile lookup", async () => {
  host.invoke.mockResolvedValue({ api_major: 1, api_minor: 0, operations: ["group.create", "group.message_enqueue"] });
  await expect(prepareKeyedGroupCreation("Name", "members", ["destination"], "ui-owned-key")).resolves.toBeNull();
  await expect(prepareKeyedGroupSend("group", "text", "ui-owned-key")).resolves.toBeNull();
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_capabilities", "core_api_capabilities"]);
});

it.each([0, -1, 1.5, undefined])("does not downgrade an advertised extension with invalid limit %s", async (value) => {
  host.invoke.mockResolvedValue({ ...capabilities, limits: { ...capabilities.limits, optional_keys_per_vault: value } });
  await expect(prepareKeyedGroupSend("group", "text", "ui-owned-key")).rejects.toMatchObject({ code: "unsupported_operation" });
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_capabilities"]);
});

it("replays the original group creation key and resolved member/profile payload after a lost reply", async () => {
  let lost = true;
  host.invoke.mockImplementation(async (command) => {
    if (command === "core_api_capabilities") return capabilities;
    if (command === "core_api_profile") return { profile: "original-profile" };
    if (command === "core_api_peer_for_destination") return { profile: "original-profile", peer: "original-peer" };
    if (lost) { lost = false; throw JSON.stringify({ code: "unavailable" }); }
    return { group: "original-group", name: "Original name" };
  });
  const destinations = ["destination"];
  const ticket = (await prepareKeyedGroupCreation("Original name", "members", destinations, "ui-owned-key"))!;
  destinations[0] = "other";
  await expect(submitKeyedGroupCreation(ticket, admitCoreRequest)).rejects.toMatchObject({ code: "unavailable" });
  await expect(submitKeyedGroupCreation(ticket, admitCoreRequest)).resolves.toEqual({ group: "original-group", name: "Original name" });
  const requests = host.invoke.mock.calls.filter(([command]) => command === "core_api_request");
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[0][1]).toEqual({ operation: "group.create", params: {
    profile: "original-profile", title: "Original name", posting_policy: "members", members: ["original-peer"],
  }, idempotencyKey: "ui-owned-key" });
  expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_profile")).toHaveLength(1);
});

it("keeps an uncertain send ticket stable and accepts only the explicit local acceptance projection", async () => {
  let lost = true;
  host.invoke.mockImplementation(async (command) => {
    if (command === "core_api_capabilities") return capabilities;
    if (command === "core_api_profile") return { profile: "original-profile" };
    if (lost) { lost = false; throw JSON.stringify({ code: "unavailable" }); }
    return acceptance;
  });
  const ticket = (await prepareKeyedGroupSend("group", "Original text", "ui-owned-key"))!;
  await expect(submitKeyedGroupSend(ticket, admitCoreRequest)).rejects.toMatchObject({ code: "unavailable" });
  await expect(submitKeyedGroupSend(ticket, admitCoreRequest)).resolves.toEqual(acceptance);
  const requests = host.invoke.mock.calls.filter(([command]) => command === "core_api_request");
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[0][1]).toEqual({ operation: "group.message_enqueue", params: {
    profile: "original-profile", group: "group", text: "Original text",
  }, idempotencyKey: "ui-owned-key" });
});

it("does not replace a receipt identity or invoke after a profile lifetime retires", async () => {
  host.invoke.mockImplementation(async (command) => command === "core_api_capabilities" ? capabilities : { profile: "profile" });
  const ticket = (await prepareKeyedGroupSend("group", "text", "ui-owned-key"))!;
  const lifetime = new ProfileLifetime();
  const generation = lifetime.capture();
  await lifetime.retire();
  await expect(submitKeyedGroupSend(ticket, (submit) => lifetime.mutate(generation, submit))).rejects.toMatchObject({ code: "profile_changed" });
  expect(host.invoke.mock.calls.some(([command]) => command === "core_api_request")).toBe(false);
});
