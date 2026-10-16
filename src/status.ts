import type { Contact, DeliveryState, Workspace } from "./types";

export const deliveryLabel: Record<DeliveryState, string> = {
  waiting_for_keys: "Getting ready to chat securely…",
  queued: "Saved on this device",
  sending: "Sending…",
  stored_for_delivery: "Saved for delivery when they reconnect",
  received_by_endpoint: "Received by their device",
  delivered: "Delivered",
  expired: "Expired",
  failed: "Needs attention",
  cancelled: "Cancelled",
};

export interface WorkspaceJoinStatus {
  headline: string;
  detail: string;
  ownerReached: boolean;
  terminal: boolean;
}

export function workspaceJoinStatus(
  workspace: Pick<Workspace, "state" | "join_delivery_state" | "join_acknowledged">,
): WorkspaceJoinStatus | null {
  if (workspace.state !== "joining") return null;
  if (workspace.join_acknowledged === true) {
    return {
      headline: "Request received — waiting for approval",
      detail: "The owner app validated and saved this exact request. Workspace membership begins only after the owner approves it.",
      ownerReached: true,
      terminal: false,
    };
  }
  if (
    workspace.join_delivery_state === "received_by_endpoint"
    || workspace.join_delivery_state === "delivered"
  ) {
    return {
      headline: "Request reached owner’s device · awaiting validation",
      detail: "Transport reached the owner device. The owner app must still validate the invitation and request before it can show an approval prompt.",
      ownerReached: true,
      terminal: false,
    };
  }
  if (
    workspace.join_delivery_state === "failed"
    || workspace.join_delivery_state === "expired"
    || workspace.join_delivery_state === "cancelled"
  ) {
    return {
      headline: "Join request needs attention",
      detail: "Delivery stopped without confirmation from the owner app. Open Workspace settings to remove this failed join, then use a fresh invitation.",
      ownerReached: false,
      terminal: true,
    };
  }
  return {
    headline: "Join request saved · trying to reach owner",
    detail: "The owner app has not confirmed receipt. Keep both apps open. Mesh Chat will retry automatically when a route becomes available.",
    ownerReached: false,
    terminal: false,
  };
}

export function contactConnectionLabel(contact: Contact): string {
  switch (contact.trust) {
    case "awaiting_consent":
      return contact.request_state === "received_by_endpoint" || contact.request_state === "delivered"
        ? `Request reached ${contact.display_name}’s device. Waiting for acceptance.`
        : `Trying to reach ${contact.display_name}. Keep both apps open on the same local network.`;
    case "pending_request":
      return `${contact.display_name} would like to connect.`;
    case "identity_changed":
      return "Their security identity changed. Review before continuing.";
    case "blocked":
      return "This person is blocked.";
    default:
      return `Connecting to ${contact.display_name}…`;
  }
}
