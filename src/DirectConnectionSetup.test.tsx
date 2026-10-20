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

it("shows the reachability plan and installs the UDP firewall rule on request", async () => {
  const plan = {state:"needs_action", candidate_count:1, blockers:[],
    steps:[
      {id:"pcp",label:"PCP",state:"prepared",reason:"mapping_prepared"},
      {id:"firewall",label:"Windows firewall",state:"needs_consent",reason:"firewall_permission_required"},
    ],
    primary_action:{kind:"allow_firewall",label:"Allow UDP in Windows Firewall"},
    manual_forward:{local_host:"192.168.1.20",local_port:54321}};
  api.serviceCommand.mockImplementation(async command => {
    if (command === "prepare_direct_offer") return {...base, reachability:plan};
    if (command === "check_direct_setup") return {...base, reachability:plan,
      readiness:"address_prepared", can_share:true, text:"mesh-direct:offer"};
    if (command === "configure_direct_firewall") return {state:"prepared"};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup invitationId="invite" autoStart />);
  expect(await screen.findByText("Allow UDP in Windows Firewall")).toBeTruthy();
  expect(screen.getByText("PCP")).toBeTruthy();
  fireEvent.click(screen.getByText("Allow UDP in Windows Firewall"));
  await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith(
    "configure_direct_firewall", {setup_id:"saved"}));
});

it("does not offer a manual forward or restore-Internet advice for carrier NAT", async () => {
  const plan = {state:"blocked", candidate_count:0, blockers:["carrier_nat"],
    upstream_nat:{state:"carrier_nat",port_forward:"no",reason:"upnp_wan_shared"},
    steps:[
      {id:"manual",label:"Manual UDP forward",state:"unavailable",reason:"upstream_nat"},
      {id:"upstream_nat",label:"Upstream NAT",state:"blocked",reason:"upnp_wan_shared"},
    ],
    primary_action:{kind:"change_network",label:"Try another network, IPv6, or an approved access point"},
    manual_forward:{local_host:"192.168.4.20",local_port:54321}};
  api.serviceCommand.mockImplementation(async command => {
    if (command === "prepare_direct_offer") return {...base, reachability:plan};
    if (command === "check_direct_setup") return {...base, reachability:plan,
      readiness:"both_no_address", can_share:false};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup invitationId="invite" autoStart />);
  expect(await screen.findByText("A local forward cannot bypass carrier or upstream NAT.")).toBeTruthy();
  expect(screen.getByText("Carrier-grade NAT")).toBeTruthy();
  expect(screen.getByText("UDP port forward: Not possible")).toBeTruthy();
  expect(screen.getAllByText(/This network is behind carrier NAT/).length).toBeGreaterThan(0);
  expect(screen.queryByText("Set up manual UDP forward")).toBeNull();
  expect(screen.queryByText(/Restore this device’s Internet connection/)).toBeNull();
});

it("offers a manual forward with both routers when double NAT is detected", async () => {
  const plan = {state:"needs_action", candidate_count:0, blockers:["double_nat"],
    upstream_nat:{state:"double_nat",port_forward:"maybe",reason:"upnp_wan_private"},
    steps:[
      {id:"manual",label:"Manual UDP forward",state:"not_tried",reason:"manual_forward_available"},
      {id:"upstream_nat",label:"Upstream NAT",state:"blocked",reason:"upnp_wan_private"},
    ],
    primary_action:{kind:"manual_forward",label:"Set up manual UDP forward (both routers)"},
    manual_forward:{local_host:"192.168.4.20",local_port:54321}};
  api.serviceCommand.mockImplementation(async command => {
    if (command === "prepare_direct_offer") return {...base, reachability:plan};
    if (command === "check_direct_setup") return {...base, reachability:plan,
      readiness:"both_no_address", can_share:false};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup invitationId="invite" autoStart />);
  expect(await screen.findByText("Double NAT")).toBeTruthy();
  expect(screen.getByText("UDP port forward: Maybe")).toBeTruthy();
  expect(screen.getByText("Set up manual UDP forward (both routers)")).toBeTruthy();
});

it("prepares a manual UDP forward with the entered public address and port", async () => {
  const blocked = {state:"blocked", candidate_count:0, blockers:["no_public_candidate"],
    steps:[
      {id:"pcp",label:"PCP",state:"failed",reason:"pcp_no_response"},
      {id:"manual",label:"Manual UDP forward",state:"not_tried",reason:"manual_forward_available"},
    ],
    primary_action:{kind:"manual_forward",label:"Set up manual UDP forward"},
    manual_forward:{local_host:"192.168.1.20",local_port:54321}};
  const prepared = {...blocked, state:"prepared", candidate_count:1, blockers:[],
    primary_action:null,
    steps:[{id:"manual",label:"Manual UDP forward",state:"prepared",reason:"manual_forward_configured"}],
    manual_forward:{local_host:"192.168.1.20",local_port:54321,
      external_host:"93.184.216.34",external_port:55000}};
  let calls = 0;
  let currentPlan: any = blocked;
  api.serviceCommand.mockImplementation(async command => {
    if (command === "prepare_direct_offer") { calls += 1; currentPlan = calls === 1 ? blocked : prepared; return {...base, reachability:currentPlan, text:"mesh-direct:manual"}; }
    if (command === "check_direct_setup") return {...base, reachability:currentPlan,
      readiness:currentPlan.state === "blocked" ? "both_no_address" : "address_prepared",
      can_share:currentPlan.state !== "blocked", text:"mesh-direct:manual"};
    throw new Error("unavailable");
  });
  render(<DirectConnectionSetup invitationId="invite" autoStart />);
  fireEvent.click(await screen.findByText("Set up manual UDP forward"));
  expect(screen.getByText("The router did not answer PCP.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Router public IP address"), {target:{value:"93.184.216.34"}});
  fireEvent.change(screen.getByLabelText("External UDP port"), {target:{value:"55000"}});
  fireEvent.click(screen.getByText("Use manual forward"));
  await waitFor(() => expect(api.serviceCommand).toHaveBeenCalledWith("prepare_direct_offer", {
    invitation_id:"invite", manual_host:"93.184.216.34", manual_port:55000}));
});
