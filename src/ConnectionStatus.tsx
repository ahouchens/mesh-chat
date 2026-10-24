import { useEffect, useId, useState } from "react";
import { ChevronRight, QrCode } from "lucide-react";
import { lastWebRTCDiagnostics } from "./webrtc-diagnostics";
import type { WebRTCSessionPath } from "./webrtc-session";
import "./connection-status.css";

export function ConnectionStatus({ count, path, pendingCount, onReview, onReconnect, onDisconnect }: {
  count: number;
  path: WebRTCSessionPath;
  pendingCount: number;
  onReview: () => void;
  onReconnect: () => Promise<void>;
  onDisconnect: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(pendingCount > 0);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const detailsId = useId();
  useEffect(() => { if (pendingCount > 0) setExpanded(true); }, [pendingCount]);
  const copyDiagnostics = async () => {
    const diagnostics = lastWebRTCDiagnostics();
    if (!diagnostics) { setFeedback("No diagnostics available yet."); return; }
    try {
      await navigator.clipboard.writeText(diagnostics);
      setFeedback("Diagnostics copied.");
    } catch {
      setFeedback("Could not copy diagnostics. Try again.");
    }
  };
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setFeedback("");
    try { await action(); }
    catch { setFeedback("Could not finish the connection action. Try again."); }
    finally { setBusy(false); }
  };
  return <section className="connection-status" aria-label="Connection status">
    <button type="button" className="connection-status__summary" aria-expanded={expanded} aria-controls={detailsId}
      onClick={() => setExpanded(!expanded)}>
      <QrCode size={17} aria-hidden="true" />
      <strong>{count > 1 ? `${count} paths connected` : "Connected"} · {path === "relayed" ? "Relayed" : path === "direct" ? "Direct" : "Path pending"}</strong>
      <span>Details</span><ChevronRight size={17} className={expanded ? "connection-status__chevron--open" : ""} aria-hidden="true" />
    </button>
    {pendingCount > 0 && <div className="connection-status__pending"><p role="status">{pendingCount} contact {pendingCount === 1 ? "request" : "requests"} awaiting approval.</p><button type="button" className="button button--secondary" onClick={onReview}>Review request</button></div>}
    <div id={detailsId} className="connection-status__details" hidden={!expanded}>
      <p>WebRTC DataChannel open. Message delivery is confirmed by receipts.</p>
      <div className="connection-status__actions">
        <button type="button" className="button button--secondary" onClick={() => void copyDiagnostics()}>Copy diagnostics</button>
        <button type="button" className="button button--secondary" disabled={busy} onClick={() => void run(onReconnect)}>Reconnect</button>
        <button type="button" className="button button--secondary" disabled={busy} onClick={() => void run(onDisconnect)}>Disconnect</button>
      </div>
      <p className="connection-status__feedback" role="status">{feedback}</p>
    </div>
  </section>;
}
