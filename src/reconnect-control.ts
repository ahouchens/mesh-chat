import { serviceCommand } from "./api";
import { getWebRTCSession, getWebRTCSessions, type WebRTCSession } from "./webrtc-session";

export const RECONNECT_CAPABILITIES_EVENT = "meshchat:reconnect-capabilities";
export const CAPABILITY_REFRESH_MS = 60 * 60 * 1000;
const CAPABILITY_RETRY_MS = 60_000;
const MAX_CAPABILITY_LENGTH = 16_384;

export interface StoredReconnectCapabilities {
  profile?: { contact_id?: string } | null;
  pending?: boolean;
}

interface ControlState {
  contactId: string;
  lastSent: string;
  nextRefreshAt: number;
  refreshing: boolean;
  receiving: boolean;
  pendingDocument: string | null;
  lastReceived: string;
  requested: boolean;
}

const controls = new WeakMap<RTCDataChannel, ControlState>();

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
  const session = contactId !== undefined
    ? getWebRTCSessions().filter((item) => item.contactId === contactId && item.control?.readyState === "open")
      .sort((a, b) => b.createdAt - a.createdAt)[0]
    : getWebRTCSession();
  const control = session?.control;
  if (!control || control.readyState !== "open") return false;
  // A capability is addressed to one contact. Refuse to send it over a channel
  // whose peer is unknown or is a different contact.
  if (contactId !== undefined && session?.contactId !== contactId) return false;
  try {
    control.send(JSON.stringify({ type: "connection_capabilities", document }));
    const state = controls.get(control);
    if (state) state.lastSent = document;
    return true;
  } catch {
    return false;
  }
}

/** Store a peer capability received over the control channel. */
export async function storeReconnectCapabilities(document: string, expectedContactId?: string, expectedPeerDestination?: string): Promise<StoredReconnectCapabilities | undefined> {
  if (typeof document !== "string" || !document) return;
  const result = await serviceCommand<StoredReconnectCapabilities>("reconnect_capabilities_store", {
    document,
    ...(expectedContactId ? { expected_contact_id: expectedContactId } : {}),
    ...(expectedPeerDestination ? { expected_peer_destination: expectedPeerDestination } : {}),
  });
  window.dispatchEvent(new CustomEvent(RECONNECT_CAPABILITIES_EVENT));
  return result;
}

/** Called by foreground supervision; no independent timers survive lock/stop. */
export function maintainReconnectCapabilities(): void {
  for (const session of getWebRTCSessions()) {
    const control = session.control;
    const contactId = session.contactId;
    // Workspace capabilities have a separate signed authority wrapper.
    if (!control || control.readyState !== "open" || !contactId || contactId.startsWith("workspace:")) continue;
    let state = controls.get(control);
    if (!state || state.contactId !== contactId) {
      state = { contactId, lastSent: "", nextRefreshAt: 0, refreshing: false, receiving: false, pendingDocument: null, lastReceived: "", requested: false };
      controls.set(control, state);
      if (session.controlPurpose === "reconnect") {
        const currentState = state;
        control.onmessage = (event) => {
          if (typeof event.data !== "string" || event.data.length > MAX_CAPABILITY_LENGTH) return;
          try {
            const message = JSON.parse(event.data) as { type?: unknown; document?: unknown };
            if (message?.type === "connection_capabilities_request" && !currentState.requested) {
              currentState.requested = true;
              currentState.lastSent = "";
              currentState.nextRefreshAt = 0;
              if (!currentState.refreshing) void refreshCapabilities(session, control, currentState);
              return;
            }
            if (message?.type !== "connection_capabilities" || typeof message.document !== "string" ||
                !message.document || message.document.length > MAX_CAPABILITY_LENGTH || message.document === currentState.lastReceived) return;
            // One native verification at a time and one bounded queued update.
            currentState.pendingDocument = message.document;
            void receiveCapabilities(session, control, currentState);
          } catch {
            // A reconnect control channel carries no invitation or approval actions.
          }
        };
        // One side can attach its native bridge after the other already sent
        // its document. Request a fresh copy once our receiver is installed.
        try { control.send(JSON.stringify({ type: "connection_capabilities_request" })); } catch { /* Closing. */ }
      }
    }
    if (!state.refreshing && state.nextRefreshAt <= Date.now()) {
      void refreshCapabilities(session, control, state);
    }
  }
}

function controlIsCurrent(session: WebRTCSession, control: RTCDataChannel, state: ControlState): boolean {
  return control.readyState === "open" && session.control === control &&
    session.contactId === state.contactId && controls.get(control) === state &&
    getWebRTCSessions().includes(session);
}

async function receiveCapabilities(session: WebRTCSession, control: RTCDataChannel, state: ControlState): Promise<void> {
  if (state.receiving) return;
  state.receiving = true;
  try {
    while (state.pendingDocument && controlIsCurrent(session, control, state)) {
      const document = state.pendingDocument;
      state.pendingDocument = null;
      try {
        await storeReconnectCapabilities(document, state.contactId);
        state.lastReceived = document;
      } catch {
        // Invalid, expired, blocked, or wrong-peer documents never change trust.
      }
    }
  } finally {
    state.receiving = false;
  }
}

async function refreshCapabilities(session: WebRTCSession, control: RTCDataChannel, state: ControlState): Promise<void> {
  state.refreshing = true;
  state.nextRefreshAt = Date.now() + CAPABILITY_RETRY_MS;
  try {
    const result = await serviceCommand<{ local_capabilities?: string | null }>("reconnect_capabilities_get", { contact_id: state.contactId });
    if (!controlIsCurrent(session, control, state)) return;
    const document = result.local_capabilities;
    if (typeof document === "string" && document && document.length <= MAX_CAPABILITY_LENGTH && document !== state.lastSent) {
      control.send(JSON.stringify({ type: "connection_capabilities", document }));
      state.lastSent = document;
    }
    state.nextRefreshAt = Date.now() + CAPABILITY_REFRESH_MS;
  } catch {
    // Service startup and pending approval are retried without changing consent.
  } finally {
    state.refreshing = false;
  }
}
