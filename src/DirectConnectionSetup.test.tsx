import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ serviceCommand: vi.fn() }));
vi.mock("./api", () => api);
vi.mock("./InvitationTransfer", () => ({ InvitationImportActions: () => null, InvitationQrCode: () => <div>Connection QR</div> }));
import { DirectConnectionSetup } from "./DirectConnectionSetup";
const base = { setup_id:"saved", workspace_id:"workspace", expires_at:2_000_000_000, candidate_count:1, state:"waiting_for_reply" };
let current: typeof base & { readiness:string; can_share:boolean; text?:string };
beforeEach(() => {
  api.serviceCommand.mockReset();
  current = { ...base, readiness:"address_prepared", can_share:true, text:"mesh-direct:saved" };
  api.serviceCommand.mockImplementation(async (command) => {
    if (["prepare_direct_offer", "resume_direct_setup", "retry_direct_setup"].includes(command)) return base;
    if (command === "check_direct_setup") return current;
    if (command === "cancel_direct_setup") return {};
    throw new Error("unavailable");
  });
  Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:vi.fn().mockResolvedValue(undefined)}});
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("checks owned readiness before exposing any sharing surface", async () => {
  render(<DirectConnectionSetup invitationId="invite" />);
  expect(screen.queryByText("Copy connection message")).toBeNull();
  fireEvent.click(screen.getByText("Prepare invitation"));
  expect(await screen.findByText(/Address prepared — waiting/)).toBeTruthy();
  expect(api.serviceCommand).toHaveBeenCalledWith("check_direct_setup",{setup_id:"saved"});
  expect(screen.getByText("Connection QR")).toBeTruthy();
  expect(screen.queryByText("Connection verified with the other device")).toBeNull();
  fireEvent.click(screen.getByText("Copy connection message"));
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("mesh-direct:saved"));
});

it.each(["no_route","both_no_address","network_changed","refresh_required","test_failed"])("withholds every export for %s and offers repair", async readiness => {
  current = {...current,readiness,can_share:false};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  expect(await screen.findByText("Retry checks")).toBeTruthy();
  expect(screen.queryByText("Copy connection message")).toBeNull();
  expect(screen.queryByText("Share connection message")).toBeNull();
  expect(screen.queryByText("Save connection file")).toBeNull();
  expect(screen.queryByText("Connection QR")).toBeNull();
  expect(screen.queryByLabelText("Complete connection message")).toBeNull();
  expect(screen.getByText("Copy diagnostics")).toBeTruthy();
});

it("retries the same saved setup after restoring an Internet route", async () => {
  current = {...current,readiness:"no_route",can_share:false};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  await screen.findByText("Retry checks");
  current = {...current,readiness:"address_prepared",can_share:true};
  fireEvent.click(screen.getByText("Retry checks"));
  expect(await screen.findByText("Copy connection message")).toBeTruthy();
  expect(api.serviceCommand).toHaveBeenCalledWith("retry_direct_setup",{setup_id:"saved"});
  expect(api.serviceCommand.mock.calls.some(([c]) => c === "submit_workspace_join" || c === "create_workspace_invitation")).toBe(false);
});

it("allows the unhosted side to reply when the owner has a candidate", async () => {
  current = {...current,state:"waiting_for_ready",readiness:"no_local_address"};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  expect(await screen.findByText("No public address on this device")).toBeTruthy();
  expect(screen.getByText("Copy connection message")).toBeTruthy();
});

it("stops both-empty before connecting or sharing a final message", async () => {
  current = {...current,readiness:"both_no_address",can_share:false};
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base,kind:"offer",workspace_name:"Team"};
    if (command === "prepare_direct_answer") return {...base,text:"private-answer"};
    if (command === "check_direct_setup") return current;
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  expect(await screen.findByText("Neither device has a usable public address")).toBeTruthy();
  expect(api.serviceCommand.mock.calls.some(([c]) => c === "connect_direct_setup")).toBe(false);
  expect(screen.queryByDisplayValue("private-answer")).toBeNull();
});

it("rechecks on copy and rejects a newly lost socket", async () => {
  render(<DirectConnectionSetup workspaceId="workspace" />);
  await screen.findByText("Copy connection message");
  current = {...current,readiness:"refresh_required",can_share:false};
  fireEvent.click(screen.getByText("Copy connection message"));
  await screen.findByText("Retry checks");
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
});

it("offers selectable text on clipboard denial without claiming success", async () => {
  vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error("denied"));
  render(<DirectConnectionSetup workspaceId="workspace" />);
  fireEvent.click(await screen.findByText("Copy connection message"));
  expect(await screen.findByText(/copy it manually/)).toBeTruthy();
  expect(screen.getByLabelText("Complete connection message")).toBeTruthy();
  expect(screen.queryByText(/^Copied/)).toBeNull();
});

it("invalidates sharing when the setup expires", async () => {
  current = {...current,expires_at:1};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  await screen.findByText(/Address prepared — waiting/);
  expect(screen.queryByText("Copy connection message")).toBeNull();
  expect(screen.queryByText("Connection QR")).toBeNull();
});

it("does not attribute a failed test to a firewall", async () => {
  current = {...current,readiness:"test_failed",can_share:false};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  expect(await screen.findByText(/does not prove a firewall or UDP block/)).toBeTruthy();
});

it("shows verification only for current peer evidence and removes it on network change", async () => {
  vi.useFakeTimers();
  current = {...current,readiness:"peer_verified",can_share:false};
  render(<DirectConnectionSetup workspaceId="workspace" />);
  await act(async () => {});
  expect(screen.getByText("Connection verified with the other device")).toBeTruthy();
  current = {...current,readiness:"network_changed"};
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.queryByText("Connection verified with the other device")).toBeNull();
});

it("keeps the operation identifier after losing a reply response", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base,kind:"offer",workspace_name:"Team"};
    throw new Error("timeout");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByText("Prepare reply"));
  await waitFor(() => expect(api.serviceCommand.mock.calls.filter(([c]) => c === "prepare_direct_answer")).toHaveLength(2));
  const calls=api.serviceCommand.mock.calls.filter(([c]) => c === "prepare_direct_answer");
  expect(calls[0][1].operation_id).toBe(calls[1][1].operation_id);
});


it("keeps a retry action when the readiness service becomes unavailable", async () => {
  render(<DirectConnectionSetup workspaceId="workspace" />);
  await screen.findByText("Copy connection message");
  api.serviceCommand.mockRejectedValue(new Error("offline"));
  fireEvent.click(screen.getByText("Copy connection message"));
  expect(await screen.findByText("Retry checks")).toBeTruthy();
  expect(screen.queryByText("Connection QR")).toBeNull();
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
});

it("does not prepare a reply for a different invitation when a workspace is already saved", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base, kind:"offer", workspace_name:"Team",
      existing_workspace:{id:"workspace", name:"Team", state:"joining", can_continue:false, reason:"invitation_mismatch"}};
    throw new Error("prepare must not run");
  });
  const open = vi.fn().mockResolvedValue(undefined);
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" onOpenWorkspace={open} />);
  fireEvent.click(screen.getByText("Check received message"));
  expect(await screen.findByText("Workspace already saved")).toBeTruthy();
  expect(screen.getByText(/These details are for a different invitation/)).toBeTruthy();
  expect(screen.queryByText("Prepare reply")).toBeNull();
  expect(api.serviceCommand.mock.calls.some(([command]) => command === "prepare_direct_answer")).toBe(false);
  api.serviceCommand.mockImplementation(async command => {
    if (command === "workspace_snapshot") return {workspaces:[{id:"workspace", name:"Team"}]};
    throw new Error("unavailable");
  });
  fireEvent.click(screen.getByText("Open saved workspace"));
  await waitFor(() => expect(open).toHaveBeenCalledWith(expect.objectContaining({id:"workspace"})));
});

it("does not prepare a reply for an already active workspace", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base, kind:"offer", workspace_name:"Team",
      existing_workspace:{id:"workspace", name:"Team", state:"active", can_continue:false, reason:"workspace_active"}};
    throw new Error("prepare must not run");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" onOpenWorkspace={vi.fn()} />);
  fireEvent.click(screen.getByText("Check received message"));
  expect(await screen.findByText(/already active on this device/)).toBeTruthy();
  expect(screen.queryByText("Prepare reply")).toBeNull();
  expect(api.serviceCommand.mock.calls.some(([command]) => command === "prepare_direct_answer")).toBe(false);
});

it("allows a fresh reply that reuses a matching saved join request", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base, kind:"offer", workspace_name:"Team",
      existing_workspace:{id:"workspace", name:"Team", state:"joining", can_continue:true, reason:null}};
    if (command === "prepare_direct_answer") return {...base, state:"waiting_for_ready", text:"private-reply"};
    if (command === "check_direct_setup") return current;
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  expect(await screen.findByText(/reuses that request/)).toBeTruthy();
  fireEvent.click(screen.getByText("Prepare reply"));
  await waitFor(() => expect(api.serviceCommand.mock.calls.some(([command]) => command === "prepare_direct_answer")).toBe(true));
});

it("keeps the pasted message and the incoming section open when a saved-workspace refusal is explained", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base, kind:"offer", workspace_name:"Team"};
    if (command === "prepare_direct_answer") throw {code:"workspace_already_known", details:{reason:"invitation_mismatch"}};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/different invitation/);
  expect(alert.textContent).toMatch(/Copy diagnostics/);
  expect(screen.getByDisplayValue("mesh-direct:offer")).toBeTruthy();
  const details = screen.getByText("I have a message from the other device").closest("details");
  expect(details?.open).toBe(true);
});

it("keeps the pasted message when a reply fails before any setup exists", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "preview_direct_connection") return {...base, kind:"offer", workspace_name:"Team"};
    throw new Error("timeout");
  });
  render(<DirectConnectionSetup initialDocument="mesh-direct:offer" />);
  fireEvent.click(screen.getByText("Check received message"));
  fireEvent.click(await screen.findByText("Prepare reply"));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/still here/);
  expect(screen.getByDisplayValue("mesh-direct:offer")).toBeTruthy();
  const details = screen.getByText("I have a message from the other device").closest("details");
  expect(details?.open).toBe(true);
});

it("does not offer a retry that cannot run when resume has no saved setup", async () => {
  api.serviceCommand.mockImplementation(async command => {
    if (command === "resume_direct_setup") return {state:"refresh_required", workspace_id:"workspace",
      expires_at:0, candidate_count:0, reason:"no_saved_connection_details"};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup workspaceId="workspace" />);
  expect(await screen.findByText("Refresh the connection details")).toBeTruthy();
  expect(screen.getByText(/The owner can refresh this same invitation/)).toBeTruthy();
  expect(screen.queryByText("Retry checks")).toBeNull();
});
