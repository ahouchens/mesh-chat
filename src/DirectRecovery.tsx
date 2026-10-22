import { useEffect, useState } from "react";
import { ConnectionDiagnostics } from "./ConnectionDiagnostics";
import { serviceCommand } from "./api";

type Peer = { relationship_id: string; workspace_id: string; peer_device_id: string; state: string;
  native_engine_healthy: boolean; authenticated_peer_live: boolean; rns_ready: boolean };
type Helper = { id: string; label: string };
type Connectivity = {
  members: Array<{
    display_name: string;
    devices: Array<{ id: string; display_name: string; is_local: boolean }>;
  }>;
};
const labels: Record<string, string> = {
  connected: "Direct path connected", reconnecting: "Reconnecting",
  connection_update_needed: "Connection update needed", dormant: "Direct path dormant",
  authorization_unavailable: "This device relationship is no longer authorized",
};
export function DirectRecovery({ workspaceId }: { workspaceId: string }) {
  const [peers, setPeers] = useState<Peer[]>([]);
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [helpers, setHelpers] = useState<Helper[]>([]);
  const [helperId, setHelperId] = useState("");
  const [helperEnabled, setHelperEnabled] = useState(false);
  const [helperBusy, setHelperBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => void serviceCommand<Peer[]>("direct_recovery_status", {}).then(rows => {
      if (active) setPeers(rows.filter(row => row.workspace_id === workspaceId));
    }).catch(() => { if (active) setError("Direct connection status is unavailable."); });
    refresh(); const timer = setInterval(refresh, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [workspaceId]);
  useEffect(() => {
    let active = true;
    void Promise.all([
      serviceCommand<Connectivity>("workspace_connectivity", { workspace_id: workspaceId }),
      serviceCommand<{ enabled: boolean }>("workspace_helper_status", { workspace_id: workspaceId }),
    ]).then(([connectivity, status]) => {
      if (!active) return;
      const available = connectivity.members.flatMap((member) =>
        member.devices
          .filter((device) => !device.is_local)
          .map((device) => ({ id: device.id, label: `${member.display_name} · ${device.display_name}` })),
      );
      setHelpers(available);
      setHelperId((current) => current || available[0]?.id || "");
      setHelperEnabled(Boolean(status.enabled));
    }).catch(() => {
      // Helper relay is optional; leave the manual copy/import path usable.
    });
    return () => { active = false; };
  }, [workspaceId]);
  const setHelperConsent = async (enabled: boolean) => {
    setHelperBusy(true); setError("");
    try {
      const value = await serviceCommand<{ enabled: boolean }>("workspace_helper_consent_set", { workspace_id: workspaceId, enabled });
      setHelperEnabled(Boolean(value.enabled));
      setFeedback(enabled ? "This device will relay one-hop connection updates for active workspace members." : "Connection-update relaying is off.");
    } catch { setError("Could not save connection-helper consent."); }
    finally { setHelperBusy(false); }
  };
  const relay = async (relationshipId: string) => {
    if (!helperId) return;
    setBusy(true); setError(""); setOutput(""); setFeedback("");
    try {
      await serviceCommand("relay_workspace_connection_update", { workspace_id: workspaceId, relationship_id: relationshipId, helper_device_id: helperId });
      setFeedback("Connection update queued through the selected workspace helper.");
    } catch { setError("Could not queue this connection update through the helper."); }
    finally { setBusy(false); }
  };
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
    <div className="workspace-name-request"><h3>One-hop helper relay</h3><p className="muted">A reachable workspace member can carry one signed connection update to this device. Helpers see connection endpoints and timing, never chat, history, receipts, or membership. Relaying is off by default and never changes authority.</p><label className="checkbox-line"><input type="checkbox" checked={helperEnabled} disabled={helperBusy} onChange={(event) => void setHelperConsent(event.target.checked)} /> Allow this device to relay one-hop connection updates for active workspace members</label>{helpers.length > 0 && <label>Helper for my connection updates<select value={helperId} onChange={(event) => setHelperId(event.target.value)}>{helpers.map((helper) => <option key={helper.id} value={helper.id}>{helper.label}</option>)}</select></label>}</div>
    {peers.map(peer => <div key={peer.relationship_id}>
      <p>Device {peer.peer_device_id.slice(0, 8)} · <strong>{labels[peer.state] ?? "Connection unavailable"}</strong></p>
      <p className="muted">Native engine: {peer.native_engine_healthy ? "responding" : "not confirmed"} · Authenticated peer: {peer.authenticated_peer_live ? "recently seen" : "not confirmed"} · RNS: {peer.rns_ready ? "ready" : "waiting"}. Message receipts remain in the conversation.</p>
      <div className="dialog-actions"><button disabled={busy} onClick={() => void action("export_recovery_update", peer.relationship_id)}>Share connection update</button>
      <button disabled={busy || !helperId} onClick={() => void relay(peer.relationship_id)}>Send via helper</button>
      <button disabled={busy} onClick={() => void action(peer.state === "dormant" ? "resume_direct_recovery" : "pause_direct_recovery", peer.relationship_id)}>{peer.state === "dormant" ? "Resume direct recovery" : "Pause direct recovery"}</button></div>
    </div>)}
    {!peers.length && <p>No saved direct device relationships in this workspace.</p>}
    <label>Received connection update<textarea aria-label="Received connection update" value={input} onChange={event => setInput(event.target.value)} rows={4} maxLength={16384} /></label>
    <button disabled={busy || !input.trim()} onClick={() => void apply()}>Apply connection update</button>
    {output && <><label>Complete connection update to share<textarea aria-label="Complete connection update to share" readOnly value={output} rows={4} onFocus={(event) => event.currentTarget.select()} /></label><button onClick={() => void copy()}>Copy connection update</button></>}
    {feedback && <p role="status">{feedback}</p>}{error && <p role="alert">{error}</p>}
    <ConnectionDiagnostics />
  </section>;
}
