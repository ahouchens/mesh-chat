import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ serviceCommand: vi.fn() }));
vi.mock("./api", () => api);
vi.mock("./InvitationTransfer", () => ({ InvitationImportActions: () => null, InvitationQrCode: () => null }));
import { DirectConnectionSetup } from "./DirectConnectionSetup";

const setup = { setup_id: "opaque-setup", workspace_id: "workspace", expires_at: 2_000_000_000, candidate_count: 0 };
beforeEach(() => { api.serviceCommand.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("authors a reply with no public candidate and does not start a path before Ready", async () => {
  api.serviceCommand.mockImplementation(async (command) => {
    if (command === "preview_direct_connection") return { kind: "offer", workspace_name: "Team", ...setup };
    if (command === "prepare_direct_answer") return { ...setup, state: "waiting_for_ready", text: "mesh-direct:answer" };
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  expect(api.serviceCommand).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  expect(await screen.findByDisplayValue("mesh-direct:answer")).toBeTruthy();
  expect(screen.getByText(/Share this reply with the owner/)).toBeTruthy();
  expect((screen.getByLabelText("Message from the other device") as HTMLTextAreaElement).value).toBe("");
  expect(api.serviceCommand).toHaveBeenCalledWith("prepare_direct_answer", { document: "mesh-direct:offer", operation_id: expect.any(String) });
  expect(api.serviceCommand.mock.calls.some(([command]) => command === "connect_direct_setup" || command === "create_connection_reply")).toBe(false);
});

it("exports Ready before starting its bounded connection attempt", async () => {
  api.serviceCommand.mockImplementation(async (command) => {
    if (command === "preview_direct_connection") return { kind: "answer", workspace_name: "Team", ...setup };
    if (command === "prepare_direct_ready") return { ...setup, state: "ready_to_share", text: "mesh-direct:ready" };
    if (command === "connect_direct_setup") return { ...setup, state: "connecting" };
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:answer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare connection message"));
  await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("connect_direct_setup", { setup_id: setup.setup_id, document: "mesh-direct:ready" }));
  expect(screen.getByDisplayValue("mesh-direct:ready")).toBeTruthy();
  expect(screen.getByText(/Trying to connect/)).toBeTruthy();
});

it("uses retained Answer ownership when importing Ready", async () => {
  api.serviceCommand.mockImplementation(async (command) => {
    if (command === "preview_direct_connection") return { kind: "ready", workspace_name: "Team", ...setup };
    if (command === "accept_direct_ready") return { ...setup, state: "ready_received" };
    if (command === "connect_direct_setup") return { ...setup, state: "existing_routes_only" };
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:ready" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Connect"));
  expect(await screen.findByText(/Neither device found a public address/)).toBeTruthy();
  expect(api.serviceCommand).toHaveBeenCalledWith("accept_direct_ready", { document: "mesh-direct:ready" });
  expect(screen.queryByLabelText("Complete connection message")).toBeNull();
});

it("does not offer an apply action for expired or unverified input", async () => {
  api.serviceCommand.mockRejectedValue(new Error("invalid_request"));
  render(<DirectConnectionSetup initialDocument="mesh-direct:expired" />);
  fireEvent.click(screen.getByText("Check received message"));
  expect((await screen.findByRole("alert")).textContent).toContain("Ask the sender to refresh the connection details");
  expect(screen.queryByText("Prepare reply")).toBeNull();
});

it("invalidates review when the received document changes", async () => {
  api.serviceCommand.mockResolvedValue({ kind: "offer", workspace_name: "Team", ...setup });
  render(<DirectConnectionSetup initialDocument="mesh-direct:one" />);
  fireEvent.click(screen.getByText("Check received message"));
  expect(await screen.findByText("Prepare reply")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Message from the other device"), { target: { value: "mesh-direct:two" } });
  expect(screen.queryByText("Prepare reply")).toBeNull();
});

it("shows socket loss as explicit refresh and cancels the opaque setup", async () => {
  vi.useFakeTimers();
  api.serviceCommand.mockImplementation(async (command) => {
    if (command === "prepare_direct_offer") return { ...setup, state: "waiting_for_reply", text: "mesh-direct:offer" };
    if (command === "direct_setup_status") return { ...setup, state: "refresh_required" };
    return { setup_id: setup.setup_id, state: "cancelled" };
  });
  render(<DirectConnectionSetup invitationId="invite" />);
  await act(async () => { fireEvent.click(screen.getByText("Prepare invitation")); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByText(/These connection details can no longer be used/)).toBeTruthy();
  expect(screen.queryByText("Copy connection message")).toBeNull();
  expect(screen.queryByLabelText("Complete connection message")).toBeNull();
  await act(async () => { fireEvent.click(screen.getByText("Cancel connection attempt")); });
  expect(api.serviceCommand).toHaveBeenCalledWith("cancel_direct_setup", { setup_id: setup.setup_id });
  expect(screen.queryByLabelText("Complete connection message")).toBeNull();
});

it("keeps completed admission separate from expired setup sockets", async () => {
  vi.useFakeTimers();
  api.serviceCommand.mockImplementation(async command => {
    if (command === "prepare_direct_offer") return { ...setup, state: "waiting_for_reply", text: "mesh-direct:offer" };
    return { ...setup, state: "relationship_active" };
  });
  render(<DirectConnectionSetup invitationId="invite" />);
  await act(async () => { fireEvent.click(screen.getByText("Prepare invitation")); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByText(/Your saved device relationship reconnects automatically/)).toBeTruthy();
  expect(screen.queryByText(/Ask the owner for a fresh offer/)).toBeNull();
  expect(screen.queryByLabelText("Complete connection message")).toBeNull();
});

it("reopens a pending request without needing its original clipboard", async () => {
  api.serviceCommand.mockResolvedValue({ ...setup, state:"waiting_for_ready", text:"mesh-direct:saved" });
  render(<DirectConnectionSetup workspaceId="workspace" />);
  expect(await screen.findByDisplayValue("mesh-direct:saved")).toBeTruthy();
  expect(api.serviceCommand).toHaveBeenCalledWith("resume_direct_setup", { workspace_id:"workspace" });
  expect(api.serviceCommand.mock.calls.some(([command]) => command === "submit_workspace_join")).toBe(false);
});

it("keeps the operation identifier when reply creation loses its response", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return { kind:"offer", workspace_name:"Team", ...setup };
    throw new Error("timeout");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByText("Prepare reply"));
  await waitFor(() => expect(api.serviceCommand.mock.calls.filter(([command]) => command === "prepare_direct_answer")).toHaveLength(2));
  const calls = api.serviceCommand.mock.calls.filter(([command]) => command === "prepare_direct_answer");
  expect(calls[0][1].operation_id).toBe(calls[1][1].operation_id);
});
