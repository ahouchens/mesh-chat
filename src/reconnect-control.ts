import { serviceCommand } from "./api";
import { getWebRTCSession } from "./webrtc-session";

export const RECONNECT_CAPABILITIES_EVENT = "meshchat:reconnect-capabilities";

/**
 * Send a freshly signed capability document over the authenticated WebRTC
 * control channel.
 *
 * Consent changes require a new signed document, so this is best effort: when
 * the peer is not currently connected the caller must tell the user that the
 * change will be shared on the next live connection instead of pretending the
 * peer already knows.
 */
export function sendReconnectCapabilities(
  document: string,
  contactId?: string,
): boolean {
  if (!document) return false;
  const session = getWebRTCSession();
  const control = session?.control;
  if (!control || control.readyState !== "open") return false;
  // A capability is addressed to one contact. Refuse to send it over a channel
  // whose peer is unknown or is a different contact.
  if (contactId !== undefined && session?.contactId !== contactId) return false;
  control.send(JSON.stringify({ type: "connection_capabilities", document }));
  return true;
}

/** Store a peer capability received over the control channel. */
export async function storeReconnectCapabilities(document: string): Promise<void> {
  if (typeof document !== "string" || !document) return;
  await serviceCommand("reconnect_capabilities_store", { document });
  window.dispatchEvent(new CustomEvent(RECONNECT_CAPABILITIES_EVENT));
}
