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
import { isNativeWebRTCPlatform } from "./native-webrtc";
import { maintainReconnectCapabilities } from "./reconnect-control";
import { setWebRTCSession, getWebRTCSessions, getWebRTCSessionByKey, closeWebRTCSession, removeWebRTCSession } from "./webrtc-session";

export const DISCONNECTED_SESSION_GRACE_MS = 10_000;
const disconnectedSince = new WeakMap<WebRTCSession, number>();
const nativeSessions = new Map<string, { peer: NativeReconnectPeer; contactId: string }>();

export function closeNativeReconnectSessions(contactId?: string): void {
  for (const [profileId, item] of nativeSessions) {
    if (contactId && item.contactId !== contactId) continue;
    nativeSessions.delete(profileId);
    item.peer.close();
  }
}

function hasLiveSession(profileId: string, contactId: string): boolean {
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
      const payload = await serviceCommand<ReconnectProfilesPayload>("reconnect_profiles");
      maintainReconnectCapabilities();
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
    createPeer: (ice, role) => isNativeWebRTCPlatform()
      ? NativeReconnectPeer.create(ice, role)
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
          options.onSession?.(await peer.path());
          return;
        } catch (reason) {
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
          isCurrent,
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
      const native = nativeSessions.get(profileId);
      if (native) {
        nativeSessions.delete(profileId);
        native.peer.close();
      }
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
