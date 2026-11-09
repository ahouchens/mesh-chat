import { afterEach, beforeEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));

import { CallOperation, callRecovery } from "./call-operation";

let losses: number;
let profile: string;
let committed: string[];
let receipts: Map<string, Record<string, unknown>>;
const requests = () => host.invoke.mock.calls.filter(([command]) => command === "core_api_request")
  .map(([, request]) => request as { params: Record<string, unknown>; idempotencyKey: string });

beforeEach(() => {
  losses = 1;
  profile = "original-profile";
  committed = [];
  receipts = new Map();
  host.invoke.mockImplementation(async (command: string, request: { params: Record<string, unknown>; idempotencyKey: string }) => {
    if (command === "core_api_profile") return { profile };
    const existing = receipts.get(request.idempotencyKey);
    if (existing) return { result: existing };
    committed.push(String(request.params.action));
    const result = { id: "one-call", state: request.params.action === "end" ? "ended" : "dialing", role: "caller" };
    receipts.set(request.idempotencyKey, result);
    if (losses-- > 0) throw JSON.stringify({ code: "unavailable", outcome: "unknown", retry_after_ms: null });
    return { result };
  });
});

afterEach(async () => {
  losses = 0;
  for (const session of callRecovery.getSnapshot()) await session.retry();
  await vi.waitFor(() => expect(callRecovery.getSnapshot()).toHaveLength(0));
  host.invoke.mockReset();
});

it.each(["start", "answer", "restart", "answer_restart"])("resolves a lost %s reply using its original profile, key and SDP", async (action) => {
  const operation = new CallOperation("Taylor", action === "start" ? undefined : "one-call");
  const params = { ...(action === "start" ? { contact_id: "contact", media: "video" } : { call_id: "one-call" }), sdp: "original-sdp", dtls_fingerprint: "fingerprint" };
  const outcome = operation.control(action, params);
  await vi.waitFor(() => expect(operation.getSnapshot().uncertain).toBe(true));
  params.sdp = "replaced-by-caller";
  profile = "different-profile";
  await expect(operation.control("restart", {})).rejects.toThrow("call_operation_pending");
  expect(requests()).toHaveLength(1);
  await operation.retry();
  await expect(outcome).resolves.toMatchObject({ id: "one-call" });
  expect(requests()[1]).toEqual(requests()[0]);
  expect(requests()[1].params).toMatchObject({ profile: "original-profile", sdp: "original-sdp" });
  expect(committed).toEqual([action]);
  operation.cancel();
  await vi.waitFor(() => expect(committed).toEqual([action, "end"]));
  await vi.waitFor(() => expect(callRecovery.getSnapshot()).toHaveLength(0));
});

it("cancels an uncertain committed start by resolving its ticket before ending the exact call", async () => {
  const operation = new CallOperation("Taylor");
  const outcome = operation.control("start", { contact_id: "contact", media: "audio", sdp: "original-sdp" });
  await vi.waitFor(() => expect(operation.getSnapshot().uncertain).toBe(true));
  operation.cancel();
  operation.cancel();
  await outcome;
  await vi.waitFor(() => expect(callRecovery.getSnapshot()).toHaveLength(0));
  expect(requests()).toHaveLength(3);
  expect(requests()[1]).toEqual(requests()[0]);
  expect(requests()[2].params).toEqual({ profile: "original-profile", action: "end", call_id: "one-call", reason: "cancelled" });
  expect(committed).toEqual(["start", "end"]);
});

it("retains a lost cleanup reply for explicit retry and blocks a new call", async () => {
  losses = 0;
  const operation = new CallOperation("Taylor");
  await operation.control("start", { sdp: "original-sdp" });
  losses = 1;
  operation.cancel();
  await vi.waitFor(() => expect(operation.getSnapshot().uncertain).toBe(true));
  expect(callRecovery.getSnapshot()).toContain(operation);
  expect(new CallOperation("Another contact").reset()).toBe(false);
  expect(committed).toEqual(["start", "end"]);
  const ending = requests()[1];
  await operation.retry();
  expect(requests()[2]).toEqual(ending);
  expect(committed).toEqual(["start", "end"]);
  expect(callRecovery.getSnapshot()).toHaveLength(0);
});

it.each(["resync_required", "forbidden", "idempotency_expired"])("keeps an uncertain ticket after %s without authorizing a fresh mutation", async (code) => {
  const operation = new CallOperation("Taylor");
  const outcome = operation.control("start", { sdp: "original-sdp" });
  await vi.waitFor(() => expect(operation.getSnapshot().uncertain).toBe(true));
  host.invoke.mockRejectedValueOnce(JSON.stringify({ code }));
  await operation.retry();
  expect(operation.getSnapshot()).toMatchObject({ pending: true, uncertain: true, errorCode: code });
  await expect(operation.control("start", { sdp: "new-sdp" })).rejects.toThrow("call_operation_pending");
  expect(requests()[1]).toEqual(requests()[0]);
  expect(committed).toEqual(["start"]);
  await operation.retry();
  await outcome;
  await operation.cancel();
});
