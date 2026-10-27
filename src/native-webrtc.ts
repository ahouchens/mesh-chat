import { serviceCommand } from "./api";
import type { CallIceConfiguration } from "./types";

export interface NativeIceServer {
  urls: string[];
  username?: string;
  credential?: string;
}

export interface NativeIceConfiguration {
  iceServers: NativeIceServer[];
  iceTransportPolicy: "all" | "relay";
}

export interface NativeChannelSpec {
  label: "mesh-reticulum" | "mesh-onboarding" | "meshchat-reconnect";
  binary: boolean;
  ordered: boolean;
}

export interface NativeSdpResult {
  ok: true;
  sdp: string;
  fingerprint: string;
}

export interface NativeWebRTCStats {
  ice_connection_state?: string;
  ice_gathering_state?: string;
  data_channel_state?: string;
  channels?: string[];
  attached?: boolean;
  session_id?: string;
}

export const NATIVE_RECONNECT_CHANNELS: NativeChannelSpec[] = [
  { label: "mesh-reticulum", binary: true, ordered: true },
  { label: "meshchat-reconnect", binary: false, ordered: true },
];

const activeSessions = new Set<string>();
const pendingCreations = new Map<string, object>();

export function rememberNativeWebRTCSession(sessionId: string): void {
  activeSessions.add(sessionId);
}

export function forgetNativeWebRTCSession(sessionId: string): void {
  activeSessions.delete(sessionId);
  pendingCreations.delete(sessionId);
}

/** Close every native session this WebView created, including onboarding. */
export async function closeNativeWebRTCSessions(): Promise<void> {
  const sessions = [...activeSessions];
  activeSessions.clear();
  pendingCreations.clear();
  await Promise.all(sessions.map((sessionId) =>
    serviceCommand("native_webrtc_close", { session_id: sessionId }).catch(() => undefined)
  ));
}

async function createNativeSession(
  command: string,
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<NativeSdpResult> {
  const creation = {};
  pendingCreations.set(sessionId, creation);
  rememberNativeWebRTCSession(sessionId);
  try {
    const result = await serviceCommand<NativeSdpResult>(command, payload);
    if (pendingCreations.get(sessionId) !== creation) {
      // Cancellation may have closed the ID before the native host created it.
      await serviceCommand("native_webrtc_close", { session_id: sessionId }).catch(() => undefined);
      throw new Error("Native WebRTC creation was cancelled.");
    }
    return result;
  } catch (reason) {
    if (pendingCreations.get(sessionId) === creation) {
      await nativeWebRTCClose(sessionId).catch(() => undefined);
    }
    throw reason;
  } finally {
    if (pendingCreations.get(sessionId) === creation) pendingCreations.delete(sessionId);
  }
}

function nativeIce(ice: CallIceConfiguration): NativeIceConfiguration {
  return {
    iceTransportPolicy: ice.iceTransportPolicy,
    iceServers: ice.iceServers.map((server) => ({
      urls: Array.isArray(server.urls) ? server.urls : [server.urls],
      ...(server.username ? { username: server.username } : {}),
      ...(server.credential ? { credential: server.credential } : {}),
    })),
  };
}

/** Android only: create an offer from the native peer, outside the WebView. */
export function nativeWebRTCOffer(
  sessionId: string,
  ice: CallIceConfiguration,
  channels: NativeChannelSpec[] = NATIVE_RECONNECT_CHANNELS,
  profileId?: string,
): Promise<NativeSdpResult> {
  return createNativeSession("native_webrtc_offer", sessionId, {
    session_id: sessionId,
    ice: nativeIce(ice),
    channels,
    ...(profileId ? { profile_id: profileId } : {}),
  });
}

/** Android only: accept a remote offer and produce the native answer SDP. */
export function nativeWebRTCAccept(
  sessionId: string,
  offerSdp: string,
  ice: CallIceConfiguration,
  channels: NativeChannelSpec[] = NATIVE_RECONNECT_CHANNELS,
  profileId?: string,
): Promise<NativeSdpResult> {
  return createNativeSession("native_webrtc_accept", sessionId, {
    session_id: sessionId,
    offer_sdp: offerSdp,
    ice: nativeIce(ice),
    channels,
    ...(profileId ? { profile_id: profileId } : {}),
  });
}

export function nativeWebRTCApplyAnswer(sessionId: string, answerSdp: string): Promise<unknown> {
  return serviceCommand("native_webrtc_apply_answer", {
    session_id: sessionId,
    answer_sdp: answerSdp,
  });
}

export function nativeWebRTCControl(
  sessionId: string,
  label: "mesh-onboarding" | "meshchat-reconnect",
  text: string,
): Promise<{ accepted: boolean }> {
  return serviceCommand<{ accepted: boolean }>("native_webrtc_control", {
    session_id: sessionId,
    label,
    text,
  });
}

export function nativeWebRTCStats(sessionId: string): Promise<NativeWebRTCStats> {
  return serviceCommand<NativeWebRTCStats>("native_webrtc_stats", { session_id: sessionId });
}

export function nativeWebRTCClose(sessionId: string): Promise<unknown> {
  forgetNativeWebRTCSession(sessionId);
  return serviceCommand("native_webrtc_close", { session_id: sessionId });
}

export function isNativeWebRTCPlatform(userAgent = navigator.userAgent): boolean {
  return /\bAndroid\b/i.test(userAgent);
}
