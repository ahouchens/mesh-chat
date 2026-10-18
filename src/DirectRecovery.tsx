import { useEffect, useState } from "react";
import { serviceCommand } from "./api";

type Peer = { relationship_id: string; workspace_id: string; peer_device_id: string; state: string;
  native_engine_healthy: boolean; authenticated_peer_live: boolean; rns_ready: boolean };
const labels: Record<string, string> = {
  connected: "Direct path connected", reconnecting: "Reconnecting",
  connection_update_needed: "Connection update needed", dormant: "Direct recovery paused",
  authorization_unavailable: "This device relationship is no longer authorized",
};
export function DirectRecovery({ workspaceId }: { workspaceId: string }) {
  const [peers, setPeers] = useState<Peer[]>([]);
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => void serviceCommand<Peer[]>("direct_recovery_status", {}).then(rows => {
      if (active) setPeers(rows.filter(row => row.workspace_id === workspaceId));
    }).catch(() => { if (active) setError("Direct connection status is unavailable."); });
    refresh(); const timer = setInterval(refresh, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [workspaceId]);
  const action = async (command: string, identifier: string) => {
    setBusy(true); setError(""); setOutput("");
    try {
      const result = await serviceCommand<{ state: string; text?: string }>(command, { identifier });
      if (result.text) setOutput(result.text);
      setFeedback(result.state === "preparing" ? "Preparing fresh connection details. Choose Share connection update again when ready. Keep both apps open." : "Connection action saved.");
    } catch { setError("Could not update this connection. Check that the workspace and device are still active."); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true); setError("");
    try {
      await serviceCommand("import_recovery_update", { document: input.trim(), workspace_id: workspaceId });
      setInput(""); setFeedback("Connection update verified. Reconnection keeps your existing membership and queued messages.");
    } catch { setError("This update could not be verified. It may be expired, replayed, or intended for another device."); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(output); setFeedback("Complete connection update copied. Send it to this device's owner."); }
    catch { setFeedback("Select and copy the complete update below."); }
  };
  return <section className="form-stack" aria-label="Direct connection recovery">
    <h3>Direct connections</h3>
    <p>Membership and queued messages survive disconnection. If both known addresses stop working, exchange fresh connection updates while both apps are open. No new invitation is needed.</p>
    {peers.map(peer => <div key={peer.relationship_id}>
      <p>Device {peer.peer_device_id.slice(0, 8)} · <strong>{labels[peer.state] ?? "Connection unavailable"}</strong></p>
      <p className="muted">Native engine: {peer.native_engine_healthy ? "responding" : "not confirmed"} · Authenticated peer: {peer.authenticated_peer_live ? "recently seen" : "not confirmed"} · RNS: {peer.rns_ready ? "ready" : "waiting"}. Message receipts remain in the conversation.</p>
      <div className="dialog-actions"><button disabled={busy} onClick={() => void action("export_recovery_update", peer.relationship_id)}>Share connection update</button>
      <button disabled={busy} onClick={() => void action(peer.state === "dormant" ? "resume_direct_recovery" : "pause_direct_recovery", peer.relationship_id)}>{peer.state === "dormant" ? "Resume direct recovery" : "Pause direct recovery"}</button></div>
    </div>)}
    {!peers.length && <p>No saved direct device relationships in this workspace.</p>}
    <label>Received connection update<textarea aria-label="Received connection update" value={input} onChange={event => setInput(event.target.value)} rows={4} maxLength={24576} /></label>
    <button disabled={busy || !input.trim()} onClick={() => void apply()}>Apply connection update</button>
    {output && <><label>Complete connection update to share<textarea aria-label="Complete connection update to share" readOnly value={output} rows={4} onFocus={event => event.target.select()} /></label><button onClick={() => void copy()}>Copy connection update</button></>}
    {feedback && <p role="status">{feedback}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
