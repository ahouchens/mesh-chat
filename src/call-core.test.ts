import { afterEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));

import { callControl, fetchCallMedia } from "./call-core";

afterEach(() => host.invoke.mockReset());

it("unwraps the actual call control envelope and sends one keyed mutation", async () => {
  host.invoke.mockImplementation(async (command: string) => command === "core_api_profile"
    ? { profile: "profile-handle" } : { profile: "profile-handle", result: { id: "local-call", state: "dialing" } });
  await expect(callControl("start", { contact_id: "contact", media: "audio" }))
    .resolves.toEqual({ id: "local-call", state: "dialing" });
  expect(host.invoke.mock.calls).toEqual([
    ["core_api_profile", undefined],
    ["core_api_request", { operation: "call.control", params: {
      profile: "profile-handle", action: "start", contact_id: "contact", media: "audio",
    }, idempotencyKey: expect.stringMatching(/^[0-9a-f-]{36}$/) }],
  ]);
});

it("resolves a local call ID through the scoped snapshot before querying media", async () => {
  host.invoke.mockImplementation(async (command: string, args: Record<string, unknown>) => {
    if (command === "core_api_profile") return { profile: "profile-handle" };
    if (args.operation === "application.snapshot") return { calls: [
      { id: "another-call", core_handle: "other-handle" }, { id: "local-call", core_handle: "scoped-call" },
    ] };
    if (args.operation === "call.media_query") return { profile: "profile-handle", call: "scoped-call", media: {
      id: "local-call", state: "in_call", remote_sdp: "answer-sdp",
    } };
    throw new Error("Unexpected native request");
  });
  await expect(fetchCallMedia({ id: "local-call" })).resolves.toMatchObject({
    id: "local-call", core_handle: "scoped-call", remote_sdp: "answer-sdp",
  });
  expect(host.invoke.mock.calls.filter(([command]) => command === "core_api_request")).toEqual([
    ["core_api_request", { operation: "application.snapshot", params: {}, idempotencyKey: null }],
    ["core_api_request", { operation: "call.media_query", params: { profile: "profile-handle", call: "scoped-call" }, idempotencyKey: null }],
  ]);
});

it("reuses a scoped call handle without reading another snapshot", async () => {
  host.invoke.mockImplementation(async (command: string) => command === "core_api_profile"
    ? { profile: "profile-handle" } : { media: { id: "local-call", state: "ringing" } });
  await fetchCallMedia({ id: "local-call", core_handle: "scoped-call" });
  expect(host.invoke.mock.calls).toHaveLength(2);
  expect(host.invoke.mock.calls[1][1]).toMatchObject({ operation: "call.media_query", params: { call: "scoped-call" } });
});

it("does not query media or use a native command when the call is absent", async () => {
  host.invoke.mockResolvedValue({ calls: [{ id: "another-call", core_handle: "other-handle" }] });
  await expect(fetchCallMedia({ id: "missing" })).rejects.toMatchObject({ code: "call_not_found" });
  expect(host.invoke.mock.calls).toHaveLength(1);
  expect(host.invoke.mock.calls[0][1]).toMatchObject({ operation: "application.snapshot" });
});

it.each(["forbidden", "unavailable"])("preserves %s from media reads without a legacy fallback", async (code) => {
  host.invoke.mockImplementation(async (command: string) => {
    if (command === "core_api_profile") return { profile: "profile-handle" };
    throw JSON.stringify({ code, retry_after_ms: null });
  });
  await expect(fetchCallMedia({ id: "local-call", core_handle: "scoped-call" })).rejects.toMatchObject({ code });
  expect(host.invoke.mock.calls.map(([command]) => command)).toEqual(["core_api_profile", "core_api_request"]);
});
