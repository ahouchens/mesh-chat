import type { WebRTCBridge } from "./webrtc-onboarding";

export type WebRTCSessionPath = "direct" | "relayed" | "unknown";

export interface WebRTCSession {
  bridge: WebRTCBridge;
  channel: RTCDataChannel;
  pc: RTCPeerConnection;
  control: RTCDataChannel | null;
  path: WebRTCSessionPath;
  createdAt: number;
  approvalPending: boolean;
  /** Contact approved on this channel, once known. Capability messages are contact-scoped. */
  contactId?: string;
}

let activeSession: WebRTCSession | null = null;

export function setWebRTCSession(session: WebRTCSession): void {
  if (activeSession && activeSession.bridge !== session.bridge) {
    void closeWebRTCSession();
  }
  activeSession = session;
}

export function updateWebRTCSessionPath(path: WebRTCSessionPath): void {
  if (activeSession) activeSession.path = path;
}

export function updateWebRTCSessionApprovalPending(pending: boolean): void {
  if (activeSession) activeSession.approvalPending = pending;
}

/** Bind the live channel to a contact so capability messages cannot cross peers. */
export function updateWebRTCSessionContact(contactId: string): void {
  if (activeSession && contactId) activeSession.contactId = contactId;
}

export function getWebRTCSession(): WebRTCSession | null {
  return activeSession;
}

export async function closeWebRTCSession(): Promise<void> {
  const session = activeSession;
  activeSession = null;
  if (!session) return;
  try {
    await session.bridge.close();
  } finally {
    session.control?.close();
    session.channel.close();
    session.pc.close();
  }
}
