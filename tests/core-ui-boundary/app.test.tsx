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
let loseNextSendReply = false;
let loseNextProfileReply = false;
let failRefreshAfterEnqueue = false;
let enqueueAccepted = false;
let beforeThreadReply: (() => Promise<void>) | null = null;

beforeEach(async () => {
  hostStarted = false;
  loseNextSendReply = false;
  loseNextProfileReply = false;
  failRefreshAfterEnqueue = false;
  enqueueAccepted = false;
  beforeThreadReply = null;
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
    if (command === "core_api_request" && args.operation === "profile.create" && loseNextProfileReply) {
      loseNextProfileReply = false;
      throw new Error(JSON.stringify({ code: "unavailable", retry_after_ms: null, outcome: "unknown" }));
    }
    if (command === "core_api_send_message") {
      enqueueAccepted = true;
      if (loseNextSendReply) {
        loseNextSendReply = false;
        // The real session committed. Only the caller's response is lost.
        throw new Error(JSON.stringify({ code: "unavailable", retry_after_ms: null, outcome: "unknown" }));
      }
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
  const composer = await screen.findByRole("textbox", { name: "Message Boundary Blair" });
  fireEvent.change(composer, { target: { value: text } });
  return composer as HTMLTextAreaElement;
}

describe("rendered UI through the production framed Core session", () => {
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
    loseNextSendReply = true;
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("alert");
    expect(composer.value).toBe("Lost committed reply");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(transport.invoke.mock.calls.filter(([command]) => command === "core_api_send_message")).toHaveLength(2));
    await act(async () => { await host.invoke("fixture_inspect"); });
    const sends = transport.invoke.mock.calls.filter(([command]) => command === "core_api_send_message");
    expect(sends[1][1]).toEqual(sends[0][1]);
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
