import { useEffect, useState } from "react";
import { serviceCommand } from "./api";
import { InvitationImportActions } from "./InvitationTransfer";
import { normalizeInvitationInput } from "./invitation-transfer";
import type { Workspace } from "./types";

type Preview = { kind: "offer" | "answer" | "ready"; workspace_id: string; workspace_name: string; expires_at: number; candidate_count: number };
type Setup = { setup_id: string; state: string; workspace_id: string; expires_at: number; candidate_count: number; text?: string };

const states: Record<string, string> = {
  waiting_for_reply: "Share this offer with the recipient and wait for their reply.",
  waiting_for_ready: "Share this reply with the owner. Keep Mesh Chat open while waiting for their ready document.",
  ready_to_share: "Share this ready document with the recipient while both apps are open.",
  ready_received: "Ready document verified. Start the connection while the owner is online.",
  connecting: "Trying the signed direct paths. Share the ready document now if you created it.",
  bootstrap_connected: "Direct setup path established. The signed join request still needs acknowledgment and owner approval.",
  relationship_active: "Direct setup is complete. Your saved device relationship reconnects automatically. Check Direct connections in workspace settings for current status.",
  admitted_path: "Direct workspace path established with fresh credentials. Workspace delivery and receipts appear in the conversation.",
  existing_routes_only: "Neither device supplied a public direct candidate. The saved join request continues over existing routes, including signed TCP routes. Refresh these details after changing networks.",
  refresh_required: "These connection details can no longer be used. Ask the owner for a fresh offer, then exchange a new reply and ready document.",
  cancelled: "Direct setup cancelled. Your saved workspace request and existing routes remain available.",
};

export function DirectConnectionSetup({ invitationId, initialDocument = "", onOpenWorkspace }: {
  invitationId?: string; initialDocument?: string; onOpenWorkspace?: (workspace: Workspace) => Promise<void>;
}) {
  const [input, setInput] = useState(initialDocument);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [outgoing, setOutgoing] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

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
    } catch { setError("Could not verify these connection details. They may be incomplete, changed or expired. Ask the sender for a fresh document."); }
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
    try {
      const command = preview.kind === "offer" ? "prepare_direct_answer" : preview.kind === "answer" ? "prepare_direct_ready" : "accept_direct_ready";
      const value = await serviceCommand<Setup>(command, { document: input,
        ...(preview.kind === "offer" ? { operation_id: crypto.randomUUID() } : {}) });
      setSetup(value); setOutgoing(value.text ?? ""); setPreview(null);
      if (preview.kind !== "offer") {
        setSetup(await serviceCommand<Setup>("connect_direct_setup", {
          setup_id: value.setup_id, document: preview.kind === "answer" ? value.text : input,
        }));
      }
    } catch { setError("These details could not start the next step. If either app restarted, the network changed or the details expired, exchange a fresh offer and reply."); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(outgoing); setFeedback("Complete connection document copied."); }
    catch { setFeedback("Select the complete document below and copy it manually."); }
  };
  const share = async () => {
    if (!navigator.share) { await copy(); return; }
    try { await navigator.share({ title: "Mesh Chat direct connection", text: outgoing }); setFeedback("Connection document shared."); }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) await copy(); }
  };
  const save = () => {
    const url = URL.createObjectURL(new Blob([outgoing], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "mesh-chat-direct.meshchat-invite"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const cancel = async () => {
    if (!setup) return;
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

  return <section className="form-stack" aria-label="Direct connection setup">
    <h3>Direct connection setup</h3>
    <p>Exchange an offer, reply and ready document by email or file. Keep both apps open and exchange them promptly: setup details last only a few minutes. A phone can create a reply even when it cannot host an inbound connection.</p>
    {invitationId && <button className="button button--secondary" disabled={busy} onClick={() => void offer()}>{setup ? "Refresh direct offer" : "Prepare direct offer"}</button>}
    <label className="field"><span>Received direct connection document</span><textarea aria-label="Received direct connection document" rows={5} value={input} onChange={(event) => edit(event.target.value)} disabled={busy} /></label>
    <InvitationImportActions onValue={edit} />
    <button className="button button--secondary" disabled={busy || !input.trim()} onClick={() => void review()}>Review connection document</button>
    {preview && <div className="direct-consent"><h4>{preview.workspace_name}</h4><p>Verified {preview.kind === "answer" ? "reply" : preview.kind} · expires {new Date(preview.expires_at * 1000).toLocaleTimeString()}. {preview.candidate_count ? "Candidate paths still need a live connection check." : "No public candidate was supplied; a reply can still be created."}</p><button className="button button--primary" disabled={busy} onClick={() => void apply()}>{preview.kind === "offer" ? "Create connection reply" : preview.kind === "answer" ? "Create ready document" : "Use ready document"}</button></div>}
    {setup && <div role="status"><p>{states[setup.state] ?? "Connection setup is in progress."}</p><p className="muted">Setup expiry: {new Date(setup.expires_at * 1000).toLocaleTimeString()}. Workspace approval and receipt status are shown in the workspace.</p></div>}
    {outgoing && <><label className="field"><span>Complete document to share</span><textarea aria-label="Complete direct connection document" readOnly rows={5} value={outgoing} onFocus={(event) => event.currentTarget.select()} /></label><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy()}>Copy connection document</button><button className="button button--secondary" onClick={() => void share()}>Share connection document</button><button className="button button--ghost" onClick={save}>Save connection file</button></div></>}
    {setup && setup.state !== "cancelled" && <button className="button button--ghost" disabled={busy} onClick={() => void cancel()}>Cancel direct setup</button>}
    {setup && onOpenWorkspace && <button className="button button--secondary" onClick={() => void openWorkspace()}>View workspace</button>}
    {feedback && <p aria-live="polite">{feedback}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
