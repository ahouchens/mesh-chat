import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FacadeHost } from "./host";

const transport = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: transport.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => undefined) }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  getCurrent: vi.fn(async () => null), onOpenUrl: vi.fn(async () => () => undefined),
}));

import App from "../../src/App";
import { coreApiProfile, coreApiTimelineQuery } from "../../src/api";

let host: FacadeHost;
let hostStarted = false;
let loseNextDraftSendReply = false;
let loseNextProfileReply = false;
let failRefreshAfterEnqueue = false;
let enqueueAccepted = false;
let beforeThreadReply: (() => Promise<void>) | null = null;
let loseNextGroupCreateReply = false;
let loseNextGroupSendReply = false;

beforeEach(async () => {
  hostStarted = false;
  loseNextDraftSendReply = false;
  loseNextProfileReply = false;
  failRefreshAfterEnqueue = false;
  enqueueAccepted = false;
  beforeThreadReply = null;
  loseNextGroupCreateReply = false;
  loseNextGroupSendReply = false;
  window.localStorage.clear();
  transport.invoke.mockReset();
  transport.invoke.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
    if (command === "runtime_platform") return "desktop";
    if (command === "set_native_theme") return;
    if (command === "notification_capability") return { supported: false, platform: "desktop", permission_state: "unsupported" };
    if (command === "core_api_request" && args.operation === "application.snapshot"
      && enqueueAccepted && failRefreshAfterEnqueue) throw new Error("fixture_snapshot_unavailable");
    if (command === "core_api_request" && args.operation === "workspace.timeline_mutation"
      && (args.params as Record<string, unknown>).action === "thread_reply") await beforeThreadReply?.();
    const result = await host.invoke(command, args);
    if (command === "core_api_request" && ((args.operation === "group.create" && loseNextGroupCreateReply)
      || (args.operation === "group.message_enqueue" && loseNextGroupSendReply))) {
      loseNextGroupCreateReply = loseNextGroupSendReply = false;
      throw new Error(JSON.stringify({ code: "unavailable", retry_after_ms: null, outcome: "unknown" }));
    }
    if (command === "core_api_request" && args.operation === "message.enqueue_draft") {
      enqueueAccepted = true;
      if (loseNextDraftSendReply) {
        loseNextDraftSendReply = false;
        throw new Error(JSON.stringify({ code: "unavailable", retry_after_ms: null, outcome: "unknown" }));
      }
    }
    if (command === "core_api_request" && args.operation === "profile.create" && loseNextProfileReply) {
      loseNextProfileReply = false;
      throw new Error(JSON.stringify({ code: "unavailable", retry_after_ms: null, outcome: "unknown" }));
    }
    return result;
  });
});

afterEach(async () => {
  cleanup();
  if (hostStarted) await host.close();
});

async function startHost(options: { freshProfile?: boolean } = {}) {
  host = new FacadeHost(options);
  hostStarted = true;
  // Establish readiness before rendering, so startup failures have useful host diagnostics.
  await host.invoke("fixture_inspect");
}

async function compose(text: string) {
  await startHost();
  render(<App />);
  const composer = await liveComposer();
  fireEvent.change(composer, { target: { value: text } });
  return composer as HTMLTextAreaElement;
}

async function liveComposer() {
  return waitFor(() => {
    const field = screen.getByRole("textbox", { name: "Message Boundary Blair" }) as HTMLTextAreaElement;
    expect(field.readOnly).toBe(false);
    expect(field.disabled).toBe(false);
    return field;
  });
}

describe("rendered UI through the production framed Core session", () => {
  async function groupDialog(title: string) {
    fireEvent.click(await screen.findByRole("button", { name: "New group" }));
    const dialog = await screen.findByRole("dialog", { name: "Create a private group" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), { target: { value: title } });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    return dialog;
  }

  it("replays lost committed group creation with the original caller key and one durable group", async () => {
    await startHost();
    const caps = await host.invoke("core_api_capabilities") as { optional_keyed_operations: string[] };
    expect(caps.optional_keyed_operations).toEqual(expect.arrayContaining(["group.create", "group.message_enqueue"]));
    render(<App />);
    let dialog = await groupDialog("Boundary keyed group");
    loseNextGroupCreateReply = true;
    fireEvent.click(within(dialog).getByRole("button", { name: "Create group" }));
    await within(dialog).findByRole("button", { name: "Retry group creation" });
    const committed = await host.invoke("fixture_inspect") as { groups: { id: string; title: string }[]; optional_receipt_count: number; group_delivery_count: number };
    expect(committed.groups.map(group => group.title)).toEqual(["Boundary keyed group"]);
    expect(committed.optional_receipt_count).toBe(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    dialog = await groupDialog("Boundary keyed group");
    fireEvent.click(within(dialog).getByRole("button", { name: "Retry group creation" }));
    await screen.findByRole("region", { name: "Group conversation Boundary keyed group" });
    expect(screen.queryByRole("textbox", { name: "Message Boundary keyed group" })).toBeNull();
    const creates = transport.invoke.mock.calls.filter(([command, args]) => command === "core_api_request" && args.operation === "group.create");
    expect(creates).toHaveLength(2);
    expect(creates[1][1]).toEqual(creates[0][1]);
    expect(creates[0][1].idempotencyKey).toEqual(expect.any(String));
    const replayed = await host.invoke("fixture_inspect");
    expect(replayed).toMatchObject({ groups: committed.groups, group_delivery_count: committed.group_delivery_count, optional_receipt_count: 1 });
  });

  it("replays lost committed group send once and preserves a newer draft through actual Core", async () => {
    await startHost();
    const profile = await coreApiProfile();
    await host.invoke("core_api_request", { operation: "group.create", params: { profile: profile.profile,
      title: "Boundary send group", posting_policy: "members", members: [profile.peers[0]] }, idempotencyKey: "boundary-group-send-setup-0001" });
    expect(await host.invoke("fixture_group_accept")).toMatchObject({ signed_acceptance_applied: true, epoch: 2 });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /^Boundary send group/ }));
    const composer = await screen.findByRole("textbox", { name: "Message Boundary send group" }) as HTMLTextAreaElement;
    fireEvent.change(composer, { target: { value: "Original group boundary message" } });
    loseNextGroupSendReply = true;
    fireEvent.click(screen.getByRole("button", { name: "Send group message" }));
    const retry = await screen.findByRole("button", { name: "Retry previous group send" });
    await waitFor(() => expect(retry).toHaveProperty("disabled", false));
    const committed = await host.invoke("fixture_inspect") as { group_messages: { id: string; text: string }[]; group_delivery_count: number };
    expect(committed.group_messages.map(message => message.text)).toEqual(["Original group boundary message"]);
    fireEvent.change(composer, { target: { value: "Newer group boundary draft" } });
    expect(screen.getByRole("textbox", { name: "Previous group send text" })).toHaveProperty("value", "Original group boundary message");
    fireEvent.click(retry);
    await screen.findByRole("button", { name: "Send group message" });
    await waitFor(() => expect(composer.value).toBe("Newer group boundary draft"));
    const sends = transport.invoke.mock.calls.filter(([command, args]) => command === "core_api_request" && args.operation === "group.message_enqueue");
    expect(sends).toHaveLength(2);
    expect(sends[1][1]).toEqual(sends[0][1]);
    expect(sends[0][1].idempotencyKey).toEqual(expect.any(String));
    const replayed = await host.invoke("fixture_inspect");
    expect(replayed).toMatchObject({ group_messages: committed.group_messages, group_delivery_count: committed.group_delivery_count, optional_receipt_count: 2 });
    expect(transport.invoke.mock.calls.some(([command, args]) => command === "core_api_request" && args.operation === "message.query")).toBe(false);
  });

  it("restores an unsent composer after renderer remount and real vault reopen", async () => {
    await startHost();
    const caps = await host.invoke("core_api_capabilities") as { operations: string[] };
    expect(caps.operations).toEqual(expect.arrayContaining(["peer.composer_query", "peer.composer_update", "message.enqueue_draft"]));
    render(<App />);
    const composer = await liveComposer();
    fireEvent.change(composer, { target: { value: "Durable unsent composer" } });
    await waitFor(() => expect(transport.invoke.mock.calls.some(([command, args]) => command === "core_api_request"
      && args.operation === "peer.composer_update" && args.params.text === "Durable unsent composer")).toBe(true));
    // Await a later serialized read to ensure the real update has reached the host.
    const profile = await coreApiProfile();
    const persisted = await host.invoke("core_api_request", { operation: "peer.composer_query",
      params: { profile: profile.profile, peer: profile.peers[0] } }) as { text: string; revision: string };
    expect(persisted).toMatchObject({ text: "Durable unsent composer", revision: expect.any(String) });
    cleanup();
    await host.invoke("fixture_reopen");
    render(<App />);
    await liveComposer();
    await waitFor(() => expect((screen.getByRole("textbox", { name: "Message Boundary Blair" }) as HTMLTextAreaElement).value).toBe("Durable unsent composer"));
    expect(transport.invoke.mock.calls.some(([command]) => command === "core_api_send_message")).toBe(false);
    expect(await host.invoke("fixture_inspect")).toMatchObject({ messages: [] });
  });

  it("resolves a lost draft enqueue reply after remount and vault reopen without a second send", async () => {
    await startHost();
    const caps = await host.invoke("core_api_capabilities") as { operations: string[] };
    expect(caps.operations).toEqual(expect.arrayContaining(["peer.composer_query", "peer.composer_update", "message.enqueue_draft"]));
    render(<App />);
    const composer = await liveComposer();
    fireEvent.change(composer, { target: { value: "Committed composer remount" } });
    await waitFor(() => expect(transport.invoke.mock.calls.some(([command, args]) => command === "core_api_request"
      && args.operation === "peer.composer_update" && args.params.text === "Committed composer remount")).toBe(true));
    const profile = await coreApiProfile();
    const persisted = await host.invoke("core_api_request", { operation: "peer.composer_query",
      params: { profile: profile.profile, peer: profile.peers[0] } }) as { revision: string; text: string };
    expect(persisted.text).toBe("Committed composer remount");
    loseNextDraftSendReply = true;
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(enqueueAccepted).toBe(true));
    cleanup();
    await host.invoke("fixture_reopen");
    render(<App />);
    await liveComposer();
    await waitFor(() => expect((screen.getByRole("textbox", { name: "Message Boundary Blair" }) as HTMLTextAreaElement).value).toBe(""));
    const stored = await host.invoke("fixture_inspect") as { messages: { text: string }[] };
    expect(stored.messages.map(message => message.text)).toEqual(["Committed composer remount"]);
    const sends = transport.invoke.mock.calls.filter(([command, args]) => command === "core_api_request" && args.operation === "message.enqueue_draft");
    expect(sends).toHaveLength(1);
    expect(sends[0][1]).toMatchObject({ idempotencyKey: persisted.revision,
      params: { draft_revision: persisted.revision } });
    expect(transport.invoke.mock.calls.some(([command]) => command === "core_api_send_message" || command === "service_command")).toBe(false);
  });

  it("creates one fresh identity from rendered onboarding and resolves a lost committed reply", async () => {
    await startHost({ freshProfile: true });
    expect(await host.invoke("fixture_inspect")).toMatchObject({ profile_count: 0, identity_count: 0, profile: null });
    loseNextProfileReply = true;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Start a chat" }));
    const name = screen.getByRole("textbox", { name: "Display name" });
    fireEvent.change(name, { target: { value: "Fresh rendered owner" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my invite" }));
    await screen.findByRole("alert");
    const committed = await host.invoke("fixture_inspect") as {
      profile_count: number; identity_count: number; profile: { display_name: string; destination_hash: string };
    };
    expect(committed).toMatchObject({ profile_count: 1, identity_count: 1, profile: { display_name: "Fresh rendered owner" } });
    const creates = () => transport.invoke.mock.calls.filter(([command, args]) => command === "core_api_request"
      && args.operation === "profile.create");
    expect(creates()).toHaveLength(1);
    expect(creates()[0][1]).toMatchObject({ params: { display_name: "Fresh rendered owner" }, idempotencyKey: expect.any(String) });
    const retry = screen.getByRole("button", { name: "Create my invite" });
    await waitFor(() => expect(retry.hasAttribute("disabled")).toBe(false));
    fireEvent.click(retry);
    await screen.findByRole("heading", { name: "Your private conversations" });
    expect(creates()).toHaveLength(1);
    expect(await coreApiProfile()).toMatchObject({ display_name: "Fresh rendered owner", destination: committed.profile.destination_hash });
    expect(await host.invoke("fixture_inspect")).toMatchObject({ profile_count: 1, identity_count: 1, profile: committed.profile });
    expect(transport.invoke.mock.calls.filter(([command]) => command === "initialize_service")).toHaveLength(1);
    expect(transport.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
  });

  it("enqueues durable text through the real serializer and service", async () => {
    const composer = await compose("Boundary durable hello");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(enqueueAccepted).toBe(true));
    await waitFor(() => expect(composer.value).toBe(""));
    const stored = await host.invoke("fixture_inspect") as { messages: { text: string; state: string }[] };
    expect(stored.messages.map((message) => message.text)).toEqual(["Boundary durable hello"]);
    expect(stored.messages[0].state).not.toBe("delivered");
    expect(transport.invoke.mock.calls.some(([command]) => command === "service_command")).toBe(false);
  });

  it("keeps accepted text cleared when the following snapshot fails", async () => {
    const composer = await compose("Accepted before refresh failure");
    failRefreshAfterEnqueue = true;
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(enqueueAccepted).toBe(true));
    await screen.findByRole("alert");
    expect(composer.value).toBe("");
    const stored = await host.invoke("fixture_inspect") as { messages: unknown[] };
    expect(stored.messages).toHaveLength(1);
  });

  it("retries an uncertain committed enqueue with the same key and one durable record", async () => {
    const composer = await compose("Lost committed reply");
    loseNextDraftSendReply = true;
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("alert");
    expect(composer.value).toBe("Lost committed reply");
    fireEvent.click(screen.getByRole("button", { name: "Retry previous send" }));
    const draftSends = () => transport.invoke.mock.calls.filter(([command, args]) =>
      command === "core_api_request" && args.operation === "message.enqueue_draft");
    await waitFor(() => expect(draftSends()).toHaveLength(2));
    await act(async () => { await host.invoke("fixture_inspect"); });
    const sends = draftSends();
    expect(sends[1][1]).toEqual(sends[0][1]);
    expect(sends[0][1]).toMatchObject({ idempotencyKey: expect.stringMatching(/^[0-9a-f]{64}$/),
      params: { draft_revision: sends[0][1].idempotencyKey } });
    expect(transport.invoke.mock.calls.some(([command]) => command === "core_api_send_message" || command === "core_api_draft_set")).toBe(false);
    expect(transport.invoke.mock.calls.some(([command, args]) => command === "core_api_request"
      && args.operation === "peer.composer_update" && args.params.text === "")).toBe(false);
    const stored = await host.invoke("fixture_inspect") as { messages: unknown[] };
    expect(stored.messages).toHaveLength(1);
  });

  it("preserves canonical workspace conversation fields from rendered channel send", async () => {
    await startHost();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Boundary Team" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    await within(conversation).findByText("Boundary root message", { selector: "article p" });
    const composer = within(conversation).getByRole("textbox", { name: "Message general" });
    fireEvent.change(composer, { target: { value: "Workspace boundary hello" } });
    fireEvent.click(within(conversation).getByRole("button", { name: "Send workspace message" }));
    await waitFor(() => {
      const call = transport.invoke.mock.calls.find(([command, args]) => command === "core_api_request"
        && args.operation === "workspace.timeline_mutation" && args.params.action === "channel_message");
      expect(call).toBeDefined();
      expect(call![1].params).toHaveProperty("conversation");
      expect(call![1].params).not.toHaveProperty("conversation_id");
    });
    await within(conversation).findByText("Workspace boundary hello", { selector: "article p" });
    fireEvent.click(within(conversation).getAllByRole("button", { name: "Thread" })[0]);
    const thread = await screen.findByLabelText("Thread in Boundary Team");
    await within(thread).findByText("Boundary root message", { selector: "article p" });
    const query = transport.invoke.mock.calls.find(([command, args]) => command === "core_api_request"
      && args.operation === "workspace.timeline_query" && args.params.view === "thread_messages");
    expect(query![1].params).toHaveProperty("thread_root");
    expect(query![1].params).not.toHaveProperty("thread_root_id");
    const threadComposer = within(thread).getByRole("textbox", { name: "Reply in thread" }) as HTMLTextAreaElement;
    fireEvent.change(threadComposer,
      { target: { value: "Boundary thread reply" } });
    const sendReply = within(thread).getByRole("button", { name: "Send thread reply" });
    await waitFor(() => expect(sendReply.hasAttribute("disabled")).toBe(false));
    let releaseReply!: () => void;
    const heldReply = new Promise<void>((resolve) => { releaseReply = resolve; });
    beforeThreadReply = () => heldReply;
    fireEvent.click(sendReply);
    try {
      await waitFor(() => expect(transport.invoke.mock.calls.some(([command, args]) => command === "core_api_request"
        && args.operation === "workspace.timeline_mutation" && args.params.action === "thread_reply")).toBe(true));
      expect(threadComposer.value).toBe("Boundary thread reply");
      expect(within(thread).queryByText("Boundary thread reply", { selector: "article p" })).toBeNull();
    } finally {
      releaseReply();
    }
    await within(thread).findByText("Boundary thread reply", { selector: "article p" });
    const reply = transport.invoke.mock.calls.find(([command, args]) => command === "core_api_request"
      && args.operation === "workspace.timeline_mutation" && args.params.action === "thread_reply");
    expect(reply).toBeDefined();
    expect(reply![1].params).toHaveProperty("thread_root");
    expect(reply![1].params).toHaveProperty("conversation");
    expect(reply![1].params).not.toHaveProperty("thread_root_id");
    expect(reply![1].params).not.toHaveProperty("conversation_id");
    const saved = await coreApiTimelineQuery(query![1].params.workspace, "thread_messages", {
      thread_root: query![1].params.thread_root, cursor: null, limit: 50,
    }) as { replies: { id: string; text: string; thread_root: string }[] };
    expect(saved.replies).toEqual([expect.objectContaining({
      id: reply![1].params.event_id, text: "Boundary thread reply", thread_root: query![1].params.thread_root,
    })]);
  });

  it("serializes thread_root to a real timeline query without legacy field aliases", async () => {
    await startHost();
    const snapshot = await host.invoke("initialize_service") as { workspaces: { core_handle: string }[] };
    const fixture = await host.invoke("fixture_inspect") as { root: { id: string } };
    expect((await coreApiProfile()).profile).toBeTruthy();
    const result = await coreApiTimelineQuery(snapshot.workspaces[0].core_handle,
      "thread_messages", { thread_root: fixture.root.id, cursor: null, limit: 50 });
    expect(result.root).toMatchObject({ text: "Boundary root message" });
  });
});
