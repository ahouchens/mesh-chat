import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ serviceCommand: vi.fn() }));
vi.mock("./api", () => api);
import { DirectRecovery } from "./DirectRecovery";
const peer = { relationship_id: "opaque-peer", workspace_id: "workspace", peer_device_id: "device1234",
  state: "connection_update_needed", native_engine_healthy: false, authenticated_peer_live: false, rns_ready: false };
beforeEach(() => { api.serviceCommand.mockReset(); });
afterEach(cleanup);
it("separates engine, peer and RNS evidence and filters the selected workspace", async () => {
  api.serviceCommand.mockResolvedValue([peer, { ...peer, relationship_id: "other", workspace_id: "elsewhere" }]);
  render(<DirectRecovery workspaceId="workspace" />);
  expect(await screen.findByText("Connection update needed")).toBeTruthy();
  expect(screen.getAllByText("Share connection update")).toHaveLength(1);
  expect(screen.getByText(/Authenticated peer: not confirmed/)).toBeTruthy();
  expect(screen.getByText(/Message receipts remain in the conversation/)).toBeTruthy();
});
it("imports only an opaque update bound to the selected workspace", async () => {
  api.serviceCommand.mockImplementation(async command => command === "direct_recovery_status" ? [peer] : {});
  render(<DirectRecovery workspaceId="workspace" />);
  fireEvent.change(screen.getByLabelText("Received connection update"), { target: { value: "mesh-recover:opaque" } });
  fireEvent.click(screen.getByText("Apply connection update"));
  await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("import_recovery_update", { document: "mesh-recover:opaque", workspace_id: "workspace" }));
  expect(await screen.findByText(/Connection update verified/)).toBeTruthy();
  expect(api.serviceCommand.mock.calls.some(([name]) => name.includes("invitation"))).toBe(false);
});
it("does not export stale saved details while fresh ownership is being prepared", async () => {
  api.serviceCommand.mockImplementation(async command => command === "direct_recovery_status" ? [peer] : { state: "preparing", text: null });
  render(<DirectRecovery workspaceId="workspace" />);
  fireEvent.click(await screen.findByText("Share connection update"));
  expect(await screen.findByText(/Preparing fresh connection details/)).toBeTruthy();
  expect(screen.queryByLabelText("Complete connection update to share")).toBeNull();
});
it("reports verification failure without claiming recovery", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "direct_recovery_status") return [peer];
    throw new Error("wrong audience");
  });
  render(<DirectRecovery workspaceId="workspace" />);
  fireEvent.change(screen.getByLabelText("Received connection update"), { target: { value: "wrong" } });
  fireEvent.click(screen.getByText("Apply connection update"));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be verified");
  expect(screen.queryByText(/Connection update verified/)).toBeNull();
});
it("can resume a paused durable relationship without another invitation", async () => {
  api.serviceCommand.mockImplementation(async command => command === "direct_recovery_status" ? [{ ...peer, state: "dormant" }] : { state: "reconnecting" });
  render(<DirectRecovery workspaceId="workspace" />);
  fireEvent.click(await screen.findByText("Resume direct recovery"));
  await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("resume_direct_recovery", { identifier: "opaque-peer" }));
});
