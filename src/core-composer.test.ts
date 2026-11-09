import { beforeEach, describe, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(), onOpenUrl: vi.fn() }));

import { composerRequests, openCoreComposer } from "./core-composer";

const limits = {
  composer_text_utf8_bytes: 16384, composers_per_caller_profile: 256, composers_per_vault: 4096,
  composer_update_idempotency_seconds: 3600, composer_update_keys_per_caller_profile: 8192,
  composer_update_keys_per_vault: 65536, composer_send_idempotency_seconds: 604800,
  composer_send_keys_per_caller_profile: 4096, composer_send_keys_per_vault: 65536,
};
const capabilities = () => ({ api_major: 1, api_minor: 1, operations: ["peer.composer_query", "peer.composer_update", "message.enqueue_draft"], limits: { ...limits } });
const profile = "profile-handle";
const peer = "peer-handle";
const revision = "a".repeat(64);
const updateKey = "b".repeat(64);

beforeEach(() => { host.invoke.mockReset(); });

describe("composer native serialization", () => {
  it("gates support before resolving a peer and uses Core-issued identities exactly", async () => {
    host.invoke.mockImplementation(async (command) => command === "core_api_capabilities" ? capabilities()
      : command === "core_api_peer_for_destination" ? { profile, peer, destination: "destination" } : {});
    const { port, textUtf8Bytes } = await openCoreComposer("destination");
    expect(textUtf8Bytes).toBe(16384);
    await port.query();
    expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", {
      operation: "peer.composer_query", params: { profile, peer }, idempotencyKey: null,
    });
    await port.query(revision);
    expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", {
      operation: "peer.composer_query", params: { profile, peer, send_revision: revision }, idempotencyKey: null,
    });
    await port.update(null, "First persisted text", updateKey);
    expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", {
      operation: "peer.composer_update", params: { profile, peer, expected_revision: null, text: "First persisted text" }, idempotencyKey: updateKey,
    });
    await port.enqueue(revision);
    expect(host.invoke).toHaveBeenLastCalledWith("core_api_request", {
      operation: "message.enqueue_draft", params: { profile, recipient: peer, draft_revision: revision }, idempotencyKey: revision,
    });
    expect(host.invoke.mock.calls.map(([command]) => command)).not.toContain("core_api_send_message");
    expect(host.invoke.mock.calls.map(([command]) => command)).not.toContain("core_api_draft_set");
  });

  it.each(["minor", "missing_operation", "missing_limit", "invalid_limit"])("refuses %s without peer lookup or mutation", async (kind) => {
    const value = capabilities();
    if (kind === "minor") value.api_minor = 0;
    if (kind === "missing_operation") value.operations.pop();
    if (kind === "missing_limit") delete (value.limits as Partial<typeof limits>).composer_text_utf8_bytes;
    if (kind === "invalid_limit") value.limits.composer_update_idempotency_seconds = NaN;
    host.invoke.mockResolvedValue(value);
    await expect(openCoreComposer("destination")).rejects.toMatchObject({ code: "unsupported_operation" });
    expect(host.invoke.mock.calls).toEqual([["core_api_capabilities", undefined]]);
  });

  it("preserves typed uncertainty and never falls back after draft enqueue", async () => {
    host.invoke.mockRejectedValue(JSON.stringify({ code: "unavailable", retry_after_ms: 100 }));
    await expect(composerRequests({ profile, peer }).enqueue(revision)).rejects.toMatchObject({ code: "unavailable", retry_after_ms: 100 });
    expect(host.invoke).toHaveBeenCalledTimes(1);
    expect(host.invoke).toHaveBeenCalledWith("core_api_request", {
      operation: "message.enqueue_draft", params: { profile, recipient: peer, draft_revision: revision }, idempotencyKey: revision,
    });
  });
});
