import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Snapshot } from "./types";
const host = vi.hoisted(() => ({ invoke: vi.fn(), events: [] as Array<(event: { payload: unknown }) => void> }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: host.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (name, callback) => { if (name === "mesh-chat://service-event") host.events.push(callback); return () => undefined; }) }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ getCurrent: vi.fn(async () => []), onOpenUrl: vi.fn(async () => () => undefined) }));
vi.mock("@tauri-apps/api/app", () => ({ onBackButtonPress: vi.fn() }));
import App from "./App";
import { parseProfileCatalog, supportsProfileLifecycle } from "./core-profiles";

const first = "a".repeat(64), second = "b".repeat(64), credential = "c".repeat(64);
const caps = { api_major: 1, api_minor: 1, stability: "experimental", profiles: [first, second],
  operations: ["profile.catalog", "profile.select", "profile.lock", "profile.unlock"],
  limits: { profile_slots: 8, profile_lifecycle_keys_per_host: 4096, profile_lifecycle_keys_per_caller_profile: 256, profile_unlock_credentials: 128 } };
const requests = (operation: string) => host.invoke.mock.calls.filter(([command, args]) => command === "core_api_request" && args.operation === operation).map(([, args]) => args);
const native = (command: string) => host.invoke.mock.calls.filter(([name]) => name === command);
const reject = (code: string): never => { throw JSON.stringify({ code, retry_after_ms: null }); };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { resolve, promise }; }
let selected: string, state: "locked" | "unlocked" | "retiring", revision: number;
let authenticate: () => Promise<unknown>;
let mutate: (operation: string, params: Record<string, unknown>, key: string) => Promise<unknown>;
const catalog = () => ({ profiles: [first, second].map((profile, index) => ({ profile, display_name: index ? "Work" : "Personal", selected: selected === profile, state: selected === profile ? state : "locked" })), selected_profile: selected, revision });
const snapshot = (): Snapshot => ({ profile: { display_name: selected === first ? "Alex" : "Blair", public_identity: "identity", identity_hash: "11".repeat(16), destination_hash: selected.slice(0, 32), fingerprint: "AAAA BBBB", created_at: 1 },
  contacts: [], messages: [], drafts: [], service_error: null,
  settings: { nearby_discovery: true, lan_fallback: true, lan_listener_port: null, allowed_interfaces: [], tcp_clients: [], tcp_listener: null, help_route: false, store_for_offline: false, approved_propagation_nodes: [], i2p_enabled: false, i2p_connectable: false, i2p_managed: true, i2p_peers: [] },
  network: { transport_enabled: false, propagation_enabled: false, interface_available: true, interfaces: [], outbound_propagation_node: null } });
beforeEach(() => {
  selected = first; state = "locked"; revision = 0; host.events.length = 0;
  authenticate = async () => ({ credential_handle: credential, expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) });
  mutate = async (operation, params) => { selected = params.profile as string; state = operation === "profile.unlock" ? "unlocked" : "locked"; revision++; return catalog(); };
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "runtime_platform") return "desktop";
    if (command === "initialize_service") { if (state !== "unlocked") reject("locked"); return {}; }
    if (command === "core_api_capabilities") return caps;
    if (command === "core_api_unlock_credential") return authenticate();
    if (command === "core_api_profile") return { profile: selected, destination: selected.slice(0, 32), connections: [], peers: [] };
    if (command === "set_native_theme") return;
    if (command === "lock_service" || command === "service_command") throw new Error(`Forbidden legacy lifecycle fallback: ${command}`);
    if (command === "core_api_request") {
      if (args.operation === "profile.catalog") return catalog();
      if (["profile.lock", "profile.select", "profile.unlock"].includes(args.operation)) return mutate(args.operation, args.params, args.idempotencyKey);
      if (args.operation === "application.snapshot") { if (state !== "unlocked") reject("locked"); return snapshot(); }
      if (args.operation === "native.command") return { profiles: [], sessions: [] };
      if (args.operation === "workspace.snapshot") return { workspaces: [], workspace_join_requests: [] };
      if (args.operation === "remote_profile.query") return { profiles: [] };
      if (args.operation === "call.settings_query") return { settings: {} };
      return {};
    }
    return {};
  });
});
afterEach(() => { cleanup(); host.invoke.mockReset(); });
const bootLocked = async () => { render(<App />); await screen.findByRole("button", { name: "Unlock selected profile" }); };

it("boots a cold locked native host into its catalog without querying the profile snapshot", async () => {
  await bootLocked();
  expect((screen.getByRole("combobox", { name: "Selected profile" }) as HTMLSelectElement).value).toBe(first);
  expect(requests("application.snapshot")).toHaveLength(0); expect(native("core_api_unlock_credential")).toHaveLength(0);
  expect(native("initialize_service")).toHaveLength(1);
});
it("selects another opaque profile with a caller key and leaves it locked", async () => {
  await bootLocked(); fireEvent.change(screen.getByRole("combobox", { name: "Selected profile" }), { target: { value: second } });
  await waitFor(() => expect(requests("profile.select")).toHaveLength(1));
  await screen.findByRole("button", { name: "Unlock selected profile" });
  expect(requests("profile.select")[0]).toMatchObject({ params: { profile: second }, idempotencyKey: expect.any(String) });
  expect(requests("profile.unlock")).toHaveLength(0); expect(native("core_api_unlock_credential")).toHaveLength(0);
  expect(requests("application.snapshot")).toHaveLength(0); expect(native("initialize_service")).toHaveLength(1);
});
it("waits for actual native authentication before submitting keyed unlock and publishing a fresh snapshot", async () => {
  const auth = deferred<unknown>(); authenticate = () => auth.promise;
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await waitFor(() => expect(native("core_api_unlock_credential")).toHaveLength(1));
  expect(native("core_api_unlock_credential")[0][1]).toEqual({ profile: first }); expect(requests("profile.unlock")).toHaveLength(0);
  await act(async () => auth.resolve({ credential_handle: credential, expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(requests("profile.unlock")[0]).toMatchObject({ params: { profile: first, credential_handle: credential }, idempotencyKey: expect.any(String) });
  expect(native("initialize_service")).toHaveLength(1);
});
it.each(["authentication_cancelled", "unsupported_operation"])("keeps %s native authentication failures locked without Core or legacy unlock", async (code) => {
  authenticate = async () => reject(code); await bootLocked();
  fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await screen.findByRole("alert"); await screen.findByRole("button", { name: "Unlock selected profile" });
  expect(requests("profile.unlock")).toHaveLength(0); expect(native("initialize_service")).toHaveLength(1); expect(native("lock_service")).toHaveLength(0);
});
it("retries a committed unlock whose reply was lost with its exact caller key and credential", async () => {
  const complete = mutate; let lost = true;
  mutate = async (operation, params, key) => { if (lost) { lost = false; await complete(operation, params, key); reject("unavailable"); } return catalog(); };
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry previous unlock" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(requests("profile.unlock")).toHaveLength(2);
  expect(requests("profile.unlock")[1]).toEqual(requests("profile.unlock")[0]);
  expect(native("core_api_unlock_credential")).toHaveLength(1); expect(native("initialize_service")).toHaveLength(1);
});
it("refreshes expired native authorization while preserving the unknown unlock identity", async () => {
  let attempts = 0;
  const complete = mutate;
  mutate = async (operation, params, key) => { attempts++; if (attempts === 1) reject("unavailable"); if (attempts === 2) reject("forbidden"); return complete(operation, params, key); };
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry previous unlock" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Retry to authenticate again"));
  const refreshed = "e".repeat(64); authenticate = async () => ({ credential_handle: refreshed, expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) });
  fireEvent.click(screen.getByRole("button", { name: "Retry previous unlock" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  const rows = requests("profile.unlock"); expect(new Set(rows.map((row) => row.idempotencyKey)).size).toBe(1);
  expect(rows[2].params).toEqual({ profile: first, credential_handle: refreshed }); expect(native("core_api_unlock_credential")).toHaveLength(2);
});
it("blocks a stale action until explicit catalog review and never opens as part of review", async () => {
  mutate = async () => reject("resync_required"); await bootLocked();
  fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Retry previous unlock" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Unlock selected profile" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Review current profiles" }));
  await screen.findByRole("button", { name: "Unlock selected profile" });
  expect(requests("profile.unlock")).toHaveLength(1); expect(requests("application.snapshot")).toHaveLength(0);
});
it("retains an earlier unknown unlock key when renewed device authentication is canceled", async () => {
  let attempts = 0;
  const complete = mutate;
  mutate = async (operation, params, key) => { attempts++; if (attempts === 1) reject("unavailable"); if (attempts === 2) reject("forbidden"); return complete(operation, params, key); };
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry previous unlock" }));
  await screen.findByText(/Retry to authenticate again/);
  authenticate = async () => reject("authentication_cancelled");
  fireEvent.click(screen.getByRole("button", { name: "Retry previous unlock" }));
  await screen.findByText(/Device authentication was canceled/);
  expect(screen.queryByRole("button", { name: "Unlock selected profile" })).toBeNull();
  expect(screen.getByRole("button", { name: "Retry previous unlock" })).toBeDefined();
  authenticate = async () => ({ credential_handle: credential, expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) });
  fireEvent.click(screen.getByRole("button", { name: "Retry previous unlock" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(new Set(requests("profile.unlock").map((row) => row.idempotencyKey)).size).toBe(1);
});
it.each(["lock", "select"] as const)("retries a committed %s with the same key and target and never implicitly opens", async (action) => {
  state = action === "lock" ? "unlocked" : "locked";
  const complete = mutate; let firstReply = true;
  mutate = async (operation, params, key) => { if (firstReply) { firstReply = false; await complete(operation, params, key); reject("unavailable"); } return catalog(); };
  render(<App />);
  if (action === "lock") fireEvent.click(await screen.findByRole("button", { name: "Lock Mesh Chat" }));
  else { await screen.findByRole("button", { name: "Unlock selected profile" }); fireEvent.change(screen.getByRole("combobox", { name: "Selected profile" }), { target: { value: second } }); }
  fireEvent.click(await screen.findByRole("button", { name: `Retry previous ${action}` }));
  await screen.findByRole("button", { name: "Unlock selected profile" });
  expect(requests(`profile.${action}`)).toHaveLength(2);
  expect(requests(`profile.${action}`)[1]).toEqual(requests(`profile.${action}`)[0]);
  expect(requests("profile.unlock")).toHaveLength(0); expect(native("core_api_unlock_credential")).toHaveLength(0);
});
it("does not repeat a confirmed unlock when its following snapshot needs review", async () => {
  const original = host.invoke.getMockImplementation()!;
  let snapshotReads = 0;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && args.operation === "application.snapshot" && ++snapshotReads === 1) reject("resync_required");
    return original(command, args);
  });
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Open selected profile" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Review current profiles" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open selected profile" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(requests("profile.unlock")).toHaveLength(1); expect(native("core_api_unlock_credential")).toHaveLength(1);
});
it("discards a snapshot arriving after a native transition canceled profile opening", async () => {
  const late = deferred<Snapshot>(); const original = host.invoke.getMockImplementation()!;
  host.invoke.mockImplementation(async (command, args) => command === "core_api_request" && args.operation === "application.snapshot" ? late.promise : original(command, args));
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await waitFor(() => expect(requests("application.snapshot")).toHaveLength(1));
  const old = snapshot();
  await act(async () => { state = "locked"; revision++; for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "e".repeat(32) } }); });
  await act(async () => late.resolve(old));
  expect(screen.queryByRole("button", { name: "Lock Mesh Chat" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Open selected profile" })).toBeNull();
  expect(screen.getByRole("button", { name: "Review current profiles" })).toBeDefined();
});
it("hides an open profile immediately and uses the keyed Core lock without legacy service teardown", async () => {
  state = "unlocked"; const reply = deferred<unknown>(); mutate = () => reply.promise;
  render(<App />); fireEvent.click(await screen.findByRole("button", { name: "Lock Mesh Chat" }));
  expect(screen.queryByRole("button", { name: "Lock Mesh Chat" })).toBeNull();
  await waitFor(() => expect(requests("profile.lock")).toHaveLength(1));
  state = "locked"; revision++;
  await act(async () => reply.resolve(catalog())); await screen.findByRole("button", { name: "Unlock selected profile" });
  expect(requests("profile.lock")[0].params).toEqual({ profile: first }); expect(native("lock_service")).toHaveLength(0);
});
it("invalidates an open renderer immediately on a native profile transition and requires review", async () => {
  state = "unlocked"; render(<App />); await screen.findByRole("button", { name: "Lock Mesh Chat" });
  await act(async () => { state = "locked"; revision++; for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "d".repeat(32) } }); });
  expect(screen.queryByRole("button", { name: "Lock Mesh Chat" })).toBeNull(); expect(screen.getByRole("alert").textContent).toContain("host changed");
  expect(requests("profile.unlock")).toHaveLength(0);
});
it("keeps retiring cold catalogs read-only when the previous renderer action key is unavailable", async () => {
  state = "retiring"; render(<App />); await screen.findByText(/Profile retirement is pending/);
  expect(screen.queryByRole("button", { name: "Unlock selected profile" })).toBeNull();
  expect((screen.getByRole("combobox", { name: "Selected profile" }) as HTMLSelectElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Review current profiles" }));
  await waitFor(() => expect(requests("profile.catalog").length).toBeGreaterThan(1));
  expect(requests("profile.lock")).toHaveLength(0); expect(requests("profile.unlock")).toHaveLength(0);
});
it("invalidates the renderer on host generation replacement even when profile, revision and state match", async () => {
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  await act(async () => { for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "e".repeat(32) } }); });
  expect(screen.queryByRole("button", { name: "Lock Mesh Chat" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Open selected profile" })).toBeNull();
  expect(screen.getByRole("alert").textContent).toContain("host changed");
});
it("blocks late authentication from a replaced host before submitting the original pending unlock", async () => {
  const auth = deferred<unknown>(); authenticate = () => auth.promise;
  await bootLocked();
  await act(async () => { for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "d".repeat(32) } }); });
  fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await waitFor(() => expect(native("core_api_unlock_credential")).toHaveLength(1));
  await act(async () => { for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "e".repeat(32) } }); });
  await act(async () => auth.resolve({ credential_handle: credential, expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) }));
  expect(requests("profile.unlock")).toHaveLength(0); expect(requests("application.snapshot")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Retry previous unlock" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Unlock selected profile" })).toBeNull();
  expect(screen.getByRole("alert").textContent).toContain("Review the current profiles");
});
it("discards late Core unlock completion from a replaced host before publishing its catalog or opening", async () => {
  const reply = deferred<unknown>(); mutate = () => reply.promise;
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await waitFor(() => expect(requests("profile.unlock")).toHaveLength(1));
  const old = { ...catalog(), revision: 1, profiles: catalog().profiles.map((row) => ({ ...row, state: row.selected ? "unlocked" : "locked" })) };
  await act(async () => { for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "e".repeat(32) } }); });
  await act(async () => reply.resolve(old));
  expect(requests("application.snapshot")).toHaveLength(0); expect(requests("profile.unlock")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Open selected profile" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Retry previous unlock" })).toBeNull();
  expect(screen.getByRole("combobox", { name: "Selected profile" }).textContent).toContain("Personal · locked");
});
it("accepts ordinary own lifecycle revision events while the original Core unlock is pending", async () => {
  const reply = deferred<unknown>(); mutate = () => reply.promise;
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await waitFor(() => expect(requests("profile.unlock")).toHaveLength(1));
  await act(async () => {
    state = "unlocked"; revision++;
    for (const callback of host.events) callback({ payload: { type: "event", event: "profile_lifecycle", profile: first, state, revision, host_generation: "d".repeat(32) } });
    reply.resolve(catalog());
  });
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(requests("profile.unlock")).toHaveLength(1);
});
it("handles a host first registered by native initialization without reading its locked vault", async () => {
  const original = host.invoke.getMockImplementation()!; let probes = 0;
  host.invoke.mockImplementation(async (command, args) => { if (command === "core_api_capabilities" && ++probes === 1) reject("unavailable"); return original(command, args); });
  await bootLocked();
  expect(requests("application.snapshot")).toHaveLength(0); expect(native("initialize_service")).toHaveLength(1);
  expect(native("core_api_unlock_credential")).toHaveLength(0);
});
it("retains the catalog for explicit snapshot retry when cold unlocked startup cannot read content", async () => {
  state = "unlocked"; const original = host.invoke.getMockImplementation()!; let failed = false;
  host.invoke.mockImplementation(async (command, args) => {
    if (command === "core_api_request" && args.operation === "application.snapshot" && !failed) { failed = true; reject("unavailable"); }
    return original(command, args);
  });
  render(<App />); fireEvent.click(await screen.findByRole("button", { name: "Open selected profile" }));
  await screen.findByRole("button", { name: "Lock Mesh Chat" });
  expect(requests("profile.unlock")).toHaveLength(0); expect(native("initialize_service")).toHaveLength(1);
});
it("rejects malformed native credential responses before any public unlock request", async () => {
  authenticate = async () => ({ credential_handle: "made-up", expires_in_ms: 60_000, revision, host_generation: "d".repeat(32) });
  await bootLocked(); fireEvent.click(screen.getByRole("button", { name: "Unlock selected profile" }));
  await screen.findByRole("alert");
  expect(requests("profile.unlock")).toHaveLength(0); expect(native("initialize_service")).toHaveLength(1);
});
it("rejects incomplete lifecycle capability contracts and inconsistent catalogs", async () => {
  const original = host.invoke.getMockImplementation()!;
  host.invoke.mockImplementation(async (command, args) => command === "core_api_capabilities" ? { ...caps, limits: {} } : original(command, args));
  await expect(supportsProfileLifecycle()).rejects.toMatchObject({ code: "core_api_protocol" });
  expect(() => parseProfileCatalog({ ...catalog(), selected_profile: second })).toThrow("core_api_protocol");
  expect(() => parseProfileCatalog({ ...catalog(), profiles: [...catalog().profiles, catalog().profiles[0]] })).toThrow("core_api_protocol");
});
