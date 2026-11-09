import type { CoordinatorPeer } from "./reconnect-coordinator";
import type { CallIceConfiguration } from "./types";
import type { WebRTCSessionPath } from "./webrtc-session";
import { captureEffectScope, effectIsCurrent, ProfileRetiredError, type CoreEffectScope } from "./core-admission";
import {
  NATIVE_RECONNECT_CHANNELS,
  nativeWebRTCAccept,
  nativeWebRTCApplyAnswer,
  nativeWebRTCClose,
  nativeWebRTCStats,
  nativeWebRTCOffer,
} from "./native-webrtc";

const OPEN_POLL_MS = 250;
const DISCONNECTED_GRACE_MS = 10_000;

/**
 * Coordinator peer backed by the Android native WebRTC host.
 *
 * Python owns the Reticulum interface attached to the native DataChannel, so
 * this class never touches packets. It only requests SDP, applies the signed
 * answer, waits for the native attachment, and closes the session.
 */
export class NativeReconnectPeer implements CoordinatorPeer {
  readonly sessionId: string;
  private attached = false;
  private closed = false;
  private disconnectedSince: number | null = null;
  private unavailableSince: number | null = null;
  private readonly effects: CoreEffectScope;
  private readonly requests: CoreEffectScope;

  private constructor(
    readonly ice: CallIceConfiguration,
    readonly role: "offer" | "answer",
    readonly profileId?: string,
    effects?: CoreEffectScope,
  ) {
    this.effects = captureEffectScope(effects);
    this.requests = captureEffectScope({ ...this.effects, isCurrent: () => !this.closed && effectIsCurrent(this.effects) });
    this.sessionId = `reconnect-${role}-${crypto.randomUUID()}`;
  }

  static create(ice: CallIceConfiguration, role: "offer" | "answer", profileId?: string, effects?: CoreEffectScope): NativeReconnectPeer {
    return new NativeReconnectPeer(ice, role, profileId, effects);
  }

  async createOffer(): Promise<string> {
    const result = await nativeWebRTCOffer(
      this.sessionId,
      this.ice,
      NATIVE_RECONNECT_CHANNELS,
      this.profileId,
      this.requests,
    );
    return result.sdp;
  }

  async createAnswer(remoteOffer: string): Promise<string> {
    const result = await nativeWebRTCAccept(
      this.sessionId,
      remoteOffer,
      this.ice,
      NATIVE_RECONNECT_CHANNELS,
      this.profileId,
      this.requests,
    );
    return result.sdp;
  }

  async applyAnswer(remoteAnswer: string): Promise<void> {
    await nativeWebRTCApplyAnswer(this.sessionId, remoteAnswer, this.requests);
  }

  async open(timeoutMs = 20_000): Promise<unknown> {
    const deadline = Date.now() + timeoutMs;
    while (!this.closed) {
      if (!effectIsCurrent(this.effects)) { this.close(); throw new ProfileRetiredError(); }
      try {
        const stats = await nativeWebRTCStats(this.sessionId, this.requests);
        if (this.closed) break;
        if (!effectIsCurrent(this.effects)) { this.close(); throw new ProfileRetiredError(); }
        if (stats.attached && stats.data_channel_state === "open" && ["connected", "completed"].includes(stats.ice_connection_state ?? "")) {
          this.attached = true;
          return stats;
        }
      } catch (reason) {
        if (!effectIsCurrent(this.effects)) throw reason;
        // The native host or Python bridge may still be starting.
      }
      if (Date.now() >= deadline) {
        throw new Error("The native reconnect DataChannel did not attach.");
      }
      await new Promise((resolve) => window.setTimeout(resolve, OPEN_POLL_MS));
    }
    throw new Error("The native reconnect peer was closed.");
  }

  async path(): Promise<WebRTCSessionPath> {
    try {
      const stats = await nativeWebRTCStats(this.sessionId, this.requests);
      const state = stats.ice_connection_state;
      if (state === "connected" || state === "completed") return "unknown";
    } catch {
      // A missing session is unknown, not a reason to claim a route.
    }
    return "unknown";
  }

  isAttached(): boolean {
    return this.attached && !this.closed;
  }

  async refreshHealth(): Promise<void> {
    if (!this.isAttached()) return;
    try {
      const stats = await nativeWebRTCStats(this.sessionId, this.requests);
      if (this.closed || !effectIsCurrent(this.effects)) return;
      this.unavailableSince = null;
      if (!stats.attached || stats.data_channel_state !== "open" || ["failed", "closed"].includes(stats.ice_connection_state ?? "")) {
        this.close();
      } else if (stats.ice_connection_state === "disconnected") {
        this.disconnectedSince ??= Date.now();
        if (Date.now() - this.disconnectedSince >= DISCONNECTED_GRACE_MS) this.close();
      } else if (["connected", "completed"].includes(stats.ice_connection_state ?? "")) {
        this.disconnectedSince = null;
      } else {
        this.close();
      }
    } catch {
      this.unavailableSince ??= Date.now();
      if (Date.now() - this.unavailableSince >= DISCONNECTED_GRACE_MS) this.close();
    }
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.attached = false;
    void nativeWebRTCClose(this.sessionId, this.effects).catch(() => undefined);
  }
}
