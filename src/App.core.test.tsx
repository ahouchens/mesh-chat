import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Snapshot, Workspace, WorkspaceChannel, WorkspaceMessage } from "./types";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => undefined) }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  getCurrent: vi.fn(async () => []), onOpenUrl: vi.fn(async () => () => undefined),
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
let current: Snapshot;
let snapshotsFail: boolean;
let send: (params: Record<string, unknown>) => Promise<unknown>;
let mutation: (params: Record<string, unknown>) => Promise<unknown>;
let createProfile: (params: Record<string, unknown>) => Promise<unknown>;

const requests = (operation: string) => host.invoke.mock.calls
  .filter(([command, payload]) => command === "core_api_request" && payload.operation === operation)
  .map(([, payload]) => payload as { operation: string; params: Record<string, unknown>; idempotencyKey: string | null });
const sends = () => host.invoke.mock.calls.filter(([command]) => command === "core_api_send_message").map(([, params]) => params);

beforeEach(() => {
  snapshotsFail = false;
  current = {
    profile, contacts: [contact], messages: [], drafts: [], service_error: null,
    settings: { nearby_discovery: true, lan_fallback: true, lan_listener_port: null, allowed_interfaces: [], tcp_clients: [], tcp_listener: null,
      help_route: false, store_for_offline: false, approved_propagation_nodes: [], i2p_enabled: false, i2p_connectable: false, i2p_managed: true, i2p_peers: [] },
    network: { transport_enabled: false, propagation_enabled: false, interface_available: true, interfaces: [], outbound_propagation_node: null },
  };
  send = async () => ({ message: "d".repeat(40), accepted: true });
  createProfile = async () => {
    current = { ...current, profile };
    return { display_name: profile.display_name };
  };
  mutation = async (params) => ({ ...root, id: params.event_id, direction: "outbound", text: params.text, reply_count: 0 });
  host.invoke.mockImplementation(async (command: string, payload: Record<string, unknown> = {}) => {
    if (command === "initialize_service") return current;
    if (command === "runtime_platform") return "desktop";
    if (command === "core_api_profile") {
      if (!current.profile) throw JSON.stringify({ code: "locked", retry_after_ms: null });
      return { profile: profileHandle, ...profile, destination: profile.destination_hash, connections: [], peers: [] };
    }
    if (command === "core_api_draft_get") return { text: "" };
    if (command === "core_api_draft_set") return {};
    if (command === "core_api_send_message") return send(payload);
    if (command === "set_native_theme") return;
    if (command === "core_api_request") {
      const params = payload.params as Record<string, unknown>;
      if (payload.operation === "application.snapshot") {
        if (snapshotsFail) throw JSON.stringify({ code: "unavailable", retry_after_ms: 100 });
        return current;
      }
      if (payload.operation === "profile.create") return createProfile(params);
      if (payload.operation === "workspace.timeline_query") {
        if (params.view === "thread_messages") return { result: {
          root, replies: [], next_cursor: null, high_water: 1, unread_count: 1,
          conversation: { id: channel.id, kind: "channel", name: "general", visibility: "public", state: "active" },
        } };
        return { result: { messages: [root], next_cursor: null, high_water: 1 } };
      }
      if (payload.operation === "workspace.timeline_mutation") return { result: await mutation(params) };
      if (payload.operation === "native.command") return { profiles: [], sessions: [] };
      if (payload.operation === "call.settings_query") return { settings: {} };
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
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("textbox", { name: "Message Taylor" });
    expect(requests("profile.create")).toHaveLength(1);
    expect(requests("application.snapshot")).toHaveLength(1);
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
    fireEvent.change(name, { target: { value: "Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    snapshotsFail = true;
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    expect(requests("profile.create")).toHaveLength(1);
    expect(requests("application.snapshot")).toHaveLength(1);
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

  it("keeps a pre-profile invitation without creating or accepting when scoped preview is unavailable", async () => {
    current = { ...current, profile: null };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Join a chat" }));
    const invitation = screen.getByRole("textbox", { name: "Invitation" });
    fireEvent.change(invitation, { target: { value: "MESHCHAT2:pending-consent" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("alert");
    expect((invitation as HTMLTextAreaElement).value).toBe("MESHCHAT2:pending-consent");
    expect(requests("profile.create")).toHaveLength(0);
    expect(requests("peer.pairing_accept")).toHaveLength(0);
    expect(host.invoke.mock.calls.filter(([command]) => command === "initialize_service")).toHaveLength(1);
    expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
  });

  it("reuses the exact pending send after Core commits but its reply is lost", async () => {
    const durable = new Map<string, unknown>();
    send = async (params) => {
      if (!durable.has(String(params.idempotencyKey))) {
        durable.set(String(params.idempotencyKey), { message: "d".repeat(40), accepted: true });
        throw JSON.stringify({ code: "unavailable", retry_after_ms: 100 });
      }
      return durable.get(String(params.idempotencyKey));
    };
    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: "Retry this exact send" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Retrying unchanged text");
    expect((composer as HTMLTextAreaElement).value).toBe("Retry this exact send");
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(sends()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[1]).toEqual(sends()[0]);
    expect(durable.size).toBe(1);
    await waitFor(() => expect((composer as HTMLTextAreaElement).value).toBe(""));
    expect((await screen.findByRole("alert")).textContent).toContain("Saved text: Retry this exact send");
    expect(host.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
    expect(requests("native.command").some(({ params }) => params.command === "send_message")).toBe(false);
  });

  it("keeps an accepted send out of the composer when snapshot refresh fails", async () => {
    send = async () => { snapshotsFail = true; return { message: "d".repeat(40), accepted: true }; };
    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    fireEvent.change(composer, { target: { value: "Already accepted" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    const notice = (await screen.findByRole("alert")).textContent;
    expect(notice).toContain("Your message was saved");
    expect(notice).toContain("Saved text: Already accepted");
    expect((composer as HTMLTextAreaElement).value).toBe("");
    fireEvent.submit(composer.closest("form")!);
    expect(sends()).toHaveLength(1);
    expect(host.invoke).toHaveBeenCalledWith("core_api_draft_set", { destination: contact.destination_hash, text: "" });
  });

  it("gives changed text a separate operation while retaining the uncertain original", async () => {
    send = async () => { throw JSON.stringify({ code: "unavailable", retry_after_ms: null }); };
    render(<App />);
    const composer = await screen.findByRole("textbox", { name: "Message Taylor" });
    for (const text of ["Original", "Edited", "Original"]) {
      fireEvent.change(composer, { target: { value: text } });
      fireEvent.click(screen.getByRole("button", { name: "Send message" }));
      await screen.findByRole("alert");
    }
    expect(sends()).toHaveLength(3);
    expect(sends()[1].idempotencyKey).not.toBe(sends()[0].idempotencyKey);
    expect(sends()[2]).toEqual(sends()[0]);
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
