import { useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { callRecovery, type CallOperation } from "./call-operation";

export function CallRecoveryNotice() {
  const sessions = useSyncExternalStore(callRecovery.subscribe, callRecovery.getSnapshot, callRecovery.getSnapshot);
  if (!sessions.length) return null;
  return createPortal(<div className="call-cleanup-notice">{sessions.map((session, index) => <PendingCleanup key={index} session={session} />)}</div>, document.body);
}

function PendingCleanup({ session }: { session: CallOperation }) {
  const view = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  return <aside role="status" className="incoming-call-banner">
    <p>Finishing the previous call with {session.name}. Your microphone and camera are off.</p>
    {view.errorCode === "resync_required" && <p>The call runtime changed. Cleanup is not confirmed; the previous operation is kept for review.</p>}
    {view.uncertain && <button type="button" disabled={view.busy} onClick={() => { void session.retry(); }}>Retry call cleanup</button>}
  </aside>;
}
