import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Snapshot, Workspace, WorkspaceChannel, WorkspaceMessage } from "./types";
import { ComposerHostFixture, composerCapabilities } from "./test/composer-host";

const host = vi.hoisted(() => ({ invoke: vi.fn(), openUrls: [] as Array<(urls: string[]) => void>,
  events: [] as Array<{ name: string; callback: (event: { payload: unknown }) => void }> }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (name, callback) => {
  host.events.push({ name, callback });
  return () => undefined;
}) }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  getCurrent: vi.fn(async () => []), onOpenUrl: vi.fn(async (callback) => {
    host.openUrls.push(callback);
    return () => undefined;
  }),
}));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));

// App and api.ts stay real. Substitute only the serialized native host boundary.
import App from "./App";

const profile = {
  display_name: "Alex", public_identity: "alex", identity_hash: "11".repeat(16),
  destination_hash: "22".repeat(16), fingerprint: "AAAA BBBB", created_at: 1,
};
const contact = {
  id: "contact-taylor", display_name: "Taylor", public_identity: "taylor",
  identity_hash: "33".repeat(16), destination_hash: "44".repeat(16),
  fingerprint: "CCCC DDDD", trust: "approved" as const, connection_hints: [], created_at: 2, updated_at: 2,
};
const workspace: Workspace = {
  id: "11111111-1111-4111-8111-111111111111", core_handle: "a".repeat(40),
  name: "Lakewatcher", description: "Field coordination", state: "active", local_role: "owner",
  local_member_id: "22222222-2222-4222-8222-222222222222", local_device_id: "33333333-3333-4333-8333-333333333333",
  owner_member_id: "22222222-2222-4222-8222-222222222222", authority_device_id: "33333333-3333-4333-8333-333333333333",
  epoch: 1, manifest_hash: "66".repeat(32), genesis_digest: "77".repeat(32),
  general_channel_id: "44444444-4444-4444-8444-444444444444", channel_discovery: "converged", retention_days: 90,
  policies: { channel_creation: "all_members", posting: "all_members", invitation_requests: "owner_only" },
  members: [{
    id: "22222222-2222-4222-8222-222222222222", display_name: "Alex", role: "owner", status: "active", short_id: "222222",
    device: { id: "33333333-3333-4333-8333-333333333333", destination_hash: profile.destination_hash, fingerprint: profile.fingerprint },
  }],
  authorization_generation: 1, retention_generation: 1, mention_unread_count: 0, thread_unread_count: 0,
  created_at: 4, updated_at: 4,
};
const channel: WorkspaceChannel = {
  id: workspace.general_channel_id!, core_handle: "b".repeat(40), workspace_id: workspace.id,
  name: "general", name_key: "general", display_name: "general", short_id: "444444", topic: "", visibility: "public",
  member_ids: [], state: "active", manager_member_id: workspace.local_member_id, manager_device_id: workspace.local_device_id,
  version: 1, head_hash: "88".repeat(32), manifest_digest: workspace.manifest_hash,
  unread_count: 0, subscribed: true, mentions_muted: false, is_general: true, duplicate_name: false, created_at: 4, updated_at: 4,
};
const root: WorkspaceMessage = {
  id: "55555555-5555-4555-8555-555555555555", workspace_id: workspace.id, conversation_id: channel.id,
  direction: "inbound", author_member_id: workspace.local_member_id, author_display_name: "Alex",
  text: "Inspect the relay", reply_count: 1, thread_unread_count: 1,
  sequence: 1, event_digest: "88".repeat(32), created_at: 100,
};
const profileHandle = "c".repeat(40);
const personalPreview = {
  display_name: "Taylor", identity_hash: contact.identity_hash, destination_hash: contact.destination_hash,
  fingerprint: contact.fingerprint, hints: [], expires_at: 2_000_000_000,
};
let current: Snapshot;
let snapshotsFail: boolean;
let directComposer: ComposerHostFixture;
let mutation: (params: Record<string, unknown>) => Promise<unknown>;
let createProfile: (params: Record<string, unknown>) => Promise<unknown>;
let bootstrapPreview: (params: Record<string, unknown>) => Promise<unknown>;

const requests = (operation: string) => host.invoke.mock.calls
  .filter(([command, payload]) => command === "core_api_request" && payload.operation === operation)
  .map(([, payload]) => payload as { operation: string; params: Record<string, unknown>; idempotencyKey: string | null });
const sends = () => requests("message.enqueue_draft");

beforeEach(() => {
  host.openUrls.length = 0;
  host.events.length = 0;
  snapshotsFail = false;
  current = {
    profile, contacts: [contact], messages: [], drafts: [], service_error: null,
    settings: { nearby_discovery: true, lan_fallback: true, lan_listener_port: null, allowed_interfaces: [], tcp_clients: [], tcp_listener: null,
      help_route: false, store_for_offline: false, approved_propagation_nodes: [], i2p_enabled: false, i2p_connectable: false, i2p_managed: true, i2p_peers: [] },
    network: { transport_enabled: false, propagation_enabled: false, interface_available: true, interfaces: [], outbound_propagation_node: null },
  };
  directComposer = new ComposerHostFixture(profileHandle, "e".repeat(40));
  createProfile = async () => {
    current = { ...current, profile };
    return { display_name: profile.display_name };
  };
  bootstrapPreview = async () => { throw JSON.stringify({ code: "unsupported_operation", retry_after_ms: null }); };
  mutation = async (params) => ({ ...root, id: params.event_id, direction: "outbound", text: params.text, reply_count: 0 });
  host.invoke.mockImplementation(async (command: string, payload: Record<string, unknown> = {}) => {
    if (command === "initialize_service") return current;
    if (command === "lock_service") return;
    if (command === "runtime_platform") return "desktop";
    if (command === "core_api_capabilities") return composerCapabilities;
    if (command === "core_api_peer_for_destination") return { profile: profileHandle, peer: "e".repeat(40), destination: contact.destination_hash };
    if (command === "core_api_profile") {
      if (!current.profile) throw JSON.stringify({ code: "locked", retry_after_ms: null });
      return { profile: profileHandle, ...profile, destination: profile.destination_hash, connections: [], peers: [] };
    }
    if (command === "core_api_draft_get") return { text: "" };
    if (command === "core_api_draft_set") return {};
    if (command === "core_api_send_message") throw new Error("Legacy direct enqueue must not be used");
    if (command === "set_native_theme") return;
    if (command === "core_api_request") {
      const params = payload.params as Record<string, unknown>;
      if (payload.operation === "application.snapshot") {
        if (snapshotsFail) throw JSON.stringify({ code: "unavailable", retry_after_ms: 100 });
        return current;
      }
      if (payload.operation === "profile.create") return createProfile(params);
      if (["peer.composer_query", "peer.composer_update", "message.enqueue_draft"].includes(String(payload.operation))) {
        return directComposer.request(String(payload.operation), params, payload.idempotencyKey as string | undefined);
      }
      if (payload.operation === "bootstrap.preview") return bootstrapPreview(params);
      if (payload.operation === "peer.pairing_accept") return { profile: profileHandle, peer: "d".repeat(40), trust: "awaiting_consent" };
      if (payload.operation === "workspace.timeline_query") {
        if (params.view === "thread_messages") return { result: {
          root, replies: [], next_cursor: null, high_water: 1, unread_count: 1,
          conversation: { id: channel.id, kind: "channel", name: "general", visibility: "public", state: "active" },
        } };
        return { result: { messages: [root], next_cursor: null, high_water: 1 } };
      }
      if (payload.operation === "workspace.timeline_mutation") return { result: await mutation(params) };
      if (payload.operation === "workspace.draft_set") return {};
      if (payload.operation === "native.command") return { profiles: [], sessions: [] };
      if (payload.operation === "call.settings_query") return { settings: {} };
      if (payload.operation === "remote_profile.query") return { profiles: current.remote_profiles ?? [] };
      if (payload.operation === "remote_profile.mutate") return { result: {} };
      if (payload.operation === "workspace.history") return { result: { status: "complete", eligible: false } };
      throw new Error(`Unexpected Core operation: ${String(payload.operation)}`);
    }
    throw new Error(`Unexpected native command: ${command}`);
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("Core application serialization", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((finish) => { resolve = finish; });
    return { promise, resolve };
  }

  const nativeLocks = () => host.invoke.mock.calls.filter(([command]) => command === "lock_service");

  it("does not save settings when the profile lookup finishes after lock and reopen", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const settings = await screen.findByRole("region", { name: "Settings" });
    fireEvent.click(within(settings).getByRole("button", { name: "Connections" }));
    const profileReply = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    let delaying = true;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_profile" && delaying
      ? profileReply.promise : original(command, payload));
    fireEvent.click(within(settings).getByRole("checkbox", { name: /Find nearby people/ }));
    const before = host.invoke.mock.calls.filter(([command]) => command === "core_api_profile").length;
    fireEvent.click(within(settings).getByRole("button", { name: "Save connection settings" }));
    await waitFor(() => expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_profile").length).toBeGreaterThan(before));
    // Exercise global retirement while Settings owns the foreground surface.
    fireEvent.click(screen.getByLabelText("Lock Mesh Chat"));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    delaying = false;
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => profileReply.resolve({ profile: profileHandle }));
    expect(requests("settings.update")).toHaveLength(0);
  });

  it("does not verify a contact when its peer lookup finishes after lock and reopen", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Contacts" }));
    const dialog = await screen.findByRole("dialog", { name: "Contacts" });
    const peerReply = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    let delaying = true;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_peer_for_destination" && delaying
      ? peerReply.promise : original(command, payload));
    const before = host.invoke.mock.calls.filter(([command]) => command === "core_api_peer_for_destination").length;
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark verified" }));
    await waitFor(() => expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_peer_for_destination").length).toBeGreaterThan(before));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    delaying = false;
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => peerReply.resolve({ profile: profileHandle, peer: "e".repeat(40), destination: contact.destination_hash }));
    expect(requests("peer.update")).toHaveLength(0);
  });

  async function openWorkspaceComposer() {
    current = { ...current, workspaces: [workspace], workspace_channels: [channel] };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    return within(conversation).getByRole("textbox", { name: "Message general" });
  }

  it("does not send after a canceled pending draft tail settles beyond lock and reopen", async () => {
    const composer = await openWorkspaceComposer();
    const old = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "workspace.draft_set" ? old.promise : original(command, payload));
    fireEvent.change(composer, { target: { value: "Original queued draft" } });
    await waitFor(() => expect(requests("workspace.draft_set")).toHaveLength(1));
    fireEvent.change(composer, { target: { value: "Do not send after lock" } });
    fireEvent.click(screen.getByRole("button", { name: "Send workspace message" }));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" }, { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => old.resolve({}));
    expect(requests("workspace.timeline_mutation").filter(({ params }) => params.action === "channel_message")).toHaveLength(0);
    expect(requests("workspace.draft_set")).toHaveLength(1);
  });

  it("does not invoke an old queued draft after the retirement deadline and reopening", async () => {
    const composer = await openWorkspaceComposer();
    const old = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "workspace.draft_set" ? old.promise : original(command, payload));
    fireEvent.change(composer, { target: { value: "First draft" } });
    await waitFor(() => expect(requests("workspace.draft_set")).toHaveLength(1));
    fireEvent.change(composer, { target: { value: "Later queued draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" }, { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => old.resolve({}));
    expect(requests("workspace.draft_set").map(({ params }) => params.text)).toEqual(["First draft"]);
  });

  it("does not mark a conversation read when its query completes after lock and reopen", async () => {
    current = { ...current, workspaces: [workspace], workspace_channels: [{ ...channel, unread_count: 2 }] };
    const page = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "workspace.timeline_query" ? page.promise : original(command, payload));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    await waitFor(() => expect(requests("workspace.timeline_query")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => page.resolve({ result: { messages: [root], next_cursor: null, high_water: 7 } }));
    expect(requests("workspace.timeline_mutation").filter(({ params }) => params.action === "workspace_read")).toHaveLength(0);
  });

  it("ignores an old snapshot and its queued trailing refresh after lock and unlock", async () => {
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const stale = deferred<Snapshot>();
    const original = host.invoke.getMockImplementation()!;
    let delay = true;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "application.snapshot" && delay ? stale.promise : original(command, payload));
    const count = requests("application.snapshot").length;
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(requests("application.snapshot")).toHaveLength(count + 1));
    // The service event queues a trailing snapshot behind the stalled one.
    act(() => host.events.filter(({ name }) => name === "mesh-chat://service-event")
      .forEach(({ callback }) => callback({ payload: { event: "profile_changed" } })));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    expect(screen.queryByRole("textbox", { name: "Message Taylor" })).toBeNull();
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    delay = false;
    current = { ...current, profile: { ...profile, display_name: "Blair", destination_hash: "99".repeat(16) },
      contacts: [{ ...contact, display_name: "Morgan" }] };
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Morgan" });
    const snapshots = requests("application.snapshot").length;
    await act(async () => stale.resolve({ ...current, profile, contacts: [contact] }));
    expect(screen.queryByRole("textbox", { name: "Message Taylor" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message Morgan" })).toBeTruthy();
    expect(requests("application.snapshot")).toHaveLength(snapshots);
  });

  it("flushes one exact draft update before native lock and never saves again on unmount", async () => {
    const composer = await composeDirect("Final unsaved draft");
    const saved = deferred<unknown>();
    const original = directComposer.request.bind(directComposer);
    vi.spyOn(directComposer, "request").mockImplementation(async (...args) => {
      const result = await original(...args);
      return args[0] === "peer.composer_update" ? saved.promise.then(() => result) : result;
    });
    const key = directComposer.snapshot().update_key;
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    expect(composer.isConnected).toBe(false);
    await waitFor(() => expect(requests("peer.composer_update")).toHaveLength(1));
    expect(nativeLocks()).toHaveLength(0);
    expect(requests("peer.composer_update")[0]).toEqual({ operation: "peer.composer_update", params: {
      profile: profileHandle, peer: "e".repeat(40), expected_revision: null, text: "Final unsaved draft",
    }, idempotencyKey: key });
    await act(async () => saved.resolve(undefined));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    expect(nativeLocks()).toHaveLength(1);
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(requests("peer.composer_update")).toHaveLength(1);
    expect(sends()).toHaveLength(0);
  });

  it("locks despite a never resolving draft reply and blocks late enqueue after reopening", async () => {
    await composeDirect("Pending save before send");
    const reply = deferred<unknown>();
    const original = directComposer.request.bind(directComposer);
    vi.spyOn(directComposer, "request").mockImplementation(async (...args) => {
      const result = await original(...args);
      return args[0] === "peer.composer_update" ? reply.promise.then(() => result) : result;
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(requests("peer.composer_update")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    expect(screen.queryByRole("textbox", { name: "Message Taylor" })).toBeNull();
    await screen.findByRole("heading", { name: "Mesh Chat is locked" }, { timeout: 2000 });
    expect(nativeLocks()).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toContain("did not finish");
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => reply.resolve(undefined));
    expect(sends()).toHaveLength(0);
    expect(requests("peer.composer_update")).toHaveLength(1);
  });

  it.each([
    new Error("service_write_failed"),
    JSON.stringify({ code: "unavailable", outcome: "unknown", retry_after_ms: null }),
  ])("keeps profile content hidden and offers retry when native lock rejects with %s", async (failure) => {
    render(<App />);
    await screen.findByRole("button", { name: "Lock Mesh Chat" });
    const original = host.invoke.getMockImplementation()!;
    // Lock is asynchronous behind the retirement barrier.
    host.invoke.mockImplementation(async (command, payload) => {
      if (command === "lock_service") throw failure;
      return original(command, payload);
    });
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Lock not confirmed" });
    expect(screen.queryByText("The messaging service is stopped and its keys have been released.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Unlock" })).toBeNull();
    host.invoke.mockImplementation(original);
    fireEvent.click(screen.getByRole("button", { name: "Retry lock" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    expect(nativeLocks()).toHaveLength(2);
  });

  it("ignores a prior lifetime's workspace snapshot after reopening the same profile", async () => {
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const stale = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "workspace.snapshot" ? stale.promise : original(command, payload));
    act(() => host.events.filter(({ name }) => name === "mesh-chat://service-event")
      .forEach(({ callback }) => callback({ payload: { event: "workspace_changed", workspace_id: workspace.id } })));
    await waitFor(() => expect(requests("workspace.snapshot")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => stale.resolve({ workspaces: [workspace], workspace_channels: [channel] }));
    expect(screen.queryByText("Lakewatcher")).toBeNull();
  });

  it("does not publish or refresh for an old notification result after bounded lock and reopen", async () => {
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const stale = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_request"
      && payload.operation === "runtime.mutate" ? stale.promise : original(command, payload));
    act(() => host.openUrls.forEach((accept) => accept([`meshchat://notification/${"a".repeat(64)}`])));
    await waitFor(() => expect(requests("runtime.mutate")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    expect(nativeLocks()).toHaveLength(0);
    await screen.findByRole("heading", { name: "Mesh Chat is locked" }, { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const count = requests("application.snapshot").length;
    await act(async () => stale.resolve({ result: { available: false, message: "Old profile notification" } }));
    expect(screen.queryByText("Old profile notification")).toBeNull();
    expect(requests("application.snapshot")).toHaveLength(count);
    expect(requests("runtime.mutate")).toHaveLength(1);
  });

  it("does not admit a notification mutation when its profile lookup finishes after lock and reopen", async () => {
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const stale = deferred<unknown>();
    const original = host.invoke.getMockImplementation()!;
    let delaying = true;
    host.invoke.mockImplementation(async (command, payload) => command === "core_api_profile" && delaying
      ? stale.promise : original(command, payload));
    const before = host.invoke.mock.calls.filter(([command]) => command === "core_api_profile").length;
    act(() => host.openUrls.forEach((accept) => accept([`meshchat://notification/${"b".repeat(64)}`])));
    await waitFor(() => expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_profile")).toHaveLength(before + 1));
    fireEvent.click(screen.getByRole("button", { name: "Lock Mesh Chat" }));
    await screen.findByRole("heading", { name: "Mesh Chat is locked" });
    delaying = false;
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await act(async () => stale.resolve({ profile: profileHandle }));
    expect(requests("runtime.mutate")).toHaveLength(0);
  });

  it("uses a keyed Core mutation for explicit remote propagation approval", async () => {
    current = { ...current, remote_profiles: [{
      id: "remote-access-id", label: "Field access", origin: "manual", expires_at: 2_000_000_000,
      endpoint_count: 1, connected_endpoint_count: 1, state: "connected", path_available: true,
      ratchet_ready: true, offline_delivery_recommended: true, offline_delivery_approved: false,
      offline_delivery_available: false, propagation_identifier: "11".repeat(16), scope_count: 1,
      retry_count: 0, last_error: null, last_connected_at: 1, capabilities: [], allow_private: false,
    }] };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const settings = await screen.findByRole("region", { name: "Settings" });
    fireEvent.click(within(settings).getByRole("button", { name: "Connections" }));
    expect(requests("remote_profile.mutate")).toHaveLength(0);
    fireEvent.click(within(settings).getByRole("button", { name: "Approve offline delivery" }));
    await waitFor(() => expect(requests("remote_profile.mutate")).toHaveLength(1));
    expect(requests("remote_profile.mutate")[0]).toEqual({ operation: "remote_profile.mutate", params: {
      profile: profileHandle, action: "approve_propagation", remote_profile_id: "remote-access-id",
    }, idempotencyKey: expect.any(String) });
    expect(requests("native.command").some(({ params }) => params.command === "approve_remote_propagation")).toBe(false);
  });

  async function openProfileSetup() {
    current = { ...current, profile: null };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Start a chat" }));
    return screen.getByRole("textbox", { name: "Display name" });
  }

  it("reuses the serialized key for unchanged first-run creation after an uncertain response", async () => {
    let attempts = 0;
    createProfile = async () => {
      if (++attempts === 1) throw JSON.stringify({ code: "unavailable", retry_after_ms: null });
      current = { ...current, profile };
      return { display_name: "Alex" };
    };
    const name = await openProfileSetup();
    fireEvent.change(name, { target: { value: "  Alex  " } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    fireEvent.submit(name.closest("form")!);
    await screen.findByRole("alert");
    expect(requests("profile.create")).toHaveLength(1);
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    const creates = requests("profile.create");
    expect(creates).toHaveLength(2);
    expect(creates[0]).toEqual({ operation: "profile.create", params: { display_name: "Alex" }, idempotencyKey: expect.any(String) });
    expect(creates[1]).toEqual(creates[0]);
    expect(host.invoke).toHaveBeenCalledWith("initialize_service", { displayName: null });
    expect(host.invoke.mock.calls.filter(([command]) => command === "initialize_service")).toHaveLength(1);
  });

  it("keeps each proposed name bound to its own key without changing an earlier payload", async () => {
    createProfile = async () => { throw JSON.stringify({ code: "unavailable", retry_after_ms: null }); };
    const name = await openProfileSetup();
    for (const text of ["Alex", "Blair", "Alex"]) {
      fireEvent.change(name, { target: { value: text } });
      fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
      await screen.findByRole("alert");
    }
    const creates = requests("profile.create");
    expect(creates).toHaveLength(3);
    expect(creates[1].idempotencyKey).not.toBe(creates[0].idempotencyKey);
    expect(creates[2]).toEqual(creates[0]);
  });

  it("loads a profile after its accepted creation reply was lost without another create", async () => {
    createProfile = async () => {
      current = { ...current, profile };
      throw JSON.stringify({ code: "unavailable", retry_after_ms: null });
    };
    const name = await openProfileSetup();
    const snapshotsBeforeCreate = requests("application.snapshot").length;
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    expect(requests("profile.create")).toHaveLength(1);
    expect(requests("application.snapshot")).toHaveLength(snapshotsBeforeCreate + 1);
  });

  it("does not recreate a confirmed profile when the following snapshot failed", async () => {
    createProfile = async () => {
      current = { ...current, profile };
      snapshotsFail = true;
      return { display_name: "Alex" };
    };
    const name = await openProfileSetup();
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Your profile was created");
    snapshotsFail = false;
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    expect(requests("profile.create")).toHaveLength(1);
  });

  it("opens the existing profile after a lost reply and renderer remount without another creation", async () => {
    createProfile = async () => {
      current = { ...current, profile };
      throw JSON.stringify({ code: "unavailable", retry_after_ms: null });
    };
    const name = await openProfileSetup();
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    cleanup();
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    expect(requests("profile.create")).toHaveLength(1);
  });

  it("waits for outcome reconciliation when a retry snapshot is unavailable", async () => {
    createProfile = async () => { throw JSON.stringify({ code: "unavailable", retry_after_ms: null }); };
    const name = await openProfileSetup();
    const snapshotsBeforeCreate = requests("application.snapshot").length;
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    snapshotsFail = true;
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    expect(requests("profile.create")).toHaveLength(1);
    expect(requests("application.snapshot")).toHaveLength(snapshotsBeforeCreate + 1);
  });

  it("does not create under an edited name if the earlier uncertain creation succeeded", async () => {
    createProfile = async () => {
      current = { ...current, profile };
      throw JSON.stringify({ code: "unavailable", retry_after_ms: null });
    };
    const name = await openProfileSetup();
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    fireEvent.change(name, { target: { value: "Blair" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already has a profile named Alex");
    expect(requests("profile.create")).toHaveLength(1);
    expect((name as HTMLInputElement).value).toBe("Blair");
  });

  it.each([
    "MESHCHAT2:pending-consent",
    "MESHWORKSPACE4:pending-consent",
    "MESHWORKSPACEDEVICE1:pending-consent",
  ])("keeps pre-profile %s without effects when bootstrap verification is unavailable", async (document) => {
    current = { ...current, profile: null };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Join a chat" }));
    const invitation = screen.getByRole("textbox", { name: "Invitation" });
    fireEvent.change(invitation, { target: { value: document } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("alert");
    expect((invitation as HTMLTextAreaElement).value).toBe(document);
    const kind = document.startsWith("MESHWORKSPACEDEVICE") ? "device_link" : document.startsWith("MESHWORKSPACE") ? "workspace" : "personal";
    expect(requests("bootstrap.preview")).toEqual([{ operation: "bootstrap.preview", params: { kind, document }, idempotencyKey: null }]);
    expect(host.invoke.mock.calls.some(([command]) => command === "core_api_profile")).toBe(false);
    expect(requests("profile.create")).toHaveLength(0);
    expect(requests("peer.pairing_accept")).toHaveLength(0);
    expect(requests("workspace.join")).toHaveLength(0);
    expect(requests("workspace.device_link_submit")).toHaveLength(0);
    expect(host.invoke.mock.calls.filter(([command]) => command === "initialize_service")).toHaveLength(1);
    expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
  });

  it.each([
    ["MESHCHAT2:verified-document", "personal", "Connect to Taylor"],
    ["MESHWORKSPACE4:verified-document", "workspace", "Set up this device for Lakewatcher"],
    ["MESHWORKSPACEDEVICE1:verified-document", "device_link", "Set up this device for Lakewatcher"],
  ] as const)("reviews pre-profile %s through the exact trusted verification envelope", async (document, kind, heading) => {
    current = { ...current, profile: null };
    bootstrapPreview = async () => ({ kind, preview: kind === "personal" ? personalPreview
      : kind === "workspace" ? { name: "Lakewatcher", description: "Field coordination", owner_fingerprint: "AAAA BBBB", member_count: 1, retention_days: 90, expires_at: 2_000_000_000 }
        : { name: "Lakewatcher", member_display_name: "Alex", sponsor_fingerprint: "AAAA BBBB", device_count: 1, expires_at: 2_000_000_000 } });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Join a chat" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Invitation" }), { target: { value: document } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: heading });
    expect(requests("bootstrap.preview")).toEqual([{ operation: "bootstrap.preview", params: { kind, document }, idempotencyKey: null }]);
    expect(requests("profile.create")).toHaveLength(0);
    expect(requests("peer.pairing_accept")).toHaveLength(0);
    expect(requests("workspace.join")).toHaveLength(0);
    expect(requests("workspace.device_link_submit")).toHaveLength(0);
    expect(host.invoke.mock.calls.some(([command]) => command === "core_api_profile")).toBe(false);
    expect(requests("peer.pairing_preview")).toHaveLength(0);
    expect(requests("workspace.invitation_preview")).toHaveLength(0);
    expect(requests("workspace.connection")).toHaveLength(0);
  });

  it("requires both verified remote and I2P consent before creation or personal acceptance", async () => {
    const document = "MESHI2P1:verified-remote-document";
    current = { ...current, profile: null };
    bootstrapPreview = async () => ({ kind: "personal", preview: {
      ...personalPreview, requires_network_consent: true, requires_i2p_consent: true,
      remote_profile: { id: "remote", label: "Field relay", endpoint_count: 1, expires_at: 2_000_000_000,
        capabilities: ["reticulum_tcp"], private_endpoint_warning: false, propagation_identifier: null,
        privacy_disclosure: "The operator can observe connection metadata." },
      i2p_access_point: { b32: "a".repeat(52) + ".b32.i2p", label: "Approved relay", relay: "i2p" },
    } });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Join a chat" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Invitation" }), { target: { value: document } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const submit = await screen.findByRole("button", { name: "Create profile and connect" });
    fireEvent.change(screen.getByRole("textbox", { name: "Your display name" }), { target: { value: "Alex" } });
    fireEvent.submit(submit.closest("form")!);
    expect(requests("profile.create")).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: /Connect to this access point/ }));
    fireEvent.submit(submit.closest("form")!);
    expect(requests("profile.create")).toHaveLength(0);
    expect(requests("peer.pairing_accept")).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: /Use this I2P access point/ }));
    fireEvent.click(submit);
    await waitFor(() => expect(requests("peer.pairing_accept")).toHaveLength(1));
    expect(requests("profile.create")[0]).toEqual({ operation: "profile.create", params: { display_name: "Alex" }, idempotencyKey: expect.any(String) });
    expect(requests("peer.pairing_accept")[0]).toEqual({ operation: "peer.pairing_accept", params: {
      profile: profileHandle, document, i2p_consent: true,
    }, idempotencyKey: null });
    const operations = host.invoke.mock.calls.filter(([command]) => command === "core_api_request").map(([, payload]) => payload.operation);
    expect(operations.indexOf("bootstrap.preview")).toBeLessThan(operations.indexOf("profile.create"));
    expect(operations.indexOf("profile.create")).toBeLessThan(operations.indexOf("peer.pairing_accept"));
  });

  it("ignores an older verification result after the invitation document changes", async () => {
    current = { ...current, profile: null };
    let finishOld!: (value: unknown) => void;
    const oldPreview = new Promise((resolve) => { finishOld = resolve; });
    bootstrapPreview = async (params) => params.document === "MESHCHAT2:older-document" ? oldPreview
      : { kind: "personal", preview: { ...personalPreview, display_name: "Blair" } };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Join a chat" }));
    const input = screen.getByRole("textbox", { name: "Invitation" });
    fireEvent.change(input, { target: { value: "MESHCHAT2:older-document" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(requests("bootstrap.preview")).toHaveLength(1));
    fireEvent.change(input, { target: { value: "MESHCHAT2:newer-document" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Connect to Blair" });
    await act(async () => finishOld({ kind: "personal", preview: personalPreview }));
    expect(screen.queryByRole("heading", { name: "Connect to Taylor" })).toBeNull();
    expect(requests("profile.create")).toHaveLength(0);
    expect(requests("peer.pairing_accept")).toHaveLength(0);
  });

  async function composeDirect(text: string) {
    render(<App />);
    await screen.findByRole("textbox", { name: "Message Taylor" });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Message Taylor" })).toHaveProperty("readOnly", false));
    const composer = screen.getByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: text } });
    return composer as HTMLTextAreaElement;
  }

  it("retries the same persisted revision after Core commits but its reply is lost", async () => {
    directComposer.loseNextSendReply = true;
    const composer = await composeDirect("Retry this exact send");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("button", { name: "Retry previous send" });
    expect(composer.value).toBe("Retry this exact send");
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(sends()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry previous send" }));
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[1]).toEqual(sends()[0]);
    expect(directComposer.messageCount).toBe(1);
    await waitFor(() => expect(composer.value).toBe(""));
    expect(screen.getByDisplayValue("Retry this exact send")).toHaveProperty("readOnly", true);
    expect(host.invoke.mock.calls.some(([command]) => command === "core_api_send_message")).toBe(false);
    expect(host.invoke.mock.calls.some(([command]) => command === "core_api_draft_set")).toBe(false);
    expect(requests("native.command").some(({ params }) => params.command === "send_message")).toBe(false);
  });

  it("keeps an accepted send out of the composer when snapshot refresh fails", async () => {
    directComposer.onEnqueue = async () => { snapshotsFail = true; };
    const composer = await composeDirect("Already accepted");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Your message was saved");
    expect(composer.value).toBe("");
    expect(screen.getByDisplayValue("Already accepted")).toHaveProperty("readOnly", true);
    fireEvent.submit(composer.closest("form")!);
    expect(sends()).toHaveLength(1);
    expect(requests("peer.composer_update")).toHaveLength(1);
    expect(host.invoke.mock.calls.some(([command]) => command === "core_api_draft_set")).toBe(false);
  });

  it("recovers a committed send and newer saved text after App remount", async () => {
    directComposer.loseNextSendReply = true;
    const composer = await composeDirect("Committed before remount");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("button", { name: "Retry previous send" });
    directComposer.replace("Newer Core draft");
    cleanup();
    render(<App />);
    await screen.findByDisplayValue("Newer Core draft");
    expect(screen.getByDisplayValue("Committed before remount")).toHaveProperty("readOnly", true);
    expect(sends()).toHaveLength(1);
    expect(directComposer.messageCount).toBe(1);
  });

  it("uses a new persisted revision for a deliberate later same-text send", async () => {
    const composer = await composeDirect("Same message text");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(composer.value).toBe(""));
    fireEvent.change(composer, { target: { value: "Same message text" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[1].idempotencyKey).not.toBe(sends()[0].idempotencyKey);
    expect(directComposer.messageCount).toBe(2);
  });

  it("serializes workspace send and read fields without legacy aliases", async () => {
    current = { ...current, workspaces: [workspace], workspace_channels: [{ ...channel, unread_count: 1 }] };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "workspace_read")).toBe(true));
    expect(requests("workspace.timeline_query")[0]).toEqual({
      operation: "workspace.timeline_query", params: { profile: profileHandle, workspace: workspace.core_handle,
        view: "channel_messages", channel: channel.id, cursor: null, limit: 50 }, idempotencyKey: null,
    });
    fireEvent.change(within(conversation).getByRole("textbox", { name: "Message general" }), { target: { value: "Core channel send" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "channel_message")).toBe(true));
    const sent = requests("workspace.timeline_mutation").find(({ params }) => params.action === "channel_message")!;
    expect(sent).toEqual({ operation: "workspace.timeline_mutation", params: {
      profile: profileHandle, workspace: workspace.core_handle, action: "channel_message", conversation: channel.id,
      text: "Core channel send", event_id: expect.any(String), mention_member_ids: [],
    }, idempotencyKey: expect.any(String) });
  });

  it("serializes thread query/read/retry with stable event and operation identities", async () => {
    current = { ...current, workspaces: [workspace], workspace_channels: [channel] };
    let attempts = 0;
    mutation = async (params) => {
      if (params.action === "thread_reply" && ++attempts === 1) throw JSON.stringify({ code: "unavailable", retry_after_ms: null });
      return { ...root, id: params.event_id ?? root.id, direction: "outbound", text: params.text ?? root.text };
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    fireEvent.click(await within(conversation).findByRole("button", { name: /Thread · 1/ }));
    const thread = await screen.findByLabelText("Thread in Lakewatcher");
    expect(requests("workspace.timeline_query").find(({ params }) => params.view === "thread_messages")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, view: "thread_messages", thread_root: root.id, cursor: null, limit: 50,
    });
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "thread_read")).toBe(true));
    expect(requests("workspace.timeline_mutation").find(({ params }) => params.action === "thread_read")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, action: "thread_read", thread_root: root.id, high_water: 1,
    });
    fireEvent.change(within(thread).getByRole("textbox", { name: "Reply in thread" }), { target: { value: "Stable reply" } });
    fireEvent.click(within(thread).getByRole("button", { name: "Send thread reply" }));
    await within(thread).findByRole("alert");
    fireEvent.click(within(thread).getByRole("button", { name: "Send thread reply" }));
    await waitFor(() => expect(requests("workspace.timeline_mutation").filter(({ params }) => params.action === "thread_reply")).toHaveLength(2));
    const replies = requests("workspace.timeline_mutation").filter(({ params }) => params.action === "thread_reply");
    expect(replies[1]).toEqual(replies[0]);
    expect(replies[0].params).toEqual({ profile: profileHandle, workspace: workspace.core_handle, action: "thread_reply",
      conversation: channel.id, thread_root: root.id, event_id: expect.any(String), text: "Stable reply" });
  });

  it("uses conversation for direct messages, reads and hides", async () => {
    const direct = {
      id: "66666666-6666-4666-8666-666666666666", workspace_id: workspace.id,
      participant_member_ids: [workspace.local_member_id], peer_member_id: "peer-member", peer_display_name: "Bailey",
      peer_short_id: "peer", peer_device_id: "peer-device", state: "open" as const,
      unread_count: 1, created_at: 1, updated_at: 1,
    };
    current = { ...current, workspaces: [workspace], workspace_channels: [channel], workspace_directs: [direct] };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: /Bailey/ }));
    const conversation = await screen.findByLabelText("Workspace direct message with Bailey");
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "direct_read")).toBe(true));
    expect(requests("workspace.timeline_query").find(({ params }) => params.view === "direct_messages")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, view: "direct_messages", conversation: direct.id, cursor: null, limit: 50,
    });
    expect(requests("workspace.timeline_mutation").find(({ params }) => params.action === "direct_read")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, action: "direct_read", conversation: direct.id, high_water: 1,
    });
    fireEvent.change(within(conversation).getByRole("textbox", { name: "Message Bailey" }), { target: { value: "Core direct send" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace direct message" }));
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "direct_message")).toBe(true));
    expect(requests("workspace.timeline_mutation").find(({ params }) => params.action === "direct_message")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, action: "direct_message", conversation: direct.id,
      text: "Core direct send", event_id: expect.any(String), mention_member_ids: [],
    });
    await waitFor(() => expect(within(conversation).getByRole("button", { name: "Send workspace direct message" })).toHaveProperty("disabled", true));
    fireEvent.click(within(conversation).getByRole("button", { name: "Hide workspace conversation with Bailey" }));
    await waitFor(() => expect(requests("workspace.history")).toHaveLength(1));
    expect(requests("workspace.history")[0]).toEqual({ operation: "workspace.history", params: {
      profile: profileHandle, workspace: workspace.core_handle, action: "hide_direct", conversation: direct.id,
    }, idempotencyKey: expect.any(String) });
  });

  it("serializes workspace-wide notification preference and history status", async () => {
    current = { ...current, workspaces: [workspace], workspace_channels: [channel] };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Lakewatcher" }));
    fireEvent.click(await screen.findByRole("button", { name: "Workspace settings" }));
    const settings = await screen.findByRole("region", { name: "Workspace settings for Lakewatcher" });
    fireEvent.change(within(settings).getByRole("combobox", { name: "For this workspace" }), { target: { value: "mentions_only" } });
    await waitFor(() => expect(requests("workspace.timeline_mutation").some(({ params }) => params.action === "notification_preference")).toBe(true));
    expect(requests("workspace.timeline_mutation").find(({ params }) => params.action === "notification_preference")?.params).toEqual({
      profile: profileHandle, workspace: workspace.core_handle, action: "notification_preference", conversation: null, mode: "mentions_only",
    });
    fireEvent.click(within(settings).getByRole("button", { name: /^History & retention/ }));
    await waitFor(() => expect(requests("workspace.history")).toHaveLength(1));
    expect(requests("workspace.history")[0]).toEqual({ operation: "workspace.history", params: {
      profile: profileHandle, workspace: workspace.core_handle, action: "status", conversation: channel.id,
    }, idempotencyKey: expect.any(String) });
  });
});
