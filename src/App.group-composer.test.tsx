import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Group, Snapshot } from "./types";
import { GroupComposerHostFixture, groupComposerCapabilities } from "./test/group-composer-host";
const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => undefined) }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(async () => []), onOpenUrl: vi.fn(async () => () => undefined) }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import App from "./App";

const profileHandle = "c".repeat(64), groupHandle = "d".repeat(64);
const profile = { display_name: "Alex", public_identity: "alex", identity_hash: "11".repeat(16), destination_hash: "22".repeat(16), fingerprint: "AAAA BBBB", created_at: 1 };
const group: Group = { id: "local-group", core_handle: groupHandle, title: "Field team", owner_destination: profile.destination_hash,
  posting_policy: "members", status: "active", epoch: 1, manifest_hash: "e".repeat(64), created_at: 1, updated_at: 1,
  members: [{ destination_hash: profile.destination_hash, display_name: "Alex", role: "owner", status: "active", fingerprint: profile.fingerprint },
    { destination_hash: "44".repeat(16), display_name: "Taylor", role: "member", status: "active", fingerprint: "CCCC DDDD" }] };
let current: Snapshot, fixture: GroupComposerHostFixture, snapshotsFail: boolean;
const requests = (operation: string) => host.invoke.mock.calls.filter(([command, args]) => command === "core_api_request" && args.operation === operation).map(([, args]) => args);
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; }
beforeEach(() => {
  fixture = new GroupComposerHostFixture(profileHandle, groupHandle); snapshotsFail = false;
  current = { profile, contacts: [], messages: [], drafts: [], groups: [group], group_messages: [], group_drafts: [{ group_id: group.id, text: "Old shared snapshot text" }], service_error: null,
    settings: { nearby_discovery: true, lan_fallback: true, lan_listener_port: null, allowed_interfaces: [], tcp_clients: [], tcp_listener: null, help_route: false, store_for_offline: false, approved_propagation_nodes: [], i2p_enabled: false, i2p_connectable: false, i2p_managed: true, i2p_peers: [] },
    network: { transport_enabled: false, propagation_enabled: false, interface_available: true, interfaces: [], outbound_propagation_node: null } };
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "initialize_service" || command === "lock_service" || command === "set_native_theme") return;
    if (command === "runtime_platform") return "desktop";
    if (command === "core_api_capabilities") return groupComposerCapabilities;
    if (command === "core_api_profile") return { profile: profileHandle, destination: profile.destination_hash, peers: [], connections: [] };
    if (command === "core_api_request") {
      if (args.operation === "application.snapshot") { if (snapshotsFail) throw JSON.stringify({ code: "unavailable" }); return current; }
      if (groupComposerCapabilities.operations.includes(args.operation)) return fixture.request(args.operation, args.params, args.idempotencyKey);
      if (["group.draft_set", "group.message_enqueue"].includes(args.operation)) throw new Error("Composer must not use legacy group mutation");
      if (args.operation === "native.command") return { profiles: [], sessions: [] };
      if (args.operation === "remote_profile.query") return { profiles: [] };
      if (args.operation === "workspace.snapshot") return { workspaces: [], workspace_join_requests: [] };
      if (args.operation === "call.settings_query") return { settings: {} };
      return {};
    }
    if (command === "service_command") throw new Error("No legacy command fallback");
    return {};
  });
});
afterEach(() => { cleanup(); host.invoke.mockReset(); });
async function open() {
  const rendered = render(<App />);
  const field = await screen.findByRole("textbox", { name: `Message ${group.title}` });
  await waitFor(() => expect(field).toHaveProperty("readOnly", false));
  return { ...rendered, field };
}
async function typeAndSend(field: HTMLElement, text: string) {
  fireEvent.change(field, { target: { value: text } }); fireEvent.click(screen.getByRole("button", { name: "Send group message" }));
}
it("uses Core draft state instead of snapshot shared text and never separately clears after acceptance", async () => {
  const { field } = await open(); expect(field).toHaveProperty("value", "");
  await typeAndSend(field, "Atomic group note");
  await screen.findByRole("textbox", { name: "Saved group message text" });
  const update = requests("group.composer_update")[0], send = requests("group.message_enqueue_draft")[0];
  expect(update.idempotencyKey).toMatch(/^[a-f0-9]{64}$/); expect(send.idempotencyKey).toBe(send.params.draft_revision);
  expect(send.params).toEqual({ profile: profileHandle, group: groupHandle, draft_revision: send.idempotencyKey });
  expect(requests("group.draft_set")).toHaveLength(0); expect(requests("group.message_enqueue")).toHaveLength(0);
});
it("recovers historical accepted text after a lost reply and full App remount without sending again", async () => {
  fixture.loseNextSendReply = true; const first = await open(); await typeAndSend(first.field, "Committed before reload");
  await screen.findByRole("button", { name: "Retry previous group send" }); first.unmount();
  const second = await open();
  expect(await screen.findByRole("textbox", { name: "Saved group message text" })).toHaveProperty("value", "Committed before reload");
  expect(second.field).toHaveProperty("value", ""); expect(fixture.messageCount).toBe(1);
  expect(requests("group.message_enqueue_draft")).toHaveLength(1);
});
it("reuses the saved Core revision after an unaccepted lost send and full App remount", async () => {
  const original = host.invoke.getMockImplementation()!; let lose = true;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && args.operation === "group.message_enqueue_draft" && lose) { lose = false; throw JSON.stringify({ code: "unavailable" }); }
    return original(command, args);
  });
  const first = await open(); await typeAndSend(first.field, "Not accepted yet"); await screen.findByRole("button", { name: "Retry previous group send" });
  const originalRevision = requests("group.message_enqueue_draft")[0].idempotencyKey; first.unmount();
  const second = await open(); expect(second.field).toHaveProperty("value", "Not accepted yet");
  expect(requests("group.message_enqueue_draft")).toHaveLength(1); fireEvent.click(screen.getByRole("button", { name: "Send group message" }));
  await screen.findByRole("textbox", { name: "Saved group message text" });
  expect(requests("group.message_enqueue_draft")[1].idempotencyKey).toBe(originalRevision); expect(fixture.messageCount).toBe(1);
});
it("explicit retry returns historical acceptance while preserving a newer server draft and local text", async () => {
  fixture.loseNextSendReply = true; const { field } = await open(); await typeAndSend(field, "Original");
  const retry = await screen.findByRole("button", { name: "Retry previous group send" });
  fixture.replace("New saved draft"); fireEvent.change(field, { target: { value: "New local draft" } }); fireEvent.click(retry);
  await screen.findByRole("textbox", { name: "Local text kept for review" });
  expect(field).toHaveProperty("value", "New saved draft");
  expect(screen.getByRole("textbox", { name: "Local text kept for review" })).toHaveProperty("value", "New local draft");
  expect(screen.getByRole("textbox", { name: "Saved group message text" })).toHaveProperty("value", "Original");
  const sends = requests("group.message_enqueue_draft"); expect(sends).toHaveLength(2); expect(sends[1]).toEqual(sends[0]); expect(fixture.messageCount).toBe(1);
});
it("does not resend after confirmed acceptance when conversation refresh fails", async () => {
  const { field } = await open(); snapshotsFail = true; await typeAndSend(field, "Saved despite refresh failure");
  await screen.findByText("Your message was saved. The conversation could not refresh yet.");
  expect(field).toHaveProperty("value", ""); expect(requests("group.message_enqueue_draft")).toHaveLength(1); expect(fixture.messageCount).toBe(1);
});
it("recovers a committed draft update after full App remount without allocating a replacement update key", async () => {
  fixture.loseNextUpdateReply = true; const first = await open(); fireEvent.change(first.field, { target: { value: "Draft committed" } });
  await screen.findByRole("button", { name: "Retry draft save" }); first.unmount();
  const second = await open(); expect(second.field).toHaveProperty("value", "Draft committed");
  expect(requests("group.composer_update")).toHaveLength(1); expect(requests("group.message_enqueue_draft")).toHaveLength(0);
});
it("holds expired sends for review and never creates a replacement send key", async () => {
  fixture.loseNextSendReply = true; const { field } = await open(); await typeAndSend(field, "Old send");
  const retry = await screen.findByRole("button", { name: "Retry previous group send" }); fixture.expireSends = true; fireEvent.click(retry);
  await screen.findByText(/previous send has expired/);
  const sends = requests("group.message_enqueue_draft"); expect(sends).toHaveLength(2); expect(sends[1]).toEqual(sends[0]); expect(fixture.messageCount).toBe(1);
});
it("does not downgrade to legacy or fresh keys when current group authority is revoked", async () => {
  fixture.loseNextSendReply = true; const { field } = await open(); await typeAndSend(field, "Original");
  const retry = await screen.findByRole("button", { name: "Retry previous group send" }); fixture.forbidden = true; fireEvent.click(retry);
  await waitFor(() => expect(requests("group.composer_query").length).toBeGreaterThan(1));
  expect(requests("group.message_enqueue_draft")).toHaveLength(2); expect(requests("group.draft_set")).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Send group message" })).toHaveProperty("disabled", true);
});
it("does not enqueue or save from an old profile after a delayed Core query resolves", async () => {
  const query = deferred<unknown>(); const original = host.invoke.getMockImplementation()!; let firstQuery = true;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && args.operation === "group.composer_query" && firstQuery) { firstQuery = false; return query.promise; }
    return original(command, args);
  });
  render(<App />); await waitFor(() => expect(requests("group.composer_query")).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" })); await screen.findByRole("button", { name: "Unlock" });
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
  const field = await screen.findByRole("textbox", { name: `Message ${group.title}` }); await waitFor(() => expect(field).toHaveProperty("readOnly", false));
  await act(async () => query.resolve(fixture.snapshot()));
  expect(requests("group.composer_update")).toHaveLength(0); expect(requests("group.message_enqueue_draft")).toHaveLength(0);
});
it("cancels a queued send when posting is revoked while its draft update reply is pending", async () => {
  const reply = deferred<unknown>(); const original = host.invoke.getMockImplementation()!;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && args.operation === "group.composer_update") { await original(command, args); return reply.promise; }
    return original(command, args);
  });
  const { field } = await open(); await typeAndSend(field, "Revoked before enqueue");
  await waitFor(() => expect(requests("group.composer_update")).toHaveLength(1));
  const committed = fixture.snapshot();
  current = { ...current, groups: [{ ...group, status: "removed" }] };
  await act(async () => window.dispatchEvent(new Event("focus")));
  await screen.findAllByText("You are no longer an active member of this group.");
  await act(async () => reply.resolve({ applied_revision: committed.revision, changed: true, composer: committed }));
  expect(requests("group.message_enqueue_draft")).toHaveLength(0);
  expect(requests("group.composer_update")).toHaveLength(1);
});
it("cancels a queued send on group switch without publishing into the newly selected composer", async () => {
  const other = { ...group, id: "other-group", core_handle: "f".repeat(64), title: "Other team" };
  const otherHost = new GroupComposerHostFixture(profileHandle, other.core_handle);
  current = { ...current, groups: [group, other] };
  const reply = deferred<unknown>(); const original = host.invoke.getMockImplementation()!;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && groupComposerCapabilities.operations.includes(args.operation) && args.params.group === other.core_handle) return otherHost.request(args.operation, args.params, args.idempotencyKey);
    if (command === "core_api_request" && args.operation === "group.composer_update") { await original(command, args); return reply.promise; }
    return original(command, args);
  });
  const { field } = await open(); await typeAndSend(field, "Old group only");
  await waitFor(() => expect(requests("group.composer_update")).toHaveLength(1));
  const committed = fixture.snapshot(); fireEvent.click(screen.getByText(other.title));
  const next = await screen.findByRole("textbox", { name: `Message ${other.title}` });
  await waitFor(() => expect(next).toHaveProperty("readOnly", false));
  await act(async () => reply.resolve({ applied_revision: committed.revision, changed: true, composer: committed }));
  expect(requests("group.message_enqueue_draft")).toHaveLength(0);
  expect(next).toHaveProperty("value", ""); expect(screen.queryByRole("textbox", { name: "Saved group message text" })).toBeNull();
});
it("does not publish or refresh a late already-admitted acceptance after posting revocation", async () => {
  const reply = deferred<void>(); fixture.onEnqueue = () => reply.promise;
  const { field } = await open(); await typeAndSend(field, "Already admitted");
  await waitFor(() => expect(fixture.messageCount).toBe(1));
  current = { ...current, groups: [{ ...group, status: "removed" }] };
  await act(async () => window.dispatchEvent(new Event("focus")));
  await screen.findAllByText("You are no longer an active member of this group.");
  const reads = requests("application.snapshot").length;
  await act(async () => reply.resolve());
  expect(requests("application.snapshot")).toHaveLength(reads);
  expect(screen.queryByRole("textbox", { name: "Saved group message text" })).toBeNull();
  expect(requests("group.message_enqueue_draft")).toHaveLength(1);
});
it("does not flush uncommitted local text after posting revocation", async () => {
  const { field } = await open(); fireEvent.change(field, { target: { value: "Uncommitted revoked draft" } });
  current = { ...current, groups: [{ ...group, status: "removed" }] };
  await act(async () => window.dispatchEvent(new Event("focus")));
  await screen.findAllByText("You are no longer an active member of this group.");
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  expect(requests("group.composer_update")).toHaveLength(0); expect(requests("group.message_enqueue_draft")).toHaveLength(0);
});
it("flushes a permitted navigation draft to its original group without sending it", async () => {
  const other = { ...group, id: "other-group", core_handle: "f".repeat(64), title: "Other team" };
  const otherHost = new GroupComposerHostFixture(profileHandle, other.core_handle);
  current = { ...current, groups: [group, other] }; const original = host.invoke.getMockImplementation()!;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && groupComposerCapabilities.operations.includes(args.operation) && args.params.group === other.core_handle) return otherHost.request(args.operation, args.params, args.idempotencyKey);
    return original(command, args);
  });
  const { field } = await open(); fireEvent.change(field, { target: { value: "Original group draft" } });
  fireEvent.click(screen.getByText(other.title));
  const next = await screen.findByRole("textbox", { name: `Message ${other.title}` });
  await waitFor(() => expect(fixture.snapshot().text).toBe("Original group draft"));
  expect(requests("group.composer_update")).toHaveLength(1);
  expect(requests("group.composer_update")[0].params.group).toBe(groupHandle);
  expect(next).toHaveProperty("value", ""); expect(requests("group.message_enqueue_draft")).toHaveLength(0);
});
