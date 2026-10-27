import type { WebRTCBridge } from "./webrtc-onboarding";

export type WebRTCSessionPath = "direct" | "relayed" | "unknown";

export interface WebRTCSession {
  /** Stable per-peer/device key. Reconnect uses the profile ID. */
  key: string;
  bridge: WebRTCBridge;
  channel: RTCDataChannel;
  pc: RTCPeerConnection;
  control: RTCDataChannel | null;
  /** Reconnect control carries capabilities only, never onboarding actions. */
  controlPurpose?: "onboarding" | "reconnect";
  path: WebRTCSessionPath;
  createdAt: number;
  approvalPending: boolean;
  /** Contact approved on this channel, once known. Capability messages are contact-scoped. */
  contactId?: string;
  /** Peer identity verified against this transport's signed signaling. */
  peerDestination?: string;
}

const sessions = new Map<string, WebRTCSession>();
let activeKey: string | null = null;
const listeners = new Set<() => void>();
type SessionEvent = {
  time: number;
  event: "registered" | "removed" | "close_requested";
  channel: string;
  connection: string;
  ice: string;
};
const recentEvents: SessionEvent[] = [];

function recordSessionEvent(event: SessionEvent["event"], session: WebRTCSession): void {
  const state = (value: string, allowed: string[]) => allowed.includes(value) ? value : "unavailable";
  recentEvents.push({ time: Math.floor(Date.now() / 1000), event,
    channel: state(session.channel.readyState, ["connecting", "open", "closing", "closed"]),
    connection: state(session.pc.connectionState, ["new", "connecting", "connected", "disconnected", "failed", "closed"]),
    ice: state(session.pc.iceConnectionState, ["new", "checking", "connected", "completed", "disconnected", "failed", "closed"]),
  });
  if (recentEvents.length > 32) recentEvents.shift();
}

/** Keep retirement evidence after the live-session list becomes empty. */
export function recentWebRTCSessionEvents(): readonly SessionEvent[] {
  return recentEvents.map((event) => ({ ...event }));
}

export function clearWebRTCSessionEvents(): void { recentEvents.length = 0; }

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
  if (sessions.get(session.key) !== session) recordSessionEvent("registered", session);
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
    if (session.controlPurpose === "reconnect") continue;
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
export function removeWebRTCSession(key: string, bridgeId?: string): void {
  const session = sessions.get(key);
  if (!session || (bridgeId !== undefined && session.bridge.bridgeId !== bridgeId)) return;
  recordSessionEvent("removed", session);
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
    recordSessionEvent("close_requested", session);
    // Native detach can yield while another peer installs its replacement.
    // Retire only the session captured by this close operation.
    if (sessions.get(session.key) === session) {
      sessions.delete(session.key);
      if (activeKey === session.key) {
        activeKey = [...sessions.keys()].pop() ?? null;
      }
    }
    try { session.control?.close(); } catch { /* already closed */ }
    try { session.channel.close(); } catch { /* already closed */ }
    try { session.pc.close(); } catch { /* already closed */ }
  }
  // Lock must retire every transport before any slow native detach can yield.
  // Delayed capability tasks then see no registered session and cannot send.
  emit();
  await Promise.all(targets.map(async (session) => {
    try { await session.bridge.close(); }
    catch { /* Every renderer transport is already closed. */ }
  }));
}
