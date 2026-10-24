import { serviceCommand } from "./api";
import type { CallIceConfiguration } from "./types";
import {
  ReconnectCoordinator,
  type CoordinatorPeer,
  type ReconnectCoordinatorDeps,
  type ReconnectProfile,
  type ReconnectProfilesPayload,
} from "./reconnect-coordinator";
import type { WebRTCSessionPath } from "./webrtc-session";
import { attachWebRTCBridge } from "./webrtc-onboarding";
import { ReconnectPeer, fingerprint } from "./webrtc-peer";
import { setWebRTCSession, getWebRTCSessions, closeWebRTCSession, removeWebRTCSession } from "./webrtc-session";

function hasLiveSession(profileId: string, contactId: string): boolean {
  return getWebRTCSessions().some((session) =>
    (session.key === profileId || session.contactId === contactId) &&
    session.channel.readyState === "open" &&
    session.pc.connectionState !== "closed" && session.pc.connectionState !== "failed",
  );
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
    profiles: () =>
      serviceCommand<ReconnectProfilesPayload>("reconnect_profiles"),
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
    createPeer: (ice, role) => ReconnectPeer.create(ice, role),
    attach: async (peer: CoordinatorPeer, profile: ReconnectProfile, isCurrent = () => true) => {
      const concrete = peer as ReconnectPeer;
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
          // Reconnect never carries an onboarding control channel and never
          // sets a pending contact approval.
          control: null,
          path,
          createdAt: Date.now(),
          approvalPending: false,
          contactId: profile.contact_id,
        });
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
    closeSession: (profileId) => closeWebRTCSession(profileId),
    fingerprint,
  };
}

/** Build the coordinator used by the app shell. */
export function createReconnectCoordinator(
  options: ReconnectRuntimeOptions,
): ReconnectCoordinator {
  return new ReconnectCoordinator(createReconnectDeps(options));
}
