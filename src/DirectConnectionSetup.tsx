import { useEffect, useRef, useState } from "react";
import { serviceCommand } from "./api";
import { InvitationImportActions, InvitationQrCode } from "./InvitationTransfer";
import { ConnectionDiagnostics } from "./ConnectionDiagnostics";
import { normalizeInvitationInput } from "./invitation-transfer";
import type { Workspace } from "./types";

type Preview = { kind: "offer" | "answer" | "ready"; workspace_id: string; workspace_name: string; expires_at: number; candidate_count: number };
type Setup = { setup_id: string; state: string; workspace_id: string; expires_at: number; candidate_count: number; text?: string };

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

export function DirectConnectionSetup({ invitationId, workspaceId, autoStart = false, onShared, initialDocument = "", onOpenWorkspace }: {
  invitationId?: string; workspaceId?: string; autoStart?: boolean; onShared?: () => void; initialDocument?: string; onOpenWorkspace?: (workspace: Workspace) => Promise<void>;
}) {
  const [input, setInput] = useState(initialDocument);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [outgoing, setOutgoing] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [now, setNow] = useState(Date.now());
  const started = useRef(false);
  const operation = useRef({ document: "", id: "" });
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (autoStart && invitationId) void offer();
    if (workspaceId) {
      setBusy(true);
      void serviceCommand<Setup>("resume_direct_setup", { workspace_id: workspaceId }).then(value => { setSetup(value); setOutgoing(value.text ?? ""); })
        .catch(() => setError("Could not reopen setup. Paste fresh connection details from the owner below."))
        .finally(() => setBusy(false));
    }
  }, [invitationId, workspaceId, autoStart]);

  useEffect(() => {
    if (!setup?.setup_id || setup.state === "cancelled") return;
    let active = true;
    const timer = setInterval(() => {
      void serviceCommand<Setup>("direct_setup_status", { setup_id: setup.setup_id }).then((value) => {
        if (active) {
          setSetup(value);
          if (value.state === "refresh_required" || value.state === "cancelled" || value.state === "relationship_active") setOutgoing("");
        }
      }).catch(() => { if (active) setError("Connection status is unavailable. Reopen Mesh Chat and refresh the setup details."); });
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
    setBusy(true); setError(""); setFeedback("");
    try {
      const value = await serviceCommand<Setup>("prepare_direct_offer", { invitation_id: invitationId });
      setSetup(value); setOutgoing(value.text ?? "");
    } catch { setError("Could not prepare fresh connection details. Check that this invitation is still active and the app is unlocked."); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!preview) return;
    setBusy(true); setError(""); setFeedback("");
    if (operation.current.document !== input) operation.current = { document: input, id: crypto.randomUUID() };
    try {
      const command = preview.kind === "offer" ? "prepare_direct_answer" : preview.kind === "answer" ? "prepare_direct_ready" : "accept_direct_ready";
      const value = await serviceCommand<Setup>(command, { document: input,
        ...(preview.kind === "offer" ? { operation_id: operation.current.id } : {}) });
      setSetup(value); setOutgoing(value.text ?? ""); setPreview(null);
      if (preview.kind !== "offer") {
        setSetup(await serviceCommand<Setup>("connect_direct_setup", {
          setup_id: value.setup_id, document: preview.kind === "answer" ? value.text : input,
        }));
      }
      setInput("");
    } catch { setError("These details could not start the next step. Your saved request is kept. If either app restarted or the details expired, ask the owner to refresh the connection details."); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    if (setup && setup.expires_at * 1000 <= Date.now()) return;
    try { await navigator.clipboard.writeText(outgoing); onShared?.(); setFeedback("Copied. Send this message to the other device."); }
    catch { setFeedback("Select the complete document below and copy it manually."); }
  };
  const share = async () => {
    if (setup && setup.expires_at * 1000 <= Date.now()) return;
    if (!navigator.share) { await copy(); return; }
    try { await navigator.share({ title: "Mesh Chat connection", text: outgoing }); onShared?.(); setFeedback("Shared. Return to Mesh Chat promptly to keep setup available."); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) await copy(); }
  };
  const save = () => {
    if (setup && setup.expires_at * 1000 <= Date.now()) return;
    const url = URL.createObjectURL(new Blob([outgoing], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "mesh-chat-direct.meshchat-invite"; anchor.click(); onShared?.();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const cancel = async () => {
    if (!setup?.setup_id) return;
    setBusy(true);
    try { await serviceCommand("cancel_direct_setup", { setup_id: setup.setup_id }); setSetup({ ...setup, state: "cancelled" }); setOutgoing(""); }
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

  const remaining = setup ? Math.max(0, Math.ceil((setup.expires_at * 1000 - now) / 1000)) : 0;
  return <section className="form-stack guided-connection" aria-label="Direct connection setup">
    <h3>Connect your devices</h3>
    <p>Send each message using your preferred app. On the receiving device, open <strong>Join or connect</strong> and paste it there. Both apps need to be open while connecting.</p>
    {invitationId && (!setup || !remaining || setup.state === "refresh_required" || setup.state === "cancelled") && <button className="button button--primary" disabled={busy} onClick={() => void offer()}>{setup ? "Refresh connection details" : "Prepare invitation"}</button>}
    <label className="field"><span>Message from the other device</span><textarea aria-label="Message from the other device" rows={5} value={input} onChange={(event) => edit(event.target.value)} disabled={busy} /></label>
    <InvitationImportActions onValue={edit} />
    <button className="button button--secondary" disabled={busy || !input.trim()} onClick={() => void review()}>Check received message</button>
    {preview && <div className="direct-consent"><h4>{preview.workspace_name}</h4><p>Message checked. {preview.kind === "offer" ? "Save your request and prepare a reply for the owner." : preview.kind === "answer" ? "Prepare the final connection message for the other person." : "Both devices need to stay open for this step."}</p><button className="button button--primary" disabled={busy} onClick={() => void apply()}>{preview.kind === "offer" ? "Prepare reply" : preview.kind === "answer" ? "Prepare connection message" : "Connect"}</button></div>}
    {setup && <div role="status"><p>{states[setup.state] ?? "Connection setup is in progress."}</p><p className="muted">Connection details: {remaining ? `${Math.floor(remaining / 60)}m ${remaining % 60}s remaining` : "expired"}. This short setup timer is separate from invitation expiry. Check the workspace for owner receipt and approval.</p></div>}
    {outgoing && remaining > 0 && <><details><summary>Message details and QR code</summary><InvitationQrCode document={outgoing} destination="workspace" /><label className="field"><span>Complete message to share</span><textarea aria-label="Complete connection message" readOnly rows={5} value={outgoing} onFocus={(event) => event.currentTarget.select()} /></label></details><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy()}>Copy connection message</button><button className="button button--secondary" onClick={() => void share()}>Share connection message</button><button className="button button--ghost" onClick={save}>Save connection file</button></div></>}
    {setup?.setup_id && setup.state !== "cancelled" && <button className="button button--ghost" disabled={busy} onClick={() => void cancel()}>Cancel connection attempt</button>}
    {setup && onOpenWorkspace && <button className="button button--secondary" onClick={() => void openWorkspace()}>View workspace</button>}
    {feedback && <p aria-live="polite">{feedback}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <ConnectionDiagnostics />
  </section>;
}
