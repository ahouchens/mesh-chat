import { useEffect, useRef, useState } from "react";
import { serviceCommand } from "./api";
import { InvitationImportActions, InvitationQrCode } from "./InvitationTransfer";
import { ConnectionDiagnostics } from "./ConnectionDiagnostics";
import { normalizeInvitationInput } from "./invitation-transfer";
import type { Workspace } from "./types";
type Preview = { kind: "offer" | "answer" | "ready"; workspace_id: string; workspace_name: string; expires_at: number; candidate_count: number };
type Setup = { setup_id: string; state: string; workspace_id: string; expires_at: number; candidate_count: number; text?: string; readiness?: string; can_share?: boolean; route?: string; socket?: string; mapping?: string; firewall?: string; peer_candidate_count?: number | null; peer_verified?: boolean; candidate_sources?: { ipv4?: number; ipv6?: number } };
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
  const edit = (value: string) => { setInput(value); setPreview(null); setError(""); setFeedback(""); };
  const review = async () => {
    setBusy(true); setError("");
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
    if (!preview) return;
    revision.current++; setBusy(true); setError(""); setFeedback("");
    if (operation.current.document !== input) operation.current = { document: input, id: crypto.randomUUID() };
    try {
      const command = preview.kind === "offer" ? "prepare_direct_answer" : preview.kind === "answer" ? "prepare_direct_ready" : "accept_direct_ready";
      const value = await serviceCommand<Setup>(command, { document: input,
        ...(preview.kind === "offer" ? { operation_id: operation.current.id } : {}) });
      const readiness = await check(value); setBack(false); setPreview(null);
      if (preview.kind !== "offer" && !["both_no_address", "no_route", "network_changed", "refresh_required"].includes(readiness.readiness ?? "")) {
        await check(await serviceCommand<Setup>("connect_direct_setup", {
          setup_id: value.setup_id, document: preview.kind === "answer" ? value.text : input,
        }));
      }
      setInput("");
    } catch { setError("These details could not start the next step. Your saved request is kept. If either app restarted or the details expired, ask the owner to refresh the connection details."); }
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
  const openWorkspace = async () => {
    if (!setup || !onOpenWorkspace) return;
    try {
      const snapshot = await serviceCommand<{ workspaces: Workspace[] }>("workspace_snapshot", {});
      const workspace = snapshot.workspaces.find((item) => item.id === setup.workspace_id);
      if (workspace) await onOpenWorkspace(workspace);
    } catch { setError("Could not open the workspace. Close this dialog and open it from the workspace list."); }
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
  const remaining = setup ? Math.max(0, Math.ceil((setup.expires_at * 1000 - now) / 1000)) : 0;
  return <section className="form-stack guided-connection" aria-label="Direct connection setup">
    <h3>Connect your devices</h3>
    <p>Check this device before sharing. Keep both Mesh Chat apps open.</p>
    <p aria-label="Connection progress">Step {step} of 3: {step === 1 ? "Check this device" : step === 2 ? "Exchange messages" : "Test connection"}</p>
    {readiness && guidance[readiness] && <div className="direct-consent" role="status"><h4>{guidance[readiness][0]}</h4><p>{guidance[readiness][1]}</p>
      <details><summary>What was checked</summary>
      {setup?.socket === "retained" && !setup.peer_verified && <p className="muted">UDP socket retained. Address candidates: IPv4 {setup.candidate_sources?.ipv4 ?? 0}; IPv6 {setup.candidate_sources?.ipv6 ?? 0}. These are candidates, not a successful peer test.</p>}
      {setup?.mapping === "unavailable" && <p>The router did not provide a usable UDP mapping. This alone does not prove that incoming connections are blocked.</p>}
      {setup?.firewall && <p className="muted">UDP firewall permission has not been verified. {setup.firewall === "windows_profile_unavailable_udp_unverified" ? "Windows did not report an active Internet network profile. Check Windows network settings." : "The existing automatic firewall helper supports TCP only; it cannot approve this QUIC connection."}</p>}
      </details>
    </div>}
    {canExport && remaining > 0 && <><p>On the other device, open <strong>Join or connect</strong>, paste this message and follow its next step. {setup?.state === "waiting_for_reply" || setup?.state === "waiting_for_ready" ? "Bring its reply back here." : "Choose Connect there and keep both apps open; no further reply is needed."}</p><details><summary>Message details and QR code</summary><InvitationQrCode document={outgoing} destination="workspace" /><label className="field"><span>Complete message to share</span><textarea aria-label="Complete connection message" onCopy={(event) => { if (!canExport || !setup || setup.expires_at * 1000 <= Date.now()) event.preventDefault(); else onShared?.(); }} readOnly rows={5} value={outgoing} onFocus={(event) => event.currentTarget.select()} /></label></details><div className="dialog-actions"><button className={preview ? "button button--secondary" : "button button--primary"} onClick={() => void copy()}>Copy connection message</button><button className="button button--secondary" onClick={() => void share()}>Share connection message</button><button className="button button--ghost" onClick={() => void save()}>Save connection file</button></div></>}
    {setup && ["checks_unavailable", "no_route", "both_no_address", "network_changed", "refresh_required", "test_failed"].includes(readiness ?? "") && <>
      <button className="button button--primary" disabled={busy} onClick={() => void retry()}>Retry checks</button>
      <details><summary>Other ways to proceed</summary><p>Try the other device as the reachable side, or recheck after changing one device’s Internet connection. You can keep Windows on the home router and Android on mobile data.</p><p>If you manage the home router, check whether it allows app-requested UDP mappings (PCP, UPnP or NAT-PMP), then retry. Optional manual router configuration requires a usable public address and the exact app-owned UDP endpoint; this wizard does not currently provide a manual UDP mapping editor. A carrier or upstream router may prevent inbound connections. Some networks cannot connect without a helper service, which this server-free mode does not use.</p><p>Keep the firewall enabled. This wizard has no supported automatic UDP firewall repair action. A TCP permission or mapping is not proof for this connection.</p></details>
    </>}
    <ConnectionDiagnostics />
    {invitationId && (!setup?.setup_id || setup.state === "cancelled") && <button className="button button--primary" disabled={busy} onClick={() => void offer()}>{setup ? "Refresh connection details" : "Prepare invitation"}</button>}
    <details open={!canExport || !!preview}><summary>I have a message from the other device</summary>
    <label className="field"><span>Message from the other device</span><textarea aria-label="Message from the other device" rows={5} value={input} onChange={(event) => edit(event.target.value)} disabled={busy} /></label>
    <InvitationImportActions onValue={edit} />
    <button className="button button--secondary" disabled={busy || !input.trim()} onClick={() => void review()}>Check received message</button>
    {preview && <div className="direct-consent"><h4>{preview.workspace_name}</h4><p>Message checked. {preview.kind === "offer" ? "Save your request and prepare a reply for the owner." : preview.kind === "answer" ? "Prepare the final connection message for the other person." : "Both devices need to stay open for this step."}</p><button className="button button--primary" disabled={busy} onClick={() => void apply()}>{preview.kind === "offer" ? "Prepare reply" : preview.kind === "answer" ? "Prepare connection message" : "Connect"}</button></div>}
    </details>
    {setup && <div><p>{!setup.readiness ? states[setup.state] ?? "Connection setup is in progress." : ""}</p><p className="muted">Connection details: {remaining ? `${Math.floor(remaining / 60)}m ${remaining % 60}s remaining` : "expired"}. This short setup timer is separate from invitation expiry. Check the workspace for owner receipt and approval.</p></div>}

    {setup?.setup_id && setup.state !== "cancelled" && <button className="button button--ghost" disabled={busy} onClick={() => void cancel()}>Cancel connection attempt</button>}
    {setup && onOpenWorkspace && <button className="button button--secondary" onClick={() => void openWorkspace()}>View workspace</button>}
    {feedback && <p aria-live="polite">{feedback}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {setup && <button className="button button--ghost" disabled={busy} onClick={() => { setBack(!back); setPreview(null); }}>{back ? "Return to connection steps" : "Back"}</button>}
  </section>;
}
