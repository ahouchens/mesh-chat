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
let loseNextSendReply = false;
let failRefreshAfterEnqueue = false;
let enqueueAccepted = false;

beforeEach(async () => {
  host = new FacadeHost();
  loseNextSendReply = false;
  failRefreshAfterEnqueue = false;
  enqueueAccepted = false;
  window.localStorage.clear();
  transport.invoke.mockReset();
  transport.invoke.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
    if (command === "runtime_platform") return "desktop";
    if (command === "set_native_theme") return;
    if (command === "notification_capability") return { supported: false, platform: "desktop", permission_state: "unsupported" };
    if (command === "core_api_request" && args.operation === "application.snapshot"
      && enqueueAccepted && failRefreshAfterEnqueue) throw new Error("fixture_snapshot_unavailable");
    const result = await host.invoke(command, args);
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
  // Establish readiness before rendering, so startup failures have useful host diagnostics.
  await host.invoke("fixture_inspect");
});

afterEach(async () => {
  cleanup();
  await host.close();
});

async function compose(text: string) {
  render(<App />);
  const composer = await screen.findByRole("textbox", { name: "Message Boundary Blair" });
  fireEvent.change(composer, { target: { value: text } });
  return composer as HTMLTextAreaElement;
}

describe("rendered UI through the production framed Core session", () => {
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
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Workspace Boundary Team" }));
    const conversation = await screen.findByLabelText("Workspace channel general");
    await within(conversation).findByText("Boundary root message");
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
    await within(conversation).findByText("Workspace boundary hello");
    fireEvent.click(within(conversation).getAllByRole("button", { name: "Thread" })[0]);
    const thread = await screen.findByLabelText("Thread in Boundary Team");
    await within(thread).findByText("Boundary root message");
    const query = transport.invoke.mock.calls.find(([command, args]) => command === "core_api_request"
      && args.operation === "workspace.timeline_query" && args.params.view === "thread_messages");
    expect(query![1].params).toHaveProperty("thread_root");
    expect(query![1].params).not.toHaveProperty("thread_root_id");
    fireEvent.change(within(thread).getByRole("textbox", { name: "Reply in thread" }),
      { target: { value: "Boundary thread reply" } });
    fireEvent.click(within(thread).getByRole("button", { name: "Send thread reply" }));
    await within(thread).findByText("Boundary thread reply");
    const reply = transport.invoke.mock.calls.find(([command, args]) => command === "core_api_request"
      && args.operation === "workspace.timeline_mutation" && args.params.action === "thread_reply");
    expect(reply![1].params).toHaveProperty("thread_root");
    expect(reply![1].params).toHaveProperty("conversation");
    expect(reply![1].params).not.toHaveProperty("thread_root_id");
    expect(reply![1].params).not.toHaveProperty("conversation_id");
  });

  it("serializes thread_root to a real timeline query without legacy field aliases", async () => {
    const snapshot = await host.invoke("initialize_service") as { workspaces: { core_handle: string }[] };
    const fixture = await host.invoke("fixture_inspect") as { root: { id: string } };
    expect((await coreApiProfile()).profile).toBeTruthy();
    const result = await coreApiTimelineQuery(snapshot.workspaces[0].core_handle,
      "thread_messages", { thread_root: fixture.root.id, cursor: null, limit: 50 });
    expect(result.root).toMatchObject({ text: "Boundary root message" });
  });
});
