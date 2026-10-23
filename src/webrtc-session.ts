import type { WebRTCBridge } from "./webrtc-onboarding";

export type WebRTCSessionPath = "direct" | "relayed" | "unknown";

export interface WebRTCSession {
  /** Stable per-peer/device key. Reconnect uses the profile ID. */
  key: string;
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

const sessions = new Map<string, WebRTCSession>();
let activeKey: string | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function subscribeWebRTCSessions(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function newestSession(): WebRTCSession | null {
  let newest: WebRTCSession | null = null;
  for (const session of sessions.values()) {
    if (!newest || session.createdAt >= newest.createdAt) newest = session;
  }
  return newest;
}

/**
 * Register one WebRTC transport without touching any other peer's transport.
 *
 * The service supports one Reticulum bridge per DataChannel, so the renderer
 * must preserve every live session. The most recently registered session is
 * exposed through getWebRTCSession() for legacy UI handlers.
 */
export function setWebRTCSession(session: WebRTCSession): void {
  sessions.set(session.key, session);
  activeKey = session.key;
  emit();
}

export function getWebRTCSession(): WebRTCSession | null {
  if (activeKey) {
    const active = sessions.get(activeKey);
    if (active) return active;
  }
  return newestSession();
}

export function getWebRTCSessionByKey(key: string): WebRTCSession | null {
  return sessions.get(key) ?? null;
}

export function getWebRTCSessions(): WebRTCSession[] {
  return [...sessions.values()];
}

export function getWebRTCSessionCount(): number {
  return sessions.size;
}

/** Find the newest session bound to a specific contact. */
export function getWebRTCSessionForContact(contactId: string): WebRTCSession | null {
  let found: WebRTCSession | null = null;
  for (const session of sessions.values()) {
    if (session.contactId === contactId) {
      if (!found || session.createdAt >= found.createdAt) found = session;
    }
  }
  return found;
}

/** Newest session that still has an open onboarding control channel. */
export function getWebRTCSessionWithControl(): WebRTCSession | null {
  let found: WebRTCSession | null = null;
  for (const session of sessions.values()) {
    if (!session.control || session.control.readyState !== "open") continue;
    if (!found || session.createdAt >= found.createdAt) found = session;
  }
  return found;
}

function target(key?: string): WebRTCSession | null {
  if (key) return sessions.get(key) ?? null;
  return getWebRTCSession();
}

export function updateWebRTCSessionPath(
  path: WebRTCSessionPath,
  key?: string,
): void {
  const session = target(key);
  if (session) session.path = path;
}

export function updateWebRTCSessionApprovalPending(
  pending: boolean,
  key?: string,
): void {
  const session = target(key);
  if (session) session.approvalPending = pending;
}

/**
 * Bind a live channel to a contact so capability messages cannot cross peers.
 *
 * When a key is not supplied, prefer the newest still-unbound session. This
 * preserves onboarding callers that bind after the invitation is reviewed,
 * without assigning a reconnect session that already has a contact.
 */
export function updateWebRTCSessionContact(
  contactId: string,
  key?: string,
): void {
  if (!contactId) return;
  let session = target(key);
  if (!session && !key) {
    for (const candidate of sessions.values()) {
      if (!candidate.contactId) {
        if (!session || candidate.createdAt >= session.createdAt) session = candidate;
      }
    }
  }
  if (session) session.contactId = contactId;
}

/** Remove one closed session without treating it as an active transport. */
export function removeWebRTCSession(key: string): void {
  const session = sessions.get(key);
  if (!session) return;
  sessions.delete(key);
  if (activeKey === key) activeKey = [...sessions.keys()].pop() ?? null;
  try { session.control?.close(); } catch { /* already closed */ }
  try { session.channel.close(); } catch { /* already closed */ }
  try { session.pc.close(); } catch { /* already closed */ }
  emit();
}

/**
 * Close one session by key, or every session when no key is supplied.
 *
 * Every transport is cleaned up even if one bridge close throws. A failed
 * bridge close must not leave the remaining peer connections attached.
 */
export async function closeWebRTCSession(key?: string): Promise<void> {
  const targets = key
    ? [sessions.get(key)].filter((session): session is WebRTCSession => Boolean(session))
    : [...sessions.values()];
  for (const session of targets) {
    sessions.delete(session.key);
    if (activeKey === session.key) {
      activeKey = [...sessions.keys()].pop() ?? null;
    }
    try {
      await session.bridge.close();
    } catch {
      // Continue closing the remaining transports.
    } finally {
      try { session.control?.close(); } catch { /* already closed */ }
      try { session.channel.close(); } catch { /* already closed */ }
      try { session.pc.close(); } catch { /* already closed */ }
    }
  }
  emit();
}
