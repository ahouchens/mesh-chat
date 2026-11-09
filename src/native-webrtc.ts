import { captureEffectScope, effectIsCurrent, ProfileRetiredError, type CoreEffectScope } from "./core-admission";
import { requestEffect } from "./effect-requests";
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

type NativeRegistration = { readonly effects: CoreEffectScope };
const activeSessions = new Map<string, NativeRegistration>();
const pendingCreations = new Map<string, NativeRegistration>();

export function rememberNativeWebRTCSession(sessionId: string, effects?: CoreEffectScope): void {
  activeSessions.set(sessionId, { effects: captureEffectScope(effects) });
}

export function forgetNativeWebRTCSession(sessionId: string): void {
  activeSessions.delete(sessionId);
  pendingCreations.delete(sessionId);
}

/** Close every native session this WebView created, including onboarding. */
export async function closeNativeWebRTCSessions(): Promise<void> {
  const sessions = [...activeSessions.entries()];
  activeSessions.clear();
  pendingCreations.clear();
  await Promise.all(sessions.map(([sessionId, registration]) =>
    requestEffect(registration.effects, "native_webrtc_close", { session_id: sessionId }, true).catch(() => undefined)
  ));
}

async function createNativeSession(
  command: string,
  sessionId: string,
  payload: Record<string, unknown>,
  effects?: CoreEffectScope,
): Promise<NativeSdpResult> {
  const creation = { effects: captureEffectScope(effects) };
  pendingCreations.set(sessionId, creation);
  activeSessions.set(sessionId, creation);
  try {
    const result = await requestEffect<NativeSdpResult>(creation.effects, command, payload);
    if (pendingCreations.get(sessionId) !== creation) {
      // Cancellation may have closed the ID before the native host created it.
      if (!activeSessions.has(sessionId)) {
        await requestEffect(creation.effects, "native_webrtc_close", { session_id: sessionId }, true).catch(() => undefined);
      }
      throw new Error("Native WebRTC creation was cancelled.");
    }
    if (!effectIsCurrent(creation.effects)) throw new ProfileRetiredError();
    return result;
  } catch (reason) {
    if (pendingCreations.get(sessionId) === creation) {
      await nativeWebRTCClose(sessionId, creation.effects).catch(() => undefined);
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

/** Create an offer through the service's registered platform transport. */
export function nativeWebRTCOffer(
  sessionId: string,
  ice: CallIceConfiguration,
  channels: NativeChannelSpec[] = NATIVE_RECONNECT_CHANNELS,
  profileId?: string,
  effects?: CoreEffectScope,
): Promise<NativeSdpResult> {
  return createNativeSession("native_webrtc_offer", sessionId, {
    session_id: sessionId,
    ice: nativeIce(ice),
    channels,
    ...(profileId ? { profile_id: profileId } : {}),
  }, effects);
}

/** Accept an offer through the service's registered platform transport. */
export function nativeWebRTCAccept(
  sessionId: string,
  offerSdp: string,
  ice: CallIceConfiguration,
  channels: NativeChannelSpec[] = NATIVE_RECONNECT_CHANNELS,
  profileId?: string,
  effects?: CoreEffectScope,
): Promise<NativeSdpResult> {
  return createNativeSession("native_webrtc_accept", sessionId, {
    session_id: sessionId,
    offer_sdp: offerSdp,
    ice: nativeIce(ice),
    channels,
    ...(profileId ? { profile_id: profileId } : {}),
  }, effects);
}

export function nativeWebRTCApplyAnswer(sessionId: string, answerSdp: string, effects: CoreEffectScope = {}): Promise<unknown> {
  return requestEffect(effects, "native_webrtc_apply_answer", {
    session_id: sessionId,
    answer_sdp: answerSdp,
  });
}

export function nativeWebRTCControl(
  sessionId: string,
  label: "mesh-onboarding" | "meshchat-reconnect",
  text: string,
  effects: CoreEffectScope = {},
): Promise<{ accepted: boolean }> {
  return requestEffect<{ accepted: boolean }>(effects, "native_webrtc_control", {
    session_id: sessionId,
    label,
    text,
  });
}

export function nativeWebRTCStats(sessionId: string, effects: CoreEffectScope = {}): Promise<NativeWebRTCStats> {
  return requestEffect<NativeWebRTCStats>(effects, "native_webrtc_stats", { session_id: sessionId });
}

export function nativeWebRTCClose(sessionId: string, effects?: CoreEffectScope): Promise<unknown> {
  const origin = effects ?? activeSessions.get(sessionId)?.effects ?? {};
  forgetNativeWebRTCSession(sessionId);
  return requestEffect(origin, "native_webrtc_close", { session_id: sessionId }, true);
}

export function isNativeWebRTCPlatform(userAgent = navigator.userAgent): boolean {
  return /\bAndroid\b/i.test(userAgent);
}

/** Host-provided routing hint; it grants no authority to private host commands. */
export function usesServiceWebRTCTransport(userAgent = navigator.userAgent): boolean {
  return isNativeWebRTCPlatform(userAgent) || (typeof window !== "undefined" &&
    (window as unknown as { __MESH_SERVICE_TRANSPORT__?: boolean }).__MESH_SERVICE_TRANSPORT__ === true);
}
