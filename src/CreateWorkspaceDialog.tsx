import { useState } from "react";
import { ShieldCheck, Users, WifiOff } from "lucide-react";
import { coreApiCreateWorkspace } from "./api";
import type { Workspace } from "./types";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { errorMessage } from "./errors";
import { newOperationId } from "./operationId";

export function CreateWorkspaceDialog({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (workspace: Workspace) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const workspace = await coreApiCreateWorkspace(
        name.trim(), description.trim(), newOperationId()) as unknown as Workspace;
      await onCreated(workspace);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  };
  return <Dialog title="Create a workspace" onClose={onClose}><div className="form-stack workspace-create"><p className="dialog-lead">A private collaboration space for a trusted team.</p><label>Name<input autoFocus value={name} maxLength={64} onChange={(event) => setName(event.target.value)} aria-label="Workspace name" /></label><label>Description <small>Optional</small><textarea value={description} maxLength={250} onChange={(event) => setDescription(event.target.value)} aria-label="Workspace description" /></label><div className="workspace-facts"><p><ShieldCheck size={17} /><span><strong>This device becomes the owner authority.</strong> Link another device and rotate authority before retiring this one.</span></p><p><Users size={17} /><span>Every public message is encrypted separately for each member device.</span></p><p><WifiOff size={17} /><span>Delivery and history depend on reachable peers; there is no hosted workspace server.</span></p></div>{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !name.trim()} onClick={() => void create()}>{busy ? "Creating…" : "Create workspace"}</Button></div></div></Dialog>;
}
