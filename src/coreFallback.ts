import {
  coreApiCallMedia,
  coreApiRuntimeMutate,
  coreApiRuntimeQuery,
  coreApiTimelineMutation,
  coreApiTimelineQuery,
  coreApiWorkspaceAccessRecommendation,
  coreApiWorkspaceConnection,
  coreApiWorkspaceHistory,
  coreApiWorkspaceSnapshot,
  serviceCommand,
} from "./api";
import type {
  BackgroundAvailability,
  CallMedia,
  NotificationOpenTarget,
  WorkspaceNotificationState,
  WorkspaceSnapshot,
} from "./types";

// Reuse the renderer's operation-id shape without coupling this module to App.
function operationId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function fetchCallMedia(
  call: { id: string; core_handle?: string } | undefined,
  callId = call?.id,
): Promise<CallMedia> {
  if (call?.core_handle) {
    try {
      return await coreApiCallMedia(call.core_handle) as unknown as CallMedia;
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  if (!callId) throw new Error("call_not_found");
  return serviceCommand<CallMedia>("call_media", { call_id: callId });
}

export async function fetchWorkspaceTimeline(
  workspace: { id: string; core_handle?: string },
  view: "threads" | "thread_messages" | "mentions" | "search",
  params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (workspace.core_handle) {
    try {
      return await coreApiTimelineQuery(workspace.core_handle, view, params);
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  const command = view === "threads" ? "list_workspace_threads"
    : view === "thread_messages" ? "list_workspace_thread_messages"
    : view === "mentions" ? "list_workspace_mentions" : "search_workspace";
  return serviceCommand<Record<string, unknown>>(command, { workspace_id: workspace.id, ...params });
}

export async function mutateWorkspaceTimeline(
  workspace: { id: string; core_handle?: string },
  action: "thread_reply" | "thread_read" | "mentions_read" | "notification_preference",
  params: Record<string, unknown>,
  fallbackCommand: string,
): Promise<Record<string, unknown>> {
  if (workspace.core_handle) {
    try {
      return await coreApiTimelineMutation(workspace.core_handle, action, params, operationId());
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  return serviceCommand<Record<string, unknown>>(fallbackCommand, { workspace_id: workspace.id, operation_id: operationId(), ...params });
}

export async function loadWorkspaceSnapshot(): Promise<WorkspaceSnapshot> {
  try {
    return await coreApiWorkspaceSnapshot() as unknown as WorkspaceSnapshot;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<WorkspaceSnapshot>("workspace_snapshot");
}

export async function fetchWorkspaceAccessRecommendation(
  workspace: { id: string; core_handle?: string },
  action: string,
  params: Record<string, unknown>,
  fallbackCommand: string,
  key?: string,
): Promise<Record<string, unknown>> {
  if (workspace.core_handle) {
    try {
      return await coreApiWorkspaceAccessRecommendation(workspace.core_handle, action as never, params, key);
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  return serviceCommand<Record<string, unknown>>(fallbackCommand,
    { workspace_id: workspace.id, ...params, ...(key ? { operation_id: key } : {}) });
}

export async function fetchWorkspaceHistory(
  workspace: { id: string; core_handle?: string },
  action: string,
  params: Record<string, unknown>,
  fallbackCommand: string,
  key?: string,
): Promise<Record<string, unknown>> {
  if (workspace.core_handle) {
    try {
      return await coreApiWorkspaceHistory(workspace.core_handle, action as never, params, key);
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  return serviceCommand<Record<string, unknown>>(fallbackCommand,
    { workspace_id: workspace.id, ...params, ...(key ? { operation_id: key } : {}) });
}

export async function fetchWorkspaceConnection(
  workspace: { id: string; core_handle?: string } | null,
  action: string,
  params: Record<string, unknown>,
  fallbackCommand: string,
  key?: string,
): Promise<Record<string, unknown>> {
  if (workspace?.core_handle || !workspace) {
    try {
      return await coreApiWorkspaceConnection(workspace?.core_handle ?? null, action, params, key);
    } catch (reason) {
      if (!String(reason).includes("core_api_unavailable")) throw reason;
    }
  }
  return serviceCommand<Record<string, unknown>>(fallbackCommand,
    { ...(workspace ? { workspace_id: workspace.id } : {}), ...params,
      ...(key ? { operation_id: key } : {}) });
}

export async function fetchBackgroundStatus(): Promise<BackgroundAvailability> {
  try {
    return await coreApiRuntimeQuery("background") as unknown as BackgroundAvailability;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<BackgroundAvailability>("background_status");
}

export async function setBackgroundAvailability(enabled: boolean): Promise<BackgroundAvailability> {
  try {
    return await coreApiRuntimeMutate("background_set", { enabled }, operationId()) as unknown as BackgroundAvailability;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<BackgroundAvailability>("set_background_availability", { enabled });
}

export async function fetchNotificationState(): Promise<WorkspaceNotificationState> {
  try {
    return await coreApiRuntimeQuery("notifications") as unknown as WorkspaceNotificationState;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<WorkspaceNotificationState>("get_notification_state");
}

export async function setNotificationPreviews(hidden: boolean): Promise<WorkspaceNotificationState> {
  try {
    return await coreApiRuntimeMutate("notification_previews", { hidden }, operationId()) as unknown as WorkspaceNotificationState;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<WorkspaceNotificationState>("set_hide_notification_previews", { hidden, operation_id: operationId() });
}

export async function openNotificationTarget(notificationId: string): Promise<NotificationOpenTarget> {
  try {
    return await coreApiRuntimeMutate("notification_open", { notification_id: notificationId }, operationId()) as unknown as NotificationOpenTarget;
  } catch (reason) {
    if (!String(reason).includes("core_api_unavailable")) throw reason;
  }
  return serviceCommand<NotificationOpenTarget>("open_notification_target", { notification_id: notificationId });
}

