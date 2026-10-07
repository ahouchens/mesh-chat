import { invoke } from "@tauri-apps/api/core";
import { onBackButtonPress } from "@tauri-apps/api/app";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import type { Snapshot } from "./types";

export interface ServiceEvent {
  type: "event";
  event: "state_changed" | "message_status";
  message_id?: string;
  state?: string;
}

let platformPromise: Promise<"desktop" | "android" | "ios"> | null = null;

export function runtimePlatform(): Promise<"desktop" | "android" | "ios"> {
  platformPromise ??= invoke<"desktop" | "android" | "ios">("runtime_platform");
  return platformPromise;
}

export async function initializeService(displayName?: string): Promise<Snapshot> {
  return invoke<Snapshot>("initialize_service", { displayName: displayName ?? null });
}

export async function serviceCommand<T>(
  command: string,
  payload: Record<string, unknown> = {},
): Promise<T> {
  return invoke<T>("service_command", { command, payload });
}

export async function lockService(): Promise<void> {
  return invoke<void>("lock_service");
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
  const accept = (urls: string[] | null) => {
    const invitation = urls?.find((value) =>
      value.startsWith("meshchat://invite/") || value.startsWith("meshchat://workspace/"),
    );
    if (invitation) callback(invitation);
  };
  return Promise.all([
    listen<string>("mesh-chat://invitation", (event) => callback(event.payload)),
    onOpenUrl(accept),
    getCurrent().then(accept),
    invoke<string | null>("take_pending_invitation").then((value) => value && callback(value)),
  ]).then(([unlistenFile, unlistenLink]) => {
    return () => { unlistenFile(); unlistenLink(); };
  });
}
