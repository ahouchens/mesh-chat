import { useEffect, useRef, useState } from "react";
import { serviceCommand } from "./api";
import { InvitationImportActions, InvitationQrCode } from "./InvitationTransfer";
import { ConnectionDiagnostics } from "./ConnectionDiagnostics";
import { normalizeInvitationInput } from "./invitation-transfer";
import type { Workspace } from "./types";
type ExistingWorkspace = { id: string; name: string; state: string; can_continue: boolean; reason: string | null };
type ReachabilityStep = { id: string; label: string; state: string; reason?: string | null };
type Reachability = {
  state: "prepared" | "needs_action" | "blocked";
  steps: ReachabilityStep[];
  candidate_count: number;
  candidate_sources?: Record<string, number>;
  primary_action?: { kind: string; label: string } | null;
  blockers: string[];
  upstream_nat?: { state: string; port_forward: string; reason?: string | null } | null;
  manual_forward?: { local_host?: string | null; local_port?: number | null; external_host?: string | null; external_port?: number | null } | null;
};
type Preview = { kind: "offer" | "answer" | "ready"; workspace_id: string; workspace_name: string; expires_at: number; candidate_count: number; existing_workspace?: ExistingWorkspace | null };
type Setup = { setup_id: string; state: string; workspace_id: string; expires_at: number; candidate_count: number; text?: string; readiness?: string; can_share?: boolean; route?: string; socket?: string; mapping?: string; firewall?: string; peer_candidate_count?: number | null; peer_verified?: boolean; candidate_sources?: { ipv4?: number; ipv6?: number }; reachability?: Reachability | null };
const states: Record<string, string> = {
  waiting_for_reply: "Send this invitation to the other person. Next, they open Join or connect and send a reply back to you.",
  waiting_for_ready: "Share this reply with the owner. Next, the owner opens Join or connect and sends you the final connection message.",
  ready_to_share: "Send this connection message to the other person now. Next, they paste it into Join or connect and choose Connect.",
  ready_received: "Connection message checked. Both devices need to stay open while connecting.",
  connecting: "Trying to connect. Keep both apps open. Send the connection message below to the other person now if you created it.",
  bootstrap_connected: "The devices are connected. Waiting for the owner to receive and approve your request. Check the workspace for progress.",
  relationship_active: "Direct setup is complete. Your saved device relationship reconnects automatically. Check Direct connections in workspace settings for current status.",
  admitted_path: "Your workspace connection is ready. Open the workspace to send a message and check its delivery status.",
  existing_routes_only: "Neither device found a public address it can share. This connection cannot start on the current networks. Your request stays saved and can use an existing authorized route. Waiting or copying these details again will not discover an address.",
  refresh_required: "These connection details can no longer be used. Ask the owner to refresh their saved invitation and send it through Join or connect. Your saved request is kept.",
  cancelled: "Connection attempt cancelled. Your saved request is kept; a request already received by the owner is not withdrawn.",
};
const failureGuidance: Record<string, string> = {
  invitation_expired: "These connection details have expired. Ask the sender to refresh them and send the complete message.",
  invitation_invalid: "These connection details could not be verified. Ask the sender to send the complete message again.",
  identity_mismatch: "The identity check failed. Confirm that the sender shared this message for this device.",
  workspace_already_known: "This workspace is already saved on this device. Open it from the workspace list to check its status.",
  workspace_limit_reached: "This device has reached its workspace limit. Remove a workspace you have left or closed before joining another.",
  protected_storage_unavailable: "Protected storage is unavailable. Unlock this device and Mesh Chat, then try again.",
  profile_in_use: "This profile is already in use. Close its other Mesh Chat session, then try again.",
  network_unavailable: "The network is unavailable. Check this device’s Internet connection, then try again.",
  native_unavailable: "The on-device connection service stopped responding. Close and reopen Mesh Chat, then try again. Your saved request and messages are unchanged.",
};
const savedWorkspaceReason: Record<string, string> = {
  invitation_mismatch: "These details are for a different invitation. Your saved join request stays tied to the original invitation. Ask the owner to choose Refresh connection details for that original invitation, or open the saved workspace.",
  request_stopped: "The saved join request has stopped. Open the saved workspace to review its status before starting again.",
  request_expired: "The saved join request’s delivery window has expired. Open the saved workspace to review it.",
  identity_mismatch: "The saved join request belongs to a different local device identity, so it cannot be reused. Open the saved workspace to review it.",
  saved_request_invalid: "The saved join request could not be verified. Open the saved workspace to review it.",
  workspace_active: "This workspace is already active on this device. Open it to continue.",
  workspace_not_pending: "This workspace is saved but is not waiting for a join reply. Open it to check its status.",
};
function savedWorkspaceDetail(existing: ExistingWorkspace) {
  return savedWorkspaceReason[existing.reason ?? ""] ?? "This invitation cannot reuse the saved join request. Open the saved workspace to review it.";
}
const reachabilityState: Record<string, string> = {
  prepared: "Ready", verified: "Verified", unavailable: "Not available", failed: "Failed",
  needs_consent: "Needs permission", not_tried: "Not tried", skipped: "Skipped", blocked: "Blocked",
};
const reachabilityReason: Record<string, string> = {
  ipv6_candidate_prepared: "A global IPv6 address is ready.",
  no_route: "No Internet route was found on this device.",
  no_eligible_route: "No usable Internet interface was found.",
  no_global_ipv6_address: "No global IPv6 address is available.",
  ipv6_pinhole_prepared: "A temporary IPv6 pinhole was prepared.",
  ipv6_pinhole_unavailable: "The router did not provide an IPv6 pinhole. A host firewall may still block traffic.",
  public_ipv4_prepared: "A directly assigned public IPv4 address is ready.",
  no_public_ipv4: "No directly assigned public IPv4 address is available.",
  mapping_prepared: "The router created a temporary UDP mapping.",
  mapping_not_attempted: "An earlier method succeeded, so this one was not needed.",
  pcp_no_response: "The router did not answer PCP.",
  pcp_mapping_denied: "The router refused the PCP mapping.",
  upnp_no_discovery: "No UPnP router was found.",
  upnp_mapping_denied: "The router refused the UPnP mapping.",
  upnp_unsupported_lease: "The router refused the requested mapping lifetime.",
  upnp_wan_private: "The router reports a private upstream address.",
  upnp_wan_shared: "The router is behind carrier or shared NAT.",
  upstream_nat_detected: "The router is behind another NAT or carrier NAT.",
  nat_pmp_no_response: "The router did not answer NAT-PMP.",
  nat_pmp_mapping_denied: "The router refused the NAT-PMP mapping.",
  manual_forward_configured: "A manual UDP forward was added to the signed message.",
  upstream_nat: "A local forward cannot bypass carrier or upstream NAT.",
  upstream_nat_unknown: "The upstream router did not identify its WAN address. Check it before forwarding.",
  manual_forward_available: "You can forward one UDP port on your router.",
  firewall_permission_required: "Windows may block inbound UDP until you allow it.",
  temporary_udp_rule_active: "A temporary Windows UDP rule is active.",
  windows_firewall_blocked: "Windows did not report an active firewall profile.",
  firewall_check_unsupported: "This platform does not expose automated firewall control.",
  no_prepared_candidate: "No address is ready yet.",
  firewall_not_checked: "The host firewall was not checked.",
  no_public_candidate: "No public address or router mapping was found.",
};
const blockerText: Record<string, string> = {
  no_route: "This device has no Internet route. Restore Wi-Fi or mobile data, then retry.",
  no_eligible_route: "This device has no usable Internet interface for a direct connection.",
  carrier_nat: "The router is behind carrier-grade NAT. A local port forward cannot make this device reachable. Ask the ISP for a public IPv4 address or IPv6, or use an approved access point.",
  double_nat: "The router is behind another router (double NAT). A UDP forward can work only if you control the upstream router: forward the port on both routers, or put the inner router in bridge/AP mode.",
  upstream_nat: "The router is behind an upstream NAT that did not identify itself. Check its WAN address: 100.64.x.x means carrier NAT; a private address means double NAT.",
  no_public_candidate: "This device could not prepare a public address or router mapping. You can try a manual UDP forward or the other device as host.",
};
const upstreamNatLabel: Record<string, string> = {
  carrier_nat: "Carrier-grade NAT",
  double_nat: "Double NAT",
  unknown: "Upstream NAT",
  none: "No upstream NAT",
};
const portForwardLabel: Record<string, string> = {
  no: "Not possible",
  maybe: "Maybe",
  yes: "Likely",
  unknown: "Unknown",
  not_needed: "Not needed",
};
const upstreamNatText: Record<string, string> = {
  carrier_nat: "The router's WAN address is in the carrier-shared range. You cannot forward a UDP port through it. Ask the ISP for a public IPv4 address or IPv6, or use an approved access point.",
  double_nat: "The router is behind another router. A UDP forward can work only if you control the upstream router: forward the port on both routers, or put the inner router in bridge/AP mode.",
  unknown: "The upstream router did not report a usable WAN address. Check its status page: 100.64.x.x means carrier NAT; a private address means double NAT.",
  none: "No upstream NAT was detected. A manual UDP forward may work if the router's WAN address is public and you can reach its port-forwarding page.",
};
function actionFailure(action: string, reason: unknown, retryAction: string) {
  const value = reason !== null && typeof reason === "object" ? reason as Record<string, unknown> : {};
  const code = typeof value.code === "string" ? value.code : "";
  const details = value.details !== null && typeof value.details === "object" ? value.details as Record<string, unknown> : {};
  const guidance = Object.hasOwn(failureGuidance, code) ? failureGuidance[code] : `Your pasted message is still here. Try ${retryAction} again.`;
  const saved = code === "workspace_already_known" && typeof details.reason === "string" && Object.hasOwn(savedWorkspaceReason, details.reason)
    ? ` ${savedWorkspaceReason[details.reason]}` : "";
  return `Could not ${action}. ${guidance}${saved} If it fails again, use Copy diagnostics.`;
}
export function DirectConnectionSetup({ invitationId, workspaceId, autoStart = false, resumeExisting = false, onShared, initialDocument = "", onOpenWorkspace }: {
  invitationId?: string; workspaceId?: string; autoStart?: boolean; resumeExisting?: boolean; onShared?: () => void; initialDocument?: string; onOpenWorkspace?: (workspace: Workspace) => Promise<void>;
}) {
  const [input, setInput] = useState(initialDocument);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [outgoing, setOutgoing] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [back, setBack] = useState(false);
  const [incomingOpen, setIncomingOpen] = useState(true);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualHost, setManualHost] = useState("");
  const [manualPort, setManualPort] = useState("");
  const [checkedAt, setCheckedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const started = useRef(false);
  const revision = useRef(0);
  const operation = useRef({ document: "", id: "" });
  const check = async (value: Setup) => {
    setSetup(value); setOutgoing(""); setCheckedAt(0);
    try {
      const current = await serviceCommand<Setup>("check_direct_setup", { setup_id: value.setup_id });
      if (!current?.readiness) throw new Error("Readiness unavailable");
      setSetup(current); setOutgoing(current.can_share ? current.text ?? "" : ""); setCheckedAt(Date.now());
      return current;
    } catch (reason) {
      setSetup({ ...value, readiness:"checks_unavailable", can_share:false });
      throw reason;
    }
  };
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (autoStart && invitationId) void offer();
    if (workspaceId || (invitationId && resumeExisting)) {
      setBusy(true);
      void serviceCommand<Setup>("resume_direct_setup", invitationId ? { invitation_id: invitationId } : { workspace_id: workspaceId }).then(async value => { if (value.setup_id) await check(value); else setSetup({ ...value, readiness:"refresh_required", can_share:false }); })
        .catch(() => setError("Could not reopen setup. Paste fresh connection details from the owner below."))
        .finally(() => setBusy(false));
    }
  }, [invitationId, workspaceId, autoStart, resumeExisting]);
  useEffect(() => {
    if (!setup?.setup_id || setup.state === "cancelled") return;
    let active = true;
    const timer = setInterval(() => {
      const epoch = revision.current;
      void serviceCommand<Setup>("check_direct_setup", { setup_id: setup.setup_id }).then((value) => {
        if (active && epoch === revision.current) {
          setSetup(value); setOutgoing(value.can_share ? value.text ?? "" : ""); setCheckedAt(Date.now());
        }
      }).catch(() => { if (active && epoch === revision.current) { setOutgoing(""); setCheckedAt(0); setSetup(previous => previous ? { ...previous, readiness:"checks_unavailable", can_share:false } : previous); setError("Checks are unavailable. Retry checks before sharing."); } });
    }, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [setup?.setup_id, setup?.state === "cancelled"]);
  const edit = (value: string) => { setInput(value); setPreview(null); setIncomingOpen(true); setError(""); setFeedback(""); };
  const review = async () => {
    setBusy(true); setError(""); setIncomingOpen(true);
    try {
      const document = await normalizeInvitationInput(input);
      const checked = await serviceCommand<Preview>("preview_direct_connection", { document });
      setInput(document); setPreview(checked);
    } catch { setError("Could not verify these connection details. They may be incomplete, changed or expired. Ask the sender to refresh the connection details and send the complete message."); }
    finally { setBusy(false); }
  };
  const offer = async () => {
    if (!invitationId) return;
    revision.current++; setBusy(true); setError(""); setFeedback("");
    try {
      const value = await serviceCommand<Setup>("prepare_direct_offer", { invitation_id: invitationId });
      await check(value); setBack(false);
    } catch { setError("Could not prepare fresh connection details. Check that this invitation is still active and the app is unlocked."); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!preview || (preview.existing_workspace && !preview.existing_workspace.can_continue)) return;
    revision.current++; setBusy(true); setError(""); setFeedback(""); setIncomingOpen(true);
    if (operation.current.document !== input) operation.current = { document: input, id: crypto.randomUUID() };
    const retryAction = preview.kind === "offer" ? "Prepare reply" : preview.kind === "answer" ? "Prepare connection message" : "Connect";
    let action = preview.kind === "offer" ? "prepare your reply" : preview.kind === "answer" ? "prepare the final connection message" : "accept the final connection message";
    try {
      const command = preview.kind === "offer" ? "prepare_direct_answer" : preview.kind === "answer" ? "prepare_direct_ready" : "accept_direct_ready";
      const value = await serviceCommand<Setup>(command, { document: input,
        ...(preview.kind === "offer" ? { operation_id: operation.current.id } : {}) });
      action = "check this device before connecting or sharing";
      const readiness = await check(value); setBack(false);
      if (preview.kind !== "offer" && !["both_no_address", "no_route", "network_changed", "refresh_required"].includes(readiness.readiness ?? "")) {
        action = "connect the devices";
        const connected = await serviceCommand<Setup>("connect_direct_setup", {
          setup_id: value.setup_id, document: preview.kind === "answer" ? value.text : input,
        });
        action = "check this device after starting the connection";
        await check(connected);
      }
      setInput(""); setPreview(null); setIncomingOpen(false);
    } catch (reason) { setIncomingOpen(true); setError(actionFailure(action, reason, retryAction)); }
    finally { setBusy(false); }
  };
  const exportText = async () => {
    if (!setup || busy || back || setup.expires_at * 1000 <= Date.now()) return "";
    try { const current = await check(setup); return current.can_share ? current.text ?? "" : ""; }
    catch { setOutgoing(""); setError("Could not recheck these details. Retry checks before sharing."); return ""; }
  };
  const copy = async () => {
    const text = await exportText(); if (!text) return;
    try { await navigator.clipboard.writeText(text); onShared?.(); setFeedback("Copied. Send this message to the other device."); }
    catch { setFeedback("Select the complete document below and copy it manually."); }
  };
  const share = async () => {
    const text = await exportText(); if (!text) return;
    if (!navigator.share) { await copy(); return; }
    try { await navigator.share({ title: "Mesh Chat connection", text }); onShared?.(); setFeedback("Shared. Return to Mesh Chat promptly to keep setup available."); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) await copy(); }
  };
  const save = async () => {
    const text = await exportText(); if (!text) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "mesh-chat-direct.meshchat-invite"; anchor.click(); onShared?.();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const cancel = async () => {
    if (!setup?.setup_id) return;
    setBusy(true);
    try { await serviceCommand("cancel_direct_setup", { setup_id: setup.setup_id }); setSetup({ ...setup, state: "cancelled", readiness:"cancelled", can_share:false }); setOutgoing(""); }
    catch { setError("Could not cancel setup. Lock the app to retire its active connections."); }
    finally { setBusy(false); }
  };
  const allowFirewall = async () => {
    if (!setup?.setup_id) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      await serviceCommand("configure_direct_firewall", { setup_id: setup.setup_id });
      await check(setup);
      setFeedback("Windows firewall permission recorded for this temporary setup.");
    } catch (reason) { setError(actionFailure("allow UDP through Windows Firewall", reason, "Allow UDP in Windows Firewall")); }
    finally { setBusy(false); }
  };
  const prepareManual = async () => {
    const host = manualHost.trim();
    const port = Number(manualPort);
    if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
      setError("Enter the router’s public IP address and a UDP port from 1 to 65535."); return;
    }
    setBusy(true); setError(""); setFeedback("");
    try {
      let value: Setup;
      if (invitationId) {
        value = await serviceCommand<Setup>("prepare_direct_offer", {
          invitation_id: invitationId, manual_host: host, manual_port: port });
      } else if (preview?.kind === "offer") {
        if (operation.current.document !== input) operation.current = { document: input, id: crypto.randomUUID() };
        value = await serviceCommand<Setup>("prepare_direct_answer", {
          document: input, operation_id: operation.current.id, manual_host: host, manual_port: port });
      } else { setError("Check the received message before setting a manual forward."); return; }
      revision.current++;
      const current = await check(value); setBack(false); setPreview(null); setInput(""); setIncomingOpen(false);
      setManualOpen(false);
      const forward = current.reachability?.manual_forward;
      setFeedback(forward?.local_host && forward.local_port
        ? `Manual UDP forward prepared. Forward UDP ${forward.external_port ?? port} to ${forward.local_host}:${forward.local_port} on this device, then send the new message.`
        : "Manual UDP forward prepared. Configure your router with the local address and port in the plan above, then send the new message.");
    } catch (reason) { setError(actionFailure("prepare the manual UDP forward", reason, "Use manual forward")); }
    finally { setBusy(false); }
  };
  const openWorkspaceById = async (workspaceId: string) => {
    if (!onOpenWorkspace) return;
    try {
      const snapshot = await serviceCommand<{ workspaces: Workspace[] }>("workspace_snapshot", {});
      const workspace = snapshot.workspaces.find((item) => item.id === workspaceId);
      if (workspace) await onOpenWorkspace(workspace);
    } catch { setError("Could not open the workspace. Close this dialog and open it from the workspace list."); }
  };
  const openWorkspace = async () => {
    if (!setup) return;
    await openWorkspaceById(setup.workspace_id);
  };
  const retry = async () => {
    if (!setup?.setup_id) return;
    revision.current++; setBusy(true); setError(""); setOutgoing(""); setBack(false);
    try { await check(await serviceCommand<Setup>("retry_direct_setup", { setup_id: setup.setup_id })); }
    catch { setError("Could not refresh this saved exchange. Ask the owner to refresh the same invitation and paste it here. Your join request stays saved."); }
    finally { setBusy(false); }
  };
  const readiness = busy ? "checking" : setup?.readiness;
  const guidance: Record<string, [string, string]> = {
    checking: ["Checking this device", "Preparing the app’s UDP socket and checking local addresses and router mappings. This does not yet test the other device."],
    checks_unavailable: ["Checks are unavailable", "Keep the app unlocked and retry checks. No connection details are ready to share until these checks succeed."],
    no_route: ["Connect this device to the Internet", "No current Internet route was found. On Windows, restore the home-router connection. On Android, keep Wi-Fi off and restore mobile data. Then retry checks."],
    address_prepared: ["Address prepared — waiting for the other device’s test", "A public address is prepared, but it has not been tested by the other device. Send the message below to start that test."],
    no_local_address: ["No public address on this device", "The other device may still provide a usable address. Send the message below so it can check its own network."],
    both_no_address: ["Neither device has a usable public address", "Automatic setup cannot connect these networks with the evidence available. Your request stays saved. Change one device’s network or review the optional router help, then retry. Copying again or waiting will not discover an address."],
    network_changed: ["The network changed", "The old connection details are no longer ready to share. Retry checks on this device, then exchange the refreshed message using the same invitation."],
    refresh_required: ["Refresh the connection details", "The socket or setup time is no longer valid. The owner can refresh this same invitation. Your saved request is kept."],
    test_failed: ["The connection test did not succeed", "The intended peer did not establish a current connection. This does not prove a firewall or UDP block. Keep both apps open, check the other device’s diagnostics, and retry after a network or router change."],
    testing: ["Testing with the other device", "Keep both apps open. If this device has a message below, send it to the other device so it can connect. Receipt and workspace approval are separate steps."],
    peer_verified: ["Connection verified with the other device", "The current socket has an authenticated connection to the intended peer. Check the workspace for receipt and owner approval."],
    complete: ["Setup completed", "Open the workspace to check the current connection and message delivery. A completed setup is not a claim that the device is reachable now."],
    cancelled: ["Setup cancelled", "Your saved join request is kept."],
  };
  const step = back ? 1 : readiness === "peer_verified" || readiness === "complete" || readiness === "testing" ? 3 : setup?.can_share ? 2 : 1;
  const canExport = !!outgoing && !!setup?.can_share && !busy && !back && checkedAt > 0 && now - checkedAt < 5000;
  const upstream = setup?.reachability?.upstream_nat ?? null;
  const carrierNat = upstream?.state === "carrier_nat";
  const showUpstream = !!upstream && (upstream.state !== "none" || upstream.port_forward === "maybe");
  const canManualForward = (!!invitationId || preview?.kind === "offer") && !carrierNat;
  const remaining = setup ? Math.max(0, Math.ceil((setup.expires_at * 1000 - now) / 1000)) : 0;
  return <section className="form-stack guided-connection" aria-label="Direct connection setup">
    <h3>Connect your devices</h3>
    <p>Make this device reachable before sharing. Keep both Mesh Chat apps open.</p>
    <p aria-label="Connection progress">Step {step} of 3: {step === 1 ? "Make this device reachable" : step === 2 ? "Exchange messages" : "Test connection"}</p>
    {readiness && guidance[readiness] && <div className="direct-consent" role="status"><h4>{guidance[readiness][0]}</h4><p>{guidance[readiness][1]}</p>
      <details><summary>What was checked</summary>
      {setup?.socket === "retained" && !setup.peer_verified && <p className="muted">UDP socket retained. Address candidates: IPv4 {setup.candidate_sources?.ipv4 ?? 0}; IPv6 {setup.candidate_sources?.ipv6 ?? 0}. These are candidates, not a successful peer test.</p>}
      {setup?.mapping === "unavailable" && <p>The router did not provide a usable UDP mapping. This alone does not prove that incoming connections are blocked.</p>}
      {setup?.firewall && <p className="muted">UDP firewall permission is not confirmed. {setup.firewall === "windows_profile_unavailable_udp_unverified" ? "Windows did not report an active Internet network profile. Check Windows network settings." : "If Windows blocks inbound UDP, use Allow UDP in Windows Firewall above."}</p>}
      </details>
    </div>}
    {setup?.reachability && <section className="direct-consent" aria-label="Reachability plan" role="status">
      <h4>{setup.reachability.state === "prepared" ? "This device is ready to share" : setup.reachability.state === "needs_action" ? "One local action is needed" : "No reachable address on this device"}</h4>
      <ul className="reachability-list">
        {setup.reachability.steps.map(step => <li key={step.id}><span>{step.label}</span><strong>{reachabilityState[step.state] ?? step.state}</strong>{step.reason && <small>{reachabilityReason[step.reason] ?? step.reason}</small>}</li>)}
      </ul>
      {setup.reachability.blockers.map(blocker => <p className="reachability-blocker" key={blocker}>{blockerText[blocker] ?? "This network cannot supply a reachable address."}</p>)}
      {upstream && showUpstream && <div className={`upstream-nat-card upstream-nat-card--${upstream.state}`}>
        <div className="upstream-nat-card__head"><strong>{upstreamNatLabel[upstream.state] ?? "Upstream NAT"}</strong><span>UDP port forward: {portForwardLabel[upstream.port_forward] ?? upstream.port_forward}</span></div>
        <p>{upstreamNatText[upstream.state] ?? upstreamNatText.unknown}</p>
      </div>}
      {setup.reachability.primary_action?.kind === "allow_firewall" && <button className="button button--primary" disabled={busy} onClick={() => void allowFirewall()}>{setup.reachability.primary_action.label}</button>}
      {setup.reachability.primary_action?.kind === "manual_forward" && canManualForward && <button className="button button--secondary" disabled={busy} onClick={() => setManualOpen(true)}>{setup.reachability.primary_action.label}</button>}
      {setup.reachability.primary_action?.kind === "change_network" && <p className="muted">{carrierNat ? "This network is behind carrier NAT. A local mapping cannot make this device reachable. Use IPv6, another network, or an approved access point." : "Restore this device’s Internet connection, then retry checks."}</p>}
    </section>}
    {manualOpen && canManualForward && <form className="direct-consent" onSubmit={(event) => { event.preventDefault(); void prepareManual(); }}>
      <h4>Manual UDP forward</h4>
      <p>Mesh Chat will bind one UDP port and show it next. Then forward that local port on your router and enter the router’s public IP address and the external port here. Use a numeric public IP; hostnames are not supported for UDP.</p>
      <label className="field"><span>Router public IP address</span><input value={manualHost} onChange={(event) => setManualHost(event.target.value)} placeholder="203.0.113.7" autoComplete="off" disabled={busy} /></label>
      <label className="field"><span>External UDP port</span><input inputMode="numeric" value={manualPort} onChange={(event) => setManualPort(event.target.value)} placeholder="54321" disabled={busy} /></label>
      <div className="dialog-actions"><button className="button button--primary" type="submit" disabled={busy}>Use manual forward</button><button className="button button--ghost" type="button" disabled={busy} onClick={() => setManualOpen(false)}>Cancel</button></div>
    </form>}
    {canExport && remaining > 0 && <><p>On the other device, open <strong>Join or connect</strong>, paste this message and follow its next step. {setup?.state === "waiting_for_reply" || setup?.state === "waiting_for_ready" ? "Bring its reply back here." : "Choose Connect there and keep both apps open; no further reply is needed."}</p><details><summary>Message details and QR code</summary><InvitationQrCode document={outgoing} destination="workspace" /><label className="field"><span>Complete message to share</span><textarea aria-label="Complete connection message" onCopy={(event) => { if (!canExport || !setup || setup.expires_at * 1000 <= Date.now()) event.preventDefault(); else onShared?.(); }} readOnly rows={5} value={outgoing} onFocus={(event) => event.currentTarget.select()} /></label></details><div className="dialog-actions"><button className={preview ? "button button--secondary" : "button button--primary"} onClick={() => void copy()}>Copy connection message</button><button className="button button--secondary" onClick={() => void share()}>Share connection message</button><button className="button button--ghost" onClick={() => void save()}>Save connection file</button></div></>}
    {setup?.setup_id && ["checks_unavailable", "no_route", "both_no_address", "network_changed", "refresh_required", "test_failed"].includes(readiness ?? "") && <>
      <button className="button button--primary" disabled={busy} onClick={() => void retry()}>Retry checks</button>
      <details><summary>Other ways to proceed</summary><p>{carrierNat ? "This Windows network cannot accept an inbound path. The other device may still work as host if it has a public IPv6 or a different network; a carrier-only phone usually cannot." : "Try the other device as the reachable side, or recheck after changing one device’s Internet connection. You can keep Windows on the home router and Android on mobile data."}</p><p>{carrierNat ? "This network is behind carrier NAT. A local mapping or manual forward will not help. Try IPv6, another network, or an approved access point." : "If you manage the home router, use Set up manual UDP forward above when automatic PCP, UPnP, or NAT-PMP is unavailable. A carrier or upstream router may prevent inbound connections. Some networks cannot connect without a helper service, which this server-free mode does not use."}</p><p>Keep the firewall enabled. On Windows, allow UDP for this temporary setup; a TCP permission or mapping is not proof for this connection.</p></details>
      {canManualForward && setup.reachability?.primary_action?.kind !== "manual_forward" && <button className="button button--secondary" disabled={busy} onClick={() => setManualOpen(true)}>Set up manual UDP forward</button>}
    </>}
    <ConnectionDiagnostics />
    {invitationId && (!setup?.setup_id || setup.state === "cancelled") && <button className="button button--primary" disabled={busy} onClick={() => void offer()}>{setup ? "Refresh connection details" : "Prepare invitation"}</button>}
    <details open={incomingOpen} onToggle={event => setIncomingOpen(event.currentTarget.open)}><summary>I have a message from the other device</summary>
    <label className="field"><span>Message from the other device</span><textarea aria-label="Message from the other device" rows={5} value={input} onChange={(event) => edit(event.target.value)} disabled={busy} /></label>
    <InvitationImportActions onValue={edit} />
    <button className="button button--secondary" disabled={busy || !input.trim()} onClick={() => void review()}>Check received message</button>
    {preview && (preview.existing_workspace ? <div className="direct-consent" role="status">
      <h4>Workspace already saved</h4>
      <p><strong>{preview.existing_workspace.name}</strong> is already saved on this device.</p>
      {preview.existing_workspace.can_continue
        ? <p>These details match the saved join request. Preparing the reply reuses that request; Mesh Chat will not replace it.</p>
        : <p>{savedWorkspaceDetail(preview.existing_workspace)}</p>}
      <div className="dialog-actions">
        {preview.existing_workspace.can_continue && <button className="button button--primary" disabled={busy} onClick={() => void apply()}>{preview.kind === "offer" ? "Prepare reply" : preview.kind === "answer" ? "Prepare connection message" : "Connect"}</button>}
        {onOpenWorkspace && <button className="button button--secondary" disabled={busy} onClick={() => void openWorkspaceById(preview.existing_workspace!.id)}>Open saved workspace</button>}
      </div>
      {!preview.existing_workspace.can_continue && preview.existing_workspace.reason !== "workspace_active" && <p className="muted">To use a different invitation, open the saved workspace and remove its saved request in Workspace settings first. Mesh Chat will not replace it automatically.</p>}
    </div> : <div className="direct-consent"><h4>{preview.workspace_name}</h4><p>Message checked. {preview.kind === "offer" ? "Save your request and prepare a reply for the owner." : preview.kind === "answer" ? "Prepare the final connection message for the other person." : "Both devices need to stay open for this step."}</p><button className="button button--primary" disabled={busy} onClick={() => void apply()}>{preview.kind === "offer" ? "Prepare reply" : preview.kind === "answer" ? "Prepare connection message" : "Connect"}</button></div>)}
    </details>
    {setup && <div><p>{!setup.readiness ? states[setup.state] ?? "Connection setup is in progress." : ""}</p><p className="muted">Connection details: {remaining ? `${Math.floor(remaining / 60)}m ${remaining % 60}s remaining` : "expired"}. This short setup timer is separate from invitation expiry. Check the workspace for owner receipt and approval.</p></div>}

    {setup?.setup_id && setup.state !== "cancelled" && <button className="button button--ghost" disabled={busy} onClick={() => void cancel()}>Cancel connection attempt</button>}
    {setup && onOpenWorkspace && <button className="button button--secondary" onClick={() => void openWorkspace()}>View workspace</button>}
    {feedback && <p aria-live="polite">{feedback}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {setup && <button className="button button--ghost" disabled={busy} onClick={() => { setBack(!back); setPreview(null); }}>{back ? "Return to connection steps" : "Back"}</button>}
  </section>;
}
