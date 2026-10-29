import { serviceCommand } from "./api";
import type { CallIceConfiguration } from "./types";
import {
  ReconnectCoordinator,
  type CoordinatorPeer,
  type ReconnectCoordinatorDeps,
  type ReconnectProfile,
  type ReconnectProfilesPayload,
} from "./reconnect-coordinator";
import type { WebRTCSession, WebRTCSessionPath } from "./webrtc-session";
import { attachWebRTCBridge } from "./webrtc-onboarding";
import { ReconnectPeer, fingerprint } from "./webrtc-peer";
import { NativeReconnectPeer } from "./native-reconnect-peer";
import { isNativeWebRTCPlatform, nativeWebRTCStats, nativeWebRTCClose } from "./native-webrtc";
import { maintainReconnectCapabilities } from "./reconnect-control";
import { setWebRTCSession, getWebRTCSessions, getWebRTCSessionByKey, closeWebRTCSession, removeWebRTCSession } from "./webrtc-session";

export const DISCONNECTED_SESSION_GRACE_MS = 10_000;
const disconnectedSince = new WeakMap<WebRTCSession, number>();
const nativeSessions = new Map<string, { peer: NativeReconnectPeer; contactId: string }>();
type ServiceSession = { sessionId: string; contactId: string; disconnectedAt?: number; unavailableAt?: number };
const serviceSessions = new Map<string, ServiceSession>();
const serviceLookups = new Set<ServiceSession & { profileId: string }>();
let closeGeneration = 0;
let refreshGeneration = 0;
const contactCloseGenerations = new Map<string, number>();
const profileCloseGenerations = new Map<string, number>();

export function closeNativeReconnectSessions(contactId?: string): void {
  if (contactId) contactCloseGenerations.set(contactId, (contactCloseGenerations.get(contactId) ?? 0) + 1);
  else closeGeneration += 1;
  const closing = new Set<string>();
  for (const item of serviceLookups) {
    if (!contactId || item.contactId === contactId) closing.add(item.sessionId);
  }
  for (const [profileId, item] of serviceSessions) {
    if (contactId && item.contactId !== contactId) continue;
    serviceSessions.delete(profileId);
    closing.add(item.sessionId);
  }
  for (const [profileId, item] of nativeSessions) {
    if (contactId && item.contactId !== contactId) continue;
    nativeSessions.delete(profileId);
    item.peer.close();
  }
  for (const sessionId of closing) void nativeWebRTCClose(sessionId).catch(() => undefined);
}

function hasLiveSession(profileId: string, contactId: string): boolean {
  if (serviceSessions.get(profileId)?.contactId === contactId) return true;
  const native = nativeSessions.get(profileId);
  if (native && native.contactId === contactId) {
    if (native.peer.isAttached()) return true;
    nativeSessions.delete(profileId);
    native.peer.close();
  }
  return getWebRTCSessions().some((session) => {
    if (session.key !== profileId && session.contactId !== contactId) return false;
    const states = [session.pc.connectionState, session.pc.iceConnectionState];
    const terminated = session.channel.readyState !== "open" ||
      states.some((state) => state === "closed" || state === "failed");
    if (!terminated) {
      if (!states.includes("disconnected")) {
        disconnectedSince.delete(session);
        return true;
      }
      // SCTP can keep the DataChannel "open" after an Android network change
      // has lost its ICE route. Give temporary disconnects time to recover,
      // then let the supervisor negotiate a fresh transport.
      const now = Date.now();
      const since = disconnectedSince.get(session) ?? now;
      disconnectedSince.set(session, since);
      if (now - since < DISCONNECTED_SESSION_GRACE_MS) return true;
    }
    disconnectedSince.delete(session);
    // Retire the native Reticulum interface as well as the renderer session,
    // so cached paths cannot keep sending into the disconnected channel.
    void closeWebRTCSession(session.key);
    return false;
  });
}

export interface ReconnectRuntimeOptions {
  refresh: () => Promise<void>;
  onSession?: (path: WebRTCSessionPath) => void;
}

/**
 * Production dependencies for the renderer coordinator.
 *
 * Mailbox tokens and signatures never reach this module: every publish and
 * fetch is addressed by profile ID, and the service resolves the pair
 * capability server-side.
 */
export function createReconnectDeps(
  options: ReconnectRuntimeOptions,
): ReconnectCoordinatorDeps {
  return {
    profiles: async () => {
      const generation = ++refreshGeneration;
      const closing = closeGeneration;
      const contacts = new Map(contactCloseGenerations);
      const profiles = new Map(profileCloseGenerations);
      const current = (profile: ReconnectProfile) => closing === closeGeneration &&
        contacts.get(profile.contact_id) === contactCloseGenerations.get(profile.contact_id) &&
        profiles.get(profile.id) === profileCloseGenerations.get(profile.id);
      const payload = await serviceCommand<ReconnectProfilesPayload>("reconnect_profiles");
      const previous = new Map(serviceSessions);
      const next = new Map<string, ServiceSession>();
      await Promise.all(payload.profiles.map(async (profile) => {
        const sessionId = profile.native_session_id;
        if (!sessionId || nativeSessions.has(profile.id)) return;
        if (!current(profile)) {
          await nativeWebRTCClose(sessionId).catch(() => undefined);
          return;
        }
        const lookup = { profileId: profile.id, sessionId, contactId: profile.contact_id };
        serviceLookups.add(lookup);
        try {
          const stats = await nativeWebRTCStats(sessionId);
          if (!current(profile)) {
            await nativeWebRTCClose(sessionId).catch(() => undefined);
            return;
          }
          if (generation !== refreshGeneration) return;
          if (!stats.attached || !["connected", "completed", "disconnected"].includes(stats.ice_connection_state ?? "")) return;
          const old = previous.get(profile.id);
          const disconnectedAt = stats.ice_connection_state === "disconnected"
            ? (old?.sessionId === sessionId ? old.disconnectedAt : undefined) ?? Date.now() : undefined;
          if (disconnectedAt !== undefined && Date.now() - disconnectedAt >= DISCONNECTED_SESSION_GRACE_MS) {
            await nativeWebRTCClose(sessionId);
            return;
          }
          next.set(profile.id, { sessionId, contactId: profile.contact_id, disconnectedAt });
        } catch {
          const old = previous.get(profile.id);
          if (generation === refreshGeneration && current(profile) && old?.sessionId === sessionId) {
            const unavailableAt = old.unavailableAt ?? Date.now();
            if (Date.now() - unavailableAt < DISCONNECTED_SESSION_GRACE_MS) {
              next.set(profile.id, { ...old, unavailableAt });
            } else {
              await nativeWebRTCClose(sessionId).catch(() => undefined);
            }
          }
        } finally {
          serviceLookups.delete(lookup);
        }
      }));
      // Keep the live registry visible throughout asynchronous health checks.
      // Only the latest refresh may replace it, and closes fence late results.
      if (generation === refreshGeneration) {
        for (const [profileId, item] of serviceSessions) {
          const profile = payload.profiles.find((candidate) => candidate.id === profileId);
          if (!profile || current(profile)) serviceSessions.delete(profileId);
        }
        for (const profile of payload.profiles) {
          const item = next.get(profile.id);
          if (item && current(profile)) serviceSessions.set(profile.id, item);
        }
      }
      await Promise.all([...nativeSessions.values()].map(({ peer }) => peer.refreshHealth()));
      maintainReconnectCapabilities(payload.profiles);
      return payload;
    },
    start: (contactId) =>
      serviceCommand("reconnect_start", { contact_id: contactId }),
    stop: (contactId) =>
      serviceCommand(
        "reconnect_stop",
        contactId ? { contact_id: contactId } : {},
      ),
    requestCreate: (contactId, attemptId) =>
      serviceCommand("reconnect_request_create", {
        contact_id: contactId,
        attempt_id: attemptId,
      }),
    offerCreate: (contactId, requestDocument, sdp, dtlsFingerprint) =>
      serviceCommand("reconnect_offer_create", {
        contact_id: contactId,
        request_document: requestDocument,
        sdp,
        dtls_fingerprint: dtlsFingerprint,
      }),
    answerCreate: (contactId, offerDocument, sdp, dtlsFingerprint) =>
      serviceCommand("reconnect_answer_create", {
        contact_id: contactId,
        offer_document: offerDocument,
        sdp,
        dtls_fingerprint: dtlsFingerprint,
      }),
    verifyRequest: (document, profileId) =>
      serviceCommand("verify_reconnect_request", { document, profile_id: profileId }),
    verifyOffer: (document, profileId) =>
      serviceCommand("verify_reconnect_offer", { document, profile_id: profileId }),
    verifyAnswer: (document, offerDocument, profileId) =>
      serviceCommand("verify_reconnect_answer", {
        document,
        offer_document: offerDocument,
        profile_id: profileId,
      }),
    publish: (profileId, document, role) =>
      serviceCommand("reconnect_publish", {
        profile_id: profileId,
        document,
        role,
      }),
    fetch: (profileId, role) =>
      serviceCommand("reconnect_fetch", { profile_id: profileId, role }),
    status: (state, detail, attemptId) =>
      serviceCommand("reconnect_status", {
        state,
        ...(detail ? { detail } : {}),
        ...(attemptId ? { attempt_id: attemptId } : {}),
      }),
    ice: async (profile) => {
      const configuration = await serviceCommand<CallIceConfiguration>(
        "call_ice_servers",
      );
      if (
        !profile.allow_direct_ip_disclosure &&
        configuration.iceTransportPolicy !== "relay"
      ) {
        // Direct host/srflx candidates reveal IP addresses. Without the
        // separate disclosure consent, only relay candidates are offered.
        return { ...configuration, iceTransportPolicy: "relay" };
      }
      return configuration;
    },
    createPeer: (ice, role, profile) => isNativeWebRTCPlatform()
      ? NativeReconnectPeer.create(ice, role, profile?.id)
      : ReconnectPeer.create(ice, role),
    attach: async (peer: CoordinatorPeer, profile: ReconnectProfile, isCurrent = () => true) => {
      if (peer instanceof NativeReconnectPeer) {
        try {
          if (!isCurrent()) throw new Error("Reconnect attachment was cancelled.");
          await peer.open();
          if (!isCurrent()) {
            peer.close();
            throw new Error("Reconnect attachment was cancelled.");
          }
          nativeSessions.set(profile.id, { peer, contactId: profile.contact_id });
          const path = await peer.path();
          if (!isCurrent() || !peer.isAttached() || nativeSessions.get(profile.id)?.peer !== peer) {
            throw new Error("Reconnect attachment was cancelled.");
          }
          options.onSession?.(path);
          return;
        } catch (reason) {
          if (nativeSessions.get(profile.id)?.peer === peer) nativeSessions.delete(profile.id);
          peer.close();
          throw reason;
        }
      }
      const concrete = peer as ReconnectPeer;
      concrete.onControl = (control) => {
        const update = () => {
          const session = getWebRTCSessionByKey(profile.id);
          if (session?.pc !== concrete.pc) return;
          session.control = control;
          maintainReconnectCapabilities();
        };
        control.addEventListener("open", update, { once: true });
        update();
      };
      let bridge: Awaited<ReturnType<typeof attachWebRTCBridge>> | null = null;
      const check = (channel?: RTCDataChannel) => {
        if (!isCurrent() || (channel && channel.readyState !== "open") ||
            hasLiveSession(profile.id, profile.contact_id)) {
          throw new Error("Reconnect attachment was cancelled or superseded.");
        }
      };
      try {
        check();
        const channel = await concrete.open();
        check(channel);
        bridge = await attachWebRTCBridge(channel, {
          isCurrent: () => {
            // After negotiation finishes, the coordinator retires its attempt.
            // Bridge supervision belongs to the registered transport instead.
            const registered = getWebRTCSessionByKey(profile.id);
            return registered ? registered.pc === concrete.pc && registered.bridge === bridge : isCurrent();
          },
          peerDestination: () => profile.destination_hash,
          onClosed: (bridgeId) => removeWebRTCSession(profile.id, bridgeId),
        });
        check(channel);
        const path = await concrete.path();
        check(channel);
        setWebRTCSession({
          key: profile.id,
          bridge,
          channel,
          pc: concrete.pc,
          // This control channel only renews signed reconnect capabilities;
          // it cannot accept invitations or approve contacts.
          control: concrete.control,
          controlPurpose: "reconnect",
          path,
          createdAt: Date.now(),
          approvalPending: false,
          contactId: profile.contact_id,
          peerDestination: profile.destination_hash,
        });
        maintainReconnectCapabilities();
        options.onSession?.(path);
        try {
          await options.refresh();
        } catch {
          // A failed snapshot refresh is not a transport failure.
        }
        if (!isCurrent() || channel.readyState !== "open") {
          throw new Error("Reconnect attachment was cancelled or closed.");
        }
      } catch (reason) {
        try { await bridge?.close(); }
        finally {
          if (bridge) removeWebRTCSession(profile.id, bridge.bridgeId);
          concrete.pc.close();
        }
        throw reason;
      }
    },
    pathStatus: (contactId) =>
      serviceCommand("reconnect_path_status", { contact_id: contactId }),
    hasSession: hasLiveSession,
    closeSession: async (profileId) => {
      profileCloseGenerations.set(profileId, (profileCloseGenerations.get(profileId) ?? 0) + 1);
      const closing = new Set([...serviceLookups].filter((item) => item.profileId === profileId).map((item) => item.sessionId));
      const serviceSession = serviceSessions.get(profileId);
      if (serviceSession) {
        serviceSessions.delete(profileId);
        closing.add(serviceSession.sessionId);
      }
      const native = nativeSessions.get(profileId);
      if (native) {
        nativeSessions.delete(profileId);
        native.peer.close();
      }
      await Promise.all([...closing].map((sessionId) => nativeWebRTCClose(sessionId).catch(() => undefined)));
      await closeWebRTCSession(profileId);
    },
    fingerprint,
  };
}

/** Build the coordinator used by the app shell. */
export function createReconnectCoordinator(
  options: ReconnectRuntimeOptions,
): ReconnectCoordinator {
  return new ReconnectCoordinator(createReconnectDeps(options));
}
