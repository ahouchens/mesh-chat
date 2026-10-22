import type { CallIceConfiguration } from "./types";
import type { WebRTCSessionPath } from "./webrtc-session";

export type ReconnectState =
  | "idle"
  | "waiting_for_peer"
  | "probing"
  | "offer_pending"
  | "answer_pending"
  | "connecting"
  | "connected"
  | "retry_wait"
  | "peer_offline"
  | "manual_required"
  | "stopped";

export type ReconnectRole = "request" | "offer" | "answer";

export interface ReconnectEffective {
  ready: boolean;
  configured: boolean;
  preferred: boolean;
  session: string | null;
  mailbox_url: string | null;
  source: "local" | "remote" | null;
  reasons: string[];
}

export interface ReconnectProfile {
  id: string;
  contact_id: string;
  display_name?: string;
  destination_hash?: string;
  trust?: string;
  local_device_id: string;
  remote_device_id: string | null;
  auto_reconnect: boolean;
  allow_direct_ip_disclosure: boolean;
  relay_consent_scope: string;
  peer_auto_reconnect: boolean;
  peer_allow_direct_ip_disclosure: boolean;
  has_local_capabilities: boolean;
  has_peer_capabilities: boolean;
  capabilities_expires_at: number;
  peer_capabilities_expires_at: number;
  state: ReconnectState;
  active: boolean;
  last_attempt_at: number;
  last_error: string;
  updated_at: number;
  effective: ReconnectEffective;
}

export interface ReconnectProfilesPayload {
  local_device_id: string;
  local_destination?: string;
  mailbox_configured: boolean;
  profiles: ReconnectProfile[];
}

export interface ReconnectEntry {
  profileId: string;
  contactId: string;
  displayName: string;
  state: ReconnectState;
  detail: string;
  attempts: number;
  nextAttemptAt: number | null;
  path: WebRTCSessionPath | null;
  updatedAt: number;
}

export interface ReconnectSnapshot {
  running: boolean;
  entries: Record<string, ReconnectEntry>;
}

export interface CoordinatorPeer {
  createOffer(): Promise<string>;
  createAnswer(remoteOffer: string): Promise<string>;
  applyAnswer(remoteAnswer: string): Promise<void>;
  open(): Promise<unknown>;
  path(): Promise<WebRTCSessionPath>;
  close(): void;
}

export interface ReconnectCoordinatorDeps {
  profiles(): Promise<ReconnectProfilesPayload>;
  start(contactId: string): Promise<unknown>;
  stop(contactId?: string): Promise<unknown>;
  requestCreate(
    contactId: string,
    attemptId: string,
  ): Promise<{ document: string; expires_at: number }>;
  offerCreate(
    contactId: string,
    requestDocument: string,
    sdp: string,
    fingerprint: string,
  ): Promise<{ document: string; session_id: string; expires_at: number }>;
  answerCreate(
    contactId: string,
    offerDocument: string,
    sdp: string,
    fingerprint: string,
  ): Promise<{ document: string; expires_at: number }>;
  verifyRequest(document: string): Promise<{ contact_id: string; attempt_id: string }>;
  verifyOffer(document: string): Promise<{ sdp: string; attempt_id: string }>;
  verifyAnswer(
    document: string,
    offerDocument: string,
  ): Promise<{ sdp: string; attempt_id: string }>;
  publish(profileId: string, document: string, role: ReconnectRole): Promise<unknown>;
  fetch(
    profileId: string,
    role: ReconnectRole,
  ): Promise<{ document: string | null; pending: boolean }>;
  status(state: ReconnectState, detail?: string, attemptId?: string): Promise<unknown>;
  ice(profile: ReconnectProfile): Promise<CallIceConfiguration>;
  createPeer(ice: CallIceConfiguration, role: "offer" | "answer"): CoordinatorPeer;
  attach(peer: CoordinatorPeer, profile: ReconnectProfile): Promise<void>;
  pathStatus?(
    contactId: string,
  ): Promise<{ has_path: boolean; state: string; reason: string | null }>;
  /** True when a WebRTC transport is already attached; reconnect must not replace it. */
  hasSession?(): boolean;
  now?(): number;
  random?(): number;
  sleep?(ms: number): Promise<void>;
  fingerprint?(sdp: string): string;
}

export const BACKOFF_MS = [1000, 2000, 5000, 15000, 30000, 60000] as const;
export const MAX_ATTEMPTS = 20;
export const MAX_CONCURRENT = 2;
export const REQUEST_POLL_MS = 25000;
export const ANSWER_POLL_MS = 25000;
export const OPEN_TIMEOUT_MS = 30000;
export const PATH_TIMEOUT_MS = 10000;

export const RECONNECT_STATUS_LABELS: Record<ReconnectState, string> = {
  idle: "Not connected",
  waiting_for_peer: "Waiting for peer",
  probing: "Reconnecting…",
  offer_pending: "Waiting for peer",
  answer_pending: "Reconnecting…",
  connecting: "Connecting…",
  connected: "Connected",
  retry_wait: "Reconnecting shortly",
  peer_offline: "Peer offline",
  manual_required: "Manual reconnect required",
  stopped: "Auto-reconnect is off",
};

export function reconnectStatusLabel(entry: ReconnectEntry | undefined): string {
  if (!entry) return "Auto-reconnect is off";
  if (entry.state === "retry_wait" && entry.nextAttemptAt) {
    const seconds = Math.max(0, Math.ceil(entry.nextAttemptAt - Date.now() / 1000));
    return `Reconnecting in ${seconds}s`;
  }
  return RECONNECT_STATUS_LABELS[entry.state];
}

export function reconnectStatusDetail(entry: ReconnectEntry | undefined): string {
  if (!entry) return "";
  if (entry.state === "manual_required") {
    if (entry.detail === "mailbox_not_configured") {
      return "No signaling mailbox is configured on this device. Configure one or exchange a fresh link.";
    }
    return entry.detail || "A manual reconnect is required.";
  }
  if (entry.state === "peer_offline") return "The peer has not answered. They may be offline.";
  if (entry.state === "connected") {
    if (entry.detail) return entry.detail;
    return entry.path === "relayed"
      ? "Connected over the community relay."
      : entry.path === "direct"
        ? "Connected directly."
        : "Connected. Path details are still settling.";
  }
  if (entry.state === "retry_wait") return entry.detail || "Waiting before the next attempt.";
  if (entry.state === "waiting_for_peer") return entry.detail || "Waiting for the other device.";
  return entry.detail;
}

type Listener = () => void;

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function makeAttemptId(): string {
  const value =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  return value.replace(/[^A-Za-z0-9_-]/g, "-");
}

function errorCode(reason: unknown): string {
  if (reason && typeof reason === "object" && "code" in reason) {
    return String((reason as { code?: unknown }).code ?? "");
  }
  return "";
}

function safeMessage(reason: unknown): string {
  const code = errorCode(reason);
  if (code) return code;
  return reason instanceof Error ? reason.message.slice(0, 120) : "Reconnect attempt failed";
}

/**
 * Renderer-owned reconnect coordinator.
 *
 * The Python service owns trust, capabilities, signatures, replay state, and
 * mailbox I/O. This class owns only the lifecycle of fresh RTCPeerConnections
 * and never opens a dialog, steals focus, or asks for contact approval.
 *
 * Protocol shape (bound by the signed documents):
 *   preferred device  -> publishes a signed request
 *   other device      -> verifies it, creates the offer, publishes the offer
 *   preferred device  -> verifies the offer, creates the answer, publishes it
 *   other device      -> verifies the answer, applies it
 * Only the preferred device publishes a request, so one attempt yields one
 * offer: simultaneous starts cannot glare.
 */
export class ReconnectCoordinator {
  private readonly deps: ReconnectCoordinatorDeps;
  private readonly listeners = new Set<Listener>();
  private entries: Record<string, ReconnectEntry> = {};
  private running = false;
  private generation = 0;
  private peers = new Map<string, CoordinatorPeer>();
  private stoppedProfiles = new Set<string>();
  private active = false;

  constructor(deps: ReconnectCoordinatorDeps) {
    this.deps = deps;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): ReconnectSnapshot {
    return { running: this.running, entries: { ...this.entries } };
  }

  isActive(): boolean {
    return this.active;
  }

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.running = true;
    this.stoppedProfiles.clear();
    this.generation += 1;
    this.emit();
    void this.run(this.generation);
  }

  async refresh(): Promise<void> {
    try {
      const payload = await this.deps.profiles();
      this.reconcile(Array.isArray(payload?.profiles) ? payload.profiles : []);
    } catch {
      // A locked service is not an error; the next unlock restarts this.
    }
  }

  async stop(contactId?: string): Promise<void> {
    this.active = contactId === undefined ? false : this.active;
    if (contactId === undefined) {
      this.running = false;
      this.generation += 1;
    }
    this.closePeers(contactId);
    for (const entry of Object.values(this.entries)) {
      if (contactId && entry.contactId !== contactId) continue;
      this.stoppedProfiles.add(entry.profileId);
      entry.state = "stopped";
      entry.detail = "Stopped by you";
      entry.nextAttemptAt = null;
      entry.updatedAt = this.now();
    }
    this.emit();
    try {
      await this.deps.stop(contactId);
    } catch {
      // The state is already local; a failed status write is not fatal.
    }
  }

  async retryNow(contactId?: string): Promise<void> {
    this.generation += 1;
    this.closePeers();
    this.active = true;
    this.running = true;
    for (const entry of Object.values(this.entries)) {
      if (contactId && entry.contactId !== contactId) continue;
      this.stoppedProfiles.delete(entry.profileId);
      entry.state = "waiting_for_peer";
      entry.detail = "Retrying now";
      entry.attempts = 0;
      entry.nextAttemptAt = null;
      entry.updatedAt = this.now();
    }
    this.emit();
    void this.run(this.generation);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private now(): number {
    return Math.floor(this.clock() / 1000);
  }

  private clock(): number {
    return this.deps.now?.() ?? Date.now();
  }

  private random(): number {
    return this.deps.random?.() ?? Math.random();
  }

  private async wait(ms: number, generation: number): Promise<boolean> {
    if (!this.running || generation !== this.generation) return false;
    const sleep = this.deps.sleep ?? defaultSleep;
    await sleep(ms);
    return this.running && generation === this.generation;
  }

  private closePeers(contactId?: string): void {
    for (const [profileId, peer] of this.peers) {
      if (contactId && this.entries[profileId]?.contactId !== contactId) continue;
      try {
        peer.close();
      } catch {
        // A peer that already failed needs no cleanup.
      }
      this.peers.delete(profileId);
    }
  }

  private reconcile(profiles: ReconnectProfile[]): void {
    const next: Record<string, ReconnectEntry> = {};
    for (const profile of profiles) {
      const existing = this.entries[profile.id];
      next[profile.id] = existing ?? {
        profileId: profile.id,
        contactId: profile.contact_id,
        displayName: profile.display_name ?? "Contact",
        state: profile.state,
        detail: profile.last_error,
        attempts: 0,
        nextAttemptAt: null,
        path: null,
        updatedAt: profile.updated_at,
      };
      next[profile.id].contactId = profile.contact_id;
      next[profile.id].displayName = profile.display_name ?? next[profile.id].displayName;
    }
    this.entries = next;
    this.emit();
  }

  private setState(
    profile: ReconnectProfile,
    state: ReconnectState,
    detail = "",
    attemptId?: string,
  ): void {
    if (this.stoppedProfiles.has(profile.id) && state !== "stopped") {
      // A late await must not overwrite an explicit stop.
      return;
    }
    const entry = this.entries[profile.id] ?? {
      profileId: profile.id,
      contactId: profile.contact_id,
      displayName: profile.display_name ?? "Contact",
      state,
      detail,
      attempts: 0,
      nextAttemptAt: null,
      path: null,
      updatedAt: this.now(),
    };
    entry.state = state;
    entry.detail = detail;
    entry.updatedAt = this.now();
    if (state !== "retry_wait") entry.nextAttemptAt = null;
    this.entries[profile.id] = entry;
    this.emit();
    void this.deps.status(state, detail, attemptId).catch(() => undefined);
  }

  private isReady(profile: ReconnectProfile): boolean {
    return Boolean(profile.auto_reconnect && profile.peer_auto_reconnect);
  }

  private async run(generation: number): Promise<void> {
    if (this.deps.hasSession?.()) {
      // A live transport already exists. Automatic reconnect never replaces a
      // working session or migrates it in place.
      return;
    }
    const payload = await this.deps.profiles().catch(() => null);
    if (!payload || generation !== this.generation) return;
    if (!Array.isArray(payload.profiles)) return;
    this.reconcile(payload.profiles);
    const profiles = payload.profiles.filter((profile) => this.isReady(profile));
    if (profiles.length === 0) return;

    for (const profile of profiles) {
      if (!profile.effective.configured) {
        this.setState(profile, "manual_required", "mailbox_not_configured");
        continue;
      }
      if (!profile.effective.ready) {
        this.setState(
          profile,
          "manual_required",
          profile.effective.reasons.join(", "),
        );
        continue;
      }
      await this.deps.start(profile.contact_id).catch(() => undefined);
    }

    const queue = profiles.filter(
      (profile) => profile.effective.ready && profile.effective.configured,
    );
    const workers = Math.min(MAX_CONCURRENT, queue.length);
    let index = 0;
    const worker = async () => {
      while (generation === this.generation) {
        const position = index;
        index += 1;
        const profile = queue[position];
        if (!profile) return;
        if (profile.effective.preferred) {
          await this.runProber(profile, generation);
        } else {
          await this.runOfferer(profile, generation);
        }
      }
    };
    await Promise.all(
      Array.from({ length: workers }, () => worker()),
    );
  }

  private async poll(
    profile: ReconnectProfile,
    role: ReconnectRole,
    timeoutMs: number,
    generation: number,
    accept: (document: string) => Promise<boolean> = async () => true,
  ): Promise<string | null> {
    const deadline = this.clock() + timeoutMs;
    while (this.clock() < deadline) {
      if (!this.running || generation !== this.generation) return null;
      try {
        const fetched = await this.deps.fetch(profile.id, role);
        if (!fetched.pending && fetched.document && (await accept(fetched.document))) {
          return fetched.document;
        }
      } catch (reason) {
        if (errorCode(reason) === "mailbox_unauthorized") throw reason;
      }
      if (!(await this.wait(1000, generation))) return null;
    }
    return null;
  }

  private backoff(attempt: number): number {
    const base = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
    return Math.round(base * (0.8 + this.random() * 0.4));
  }

  private async afterOpen(
    peer: CoordinatorPeer,
    profile: ReconnectProfile,
    generation: number,
  ): Promise<{ path: WebRTCSessionPath; pathState: "ready" | "pending" | "unavailable" | "unknown" }> {
    this.setState(profile, "connecting", "Opening the DataChannel");
    await peer.open();
    await this.deps.attach(peer, profile);
    const path = await peer.path().catch(() => "unknown" as WebRTCSessionPath);
    const entry = this.entries[profile.id];
    if (entry) {
      entry.path = path;
      this.emit();
    }
    let pathState: "ready" | "pending" | "unavailable" | "unknown" = "unknown";
    if (this.deps.pathStatus) {
      // Attaching the bridge announces the interface; Reticulum may need a
      // moment to learn a path. Report the distinction instead of pretending
      // messaging is ready the instant the DataChannel opens.
      pathState = "pending";
      const deadline = this.clock() + PATH_TIMEOUT_MS;
      while (this.clock() < deadline && generation === this.generation) {
        try {
          const status = await this.deps.pathStatus(profile.contact_id);
          if (status.has_path) {
            pathState = "ready";
            break;
          }
          if (status.state === "network_unavailable") {
            pathState = "unavailable";
            break;
          }
        } catch {
          pathState = "unknown";
          break;
        }
        if (!(await this.wait(1000, generation))) break;
      }
    }
    return { path, pathState };
  }

  private connectedDetail(result: {
    pathState: "ready" | "pending" | "unavailable" | "unknown";
  }): string {
    switch (result.pathState) {
      case "ready":
        return "Fresh WebRTC transport attached; Reticulum path ready.";
      case "pending":
        return "Fresh WebRTC transport attached; waiting for a Reticulum path.";
      case "unavailable":
        return "Fresh WebRTC transport attached; Reticulum networking is unavailable.";
      default:
        return "Fresh WebRTC transport attached.";
    }
  }

  private async runProber(
    profile: ReconnectProfile,
    generation: number,
  ): Promise<void> {
    let attempt = 0;
    // One attempt id and one signed request are reused across retries. The
    // spec allows a request to be repeated; regenerating it on every retry
    // races the responder's offer and makes the two sides chase each other.
    let attemptId = makeAttemptId();
    let requestDocument = "";
    while (
      this.running &&
      generation === this.generation &&
      !this.stoppedProfiles.has(profile.id)
    ) {
      if (!this.isReady(profile)) return;
      this.setState(profile, "probing", "Publishing a signed reconnect request");
      let peer: CoordinatorPeer | null = null;
      try {
        // Authorization and consent are checked before any peer connection is
        // allocated: the signed request is created first, and the peer's offer
        // is verified before an RTCPeerConnection exists.
        if (!requestDocument) {
          requestDocument = (
            await this.deps.requestCreate(profile.contact_id, attemptId)
          ).document;
        }
        await this.deps.publish(profile.id, requestDocument, "request");
        let offer: { sdp: string; attempt_id: string } | null = null;
        const verifiedOffer: { value: { sdp: string; attempt_id: string } | null } = {
          value: null,
        };
        const offerDocument = await this.poll(
          profile,
          "offer",
          REQUEST_POLL_MS,
          generation,
          async (document) => {
            try {
              const verified = await this.deps.verifyOffer(document);
              if (verified.attempt_id !== attemptId) return false;
              verifiedOffer.value = verified;
              return true;
            } catch (reason) {
              if (
                ["mailbox_unauthorized", "contact_not_approved", "identity_mismatch"].includes(
                  errorCode(reason),
                )
              ) {
                throw reason;
              }
              return false;
            }
          },
        );
        offer = verifiedOffer.value;
        if (!offerDocument || !offer) {
          if (
            !this.running ||
            generation !== this.generation ||
            this.stoppedProfiles.has(profile.id)
          ) {
            return;
          }
          this.setState(profile, "waiting_for_peer", "The peer has not answered yet");
          throw new Error("offer_timeout");
        }
        const ice = await this.deps.ice(profile);
        peer = this.deps.createPeer(ice, "answer");
        this.peers.set(profile.id, peer);
        const sdp = await peer.createAnswer(offer.sdp);
        const answer = await this.deps.answerCreate(
          profile.contact_id,
          offerDocument,
          sdp,
          this.deps.fingerprint?.(sdp) ?? fingerprintOf(sdp),
        );
        await this.deps.publish(profile.id, answer.document, "answer");
        const attached = await this.afterOpen(peer, profile, generation);
        if (!this.running || generation !== this.generation) {
          peer.close();
          this.peers.delete(profile.id);
          return;
        }
        this.setState(profile, "connected", this.connectedDetail(attached));
        this.peers.delete(profile.id);
        // A connected profile keeps its transport until the user disconnects.
        return;
      } catch (reason) {
        peer?.close();
        this.peers.delete(profile.id);
        if (!this.running || generation !== this.generation) return;
        if (!this.isReady(profile)) {
          this.setState(profile, "manual_required", "consent_removed");
          return;
        }
        const code = errorCode(reason);
        if (
          ["mailbox_unauthorized", "contact_not_approved", "identity_mismatch", "reconnect_replayed"].includes(
            code,
          )
        ) {
          this.setState(profile, "manual_required", code);
          return;
        }
        if (code === "invalid_request") {
          // A rejected or expired request needs a fresh signature, not a
          // fresh peer connection.
          requestDocument = "";
          attemptId = makeAttemptId();
        }
        attempt += 1;
        const entry = this.entries[profile.id];
        if (entry) entry.attempts = attempt;
        if (attempt > MAX_ATTEMPTS) {
          this.setState(profile, "peer_offline", "No answer after repeated attempts");
          return;
        }
        const delay = code === "mailbox_rate_limited" ? 60000 : this.backoff(attempt - 1);
        if (entry) {
          entry.nextAttemptAt = this.now() + Math.ceil(delay / 1000);
          this.emit();
        }
        this.setState(profile, "retry_wait", safeMessage(reason));
        if (!(await this.wait(delay, generation))) return;
      }
    }
  }

  private async runOfferer(
    profile: ReconnectProfile,
    generation: number,
  ): Promise<void> {
    let attempt = 0;
    while (
      this.running &&
      generation === this.generation &&
      !this.stoppedProfiles.has(profile.id)
    ) {
      if (!this.isReady(profile)) return;
      this.setState(profile, "waiting_for_peer", "Waiting for a signed reconnect request");
      let requestDocument: string | null = null;
      try {
        requestDocument = await this.poll(
          profile,
          "request",
          REQUEST_POLL_MS,
          generation,
        );
      } catch (reason) {
        this.setState(profile, "manual_required", safeMessage(reason));
        return;
      }
      if (!requestDocument) {
        if (
          !this.running ||
          generation !== this.generation ||
          this.stoppedProfiles.has(profile.id)
        ) {
          return;
        }
        continue;
      }
      let peer: CoordinatorPeer | null = null;
      try {
        const verified = await this.deps.verifyRequest(requestDocument);
        if (verified.contact_id !== profile.contact_id) {
          // A request for another contact in this pair's mailbox is a protocol
          // error, not something to answer.
          this.setState(profile, "manual_required", "request_for_another_contact");
          return;
        }
        const ice = await this.deps.ice(profile);
        peer = this.deps.createPeer(ice, "offer");
        this.peers.set(profile.id, peer);
        const sdp = await peer.createOffer();
        const offer = await this.deps.offerCreate(
          profile.contact_id,
          requestDocument,
          sdp,
          this.deps.fingerprint?.(sdp) ?? fingerprintOf(sdp),
        );
        await this.deps.publish(profile.id, offer.document, "offer");
        this.setState(profile, "answer_pending", "Waiting for the answer");
        let answer: { sdp: string } | null = null;
        const verifiedAnswer: { value: { sdp: string } | null } = { value: null };
        const answerDocument = await this.poll(
          profile,
          "answer",
          ANSWER_POLL_MS,
          generation,
          async (document) => {
            try {
              const value = await this.deps.verifyAnswer(document, offer.document);
              verifiedAnswer.value = value;
              return true;
            } catch (reason) {
              if (
                ["mailbox_unauthorized", "contact_not_approved"].includes(
                  errorCode(reason),
                )
              ) {
                throw reason;
              }
              return false;
            }
          },
        );
        answer = verifiedAnswer.value;
        if (!answerDocument || !answer) {
          peer.close();
          this.peers.delete(profile.id);
          if (
            !this.running ||
            generation !== this.generation ||
            this.stoppedProfiles.has(profile.id)
          ) {
            return;
          }
          attempt += 1;
          if (attempt > MAX_ATTEMPTS) {
            this.setState(profile, "peer_offline", "The peer did not answer the offer");
            return;
          }
          this.setState(profile, "waiting_for_peer", "The peer did not answer the offer");
          continue;
        }
        await peer.applyAnswer(answer.sdp);
        const attached = await this.afterOpen(peer, profile, generation);
        if (!this.running || generation !== this.generation) {
          peer.close();
          this.peers.delete(profile.id);
          return;
        }
        this.setState(profile, "connected", this.connectedDetail(attached));
        this.peers.delete(profile.id);
        return;
      } catch (reason) {
        peer?.close();
        this.peers.delete(profile.id);
        if (!this.running || generation !== this.generation) return;
        const code = errorCode(reason);
        if (
          ["mailbox_unauthorized", "contact_not_approved", "identity_mismatch", "reconnect_replayed"].includes(
            code,
          )
        ) {
          this.setState(profile, "manual_required", code);
          return;
        }
        if (!this.isReady(profile)) {
          this.setState(profile, "manual_required", "consent_removed");
          return;
        }
        attempt += 1;
        if (attempt > MAX_ATTEMPTS) {
          this.setState(profile, "peer_offline", "No answer after repeated attempts");
          return;
        }
        const delay = code === "mailbox_rate_limited" ? 60000 : this.backoff(0);
        this.setState(profile, "retry_wait", safeMessage(reason));
        if (!(await this.wait(delay, generation))) return;
      }
    }
  }
}

function fingerprintOf(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) {
      return line.slice("a=fingerprint:".length).trim();
    }
  }
  throw new Error("The SDP has no DTLS fingerprint.");
}
