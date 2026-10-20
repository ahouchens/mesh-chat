import { invoke } from "@tauri-apps/api/core";
import { onBackButtonPress } from "@tauri-apps/api/app";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import type { NotificationCapability, Snapshot } from "./types";

export interface ServiceEvent {
  type: "event";
  event: "state_changed" | "message_status" | "workspace_changed";
  message_id?: string;
  state?: string;
  workspace_id?: string;
  conversation_id?: string | null;
  resource_kind?: string;
  generation?: number;
  overflow?: boolean;
}

let platformPromise: Promise<"desktop" | "android" | "ios"> | null = null;

export class ServiceCommandError extends Error {
  code: string;
  details?: Record<string, string>;

  constructor(code: string, details?: Record<string, string>) {
    super(code);
    this.name = "ServiceCommandError";
    this.code = code;
    this.details = details;
  }
}

function normalizedServiceError(reason: unknown): ServiceCommandError {
  const text = String(reason);
  try {
    const parsed = JSON.parse(text) as { code?: unknown; details?: unknown };
    if (typeof parsed.code === "string") {
      const details = parsed.details && typeof parsed.details === "object"
        ? Object.fromEntries(Object.entries(parsed.details).filter(
          (entry): entry is [string, string] => typeof entry[1] === "string",
        ))
        : undefined;
      return new ServiceCommandError(parsed.code, details);
    }
  } catch {
    // Existing sidecars return a plain allowlisted error code.
  }
  return new ServiceCommandError(text);
}

export function runtimePlatform(): Promise<"desktop" | "android" | "ios"> {
  platformPromise ??= invoke<"desktop" | "android" | "ios">("runtime_platform");
  return platformPromise;
}

export function appBuildInfo(): Promise<unknown> {
  return invoke("app_build_info");
}

export function setNativeTheme(theme: "dark" | "light"): Promise<void> {
  return invoke<void>("set_native_theme", { theme });
}

export async function initializeService(displayName?: string): Promise<Snapshot> {
  return invoke<Snapshot>("initialize_service", { displayName: displayName ?? null });
}

export async function serviceCommand<T>(
  command: string,
  payload: Record<string, unknown> = {},
): Promise<T> {
  try {
    return await invoke<T>("service_command", { command, payload });
  } catch (reason) {
    throw normalizedServiceError(reason);
  }
}

export async function lockService(): Promise<void> {
  return invoke<void>("lock_service");
}

export function notificationCapability(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("notification_capability");
}

export function requestNotificationPermission(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("request_notification_permission");
}

export function requestMediaPermission(): Promise<{ audio: boolean; camera: boolean }> {
  return invoke<{ audio: boolean; camera: boolean }>("request_media_permission");
}

export function openNotificationSettings(): Promise<NotificationCapability> {
  return invoke<NotificationCapability>("open_notification_settings");
}

/**
 * Open Android's document picker and return a native-validated Mesh Chat
 * invitation. Cancellation resolves to null; validation and provider failures
 * reject with a stable invitation_file_* error code.
 */
export async function pickInvitationFile(): Promise<string | null> {
  try {
    return await invoke<string | null>("pick_invitation_file");
  } catch (reason) {
    throw normalizedServiceError(reason);
  }
}

/**
 * Temporarily take ownership of Android's system back action.
 *
 * Callers should only keep this listener mounted while they have an in-app
 * layer to dismiss. Once it is removed, Tauri resumes the platform default so
 * Back at the conversation list can leave the app normally.
 */
export async function onMobileBackButton(callback: () => void): Promise<UnlistenFn> {
  if (await runtimePlatform() !== "android") return () => undefined;
  const listener = await onBackButtonPress(callback);
  return () => { void listener.unregister(); };
}

export function onServiceEvent(callback: (event: ServiceEvent) => void): Promise<UnlistenFn> {
  return Promise.all([
    listen<ServiceEvent>("mesh-chat://service-event", (event) => callback(event.payload)),
    runtimePlatform(),
  ]).then(([unlisten, platform]) => {
    if (platform === "desktop") return unlisten;
    let active = true;
    let polling = false;
    const poll = async () => {
      if (!active || polling || document.visibilityState === "hidden") return;
      polling = true;
      try {
        const events = await invoke<ServiceEvent[]>("poll_mobile_events");
        events.forEach(callback);
      } catch {
        // Initialization and lock transitions can briefly leave no service.
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 750);
    const visibility = () => { if (document.visibilityState === "visible") void poll(); };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
      unlisten();
    };
  });
}

export function onInvitation(callback: (invitation: string) => void): Promise<UnlistenFn> {
  const delivered = new Set<string>();
  const deliver = (invitation: string | null | undefined) => {
    if (!invitation || delivered.has(invitation)) return;
    callback(invitation);
    delivered.add(invitation);
  };
  const accept = (urls: string[] | null) => {
    const invitation = urls?.find((value) =>
      value.startsWith("meshchat://invite/") || value.startsWith("meshchat://workspace/") || value.startsWith("meshchat://workspace-device/") || value.startsWith("meshchat://connect/") || value.startsWith("meshchat://route/"),
    );
    deliver(invitation);
  };
  return runtimePlatform().then(async (platform) => {
    if (platform === "android") {
      let active = true;
      let polling = false;
      const poll = async () => {
        if (!active || polling || document.visibilityState === "hidden") return;
        polling = true;
        try { deliver(await invoke<string | null>("take_pending_invitation")); }
        catch { /* A delayed native runtime or lock transition is retried. */ }
        finally { polling = false; }
      };
      await poll();
      const timer = window.setInterval(() => void poll(), 750);
      const visible = () => { if (document.visibilityState === "visible") void poll(); };
      const focused = () => void poll();
      document.addEventListener("visibilitychange", visible);
      window.addEventListener("focus", focused);
      return () => {
        active = false;
        window.clearInterval(timer);
        document.removeEventListener("visibilitychange", visible);
        window.removeEventListener("focus", focused);
      };
    }

    const [unlistenFile, unlistenLink] = await Promise.all([
      listen<string>("mesh-chat://invitation", (event) => deliver(event.payload)),
      onOpenUrl(accept),
      getCurrent().then(accept),
      invoke<string | null>("take_pending_invitation").then(deliver),
    ]);
    return () => { unlistenFile(); unlistenLink(); };
  });
}

export function onNotificationOpen(callback: (notificationId: string) => void): Promise<UnlistenFn> {
  const accept = (urls: string[] | null) => {
    for (const value of urls ?? []) {
      const match = /^meshchat:\/\/notification\/([0-9a-f]{64})$/.exec(value);
      if (match) callback(match[1]);
    }
  };
  return Promise.all([
    onOpenUrl(accept),
    getCurrent().then(accept),
  ]).then(([unlisten]) => () => unlisten());
}
