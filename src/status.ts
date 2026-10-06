import type { Contact, DeliveryState } from "./types";

export const deliveryLabel: Record<DeliveryState, string> = {
  waiting_for_keys: "Getting ready to chat securely…",
  queued: "Saved on this device",
  sending: "Sending…",
  stored_for_delivery: "Saved for delivery when they reconnect",
  received_by_endpoint: "Received by their device",
  delivered: "Delivered",
  expired: "Expired",
  failed: "Needs attention",
};

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
