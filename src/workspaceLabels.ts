import { workspaceJoinStatus } from "./status";
import type { Workspace } from "./types";

export function workspaceConnectivityLabel(state: string): string {
  return ({
    local: "This device",
    reachable: "Path known",
    recently_reached: "Recently reached",
    store_and_forward: "Stored for delivery",
    queued: "Queued · no path",
    unreachable: "Unreachable",
    unknown: "No path yet",
  } as Record<string, string>)[state] ?? state;
}

export function workspaceStateLabel(workspace: Workspace): string {
  const joinStatus = workspaceJoinStatus(workspace);
  if (joinStatus) return joinStatus.headline;
  switch (workspace.state) {
    case "linking": return "Waiting for device approval";
    case "leaving": return "Leave request pending";
    case "left": return "Left workspace";
    case "removed": return "Membership removed";
    case "device_removed": return "This device was removed";
    case "closed": return "Closed · read-only";
    case "forked": return "Paused for a security conflict";
    case "incomplete_sync": return "Incomplete sync";
    default: return "Active";
  }
}

export function workspaceSyncIssueLabel(workspace: Workspace): string {
  if (!workspace.sync_issue) return "";
  if (workspace.sync_issue === "queue_pressure") {
    return "Sync paused because the protected pending queue is full. Keep Mesh Chat open and review workspace diagnostics.";
  }
  return "Waiting for signed controls or an earlier event. Keep Mesh Chat open so an authorized peer can complete synchronization.";
}

