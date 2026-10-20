import type { WebRTCBridge } from "./webrtc-onboarding";

export interface WebRTCSession {
  bridge: WebRTCBridge;
  channel: RTCDataChannel;
  pc: RTCPeerConnection;
}

let activeSession: WebRTCSession | null = null;

export function setWebRTCSession(session: WebRTCSession): void {
  if (activeSession && activeSession !== session) {
    void closeWebRTCSession();
  }
  activeSession = session;
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
    session.channel.close();
    session.pc.close();
  }
}
